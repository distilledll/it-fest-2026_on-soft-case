import type { RunMeta } from '@/types'
import saved from './release-benchmark.json'

// Агрегаты двух завершённых прогонов публичного набора от 8 ноября.
export const releaseBefore = saved.before as RunMeta
export const releaseAfter = saved.after as RunMeta

const SHORT: Record<string, string> = {
  'факт': 'факт',
  'расчёт': 'расчёт',
  'после изменений': 'после изм.',
  'ловушка: нет в документах': 'нет в док.',
  'ловушка: требования нет': 'треб. нет',
  'расхождение': 'расхождение',
}

export function shortType(type: string): string {
  return SHORT[type] ?? type
}
