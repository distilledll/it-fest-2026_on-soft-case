"""Что показать модели: вся закупка, если влезает, иначе — фрагменты от ретривера.

Сюда же — защита от «трудных файлов»: пустые файлы помечаются, подозрительные инструкции
в тексте вырезаются из контекста (в самих документах остаются — цитаты сверяются по оригиналу).
"""
import re
from dataclasses import dataclass

from app.ingest import INJECTION_RE
from app.pipeline.agent.critics import is_amendment_doc
from app.schemas import Document

WORD = re.compile(r"[а-яёa-z0-9]{3,}", re.IGNORECASE)


@dataclass
class Chunk:
    file: str
    text: str
    score: float = 0.0


def redact(text: str) -> tuple[str, int]:
    """Предложения с инструкциями для ИИ заменяем пометкой. Возвращает (текст, сколько вырезано)."""
    n = 0

    def sub(m):
        nonlocal n
        n += 1
        return "[фрагмент удалён: похоже на инструкцию для ИИ, это не часть условий закупки]"

    sents = re.split(r"(?<=[.!?\n])", text)
    out = "".join(sub(None) if INJECTION_RE.search(s) else s for s in sents)
    return out, n


def keyword_chunks(question: str, docs: list[Document], k: int = 12, size: int = 600) -> list[Chunk]:
    """Запасной ретривер без модели: абзацы с наибольшим пересечением основ слов вопроса."""
    qw = {w.lower()[:5] for w in WORD.findall(question)}
    chunks = []
    for d in docs:
        paras = [p for p in re.split(r"\n\s*\n|\n(?=\d+\.\d*\.?\s)", d.text) if p.strip()]
        for p in paras:
            for i in range(0, len(p), size):
                part = p[i:i + size + 100]
                score = len(qw & {w.lower()[:5] for w in WORD.findall(part)})
                if score:
                    chunks.append(Chunk(d.file, part, score))
    return sorted(chunks, key=lambda c: -c.score)[:k]


def retrieve(question: str, docs: list[Document], ctx, k: int = 12) -> tuple[list[Chunk], str]:
    """RAG от раг-человека, если он есть (app.rag.retrieve), иначе — keyword fallback."""
    try:
        from app.rag import retrieve as rag_retrieve  # type: ignore[attr-defined]
    except ImportError:
        return keyword_chunks(question, docs, k), "keyword"
    raw = rag_retrieve(question, docs, ctx, k=k)
    return [c if isinstance(c, Chunk) else Chunk(c.file, c.text, getattr(c, "score", 0.0)) for c in raw], "rag"


def build_context(question: str, docs: list[Document], ctx, budget_chars: int) -> tuple[str, dict]:
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

    if total <= budget_chars:
        for d in rest:
            t, n = redact(d.text)
            info["redacted"] += n
            parts.append(f"=== Файл: {d.file} ===\n{t}")
    else:
        chunks, info["mode"] = retrieve(question, rest, ctx)
        for c in chunks:
            t, n = redact(c.text)
            info["redacted"] += n
            parts.append(f"=== Фрагмент файла: {c.file} ===\n{t}")
        info["chunks"] = len(chunks)

    for f in info["empty"]:
        parts.append(f"=== Файл: {f} — ПУСТОЙ, текста нет ===")
    return "\n\n".join(parts), info
