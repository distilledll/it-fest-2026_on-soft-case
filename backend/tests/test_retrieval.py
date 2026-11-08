import asyncio
import json

from app import llm, retrieval
from app.llm import ModelProfile
from app.pipeline.agent import AgentPipeline
from app.pipeline.base import Context
from app.schemas import Document, Question, Status


def doc(file, text):
    return Document(package="T", file=file, text=text, encoding="utf-8", is_empty=not text.strip())


FILLER = "Стороны обязуются соблюдать конфиденциальность сведений. Заказчик в течение 5 рабочих дней рассматривает претензию.\n"
BIG = [doc("01_izveshchenie.txt", "Начальная (максимальная) цена контракта: 7 700 000,00 руб.\n"),
       doc("04_proekt_kontrakta.txt", FILLER * 1500 + "Гарантийный срок на результаты работ составляет 30 месяцев.\n"
           + FILLER * 1500)]
CTX = Context(models={"answer": ModelProfile(id="m", name="m", base_url="http://x", model="fake")})


def test_chunks_cover_text_with_overlap():
    chunks = retrieval.chunk_docs(BIG)
    joined = {c.file for c in chunks}
    assert joined == {"01_izveshchenie.txt", "04_proekt_kontrakta.txt"}
    assert all(len(c.text) <= retrieval.CHUNK_CHARS + 1 for c in chunks)
    assert any("Гарантийный срок на результаты работ составляет 30 месяцев" in c.text for c in chunks)


def test_bm25_finds_buried_fact_and_covers_every_file():
    chunks, info = asyncio.run(retrieval.search(["Какой гарантийный срок на результаты работ, в месяцах?"], BIG, CTX, k=3))
    assert any("30 месяцев" in c.text for c in chunks)
    assert {c.file for c in chunks} == {"01_izveshchenie.txt", "04_proekt_kontrakta.txt"}   # покрытие файлов
    assert info["mode"] == "hybrid"


def test_embeddings_are_cached(monkeypatch, tmp_path):
    calls = {"n": 0}

    async def fake_embed(profile, texts, task=None, dimensions=None):
        calls["n"] += 1
        return [[1.0 if "Гарантийный" in t or task == "retrieval.query" else 0.0, 0.0] for t in texts]

    monkeypatch.setattr(llm, "embed", fake_embed)
    retrieval._indexes.clear()
    ctx = Context(models={**CTX.models, "embed": ModelProfile(id="e", name="e", base_url="http://x", model="emb", embed_query_task="retrieval.query")})
    chunks, info = asyncio.run(retrieval.search(["гарантия"], BIG, ctx, k=2))
    assert info["mode"] == "hybrid+emb" and any("30 месяцев" in c.text for c in chunks)
    retrieval._indexes.clear()                      # новый процесс: индекс берётся с диска, не пересчитывается
    before = calls["n"]
    asyncio.run(retrieval.search(["гарантия"], BIG, ctx, k=2))
    assert calls["n"] == before + 1                 # +1 — только эмбеддинг запроса


def test_rerank_keeps_best(monkeypatch):
    chunks = [retrieval.Chunk("f", f"текст {i}") for i in range(5)]

    async def fake_chat(profile, messages, **kw):
        return json.dumps({"scores": {"3": 10, "1": 7}})

    monkeypatch.setattr(llm, "chat", fake_chat)
    kept, calls = asyncio.run(retrieval.rerank("q", chunks, CTX, keep=2))
    assert [c.text for c in kept] == ["текст 1", "текст 3"] and calls == 1


def test_research_before_absent_in_fragment_mode(monkeypatch):
    replies = [{"status": "нет в документах"}, {"queries": ["гарантийный срок результатов"]},
               {"status": "ответ", "answer": "30", "quote": "составляет 30 месяцев", "file": "04_proekt_kontrakta.txt"}]
    seen = []

    async def fake_chat(profile, messages, **kw):
        seen.append(messages)
        return json.dumps(replies.pop(0), ensure_ascii=False)

    monkeypatch.setattr(llm, "chat", fake_chat)
    retrieval._indexes.clear()
    ctx = Context(models=CTX.models, options={"llm_critic": False, "strategy": "full"})
    a = asyncio.run(AgentPipeline().answer(Question(id="x", package="T", question="Срок гарантии?"), BIG, ctx))
    assert a.status == Status.ANSWER and a.answer == "30"
    assert "research" in [t.node for t in a.trace] and a.llm_calls == 3


def test_no_research_when_documents_fit(monkeypatch):
    async def fake_chat(profile, messages, **kw):
        return json.dumps({"status": "нет в документах"})

    monkeypatch.setattr(llm, "chat", fake_chat)
    small = [doc("01.txt", "Цена 100 руб.")]
    a = asyncio.run(AgentPipeline().answer(Question(id="x", package="T", question="Срок гарантии?"), small,
                                           Context(models=CTX.models, options={"llm_critic": False})))
    assert a.status == Status.ABSENT and "research" not in [t.node for t in a.trace]


def test_embedding_failure_is_visible(monkeypatch):
    """Чужой API эмбеддингов отклонил запрос — поиск работает по словам, а в trace видно почему."""
    async def broken(profile, texts, task=None, dimensions=None):
        raise ValueError("unknown field: task")

    monkeypatch.setattr(llm, "embed", broken)
    retrieval._indexes.clear()
    ctx = Context(models={**CTX.models, "embed": ModelProfile(id="e2", name="e", base_url="http://y", model="emb")})
    chunks, info = asyncio.run(retrieval.search(["гарантия"], BIG, ctx, k=2))
    assert info["mode"] == "hybrid" and "unknown field" in info["embed_error"]
