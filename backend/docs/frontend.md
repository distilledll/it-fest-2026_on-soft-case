# API для фронта

Swagger: **`/docs`** (там можно вызывать ручки), ReDoc: `/redoc`, схема: `/openapi.json`.
Типы для TypeScript: `npx openapi-typescript http://localhost:8000/openapi.json -o src/api.d.ts`.

CORS открыт для всех адресов. Без модели можно работать, передав в запросах `"pipeline": "stub"`:
ответы мгновенные и бесплатные, для вёрстки этого хватает.

## Словарь

| Что | Значения |
|---|---|
| `status` ответа | `ответ`, `расхождение`, `нет в документах`, `не знаю` |
| `verdict` (check.py) | `верно` (+1), `осторожно` (это «не знаю», 0), `обман` (−1) |
| Индекс доверия | `(верно − обман) / всего × 100`; это главная цифра на дашборде |
| `node` шага (TraceStep) | `prepare`, `decompose`, `map`, `extract`, `votes`, `answer`, `check`, `critic_<имя>`, `llm_critic`, `retry`, `research`, `finalize`, `guard_quote`, `guard_number`, `error` |
| `ok` шага | `true` — прошло, `false` — проверка поймала проблему (подсвечивать красным), `null` — служебный шаг |
| Шаги лесенки | `baseline` → `prompt` → `critics` → `full` (порядок в поле `order`) |

## Сценарии

### 1. Загрузка данных
```
POST /api/datasets    multipart/form-data: files=<один .zip | несколько .txt>, name=<подпись>, package=<P01>
→ DatasetInfo {id, name, packages[], has_questions, has_gold}
GET /api/datasets     — список (первым идёт "sample", это пример организатора)
GET /api/datasets/{id} — закупки и файлы: кодировка, пустой ли файл, warnings (например, «инструкция для ИИ»)
```
- Если `has_questions: false`, вопросы задаются только строкой ввода (сценарий 2), прогоны недоступны.
- Если `has_gold: false`, прогоны работают, но без оценки: в `meta.score` ничего не будет.

### 2. Вопрос строкой ввода (живой вопрос жюри)
```
POST /api/ask/stream   {"dataset": "sample", "package": "P01", "question": "Какой срок выполнения работ?"}
```
Ответ — SSE. Приходят события `step` (TraceStep) по мере работы агента, последним одно событие `answer` (Answer):
```
event: step
data: {"node": "prepare", "ok": true, "message": "режим: full", "data": {}}

event: step
data: {"node": "critic_conflict", "ok": false, "message": "в документах разные значения: 60 … 75 …"}

event: answer
data: {"id": "adhoc", "status": "расхождение", "answer": "60 и 75", "quote": "60 календарных дней",
       "file": "01_izveshchenie.txt", "trace": [...], "llm_calls": 3, "elapsed_s": 12.4}
```
`EventSource` в браузере умеет только GET, поэтому для POST используйте `fetch` с чтением `response.body`
или `@microsoft/fetch-event-source`. Без потока: `POST /api/ask` с тем же телом вернёт сразу Answer.

**Подсветка цитаты:** `GET /api/datasets/{id}/packages/{package}/files/{file}` отдаёт Document с полным текстом.
Цитата сверяется без учёта регистра, пробелов, вида кавычек и ё/е. Для поиска в тексте нормализуйте
и цитату, и текст одинаково.

### 3. Прогон набора и сдача
```
POST /api/runs  {"dataset": "sample", "label": "стало", "pipeline": "agent"}   → {run_id}
GET  /api/runs/{run_id}   — опрашивать раз в 2–3 с, пока meta.status == "running"; прогресс в meta.progress {done, total}
GET  /api/runs/{run_id}/answers.csv   — файл для сдачи
```
В `GET /api/runs/{run_id}` поле `items[]` — это ответ по каждому вопросу (Answer) плюс `verdict` {verdict, why, type}.

### 4. Дашборд «было → стало»
```
GET /api/ladders          — все лесенки; на каждую steps[] уже в порядке для графика
GET /api/ladders/{id}     — то же + per_critic, caught, false_alarms на шагах critics/full
POST /api/ladders {"dataset": "sample"}   — запустить новую лесенку (4 прогона подряд)
```
Что рисовать:
- **Столбцы индекса доверия** по шагам: `steps[].index`. Подписи берите из `steps[].title`.
- **Стопка верно / не знаю / обман** по шагам: `correct`, `careful`, `lies`.
- **Разбивка по типам вопросов:** `steps[].by_type` — `{ "ловушка: нет в документах": {верно, осторожно, обман}, … }`.
- **Цена:** `llm_calls`, `elapsed_s` (сколько запросов к модели и секунд ушло на набор).
- **Вклад критиков:** `per_critic` — `{conflict: {fired, caught, false_alarm}, …}`.

### 5. «Покажите обман, который поймала система»
```
GET /api/runs/{run_id}/caught
```
`caught[]` — вопросы, где **первый черновик модели был обманом**, а итог системы нет:
- `draft` — что модель ответила сначала, `draft_why` — почему это обман по check.py;
- `critics` — какие проверки сработали;
- `steps` — что именно сказала каждая проверка, повторы и итог;
- `final` — итоговый ответ.

`false_alarms[]` — честная обратная сторона: проверки испортили верный ответ. В идеале список пуст.

### 6. Сравнение двух прогонов
```
GET /api/runs/compare/{before}/{after}   → метрики обоих + changed[] (вопросы, где вердикт изменился)
```

### 7. Модели
Каждое подключение — **профиль** (адрес OpenAI-совместимого API, модель, ключ). Профиль назначается на **роль**:
`answer` — отвечает, `critic` — проверяет ответ, `embed` — эмбеддинги для поиска фрагментов. У LLM и эмбеддингов
могут быть разные адреса и ключи.

```
GET    /api/models                — профили (ключи не отдаются, только has_key) и роли
POST   /api/models                — добавить профиль
PATCH  /api/models/{id}           — изменить поля (api_key: "" — стереть ключ)
DELETE /api/models/{id}
POST   /api/models/{id}/test      — проверить подключение (для embedding вернёт dimensions)
GET    /api/models/{id}/remote    — какие модели отдаёт API (выбор из списка)
PUT    /api/models/roles          {"answer": "<id>", "critic": "<id>", "embed": "<id>"}
```

LLM:
```json
POST /api/models
{"id": "llm-fast", "name": "Шлюз, без рассуждений", "kind": "chat",
 "base_url": "https://.../api/v1", "model": "cifra48/llm", "api_key": "<ключ>",
 "extra_headers": "User-Agent=Mozilla/5.0", "disable_thinking": true}
```
Эмбеддинги:
```json
POST /api/models
{"id": "embedding", "name": "Эмбеддинги", "kind": "embedding",
 "base_url": "https://.../api/v1", "model": "cifra48/embedding", "api_key": "<свой ключ>",
 "extra_headers": "User-Agent=Mozilla/5.0",
 "embed_query_task": "retrieval.query", "embed_passage_task": "retrieval.passage", "embed_dimensions": 256}
```
- `kind`: `chat` (роли answer/critic) или `embedding` (роль embed). Назначить модель не на свою роль нельзя: 422.
- Первый добавленный профиль сам становится ролью `answer` (или `embed` для embedding).
- `embed_query_task` / `embed_passage_task` / `embed_dimensions` — нестандартные поля запроса `/embeddings`.
  Задавайте, только если API их понимает (шлюз — да; OpenAI понимает только `dimensions`). Не заданы — не отправляются.
- Если эмбеддинги не работают, поиск идёт только по словам, а в шаге `prepare` будет
  «эмбеддинги не работают (…) — поиск только по словам».
- Ключ хранится на сервере в `storage/models.json` (не в git) и наружу не отдаётся.

Модель можно передать в конкретном запросе, не меняя роли: `"roles": {"answer": "qwen7b"}` в `/api/ask`,
`/api/runs` или `/api/ladders`.
