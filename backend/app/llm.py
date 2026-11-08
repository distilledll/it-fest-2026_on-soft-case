"""Профили моделей: base_url + model + ключ + заголовки. Любой OpenAI-совместимый API.

Роли — какой профиль для чего используется: answer, critic, embed, rerank.
Хранится в storage/models.json. Ключ лучше указывать через api_key_env (имя переменной в .env);
api_key в файле допустим (storage/ в .gitignore), но наружу через API никогда не отдаётся.
"""
import asyncio
import json
import logging
import time
import os
import re
import threading
import uuid
from typing import Any, Literal

import httpx
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, InternalServerError, RateLimitError
from pydantic import BaseModel, Field, model_validator

from app.config import settings

log = logging.getLogger("llm")

ROLES = ("answer", "critic", "embed", "rerank")


class ModelProfile(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str
    base_url: str
    model: str
    api_key: str = ""
    api_key_env: str = ""
    extra_headers: str = ""          # "User-Agent=...;X-Foo=bar" — шлюз может резать дефолтный UA SDK
    temperature: float = 0.0         # для честного «было/стало» — 0
    max_tokens: int | None = None
    # окно контекста модели в токенах (напр. 262144 у шлюза): от него считается, сколько текста закупки
    # модель читает целиком, а с какого размера агент переходит на фрагменты (map-reduce)
    context_tokens: int | None = None
    # По умолчанию рассуждения выключены (chat_template_kwargs.enable_thinking=false — vLLM/SGLang, Qwen3):
    # так советуют организаторы, ответ ~2 с вместо 20–40 с, точность агент добирает проверками.
    # Для API, которые не знают этого поля (напр. OpenAI), ставьте false.
    disable_thinking: bool = True
    json_mode: bool = True           # response_format={"type": "json_object"}, если API поддерживает
    reasoning_effort: str | None = None   # low | medium | high — для моделей с рассуждениями
    extra_body: dict[str, Any] = Field(default_factory=dict)
    # опции агента по умолчанию для этой модели, напр. {"strategy": "map"} для слабых моделей;
    # опции запроса/прогона их переопределяют
    agent_options: dict[str, Any] = Field(default_factory=dict)
    # chat — отвечает/проверяет (роли answer, critic); embedding — векторы для поиска (роль embed)
    kind: Literal["chat", "embedding"] = "chat"
    # для embedding: нестандартные поля запроса /embeddings. Не всякий API их принимает, поэтому
    # по умолчанию не отправляются (напр. для шлюза: "retrieval.query" / "retrieval.passage", 256)
    embed_query_task: str | None = None
    embed_passage_task: str | None = None
    embed_dimensions: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _guess_kind(cls, v):
        # профили, сохранённые до появления kind: модель с «embed» в имени — эмбеддинги
        if isinstance(v, dict) and "kind" not in v and "embed" in str(v.get("model", "")).lower():
            v = {**v, "kind": "embedding"}
        return v

    def public(self) -> dict:
        d = self.model_dump(exclude={"api_key"})
        d["has_key"] = bool(self.resolve_key())
        return d

    def resolve_key(self) -> str:
        return self.api_key or (os.environ.get(self.api_key_env, "") if self.api_key_env else "")

    def headers(self) -> dict[str, str]:
        out = {}
        for part in re.split(r"[;\n]", self.extra_headers or ""):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k.strip()] = v.strip()
        return out

    def client(self) -> AsyncOpenAI:
        """Один клиент на подключение (и event loop): соединения с API переиспользуются (keep-alive).
        Новый клиент на каждый запрос — это новое TCP+TLS-соединение на каждый вызов модели: сотни
        соединений в минуту с одного IP, и защита шлюза от DDoS блокирует IP на несколько минут."""
        loop = asyncio.get_running_loop()
        key = (id(loop), self.base_url, self.resolve_key(), self.extra_headers)
        c = _clients.get(key)
        if c is None:
            n = max(settings.llm_concurrency, 1)
            http = httpx.AsyncClient(limits=httpx.Limits(max_connections=n, max_keepalive_connections=n,
                                                         keepalive_expiry=60),
                                     timeout=settings.llm_timeout_s)
            c = AsyncOpenAI(base_url=self.base_url, api_key=self.resolve_key() or "none",
                            default_headers=self.headers(), timeout=settings.llm_timeout_s, max_retries=0,
                            http_client=http)
            _clients[key] = c
        return c

    def body(self) -> dict:
        b = dict(self.extra_body)
        if self.disable_thinking:
            b.setdefault("chat_template_kwargs", {})["enable_thinking"] = False
        return b


class Registry(BaseModel):
    profiles: list[ModelProfile] = Field(default_factory=list)
    roles: dict[str, str] = Field(default_factory=dict)  # роль -> id профиля


_lock = threading.Lock()


def _path():
    return settings.storage_dir / "models.json"


def load() -> Registry:
    p = _path()
    if p.exists():
        return Registry.model_validate_json(p.read_text(encoding="utf-8"))
    reg = Registry()
    if settings.llm_base_url and settings.llm_model:
        prof = ModelProfile(id="default", name="По умолчанию (.env)", base_url=settings.llm_base_url,
                            model=settings.llm_model, api_key_env=settings.llm_api_key_env,
                            extra_headers=settings.llm_extra_headers)
        reg.profiles.append(prof)
        reg.roles = {"answer": "default", "critic": "default"}
    if settings.embed_model:
        reg.profiles.append(ModelProfile(
            id="embedding", name="Эмбеддинги (.env)", kind="embedding", model=settings.embed_model,
            base_url=settings.embed_base_url or settings.llm_base_url,
            api_key_env=settings.embed_api_key_env or settings.llm_api_key_env,
            extra_headers=settings.llm_extra_headers))
        reg.roles["embed"] = "embedding"
    return reg


def save(reg: Registry) -> None:
    with _lock:
        _path().parent.mkdir(parents=True, exist_ok=True)
        tmp = _path().with_suffix(".tmp")
        tmp.write_text(reg.model_dump_json(indent=1), encoding="utf-8")
        tmp.replace(_path())


def get(profile_id: str) -> ModelProfile:
    for p in load().profiles:
        if p.id == profile_id:
            return p
    raise KeyError(profile_id)


def resolve_roles(overrides: dict[str, str] | None = None) -> dict[str, ModelProfile]:
    """Роли для конкретного запроса/прогона: дефолты из models.json + переопределения из запроса."""
    reg = load()
    by_id = {p.id: p for p in reg.profiles}
    ids = {**reg.roles, **(overrides or {})}
    out = {}
    for role, pid in ids.items():
        if pid not in by_id:
            raise KeyError(f"роль {role}: нет профиля {pid}")
        out[role] = by_id[pid]
    return out


# Шлюз может ограничивать число одновременных запросов на организацию (у нас — 1). Один семафор на процесс
# для всех ролей и всех прогонов; повтор после 429 с паузой, которую называет сам шлюз.
_slots: dict[int, asyncio.Semaphore] = {}
RETRY_AFTER_RE = re.compile(r"retry after (\d+(?:\.\d+)?)\s*s", re.I)
RETRYABLE = (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError)


# Обрыв связи/5xx — это шлюз лёг, а не один плохой запрос. Общая пауза на весь процесс: все запросы
# ждут вместе (с растущей паузой) и продолжают, когда шлюз вернётся, а не сжигают каждый свои повторы.
_outage = {"until": 0.0, "delay": 5.0}
_clients: dict[tuple, AsyncOpenAI] = {}
_rate = {"next": 0.0}


async def _throttle() -> None:
    """Не чаще llm_rps запросов в секунду на весь процесс (0 — без ограничения)."""
    if settings.llm_rps <= 0:
        return
    now = _now()
    at = max(now, _rate["next"])
    _rate["next"] = at + 1.0 / settings.llm_rps
    if at > now:
        await asyncio.sleep(at - now)


def _now() -> float:
    return time.monotonic()


def _slot() -> asyncio.Semaphore:
    loop_id = id(asyncio.get_running_loop())   # семафор привязан к event loop (CLI и тесты создают свои)
    if loop_id not in _slots:
        _slots[loop_id] = asyncio.Semaphore(settings.llm_concurrency)
    return _slots[loop_id]


async def call(fn, *args, **kw):
    """Вызов API с общим лимитом параллельности и повторами.
    - 429 — до llm_retries раз с паузой, которую называет шлюз (это просто очередь);
    - тайм-аут одного запроса — не больше 2 повторов, иначе зависший вопрос держит прогон;
    - обрыв связи / 5xx — шлюз недоступен: общая пауза для всех запросов, ждём до llm_outage_s."""
    delay, timeouts, waited = 2.0, 0, 0.0
    rate_limits = 0
    while True:
        pause = _outage["until"] - _now()
        if pause > 0:                                   # шлюз лежит — ждём вместе со всеми
            await asyncio.sleep(pause)
            waited += pause
        async with _slot():
            await _throttle()
            try:
                result = await fn(*args, **kw)
                _outage["delay"] = 5.0
                return result
            except RateLimitError as e:
                rate_limits += 1
                if rate_limits > settings.llm_retries:
                    raise
                m = RETRY_AFTER_RE.search(str(e))
                wait = float(m.group(1)) + 0.5 if m else delay
                delay = min(delay * 2, 30)
                log.warning("LLM 429, повтор %d через %.1f с", rate_limits, wait)
            except APITimeoutError:
                timeouts += 1
                if timeouts > 2:
                    raise
                wait = delay
                delay = min(delay * 2, 30)
                log.warning("LLM тайм-аут запроса, повтор %d через %.1f с", timeouts, wait)
            except (APIConnectionError, InternalServerError) as e:
                if waited >= settings.llm_outage_s:
                    raise
                if _now() >= _outage["until"]:              # первый, кто заметил — объявляет паузу для всех
                    wait = _outage["delay"]
                    _outage["until"] = _now() + wait
                    _outage["delay"] = min(wait * 2, 60.0)
                    log.warning("API недоступен (%s), все запросы ждут %.0f с", type(e).__name__, wait)
                continue                                    # пауза — в начале цикла, вне семафора
        await asyncio.sleep(wait)   # ждём вне семафора — слот свободен для других (не в счёт простоя шлюза)


async def chat(profile: ModelProfile, messages: list[dict], json: bool = False, **kw) -> str:
    """json=True — ждём JSON-объект: включаем response_format, если профиль это разрешает.
    parse_json всё равно нужен: не все API соблюдают response_format строго."""
    if json and profile.json_mode:
        kw.setdefault("response_format", {"type": "json_object"})
    if profile.reasoning_effort:
        kw.setdefault("reasoning_effort", profile.reasoning_effort)
    temperature = kw.pop("temperature", profile.temperature)
    resp = await call(profile.client().chat.completions.create,
                      model=profile.model, messages=messages, temperature=temperature,
                      max_tokens=profile.max_tokens, extra_body=profile.body() or None, **kw)
    return resp.choices[0].message.content or ""


async def wait_ready(profile: ModelProfile, max_wait_s: float = 900, every_s: float = 30) -> bool:
    """Ждём, пока API снова отвечает (после обрыва связи): короткий запрос без очереди повторов.
    Иначе раунд повтора упавших вопросов сгорает за секунды, пока шлюз ещё лежит."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max_wait_s
    while True:
        try:
            await asyncio.wait_for(profile.client().chat.completions.create(
                model=profile.model, messages=[{"role": "user", "content": "ok"}], max_tokens=1,
                extra_body=profile.body() or None), 30)
            return True
        except RateLimitError:
            return True                      # 429 — шлюз жив, просто очередь
        except Exception as e:  # noqa: BLE001 — любая ошибка связи значит «ещё не поднялся»
            if loop.time() + every_s > deadline:
                return False
            log.warning("API недоступен (%s), жду %.0f с", type(e).__name__, every_s)
            await asyncio.sleep(every_s)


async def embed(profile: ModelProfile, texts: list[str], task: str | None = None,
                dimensions: int | None = None) -> list[list[float]]:
    """Эмбеддинги через POST /embeddings. task/dimensions — нестандартные поля, уходят в тело запроса
    (напр. task="retrieval.query" для вопроса, "retrieval.passage" для фрагментов документов)."""
    extra = dict(profile.extra_body)
    if task:
        extra["task"] = task
    dimensions = dimensions or profile.embed_dimensions
    if dimensions:
        extra["dimensions"] = dimensions
    out: list[list[float]] = []
    for i in range(0, len(texts), 64):
        resp = await call(profile.client().embeddings.create,
                          model=profile.model, input=texts[i:i + 64], encoding_format="float", extra_body=extra or None)
        out += [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]
    return out


def parse_json(text: str) -> dict:
    """Модели любят оборачивать JSON в ```json ... ``` и писать рассуждения вокруг."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL) or re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("в ответе модели нет JSON")
    return json.loads(m.group(1) if m.lastindex else m.group(0))
