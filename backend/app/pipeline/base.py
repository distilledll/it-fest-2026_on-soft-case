"""Интерфейс, который реализует агент (LangGraph). Бэк знает только про него.

Новый пайплайн: модуль в app/pipeline/, класс с методами answer/stream, строка в PIPELINES.
"""
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from importlib import import_module
from typing import Protocol

from app.verify import guard
from app.llm import ModelProfile
from app.schemas import Answer, Document, Question, TraceStep


@dataclass
class Context:
    """Что пайплайн получает от бэка помимо вопроса и документов."""
    models: dict[str, ModelProfile] = field(default_factory=dict)  # answer | critic | embed | rerank
    options: dict = field(default_factory=dict)                    # флаги: какие критики включены и т.п.

    def model(self, role: str) -> ModelProfile:
        if role in self.models:
            return self.models[role]
        if "answer" in self.models:
            return self.models["answer"]
        raise RuntimeError(f"не выбрана модель для роли {role}")


class Pipeline(Protocol):
    name: str

    async def answer(self, q: Question, docs: list[Document], ctx: Context) -> Answer:
        """Ответ на один вопрос. Исключения можно не ловить — бэк превратит их в «не знаю»."""

    def stream(self, q: Question, docs: list[Document], ctx: Context) -> AsyncIterator[TraceStep | Answer]:
        """Шаги по мере выполнения (для фронта через SSE), последним элементом — Answer."""


PIPELINES = {
    "stub": ("app.pipeline.stub", "StubPipeline", "Заглушка без модели"),
    "direct": ("app.pipeline.baseline", "DirectPipeline", "Прямой запрос с четырьмя статусами"),
    "baseline": ("app.pipeline.baseline", "BaselinePipeline", "«Было»: один запрос, вся закупка, без проверок"),
    "hybrid": ("app.pipeline.hybrid", "HybridPipeline", "Агент + TrustQA при ответе «не знаю»"),
    "agent": ("app.pipeline.agent", "AgentPipeline", "LangGraph: retrieve → ответ → критики → исправление"),
}


def available() -> list[dict]:
    out = []
    for name, (mod, _, title) in PIPELINES.items():
        try:
            import_module(mod)
            ok = True
        except ImportError:
            ok = False
        out.append({"name": name, "title": title, "available": ok})
    return out


class GuardedPipeline:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.name = pipeline.name

    async def answer(self, q, docs, ctx):
        return guard(await self.pipeline.answer(q, docs, ctx), docs, q.question)

    async def stream(self, q, docs, ctx):
        async for item in self.pipeline.stream(q, docs, ctx):
            if isinstance(item, Answer):
                before = len(item.trace)
                item = guard(item, docs, q.question)
                for step in item.trace[before:]:
                    yield step
                item.trace = item.trace[:before]
            yield item


def get_pipeline(name: str, *, use_guard: bool = False) -> Pipeline:
    if name not in PIPELINES:
        raise ValueError(f"неизвестный пайплайн: {name}")
    mod, cls, _ = PIPELINES[name]
    factory = getattr(import_module(mod), cls)
    if name == "hybrid":
        return factory(get_pipeline("agent", use_guard=use_guard), use_guard=use_guard)
    pipeline = factory()
    return GuardedPipeline(pipeline) if use_guard else pipeline


async def collect(stream: AsyncIterator[TraceStep | Answer]) -> Answer:
    """answer() через stream(): шаги складываются в Answer.trace."""
    steps, result = [], None
    async for item in stream:
        if isinstance(item, Answer):
            result = item
        else:
            steps.append(item)
    if result is None:
        raise RuntimeError("пайплайн не вернул Answer")
    result.trace = steps + result.trace
    return result
