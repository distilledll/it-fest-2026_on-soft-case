"""Быстрый агент отвечает первым. Его отказ перепроверяет полный проход TrustQA."""
from dataclasses import replace
from functools import partial

from anyio import to_thread
from anyio.from_thread import BlockingPortal
from openai import OpenAIError

from app import retrieval
from app.config import settings
from app.ingest import norm, redact
from app.pipeline.base import Context, Pipeline, collect
from app.schemas import Answer, Document, Evidence, Question, Status, TraceStep
from app.verify import guard, moscow_deadline
from trustqa.api import CallLimit, Jina, Qwen, ServiceUnavailable
from trustqa.config import Config
from trustqa.context import Window
from trustqa.documents import Package, parse_amendments
from trustqa.engine import Engine
from trustqa.retrieval import Retriever
from trustqa.transport import post_json


def fallback_config(ctx: Context, defaults: Config):
    """Модели и параметры берутся из снимка ролей текущего запроса."""
    config = replace(defaults, cache_dir=str(settings.storage_dir / "trustqa-cache"))
    profiles = {}
    answer = ctx.models.get("answer")
    bootstrap = (answer is not None and answer._from_env
                 and bool(defaults.qwen_model and defaults.qwen_base_url))
    if answer and not bootstrap:
        same_model = (answer.model == defaults.qwen_model
                      and answer.base_url.rstrip("/") == defaults.qwen_base_url.rstrip("/"))
        window = answer.context_tokens or (defaults.context_tokens if same_model else Config.context_tokens)
        output = answer.max_tokens or min(defaults.output_tokens, window // 4)
        if window <= output + 256:
            raise ValueError("Размер ответа профиля не оставляет места для контекста TrustQA")
        config = replace(config, qwen_base_url=answer.base_url, qwen_api_key=answer.resolve_key(),
                         qwen_model=answer.model, qwen_model_version=(
                             defaults.qwen_model_version if same_model and defaults.qwen_model_version
                             else f"unversioned:{answer.model}"),
                         qwen_tokenizer=defaults.qwen_tokenizer if same_model else "",
                         temperature=answer.temperature, reasoning_effort=answer.reasoning_effort or "",
                         context_tokens=window, output_tokens=output)
        profiles["chat/completions"] = answer
    embed = ctx.models.get("embed")
    if embed:
        config = replace(config, jina_base_url=embed.base_url, jina_api_key=embed.resolve_key(),
                         jina_auth_header="Authorization", embedding_model=embed.model,
                         embedding_version=f"unversioned:{embed.model}", embedding_dimensions=embed.embed_dimensions,
                         embedding_query_task=embed.embed_query_task or "", embedding_passage_task=embed.embed_passage_task or "",
                         embedding_protocol="openai")
        profiles["embeddings"] = embed
    config.require_qwen()
    return config, profiles


def review(q: Question, docs: list[Document], config: Config, transport, rerank_config: Config, chat_ranker=None) -> Answer:
    package = Package(q.package)
    for doc in docs:
        if doc.encoding.endswith("-replace") or "\x00" in doc.text:
            return Answer(id=q.id, status=Status.UNKNOWN, trace=[
                TraceStep(node="coverage", ok=False, message=f"Не удалось прочитать {doc.file}.")])
        package.add_text(doc.file, doc.text, config.chunk_chars, config.overlap)
    parse_amendments(package)
    client = Qwen(config, transport)
    search = Jina(config, transport, rerank_config)

    def rank(question, chunks):
        if len(chunks) < 2:
            return chunks
        if client.calls >= config.max_calls:
            raise CallLimit("TrustQA call budget exhausted")
        client.calls += 1
        try:
            order = chat_ranker(question, chunks)
        except OpenAIError as exc:
            raise ServiceUnavailable(f"rerank: {type(exc).__name__}") from None
        return [chunks[i] for i in order]

    engine = Engine(config, Window(config), Retriever(config, search, rank if chat_ranker else None), lambda: client)
    try:
        result, audit = engine.answer(package, q.question, mode="D")
    except ServiceUnavailable as exc:
        return Answer(id=q.id, status=Status.UNKNOWN, llm_calls=client.calls, trace=[
            TraceStep(node="trustqa", ok=False, message=f"TrustQA недоступен: {exc}")])
    if result["status"] == Status.ANSWER:
        converted = moscow_deadline(q.question, result.get("quote", ""), result.get("file", ""), docs)
        if converted is not None and (not converted or result["answer"].strip() != converted):
            return Answer(id=q.id, status=Status.UNKNOWN, llm_calls=audit["calls"], trace=[
                TraceStep(node="timezone", ok=False, message="Московская дата и время не подтверждены.")])
    sources = []
    if result["status"] in (Status.ANSWER, Status.CONFLICT):
        sources.extend(result.get("evidence", []))
        sources.extend((result.get("calculation") or {}).get("operands", []))
    evidence = []
    # Проверяем фрагмент после отсечения команд: сама короткая цитата может выглядеть безобидно.
    clean = {d.file: norm(redact(d.text)[0]) for d in docs}
    for source in sources:
        item = Evidence.model_validate(source)
        if norm(item.quote) not in clean.get(item.file, ""):
            return Answer(id=q.id, status=Status.UNKNOWN, llm_calls=audit["calls"], trace=[
                TraceStep(node="trustqa", ok=False, message="Источник значения находится в инструкции для модели.")])
        if item not in evidence:
            evidence.append(item)
    return Answer(id=q.id, status=result["status"], evidence=evidence, answer=result.get("answer", ""),
                  quote=result.get("quote", ""), file=result.get("file", ""), llm_calls=audit["calls"],
                  trace=[TraceStep(node="trustqa", ok=result["status"] != Status.UNKNOWN,
                                   message=result.get("reason") or result["status"],
                                   data={"model": config.qwen_model, "revision": config.qwen_model_version,
                                         "calls": audit["calls"], "search": audit["search"],
                                         "full_scan": audit["full_scan"], "evidence": audit["evidence"],
                                         "events": audit["events"]})])


class HybridPipeline:
    name = "hybrid"

    def __init__(self, primary: Pipeline, use_guard: bool = False):
        self.primary = primary
        self.use_guard = use_guard

    async def answer(self, q: Question, docs: list[Document], ctx: Context) -> Answer:
        return await collect(self.stream(q, docs, ctx))

    async def stream(self, q: Question, docs: list[Document], ctx: Context):
        async for item in self.primary.stream(q, docs, ctx):
            if not isinstance(item, Answer):
                yield item
                continue
            if item.status != Status.UNKNOWN:
                yield item
                return
            yield TraceStep(node="fallback", message="Агент ответил «не знаю». TrustQA сверяет документы.")
            try:
                defaults = Config.from_env()
                config, profiles = fallback_config(ctx, defaults)
                async with BlockingPortal() as portal:
                    transport = partial(portal.call, partial(post_json, profiles=profiles))
                    ranker = None
                    if profile := ctx.models.get("rerank"):
                        ranker = partial(portal.call, partial(retrieval.ranked_indices, profile=profile))
                    checked = await to_thread.run_sync(review, q, docs, config, transport, defaults, ranker,
                                                       abandon_on_cancel=True)
            except Exception as exc:  # noqa: BLE001 — резервный проход не сработал: остаётся честное «не знаю» агента
                yield TraceStep(node="trustqa", ok=False, message=f"TrustQA не сработал: {type(exc).__name__}")
                yield item
                return
            if self.use_guard:   # цитата должна быть в документах; арифметику TrustQA проверяет сам, кодом
                checked = guard(checked, docs, q.question, quote_only=True)
            for step in checked.trace:
                yield step
            checked.trace = []
            checked.llm_calls += item.llm_calls
            yield checked
            return
