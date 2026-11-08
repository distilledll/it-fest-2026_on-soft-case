"""Отчёт для сдачи из накопленных прогонов: модель и версия, промпты, проверки, запросы и время,
лесенки «было → стало» по наборам и моделям, примеры пойманных обманов.

    python -m app.cli report --out docs/report.md
"""
from datetime import datetime

from app.analysis import analyze
from app.pipeline.agent.critics import CRITICS
from app.runs import list_ladders

CRITIC_INFO = {
    "quote": "цитата дословно есть в документах (как в check.py); почти дословная подтягивается к точному тексту",
    "number": "каждое число ответа есть в цитате или рядом с ней; при нехватке код сам ищет подтверждение",
    "amendment": "значение не из старой редакции: разбор изменений извещения (в т.ч. «по номеру пункта», «утратил силу»)",
    "conflict": "расхождение: значения одной части вопроса в разных файлах по evidence модели",
    "crosscheck": "сверка кодом без модели: тот же срок с другим числом в других файлах (веса по редкости слов)",
    "negation": "«требования нет»: «да»/число при цитате «не установлено»; «не требуется» без отрицания в цитате",
    "calc": "расчёт считает код: выражение calc, операнды из документов и не из старой редакции",
    "shape": "форма ответа: «сколько» → число, «до какой даты» → дата, «да или нет» → да/нет",
    "fields": "независимые извлекатели типовых полей (НМЦК, обеспечение, сроки, дата, гарантия) и правило "
              "«обеспечение = % × НМЦК»",
    "absent": "«нет в документах» проверяется: нет ли фразы про этот параметр с прямым отрицанием",
    "multipart": "вопрос из нескольких частей: разные части — не расхождение",
}


def _model_label(models: dict | None) -> str:
    if not models:
        return "?"
    ans = models.get("answer", {})
    return ans.get("model", "?")


def build() -> str:
    ladders = [l for l in list_ladders() if all(s["status"] == "done" for s in l["steps"])]
    latest: dict[tuple, dict] = {}
    for lad in ladders:                                   # последняя завершённая лесенка на (набор, модель)
        key = (lad.get("dataset_name"), _model_label(lad.get("models")))
        latest.setdefault(key, lad)

    out = [f"# Отчёт: ИИ, который не обманывает\n\nСобран {datetime.now():%d.%m.%Y %H:%M} из прогонов в `storage/runs`.\n"]
    out.append("## Модели\n")
    for m in sorted({k[1] for k in latest}):
        out.append(f"- `{m}`")
    out.append("\nСравнение «было/стало» — всегда на одной модели, `temperature = 0`.\n")

    out.append("## Было → стало\n")
    out.append("Шаги: **baseline** — модель «как есть», один запрос со всей закупкой; **промпт** — постановка задачи "
               "агента (статусы «нет в документах»/«не знаю», правила про изменения, расхождения, расчёты); "
               "**критики** — проверки кодом и повторы; **полный** — плюс критик-модель.\n")
    out.append("| Набор | Модель | Baseline | Промпт | + критики | Полный агент | Обманов: было → стало | Запросов / время (полный) |")
    out.append("|---|---|---|---|---|---|---|---|")
    for (ds, model), lad in sorted(latest.items(), key=lambda x: (x[0][1], x[0][0] or "")):
        st = {s["step"]: s for s in lad["steps"]}
        cell = lambda k: f"{st[k]['index']}" if k in st else "—"
        b, f = st.get("baseline", {}), st.get("full", {})
        out.append(f"| {ds} | `{model}` | {cell('baseline')} | {cell('prompt')} | {cell('critics')} | **{cell('full')}** | "
                   f"{b.get('lies', '—')} → {f.get('lies', '—')} | {f.get('llm_calls', '—')} / {f.get('elapsed_s', '—')} с |")
    out.append("\nИндекс доверия = (верных − обманов) / всех × 100. «Не знаю» — 0 баллов.\n")

    out.append("## Разбивка по типам вопросов (полный агент)\n")
    for (ds, model), lad in sorted(latest.items(), key=lambda x: (x[0][1], x[0][0] or "")):
        full = next((s for s in lad["steps"] if s["step"] == "full"), None)
        base = next((s for s in lad["steps"] if s["step"] == "baseline"), None)
        if not full or not full.get("by_type"):
            continue
        out.append(f"**{ds}, `{model}`**\n")
        out.append("| Тип вопроса | Baseline: верно / обман | Агент: верно / не знаю / обман |")
        out.append("|---|---|---|")
        for t, v in sorted(full["by_type"].items()):
            bv = (base or {}).get("by_type", {}).get(t, {})
            out.append(f"| {t} | {bv.get('верно', 0)} / {bv.get('обман', 0)} | "
                       f"{v.get('верно', 0)} / {v.get('осторожно', 0)} / {v.get('обман', 0)} |")
        out.append("")

    out.append("## Проверки\n")
    out.append("| Проверка | Что ловит |")
    out.append("|---|---|")
    for name in CRITICS:
        out.append(f"| `{name}` | {CRITIC_INFO.get(name, '')} |")
    out.append("| `llm_critic` | вторая модель видит ответ, все цитаты и расчёт: соседний параметр, пропущенное отрицание |")
    out.append("| `guard` | финальный рубеж после любого пайплайна: цитата и числа, иначе «не знаю» |\n")

    out.append("## Пойманные обманы (примеры)\n")
    shown = 0
    for (ds, model), lad in latest.items():
        full = next((s for s in lad["steps"] if s["step"] == "full"), None)
        if not full:
            continue
        r = analyze(full["run_id"])
        for row in r["caught"][:3]:
            d, f = row["draft"], row["final"]
            msgs = [s["message"] if isinstance(s, dict) else s.message for s in row["steps"]
                    if (s["ok"] if isinstance(s, dict) else s.ok) is False][:2]
            out.append(f"- **{row['id']}** ({ds}, `{model}`), {row['type']}: «{row['question']}»  \n"
                       f"  черновик модели: *{d['status']}: {d['answer']}* — {row['draft_why']}  \n"
                       f"  поймано: {', '.join(row['critics'])} — {'; '.join(m[:160] for m in msgs)}  \n"
                       f"  итог: *{f['status']}: {f['answer']}*")
            shown += 1
    if not shown:
        out.append("_Пока нет: нужен прогон полного агента на датасете с эталоном._")

    out.append("\n## Промпты и формат\n")
    out.append("- Промпты агента: `backend/app/pipeline/agent/prompts.py`; baseline: `backend/app/pipeline/baseline.py`.")
    out.append("- Формат ответа модели (строгий JSON): `backend/docs/json-contract.md`.")
    out.append("- Ключи моделей — только в `backend/.env` (в git не попадает).\n")
    out.append("## Запуск\n")
    out.append("```\npython -m app.cli run --data <архив.zip> --pipeline agent --out answers.csv\n"
               "python -m app.cli resume <run_id>      # если сеть отвалилась посреди прогона\n```")
    return "\n".join(out) + "\n"
