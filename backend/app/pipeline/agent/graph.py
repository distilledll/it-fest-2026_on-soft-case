"""Агентный цикл на LangGraph.

    prepare → decompose ─┬──────────────→ answer → check ──ok──→ llm_critic ──ok──→ finalize
                         └─ map (закупка   ↑         │ error/warn        │ problem
                            не влезает)    └─────────┴── retry (пока есть бюджет) ──→ «не знаю»

map — map-reduce: модель читает закупку фрагментами (всю, если фрагментов ≤ map_max_chunks) и выписывает дословные цитаты, код их проверяет
(есть ли в документах, не старая ли редакция), answer отвечает только по ним. Включается сам, когда
закупка не влезает в context_chars (strategy "auto"), или всегда (strategy "map").

Опции (ctx.options), чтобы мерить вклад каждой части:
  critics: list[str]      какие критики кодом включены (по умолчанию все из critics.CRITICS)
  llm_critic: bool        включён ли критик-модель (по умолчанию True)
  max_attempts: int       сколько раз модель может отвечать (по умолчанию 3)
  context_chars: int      сколько символов документов влезает целиком; по умолчанию — от context_tokens
                          профиля answer (окно × 3 символа/токен × 0.5), если не задано — 60000
  multipart: bool         правило про вопросы из нескольких частей + числа подтверждаются любым evidence (True)
  decompose: bool         отдельный запрос разбивает вопрос на подвопросы (False — включать по замеру)
  research: bool          в режиме фрагментов перед «нет в документах» — повторный поиск с другими запросами (True)
  retriever: str          "hybrid" (BM25 + эмбеддинги, по умолчанию) | "keyword" (для сравнения)
  rerank: bool            реранк фрагментов моделью (False — включать по замеру)
  quote_first: bool       сначала модель выписывает фрагменты, код их проверяет и размечает, ответ — только по ним
  votes: int              голосование: сколько ответов сравнить на первой попытке (1 — выключено)
  map_extract: bool       с quote_first: модель читает закупку фрагментами (map), ответ — по проверенным выпискам (reduce)
  map_chunk_chars: int    размер фрагмента для map (4000); map_max_chunks — больше стольких фрагментов отбирает поиск (30)
  strategy: str           "auto" (по умолчанию: map, только если закупка не влезает в context_chars) |
                          "full" (без map) | "map" (всегда); можно задать в профиле модели
"""
import asyncio
import operator
import re
from collections import Counter
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app import llm
from app.ingest import needs_redaction_review, norm, redact
from app.pipeline.agent import prompts
from app.pipeline.agent.context import build_context
from app.pipeline.agent.critics import CRITICS, MULTIPART_CTX, Draft, Issue, run_critics
from app.schemas import Document, Status, TraceStep
from app.verify import STAMP, moscow_deadline

STATUSES = {s.value for s in Status}


class State(TypedDict, total=False):
    question: str
    context: str
    messages: list[dict]
    draft: Draft | None
    issues: list[Issue]
    warned: list[str]          # по каким warn уже был повтор — второй раз не дёргаем
    pending_warns: list[Issue] # повторный warn, на который модель не отреагировала
    fragments: bool            # модель видит фрагменты, а не документы целиком
    researched: bool           # повторный поиск перед «нет в документах» уже был
    quotes_ready: bool         # шаг «сначала цитаты» выполнен (узел map)
    unreadable: bool
    redacted: bool
    incomplete_map: bool
    auto_map: bool             # map включён автоматически: закупка не влезла в контекст
    vote: dict | None          # итог голосования (опция votes)
    critic_ok: bool
    attempts: int
    llm_calls: int
    final: Draft | None
    trace: Annotated[list[TraceStep], operator.add]


def _cfg(config) -> tuple[list[Document], Any]:
    c = config["configurable"]
    return c["docs"], c["ctx"]


def _opt(ctx, key, default):
    return (ctx.options or {}).get(key, default)


CHARS_PER_TOKEN = 3.0     # русский текст закупок: ~4 символа на токен (замер на шлюзе), берём с запасом
DOC_SHARE = 0.5           # половина окна — документам; остальное — промпт, повторы с замечаниями, ответ
DEFAULT_CONTEXT_CHARS = 60000


def context_budget(ctx) -> int:
    """Сколько символов документов модель читает целиком. Явная опция context_chars важнее;
    иначе — от окна модели (context_tokens в профиле answer); окно не указано — 60000 с запасом."""
    explicit = _opt(ctx, "context_chars", None)
    if explicit:
        return int(explicit)
    tokens = getattr(ctx.models.get("answer"), "context_tokens", None) if ctx.models else None
    return int(tokens * CHARS_PER_TOKEN * DOC_SHARE) if tokens else DEFAULT_CONTEXT_CHARS


async def prepare(state: State, config) -> dict:
    docs, ctx = _cfg(config)
    context, info = await build_context(state["question"], docs, ctx, context_budget(ctx))
    rule = prompts.MULTIPART_RULE if _opt(ctx, "multipart", True) else ""
    msgs = [{"role": "system", "content": prompts.SYSTEM.replace("{multipart_rule}", rule)},
            {"role": "user", "content": prompts.USER.format(context=context, question=state["question"])}]
    notes = [f"режим: {info['mode']}"]
    if info["redacted"]:
        notes.append(f"вырезано инструкций для ИИ: {info['redacted']}")
    if info["empty"]:
        notes.append(f"пустые файлы: {', '.join(info['empty'])}")
    if info.get("embed_error"):
        notes.append(f"эмбеддинги не работают ({info['embed_error']}) — поиск только по словам")
    if info.get("chunks") is not None:
        notes.append(f"фрагментов: {info['chunks']} из файлов {', '.join(info.get('files', []))}")
    unreadable = any(d.encoding.endswith("-replace") or "\x00" in d.text for d in docs)
    return {"context": context, "messages": msgs, "attempts": 0, "llm_calls": 0, "warned": [],
            "fragments": info["mode"] != "full", "researched": False,
            "incomplete_map": info["mode"] != "full", "redacted": any(needs_redaction_review(d.text) for d in docs),
            "unreadable": unreadable,
            "trace": [TraceStep(node="prepare", ok=True, message="; ".join(notes), data=info)]}


async def decompose(state: State, config) -> dict:
    """Опция decompose: отдельный запрос разбивает вопрос на подвопросы, они добавляются в задание модели."""
    _, ctx = _cfg(config)
    if not _opt(ctx, "decompose", False):
        return {}
    raw = await llm.chat(ctx.model("answer"), json=True, messages=[
        {"role": "user", "content": prompts.DECOMPOSE.format(question=state["question"])}])
    calls = state["llm_calls"] + 1
    try:
        parts = [str(x).strip() for x in llm.parse_json(raw).get("parts", []) if str(x).strip()]
    except (ValueError, TypeError, AttributeError):
        parts = []
    if len(parts) < 2:
        return {"llm_calls": calls, "trace": [TraceStep(node="decompose", ok=True, message="вопрос простой")]}
    msgs = list(state["messages"])
    msgs[-1] = {**msgs[-1], "content": msgs[-1]["content"] + prompts.DECOMPOSED.format(
        parts="\n".join(f"{i}) {x}" for i, x in enumerate(parts, 1)))}
    return {"messages": msgs, "llm_calls": calls,
            "trace": [TraceStep(node="decompose", ok=True, message=f"частей: {len(parts)}", data={"parts": parts})]}


async def _quote_first(state: State, docs: list[Document], ctx) -> tuple[list[dict], list[TraceStep], int]:
    """Шаг А «сначала цитаты»: модель выписывает фрагменты, код проверяет и размечает их.
    Возвращает новые messages для шага Б, шаги trace и число вызовов модели."""
    from app.pipeline.agent import fields as F
    from app.pipeline.agent.critics import parse_amendments, superseded_by, is_amendment_doc
    from app.ingest import is_injection
    from app.verify import quote_exists, snap_quote

    calls, coverage, stale = 1, "", 0
    map_mode = bool(_opt(ctx, "map_extract", False)) or state.get("auto_map", False)
    if map_mode:
        got, calls, read_all = await _map_extract(state["question"], docs, ctx)
        coverage = ("Прочитаны ВСЕ фрагменты документов закупки." if read_all else
                    "Прочитаны только фрагменты, отобранные поиском: окончательный вывод требует проверки оставшихся фрагментов.")
    else:
        raw = await llm.chat(ctx.model("answer"), json=True, messages=[
            {"role": "user", "content": prompts.EXTRACT.format(context=state["context"], question=state["question"])}])
        try:
            got = [q for q in llm.parse_json(raw).get("quotes", []) if isinstance(q, dict)]
        except (ValueError, TypeError, AttributeError):
            got = []
    amendments = parse_amendments(docs)
    by_file = {d.file: d for d in docs}
    lines, kept, dropped, seen = [], 0, 0, set()
    for q in got:
        text, file = str(q.get("quote") or ""), str(q.get("file") or "")
        candidates = [d for d in docs if not file or d.file == file]
        doc = quote_exists(text, candidates)
        if not doc:
            snapped = snap_quote(text, candidates) if file or len(candidates) == 1 else None
            if not snapped:
                dropped += 1
                continue
            text, file = snapped
        else:
            file = doc.file
        if is_injection(text) or (file, norm(text)) in seen:
            dropped += 1
            continue
        seen.add((file, norm(text)))
        tags = []
        if file in by_file and is_amendment_doc(by_file[file]):
            tags.append("[ИЗМЕНЕНИЕ ИЗВЕЩЕНИЯ]")
        old_by = superseded_by(text, file, amendments)
        if old_by:
            if map_mode:          # в map-reduce старую редакцию не показываем, а подставляем то, что её заменило
                stale += 1
                repl = old_by.repeal_text if old_by.repealed else old_by.new_text
                if repl and (old_by.amend_file, norm(repl)) not in seen:
                    seen.add((old_by.amend_file, norm(repl)))
                    note = (f"пункт отменён, требования больше нет; отменённый текст: «{text}»" if old_by.repealed
                            else "заменяет старую редакцию")
                    lines.append(f"- ({old_by.amend_file}) [ИЗМЕНЕНИЕ ИЗВЕЩЕНИЯ, {note}] «{repl}»")
                    kept += 1
                continue
            tags.append("[СТАРАЯ РЕДАКЦИЯ]")
        lines.append(f"- ({file}) {' '.join(tags)} «{text}»")
        kept += 1
    field = F.field_for(state["question"])
    if field:
        for v, file, sent in F.candidates(field, docs, lambda s, f: superseded_by(s, f, amendments) is not None)[:3]:
            lines.append(f"- ({file}) [НАЙДЕНО КОДОМ: {field.title} = {v}] «{sent.strip()}»")
    rule = prompts.MULTIPART_RULE if _opt(ctx, "multipart", True) else ""
    msgs = [{"role": "user", "content": prompts.ANSWER_FROM_QUOTES.format(
        quotes=(coverage + "\n" if coverage else "") + ("\n".join(lines) or "(фрагменты не найдены)"),
        question=state["question"], multipart_rule=rule)}]
    mode = "по фрагментам" if _opt(ctx, "map_extract", False) else "сначала цитаты"
    step = TraceStep(node="extract", ok=kept > 0,
                     message=f"{mode}: запросов {calls}, проверено {kept}, отброшено (нет в документах/инъекция) {dropped}"
                             + (f", старая редакция скрыта: {stale}" if stale else "") + (f". {coverage}" if coverage else ""),
                     data={"quotes": lines, "complete": read_all if map_mode else None})
    return msgs, [step], calls


async def _map_extract(question: str, docs: list[Document], ctx) -> tuple[list[dict], int, bool]:
    """Map: модель читает закупку небольшими фрагментами и по каждому выписывает дословные предложения.
    Узкая задача на коротком тексте — по силам и маленькой модели. Фрагменты обрабатываются параллельно.
    Если фрагментов больше map_max_chunks, сначала отбираем лучшие (BM25), изменения извещения — всегда."""
    from app import retrieval
    from app.pipeline.agent.critics import is_amendment_doc

    size, overlap = int(_opt(ctx, "map_chunk_chars", 4000)), 200
    limit = max(1, int(_opt(ctx, "map_max_chunks", 30)))
    if not _opt(ctx, "map_chunk_chars", None):
        # Укрупняем фрагменты в пределах окна, чтобы прочитать пакет за тот же бюджет вызовов.
        total = sum(len(d.text) for d in docs)
        slots = max(1, limit - len(docs))
        if total > slots * (size - overlap):
            target = total // slots + 2 * overlap
            size = max(size, min(target, size * 4, context_budget(ctx) // 2))
    chunks: list[tuple[Document, str]] = []
    for d in docs:
        if d.is_empty:
            continue
        pos = 0
        while pos < len(d.text):
            end = min(len(d.text), pos + size)
            if end < len(d.text):
                cut = max(d.text.rfind("\n", pos + size // 2, end), d.text.rfind(". ", pos + size // 2, end))
                end = cut + 1 if cut > pos else end
            chunks.append((d, d.text[pos:end]))
            if end >= len(d.text):
                break
            pos = max(end - overlap, pos + 1)
    # читаем всё: только тогда «нет в документах» обоснован; поиск отбирает фрагменты лишь для огромных документов
    read_all = len(chunks) <= limit
    if not read_all:
        must = [c for c in chunks if is_amendment_doc(c[0])]
        rest = [c for c in chunks if not is_amendment_doc(c[0])]
        scores = retrieval.BM25([retrieval.tokens(t) for _, t in rest]).scores(retrieval.tokens(question))
        order = sorted(range(len(rest)), key=lambda i: -scores[i])
        picked = must + [rest[i] for i in order[:max(limit - len(must), 1)]]
        for f in {d.file for d, _ in rest}:                          # хотя бы лучший кусок каждого файла
            best = next((rest[i] for i in order if rest[i][0].file == f), None)
            if best and best not in picked:
                picked.append(best)
        chunks = picked
    prof = ctx.model("answer")

    async def read(doc: Document, text: str) -> list[dict] | None:
        shown, _ = redact(text)
        raw = await llm.chat(prof, json=True, messages=[{"role": "user", "content": prompts.MAP_CHUNK.format(
            file=doc.file, question=question, chunk=shown)}])
        try:
            qs = llm.parse_json(raw).get("quotes")
        except (ValueError, TypeError, AttributeError):
            return None
        if not isinstance(qs, list):
            return None
        return [{"file": doc.file, "quote": str(q.get("quote") if isinstance(q, dict) else q)} for q in qs if q]

    found = await asyncio.gather(*(read(d, t) for d, t in chunks), return_exceptions=True)
    got = [q for r in found if isinstance(r, list) for q in r]
    return got, len(chunks), read_all and all(isinstance(r, list) for r in found)


MONTH_DATE = re.compile(r"(\d{1,2})\s+(январ\w*|феврал\w*|март\w*|апрел\w*|ма[яй]|июн\w*|июл\w*|август\w*|"
                        r"сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)\s+(\d{4})", re.I)
TIME_WORDS = re.compile(r"(\d{1,2})\s*час\w*\s*(\d{1,2})?\s*(?:минут\w*)?", re.I)


def normalize_answer(answer: str) -> str:
    """Дата прописью → «ДД.ММ.ГГГГ ЧЧ:ММ» (формат, который ждёт check.py). Слабые модели переписывают дату словами."""
    from app.verify import MONTHS
    m = MONTH_DATE.search(answer or "")
    if not m or re.search(r"\d{1,2}\.\d{1,2}\.\d{4}", answer):
        return answer
    date = f"{int(m.group(1)):02d}.{MONTHS[m.group(2).lower()[:3]]:02d}.{m.group(3)}"
    t = TIME_WORDS.search(answer) or re.search(r"(\d{1,2}):(\d{2})", answer)
    return f"{date} {int(t.group(1)):02d}:{int(t.group(2) or 0):02d}" if t else date


def _vote_key(status: str, answer: str) -> str:
    from app.verify import numbers
    nums = sorted({round(x, 2) for x in numbers(answer)})
    if nums:
        return f"{status}|{nums}"
    a = norm(answer)
    if re.search(r"\bнет\b|не\s+(требует|установлен|предусмотрен)", a):
        return f"{status}|нет"
    if re.search(r"\bда\b", a):
        return f"{status}|да"
    return f"{status}|{re.sub(r'[^а-яa-z]', '', a)[:20]}"


async def _vote(d: Draft, messages: list[dict], prof, votes: int, ctx) -> tuple[dict, TraceStep, int]:
    """Голосование (самосогласованность): ещё votes−1 ответов с ненулевой температурой.
    Возвращает {"top": ключ большинства, "agree": доля, "variants": [...]}."""
    temp = float(_opt(ctx, "vote_temperature", 0.7))
    raws = await asyncio.gather(*(llm.chat(prof, messages, json=True, temperature=temp) for _ in range(votes - 1)),
                                return_exceptions=True)
    variants = [(d.status, d.answer)]
    for r in raws:
        try:
            j = llm.parse_json(r) if isinstance(r, str) else {}
            if j:
                variants.append((str(j.get("status", "")).strip().lower(), str(j.get("answer") or "")))
        except (ValueError, TypeError):
            continue
    keys = Counter(_vote_key(s, a) for s, a in variants)
    top, n = keys.most_common(1)[0]
    vote = {"top": top, "agree": n / len(variants), "variants": variants}
    step = TraceStep(node="votes", ok=vote["agree"] >= 2 / 3 and _vote_key(d.status, d.answer) == top,
                     message=f"голосование: согласие {n} из {len(variants)}",
                     data={"variants": [f"{s}: {a}" for s, a in variants]})
    return vote, step, votes - 1


def _vote_unreliable(vote: dict | None, d: Draft | None) -> bool:
    return bool(vote and d and (vote["agree"] < 2 / 3 or _vote_key(d.status, d.answer) != vote["top"]))


def _vote_issue(vote: dict) -> Issue:
    alts = "; ".join(f"«{s}: {a[:60]}»" for s, a in vote["variants"])
    return Issue("votes", f"при повторных запросах модель отвечает по-разному: {alts}. Перепроверь по документам и "
                          f"выбери ответ, который подтверждается дословной цитатой", severity="warn",
                 data={"variants": vote["variants"]})


def use_map(state: State, config) -> str:
    """Дробить ли закупку: явно (quote_first / strategy "map") или сама, если она не влезла в контекст."""
    _, ctx = _cfg(config)
    if _opt(ctx, "quote_first", False):
        return "map"
    if _opt(ctx, "strategy", "auto") == "auto" and state.get("fragments"):
        return "map"
    return "answer"


async def map_node(state: State, config) -> dict:
    docs, ctx = _cfg(config)
    auto = not _opt(ctx, "quote_first", False)
    st = {**state, "auto_map": auto}
    msgs, steps, calls = await _quote_first(st, docs, ctx)
    complete = steps[-1].data["complete"]
    incomplete = state.get("fragments", False) if complete is None else not complete
    if auto:
        steps = [TraceStep(node="map", ok=None, message="закупка не влезает в контекст модели — читаем по фрагментам")] + steps
    # map уже прочитал закупку целиком (или лучшие фрагменты всех файлов) — повторный поиск не нужен
    return {"messages": msgs, "incomplete_map": incomplete,
            "quotes_ready": True, "auto_map": auto, "researched": True,
            "llm_calls": state["llm_calls"] + calls, "trace": steps}


async def answer(state: State, config) -> dict:
    docs, ctx = _cfg(config)
    prof = ctx.model("answer")
    pre: list[TraceStep] = []
    extra_calls = 0
    raw = await llm.chat(prof, state["messages"], json=True)
    msgs = state["messages"] + [{"role": "assistant", "content": raw}]
    upd = {"messages": msgs, "attempts": state["attempts"] + 1, "llm_calls": state["llm_calls"] + 1 + extra_calls,
           "critic_ok": False, "quotes_ready": state.get("quotes_ready", False)}
    try:
        j = llm.parse_json(raw)
        status = str(j.get("status", "не знаю")).strip().lower()
        if status not in STATUSES:
            raise ValueError(f"непонятный статус «{status}»")
        d = Draft(status=status, answer=str(j.get("answer") or ""), quote=str(j.get("quote") or ""),
                  file=str(j.get("file") or ""), evidence=_evidence(j.get("evidence")),
                  calc=str(j["calc"]) if j.get("calc") else None)
    except (ValueError, TypeError) as e:
        issue = Issue("format", f"ответ не в формате JSON: {e}")
        return {**upd, "draft": None, "issues": [issue],
                "trace": pre + [TraceStep(node="answer", ok=False, message=issue.message, data={"raw": raw[:800]})]}
    votes = int(_opt(ctx, "votes", 1) or 1)
    if votes > 1 and state["attempts"] == 0:
        vote, vote_step, vote_calls = await _vote(d, state["messages"], prof, votes, ctx)
        upd["llm_calls"] += vote_calls
        upd["vote"] = vote
        pre = pre + [vote_step]
    d.answer = normalize_answer(d.answer)
    return {**upd, "draft": d, "issues": [],
            "trace": pre + [TraceStep(node="answer", ok=True, message=f"попытка {upd['attempts']}: {d.status} «{d.answer}»",
                                data={"draft": d.__dict__, "model": prof.model})]}


async def check(state: State, config) -> dict:
    docs, ctx = _cfg(config)
    d = state.get("draft")
    if d is None:
        return {}
    enabled = _opt(ctx, "critics", list(CRITICS))
    token = MULTIPART_CTX.set(bool(_opt(ctx, "multipart", True)))
    try:
        issues = run_critics(d, docs, state["question"], enabled)
    finally:
        MULTIPART_CTX.reset(token)
    # warn — один повтор на критика; если модель настаивает, оставляем её решение
    if state["attempts"] == 1 and _vote_unreliable(state.get("vote"), d):
        issues.append(_vote_issue(state["vote"]))
    fresh = [i for i in issues if i.severity == "error" or i.critic not in state["warned"]]
    warned = state["warned"] + [i.critic for i in fresh if i.severity == "warn"]
    # повторные warn не гоняют модель снова, но запоминаются: если ответ так и сдаётся — finalize решит
    stale_warns = [i for i in issues if i not in fresh]
    issues = fresh
    steps = [TraceStep(node=f"critic_{i.critic}", ok=False, message=i.message,
                       data={"severity": i.severity, **i.data}) for i in issues]
    if not issues:
        msg = f"проверки кодом пройдены ({', '.join(enabled)})"
        if stale_warns:
            msg += "; модель настаивает вопреки: " + ", ".join(i.critic for i in stale_warns)
        steps = [TraceStep(node="check", ok=not stale_warns, message=msg, data={"draft": d.__dict__})]
    return {"issues": issues, "warned": warned, "draft": d, "trace": steps, "pending_warns": stale_warns}


async def llm_critic(state: State, config) -> dict:
    docs, ctx = _cfg(config)
    d = state["draft"]
    if d.status in ("нет в документах", "не знаю"):
        return {"critic_ok": True}
    prof = ctx.model("critic")
    question, value, calc = state["question"], d.answer, d.calc
    converted = moscow_deadline(question, d.quote, d.file, docs)
    if converted and d.status == "ответ" and converted == value:
        # Python уже проверил перевод. Критик сверяет смысл исходного срока и его применимость.
        question = ("Какие местные дата и время в источнике соответствуют сроку подачи заявок "
                    "из вопроса «" + question + "»? Проверь, что это именно нужный срок.")
        value = " ".join(STAMP.search(d.quote).groups())
        calc = None
    messages = [{"role": "user", "content": prompts.CRITIC.format(
        question=question, status=d.status, answer=value, file=d.file, quote=d.quote,
        calc=calc or "—", around=_around(d, docs), evidence=_evidence_text(d, docs))}]
    calls = state["llm_calls"]
    for attempt in range(2):
        raw = await llm.chat(prof, json=True, messages=messages)
        calls += 1
        try:
            decision = llm.parse_json(raw)
            ok = decision.get("ok")
            if type(ok) is not bool:
                raise ValueError("ok must be boolean")
            problem = str(decision.get("problem") or "ответ не подтверждён")
            break
        except (ValueError, AttributeError, TypeError):
            if attempt == 1:
                message = "Критик дважды вернул некорректное решение; нужна повторная проверка источников."
                return {"critic_ok": False, "llm_calls": calls, "issues": [Issue("critic_format", message)],
                        "trace": [TraceStep(node="llm_critic", ok=False, message=message)]}
            messages.append({"role": "user", "content": 'Верни объект JSON. Поле ok — только true или false.'})
    if ok:
        return {"critic_ok": True, "llm_calls": calls,
                "trace": [TraceStep(node="llm_critic", ok=True, message=f"критик ({prof.model}) согласен")]}
    return {"critic_ok": False, "llm_calls": calls, "issues": [Issue("llm_critic", problem)],
            "trace": [TraceStep(node="llm_critic", ok=False, message=problem)]}


async def research(state: State, config) -> dict:
    """Модель видела только фрагменты и сказала «нет в документах» — возможно, промахнулся поиск.
    Просим другие формулировки, ищем шире и задаём вопрос заново."""
    docs, ctx = _cfg(config)
    raw = await llm.chat(ctx.model("answer"), json=True, messages=[
        {"role": "user", "content": prompts.RESEARCH.format(question=state["question"])}])
    try:
        alts = [str(x) for x in llm.parse_json(raw).get("queries", []) if str(x).strip()][:3]
    except (ValueError, TypeError, AttributeError):
        alts = []
    context, info = await build_context(state["question"], docs, ctx, context_budget(ctx),
                                        queries=[state["question"], *alts], k=20)
    rule = prompts.MULTIPART_RULE if _opt(ctx, "multipart", True) else ""
    msgs = [{"role": "system", "content": prompts.SYSTEM.replace("{multipart_rule}", rule)},
            {"role": "user", "content": prompts.USER.format(context=context, question=state["question"])}]
    return {"messages": msgs, "researched": True, "quotes_ready": False, "context": context,
            "llm_calls": state["llm_calls"] + 1, "attempts": 0,
            "warned": [], "trace": [TraceStep(node="research", ok=True,
                                              message=f"повторный поиск: {len(alts)} доп. запросов, фрагментов {info.get('chunks')}",
                                              data={"queries": alts, "files": info.get("files", [])})]}


async def retry(state: State, config) -> dict:
    text = "\n".join(f"- [{i.critic}] {i.message}" for i in state["issues"])
    return {"messages": state["messages"] + [{"role": "user", "content": prompts.RETRY.format(issues=text)}],
            "trace": [TraceStep(node="retry", message=f"повтор с замечаниями ({len(state['issues'])})")]}


async def finalize(state: State, config) -> dict:
    d = state.get("draft")
    if d and d.status != "не знаю" and any(state.get(k) for k in ("incomplete_map", "redacted", "unreadable")):
        return {"final": Draft(status="не знаю"), "trace": [TraceStep(
            node="coverage", ok=False, message="Для вывода требуется проверка пропущенных или скрытых фрагментов.")]}
    # warn по расхождению, оставшийся после исчерпания попыток, — тоже не сдаём: пропущенное расхождение = обман
    # Неразрешённое расхождение по собственным evidence модели — не сдаём. Подозрение от сверки кодом
    # (crosscheck) — тоже, но только если критик-модель не подтвердил, что это другой параметр.
    strict = ("conflict",) if state.get("critic_ok") else ("conflict", "crosscheck")
    errors = [i for i in state.get("issues", []) + state.get("pending_warns", [])
              if i.severity == "error" or i.critic in strict]
    if not errors and not state.get("critic_ok") and _vote_unreliable(state.get("vote"), d):
        errors = [_vote_issue(state["vote"])]
    if d is None or errors:
        why = "; ".join(i.message for i in errors)[:300] or "нет корректного ответа"
        return {"final": Draft(status="не знаю"),
                "trace": [TraceStep(node="finalize", ok=False, message=f"бюджет попыток исчерпан → «не знаю»: {why}")]}
    return {"final": d, "trace": [TraceStep(node="finalize", ok=True, message=f"{d.status} «{d.answer}»")]}


# ---------------------------------------------------------------- маршрутизация

def after_check(state: State, config) -> str:
    _, ctx = _cfg(config)
    if state.get("issues"):
        return "retry" if state["attempts"] < _opt(ctx, "max_attempts", 3) else "finalize"
    d = state.get("draft")
    if (d and d.status == "нет в документах" and state.get("fragments") and not state.get("researched")
            and _opt(ctx, "research", True)):
        return "research"
    if _opt(ctx, "llm_critic", True) and not state.get("critic_ok"):
        return "llm_critic"
    return "finalize"


def after_critic(state: State, config) -> str:
    _, ctx = _cfg(config)
    if state.get("critic_ok") or any(i.critic == "critic_format" for i in state.get("issues", [])):
        return "finalize"
    return "retry" if state["attempts"] < _opt(ctx, "max_attempts", 3) else "finalize"


def build():
    g = StateGraph(State)
    for name, fn in (("prepare", prepare), ("decompose", decompose), ("map", map_node), ("research", research),
                     ("answer", answer), ("check", check), ("llm_critic", llm_critic), ("retry", retry),
                     ("finalize", finalize)):
        g.add_node(name, fn)
    g.add_edge(START, "prepare")
    g.add_edge("prepare", "decompose")
    g.add_conditional_edges("decompose", use_map, ["map", "answer"])
    g.add_edge("map", "answer")
    g.add_edge("answer", "check")
    g.add_conditional_edges("check", after_check, ["retry", "research", "llm_critic", "finalize"])
    g.add_edge("research", "answer")
    g.add_conditional_edges("llm_critic", after_critic, ["retry", "finalize"])
    g.add_edge("retry", "answer")
    g.add_edge("finalize", END)
    return g.compile()


GRAPH = build()


def _evidence(raw) -> list[dict]:
    """Модели возвращают что угодно: числа вместо строк, строки вместо объектов. Приводим к виду критиков."""
    out = []
    for e in raw if isinstance(raw, list) else []:
        if isinstance(e, dict):
            out.append({k: "" if e.get(k) is None else str(e.get(k)) for k in ("file", "quote", "value", "part")})
    return out


def _evidence_text(d: Draft, docs: list[Document]) -> str:
    from app.pipeline.agent.critics import parse_amendments
    from app.verify import quote_exists
    rows = [f"- {e['file']}: «{e['quote']}» → {e['value']}" for e in d.evidence if quote_exists(e["quote"], docs, e["file"])]
    # цитата — строка изменения извещения: критик должен видеть, что именно было отменено или заменено,
    # иначе «пункт 2.6 утратил силу» для него не связан с параметром из вопроса
    cited = norm(" ".join([d.quote] + [e["quote"] for e in d.evidence]))
    for a in parse_amendments(docs):
        mark = norm(a.repeal_text if a.repealed else a.new_text)
        if mark and a.old_sentence and (mark in cited or (cited and cited in mark)):
            what = "признан утратившим силу" if a.repealed else "изложен в новой редакции"
            rows.append(f"- пункт {a.clause or '?'} ({a.target_file}) {what} изменением ({a.amend_file}); "
                        f"старая редакция: «{a.old_sentence}»")
    return "\n".join(rows) or "(не приведены)"


def _around(d: Draft, docs: list[Document], width: int = 400) -> str:
    for doc in docs:
        if doc.file == d.file:
            t, q = norm(redact(doc.text)[0]), norm(d.quote)
            i = t.find(q)
            if i >= 0:
                return t[max(0, i - width): i + len(q) + width]
    return "(не найден)"
