import { computed, onScopeDispose, ref } from 'vue'

import { startRun, listRuns, type RunStart } from '@/api/runs'
import { ApiError } from '@/api/http'
import type { RunMeta } from '@/types'

const RUNNING_EVERY = 2000

/** Состояние общее: опрос один на все экраны, сколько бы раз ни вызвали useRuns(). */
const runs = ref<RunMeta[]>([])
const loading = ref(false)
const error = ref('')
const loadedAt = ref(0)
const startedAt = ref(0)

let timer: number | undefined
let users = 0

const running = computed(() => runs.value.filter((r) => r.status === 'running'))
const finished = computed(() => runs.value.filter((r) => r.status === 'done'))
const offline = computed(() => startedAt.value > 0 && error.value !== '' && runs.value.length === 0)

function reason(e: unknown): string {
  return e instanceof ApiError ? e.message : 'сервер не отвечает'
}

/** Пока хоть один прогон идёт — опрос каждые 2 секунды, иначе обновляемся по требованию. */
function arm() {
  const need = running.value.length > 0
  if (need && timer === undefined) timer = window.setInterval(() => void refresh(), RUNNING_EVERY)
  if (!need && timer !== undefined) {
    clearInterval(timer)
    timer = undefined
  }
}

async function refresh(): Promise<void> {
  loading.value = true
  try {
    runs.value = await listRuns()
    error.value = ''
    loadedAt.value = Date.now()
  } catch (e) {
    error.value = reason(e)
  } finally {
    loading.value = false
    arm()
  }
}

/** Прогон стартует фоном (202) — сразу возвращаем id, прогресс придёт с опросом. */
async function start(body: RunStart): Promise<string> {
  const { run_id } = await startRun(body)
  await refresh()
  return run_id
}

const onVisible = () => {
  if (!document.hidden) void refresh()
}

function subscribe() {
  users += 1
  if (users === 1) {
    document.addEventListener('visibilitychange', onVisible)
    startedAt.value = Date.now()
    void refresh()
  }
}

function unsubscribe() {
  users -= 1
  if (users > 0) return
  if (timer !== undefined) {
    clearInterval(timer)
    timer = undefined
  }
  document.removeEventListener('visibilitychange', onVisible)
}

export function useRuns() {
  subscribe()
  onScopeDispose(unsubscribe)

  return {
    runs,
    running,
    finished,
    offline,
    loading,
    error,
    loadedAt,
    refresh,
    start,
    byId: (id: string) => runs.value.find((r) => r.run_id === id) ?? null,
  }
}
