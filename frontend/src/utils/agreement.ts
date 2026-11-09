import type { Status, TypeBreakdown, Verdict } from '@/types'

/** Минимально нужное из ответа прогона: сверяем статус и текст. */
export interface ComparedAnswer {
  id: string
  status: Status
  answer: string
}

export interface Agreement {
  /** Вопросов, ответленных в обоих прогонах. */
  n: number
  /** Закупка -> вердикт -> количество: «было» относительно «стало». */
  before: TypeBreakdown
  /** «Стало» принято верным по определению — все ответы «верно». */
  after: TypeBreakdown
}

const norm = (s: string): string =>
  s
    .toLowerCase()
    .replace(/ё/g, 'е')
    .replace(/[\s]+/g, ' ')
    .replace(/[.,;:«»"”(){}\[\]/–—-]/g, '')
    .trim()

const digits = (s: string): string => (s.match(/\d+(?:[.,]\d+)*/g) ?? []).map((d) => d.replace(/[.,]/g, '')).join('|')

/** Совпадение ответов: текст в норме, либо одинаковые числовые последовательности. */
function sameAnswer(a: string, b: string): boolean {
  if (!a.trim() || !b.trim()) return a.trim() === b.trim()
  const [na, nb] = [norm(a), norm(b)]
  if (na === nb) return true
  const [da, db] = [digits(a), digits(b)]
  if (da && db) return da === db
  if (na.length >= 4 && nb.length >= 4) return na.includes(nb) || nb.includes(na)
  return false
}

const ASSERTED: Status = 'ответ'

/** Вердикт черновика, где истина — ответ системы («стало»). */
function verdictOf(before: ComparedAnswer, after: ComparedAnswer): Verdict {
  if (before.status === after.status) {
    return before.status === ASSERTED ? (sameAnswer(before.answer, after.answer) ? 'верно' : 'обман') : 'верно'
  }
  if (before.status === ASSERTED) return 'обман'
  return 'осторожно'
}

/** Разметка «было» относительно «стало» без эталона: по закупкам, система = 100. */
export function buildAgreement(
  questions: { id: string; package: string }[],
  beforeItems: ComparedAnswer[],
  afterItems: ComparedAnswer[],
): Agreement {
  const beforeMap = new Map(beforeItems.map((i) => [i.id, i]))
  const afterMap = new Map(afterItems.map((i) => [i.id, i]))
  const before: TypeBreakdown = {}
  const after: TypeBreakdown = {}
  const bump = (bd: TypeBreakdown, pack: string, verdict: Verdict) => {
    const row = (bd[pack] ??= { верно: 0, осторожно: 0, обман: 0 } as Record<Verdict, number>)
    row[verdict] += 1
  }
  let n = 0
  for (const q of questions) {
    const b = beforeMap.get(q.id)
    const a = afterMap.get(q.id)
    if (!b || !a) continue
    const pack = q.package || q.id.split('-')[0] || '—'
    n += 1
    bump(after, pack, 'верно')
    bump(before, pack, verdictOf(b, a))
  }
  return { n, before, after }
}
