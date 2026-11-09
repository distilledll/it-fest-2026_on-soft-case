from collections import Counter
from hashlib import sha256
from pathlib import Path
import json
import math
import re
import sqlite3
from .api import ServiceUnavailable


def terms(text):
    # Lightweight prefix stemming retains recall for inflected Russian procurement terms.
    return [t[:6] if len(t) > 6 else t for t in re.findall(r"[а-яёa-z0-9]+", text.lower())]


def bm25(question, chunks):
    docs = [Counter(terms(c.text)) for c in chunks]
    avg = sum(sum(d.values()) for d in docs) / max(len(docs), 1)
    query = set(terms(question))
    df = Counter(t for d in docs for t in d if t in query)
    def score(d):
        size = sum(d.values())
        return sum(math.log(1 + (len(docs) - df[t] + .5) / (df[t] + .5)) * d[t] * 2.5 /
                   (d[t] + 1.5 * (.25 + .75 * size / max(avg, 1))) for t in query if d[t])
    return sorted(range(len(chunks)), key=lambda i: (-score(docs[i]), i))


class EmbeddingCache:
    def __init__(self, directory):
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.path = Path(directory) / "embeddings.sqlite3"
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute("CREATE TABLE IF NOT EXISTS embeddings (key TEXT PRIMARY KEY, vector TEXT NOT NULL)")

    def vectors(self, texts, config, client, task):
        keys = [sha256(json.dumps([config.jina_base_url, config.embedding_model, config.embedding_version, config.embedding_dimensions, task, t], ensure_ascii=False).encode()).hexdigest() for t in texts]
        with sqlite3.connect(self.path, timeout=30) as db:
            found = {key: json.loads(row[0]) for key in set(keys)
                     if (row := db.execute("SELECT vector FROM embeddings WHERE key=?", (key,)).fetchone())}
        missing = list(dict.fromkeys(k for k in keys if k not in found))
        by_key = dict(zip(keys, texts))
        for start in range(0, len(missing), 32):
            batch = missing[start:start + 32]
            values = client.embeddings([by_key[k] for k in batch], task)
            found.update(zip(batch, values))
            with sqlite3.connect(self.path, timeout=30) as db:
                db.executemany("INSERT OR REPLACE INTO embeddings VALUES (?, ?)", [(k, json.dumps(v)) for k, v in zip(batch, values)])
        return [found[k] for k in keys]


def cosine(a, b):
    if len(a) != len(b):
        raise ServiceUnavailable("Embedding dimensions differ")
    denominator = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
    return sum(x*y for x, y in zip(a, b)) / denominator if denominator else 0


class Retriever:
    def __init__(self, config, client):
        self.config, self.client = config, client
        self.cache = EmbeddingCache(config.cache_dir)

    def search(self, package, question):
        chunks = package.chunks
        events = []
        if not chunks:
            return [], "empty", events
        try:
            vectors = self.cache.vectors([c.text for c in chunks], self.config, self.client, "retrieval.passage")
            query = self.cache.vectors([question], self.config, self.client, "retrieval.query")[0]
            ranking = sorted(range(len(chunks)), key=lambda i: -cosine(query, vectors[i]))
            mode = "jina"
        except ServiceUnavailable as exc:
            if not self.config.allow_bm25:
                raise
            ranking, mode = bm25(question, chunks), "bm25"
            events.append(dict(reason=str(exc), mode=mode))
        counts, selected = Counter(), []
        for i in ranking:
            if counts[chunks[i].file] < self.config.per_file_k:
                selected.append(chunks[i])
                counts[chunks[i].file] += 1
        try:
            selected = self.client.rerank(question, selected)
            mode += "+reranker"
        except ServiceUnavailable as exc:
            events.append(dict(reason=str(exc), mode=mode + "+vector_order" if mode == "jina" else mode + "+lexical_order"))
            mode += "+unreranked"
        return selected, mode, events
