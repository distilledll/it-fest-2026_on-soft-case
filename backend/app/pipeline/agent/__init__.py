"""LangGraph-агент: контекст → ответ → узкие критики кодом → критик-модель → исправление → «не знаю»."""
from app.pipeline.base import Context, collect
from app.schemas import Answer, Document, Question, Status


class AgentPipeline:
    name = "agent"

    async def answer(self, q: Question, docs: list[Document], ctx: Context) -> Answer:
        return await collect(self.stream(q, docs, ctx))

    async def stream(self, q: Question, docs: list[Document], ctx: Context):
        from app.pipeline.agent.graph import GRAPH

        config = {"configurable": {"docs": docs, "ctx": ctx}, "recursion_limit": 40}
        state: dict = {}
        async for upd in GRAPH.astream({"question": q.question, "trace": []}, config, stream_mode="updates"):
            for delta in upd.values():
                if not delta:
                    continue
                for step in delta.get("trace", []):
                    yield step
                state.update({k: v for k, v in delta.items() if k != "trace"})
        d = state.get("final")
        if d is None:
            yield Answer(id=q.id, status=Status.UNKNOWN, llm_calls=state.get("llm_calls", 0))
            return
        yield Answer(id=q.id, status=Status(d.status), answer=d.answer, quote=d.quote, file=d.file,
                     llm_calls=state.get("llm_calls", 0))
