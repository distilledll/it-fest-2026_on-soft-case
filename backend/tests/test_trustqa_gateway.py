import asyncio
import json

import httpx
import pytest

from app import llm
from app.config import settings
from app.pipeline.base import Context, get_pipeline
from app.pipeline.agent import AgentPipeline
from app.pipeline.hybrid import fallback_config
from app.schemas import Answer, Document, Question, Status
from trustqa.config import Config
from trustqa.transport import post_json


def test_fallback_requests_use_shared_slots_and_selected_models(monkeypatch):
    async def primary(self, q, docs, ctx):
        yield Answer(id=q.id, status=Status.UNKNOWN)

    monkeypatch.setattr(AgentPipeline, "stream", primary)
    monkeypatch.setattr(settings, "llm_concurrency", 1)
    monkeypatch.setattr(settings, "llm_rps", 60)
    monkeypatch.setitem(llm._rate, "next", 0)
    answer = llm.ModelProfile(id="selected", name="answer", model="chosen", base_url="https://chat.test/v1",
                              api_key="chat-test", json_mode=False, reasoning_effort="low", disable_thinking=False)
    embed = llm.ModelProfile(name="embed", model="vector", kind="embedding", base_url="https://embed.test/v1",
                             api_key="embed-test", embed_dimensions=2)
    rank = llm.ModelProfile(name="rank", model="sort", base_url="https://rank.test/v1", api_key="rank-test")
    ctx = Context(models={"answer": answer, "embed": embed, "rerank": rank})
    docs = [Document(file=f"{i}.txt", package="P", text=text, encoding="utf-8") for i, text in enumerate(
        ["Исполнитель передаёт объекты по акту.", "Доставка производится за счёт исполнителя."])]
    active = 0
    starts, names = [], []

    async def respond(request):
        nonlocal active
        starts.append(asyncio.get_running_loop().time())
        active += 1
        assert active == 1
        try:
            await asyncio.sleep(0.002)
            body = json.loads(request.content)
            names.append(body["model"])
            if request.url.host == "embed.test":
                assert body["model"] == "vector" and request.headers["authorization"] == "Bearer embed-test"
                assert "task" not in body and "normalized" not in body
                return httpx.Response(200, json={"data": [{"index": i, "embedding": [0, 1]}
                                                           for i in range(len(body["input"]))]})
            if request.url.host == "rank.test":
                assert body["model"] == "sort" and request.headers["authorization"] == "Bearer rank-test"
                value = {"scores": {"0": 1, "1": 2}}
            else:
                assert request.url.host == "chat.test" and body["model"] == "chosen"
                assert request.headers["authorization"] == "Bearer chat-test"
                assert body["reasoning_effort"] == "low" and "response_format" not in body
                value = {"status": "нет в документах", "answer": "", "quote": "", "file": "", "evidence": []}
                if "Независимо найди" in body["messages"][0]["content"]:
                    value = {"evidence": [], "complete": True}
            return httpx.Response(200, json={"choices": [{"index": 0, "finish_reason": "stop",
                                                          "message": {"role": "assistant", "content": json.dumps(value)}}]})
        finally:
            active -= 1

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            monkeypatch.setattr(llm, "http_client", lambda: client)
            pipe = get_pipeline("hybrid", use_guard=True)
            result = await asyncio.wait_for(asyncio.gather(*[
                pipe.answer(Question(id=str(i), package="P", question=f"Какой размер аванса по этапу {i}?"), docs, ctx)
                for i in range(3)]), 10)
            assert all(r.status == Status.ABSENT and r.llm_calls == 4 for r in result)
            assert all(r.trace[-1].data["model"] == "chosen" for r in result)
            await llm.close_clients()
    asyncio.run(run())
    assert set(names) == {"chosen", "vector", "sort"}
    assert starts[-1] - starts[0] >= (len(starts) - 1) / 60 - 0.02


def test_gateway_outage_and_retry_use_the_shared_gate(monkeypatch):
    clock, starts = [0.0], []
    async def sleep(seconds):
        clock[0] += seconds

    async def respond(request):
        starts.append(clock[0])
        if len(starts) == 1:
            return httpx.Response(503)
        if len(starts) == 2:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(201, json={"ok": True})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            monkeypatch.setattr(llm, "http_client", lambda: client)
            monkeypatch.setattr(llm, "_now", lambda: clock[0])
            monkeypatch.setattr(llm.asyncio, "sleep", sleep)
            data = await post_json("https://gateway.test", "rerank", "", {}, 10)
            assert data == {"ok": True}
    asyncio.run(run())
    assert starts == [0, 5, 12]


def test_cancelled_fallback_releases_request(monkeypatch):
    async def primary(self, q, docs, ctx):
        yield Answer(id=q.id, status=Status.UNKNOWN)
    monkeypatch.setattr(AgentPipeline, "stream", primary)
    monkeypatch.setenv("JINA_API_KEY", "test")
    monkeypatch.setenv("QWEN_MODEL", "model")
    monkeypatch.setenv("QWEN_MODEL_VERSION", "test")
    monkeypatch.setenv("QWEN_BASE_URL", "https://chat.test/v1")

    async def run():
        entered, released = asyncio.Event(), asyncio.Event()
        async def respond(request):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                released.set()
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            monkeypatch.setattr(llm, "http_client", lambda: client)
            docs = [Document(file="x.txt", text="Объекты закупки.", package="P", encoding="utf-8")]
            q = Question(id="test", package="P", question="Какой аванс?")
            task = asyncio.create_task(get_pipeline("hybrid").answer(q, docs, Context()))
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
            assert released.is_set()
    asyncio.run(run())


def test_fallback_preserves_env_defaults_until_profiles_are_saved(monkeypatch):
    monkeypatch.setattr(settings, "llm_base_url", "https://primary.test")
    monkeypatch.setattr(settings, "llm_model", "primary")
    defaults = Config(qwen_base_url="https://review.test", qwen_model="review", qwen_model_version="v1")
    config, _ = fallback_config(Context(models=llm.resolve_roles()), defaults)
    assert config.qwen_model == "review"
    llm.save(llm.load())
    selected, _ = fallback_config(Context(models=llm.resolve_roles()), defaults)
    assert selected.qwen_model == "primary" and selected.qwen_model_version == "unversioned:primary"


def test_gateway_user_agent_preserves_platform_details():
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    profile = llm.ModelProfile(name="gateway", model="test", base_url="https://gateway.test",
                               extra_headers=f"User-Agent={ua};X-Deployment=demo")
    assert profile.headers() == {"User-Agent": ua, "X-Deployment": "demo"}
