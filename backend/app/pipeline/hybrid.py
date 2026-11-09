"""Быстрый агент отвечает первым. Его отказ перепроверяет полный проход TrustQA."""
import asyncio
from dataclasses import replace

from app import llm
from app.config import settings
from app.pipeline.base import Context, Pipeline, collect
from app.schemas import Answer, Document, Question, Status, TraceStep
from app.verify import guard
from trustqa.api import Jina, Qwen, ServiceUnavailable
from trustqa.config import Config
from trustqa.context import Window
from trustqa.documents import Package, parse_amendments
from trustqa.engine import Engine
from trustqa.retrieval import Retriever


def review(q: Question, docs: list[Document], config: Config) -> Answer:
    package = Package(q.package)
    for doc in docs:
        if doc.encoding == "utf-8-replace" or "\x00" in doc.text:
            package.issues.append({"file": doc.file, "reason": "unreadable document"})
            continue
        package.add_text(doc.file, doc.text, config.chunk_chars, config.overlap)
    parse_amendments(package)
    client = Qwen(config)
    engine = Engine(config, Window(config), Retriever(config, Jina(config)), lambda: client)
    try:
        result, audit = engine.answer(package, q.question, mode="D")
    except ServiceUnavailable as exc:
        return Answer(id=q.id, status=Status.UNKNOWN, llm_calls=client.calls, trace=[
            TraceStep(node="trustqa", ok=False, message=f"TrustQA недоступен: {exc}")])
    return Answer(id=q.id, status=result["status"], answer=result.get("answer", ""),
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
                config = Config.from_env()
                config.require_qwen()
                config = replace(config, cache_dir=str(settings.storage_dir / "trustqa-cache"))
                profile = llm.ModelProfile(id="trustqa-fallback", name="TrustQA", base_url=config.qwen_base_url,
                                           model=config.qwen_model, concurrency=1)
                checked = await llm.call(asyncio.to_thread, review, q, docs, config, profile=profile)
            except Exception as exc:  # noqa: BLE001 — резервный проход не сработал: остаётся честное «не знаю» агента
                yield TraceStep(node="trustqa", ok=False, message=f"TrustQA не сработал: {type(exc).__name__}: {exc}"[:300])
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
