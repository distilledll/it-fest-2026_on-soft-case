"""Выбор модели: профили (подключения к OpenAI-совместимому API) и назначение их на роли."""
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import llm
from app.llm import ROLES, ModelProfile

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("")
def list_models():
    reg = llm.load()
    return {"profiles": [p.public() for p in reg.profiles], "roles": reg.roles, "role_names": ROLES}


@router.post("", status_code=201)
def create_profile(p: ModelProfile):
    reg = llm.load()
    if any(x.id == p.id for x in reg.profiles):
        raise HTTPException(409, "профиль с таким id уже есть")
    reg.profiles.append(p)
    reg.roles.setdefault("answer", p.id)
    llm.save(reg)
    return p.public()


class ProfilePatch(BaseModel):
    name: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None        # пустая строка — стереть сохранённый ключ
    api_key_env: str | None = None
    extra_headers: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    concurrency: int | None = Field(default=None, ge=1, le=64)
    context_window: int | None = Field(default=None, ge=512, le=4_000_000)
    disable_thinking: bool | None = None
    json_mode: bool | None = None
    reasoning_effort: str | None = None   # low | medium | high; пустая строка — выключить
    extra_body: dict | None = None


@router.patch("/{pid}")
def update_profile(pid: str, patch: ProfilePatch):
    reg = llm.load()
    for i, p in enumerate(reg.profiles):
        if p.id == pid:
            reg.profiles[i] = p.model_copy(update=patch.model_dump(exclude_unset=True))
            llm.save(reg)
            return reg.profiles[i].public()
    raise HTTPException(404)


@router.delete("/{pid}", status_code=204)
def delete_profile(pid: str):
    reg = llm.load()
    reg.profiles = [p for p in reg.profiles if p.id != pid]
    reg.roles = {r: v for r, v in reg.roles.items() if v != pid}
    llm.save(reg)


@router.put("/roles")
def set_roles(roles: dict[str, str]):
    reg = llm.load()
    ids = {p.id for p in reg.profiles}
    bad = [r for r in roles if r not in ROLES] + [v for v in roles.values() if v and v not in ids]
    if bad:
        raise HTTPException(422, f"неизвестные роли/профили: {bad}")
    reg.roles = {r: v for r, v in {**reg.roles, **roles}.items() if v}
    llm.save(reg)
    return reg.roles


@router.post("/{pid}/test")
async def test_profile(pid: str):
    """Проверка подключения: короткий запрос к модели."""
    try:
        p = llm.get(pid)
    except KeyError:
        raise HTTPException(404)
    t0 = time.perf_counter()
    try:
        text = await llm.chat(p, [{"role": "user", "content": "Ответь одним словом: ок"}])
        return {"ok": True, "reply": text[:200], "latency_s": round(time.perf_counter() - t0, 2)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:500]}


@router.get("/{pid}/remote")
async def remote_models(pid: str):
    """Список моделей, которые отдаёт сам API (GET /models) — чтобы выбирать из списка, а не вписывать."""
    try:
        p = llm.get(pid)
    except KeyError:
        raise HTTPException(404)
    try:
        return [m.id async for m in p.client().models.list()]
    except Exception as e:
        raise HTTPException(502, f"{type(e).__name__}: {e}"[:500])
