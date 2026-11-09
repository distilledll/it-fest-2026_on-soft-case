import asyncio

from app.pipeline import hybrid
from app.pipeline.agent import AgentPipeline
from app.pipeline.agent.critics import Draft
from app.pipeline.agent.graph import finalize
from app.pipeline.base import Context, get_pipeline
from app.schemas import Answer, Document, Question, Status, TraceStep


def test_guarded_primary_then_verified_calculation(monkeypatch):
    q = Question(id="N", package="P", question="Назовите размер обеспечения в рублях.")
    docs = [Document(package="P", file="n.txt", encoding="utf-8", text="Цена договора 700 руб. Ставка 5 %.")]

    async def primary(self, q, docs, ctx):
        yield TraceStep(node="answer", message="черновик")
        yield Answer(id=q.id, status=Status.ANSWER, answer="100", quote="Выдуманная цитата", llm_calls=2)

    def review(q, docs, config, transport, rerank_config, chat_ranker):
        return Answer(id=q.id, status=Status.ANSWER, answer="35", quote="Ставка 5 %.", file="n.txt",
                      llm_calls=3, trace=[TraceStep(node="trustqa", ok=True)])

    monkeypatch.setenv("QWEN_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("QWEN_MODEL", "fixture")
    monkeypatch.setenv("QWEN_MODEL_VERSION", "test")
    monkeypatch.setattr(AgentPipeline, "stream", primary)
    monkeypatch.setattr(hybrid, "review", review)
    a = asyncio.run(get_pipeline("hybrid", use_guard=True).answer(q, docs, Context()))
    assert a.answer == "35" and a.llm_calls == 5
    assert [s.node for s in a.trace] == ["answer", "guard_quote", "fallback", "trustqa"]


def test_primary_absence_skips_second_pass(monkeypatch):
    async def primary(self, q, docs, ctx):
        yield Answer(id=q.id, status=Status.ABSENT, answer="нет в документах", llm_calls=2)

    monkeypatch.setattr(AgentPipeline, "stream", primary)
    q = Question(id="N", package="P", question="Нужна лицензия?")
    a = asyncio.run(get_pipeline("hybrid", use_guard=True).answer(q, [], Context()))
    assert a.status == Status.ABSENT and a.answer == "" and a.llm_calls == 2


def test_absence_requires_map_coverage():
    draft = Draft(status="нет в документах")
    out = asyncio.run(finalize({"draft": draft, "incomplete_map": True}, {}))
    assert out["final"].status == "не знаю" and out["trace"][0].node == "coverage"


def _setup_fallback(monkeypatch, review_fn):
    async def primary(self, q, docs, ctx):
        yield Answer(id=q.id, status=Status.UNKNOWN, llm_calls=2)
    monkeypatch.setenv("QWEN_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("QWEN_MODEL", "fixture")
    monkeypatch.setenv("QWEN_MODEL_VERSION", "test")
    monkeypatch.setattr(AgentPipeline, "stream", primary)
    monkeypatch.setattr(hybrid, "review", review_fn)


def test_fallback_answer_goes_through_guard(monkeypatch):
    """Ответ TrustQA с цитатой, которой нет в документах, guard превращает в «не знаю»."""
    docs = [Document(package="P", file="n.txt", encoding="utf-8", text="Срок поставки 10 дней.")]

    def review(q, docs, config, transport, rerank_config, chat_ranker):
        return Answer(id=q.id, status=Status.ANSWER, answer="15", quote="Срок поставки 15 дней", file="n.txt",
                      llm_calls=3, trace=[TraceStep(node="trustqa", ok=True)])
    _setup_fallback(monkeypatch, review)
    q = Question(id="N", package="P", question="Какой срок поставки?")
    a = asyncio.run(get_pipeline("hybrid", use_guard=True).answer(q, docs, Context()))
    assert a.status == Status.UNKNOWN and "guard_quote" in [s.node for s in a.trace]


def test_fallback_failure_keeps_agent_unknown_without_error(monkeypatch):
    """Сбой TrustQA — не технический сбой вопроса: прогон не должен перезапускать его целиком."""
    from app.runs import is_failed

    def review(q, docs, config, transport, rerank_config, chat_ranker):
        raise RuntimeError("Mandatory context exceeds Qwen window")
    _setup_fallback(monkeypatch, review)
    q = Question(id="N", package="P", question="Какой срок поставки?")
    a = asyncio.run(get_pipeline("hybrid", use_guard=True).answer(q, [], Context()))
    assert a.status == Status.UNKNOWN and not is_failed(a)
    assert [s.node for s in a.trace][-1] == "trustqa" and a.trace[-1].ok is False


def test_incomplete_positive_and_redacted_claim_require_review():
    draft = Draft(status="ответ", answer="4", quote="Нужно 4 экземпляра", file="a.txt")
    for flag in ("incomplete_map", "redacted"):
        out = asyncio.run(finalize({"draft": draft, flag: True}, {}))
        assert out["final"].status == Status.UNKNOWN
        assert out["trace"][0].node == "coverage"
