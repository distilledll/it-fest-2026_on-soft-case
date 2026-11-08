/** Моки для вёрстки: те же формы, что отдаёт бэкенд. Позже заменяется на fetch. */

import type { Answer, RunMeta, Score, TraceStep, TypeBreakdown, Verdict } from '@/types'

export const QUESTION_TYPES = [
  'факт',
  'расчёт',
  'после изменений',
  'ловушка: нет в документах',
  'ловушка: требования нет',
  'расхождение',
] as const

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

const BEFORE: TypeBreakdown = {
  'факт': { верно: 30, осторожно: 2, обман: 13 },
  'расчёт': { верно: 3, осторожно: 0, обман: 3 },
  'после изменений': { верно: 1, осторожно: 0, обман: 3 },
  'ловушка: нет в документах': { верно: 2, осторожно: 1, обман: 7 },
  'ловушка: требования нет': { верно: 1, осторожно: 0, обман: 3 },
  'расхождение': { верно: 0, осторожно: 0, обман: 2 },
}

const AFTER: TypeBreakdown = {
  'факт': { верно: 41, осторожно: 3, обман: 1 },
  'расчёт': { верно: 5, осторожно: 1, обман: 0 },
  'после изменений': { верно: 3, осторожно: 1, обман: 0 },
  'ловушка: нет в документах': { верно: 7, осторожно: 3, обман: 0 },
  'ловушка: требования нет': { верно: 3, осторожно: 1, обман: 0 },
  'расхождение': { верно: 2, осторожно: 0, обман: 0 },
}

export function total(b: TypeBreakdown): Record<Verdict, number> {
  return Object.values(b).reduce(
    (acc, row) => {
      acc.верно += row.верно
      acc.осторожно += row.осторожно
      acc.обман += row.обман
      return acc
    },
    { верно: 0, осторожно: 0, обман: 0 } as Record<Verdict, number>,
  )
}

export function scoreOf(b: TypeBreakdown): Score {
  const t = total(b)
  const n = t.верно + t.осторожно + t.обман
  return { n, correct: t.верно, careful: t.осторожно, lies: t.обман, index: round(((t.верно - t.обман) / n) * 100) }
}

export const mockBefore = { meta: runMeta('before'), breakdown: BEFORE, score: scoreOf(BEFORE) }
export const mockAfter = { meta: runMeta('after'), breakdown: AFTER, score: scoreOf(AFTER) }

function runMeta(kind: 'before' | 'after'): RunMeta {
  const isAfter = kind === 'after'
  return {
    run_id: isAfter ? '1107-142033-a91f' : '1107-115807-4c2b',
    label: isAfter ? 'стало: агент + проверки' : 'было: один запрос',
    dataset: 'sample',
    pipeline: isAfter ? 'agent' : 'baseline',
    guard: isAfter,
    status: 'done',
    created_at: isAfter ? '2026-11-07T14:20:33' : '2026-11-07T11:58:07',
    n: 71,
    llm_calls: isAfter ? 341 : 71,
    elapsed_s: isAfter ? 512.4 : 168.9,
    score: scoreOf(isAfter ? AFTER : BEFORE),
  }
}

/** Индекс доверия по каждому типу вопроса — для линейного графика «было/стало». */
export function indexByType(b: TypeBreakdown): number[] {
  return QUESTION_TYPES.map((type) => {
    const row = b[type]
    if (!row) return 0
    const n = row.верно + row.осторожно + row.обман
    return n ? round(((row.верно - row.обман) / n) * 100) : 0
  })
}

export const mockTrace: TraceStep[] = [
  { node: 'retrieve', ok: true, message: 'найдено 3 релевантных фрагмента', data: { top: '01_izveshchenie.txt' } },
  { node: 'answer', ok: true, message: 'черновик ответа получен', data: {} },
  { node: 'check_quote', ok: false, message: 'цитаты нет в документах', data: {} },
  { node: 'retry', ok: true, message: 'повторный запрос с указанием на ошибку', data: { attempt: 2 } },
  { node: 'check_quote', ok: true, message: 'цитата подтверждена', data: {} },
  { node: 'critic_numbers', ok: true, message: 'число из ответа есть в цитате', data: {} },
]

export const mockAnswer: Answer = {
  id: 'adhoc',
  status: 'ответ',
  answer: '18000 руб.',
  quote: 'Обеспечение заявки: 18 000,00 руб.',
  file: '01_izveshchenie.txt',
  trace: mockTrace,
  llm_calls: 3,
  elapsed_s: 7.4,
}

function round(v: number): number {
  return Math.round(v * 10) / 10
}
