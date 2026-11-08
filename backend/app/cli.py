"""Прогон без сервера. Главное для дня защиты: распаковали архив → одна команда → answers.csv.

python -m app.cli run --label baseline --pipeline baseline --no-guard          # «было» на примере
python -m app.cli run --data /путь/к/архиву.zip --pipeline agent --out answers.csv  # контрольный набор
python -m app.cli runs
python -m app.cli models
"""
import argparse
import asyncio
import json
import shutil
from pathlib import Path

from app import datasets, llm
from app.config import settings
from app.runs import list_runs, run_set


def _dataset(arg: str) -> str:
    p = Path(arg)
    if p.suffix.lower() == ".zip" and p.is_file():
        return datasets.from_zip(p.read_bytes(), p.name)
    if p.is_dir():
        # папку регистрируем той же логикой, что и zip: копия в storage, те же проверки
        return datasets.from_zip(_zip_dir(p), p.name)
    return arg  # id существующего датасета


def _zip_dir(p: Path) -> bytes:
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in p.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(p))
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--data", default="sample", help="id датасета, путь к .zip или к папке")
    r.add_argument("--pipeline", default=settings.pipeline)
    r.add_argument("--label", default="")
    r.add_argument("--no-guard", action="store_true", help="без финальных проверок (для «было»)")
    r.add_argument("--role", action="append", default=[], metavar="ROLE=PROFILE",
                   help="переопределить модель, напр. --role answer=gpt --role critic=small")
    r.add_argument("--out", type=Path, help="куда дополнительно скопировать answers.csv")
    r.add_argument("--options", default="{}", help='опции пайплайна JSON, напр. \'{"critics": [], "llm_critic": false}\'')
    r.add_argument("--concurrency", type=int, help="параллельных запросов к API (по лимиту ключа); "
                                                   "влияет только на скорость")
    sub.add_parser("runs")
    rs = sub.add_parser("resume", help="дозапустить прогон: недостающие и упавшие (сеть, тайм-аут) вопросы")
    rs.add_argument("run_id")
    rs.add_argument("--out", type=Path)
    rs.add_argument("--concurrency", type=int)
    sb = sub.add_parser("subset", help="поднабор вопросов датасета (с эталоном) для дорогих экспериментов")
    sb.add_argument("--data", required=True)
    sb.add_argument("--ids", required=True, help="через запятую")
    sb.add_argument("--name", default="поднабор")
    ld = sub.add_parser("ladder", help="все слои (baseline → промпт → критики → критик-модель) на одном датасете")
    ld.add_argument("--data", default="sample")
    ld.add_argument("--role", action="append", default=[], metavar="ROLE=PROFILE")
    ld.add_argument("--steps", help="через запятую: baseline,prompt,critics,full")
    ld.add_argument("--concurrency", type=int)
    an = sub.add_parser("analyze", help="какие обманы поймала система и каким критиком")
    an.add_argument("run_id")
    sub.add_parser("models")
    a = ap.parse_args()

    if a.cmd == "run":
        if a.concurrency:
            settings.llm_concurrency = settings.max_concurrency = a.concurrency
        roles = dict(x.split("=", 1) for x in a.role)
        did = _dataset(a.data)
        meta = asyncio.run(run_set(did, a.pipeline, a.label, not a.no_guard, roles or None, json.loads(a.options)))
        report = meta.get("score", {}).pop("report", "")
        print(report or f"оценки нет (в датасете нет answers_public.json), статусы: {meta['statuses']}")
        print(f"run_id={meta['run_id']}  dataset={did}  llm_calls={meta['llm_calls']}  {meta['elapsed_s']}s"
              + (f"  УПАВШИХ: {meta['failed']} — дозапуск: python -m app.cli resume {meta['run_id']}" if meta.get("failed") else ""))
        if a.out:
            shutil.copy(settings.runs_dir / meta["run_id"] / "answers.csv", a.out)
            print(f"answers.csv → {a.out}")
    elif a.cmd == "runs":
        for m in list_runs():
            s = m.get("score", {})
            print(f"{m['run_id']}  {m['status']:8} {m['pipeline']:8} guard={m['guard']!s:5} "
                  f"index={s.get('index', '—'):>6}  {m['dataset']:18} {m['label']}")
    elif a.cmd == "ladder":
        from app.runs import list_ladders, run_ladder
        if a.concurrency:
            settings.llm_concurrency = settings.max_concurrency = a.concurrency
        did = _dataset(a.data)
        lid = asyncio.run(run_ladder(did, dict(x.split("=", 1) for x in a.role) or None,
                                     a.steps.split(",") if a.steps else None))
        lad = next(x for x in list_ladders() if x["id"] == lid)
        print(f"лесенка {lid}, датасет {lad['dataset_name']}")
        for st in lad["steps"]:
            print(f"  {st['title']:34} индекс {st['index']!s:>6}  верно {st['correct']}  не знаю {st['careful']}  "
                  f"обман {st['lies']}  запросов {st['llm_calls']}  {st['elapsed_s']} с")
    elif a.cmd == "resume":
        from app.runs import resume_run
        if a.concurrency:
            settings.llm_concurrency = settings.max_concurrency = a.concurrency
        meta = asyncio.run(resume_run(a.run_id))
        report = meta.get("score", {}).pop("report", "")
        print(report or f"статусы: {meta['statuses']}")
        print(f"run_id={meta['run_id']}  дозапущено {meta.get('resumed')}  упавших осталось {meta.get('failed')}")
        if a.out:
            shutil.copy(settings.runs_dir / meta["run_id"] / "answers.csv", a.out)
            print(f"answers.csv → {a.out}")
    elif a.cmd == "subset":
        did = datasets.subset(_dataset(a.data), [x.strip() for x in a.ids.split(",") if x.strip()], a.name)
        print(f"датасет {did}: {datasets.info(did)}")
    elif a.cmd == "analyze":
        from app.analysis import analyze
        r = analyze(a.run_id)
        print(f"{r['label']}: поймано обманов {len(r['caught'])}, ложных тревог {len(r['false_alarms'])}")
        for c, v in r["per_critic"].items():
            print(f"  {c:12} сработал {v.get('fired', 0):3}  поймал {v.get('caught', 0):3}  ложно {v.get('false_alarm', 0):3}")
        for row in r["caught"]:
            d, f = row["draft"], row["final"]
            print(f"  ✓ {row['id']} [{row['type']}] {row['draft_why']}: «{d['status']}: {d['answer']}» → "
                  f"«{f['status']}: {f['answer']}»  ({', '.join(row['critics'])})")
        for row in r["false_alarms"]:
            print(f"  ✗ {row['id']} [{row['type']}] верный «{row['draft']['answer']}» → «{row['final']['status']}» "
                  f"({', '.join(row['critics'])})")
    elif a.cmd == "models":
        reg = llm.load()
        for p in reg.profiles:
            print(f"{p.id:10} {p.model:30} {p.base_url}  key={'да' if p.resolve_key() else 'НЕТ'}")
        print("роли:", reg.roles or "не назначены")


if __name__ == "__main__":
    main()
