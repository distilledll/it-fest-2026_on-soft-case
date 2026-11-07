import type { Status, Verdict } from '@/types'

export const statusMeta: Record<Status, { label: string; cls: string }> = {
  'ответ': { label: 'ответ', cls: 'badge--accent' },
  'расхождение': { label: 'расхождение', cls: 'badge--warn' },
  'нет в документах': { label: 'нет в документах', cls: 'badge--info' },
  'не знаю': { label: 'не знаю', cls: '' },
}

export const verdictMeta: Record<Verdict, { label: string; cls: string }> = {
  'верно': { label: 'верно', cls: 'badge--ok' },
  осторожно: { label: 'осторожно', cls: 'badge--warn' },
  обман: { label: 'обман', cls: 'badge--bad' },
}

export function signed(n: number): string {
  return n > 0 ? `+${n}` : `${n}`
}

export function formatIndex(n: number): string {
  return Number.isInteger(n) ? `${n}` : n.toFixed(1)
}
