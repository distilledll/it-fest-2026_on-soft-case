import { getJson } from './http'
import type { Strategy } from '@/types'

/** GET /api/strategies — режимы чтения закупки для переключателя (auto | map | full). */
export const listStrategies = () => getJson<Strategy[]>('/strategies')
