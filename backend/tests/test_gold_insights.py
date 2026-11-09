"""Контрольный набор: другое имя файла вопросов, эталон после прогона, сводка проверок без эталона."""
import asyncio
import io
import json
import zipfile

from fastapi.testclient import TestClient

from app import datasets, runs
from app.config import settings
from app.main import app
from app.schemas import Answer, Status, TraceStep

c = TestClient(app)
GOLD = [{"id": "K01-01", "package": "K01", "status": "ответ", "kind": "num", "expected": [10],
         "type": "факт", "quote": "Срок поставки 10 дней", "file": "01.txt"},
        {"id": "K01-02", "package": "K01", "status": "нет в документах", "kind": "absent", "expected": [],
         "type": "ловушка: нет в документах", "quote": "", "file": ""}]


def control_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("school21-onsoft-control/packages/K01/01.txt", "Срок поставки 10 дней.")
        z.writestr("school21-onsoft-control/questions_control.csv",
                   "id;package;question\r\nK01-01;K01;Какой срок поставки?\r\nK01-02;K01;Какая гарантия?\r\n")
    return buf.getvalue()


class Scripted:
    """Пайплайн без модели: K01-01 — проверка поймала и ответ исправлен, K01-02 — «нет в документах» сразу."""
    name = "scripted"

    async def answer(self, q, docs, ctx):
        if q.id == "K01-01":
            return Answer(id=q.id, status=Status.ANSWER, answer="10", quote="Срок поставки 10 дней", file="01.txt",
                          llm_calls=2, trace=[
                              TraceStep(node="answer", ok=True, message="попытка 1: ответ «15»"),
                              TraceStep(node="critic_number", ok=False, message="числа 15 нет в цитате"),
                              TraceStep(node="retry", message="повтор с замечаниями (1)"),
                              TraceStep(node="answer", ok=True, message="попытка 2: ответ «10»")])
        return Answer(id=q.id, status=Status.ABSENT, llm_calls=1,
                      trace=[TraceStep(node="answer", ok=True, message="попытка 1: нет в документах «»")])


def test_control_archive_questions_file_is_recognized():
    did = datasets.from_zip(control_zip(), "control")
    info = datasets.info(did)
    assert info["has_questions"] and not info["has_gold"] and info["packages"] == ["K01"]


def test_gold_after_run_rescores_and_insights(monkeypatch):
    did = datasets.from_zip(control_zip(), "control")
    monkeypatch.setattr(runs, "get_pipeline", lambda name, **kw: Scripted())
    meta = asyncio.run(runs.run_set(did, "scripted", use_guard=False))
    assert "score" not in meta                                    # эталона нет — оценки нет

    ins = c.get(f"/api/runs/{meta['run_id']}/insights").json()   # но сводка проверок есть
    assert ins["has_gold"] is False and ins["with_checks"] == 1 and ins["clean"] == 1
    ev = ins["events"][0]
    assert ev["id"] == "K01-01" and ev["checks"][0]["check"] == "number" and ev["outcome"] == "fixed"
    assert ev["draft"] == "ответ «15»" and ins["checks"][0]["fixed"] == 1

    r = c.post(f"/api/datasets/{did}/gold", files={"file": ("answers.json", json.dumps(GOLD, ensure_ascii=False))})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dataset"]["has_gold"] and body["missing"] == [] and len(body["rescored"]) == 1
    assert body["rescored"][0]["score"]["index"] == 100.0           # прогон пересчитан без перезапуска
    assert c.get(f"/api/runs/{meta['run_id']}/insights").json()["events"][0]["verdict"]["verdict"] == "верно"


def test_bad_gold_rejected():
    did = datasets.from_zip(control_zip(), "control")
    assert c.post(f"/api/datasets/{did}/gold", files={"file": ("a.json", "не json")}).status_code == 422
    alien = [dict(GOLD[0], id="X99-01")]
    r = c.post(f"/api/datasets/{did}/gold", files={"file": ("a.json", json.dumps(alien, ensure_ascii=False))})
    assert r.status_code == 422 and "X99-01" in r.json()["detail"]
    assert c.post("/api/datasets/sample/gold", files={"file": ("a.json", "[]")}).status_code in (404, 422)
