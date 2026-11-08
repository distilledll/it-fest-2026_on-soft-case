"""Устойчивость прогона: повтор упавших вопросов и дозапуск после падения процесса."""
import asyncio
import io
import json
import zipfile

from app import datasets, runs
from app.config import settings
from app.schemas import Answer, Status


def make_dataset(n=4) -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("packages/P01/01.txt", "Срок 10 дней.")
        z.writestr("questions.csv", "id;package;question\n" + "".join(f"Q{i};P01;вопрос {i}\n" for i in range(n)))
    return datasets.from_zip(buf.getvalue(), "t")


class Flaky:
    """Первые `fail` обращений к вопросу падают с сетевой ошибкой."""
    name = "flaky"

    def __init__(self, fail: dict[str, int]):
        self.fail, self.seen = fail, {}

    async def answer(self, q, docs, ctx):
        self.seen[q.id] = self.seen.get(q.id, 0) + 1
        if self.seen[q.id] <= self.fail.get(q.id, 0):
            raise ConnectionError("сеть отвалилась")
        return Answer(id=q.id, status=Status.UNKNOWN, llm_calls=1)


def test_map_timeout_scales_with_chunks():
    from app.pipeline.base import Context
    assert runs.question_timeout(Context(models={}, options={})) == settings.question_timeout_s
    assert runs.question_timeout(Context(models={}, options={"map_extract": True, "map_max_chunks": 30})) == \
        3 * settings.question_timeout_s


def test_retry_round_waits_for_api(monkeypatch):
    from app import llm
    monkeypatch.setattr(settings, "retry_pauses_s", [0, 0])
    probes = []

    async def down(profile, **kw):
        probes.append(profile)
        return False
    monkeypatch.setattr(llm, "wait_ready", down)
    p = Flaky({"Q1": 1})
    monkeypatch.setattr(runs, "get_pipeline", lambda name: p)
    monkeypatch.setattr(runs, "make_context", lambda *a, **k: runs.Context(models={"answer": llm.ModelProfile(id="m", name="m", base_url="http://x", model="m")}, options={}))
    meta = asyncio.run(runs.run_set(make_dataset(2), "flaky", use_guard=False))
    # API не поднялся — раунд не тратим впустую, вопрос остаётся «упавшим» для resume
    assert len(probes) == 1 and p.seen["Q1"] == 1 and meta["failed"] == 1


def test_failed_questions_are_retried(monkeypatch):
    monkeypatch.setattr(settings, "retry_pauses_s", [0, 0])
    p = Flaky({"Q1": 1, "Q2": 2})
    monkeypatch.setattr(runs, "get_pipeline", lambda name: p)
    meta = asyncio.run(runs.run_set(make_dataset(), "flaky", use_guard=False))
    assert meta["failed"] == 0 and p.seen == {"Q0": 1, "Q1": 2, "Q2": 3, "Q3": 1}


def test_still_failed_reported(monkeypatch):
    monkeypatch.setattr(settings, "retry_pauses_s", [0])
    monkeypatch.setattr(runs, "get_pipeline", lambda name: Flaky({"Q0": 99}))
    meta = asyncio.run(runs.run_set(make_dataset(2), "flaky", use_guard=False))
    assert meta["failed"] == 1


def test_resume_after_crash(monkeypatch):
    monkeypatch.setattr(settings, "retry_pauses_s", [])
    did = make_dataset(4)
    monkeypatch.setattr(runs, "get_pipeline", lambda name: Flaky({"Q3": 99}))
    meta = asyncio.run(runs.run_set(did, "flaky", use_guard=False))
    out = settings.runs_dir / meta["run_id"]
    # имитация падения процесса: остались только 2 ответа в partial, итоговых файлов нет
    lines = (out / "partial.jsonl").read_text().splitlines()[:2]
    (out / "partial.jsonl").write_text("\n".join(lines) + "\n")
    (out / "trace.jsonl").unlink()
    p = Flaky({})
    monkeypatch.setattr(runs, "get_pipeline", lambda name: p)
    meta = asyncio.run(runs.resume_run(meta["run_id"]))
    assert meta["failed"] == 0 and meta["resumed"] == 2 and len(p.seen) == 2
    ids = [json.loads(x)["id"] for x in (out / "trace.jsonl").read_text().splitlines()]
    assert ids == ["Q0", "Q1", "Q2", "Q3"]
    assert (out / "answers.csv").read_text().count("\n") == 5
