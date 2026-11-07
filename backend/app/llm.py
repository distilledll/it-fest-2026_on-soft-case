"""Профили моделей: base_url + model + ключ + заголовки. Любой OpenAI-совместимый API.

Роли — какой профиль для чего используется: answer, critic, embed, rerank.
Хранится в storage/models.json. Ключ лучше указывать через api_key_env (имя переменной в .env);
api_key в файле допустим (storage/ в .gitignore), но наружу через API никогда не отдаётся.
"""
import json
import os
import re
import threading
import uuid
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.config import settings

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
    disable_thinking: bool = False   # chat_template_kwargs.enable_thinking=false (vLLM/Qwen)
    extra_body: dict[str, Any] = Field(default_factory=dict)

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
        return AsyncOpenAI(base_url=self.base_url, api_key=self.resolve_key() or "none",
                           default_headers=self.headers(), timeout=settings.question_timeout_s, max_retries=2)

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


async def chat(profile: ModelProfile, messages: list[dict], **kw) -> str:
    resp = await profile.client().chat.completions.create(
        model=profile.model, messages=messages, temperature=profile.temperature,
        max_tokens=profile.max_tokens, extra_body=profile.body() or None, **kw)
    return resp.choices[0].message.content or ""


def parse_json(text: str) -> dict:
    """Модели любят оборачивать JSON в ```json ... ``` и писать рассуждения вокруг."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL) or re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("в ответе модели нет JSON")
    return json.loads(m.group(1) if m.lastindex else m.group(0))
