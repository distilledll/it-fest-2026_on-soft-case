"""Схемы ответов API — по ним Swagger (/docs) показывает форму ответов, а фронт генерирует типы
из /openapi.json (например, openapi-typescript).

extra="allow": если бэк добавит поле, старый фронт не сломается, а новое поле не потеряется.
"""
from pydantic import BaseModel, ConfigDict, Field

from app.schemas import Answer, TraceStep


class Out(BaseModel):
    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------- health

class PipelineInfo(Out):
    name: str = Field(examples=["agent"])
    title: str = Field(examples=["LangGraph: retrieve → ответ → критики → исправление"])
    available: bool


class HealthOut(Out):
    ok: bool
    default_pipeline: str = Field(examples=["agent"])
    pipelines: list[PipelineInfo]
    roles: dict[str, str | None] = Field(description="роль → модель", examples=[{"answer": "cifra48/llm"}])


# ---------------------------------------------------------------- datasets

class DocumentMeta(Out):
    package: str = Field(examples=["P01"])
    file: str = Field(examples=["01_izveshchenie.txt"])
    encoding: str = Field(examples=["utf-8-sig"], description="utf-8-sig | cp1251 | utf-8-replace")
    is_empty: bool
    warnings: list[str] = Field(examples=[["подозрение на инструкцию для ИИ внутри документа"]])


class DatasetInfo(Out):
    id: str = Field(examples=["sample"], description="'sample' — пример организатора, иначе id загрузки")
    name: str = Field(examples=["Пример организатора"])
    created_at: str | None = None
    packages: list[str] = Field(examples=[["P01", "P02"]])
    has_questions: bool = Field(description="есть questions.csv — можно запускать прогоны")
    has_gold: bool = Field(description="есть answers_public.json — прогоны оцениваются check.py")
    checker: str = Field("эталонный (backend/eval/check.py)",
                         description="установленный оценщик организатора")


class DatasetDetail(DatasetInfo):
    files: dict[str, list[DocumentMeta]] = Field(description="закупка → файлы")


# ---------------------------------------------------------------- models

class ModelProfileOut(Out):
    id: str
    name: str
    base_url: str
    model: str
    api_key_env: str = ""
    extra_headers: str = ""
    temperature: float = 0.0
    max_tokens: int | None = None
    concurrency: int = 5
    context_window: int | None = None
    context_tokens: int | None = Field(None, description="окно контекста модели в токенах; не задано — "
                                                         "закупка до 60000 символов читается целиком")
    disable_thinking: bool = Field(True, description="выключить рассуждения (по умолчанию да)")
    json_mode: bool = True
    reasoning_effort: str | None = None
    extra_body: dict = {}
    agent_options: dict = Field(default_factory=dict, description="опции агента по умолчанию, напр. {\"strategy\": \"map\"}")
    kind: str = Field("chat", description="chat — роли answer/critic; embedding — роль embed")
    embed_query_task: str | None = Field(None, description="только embedding: поле task для вопроса (нестандартное)")
    embed_passage_task: str | None = Field(None, description="только embedding: поле task для фрагментов документов")
    embed_dimensions: int | None = Field(None, description="только embedding: размерность векторов (если API умеет)")
    has_key: bool = Field(description="ключ задан (сам ключ API никогда не отдаёт)")


class ModelsOut(Out):
    profiles: list[ModelProfileOut]
    roles: dict[str, str] = Field(description="роль → id профиля", examples=[{"answer": "llm", "embed": "embedding"}])
    role_names: list[str] = Field(examples=[["answer", "critic", "embed", "rerank"]])


class ModelTestOut(Out):
    ok: bool
    reply: str | None = None
    dimensions: int | None = Field(None, description="для embedding: размерность полученного вектора")
    latency_s: float | None = None
    error: str | None = None


# ---------------------------------------------------------------- runs

class ByType(Out):
    верно: int = 0
    осторожно: int = 0
    обман: int = 0


class Score(Out):
    n: int | None = None
    correct: int | None = None
    careful: int | None = Field(None, description="«не знаю» — 0 баллов")
    lies: int | None = Field(None, description="обманы — минус балл")
    index: float | None = Field(None, description="индекс доверия = (верно − обман) / всего × 100")
    by_type: dict[str, ByType] = Field(default_factory=dict, description="тип вопроса → вердикты")
    checker: str | None = Field(None, description="установленный оценщик организатора")
    error: str | None = None


class Progress(Out):
    done: int
    total: int
    status: str


class ModelUsed(Out):
    profile: str
    model: str
    temperature: float | None = None


class LadderRef(Out):
    id: str
    step: str = Field(examples=["critics"])
    title: str
    order: int


class RunMeta(Out):
    run_id: str = Field(examples=["1108-122833-6f51"])
    label: str = ""
    dataset: str
    dataset_name: str | None = None
    pipeline: str = Field(examples=["agent"])
    guard: bool
    models: dict[str, ModelUsed] = Field(default_factory=dict, description="роль → модель, на которой шёл прогон")
    options: dict = Field(default_factory=dict)
    status: str = Field(description="running | done | failed | interrupted")
    created_at: str | None = None
    n: int | None = None
    llm_calls: int | None = None
    elapsed_s: float | None = None
    statuses: dict[str, int] | None = Field(None, description="сколько ответов каждого статуса")
    score: Score | None = Field(None, description="есть, если у датасета есть эталон")
    progress: Progress | None = Field(None, description="пока прогон идёт")
    llm_concurrency: int | None = None
    ladder: LadderRef | None = None
    failed: int | None = Field(None, description="вопросов с техническим сбоем (сеть, тайм-аут) — дозапуск через /resume")
    resumed: int | None = None
    error: str | None = None


class Verdict(Out):
    id: str
    type: str = Field(examples=["ловушка: нет в документах"])
    verdict: str = Field(description="верно | осторожно | обман")
    why: str = ""


class RunItem(Answer):
    model_config = ConfigDict(extra="allow")
    verdict: Verdict | None = Field(None, description="вердикт check.py (если есть эталон)")


class RunDetail(Out):
    meta: RunMeta
    items: list[RunItem]


class RunStarted(Out):
    run_id: str


class AnswerFields(Out):
    status: str | None = None
    answer: str | None = None
    quote: str | None = None
    file: str | None = None


class CaughtRow(Out):
    id: str
    type: str
    question: str
    draft: AnswerFields = Field(description="первый черновик модели — до проверок")
    draft_verdict: str = Field(description="вердикт check.py для черновика")
    draft_why: str = ""
    final: AnswerFields = Field(description="итоговый ответ системы")
    final_verdict: str
    critics: list[str] = Field(description="какие проверки сработали", examples=[["conflict", "llm_critic"]])
    steps: list[TraceStep] = Field(description="шаги, где проверка не прошла, повторы и итог")


class CriticStats(Out):
    fired: int = 0
    caught: int = 0
    false_alarm: int = 0


class CaughtOut(Out):
    run_id: str
    label: str | None = None
    has_gold: bool
    caught: list[CaughtRow] = Field(description="черновик был обманом, итог — нет")
    false_alarms: list[CaughtRow] = Field(description="черновик был верным, итог — нет")
    per_critic: dict[str, CriticStats]


class ChangedRow(Out):
    id: str
    type: str
    before: str
    after: str
    why_before: str = ""
    why_after: str = ""


class CompareOut(Out):
    before: RunMeta
    after: RunMeta
    changed: list[ChangedRow] = Field(description="вопросы, где вердикт изменился")


# ---------------------------------------------------------------- ladders

class LadderStepDef(Out):
    step: str
    title: str
    pipeline: str
    options: dict
    guard: bool


class LadderStep(Out):
    step: str = Field(examples=["baseline"], description="baseline | prompt | critics | full")
    title: str = Field(examples=["Baseline «как есть»"])
    order: int
    run_id: str
    status: str
    index: float | None = None
    correct: int | None = None
    careful: int | None = None
    lies: int | None = None
    n: int | None = None
    by_type: dict[str, ByType] = Field(default_factory=dict)
    llm_calls: int | None = None
    elapsed_s: float | None = None
    per_critic: dict[str, CriticStats] | None = Field(None, description="только в /api/ladders/{id}")
    caught: list[CaughtRow] | None = None
    false_alarms: list[CaughtRow] | None = None


class LadderOut(Out):
    id: str
    dataset: str
    dataset_name: str | None = None
    models: dict[str, ModelUsed] | None = None
    steps: list[LadderStep]


class LadderStarted(Out):
    ladder_id: str
