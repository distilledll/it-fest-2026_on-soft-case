"""Вопрос строкой ввода — в том числе живой вопрос жюри на защите."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app import datasets
from app.config import settings
from app.datasets import DatasetError
from app.ingest import load_package
from app.pipeline.base import get_pipeline
from app.runs import answer_one, make_context
from app.schemas import Answer, Question, TraceStep
from app.verify import guard

router = APIRouter(prefix="/api/ask", tags=["ask"])

SSE_DOC = {200: {"description": (
    "Поток Server-Sent Events. События `step` — шаги агента (схема TraceStep), по мере работы; "
    "последним приходит одно событие `answer` (схема Answer). Пример:\n\n"
    "```\nevent: step\ndata: {\"node\": \"prepare\", \"ok\": true, \"message\": \"режим: full\", \"data\": {}}\n\n"
    "event: step\ndata: {\"node\": \"critic_conflict\", \"ok\": false, \"message\": \"в документах разные значения…\"}\n\n"
    "event: answer\ndata: {\"id\": \"adhoc\", \"status\": \"расхождение\", \"answer\": \"60 и 75\", "
    "\"quote\": \"…\", \"file\": \"01_izveshchenie.txt\", \"trace\": [], \"llm_calls\": 3}\n```"),
    "content": {"text/event-stream": {"schema": {"type": "string"}}}}}




class AskIn(BaseModel):
    dataset: str = "sample"
    package: str
    question: str = Field(min_length=3, max_length=2000)
    pipeline: str | None = None
    roles: dict[str, str] | None = None     # {"answer": "<profile id>", ...} — переопределить модели
    options: dict = Field(default_factory=dict)
    guard: bool = True


def _prepare(body: AskIn):
    try:
        root = datasets.path_of(body.dataset)
        ctx = make_context(body.roles, body.options)
        pipeline = get_pipeline(body.pipeline or settings.pipeline)
    except (DatasetError, KeyError, ValueError) as e:
        raise HTTPException(422, str(e))
    if body.package not in datasets.info(body.dataset)["packages"]:
        raise HTTPException(404, f"нет закупки {body.package}")
    return root, ctx, pipeline, Question(id="adhoc", package=body.package, question=body.question)


@router.post("", response_model=Answer)
async def ask(body: AskIn):
    root, ctx, pipeline, q = _prepare(body)
    return await answer_one(pipeline, q, root, ctx, body.guard)


@router.post("/stream", responses=SSE_DOC, response_class=EventSourceResponse)
async def ask_stream(body: AskIn):
    """SSE: события `step` (TraceStep) по мере работы агента и финальное `answer` (Answer)."""
    root, ctx, pipeline, q = _prepare(body)
    docs = list(load_package(root, q.package))

    async def gen():
        steps = []
        try:
            async for item in pipeline.stream(q, docs, ctx):
                if isinstance(item, Answer):
                    item.trace = steps + item.trace
                    if body.guard:
                        before = len(item.trace)
                        item = guard(item, docs, q.question)
                        for s in item.trace[before:]:
                            yield {"event": "step", "data": s.model_dump_json()}
                    yield {"event": "answer", "data": item.model_dump_json()}
                    return
                steps.append(item)
                yield {"event": "step", "data": item.model_dump_json()}
        except Exception as e:
            err = TraceStep(node="error", ok=False, message=f"{type(e).__name__}: {e}"[:500])
            yield {"event": "step", "data": err.model_dump_json()}
            yield {"event": "answer", "data": Answer(id=q.id, status="не знаю", trace=steps + [err]).model_dump_json()}

    return EventSourceResponse(gen())
