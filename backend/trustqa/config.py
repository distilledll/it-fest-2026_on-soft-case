from dataclasses import asdict, dataclass
import os
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Config:
    qwen_base_url: str = ""
    qwen_api_key: str = ""
    qwen_model: str = ""
    qwen_model_version: str = ""
    qwen_tokenizer: str = ""
    context_tokens: int = 32768
    output_tokens: int = 3000
    max_calls: int = 16
    timeout: float = 120
    temperature: float = 0
    reasoning_effort: str = ""
    jina_base_url: str = "https://api.jina.ai/v1"
    jina_api_key: str = ""
    jina_auth_header: str = "Authorization"
    embedding_dimensions: int = 1024
    embedding_model: str = "jina-embeddings-v3"
    embedding_version: str = "jina-embeddings-v3"
    reranker_model: str = "jina-reranker-v2-base-multilingual"
    allow_bm25: bool = False
    parallel: int = 1
    chunk_chars: int = 1800
    overlap: int = 240
    per_file_k: int = 4
    cache_dir: str = ".cache/trustqa"

    @classmethod
    def from_env(cls):
        names = {
            "context_tokens": "QWEN_CONTEXT_TOKENS", "output_tokens": "QWEN_MAX_OUTPUT_TOKENS",
            "max_calls": "QWEN_MAX_CALLS", "timeout": "QWEN_TIMEOUT",
            "temperature": "QWEN_TEMPERATURE", "reasoning_effort": "QWEN_REASONING_EFFORT",
            "embedding_model": "JINA_EMBEDDING_MODEL", "embedding_version": "JINA_EMBEDDING_VERSION",
            "reranker_model": "JINA_RERANKER_MODEL",
            "embedding_dimensions": "JINA_EMBEDDING_DIMENSIONS",
            "parallel": "PARALLEL_REQUESTS", "overlap": "CHUNK_OVERLAP",
        }
        defaults = cls()
        values = {}
        for field, default in asdict(defaults).items():
            raw = os.getenv(names.get(field, field.upper()))
            if raw is not None:
                values[field] = raw.lower() in ("true", "1", "yes") if isinstance(default, bool) else type(default)(raw)
        bridge_key = os.getenv('BRIDGE_API_KEY')
        if bridge_key:
            values.setdefault('qwen_api_key', bridge_key)
            if (values.get('jina_base_url') and
                    urlsplit(values['jina_base_url']).netloc == urlsplit(values.get('qwen_base_url', '')).netloc):
                values.setdefault('jina_api_key', bridge_key)
        obj = cls(**values)
        if obj.jina_auth_header not in ('Authorization', 'X-API-Key'):
            raise ValueError('JINA_AUTH_HEADER must be Authorization or X-API-Key')
        if obj.reasoning_effort not in ('', 'low', 'medium', 'high'):
            raise ValueError('QWEN_REASONING_EFFORT must be low, medium or high')
        if obj.embedding_dimensions < 1:
            raise ValueError('JINA_EMBEDDING_DIMENSIONS must be positive')
        for url in (obj.qwen_base_url, obj.jina_base_url):
            if url:
                parsed = urlsplit(url)
                if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
                    raise ValueError('API URLs must be HTTP(S) endpoints without embedded credentials or query parameters')
        if not 0 <= obj.overlap < obj.chunk_chars or min(obj.max_calls, obj.parallel, obj.per_file_k) < 1:
            raise ValueError("Invalid chunking, call limit or parallelism")
        if obj.context_tokens <= obj.output_tokens + 256:
            raise ValueError("Context window must leave room for instructions and documents")
        return obj

    def public(self):
        return {k: v for k, v in asdict(self).items() if "api_key" not in k}

    def require_qwen(self):
        if not all((self.qwen_base_url, self.qwen_model, self.qwen_model_version)):
            raise ValueError("Set QWEN_BASE_URL, QWEN_MODEL and QWEN_MODEL_VERSION; no model is silently substituted")
