"""Что показать модели: вся закупка, если влезает, иначе — фрагменты от ретривера.

Сюда же — защита от «трудных файлов»: пустые файлы помечаются, подозрительные инструкции
в тексте вырезаются из контекста (в самих документах остаются — цитаты сверяются по оригиналу).

Ретривер: app.rag.retrieve(question, docs, ctx, k=...) от раг-человека, если есть (sync или async,
возвращает объекты с .file/.text), иначе встроенный гибридный поиск app.retrieval.search.
"""
import inspect
import re

from app import retrieval
from app.ingest import redact
from app.pipeline.agent.critics import is_amendment_doc
from app.retrieval import Chunk
from app.schemas import Document

WORD = re.compile(r"[а-яёa-z0-9]{3,}", re.IGNORECASE)


def keyword_chunks(question: str, docs: list[Document], k: int = 12, size: int = 600) -> list[Chunk]:
    """Простейший ретривер без модели (опция retriever=keyword — для сравнения с гибридным)."""
    qw = {w.lower()[:5] for w in WORD.findall(question)}
    chunks = []
    for d in docs:
        paras = [p for p in re.split(r"\n\s*\n|\n(?=\d+\.\d*\.?\s)", d.text) if p.strip()]
        for p in paras:
            for i in range(0, len(p), size):
                part = p[i:i + size + 100]
                score = len(qw & {w.lower()[:5] for w in WORD.findall(part)})
                if score:
                    chunks.append(Chunk(d.file, part, 0, score))
    return sorted(chunks, key=lambda c: -c.score)[:k]


async def retrieve(question: str, docs: list[Document], ctx, k: int = 12,
                   queries: list[str] | None = None) -> tuple[list[Chunk], dict]:
    try:
        from app.rag import retrieve as rag_retrieve  # type: ignore[attr-defined]
    except ImportError:
        rag_retrieve = None
    if rag_retrieve is not None:
        raw = rag_retrieve(question, docs, ctx, k=k)
        if inspect.isawaitable(raw):
            raw = await raw
        return [Chunk(c.file, c.text, getattr(c, "start", 0), getattr(c, "score", 0.0)) for c in raw], {"mode": "rag"}
    opts = (ctx.options or {}) if ctx else {}
    if opts.get("retriever") == "keyword":
        return keyword_chunks(question, docs, k), {"mode": "keyword"}
    chunks, info = await retrieval.search(queries or [question], docs, ctx, k=k * 2 if opts.get("rerank") else k)
    if opts.get("rerank"):
        chunks, calls = await retrieval.rerank(question, chunks, ctx, keep=k)
        info.update(rerank=True, rerank_calls=calls)
    return chunks, info


async def build_context(question: str, docs: list[Document], ctx, budget_chars: int,
                        queries: list[str] | None = None, k: int = 12) -> tuple[str, dict]:
    """Текст для промпта + сведения для trace (режим, вырезанные инъекции, пустые файлы)."""
    info = {"mode": "full", "redacted": 0, "empty": [d.file for d in docs if d.is_empty]}
    amend = [d for d in docs if is_amendment_doc(d) and not d.is_empty]
    rest = [d for d in docs if d not in amend and not d.is_empty]
    total = sum(len(d.text) for d in docs)

    parts = []
    for d in amend:  # изменения — первыми и всегда целиком: они главнее
        t, n = redact(d.text)
        info["redacted"] += n
        parts.append(f"=== Файл: {d.file} (ИЗМЕНЕНИЯ ИЗВЕЩЕНИЯ — имеют приоритет над остальными) ===\n{t}")

    if total <= budget_chars and not queries:
        for d in rest:
            t, n = redact(d.text)
            info["redacted"] += n
            parts.append(f"=== Файл: {d.file} ===\n{t}")
    else:
        chunks, rinfo = await retrieve(question, rest, ctx, k=k, queries=queries)
        info.update(rinfo)
        info["files"] = sorted({c.file for c in chunks})
        for c in chunks:
            t, n = redact(c.text)
            info["redacted"] += n
            parts.append(f"=== Фрагмент файла: {c.file} ===\n{t}")
        info["chunks"] = len(chunks)

    for f in info["empty"]:
        parts.append(f"=== Файл: {f} — ПУСТОЙ, текста нет ===")
    return "\n\n".join(parts), info
