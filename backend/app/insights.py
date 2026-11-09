"""Что заметили проверки в прогоне — без эталона.

Контрольный набор приходит без ответов, поэтому индекс доверия не посчитать. Но по ходу проверки (trace)
видно, где проверка нашла несоответствие и чем кончилось: модель исправила ответ, система честно сказала
«не знаю» или ответ подтвердился. Если к набору загрузили эталон, к каждому событию добавляется вердикт check.py.
"""
import csv
import json
import re
from collections import Counter

from app import datasets
from app.config import settings
from app.ingest import load_questions
from app.schemas import Answer, Status

# Человеческие названия проверок — для ленты событий на дашборде.
TITLES = {
    "quote": "Цитата", "number": "Числа", "amendment": "Изменения извещения", "conflict": "Расхождение",
    "crosscheck": "Сверка файлов", "negation": "Отрицание", "calc": "Расчёт", "shape": "Форма ответа",
    "fields": "Типовые поля", "absent": "«Нет в документах»", "multipart": "Части вопроса",
    "llm_critic": "Критик-модель", "guard_quote": "Финальная проверка цитаты",
    "guard_number": "Финальная проверка чисел", "coverage": "Полнота чтения", "trustqa": "Резервный проход",
    "format": "Формат ответа модели",
}
WHAT = {   # что проверка ловит — одной фразой, для подсказки
    "quote": "цитаты нет в документах дословно", "number": "числа из ответа нет в цитате",
    "amendment": "значение из старой редакции, отменённой изменениями", "conflict": "расхождение между файлами",
    "crosscheck": "в других файлах то же значение записано иначе", "negation": "«требования нет» без отрицания в тексте",
    "calc": "расчёт не сходится", "shape": "ответ не той формы (не число, не дата, не да/нет)",
    "fields": "типовое поле (НМЦК, обеспечение, сроки) расходится с документом",
    "absent": "«нет в документах», хотя документ об этом говорит", "multipart": "части вопроса перепутаны",
    "llm_critic": "ответ про другой параметр", "guard_quote": "цитаты нет в документах",
    "guard_number": "числа нет рядом с цитатой", "coverage": "прочитано не всё — отсутствие не доказано",
    "trustqa": "резервный проход не подтвердил ответ", "format": "модель вернула не тот формат",
}
OUTCOMES = {"fixed": "исправлено", "refused": "«не знаю» вместо неподтверждённого ответа", "kept": "подтверждено"}


def _check_of(step) -> str | None:
    if step.ok is not False:
        return None
    if step.node.startswith("critic_"):
        return step.node[len("critic_"):]
    if step.node in ("llm_critic", "guard_quote", "guard_number", "coverage", "trustqa"):
        return step.node
    if step.node == "answer":            # модель вернула не JSON / не тот статус
        return "format"
    return None


def _verdicts(run_dir) -> dict[str, dict]:
    p = run_dir / "result.csv"
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return {r["id"]: {"verdict": r["verdict"], "why": r.get("why", "")} for r in csv.DictReader(f, delimiter=";")}


def insights(run_id: str) -> dict:
    run_dir = settings.runs_dir / run_id
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    trace = run_dir / "trace.jsonl"
    answers = ([Answer.model_validate_json(l) for l in trace.read_text(encoding="utf-8").splitlines() if l.strip()]
               if trace.exists() else [])
    data_dir = datasets.path_of(meta["dataset"])
    questions = {q.id: q for q in load_questions(data_dir)} if (data_dir / "questions.csv").exists() else {}
    verdicts = _verdicts(run_dir)

    per_check: dict[str, Counter] = {}
    events = []
    for a in answers:
        fired: dict[str, str] = {}
        for s in a.trace:
            if (name := _check_of(s)) and name not in fired:
                fired[name] = s.message
        if not fired:
            continue
        retried = any(s.node == "retry" for s in a.trace)
        outcome = "refused" if a.status == Status.UNKNOWN else ("fixed" if retried else "kept")
        first = next((s.message for s in a.trace if s.node == "answer" and s.ok), "")
        for name in fired:
            c = per_check.setdefault(name, Counter())
            c["fired"] += 1
            c[outcome] += 1
        q = questions.get(a.id)
        lead = next(iter(fired))
        events.append({
            "id": a.id, "package": q.package if q else "", "question": q.question if q else "",
            "checks": [{"check": n, "title": TITLES.get(n, n), "what": WHAT.get(n, ""), "message": m[:400]}
                       for n, m in fired.items()],
            "draft": re.sub(r"^попытка \d+:\s*", "", first),
            "final": {"status": a.status.value, "answer": a.answer, "quote": a.quote, "file": a.file},
            "outcome": outcome, "outcome_title": OUTCOMES[outcome],
            "summary": f"{TITLES.get(lead, lead)}: {WHAT.get(lead, '')}. Итог — {OUTCOMES[outcome]}.",
            "verdict": verdicts.get(a.id),
        })
    statuses = Counter(a.status.value for a in answers)
    return {
        "run_id": run_id, "label": meta.get("label", ""), "pipeline": meta.get("pipeline"),
        "dataset": meta.get("dataset"), "has_gold": bool(verdicts), "n": len(answers),
        "statuses": {s.value: statuses.get(s.value, 0) for s in Status},
        "with_checks": len(events), "clean": len(answers) - len(events),
        "outcomes": {k: sum(e["outcome"] == k for e in events) for k in OUTCOMES},
        "checks": sorted(({"check": n, "title": TITLES.get(n, n), "what": WHAT.get(n, ""), "fired": c["fired"],
                           "fixed": c["fixed"], "refused": c["refused"], "kept": c["kept"]}
                          for n, c in per_check.items()), key=lambda x: -x["fired"]),
        "events": events,
    }
