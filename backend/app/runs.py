"""Прогон набора вопросов → answers.csv → оценка check.py.

Каждый прогон — папка storage/runs/<run_id>/: answers.csv, result.csv, trace.jsonl, meta.json.
Без БД: файлы и есть артефакты «было/стало». Прогресс идущих прогонов — в памяти процесса.
"""
import asyncio
import csv
import json
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from app import datasets, llm
from app.config import settings
from app.ingest import load_package, load_questions
from app.pipeline.base import Context, get_pipeline
from app.schemas import Answer, Question, Status, TraceStep
from app.verify import guard

FIELDS = ["id", "status", "answer", "quote", "file"]
PROGRESS: dict[str, dict] = {}   # run_id -> {"done", "total", "status"}


def make_context(roles: dict[str, str] | None = None, options: dict | None = None) -> Context:
    return Context(models=llm.resolve_roles(roles), options=options or {})


async def answer_one(pipeline, q: Question, data_dir: Path, ctx: Context, use_guard: bool = True) -> Answer:
    docs = list(load_package(data_dir, q.package))
    t0 = time.perf_counter()
    try:
        ans = await asyncio.wait_for(pipeline.answer(q, docs, ctx), settings.question_timeout_s)
        ans.id = q.id
    except Exception as e:  # прогон контрольного набора не должен падать из-за одного вопроса
        ans = Answer(id=q.id, status=Status.UNKNOWN,
                     trace=[TraceStep(node="error", ok=False, message=f"{type(e).__name__}: {e}"[:500])])
    if use_guard:
        ans = guard(ans, docs, q.question)
    ans.elapsed_s = round(time.perf_counter() - t0, 2)
    return ans


def _meta(run_id: str, dataset_id: str, pipeline_name: str, label: str, use_guard: bool, ctx: Context) -> dict:
    return {
        "run_id": run_id, "label": label, "dataset": dataset_id, "pipeline": pipeline_name, "guard": use_guard,
        "models": {r: {"profile": p.id, "model": p.model, "temperature": p.temperature} for r, p in ctx.models.items()},
        "options": ctx.options, "status": "running",
        "llm_concurrency": settings.llm_concurrency, "max_concurrency": settings.max_concurrency,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def new_run_id() -> str:
    return datetime.now().strftime("%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]


async def run_set(dataset_id: str, pipeline_name: str, label: str = "", use_guard: bool = True,
                  roles: dict[str, str] | None = None, options: dict | None = None,
                  run_id: str | None = None) -> dict:
    data_dir = datasets.path_of(dataset_id)
    run_id = run_id or new_run_id()
    out = settings.runs_dir / run_id
    out.mkdir(parents=True, exist_ok=True)
    ctx = make_context(roles, options)
    pipeline = get_pipeline(pipeline_name)
    questions = load_questions(data_dir)
    meta = _meta(run_id, dataset_id, pipeline_name, label, use_guard, ctx)
    meta["n"] = len(questions)
    _write_meta(out, meta)
    PROGRESS[run_id] = {"done": 0, "total": len(questions), "status": "running"}
    sem = asyncio.Semaphore(settings.max_concurrency)

    async def task(q):
        async with sem:
            a = await answer_one(pipeline, q, data_dir, ctx, use_guard)
            PROGRESS[run_id]["done"] += 1
            return a

    t0 = time.perf_counter()
    try:
        answers = await asyncio.gather(*(task(q) for q in questions))
    except Exception as e:
        meta.update(status="failed", error=f"{type(e).__name__}: {e}")
        _write_meta(out, meta)
        PROGRESS[run_id]["status"] = "failed"
        raise

    write_answers_csv(answers, out / "answers.csv")
    with open(out / "trace.jsonl", "w", encoding="utf-8") as f:
        f.writelines(a.model_dump_json() + "\n" for a in answers)

    meta.update(status="done", llm_calls=sum(a.llm_calls for a in answers),
                elapsed_s=round(time.perf_counter() - t0, 1),
                statuses={s.value: sum(a.status == s for a in answers) for s in Status})
    if (data_dir / "answers_public.json").exists():
        meta["score"] = score(out / "answers.csv", data_dir, out / "result.csv")
    _write_meta(out, meta)
    PROGRESS[run_id]["status"] = "done"
    return meta


def _write_meta(out: Path, meta: dict) -> None:
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


def write_answers_csv(answers: list[Answer], path: Path) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, delimiter=";")
        w.writeheader()
        for a in answers:
            row = a.model_dump(include=set(FIELDS))
            row["status"] = a.status.value
            # переносы строк в цитате ломают просмотр в Excel; check.py их всё равно нормализует
            w.writerow({k: re.sub(r"\s+", " ", str(v)).strip() for k, v in row.items()})


def score(answers_csv: Path, data_dir: Path, out_csv: Path) -> dict:
    """Оцениваем оригинальным check.py — ровно так же, как жюри."""
    checker = data_dir / "check.py" if (data_dir / "check.py").exists() else settings.checker
    p = subprocess.run(
        [sys.executable, "-I", str(checker), str(answers_csv.resolve()),
         "--gold", str(data_dir / "answers_public.json"), "--packages", str(data_dir / "packages"),
         "--out", str(out_csv.resolve())],
        capture_output=True, text=True, timeout=120,
    )
    m = re.search(r"^RESULT (.+)$", p.stdout, re.MULTILINE)
    res = json.loads(m.group(1)) if m else {"error": p.stderr[-2000:]}
    res["by_type"] = _by_type(out_csv) if out_csv.exists() else {}
    res["report"] = p.stdout
    return res


def _by_type(result_csv: Path) -> dict:
    out: dict[str, dict[str, int]] = {}
    with open(result_csv, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter=";"):
            t = out.setdefault(r["type"], {"верно": 0, "осторожно": 0, "обман": 0})
            t[r["verdict"]] = t.get(r["verdict"], 0) + 1
    return out


def read_meta(run_id: str) -> dict:
    meta = json.loads((settings.runs_dir / run_id / "meta.json").read_text(encoding="utf-8"))
    if run_id in PROGRESS:
        meta["progress"] = PROGRESS[run_id]
    elif meta.get("status") == "running":
        meta["status"] = "interrupted"   # сервер перезапустили посреди прогона
    return meta


def list_runs() -> list[dict]:
    out = []
    for p in sorted(settings.runs_dir.glob("*/meta.json"), reverse=True):
        m = read_meta(p.parent.name)
        m.get("score", {}).pop("report", None)
        out.append(m)
    return out
