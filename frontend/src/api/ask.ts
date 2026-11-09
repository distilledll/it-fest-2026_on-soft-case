import type { Answer, TraceStep } from '@/types'

import { ApiError, apiUrl, isCanceled } from './http'

export interface AskRequest {
  dataset: string
  package: string
  question: string
  pipeline?: string
  guard?: boolean
}

export interface AskHandlers {
  onStep: (step: TraceStep) => void
  onAnswer: (answer: Answer) => void
}

interface SseFrame {
  event: string
  data: string
}

/** SSE-кадры идут «event: …\r\ndata: {…}\r\n\r\n»; комментарии («: heartbeat») пропускаем. */
function drainFrames(buffer: string): [SseFrame[], string] {
  const frames: SseFrame[] = []
  let rest = buffer
  for (;;) {
    const match = /\r?\n\r?\n/.exec(rest)
    if (!match) break
    const raw = rest.slice(0, match.index)
    rest = rest.slice(match.index + match[0].length)
    let event = 'message'
    const data: string[] = []
    for (const line of raw.split(/\r?\n/)) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
    }
    if (data.length) frames.push({ event, data: data.join('\n') })
  }
  return [frames, rest]
}

/**
 * POST /api/ask/stream: ответ приходит частями — сначала шаги `step`, в конце один `answer`.
 * Ошибки до начала потока бэкенд отдаёт обычным JSON (422/404) — поднимаем как ApiError.
 */
export async function askStream(body: AskRequest, handlers: AskHandlers, signal?: AbortSignal): Promise<void> {
  let res: Response
  try {
    res = await fetch(apiUrl('/ask/stream'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    })
  } catch (e) {
    if (isCanceled(e) || (e as Error)?.name === 'AbortError') throw new ApiError(0, 'вопрос отменён')
    throw new ApiError(0, 'сервер не отвечает')
  }
  if (!res.ok) throw new ApiError(res.status, await errorTextOf(res))
  if (!res.body) throw new ApiError(0, 'сервер не отвечает')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const dispatch = (frame: SseFrame): void => {
    let payload: unknown
    try {
      payload = JSON.parse(frame.data)
    } catch {
      return
    }
    if (frame.event === 'step') handlers.onStep(payload as TraceStep)
    else if (frame.event === 'answer') handlers.onAnswer(payload as Answer)
  }
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const [frames, rest] = drainFrames(buffer)
    buffer = rest
    frames.forEach(dispatch)
  }
}

async function errorTextOf(res: Response): Promise<string> {
  try {
    const payload = (await res.json()) as { detail?: unknown }
    const detail = payload.detail
    if (typeof detail === 'string' && detail) return detail
    if (Array.isArray(detail) && detail.length) return String(detail[0])
  } catch {
    /* тело не JSON */
  }
  return res.status ? `сервер ответил ${res.status}` : 'сервер не отвечает'
}
