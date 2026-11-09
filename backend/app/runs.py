"""Прогон набора вопросов → answers.csv → оценка check.py.

Каждый прогон — папка storage/runs/<run_id>/: answers.csv, result.csv, trace.jsonl, meta.json.
Без БД: файлы и есть артефакты «было/стало». Прогресс идущих прогонов — в памяти процесса.
"""
import asyncio
import csv
import json
import logging
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

log = logging.getLogger("runs")

FIELDS = ["id", "status", "answer", "quote", "file"]
PROGRESS: dict[str, dict] = {}   # run_id -> {"done", "total", "status"}


STRATEGIES = {
    # вся закупка (или фрагменты поиска, если не влезает) в одном запросе — для сильных моделей
    "full": {},
    # по умолчанию: full, а если закупка не влезает в контекст модели — map (решает граф, узел map)
    "auto": {},
    # map-reduce: модель читает закупку фрагментами, ответ — по проверенным и размеченным выпискам
    "map": {"quote_first": True, "map_extract": True},
}


def make_context(roles: dict[str, str] | None = None, options: dict | None = None) -> Context:
    """Опции = стратегия (из профиля модели или запроса) + agent_options профиля роли answer + опции запроса."""
    models = llm.resolve_roles(roles)
    merged = dict(models["answer"].agent_options) if "answer" in models else {}
    merged.update(options or {})
    strategy = merged.setdefault("strategy", "auto")
    if strategy not in STRATEGIES:
        raise ValueError(f"нет стратегии {strategy}: {', '.join(STRATEGIES)}")
    return Context(models=models, options={**STRATEGIES[strategy], **merged})


def question_timeout(ctx: Context) -> float:
    """Лимит на вопрос. Map-reduce читает до map_max_chunks фрагментов — по запросу на каждый,
    поэтому лимит растёт с их числом (на 30 фрагментов — втрое), а не один на весь вопрос."""
    t = settings.question_timeout_s
    if ctx.options.get("map_extract"):
        t *= max(1.0, int(ctx.options.get("map_max_chunks", 30)) / 10)
    return t


async def answer_one(pipeline, q: Question, data_dir: Path, ctx: Context) -> Answer:
    docs = list(load_package(data_dir, q.package))
    t0 = time.perf_counter()
    try:
        ans = await asyncio.wait_for(pipeline.answer(q, docs, ctx), question_timeout(ctx))
        ans.id = q.id
    except Exception as e:  # прогон контрольного набора не должен падать из-за одного вопроса
        ans = Answer(id=q.id, status=Status.UNKNOWN,
                     trace=[TraceStep(node="error", ok=False, message=f"{type(e).__name__}: {e}"[:500])])
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
                  run_id: str | None = None, ladder: dict | None = None) -> dict:
    data_dir = datasets.path_of(dataset_id)
    run_id = run_id or new_run_id()
    out = settings.runs_dir / run_id
    out.mkdir(parents=True, exist_ok=True)
    ctx = make_context(roles, options)
    pipeline = get_pipeline(pipeline_name, use_guard=use_guard)
    questions = load_questions(data_dir)
    meta = _meta(run_id, dataset_id, pipeline_name, label, use_guard, ctx)
    meta["n"] = len(questions)
    meta["dataset_name"] = datasets.info(dataset_id).get("name", dataset_id)
    if ladder:
        meta["ladder"] = ladder
    _write_meta(out, meta)
    PROGRESS[run_id] = {"done": 0, "total": len(questions), "status": "running"}
    t0 = time.perf_counter()
    try:
        answers = await _answer_all(pipeline, questions, data_dir, ctx, out, run_id)
    except Exception as e:
        meta.update(status="failed", error=f"{type(e).__name__}: {e}")
        _write_meta(out, meta)
        PROGRESS[run_id]["status"] = "failed"
        raise
    return _finish(out, meta, answers, data_dir, time.perf_counter() - t0, run_id)


# ошибки самого запроса (400 «не влезает в контекст», 401, 403, 404, 422): повтор ничего не изменит
PERMANENT = ("BadRequestError", "AuthenticationError", "PermissionDeniedError", "NotFoundError",
             "UnprocessableEntityError")


def is_failed(a: Answer) -> bool:
    """Технический сбой, который стоит повторить (сеть, тайм-аут), а не честное «не знаю» модели
    и не ошибка самого запроса."""
    return any(t.node == "error" and not (t.message or "").startswith(PERMANENT) for t in a.trace)


async def _answer_all(pipeline, questions: list[Question], data_dir: Path, ctx: Context,
                      out: Path, run_id: str) -> list[Answer]:
    """Ответы на все вопросы + повтор упавших (сеть, тайм-аут) несколькими раундами с паузой.
    Каждый готовый ответ сразу дописывается в partial.jsonl — если процесс упадёт, `resume` продолжит с места."""
    sem = asyncio.Semaphore(settings.max_concurrency)
    partial = out / "partial.jsonl"

    async def task(q):
        async with sem:
            a = await answer_one(pipeline, q, data_dir, ctx)
        with open(partial, "a", encoding="utf-8") as f:
            f.write(a.model_dump_json() + "\n")
        if run_id in PROGRESS:
            PROGRESS[run_id]["done"] += 1
        return a

    answers = list(await asyncio.gather(*(task(q) for q in questions)))
    for rnd, pause in enumerate(settings.retry_pauses_s, 1):
        failed = [i for i, a in enumerate(answers) if is_failed(a)]
        if not failed:
            break
        if run_id in PROGRESS:
            PROGRESS[run_id].update(status=f"retry {rnd}: {len(failed)} упавших")
        await asyncio.sleep(pause)
        if "answer" in ctx.models and not await llm.wait_ready(ctx.models["answer"]):
            log.warning("API так и не ответил — повтор упавших отложен: python -m app.cli resume %s", run_id)
            break
        again = await asyncio.gather(*(task(questions[i]) for i in failed))
        for i, a in zip(failed, again):
            a.trace.insert(0, TraceStep(node="retry_run", ok=not is_failed(a),
                                        message=f"повтор после сбоя, раунд {rnd}"))
            answers[i] = a
    return answers


def _finish(out: Path, meta: dict, answers: list[Answer], data_dir: Path, elapsed: float, run_id: str) -> dict:
    write_answers_csv(answers, out / "answers.csv")
    with open(out / "trace.jsonl", "w", encoding="utf-8") as f:
        f.writelines(a.model_dump_json() + "\n" for a in answers)
    meta.update(status="done", llm_calls=sum(a.llm_calls for a in answers),
                elapsed_s=round(elapsed + meta.get("elapsed_s_before", 0), 1),
                failed=sum(is_failed(a) for a in answers),
                statuses={s.value: sum(a.status == s for a in answers) for s in Status})
    meta.pop("elapsed_s_before", None)
    if (data_dir / "answers_public.json").exists():
        meta["score"] = score(out / "answers.csv", data_dir, out / "result.csv")
    _write_meta(out, meta)
    if run_id in PROGRESS:
        PROGRESS[run_id]["status"] = "done"
    return meta


async def resume_run(run_id: str) -> dict:
    """Дозапуск прогона: недостающие (процесс упал) и упавшие (сеть/тайм-аут) вопросы, остальное — как было.
    На защите: если сеть отвалилась посреди контрольного набора — `python -m app.cli resume <run_id>`."""
    out = settings.runs_dir / run_id
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    data_dir = datasets.path_of(meta["dataset"])
    questions = load_questions(data_dir)
    done: dict[str, Answer] = {}
    for name in ("trace.jsonl", "partial.jsonl"):
        if (out / name).exists():
            for line in (out / name).read_text(encoding="utf-8").splitlines():
                if line.strip():
                    a = Answer.model_validate_json(line)
                    if a.id not in done or is_failed(done[a.id]):
                        done[a.id] = a
    todo = [q for q in questions if q.id not in done or is_failed(done[q.id])]
    roles = {r: m["profile"] for r, m in meta.get("models", {}).items()}
    ctx = make_context(roles, meta.get("options"))
    pipeline = get_pipeline(meta["pipeline"], use_guard=meta["guard"])
    meta.update(status="running", elapsed_s_before=meta.get("elapsed_s") or 0, resumed=len(todo))
    _write_meta(out, meta)
    PROGRESS[run_id] = {"done": len(questions) - len(todo), "total": len(questions), "status": "resume"}
    t0 = time.perf_counter()
    fresh = await _answer_all(pipeline, todo, data_dir, ctx, out, run_id) if todo else []
    done.update({a.id: a for a in fresh})
    answers = [done[q.id] for q in questions]
    return _finish(out, meta, answers, data_dir, time.perf_counter() - t0, run_id)


def _write_meta(out: Path, meta: dict) -> None:
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


def write_answers_csv(answers: list[Answer], path: Path) -> None:
    """answers.csv в формате кейса: UTF-8, разделитель «;», колонки id;status;answer;quote;file.
    BOM — чтобы Excel открыл кириллицу правильно (check.py его срезает). У «нет в документах» и «не знаю»
    answer/quote/file пустые, как в примере организатора, — даже в прогонах без guard."""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, delimiter=";")
        w.writeheader()
        for a in answers:
            row = a.model_dump(include=set(FIELDS))
            row["status"] = a.status.value
            if a.status in (Status.ABSENT, Status.UNKNOWN):
                row.update(answer="", quote="", file="")
            # переносы строк в цитате ломают просмотр в Excel; check.py их всё равно нормализует
            w.writerow({k: re.sub(r"\s+", " ", str(v)).strip() for k, v in row.items()})


def score(answers_csv: Path, data_dir: Path, out_csv: Path) -> dict:
    """Оцениваем оригинальным check.py — ровно так же, как жюри."""
    checker, source = datasets.checker_for(data_dir)
    p = subprocess.run(
        [sys.executable, "-I", str(checker), str(answers_csv.resolve()),
         "--gold", str(data_dir / "answers_public.json"), "--packages", str(data_dir / "packages"),
         "--out", str(out_csv.resolve())],
        capture_output=True, text=True, timeout=120,
    )
    m = re.search(r"^RESULT (.+)$", p.stdout, re.MULTILINE)
    res = json.loads(m.group(1)) if m else {"error": p.stderr[-2000:]}
    res["checker"] = source
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


# ---------------------------------------------------------------- лесенка «было → стало»

LADDER = [
    # step,      подпись для графика,            пайплайн,   опции,                                                guard
    ("baseline", "Baseline «как есть»",          "baseline", {},                                                   False),
    ("direct",   "+ разрешили «не знаю»",        "direct",   {},                                                   False),
    ("prompt",   "Промпт агента",                "agent",    {"critics": [], "llm_critic": False, "max_attempts": 1}, False),
    ("critics",  "+ критики кодом и повторы",    "agent",    {"llm_critic": False},                                True),
    ("full",     "+ критик-модель (полный агент)", "agent",  {},                                                   True),
    ("hybrid",   "+ резервный проход TrustQA",   "hybrid",   {},                                                   True),
]


async def run_ladder(dataset_id: str, roles: dict[str, str] | None = None, steps: list[str] | None = None,
                     ladder_id: str | None = None) -> str:
    """Все слои на одном датасете и одной модели — данные для графика вклада каждого слоя."""
    ladder_id = ladder_id or new_run_id()
    for order, (step, title, pipeline, options, use_guard) in enumerate(LADDER):
        if steps and step not in steps:
            continue
        await run_set(dataset_id, pipeline, f"{title}", use_guard, roles, options,
                      ladder={"id": ladder_id, "step": step, "title": title, "order": order})
    return ladder_id


def list_ladders() -> list[dict]:
    """Лесенки: для каждой — шаги с индексом, разбивкой и затратами (сразу в форме для графика)."""
    by_id: dict[str, dict] = {}
    for m in list_runs():
        lad = m.get("ladder")
        if not lad:
            continue
        entry = by_id.setdefault(lad["id"], {"id": lad["id"], "dataset": m["dataset"],
                                             "dataset_name": m.get("dataset_name"), "models": m.get("models"),
                                             "steps": []})
        s = m.get("score", {})
        entry["steps"].append({
            "step": lad["step"], "title": lad["title"], "order": lad["order"], "run_id": m["run_id"],
            "status": m["status"], "index": s.get("index"), "correct": s.get("correct"),
            "careful": s.get("careful"), "lies": s.get("lies"), "n": m.get("n"), "by_type": s.get("by_type", {}),
            "llm_calls": m.get("llm_calls"), "elapsed_s": m.get("elapsed_s"),
        })
    for e in by_id.values():
        e["steps"].sort(key=lambda x: x["order"])
    return sorted(by_id.values(), key=lambda e: e["id"], reverse=True)
