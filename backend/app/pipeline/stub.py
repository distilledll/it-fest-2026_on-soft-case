"""Заглушка, чтобы фронт и бэк жили без модели.
Ищет предложение с наибольшим пересечением слов вопроса — это не решение, а тестовые данные."""
import re

from app.pipeline.base import Context, collect
from app.schemas import Answer, Document, Question, Status, TraceStep

WORD = re.compile(r"[а-яёa-z]{4,}", re.IGNORECASE)


class StubPipeline:
    name = "stub"

    async def answer(self, q: Question, docs: list[Document], ctx: Context) -> Answer:
        return await collect(self.stream(q, docs, ctx))

    async def stream(self, q: Question, docs: list[Document], ctx: Context):
        words = {w.lower()[:6] for w in WORD.findall(q.question)}
        best, best_score = None, 0
        for d in docs:
            for sent in re.split(r"(?<=[.;])\s+", d.text):
                score = len(words & {w.lower()[:6] for w in WORD.findall(sent)})
                if score > best_score:
                    best, best_score = (sent.strip(), d.file), score
        yield TraceStep(node="retrieve", ok=best is not None, message=f"совпало слов: {best_score}")
        if not best or best_score < 2:
            yield Answer(id=q.id, status=Status.UNKNOWN)
            return
        sent, file = best
        nums = re.findall(r"\d+(?:[  ]\d{3})*(?:[.,]\d+)?", sent)
        yield Answer(id=q.id, status=Status.ANSWER, answer=nums[0] if nums else sent[:80],
                     quote=sent[:200], file=file)
