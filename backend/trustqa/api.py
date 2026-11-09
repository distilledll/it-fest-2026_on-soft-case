"""Small OpenAI-compatible/Jina clients; transport errors never expose headers or bodies."""
import json
import math
import time
import urllib.error
import urllib.request

# The gateway WAF rejects requests with the default Python-urllib User-Agent (HTTP 403).
USER_AGENT = "trustqa/0.1"
RETRYABLE_HTTP = {429, 500, 502, 503, 504}


class ServiceUnavailable(RuntimeError):
    pass


class InvalidResponse(ValueError):
    pass


class CallLimit(RuntimeError):
    pass


def post(base, endpoint, key, payload, timeout, auth_header="Authorization", attempts=3):
    url = base.rstrip("/") + "/" + endpoint
    if auth_header not in ('Authorization', 'X-API-Key'):
        raise ValueError('Unsupported API authentication header')
    auth = {auth_header: 'Bearer ' + key if auth_header == 'Authorization' else key} if key else {}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={
        "Content-Type": "application/json", "User-Agent": USER_AGENT, **auth})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code in RETRYABLE_HTTP and attempt + 1 < attempts:
                time.sleep(min(2 ** attempt, 10))
                continue
            raise ServiceUnavailable(f"{endpoint}: HTTP {exc.code}") from None
        except (OSError, ValueError) as exc:
            if attempt + 1 < attempts:
                time.sleep(min(2 ** attempt, 10))
                continue
            raise ServiceUnavailable(f"{endpoint}: {type(exc).__name__}") from None


class Qwen:
    def __init__(self, config):
        self.config = config
        self.calls = 0
        self.usage = []

    def complete(self, messages):
        c = self.config
        if self.calls >= c.max_calls:
            raise CallLimit("Qwen call budget exhausted")
        self.calls += 1
        extra = dict(reasoning_effort=c.reasoning_effort) if c.reasoning_effort else {}
        data = post(c.qwen_base_url, "chat/completions", c.qwen_api_key,
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
    def __init__(self, config):
        self.config = config

    def embeddings(self, texts, task):
        c = self.config
        if not c.jina_api_key:
            raise ServiceUnavailable("Jina key is not configured")
        data = post(c.jina_base_url, "embeddings", c.jina_api_key,
                    dict(model=c.embedding_model, task=task, input=texts,
                         dimensions=c.embedding_dimensions, normalized=True), c.timeout, c.jina_auth_header)
        try:
            rows = sorted(data["data"], key=lambda x: x["index"])
            vectors = [x["embedding"] for x in rows]
            if [x['index'] for x in rows] != list(range(len(texts))) or not vectors:
                raise ValueError()
            dimension = len(vectors[0])
            if dimension != c.embedding_dimensions or any(len(v) != dimension or not all(isinstance(n, (int, float)) and math.isfinite(n) for n in v) for v in vectors):
                raise ValueError()
            return vectors
        except (KeyError, TypeError, ValueError):
            raise ServiceUnavailable("Invalid embeddings response") from None

    def rerank(self, question, chunks):
        c = self.config
        if not c.jina_api_key:
            raise ServiceUnavailable("Jina key is not configured")
        data = post(c.jina_base_url, "rerank", c.jina_api_key,
                    dict(model=c.reranker_model, query=question, documents=[x.text for x in chunks], top_n=len(chunks)), c.timeout, c.jina_auth_header)
        try:
            indices = [r['index'] for r in data['results']]
            if sorted(indices) != list(range(len(chunks))):
                raise ValueError()
            return [chunks[i] for i in indices]
        except (KeyError, IndexError, TypeError, ValueError):
            raise ServiceUnavailable("Invalid reranker response") from None
