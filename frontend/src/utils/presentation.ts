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

/** Русская множественность: plural(2, ['файл', 'файла', 'файлов']) -> «2 файла». */
export function plural(n: number, forms: [string, string, string]): string {
  const ten = n % 10
  const hundred = n % 100
  const word =
    ten === 1 && hundred !== 11 ? forms[0] : ten >= 2 && ten <= 4 && (hundred < 12 || hundred > 14) ? forms[1] : forms[2]
  return `${n} ${word}`
}

export function shortTime(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

/** «только что» / «12 секунд назад» / «3 минуты назад». */
export function agoLabel(ms: number): string {
  if (ms < 2000) return 'только что'
  const s = Math.round(ms / 1000)
  if (s < 60) return plural(s, ['секунду назад', 'секунды назад', 'секунд назад'])
  return plural(Math.round(s / 60), ['минуту назад', 'минуты назад', 'минут назад'])
}
