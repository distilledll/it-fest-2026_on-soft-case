"""Агентный цикл на LangGraph.

    prepare → answer → check ──ok──→ llm_critic ──ok──→ finalize
                 ↑        │ error/warn        │ problem
                 └────────┴───── retry (пока есть бюджет) ──→ «не знаю»

Опции (ctx.options), чтобы мерить вклад каждой части:
  critics: list[str]      какие критики кодом включены (по умолчанию все из critics.CRITICS)
  llm_critic: bool        включён ли критик-модель (по умолчанию True)
  max_attempts: int       сколько раз модель может отвечать (по умолчанию 3)
  context_chars: int      сколько символов документов влезает целиком (по умолчанию 60000)
"""
import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app import llm
from app.ingest import norm
from app.pipeline.agent import prompts
from app.pipeline.agent.context import build_context
from app.pipeline.agent.critics import CRITICS, Draft, Issue, run_critics
from app.schemas import Document, Status, TraceStep

STATUSES = {s.value for s in Status}


class State(TypedDict, total=False):
    question: str
    context: str
    messages: list[dict]
    draft: Draft | None
    issues: list[Issue]
    warned: list[str]          # по каким warn уже был повтор — второй раз не дёргаем
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
    context, info = build_context(state["question"], docs, ctx, _opt(ctx, "context_chars", 60000))
    msgs = [{"role": "system", "content": prompts.SYSTEM},
            {"role": "user", "content": prompts.USER.format(context=context, question=state["question"])}]
    notes = [f"режим: {info['mode']}"]
    if info["redacted"]:
        notes.append(f"вырезано инструкций для ИИ: {info['redacted']}")
    if info["empty"]:
        notes.append(f"пустые файлы: {', '.join(info['empty'])}")
    return {"context": context, "messages": msgs, "attempts": 0, "llm_calls": 0, "warned": [],
            "trace": [TraceStep(node="prepare", ok=True, message="; ".join(notes), data=info)]}


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
    issues = run_critics(d, docs, state["question"], enabled)
    # warn — один повтор на критика; если модель настаивает, оставляем её решение
    issues = [i for i in issues if i.severity == "error" or i.critic not in state["warned"]]
    warned = state["warned"] + [i.critic for i in issues if i.severity == "warn"]
    steps = [TraceStep(node=f"critic_{i.critic}", ok=False, message=i.message,
                       data={"severity": i.severity, **i.data}) for i in issues]
    if not issues:
        steps = [TraceStep(node="check", ok=True, message=f"проверки кодом пройдены ({', '.join(enabled)})",
                           data={"draft": d.__dict__})]
    return {"issues": issues, "warned": warned, "draft": d, "trace": steps}


async def llm_critic(state: State, config) -> dict:
    docs, ctx = _cfg(config)
    d = state["draft"]
    if d.status in ("нет в документах", "не знаю"):
        return {"critic_ok": True}
    prof = ctx.model("critic")
    raw = await llm.chat(prof, json=True, messages=[{"role": "user", "content": prompts.CRITIC.format(
        question=state["question"], status=d.status, answer=d.answer, file=d.file, quote=d.quote,
        around=_around(d, docs))}])
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


async def retry(state: State, config) -> dict:
    text = "\n".join(f"- [{i.critic}] {i.message}" for i in state["issues"])
    return {"messages": state["messages"] + [{"role": "user", "content": prompts.RETRY.format(issues=text)}],
            "trace": [TraceStep(node="retry", message=f"повтор с замечаниями ({len(state['issues'])})")]}


async def finalize(state: State, config) -> dict:
    d = state.get("draft")
    errors = [i for i in state.get("issues", []) if i.severity == "error"]
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
    for name, fn in (("prepare", prepare), ("answer", answer), ("check", check), ("llm_critic", llm_critic),
                     ("retry", retry), ("finalize", finalize)):
        g.add_node(name, fn)
    g.add_edge(START, "prepare")
    g.add_edge("prepare", "answer")
    g.add_edge("answer", "check")
    g.add_conditional_edges("check", after_check, ["retry", "llm_critic", "finalize"])
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
            out.append({k: "" if e.get(k) is None else str(e.get(k)) for k in ("file", "quote", "value")})
    return out


def _around(d: Draft, docs: list[Document], width: int = 400) -> str:
    for doc in docs:
        if doc.file == d.file:
            t, q = norm(doc.text), norm(d.quote)
            i = t.find(q)
            if i >= 0:
                return t[max(0, i - width): i + len(q) + width]
    return "(не найден)"
