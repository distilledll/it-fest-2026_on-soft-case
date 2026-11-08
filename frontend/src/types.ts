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
  trace: TraceStep[]
  llm_calls: number
  elapsed_s: number
}

export interface Score {
  n: number
  correct: number
  careful: number
  lies: number
  index: number
}

export interface RunMeta {
  run_id: string
  label: string
  dataset: string
  pipeline: string
  guard: boolean
  status: 'running' | 'done' | 'failed' | 'interrupted'
  created_at: string
  n?: number
  llm_calls?: number
  elapsed_s?: number
  statuses?: Record<Status, number>
  score?: Score
  progress?: { done: number; total: number; status: string }
}

export interface TypeBreakdown {
  /** тип вопроса -> вердикт -> количество */
  [type: string]: Record<Verdict, number>
}

export interface ModelProfilePublic {
  id: string
  name: string
  base_url: string
  model: string
  has_key: boolean
  api_key_env?: string
  temperature?: number
}
