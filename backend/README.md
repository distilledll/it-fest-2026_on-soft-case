# Бэкенд

## Запуск

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -e ".[dev,agent]"
cp .env.example .env                      # LLM_BASE_URL / LLM_MODEL / LLM_API_KEY
.venv/bin/uvicorn app.main:app --reload   # http://localhost:8000/docs
.venv/bin/pytest -q
```

Или из корня: `docker compose up -d --build`.

### CLI

```bash
python -m app.cli run --pipeline baseline --no-guard --label "было"     # точка «было» на примере
python -m app.cli run --pipeline agent --label "стало: критики"         # «стало»
python -m app.cli run --data /путь/к/контрольному.zip --pipeline agent --out answers.csv   # день защиты
python -m app.cli run ... --role answer=<profile> --role critic=<profile>                   # другие модели
python -m app.cli runs      # история прогонов с индексом доверия
python -m app.cli models    # профили моделей и роли
```

Если в датасете нет `answers_public.json`, оценка пропускается, но `answers.csv` всё равно пишется.

## Устройство

```
app/
  config.py          настройки из .env
  schemas.py         контракт: Status, Question, Document, Answer, TraceStep
  llm.py             профили моделей (OpenAI-совместимый API) и роли answer/critic/embed/rerank
  datasets.py        датасеты: встроенный "sample" + загруженные zip / .txt
  ingest.py          чтение документов: utf-8/cp1251, пустые файлы, флаг «инструкция в тексте»
  verify.py          проверки кодом после любого пайплайна (цитата, число в цитате) → иначе «не знаю»
  runs.py            прогон набора → storage/runs/<id>/, оценка оригинальным check.py
  pipeline/base.py   интерфейс Pipeline + Context (модели по ролям, опции)
  pipeline/stub.py   заглушка без модели
  pipeline/baseline.py  «было»: один запрос, вся закупка
  pipeline/agent/    LangGraph-агент
    graph.py         prepare → answer → check (критики кодом) → llm_critic → retry … → finalize
    critics.py       узкие критики: quote, number, amendment, conflict, crosscheck, negation, calc
    context.py       вся закупка или фрагменты (RAG / keyword fallback), вырезание инъекций, пустые файлы
    prompts.py       промпты агента
  rag/               ретривер, реранкер, промпты
  api/               HTTP: datasets, models, ask, runs
storage/             (в корне репо, в .gitignore) datasets/, runs/, models.json
```

## Модели

Профиль — это подключение: `base_url`, `model`, ключ, `extra_headers`, `temperature`, `max_tokens`,
`disable_thinking`, `extra_body`. Роль указывает, какой профиль для чего используется:
`answer`, `critic`, `embed`, `rerank`. Если для роли профиль не назначен, берётся профиль `answer`.

- Ключ лучше хранить в `.env` и указывать в профиле имя переменной (`api_key_env`).
  Ключ, сохранённый через API, лежит в `storage/models.json` и наружу не отдаётся (`has_key: true/false`).
- `extra_headers` пишется в формате `User-Agent=...;X-Foo=bar`: некоторые шлюзы отвергают дефолтный UA SDK.
- Модели в прогоне фиксируются в `meta.json`. «Было» и «стало» нужно сравнивать на одном профиле
  с `temperature=0`.

## Агент

Цикл: модель отвечает в JSON со списком `evidence` (все места, где упоминается параметр), критики кодом
проверяют ответ, при `error`/`warn` идёт повтор с текстом замечаний, после — критик-модель. Если бюджет
попыток кончился, а ошибки остались, ответ «не знаю».

| Критик | Ловушка | Как ловит |
|---|---|---|
| `quote` | выдуманная цитата | дословный поиск как в check.py; почти дословную подтягивает к точному тексту |
| `number` | число не из документа | каждое число ответа должно быть в цитате или рядом с ней |
| `amendment` | старое значение вместо изменённого | разбирает «Пункт «…» изложить в следующей редакции «…»», бракует цитаты из старой редакции |
| `conflict` | пропущенное / выдуманное расхождение | сравнивает значения из `evidence` модели по файлам |
| `crosscheck` | пропущенное расхождение без evidence | сам ищет в других файлах тот же срок (дни/месяцы) с другим числом (warn) |
| `negation` | «требования нет» | «да» или число при цитате «не установлено/не требуется»; шаблон «если иное не установлено» не считается |
| `calc` | ошибка в расчёте | выражение из `calc` считает код, операнды должны быть в документах и не из старой редакции |
| `llm_critic` | всё остальное | вторая модель (роль `critic`) смотрит ответ + контекст цитаты |

Опции (`options` в `/api/ask` и `/api/runs`) нужны для замера вклада каждого:

```json
{"critics": ["quote", "number", "amendment"], "llm_critic": false, "max_attempts": 3, "context_chars": 60000}
```

Если документы закупки больше `context_chars`, в контекст идут фрагменты от `app.rag.retrieve(...)`, если он есть,
иначе от keyword-поиска. Изменения извещения попадают в контекст всегда целиком.

## Контракт для пайплайна (агент / RAG)

```python
class AgentPipeline:
    name = "agent"
    async def answer(self, q: Question, docs: list[Document], ctx: Context) -> Answer: ...
    async def stream(self, q, docs, ctx):   # yield TraceStep ..., последним — Answer
        ...
```

- `ctx.model("answer" | "critic" | "embed" | "rerank")` возвращает `ModelProfile`. Вызов модели: `await llm.chat(profile, messages)`.
- `ctx.options` — флаги из запроса, например какие критики включены. Нужно для замера вклада каждого.
- `Answer.trace` — шаги (`node`, `ok`, `message`, `data`). Фронт показывает по ним, как был пойман обман.
- `Answer.llm_calls` — число вызовов модели, его нужно указать в описании решения.
- Исключения можно не ловить: бэк превратит их в «не знаю». Таймаут на вопрос задаётся в `QUESTION_TIMEOUT_S`.
- `verify.guard` срабатывает после пайплайна (если `guard=true`).

## API

Полная схема есть в `/docs`.

| Метод | Путь | Что |
|---|---|---|
| GET | `/api/health` | пайплайны, модели по ролям |
| GET | `/api/datasets` | датасеты (`sample` + загруженные): закупки, есть ли вопросы и эталон |
| POST | `/api/datasets` | multipart `files` (один .zip или несколько .txt), `name`, `package` |
| GET | `/api/datasets/{id}` | закупки и файлы (кодировка, пустой ли, предупреждения) |
| DELETE | `/api/datasets/{id}` | удалить загруженный |
| GET | `/api/datasets/{id}/questions` | вопросы (пусто, если нет questions.csv) |
| GET | `/api/datasets/{id}/packages/{p}/files/{f}` | текст документа (для подсветки цитаты) |
| GET | `/api/models` | профили (без ключей) + роли |
| POST / PATCH / DELETE | `/api/models[/{id}]` | управление профилями |
| PUT | `/api/models/roles` | `{"answer": "<id>", "critic": "<id>"}` |
| POST | `/api/models/{id}/test` | проверить подключение |
| GET | `/api/models/{id}/remote` | какие модели отдаёт API (`GET /models`) |
| POST | `/api/ask` | `{dataset, package, question, pipeline?, roles?, options?, guard?}` → `Answer` |
| POST | `/api/ask/stream` | то же через SSE: события `step` и финальное `answer` |
| POST | `/api/runs` | `{dataset, pipeline?, label, guard, roles?, options?}` → `{run_id}` (в фоне) |
| GET | `/api/runs` | список прогонов: статус, прогресс, индекс, разбивка по типам |
| GET | `/api/runs/{id}` | по вопросам: ответ, trace, вердикт check.py |
| GET | `/api/runs/{id}/answers.csv` | файл для сдачи |
| GET | `/api/runs/compare/{before}/{after}` | «было/стало»: метрики обоих + вопросы, где вердикт изменился |
