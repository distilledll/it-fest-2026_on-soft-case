import time

from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import needs_sample

c = TestClient(app)


def test_health():
    r = c.get("/api/health").json()
    assert r["ok"] and any(p["name"] == "stub" for p in r["pipelines"])


def test_models_crud_never_leaks_key():
    r = c.post("/api/models", json={"id": "m1", "name": "x", "base_url": "http://x/v1", "model": "m",
                                    "api_key": "SECRET"})
    assert r.status_code == 201 and "api_key" not in r.json() and r.json()["has_key"]
    assert "SECRET" not in c.get("/api/models").text
    assert c.put("/api/models/roles", json={"critic": "m1"}).json() == {"answer": "m1", "critic": "m1"}
    assert c.put("/api/models/roles", json={"answer": "nope"}).status_code == 422
    assert c.patch("/api/models/m1", json={"temperature": 0.5}).json()["temperature"] == 0.5
    assert c.delete("/api/models/m1").status_code == 204
    assert c.get("/api/models").json()["roles"] == {}


@needs_sample
def test_ask_stub():
    r = c.post("/api/ask", json={"package": "P01", "question": "Какой размер обеспечения заявки?",
                                 "pipeline": "stub"})
    assert r.status_code == 200 and r.json()["trace"]


@needs_sample
def test_ask_unknown_package():
    r = c.post("/api/ask", json={"package": "P99", "question": "что?", "pipeline": "stub"})
    assert r.status_code == 404


@needs_sample
def test_ask_stream_stub():
    with c.stream("POST", "/api/ask/stream",
                  json={"package": "P01", "question": "Какой срок выполнения работ?", "pipeline": "stub"}) as r:
        body = "".join(r.iter_text())
    assert "event: step" in body and "event: answer" in body


@needs_sample
def test_run_and_score_stub():
    rid = c.post("/api/runs", json={"pipeline": "stub", "label": "t"}).json()["run_id"]
    for _ in range(100):
        d = c.get(f"/api/runs/{rid}").json()
        if d["meta"]["status"] != "running":
            break
        time.sleep(0.1)
    assert d["meta"]["status"] == "done"
    assert d["meta"]["score"]["n"] == 71 and d["meta"]["score"]["by_type"]
    assert d["items"][0]["verdict"]
    assert c.get(f"/api/runs/{rid}/answers.csv").text.startswith("id;status;answer;quote;file")
    assert c.get(f"/api/runs/compare/{rid}/{rid}").json()["changed"] == []


def test_upload_and_ask_without_questions():
    r = c.post("/api/datasets", files=[("files", ("doc.txt", "Срок поставки 10 дней.".encode()))],
               data={"name": "u", "package": "P01"})
    did = r.json()["id"]
    assert c.post("/api/runs", json={"dataset": did, "pipeline": "stub"}).status_code == 422
    assert c.post("/api/ask", json={"dataset": did, "package": "P01", "question": "Какой срок поставки?",
                                    "pipeline": "stub"}).status_code == 200


@needs_sample
def test_ladder_stub(monkeypatch):
    """Лесенка из заглушек: шаги идут по порядку и попадают в /api/ladders."""
    from app import runs as runs_mod
    monkeypatch.setattr(runs_mod, "LADDER", [("baseline", "b", "stub", {}, False), ("full", "f", "stub", {}, True)])
    lid = c.post("/api/ladders", json={"dataset": "sample"}).json()["ladder_id"]
    for _ in range(200):
        lad = next((x for x in c.get("/api/ladders").json() if x["id"] == lid), None)
        if lad and len(lad["steps"]) == 2 and all(s["status"] == "done" for s in lad["steps"]):
            break
        time.sleep(0.1)
    assert [s["step"] for s in lad["steps"]] == ["baseline", "full"]
    assert lad["steps"][0]["index"] is not None and lad["steps"][0]["by_type"]


def test_embedding_profile_from_frontend(monkeypatch):
    """Фронт подключает эмбеддинги отдельным профилем со своим адресом и ключом."""
    from app import llm
    r = c.post("/api/models", json={"id": "emb2", "name": "Другие эмбеддинги", "kind": "embedding",
                                          "base_url": "http://emb.local/v1", "model": "text-embedding-3-small",
                                          "api_key": "secret", "embed_dimensions": 512})
    assert r.status_code == 201 and r.json()["kind"] == "embedding" and "api_key" not in r.json()
    assert llm.load().roles["embed"] == "emb2"
    chat = c.post("/api/models", json={"id": "c1", "name": "c", "base_url": "http://x", "model": "m"}).json()
    assert c.put("/api/models/roles", json={"embed": chat["id"]}).status_code == 422
    assert c.put("/api/models/roles", json={"answer": "emb2"}).status_code == 422

    async def fake_embed(profile, texts, task=None, dimensions=None):
        return [[0.0] * (profile.embed_dimensions or 3)]
    monkeypatch.setattr(llm, "embed", fake_embed)
    t = c.post("/api/models/emb2/test").json()
    assert t["ok"] and t["dimensions"] == 512


def test_old_profiles_get_kind():
    from app.llm import ModelProfile
    assert ModelProfile.model_validate({"name": "e", "base_url": "x", "model": "cifra48/embedding"}).kind == "embedding"
    assert ModelProfile.model_validate({"name": "l", "base_url": "x", "model": "cifra48/llm"}).kind == "chat"


def test_frontend_profile_context_reaches_agent():
    from app.llm import get
    from app.pipeline.agent.graph import context_budget
    from app.pipeline.base import Context

    r = c.post("/api/models", json={"id": "ui", "name": "ui", "base_url": "http://test", "model": "m",
                                    "context_window": 8192, "concurrency": 2})
    assert r.status_code == 201 and r.json()["context_tokens"] == 8192
    r = c.patch("/api/models/ui", json={"context_tokens": 16384, "concurrency": 3})
    assert r.json()["context_window"] == 16384 and r.json()["concurrency"] == 3
    assert context_budget(Context(models={"answer": get("ui")})) == 24576
