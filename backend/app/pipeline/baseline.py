"""Шаг 1 кейса — точка «было»: модель «как есть».

Один запрос: все документы закупки + вопрос. Никаких «не знаю» / «нет в документах», никаких проверок —
кейс прямо называет это улучшениями шага 2. Цитату просим только потому, что без неё check.py
засчитывает обман автоматически, и сравнение потеряло бы смысл.

Запускать с guard=False. Промпт не меняется по ходу хакатона, чтобы «было» оставалось точкой отсчёта.
"""
from app.llm import chat, parse_json
from app.pipeline.base import Context, collect
from app.schemas import Answer, Document, Question, Status, TraceStep

PROMPT = """Ниже документы закупки. Ответь на вопрос по ним.
Верни JSON: {{"answer": "ответ", "quote": "цитата из документа, на которой основан ответ", "file": "имя файла"}}.

{docs}

Вопрос: {question}"""


def render_docs(docs: list[Document]) -> str:
    return "\n\n".join(f"=== Файл: {d.file} ===\n{d.text}" for d in docs)


class BaselinePipeline:
    name = "baseline"

    async def answer(self, q: Question, docs: list[Document], ctx: Context) -> Answer:
        return await collect(self.stream(q, docs, ctx))

    async def stream(self, q: Question, docs: list[Document], ctx: Context):
        prof = ctx.model("answer")
        raw = await chat(prof, json=True, messages=[
            {"role": "user", "content": PROMPT.format(docs=render_docs(docs), question=q.question)}])
        try:
            j = parse_json(raw)
        except ValueError:
            # «как есть»: модель ответила текстом — его и сдаём
            yield TraceStep(node="answer", ok=False, message="модель вернула не JSON", data={"raw": raw[:500]})
            yield Answer(id=q.id, status=Status.ANSWER, answer=raw.strip()[:300], llm_calls=1)
            return
        yield TraceStep(node="answer", ok=True, message=prof.model, data={"raw": raw[:500]})
        yield Answer(id=q.id, status=Status.ANSWER, answer=str(j.get("answer", "")), quote=str(j.get("quote", "")),
                     file=str(j.get("file", "")), llm_calls=1)
