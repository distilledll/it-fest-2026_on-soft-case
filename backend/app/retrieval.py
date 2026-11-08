"""Встроенный поиск фрагментов для документов, которые не влезают в контекст.

Запасной вариант по умолчанию: если в app.rag появится свой retrieve(), агент возьмёт его.
  - чанки по пунктам документа (файл + позиция), с перекрытием;
  - BM25 по основам слов и числам — точные термины и суммы;
  - эмбеддинги (роль embed), если назначены; индекс закупки кэшируется на диске;
  - слияние рейтингов (RRF) + гарантированное покрытие каждого файла (иначе не увидеть второе значение
    для расхождения);
  - реранк моделью (опция rerank) — в шлюзе нет реранкера.
"""
import asyncio
import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass

from app import llm
from app.config import settings
from app.schemas import Document

WORD = re.compile(r"[а-яёa-z]{3,}|\d+(?:[  ]\d{3})*(?:[.,]\d+)?", re.I)
CHUNK_CHARS = 900
OVERLAP = 150


@dataclass
class Chunk:
    file: str
    text: str
    start: int = 0
    score: float = 0.0


def tokens(text: str) -> list[str]:
    out = []
    for t in WORD.findall(text.lower().replace("ё", "е")):
        if t[0].isdigit():
            out.append(re.sub(r"[  ]", "", t).replace(",", "."))
        else:
            out.append(t[:5])           # грубая основа: «обеспечения» / «обеспечение» → «обесп»
    return out


def chunk_docs(docs: list[Document]) -> list[Chunk]:
    out = []
    for d in docs:
        if d.is_empty:
            continue
        text, pos = d.text, 0
        while pos < len(text):
            end = min(len(text), pos + CHUNK_CHARS)
            if end < len(text):            # режем по концу строки/предложения, чтобы не рвать пункт
                cut = max(text.rfind("\n", pos + CHUNK_CHARS // 2, end), text.rfind(". ", pos + CHUNK_CHARS // 2, end))
                if cut > pos:
                    end = cut + 1
            out.append(Chunk(d.file, text[pos:end], pos))
            if end >= len(text):
                break
            pos = max(end - OVERLAP, pos + 1)
    return out


class BM25:
    def __init__(self, docs_tokens: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(t) for t in docs_tokens]
        self.len = [len(t) for t in docs_tokens]
        self.avg = sum(self.len) / max(len(self.len), 1)
        df = Counter(w for t in docs_tokens for w in set(t))
        n = len(docs_tokens)
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}

    def scores(self, query: list[str]) -> list[float]:
        out = []
        for tf, ln in zip(self.tf, self.len):
            s = 0.0
            for w in query:
                if w in tf:
                    f = tf[w]
                    s += self.idf[w] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * ln / self.avg))
            out.append(s)
        return out


@dataclass
class Index:
    chunks: list[Chunk]
    bm25: BM25
    vectors: list[list[float]] | None = None


_indexes: dict[str, Index] = {}
_locks: dict[str, asyncio.Lock] = {}


def _key(docs: list[Document], embed_model: str) -> str:
    h = hashlib.sha256(embed_model.encode())
    for d in sorted(docs, key=lambda x: x.file):
        h.update(d.file.encode())
        h.update(d.text.encode())
    return h.hexdigest()[:24]


async def get_index(docs: list[Document], ctx) -> Index:
    """Индекс закупки: строится один раз (на процесс — в памяти, эмбеддинги — ещё и на диске)."""
    embed = ctx.models.get("embed") if ctx else None
    key = _key(docs, embed.model if embed else "")
    if key in _indexes:
        return _indexes[key]
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        if key in _indexes:
            return _indexes[key]
        chunks = chunk_docs(docs)
        idx = Index(chunks, BM25([tokens(c.text) for c in chunks]))
        if embed:
            cache = settings.storage_dir / "index" / f"{key}.json"
            if cache.exists():
                idx.vectors = json.loads(cache.read_text())
            else:
                try:
                    vecs = await llm.embed(embed, [c.text for c in chunks], task="retrieval.passage",
                                           dimensions=settings.embed_dimensions)
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_text(json.dumps(vecs))
                    idx.vectors = vecs
                except Exception:           # эмбеддинги недоступны — работаем на BM25
                    idx.vectors = None
        _indexes[key] = idx
        return idx


def _cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))   # векторы нормализованы шлюзом


async def search(queries: list[str], docs: list[Document], ctx, k: int = 12, per_file: int = 2) -> tuple[list[Chunk], dict]:
    """Гибридный поиск по нескольким формулировкам вопроса; RRF + покрытие каждого файла."""
    idx = await get_index(docs, ctx)
    if not idx.chunks:
        return [], {"mode": "hybrid", "chunks": 0}
    rrf = [0.0] * len(idx.chunks)
    for q in queries:
        rankings = [idx.bm25.scores(tokens(q))]
        if idx.vectors:
            try:
                qv = (await llm.embed(ctx.models["embed"], [q], task="retrieval.query",
                                      dimensions=settings.embed_dimensions))[0]
                rankings.append([_cos(qv, v) for v in idx.vectors])
            except Exception:
                pass
        for scores in rankings:
            order = sorted(range(len(scores)), key=lambda i: -scores[i])
            for rank, i in enumerate(order[:200]):
                rrf[i] += 1 / (60 + rank)
    order = sorted(range(len(rrf)), key=lambda i: -rrf[i])
    picked = order[:k]
    for f in {c.file for c in idx.chunks}:               # покрытие: лучшие фрагменты каждого файла
        best = [i for i in order if idx.chunks[i].file == f][:per_file]
        picked += [i for i in best if i not in picked]
    picked = sorted(set(picked), key=lambda i: (idx.chunks[i].file, idx.chunks[i].start))
    out = [Chunk(idx.chunks[i].file, idx.chunks[i].text, idx.chunks[i].start, rrf[i]) for i in picked]
    return out, {"mode": "hybrid+emb" if idx.vectors else "hybrid", "chunks": len(out), "queries": len(queries)}


RERANK = """Оцени, насколько каждый фрагмент документа помогает ответить на вопрос, по шкале 0–10.
10 — фрагмент прямо содержит ответ; 0 — не относится к вопросу. Похожие слова без ответа — низкая оценка.

Вопрос: {question}

{fragments}

Верни только JSON: {{"scores": {{"<номер>": оценка, ...}}}}"""


async def rerank(question: str, chunks: list[Chunk], ctx, keep: int = 10) -> tuple[list[Chunk], int]:
    """Реранк моделью (роль rerank, иначе critic/answer): один запрос на все фрагменты."""
    if len(chunks) <= keep:
        return chunks, 0
    frags = "\n\n".join(f"[{i}] ({c.file}) {c.text[:700]}" for i, c in enumerate(chunks))
    raw = await llm.chat(ctx.model("rerank"), json=True, messages=[
        {"role": "user", "content": RERANK.format(question=question, fragments=frags)}])
    try:
        scores = {int(k): float(v) for k, v in llm.parse_json(raw).get("scores", {}).items()}
    except (ValueError, TypeError, AttributeError):
        return chunks[:keep], 1
    best = sorted(range(len(chunks)), key=lambda i: -scores.get(i, 0))[:keep]
    return [chunks[i] for i in sorted(best)], 1
