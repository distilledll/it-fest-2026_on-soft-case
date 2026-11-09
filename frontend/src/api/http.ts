/**
 * Единая точка выхода к бэкенду.
 * В девёлке путь идёт через прокси Vite (/api -> 127.0.0.1:8000), в проде — тот же origin.
 */
const BASE = import.meta.env.VITE_API_BASE ?? ''

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

/** Отмена: ApiError с status === 0 — его нельзя показывать пользователю как поломку. */
export const isCanceled = (e: unknown): boolean => e instanceof ApiError && e.status === 0

export function apiUrl(path: string): string {
  return `${BASE}/api${path}`
}

/** Бэкенд отвечает текстом ошибки в { detail } — оттуда и берём подпись. */
async function errorText(res: Response): Promise<string> {
  let body: unknown
  try {
    body = await res.json()
  } catch {
    return res.status ? `сервер ответил ${res.status}` : 'сервер не отвечает'
  }
  const detail = (body as { detail?: unknown })?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d) => (d as { msg?: string }).msg ?? String(d)).join('; ')
  return res.statusText || `сервер ответил ${res.status}`
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  let res: Response
  try {
    res = await fetch(apiUrl(path), { signal })
  } catch (e) {
    if (isCanceled(e) || (e as Error)?.name === 'AbortError') throw new ApiError(0, 'запрос отменён')
    throw new ApiError(0, 'сервер не отвечает')
  }
  if (!res.ok) throw new ApiError(res.status, await errorText(res))
  return (await res.json()) as T
}

async function sendJson<T>(method: string, path: string, payload?: unknown, signal?: AbortSignal): Promise<T> {
  let res: Response
  try {
    res = await fetch(apiUrl(path), {
      method,
      headers: payload === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: payload === undefined ? undefined : JSON.stringify(payload),
      signal,
    })
  } catch (e) {
    if (isCanceled(e) || (e as Error)?.name === 'AbortError') throw new ApiError(0, 'запрос отменён')
    throw new ApiError(0, 'сервер не отвечает')
  }
  if (!res.ok) throw new ApiError(res.status, await errorText(res))
  return (await res.json()) as T
}

export const postJson = <T>(path: string, payload?: unknown, signal?: AbortSignal) =>
  sendJson<T>('POST', path, payload, signal)

export const putJson = <T>(path: string, payload: unknown) => sendJson<T>('PUT', path, payload)

export const patchJson = <T>(path: string, payload: unknown) => sendJson<T>('PATCH', path, payload)

export async function deleteRequest(path: string): Promise<void> {
  const res = await fetch(apiUrl(path), { method: 'DELETE' })
  if (!res.ok && res.status !== 204) throw new ApiError(res.status, await errorText(res))
}

export interface SendProgress {
  /** Сколько байм ушло на сервер. */
  sent: number
  total: number
  /** Тело ушло целиком — дальше сервер распаковывает и проверяет. */
  sent_all: boolean
}

/**
 * POST multipart с честным прогрессом: fetch отдачу файла не считает, поэтому XHR.
 * signal — для кнопки «Отменить».
 */
export function sendFiles<T>(
  path: string,
  form: FormData,
  onProgress?: (p: SendProgress) => void,
  signal?: AbortSignal,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', apiUrl(path))
    xhr.responseType = 'text'

    const onAbort = () => xhr.abort()
    signal?.addEventListener('abort', onAbort)

    xhr.upload.onprogress = (e) => {
      const total = e.total || 0
      onProgress?.({ sent: e.loaded, total, sent_all: total > 0 && e.loaded >= total })
    }

    xhr.onload = () => {
      signal?.removeEventListener('abort', onAbort)
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve((xhr.response ? JSON.parse(xhr.response) : null) as T)
        } catch {
          reject(new ApiError(xhr.status, 'сервер вернул непонятный ответ'))
        }
        return
      }
      let body: unknown
      try {
        body = xhr.response ? JSON.parse(xhr.response) : null
      } catch {
        body = null
      }
      const detail = (body as { detail?: unknown } | null)?.detail
      const fallback =
        xhr.status === 413
          ? 'файл больше разрешённого размера'
          : xhr.status
            ? `сервер ответил ${xhr.status}`
            : 'сервер не отвечает'
      reject(new ApiError(xhr.status, typeof detail === 'string' ? detail : fallback))
    }

    xhr.onerror = () => {
      signal?.removeEventListener('abort', onAbort)
      reject(new ApiError(0, 'сервер не отвечает'))
    }

    xhr.onabort = () => {
      signal?.removeEventListener('abort', onAbort)
      reject(new ApiError(0, 'загрузка отменена'))
    }

    xhr.send(form)
  })
}
