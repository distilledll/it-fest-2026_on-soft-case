# ИИ, который не обманывает — кейс ОНСОФТ

ИИ-помощник отвечает на вопросы по документам госзакупок с дословной цитатой. Если проверки
не проходят, он честно отвечает «не знаю» или «нет в документах», а не выдумывает.

```
backend/      FastAPI, агент (LangGraph), проверки, прогоны и оценка   → backend/README.md
backend/app/rag/  ретривер, реранкер, промпты
frontend/     веб-интерфейс: загрузка данных, вопросы, дашборд «было/стало»
data/sample/  пример организатора: закупки, вопросы, эталон, check.py
storage/      рантайм-данные (не в git)
```

## Быстрый старт

```bash
cp backend/.env.example backend/.env    # вписать подключение к модели
docker compose up -d --build            # API: http://localhost:8000/docs
```

Без Docker см. `backend/README.md`.

## Оценка

```bash
python data/sample/check.py storage/runs/<run_id>/answers.csv
```

Индекс доверия = (верных − обманов) / всех × 100. «Не знаю» — 0 баллов, обман — минус.
