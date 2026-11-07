"""Прогоны набора вопросов и данные для дашборда «было/стало»."""
import asyncio
import csv
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import datasets
from app.config import settings
from app.datasets import DatasetError
from app.pipeline.base import PIPELINES
from app.runs import list_runs, new_run_id, read_meta, run_set

router = APIRouter(prefix="/api/runs", tags=["runs"])
_tasks: set[asyncio.Task] = set()


class RunIn(BaseModel):
    dataset: str = "sample"
    pipeline: str | None = None
    label: str = ""
    guard: bool = True
    roles: dict[str, str] | None = None
    options: dict = Field(default_factory=dict)


@router.post("", status_code=202)
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


@router.get("")
def runs():
    return list_runs()


def _dir(run_id: str):
    d = settings.runs_dir / run_id
    if "/" in run_id or ".." in run_id or not (d / "meta.json").exists():
        raise HTTPException(404)
    return d


@router.get("/{run_id}")
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


@router.get("/{run_id}/answers.csv")
def run_csv(run_id: str):
    return FileResponse(_dir(run_id) / "answers.csv", media_type="text/csv", filename="answers.csv")


@router.get("/compare/{before}/{after}")
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
