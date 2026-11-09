import { getJson, postJson } from './http'
import type { Ladder } from '@/types'

/**GET /api/ladders — лесенки с шагами по порядку (шаги уже отсортированы). */
export const listLadders = () => getJson<Ladder[]>('/ladders')

export const getLadder = (ladderId: string) => getJson<Ladder>(`/ladders/${encodeURIComponent(ladderId)}`)

export interface LadderStart {
  dataset: string
  /** Переопределение моделей по ролям; пусто — берём реестр с настроек. */
  roles?: Record<string, string>
  /** Шаги лесенки; пусто — все четыре слоя. Для «было → стало» хватает ['baseline', 'full']. */
  steps?: string[]
}

/** POST /api/ladders — 202 + ladder_id; шаги идут по очереди, прогресс смотри в listLadders(). */
export const startLadder = (body: LadderStart) => postJson<{ ladder_id: string }>('/ladders', body)
