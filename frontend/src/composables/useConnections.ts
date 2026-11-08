import { computed, reactive, ref, watch } from 'vue'

export type ConnKind = 'embed' | 'rerank' | 'llm'

export interface LlmParams {
  /** ModelProfile.temperature — для замера «было/стало» держим 0. */
  temperature: number
  /** Пока только в .env (MAX_CONCURRENCY); просим backend принять options.concurrency в POST /api/runs. */
  concurrency: number
  /** Сколько токенов влезает в один запрос. У ModelProfile такого поля ещё нет. */
  contextWindow: number
}

export interface Connection {
  kind: ConnKind
  label: string
  hint: string
  baseUrl: string
  apiKey: string
  status: 'ok' | 'none' | 'error'
  checked?: { ok: boolean; message: string }
  /** Параметры есть у всех, но показываем мы их только у LLM. */
  params: LlmParams
}

const KEY = 'onsoft.connections'

const DEFAULT_LLM_PARAMS: LlmParams = { temperature: 0, concurrency: 4, contextWindow: 32768 }

const DEFAULTS: Connection[] = [
  {
    kind: 'llm',
    label: 'LLM',
    hint: 'Отвечает на вопрос и перепроверяет себя. Роли answer и critic.',
    baseUrl: 'https://api.example.com/v1',
    apiKey: 'sk-1f4a9c77b2e04d3f',
    status: 'ok',
    params: { ...DEFAULT_LLM_PARAMS },
  },
  {
    kind: 'embed',
    label: 'Embedding',
    hint: 'Ищет нужный кусок документа, а не отдаёт модели всё сразу.',
    baseUrl: 'https://api.example.com/v1',
    apiKey: 'sk-1f4a9c77b2e04d3f',
    status: 'ok',
    params: { ...DEFAULT_LLM_PARAMS },
  },
  {
    kind: 'rerank',
    label: 'Reranker',
    hint: 'Досортичивает найденные фрагменты: наверх поднимает то, где есть ответ.',
    baseUrl: '',
    apiKey: '',
    status: 'none',
    params: { ...DEFAULT_LLM_PARAMS },
  },
]

function load(): Connection[] {
  let stored: Connection[] = []
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) stored = JSON.parse(raw) as Connection[]
  } catch {
    /* повреждённое хранилище — начинаем с чистого */
  }
  return DEFAULTS.map((d) => {
    const saved = stored.find((s) => s.kind === d.kind)
    if (!saved) return { ...d, params: { ...d.params } }
    return { ...d, ...saved, params: { ...d.params, ...saved.params } }
  })
}

const items = reactive<Connection[]>(load())

watch(items, () => localStorage.setItem(KEY, JSON.stringify(items)), { deep: true })

/**
 * Временная заглушка: ключи и параметры лежат в браузере.
 * С бэкендом: baseUrl/apiKey/temperature → POST/PATCH /api/models/{id},
 * роли → PUT /api/models/roles, ключ наружу не отдаётся.
 */
export function useConnections() {
  const anyMissing = computed(() => items.some((c) => c.status === 'none'))
  const testing = ref<ConnKind | null>(null)

  async function test(kind: ConnKind): Promise<void> {
    const c = items.find((x) => x.kind === kind)
    if (!c) return
    testing.value = kind
    c.status = 'none'
    c.checked = undefined
    await new Promise((r) => setTimeout(r, 900))
    const ok = /^https?:\/\/.+/.test(c.baseUrl) && c.apiKey.trim().length > 8
    c.status = ok ? 'ok' : 'error'
    c.checked = ok
      ? { ok: true, message: 'соединение есть · 0.4 с' }
      : { ok: false, message: 'не удалось подключиться: проверьте base URL и ключ' }
    testing.value = null
  }

  return { items, anyMissing, testing, test }
}
