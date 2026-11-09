"""Small OpenAI-compatible/Jina clients; transport errors never expose headers or bodies."""
import json
import math
from .transport import ServiceUnavailable, post


class InvalidResponse(ValueError):
    pass


class CallLimit(RuntimeError):
    pass


class Qwen:
    def __init__(self, config, transport=post):
        self.config = config
        self.post = transport
        self.calls = 0
        self.usage = []

    def complete(self, messages):
        c = self.config
        if self.calls >= c.max_calls:
            raise CallLimit("Qwen call budget exhausted")
        self.calls += 1
        extra = dict(reasoning_effort=c.reasoning_effort) if c.reasoning_effort else {}
        data = self.post(c.qwen_base_url, "chat/completions", c.qwen_api_key,
                    dict(model=c.qwen_model, messages=messages, temperature=c.temperature,
                         max_tokens=c.output_tokens, response_format={"type": "json_object"}, **extra), c.timeout)
        self.usage.append(dict(model=data.get("model", c.qwen_model), usage=data.get("usage", {})))
        try:
            choice = data["choices"][0]
            if choice.get("finish_reason") == "length":
                raise InvalidResponse("Qwen output truncated")
            result = json.loads(choice["message"]["content"])
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (KeyError, IndexError, TypeError, ValueError):
            raise InvalidResponse("Qwen returned invalid or truncated JSON") from None


class Jina:
    def __init__(self, config, transport=post, rerank_config=None):
        self.config = config
        self.rerank_config = rerank_config or config
        self.post = transport

    def embeddings(self, texts, task):
        c = self.config
        if not c.jina_api_key and c.embedding_protocol == "jina":
            raise ServiceUnavailable("Jina key is not configured")
        payload = dict(model=c.embedding_model, input=texts)
        task = c.embedding_query_task if task == "retrieval.query" else c.embedding_passage_task
        if task:
            payload["task"] = task
        if c.embedding_dimensions:
            payload["dimensions"] = c.embedding_dimensions
        if c.embedding_protocol == "jina":
            payload["normalized"] = True
        data = self.post(c.jina_base_url, "embeddings", c.jina_api_key, payload, c.timeout, c.jina_auth_header)
        try:
            rows = sorted(data["data"], key=lambda x: x["index"])
            vectors = [x["embedding"] for x in rows]
            if [x['index'] for x in rows] != list(range(len(texts))) or not vectors:
                raise ValueError()
            dimension = len(vectors[0])
            if not dimension or (c.embedding_dimensions and dimension != c.embedding_dimensions) or any(len(v) != dimension or not all(isinstance(n, (int, float)) and math.isfinite(n) for n in v) for v in vectors):
                raise ValueError()
            return vectors
        except (KeyError, TypeError, ValueError):
            raise ServiceUnavailable("Invalid embeddings response") from None

    def rerank(self, question, chunks):
        c = self.rerank_config
        if not c.jina_api_key:
            raise ServiceUnavailable("Jina key is not configured")
        data = self.post(c.jina_base_url, "rerank", c.jina_api_key,
                    dict(model=c.reranker_model, query=question, documents=[x.text for x in chunks], top_n=len(chunks)), c.timeout, c.jina_auth_header)
        try:
            indices = [r['index'] for r in data['results']]
            if sorted(indices) != list(range(len(chunks))):
                raise ValueError()
            return [chunks[i] for i in indices]
        except (KeyError, IndexError, TypeError, ValueError):
            raise ServiceUnavailable("Invalid reranker response") from None
