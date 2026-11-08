"""Разбор прогона: какие обманы система поймала и каким критиком.

Первый черновик модели (до проверок) судится той же функцией judge из check.py, что и итог.
Черновик «обман», итог — нет → обман пойман; заслуга — у критиков, сработавших в этом вопросе.
Черновик «верно», итог — нет → ложная тревога (проверки испортили верный ответ).
"""
import importlib.util
import json
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from app import datasets
from app.config import settings
from app.ingest import norm


@lru_cache
def _checker(path: str):
    spec = importlib.util.spec_from_file_location("onsoft_check", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _judge_fn(data_dir: Path):
    from app.datasets import checker_for
    chk = _checker(str(checker_for(data_dir)[0]))
    gold = {g["id"]: g for g in json.loads((data_dir / "answers_public.json").read_text(encoding="utf-8"))}
    docs: dict[str, dict] = {}

    def judge(qid: str, row: dict | None) -> tuple[str, str]:
        g = gold[qid]
        if g["package"] not in docs:
            pdir = data_dir / "packages" / g["package"]
            docs[g["package"]] = {f.name: norm(chk.read_file(f)) for f in sorted(pdir.glob("*.txt"))}
        return chk.judge(g, row, docs[g["package"]])

    return judge, gold


def _first_draft(item: dict) -> dict | None:
    for t in item["trace"]:
        if t["node"] == "answer" and t.get("data", {}).get("draft"):
            return t["data"]["draft"]
    return None


def analyze(run_id: str) -> dict:
    rdir = settings.runs_dir / run_id
    meta = json.loads((rdir / "meta.json").read_text(encoding="utf-8"))
    data_dir = datasets.path_of(meta["dataset"])
    items = [json.loads(line) for line in (rdir / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    has_gold = (data_dir / "answers_public.json").exists()
    judge, gold = _judge_fn(data_dir) if has_gold else (None, {})

    per_critic: dict[str, Counter] = defaultdict(Counter)
    caught, false_alarms = [], []
    for it in items:
        fired = sorted({t["node"].removeprefix("critic_") for t in it["trace"]
                        if t.get("ok") is False and (t["node"].startswith("critic_")
                                                     or t["node"] in ("llm_critic", "guard_quote", "guard_number"))})
        for c in fired:
            per_critic[c]["fired"] += 1
        draft = _first_draft(it)
        if not (judge and draft and it["id"] in gold):
            continue
        before, why_before = judge(it["id"], {k: str(draft.get(k, "")) for k in ("status", "answer", "quote", "file")})
        after, _ = judge(it["id"], {"status": it["status"], "answer": it["answer"], "quote": it["quote"],
                                    "file": it["file"]})
        row = {"id": it["id"], "type": gold[it["id"]]["type"], "question": gold[it["id"]]["question"],
               "draft": {k: draft.get(k) for k in ("status", "answer", "quote", "file")},
               "draft_verdict": before, "draft_why": why_before,
               "final": {k: it[k] for k in ("status", "answer", "quote", "file")}, "final_verdict": after,
               "critics": fired,
               "steps": [t for t in it["trace"] if t.get("ok") is False or t["node"] in ("retry", "finalize")]}
        if before == "обман" and after != "обман":
            caught.append(row)
            for c in fired:
                per_critic[c]["caught"] += 1
        elif before == "верно" and after != "верно":
            false_alarms.append(row)
            for c in fired:
                per_critic[c]["false_alarm"] += 1

    return {"run_id": run_id, "label": meta.get("label"), "has_gold": has_gold,
            "caught": caught, "false_alarms": false_alarms,
            "per_critic": {c: dict(v) for c, v in sorted(per_critic.items())}}
