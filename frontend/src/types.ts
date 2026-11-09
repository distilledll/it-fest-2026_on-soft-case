/** Типы, выровненные с контрактом бэкенда (backend/app/schemas.py) — держать синхронно. */

export type IconName =
  | 'help'
  | 'settings'
  | 'sun'
  | 'moon'
  | 'message'
  | 'upload'
  | 'download'
  | 'plug'
  | 'eye'
  | 'eye-off'
  | 'chevron'
  | 'check'
  | 'close'
  | 'arrow-right'
  | 'file'
  | 'shield'
  | 'alert'
  | 'activity'
  | 'log-out'
  | 'lock'
  | 'user'
  | 'refresh'
  | 'plus'

export type Status = 'ответ' | 'расхождение' | 'нет в документах' | 'не знаю'
export type Verdict = 'верно' | 'осторожно' | 'обман'

export interface TraceStep {
  node: string
  ok: boolean | null
  message: string
  data: Record<string, unknown>
}

export interface Answer {
  id: string
  status: Status
  answer: string
  quote: string
  file: string
  evidence?: { file: string; quote: string; value: string }[]
  trace: TraceStep[]
  llm_calls: number
  elapsed_s: number
}

export type Score = {
  n: number
  correct: number
  careful: number
  lies: number
  index: number
}

/**
 * meta.score как его отдаёт бэкенд: результат check.py плюс by_type.
 * Поля check.py нам не обещаны контрактом, поэтому тип терпеливый: читаем только то, что есть.
 */
export type RunScore = {
  index?: number
  by_type?: TypeBreakdown
  error?: string
  [key: string]: unknown
}

export interface RunModelRef {
  profile: string
  model: string
  temperature: number
}

export interface RunMeta {
  run_id: string
  label: string
  dataset: string
  dataset_name?: string
  pipeline: string
  guard: boolean
  status: 'running' | 'done' | 'failed' | 'interrupted'
  created_at: string
  n?: number
  llm_calls?: number
  elapsed_s?: number
  statuses?: Record<Status, number>
  score?: RunScore
  progress?: { done: number; total: number; status: string }
  models?: Record<string, RunModelRef>
  options?: Record<string, unknown>
  error?: string
}

/** GET /api/runs/compare/{before}/{after} */
export interface ChangedQuestion {
  id: string
  type: string
  before: string
  after: string
  why_before: string
  why_after: string
}

export interface CompareResult {
  before: RunMeta
  after: RunMeta
  changed: ChangedQuestion[]
}

export interface TypeBreakdown {
  /** тип вопроса -> вердикт -> количество */
  [type: string]: Record<Verdict, number>
}

/** Профиль модели как его отдаёт GET /api/models — ключа там нет, только has_key. */
export interface ModelProfilePublic {
  id: string
  name: string
  base_url: string
  model: string
  api_key_env: string
  extra_headers: string
  temperature: number
  max_tokens: number | null
  concurrency: number
  context_window: number | null
  disable_thinking: boolean
  json_mode: boolean
  reasoning_effort: string | null
  extra_body: Record<string, unknown>
  agent_options?: Record<string, unknown>
  /** chat — отвечает/проверяет (answer, critic); embedding — векторы для поиска (embed). */
  kind?: 'chat' | 'embedding'
  /** только embedding: нестандартные поля запроса /embeddings (шлюз понимает, OpenAI — нет). */
  embed_query_task?: string | null
  embed_passage_task?: string | null
  embed_dimensions?: number | null
  has_key: boolean
}

/** Роли, на которые назначают профили (backend/app/llm.py: ROLES). */
export type RoleName = 'answer' | 'critic' | 'embed' | 'rerank'

export type RoleMap = Partial<Record<RoleName, string>>

export interface ModelsRegistry {
  profiles: ModelProfilePublic[]
  roles: RoleMap
  role_names: RoleName[]
}

/** Что можно менять PATCH-ом (backend ProfilePatch). */
export type ProfilePatch = Partial<{
  name: string
  base_url: string
  model: string
  api_key: string
  api_key_env: string
  extra_headers: string
  temperature: number
  max_tokens: number | null
  concurrency: number
  context_window: number
  disable_thinking: boolean
  json_mode: boolean
  /** '' — выключить; backend ждёт low|medium|high. */
  reasoning_effort: string
  extra_body: Record<string, unknown>
  kind: 'chat' | 'embedding'
  embed_query_task: string | null
  embed_passage_task: string | null
  embed_dimensions: number | null
}>

export type ProfileCreate = ProfilePatch & { name: string; base_url: string; model: string }

export type ProfileTest =
  | { ok: true; reply: string; latency_s: number; dimensions?: number }
  | { ok: false; error: string }

/** GET /api/health */
export interface PipelineInfo {
  name: string
  title: string
  available: boolean
}

export interface HealthInfo {
  ok: boolean
  default_pipeline: string
  pipelines: PipelineInfo[]
  roles: Record<string, string | null>
}

/** GET|POST /api/datasets — answer модели datasets.info() */
export interface DatasetInfo {
  id: string
  name: string
  created_at?: string
  packages: string[]
  has_questions: boolean
  has_gold: boolean
}

/** Документ без тела текста — как его отдаёт GET /api/datasets/{id} */
export interface DatasetFile {
  package: string
  file: string
  encoding: string
  is_empty: boolean
  warnings: string[]
}

export interface DatasetDetail extends DatasetInfo {
  /** закупка -> документы */
  files: Record<string, DatasetFile[]>
}

/** Строка questions.csv */
export interface QuestionRow {
  id: string
  package: string
  question: string
}
