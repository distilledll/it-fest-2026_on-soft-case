"""Прогоны набора вопросов и данные для дашборда «было/стало»."""
import asyncio
import csv
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import datasets
from app.api import out
from app.config import settings
from app.datasets import DatasetError
from app.pipeline.base import PIPELINES
from app.runs import LADDER, list_ladders, list_runs, new_run_id, read_meta, run_ladder, run_set

router = APIRouter(prefix="/api/runs", tags=["runs"])
_tasks: set[asyncio.Task] = set()


class RunIn(BaseModel):
    dataset: str = "sample"
    pipeline: str | None = None
    label: str = ""
    guard: bool = True
    roles: dict[str, str] | None = None
    options: dict = Field(default_factory=dict)


@router.post("", status_code=202, response_model=out.RunStarted)
async def start_run(body: RunIn):
    try:
        info = datasets.info(body.dataset)
    except DatasetError as e:
        raise HTTPException(404, str(e))
    if not info["has_questions"]:
        raise HTTPException(422, "в датасете нет questions.csv — задавайте вопросы через /api/ask")
    pipeline = body.pipeline or settings.pipeline
    if pipeline not in PIPELINES:
        raise HTTPException(422, f"неизвестный пайплайн {pipeline}")
    run_id = new_run_id()
    t = asyncio.create_task(run_set(body.dataset, pipeline, body.label, body.guard, body.roles,
                                    body.options, run_id=run_id))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return {"run_id": run_id}


@router.get("", response_model=list[out.RunMeta])
def runs():
    return list_runs()


def _dir(run_id: str):
    d = settings.runs_dir / run_id
    if "/" in run_id or ".." in run_id or not (d / "meta.json").exists():
        raise HTTPException(404)
    return d


@router.get("/{run_id}", response_model=out.RunDetail)
def run_detail(run_id: str):
    """По каждому вопросу: ответ, trace агента, вердикт check.py (верно/осторожно/обман + причина)."""
    d = _dir(run_id)
    meta = read_meta(run_id)
    verdicts = {}
    if (d / "result.csv").exists():
        with open(d / "result.csv", encoding="utf-8") as f:
            verdicts = {r["id"]: r for r in csv.DictReader(f, delimiter=";")}
    items = []
    if (d / "trace.jsonl").exists():
        for line in (d / "trace.jsonl").read_text(encoding="utf-8").splitlines():
            a = json.loads(line)
            a["verdict"] = verdicts.get(a["id"])
            items.append(a)
    return {"meta": meta, "items": items}


@router.get("/{run_id}/answers.csv", response_class=FileResponse, responses={200: {"description": "answers.csv для сдачи: UTF-8, разделитель `;`, колонки id;status;answer;quote;file", "content": {"text/csv": {"schema": {"type": "string"}}}}})
def run_csv(run_id: str):
    return FileResponse(_dir(run_id) / "answers.csv", media_type="text/csv", filename="answers.csv")


@router.get("/{run_id}/caught", response_model=out.CaughtOut)
def run_caught(run_id: str):
    """Пойманные обманы: первый черновик модели был обманом по check.py, итог — нет. Плюс ложные тревоги
    и вклад каждого критика. Материал для вопроса жюри «покажите обман, который система поймала»."""
    _dir(run_id)
    from app.analysis import analyze
    return analyze(run_id)


@router.post("/{run_id}/resume", status_code=202, response_model=out.RunStarted)
async def resume(run_id: str):
    """Дозапустить прогон: вопросы, которых нет (процесс упал) или которые упали из-за сети/тайм-аута."""
    _dir(run_id)
    from app.runs import resume_run
    t = asyncio.create_task(resume_run(run_id))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return {"run_id": run_id}


@router.get("/compare/{before}/{after}", response_model=out.CompareOut)
def compare(before: str, after: str):
    """«Было/стало»: индекс, разбивка по типам и вопросы, где вердикт поменялся."""
    out = {}
    for key, rid in (("before", before), ("after", after)):
        d = _dir(rid)
        m = read_meta(rid)
        m.get("score", {}).pop("report", None)
        v = {}
        if (d / "result.csv").exists():
            with open(d / "result.csv", encoding="utf-8") as f:
                v = {r["id"]: r for r in csv.DictReader(f, delimiter=";")}
        out[key] = {"meta": m, "verdicts": v}
    b, a = out["before"]["verdicts"], out["after"]["verdicts"]
    changed = [{"id": i, "type": a[i]["type"], "before": b[i]["verdict"], "after": a[i]["verdict"],
                "why_before": b[i]["why"], "why_after": a[i]["why"]}
               for i in sorted(a) if i in b and a[i]["verdict"] != b[i]["verdict"]]
    return {"before": out["before"]["meta"], "after": out["after"]["meta"], "changed": changed}


# ---------------------------------------------------------------- лесенки для графика «было → стало»
ladders_router = APIRouter(prefix="/api/ladders", tags=["ladders"])


class LadderIn(BaseModel):
    dataset: str = "sample"
    roles: dict[str, str] | None = None
    steps: list[str] | None = None


@ladders_router.get("/steps", response_model=list[out.LadderStepDef])
def ladder_steps():
    return [{"step": s, "title": t, "pipeline": p, "options": o, "guard": g} for s, t, p, o, g in LADDER]


@ladders_router.post("", status_code=202, response_model=out.LadderStarted)
async def start_ladder(body: LadderIn):
    try:
        info = datasets.info(body.dataset)
    except DatasetError as e:
        raise HTTPException(404, str(e))
    if not info["has_questions"]:
        raise HTTPException(422, "в датасете нет questions.csv")
    lid = new_run_id()
    t = asyncio.create_task(run_ladder(body.dataset, body.roles, body.steps, ladder_id=lid))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return {"ladder_id": lid}


@ladders_router.get("", response_model=list[out.LadderOut])
def ladders():
    """Готово для графика: по каждой лесенке — шаги по порядку с индексом, верно/не знаю/обман и разбивкой по типам."""
    return list_ladders()


@ladders_router.get("/{ladder_id}", response_model=out.LadderOut)
def ladder_detail(ladder_id: str):
    """Шаги + вклад критиков (по trace шагов с критиками): сколько обманов поймал каждый и сколько ложных тревог."""
    lad = next((x for x in list_ladders() if x["id"] == ladder_id), None)
    if not lad:
        raise HTTPException(404)
    from app.analysis import analyze
    for st in lad["steps"]:
        if st["step"] in ("critics", "full") and st["status"] == "done":
            r = analyze(st["run_id"])
            st["per_critic"], st["caught"], st["false_alarms"] = r["per_critic"], r["caught"], r["false_alarms"]
    return lad
