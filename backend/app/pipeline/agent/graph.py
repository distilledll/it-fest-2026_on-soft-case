"""Агентный цикл на LangGraph.

    prepare → answer → check ──ok──→ llm_critic ──ok──→ finalize
                 ↑        │ error/warn        │ problem
                 └────────┴───── retry (пока есть бюджет) ──→ «не знаю»

Опции (ctx.options), чтобы мерить вклад каждой части:
  critics: list[str]      какие критики кодом включены (по умолчанию все из critics.CRITICS)
  llm_critic: bool        включён ли критик-модель (по умолчанию True)
  max_attempts: int       сколько раз модель может отвечать (по умолчанию 3)
  context_chars: int      сколько символов документов влезает целиком (по умолчанию 60000)
  multipart: bool         правило про вопросы из нескольких частей + числа подтверждаются любым evidence (True)
  decompose: bool         отдельный запрос разбивает вопрос на подвопросы (False — включать по замеру)
  research: bool          в режиме фрагментов перед «нет в документах» — повторный поиск с другими запросами (True)
  retriever: str          "hybrid" (BM25 + эмбеддинги, по умолчанию) | "keyword" (для сравнения)
  rerank: bool            реранк фрагментов моделью (False — включать по замеру)
"""
import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app import llm
from app.ingest import norm
from app.pipeline.agent import prompts
from app.pipeline.agent.context import build_context
from app.pipeline.agent.critics import CRITICS, MULTIPART_CTX, Draft, Issue, run_critics
from app.schemas import Document, Status, TraceStep

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


async def prepare(state: State, config) -> dict:
    docs, ctx = _cfg(config)
    context, info = await build_context(state["question"], docs, ctx, _opt(ctx, "context_chars", 60000))
    rule = prompts.MULTIPART_RULE if _opt(ctx, "multipart", True) else ""
    msgs = [{"role": "system", "content": prompts.SYSTEM.replace("{multipart_rule}", rule)},
            {"role": "user", "content": prompts.USER.format(context=context, question=state["question"])}]
    notes = [f"режим: {info['mode']}"]
    if info["redacted"]:
        notes.append(f"вырезано инструкций для ИИ: {info['redacted']}")
    if info["empty"]:
        notes.append(f"пустые файлы: {', '.join(info['empty'])}")
    if info.get("chunks") is not None:
        notes.append(f"фрагментов: {info['chunks']} из файлов {', '.join(info.get('files', []))}")
    return {"context": context, "messages": msgs, "attempts": 0, "llm_calls": 0, "warned": [],
            "fragments": info["mode"] != "full", "researched": False,
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


async def answer(state: State, config) -> dict:
    _, ctx = _cfg(config)
    prof = ctx.model("answer")
    raw = await llm.chat(prof, state["messages"], json=True)
    msgs = state["messages"] + [{"role": "assistant", "content": raw}]
    upd = {"messages": msgs, "attempts": state["attempts"] + 1, "llm_calls": state["llm_calls"] + 1,
           "critic_ok": False}
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
                "trace": [TraceStep(node="answer", ok=False, message=issue.message, data={"raw": raw[:800]})]}
    return {**upd, "draft": d, "issues": [],
            "trace": [TraceStep(node="answer", ok=True, message=f"попытка {upd['attempts']}: {d.status} «{d.answer}»",
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
    raw = await llm.chat(prof, json=True, messages=[{"role": "user", "content": prompts.CRITIC.format(
        question=state["question"], status=d.status, answer=d.answer, file=d.file, quote=d.quote,
        calc=d.calc or "—", around=_around(d, docs), evidence=_evidence_text(d, docs))}])
    calls = state["llm_calls"] + 1
    try:
        j = llm.parse_json(raw)
        ok, problem = bool(j.get("ok")), str(j.get("problem") or "")
    except (ValueError, TypeError):
        ok, problem = True, ""   # критик сломался — не наказываем ответ, прошедший проверки кодом
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
    context, info = await build_context(state["question"], docs, ctx, _opt(ctx, "context_chars", 60000),
                                        queries=[state["question"], *alts], k=20)
    rule = prompts.MULTIPART_RULE if _opt(ctx, "multipart", True) else ""
    msgs = [{"role": "system", "content": prompts.SYSTEM.replace("{multipart_rule}", rule)},
            {"role": "user", "content": prompts.USER.format(context=context, question=state["question"])}]
    return {"messages": msgs, "researched": True, "llm_calls": state["llm_calls"] + 1, "attempts": 0,
            "warned": [], "trace": [TraceStep(node="research", ok=True,
                                              message=f"повторный поиск: {len(alts)} доп. запросов, фрагментов {info.get('chunks')}",
                                              data={"queries": alts, "files": info.get("files", [])})]}


async def retry(state: State, config) -> dict:
    text = "\n".join(f"- [{i.critic}] {i.message}" for i in state["issues"])
    return {"messages": state["messages"] + [{"role": "user", "content": prompts.RETRY.format(issues=text)}],
            "trace": [TraceStep(node="retry", message=f"повтор с замечаниями ({len(state['issues'])})")]}


async def finalize(state: State, config) -> dict:
    d = state.get("draft")
    # warn по расхождению, оставшийся после исчерпания попыток, — тоже не сдаём: пропущенное расхождение = обман
    # Неразрешённое расхождение по собственным evidence модели — не сдаём. Подозрение от сверки кодом
    # (crosscheck) — тоже, но только если критик-модель не подтвердил, что это другой параметр.
    strict = ("conflict",) if state.get("critic_ok") else ("conflict", "crosscheck")
    errors = [i for i in state.get("issues", []) + state.get("pending_warns", [])
              if i.severity == "error" or i.critic in strict]
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
    if state.get("critic_ok"):
        return "finalize"
    return "retry" if state["attempts"] < _opt(ctx, "max_attempts", 3) else "finalize"


def build():
    g = StateGraph(State)
    for name, fn in (("prepare", prepare), ("decompose", decompose), ("research", research), ("answer", answer), ("check", check), ("llm_critic", llm_critic),
                     ("retry", retry), ("finalize", finalize)):
        g.add_node(name, fn)
    g.add_edge(START, "prepare")
    g.add_edge("prepare", "decompose")
    g.add_edge("decompose", "answer")
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
    from app.verify import quote_exists
    rows = [f"- {e['file']}: «{e['quote']}» → {e['value']}" for e in d.evidence if quote_exists(e["quote"], docs)]
    return "\n".join(rows) or "(не приведены)"


def _around(d: Draft, docs: list[Document], width: int = 400) -> str:
    for doc in docs:
        if doc.file == d.file:
            t, q = norm(doc.text), norm(d.quote)
            i = t.find(q)
            if i >= 0:
                return t[max(0, i - width): i + len(q) + width]
    return "(не найден)"
