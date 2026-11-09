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

    def review(q, docs, config):
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
