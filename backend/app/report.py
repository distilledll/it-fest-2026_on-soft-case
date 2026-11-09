"""Отчёт для сдачи из накопленных прогонов: модель и версия, промпты, проверки, запросы и время,
лесенки «было → стало» по наборам и моделям, примеры пойманных обманов.

    python -m app.cli report --out docs/report.md
"""
from datetime import datetime

from app.analysis import analyze
from app.pipeline.agent.critics import CRITICS
from app.runs import list_ladders, list_runs

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
    """Модель + профиль: у одной модели профили различаются (напр. с рассуждениями и без)."""
    if not models:
        return "?"
    ans = models.get("answer", {})
    return f"{ans.get('model', '?')} ({ans.get('profile', '?')})"


def _last(lad: dict) -> dict:
    """Итоговый шаг лесенки — последний посчитанный (hybrid, если он есть, иначе полный агент)."""
    done = [s for s in lad["steps"] if s.get("index") is not None]
    return done[-1] if done else {}


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
    out.append("\nПрофиль и температура ответчика записаны в метаданных прогона. Фактическая модель резервного прохода указана в трассировке TrustQA.\n")

    out.append("## Было → стало\n")
    out.append("Шаги: **baseline** — модель «как есть», один запрос со всей закупкой; **«не знаю»** — тот же запрос, "
               "но разрешены статусы «нет в документах»/«не знаю» (`direct`); **промпт** — постановка задачи "
               "агента (правила про изменения, расхождения, расчёты); **критики** — проверки кодом и повторы; "
               "**полный** — плюс критик-модель; **hybrid** — плюс резервный проход TrustQA, если агент сказал "
               "«не знаю». Если закупка не влезает "
               "в контекст модели, агент на всех шагах читает её фрагментами (узел `map`, map-reduce): всю, если "
               "фрагментов не больше 30, иначе — изменения извещения, лучший фрагмент каждого файла и остальные "
               "по поиску. Baseline — один запрос на каждый вопрос со всей закупкой.\n")
    cols = [("baseline", "Baseline"), ("direct", "+ «не знаю»"), ("prompt", "Промпт"), ("critics", "+ критики"),
            ("full", "Полный агент"), ("hybrid", "+ TrustQA")]
    out.append("| Набор | Модель (профиль) | Дата | " + " | ".join(c[1] for c in cols)
               + " | Обманов: было → стало | Запросов / время (итог) |")
    out.append("|" + "---|" * (len(cols) + 5))
    for (ds, model), lad in sorted(latest.items(), key=lambda x: (x[0][1], x[0][0] or "")):
        st = {s["step"]: s for s in lad["steps"]}
        last = _last(lad)
        cell = lambda k: (f"**{st[k]['index']}**" if st[k] is last else f"{st[k]['index']}") if k in st else "—"
        b = st.get("baseline", {})
        date = (lad["id"][:4][2:] + "." + lad["id"][:2]) if lad.get("id") else "—"
        out.append(f"| {ds} | `{model}` | {date} | " + " | ".join(cell(k) for k, _ in cols)
                   + f" | {b.get('lies', '—')} → {last.get('lies', '—')} | {last.get('llm_calls', '—')} / "
                     f"{last.get('elapsed_s', '—')} с |")
    out.append("\nИндекс доверия = (верных − обманов) / всех × 100. «Не знаю» — 0 баллов. Профиль `llm` — "
               "с рассуждениями, `llm-fast` — без (по умолчанию). `qwen7b` — локальная Qwen 2.5 7B, прогон до части "
               "исправлений: проверка, что агент помогает и слабой модели.\n")

    out.append("## Map-reduce всегда (`strategy: map`)\n")
    out.append("Тот же агент, но модель всегда читает закупку фрагментами и отвечает по проверенным выпискам — "
               "максимум точности ценой числа запросов.\n")
    out.append("| Набор | Модель (профиль) | Индекс | Верно / не знаю / обман | Запросов | Время |")
    out.append("|---|---|---|---|---|---|")
    seen = set()
    for m in list_runs():
        sc = m.get("score") or {}
        if m.get("status") != "done" or (m.get("options") or {}).get("strategy") != "map" or sc.get("index") is None:
            continue
        if m.get("failed") or m.get("resumed"):
            continue                                    # прогон со сбоями сети — время не показательно
        key = (m.get("dataset_name"), _model_label(m.get("models")))
        if key in seen:
            continue
        seen.add(key)
        out.append(f"| {key[0]} | `{key[1]}` | **{sc['index']}** | {sc.get('correct')} / {sc.get('careful')} / "
                   f"{sc.get('lies')} | {m.get('llm_calls')} | {m.get('elapsed_s')} с |")
    out.append("\nВремя — при 5 одновременных запросах и не больше 2 запросов в секунду; часть прогонов попала "
               "на обрывы связи со шлюзом и шла дольше (так, hard).\n")

    out.append("## Разбивка по типам вопросов (итоговый шаг лесенки)\n")
    for (ds, model), lad in sorted(latest.items(), key=lambda x: (x[0][1], x[0][0] or "")):
        full = _last(lad)
        base = next((s for s in lad["steps"] if s["step"] == "baseline"), None)
        if not full or not full.get("by_type"):
            continue
        out.append(f"**{ds}, `{model}`**\n")
        out.append(f"| Тип вопроса | Baseline: верно / обман | {full['title']}: верно / не знаю / обман |")
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
        rows, seen = [], set()
        for s in lad["steps"]:                 # обман ловят проверки (critics) и критик-модель (full)
            if s["step"] in ("critics", "full", "hybrid"):
                for row in analyze(s["run_id"])["caught"]:
                    if row["id"] not in seen:
                        seen.add(row["id"])
                        rows.append(row)
        for row in rows[:3]:
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
