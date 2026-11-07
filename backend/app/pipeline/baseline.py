"""Шаг 1 кейса — точка «было»: модель «как есть», один запрос со всей закупкой, без проверок.
Запускать с guard=False, иначе это уже не «было». Промпт нарочно простой и не меняется
по ходу хакатона, чтобы сравнение оставалось честным."""
from app.llm import chat, parse_json
from app.pipeline.base import Context, collect
from app.schemas import Answer, Document, Question, Status, TraceStep

PROMPT = """Ниже документы закупки. Ответь на вопрос.
Верни JSON: {{"status": "ответ" | "расхождение" | "нет в документах" | "не знаю",
"answer": "...", "quote": "дословная цитата из документа", "file": "имя файла"}}.
Числа пиши цифрами, даты как 27.11.2026 10:00, на вопросы да/нет — "да" или "нет".

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
        raw = await chat(prof, [{"role": "user",
                                 "content": PROMPT.format(docs=render_docs(docs), question=q.question)}])
        try:
            j = parse_json(raw)
            status = Status(j.get("status", "не знаю"))
        except ValueError:
            yield TraceStep(node="answer", ok=False, message="модель вернула не JSON", data={"raw": raw[:500]})
            yield Answer(id=q.id, status=Status.UNKNOWN, llm_calls=1)
            return
        yield TraceStep(node="answer", ok=True, message=prof.model, data={"raw": raw[:500]})
        yield Answer(id=q.id, status=status, answer=str(j.get("answer", "")), quote=str(j.get("quote", "")),
                     file=str(j.get("file", "")), llm_calls=1)
