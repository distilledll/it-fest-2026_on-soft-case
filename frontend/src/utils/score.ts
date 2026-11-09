import type { TypeBreakdown, Verdict } from '@/types'

/** Арифметика индекса доверия: (верно − обман) / всех вопросов × 100. */

const round = (v: number) => Math.round(v * 10) / 10

export function sumVerdicts(b: TypeBreakdown): Record<Verdict, number> {
  return Object.values(b).reduce(
    (acc, row) => {
      acc.верно += row.верно ?? 0
      acc.осторожно += row.осторожно ?? 0
      acc.обман += row.обман ?? 0
      return acc
    },
    { верно: 0, осторожно: 0, обман: 0 } as Record<Verdict, number>,
  )
}

export function indexOfRow(row?: Partial<Record<Verdict, number>>): number {
  if (!row) return 0
  const верно = row.верно ?? 0
  const осторожно = row.осторожно ?? 0
  const обман = row.обман ?? 0
  const n = верно + осторожно + обман
  return n ? round(((верно - обман) / n) * 100) : 0
}

export const indexOfType = (b: TypeBreakdown, type: string): number => indexOfRow(b[type])

export const shareOf = (part: number, all: number): number => (all ? Math.round((part / all) * 100) : 0)

export const sumOf = (v: Record<Verdict, number>): number => v.верно + v.осторожно + v.обман
