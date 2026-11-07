"""Прогон без сервера. Главное для дня защиты: распаковали архив → одна команда → answers.csv.

python -m app.cli run --label baseline --pipeline baseline --no-guard          # «было» на примере
python -m app.cli run --data /путь/к/архиву.zip --pipeline agent --out answers.csv  # контрольный набор
python -m app.cli runs
python -m app.cli models
"""
import argparse
import asyncio
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
    r.add_argument("--concurrency", type=int, help="параллельных запросов к API (по лимиту ключа); "
                                                   "влияет только на скорость")
    sub.add_parser("runs")
    sub.add_parser("models")
    a = ap.parse_args()

    if a.cmd == "run":
        if a.concurrency:
            settings.llm_concurrency = settings.max_concurrency = a.concurrency
        roles = dict(x.split("=", 1) for x in a.role)
        did = _dataset(a.data)
        meta = asyncio.run(run_set(did, a.pipeline, a.label, not a.no_guard, roles or None))
        report = meta.get("score", {}).pop("report", "")
        print(report or f"оценки нет (в датасете нет answers_public.json), статусы: {meta['statuses']}")
        print(f"run_id={meta['run_id']}  dataset={did}  llm_calls={meta['llm_calls']}  {meta['elapsed_s']}s")
        if a.out:
            shutil.copy(settings.runs_dir / meta["run_id"] / "answers.csv", a.out)
            print(f"answers.csv → {a.out}")
    elif a.cmd == "runs":
        for m in list_runs():
            s = m.get("score", {})
            print(f"{m['run_id']}  {m['status']:8} {m['pipeline']:8} guard={m['guard']!s:5} "
                  f"index={s.get('index', '—'):>6}  {m['dataset']:18} {m['label']}")
    elif a.cmd == "models":
        reg = llm.load()
        for p in reg.profiles:
            print(f"{p.id:10} {p.model:30} {p.base_url}  key={'да' if p.resolve_key() else 'НЕТ'}")
        print("роли:", reg.roles or "не назначены")


if __name__ == "__main__":
    main()
