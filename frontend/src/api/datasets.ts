import { deleteRequest, getJson, sendFiles, type SendProgress } from './http'
import type { DatasetDetail, DatasetInfo, QuestionRow } from '@/types'

export const listDatasets = () => getJson<DatasetInfo[]>('/datasets')

export const getDataset = (id: string) =>
  getJson<DatasetDetail>(`/datasets/${encodeURIComponent(id)}`)

export const getQuestions = (id: string) =>
  getJson<QuestionRow[]>(`/datasets/${encodeURIComponent(id)}/questions`)

export const deleteDataset = (id: string) => deleteRequest(`/datasets/${encodeURIComponent(id)}`)

/** Ответ из POST /api/datasets/{id}/gold — сколько вопросов укрыл эталон и какие прогоны пересчитаны. */
export interface GoldResult {
  dataset: DatasetInfo
  gold: number
  questions: number
  missing: string[]
  rescored: { run_id: string; label: string; pipeline?: string | null; score?: { index?: number | null } | null }[]
}

/** POST /api/datasets/{id}/gold — answers_public.json к набору без эталона; прогоны пересчитываются сами. */
export function uploadGold(id: string, file: File): Promise<GoldResult> {
  const form = new FormData()
  form.append('file', file, file.name)
  return sendFiles<GoldResult>(`/datasets/${encodeURIComponent(id)}/gold`, form)
}

export interface UploadOptions {
  files: File[]
  /** Имя датасета в списке; пусто — бэкенд подставит имя архива. */
  name?: string
  /** Код закупки для отдельных .txt: они лягут в packages/<package>. */
  packageCode?: string
  onProgress?: (p: SendProgress) => void
  signal?: AbortSignal
}

/** POST /api/datasets — один .zip (формат организатора) или несколько .txt одной закупки. */
export function uploadDataset({
  files,
  name = '',
  packageCode = 'P01',
  onProgress,
  signal,
}: UploadOptions): Promise<DatasetInfo> {
  const form = new FormData()
  // Имя поля — ровно files, его ждёт FastAPI (list[UploadFile]).
  for (const f of files) form.append('files', f, f.name)
  form.append('name', name)
  form.append('package', packageCode)
  return sendFiles<DatasetInfo>('/datasets', form, onProgress, signal)
}

export const countDocuments = (d: DatasetDetail): number =>
  Object.values(d.files).reduce((sum, list) => sum + list.length, 0)
