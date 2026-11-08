import { getJson } from './http'
import type { HealthInfo } from '@/types'

/** Жив ли бэкенд и какие пайплайны умеет. */
export const getHealth = () => getJson<HealthInfo>('/health')
