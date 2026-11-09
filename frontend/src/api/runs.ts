import { apiUrl, getJson, postJson } from './http'
import type { Answer, CompareResult, Insights, RunMeta } from '@/types'

/** Строка result.csv от check.py — колонки описаны у бэкенда, берём как есть. */
export type VerdictRow = Record<string, string>

export interface RunItem extends Answer {
  verdict?: VerdictRow | null
}

export interface RunDetail {
  meta: RunMeta
  items: RunItem[]
}

export interface RunStart {
  dataset: string
  pipeline?: string
  label?: string
  guard?: boolean
  roles?: Record<string, string>
  options?: Record<string, unknown>
}

export const listRuns = () => getJson<RunMeta[]>('/runs')

export const getRun = (runId: string) => getJson<RunDetail>(`/runs/${encodeURIComponent(runId)}`)

/** 202 + run_id: прогон идёт фоном, прогресс смотри в meta.progress. */
export const startRun = (body: RunStart) => postJson<{ run_id: string }>('/runs', body)

export const compareRuns = (before: string, after: string) =>
  getJson<CompareResult>(`/runs/compare/${encodeURIComponent(before)}/${encodeURIComponent(after)}`)

/** Разбор пойманных обманов — экран «как система поймала обман». */
export const caughtRun = (runId: string) => getJson<unknown>(`/runs/${encodeURIComponent(runId)}/caught`)

/** GET /api/runs/{id}/insights — что заметили проверки кода: сводка, срабатывания, лента вопросов. */
export const runInsights = (runId: string) => getJson<Insights>(`/runs/${encodeURIComponent(runId)}/insights`)

/** Дозапуск: недостающие и упавшие вопросы, остальное остаётся как было. 202 — прогресс в meta. */
export const resumeRun = (runId: string) =>
  postJson<{ run_id: string }>(`/runs/${encodeURIComponent(runId)}/resume`, {})

export const answersCsvUrl = (runId: string) => apiUrl(`/runs/${encodeURIComponent(runId)}/answers.csv`)
