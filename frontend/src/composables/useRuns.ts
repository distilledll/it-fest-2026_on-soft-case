import { computed, onScopeDispose, ref } from 'vue'

import { startLadder } from '@/api/ladders'
import { resumeRun, startRun, listRuns, type RunStart } from '@/api/runs'
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

/** Пока идёт прогон или лесенка — опрос каждые 2 секунды, иначе обновляемся по требованию. */
function arm(): void {
  settleLadder()
  const need = running.value.length > 0 || ladderId.value !== ''
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

/** Дозапуск упавшего/оборванного прогона: фоновая 202, прогресс придёт с тем же опросом. */
async function resume(runId: string): Promise<void> {
  await resumeRun(runId)
  await refresh()
}

/** Прогон стартует фоном (202) — сразу возвращаем id, прогресс придёт с опросом. */
async function start(body: RunStart): Promise<string> {
  const { run_id } = await startRun(body)
  await refresh()
  return run_id
}

/* ------------------------------------------------- лесенка «было → стало» */

/** Короткая лесенка: «было» (baseline) и «стало» (hybrid — то, что сдаём) — руками пайплайны выбирать не надо. */
export const BOTH_STEPS = ['baseline', 'hybrid'] as const

const ladderId = ref('')
let ladderDeadline = 0

const ladderRuns = computed(() => (ladderId.value ? runs.value.filter((r) => r.ladder?.id === ladderId.value) : []))
const ladderRunning = computed(() => ladderRuns.value.some((r) => r.status === 'running'))
const ladderDoneCount = computed(() => ladderRuns.value.filter((r) => r.status === 'done').length)
const ladderFailedCount = computed(() => ladderRuns.value.filter((r) => r.status === 'failed').length)

/** Забыть лесенку: все шаги в финальном статусе — или ни один так и не родился (сервер не принял). */
function settleLadder(): void {
  if (!ladderId.value) return
  const rs = ladderRuns.value
  const allTerminal = rs.length >= BOTH_STEPS.length && rs.every((r) => r.status !== 'running')
  const neverBorn = rs.length === 0 && Date.now() > ladderDeadline
  if (allTerminal || neverBorn) ladderId.value = ''
}

/** «Было → стало» одним запуском: baseline и hybrid (агент + резервный проход) идут по очереди на одном датасете. */
async function startBoth(dataset: string, strategy = 'auto'): Promise<string> {
  const options = strategy && strategy !== 'auto' ? { strategy } : undefined
  const { ladder_id } = await startLadder({ dataset, steps: [...BOTH_STEPS], options })
  ladderId.value = ladder_id
  ladderDeadline = Date.now() + 30_000
  await refresh()
  return ladder_id
}

function forgetLadder(): void {
  ladderId.value = ''
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
    resume,
    start,
    startBoth,
    forgetLadder,
    ladderId,
    ladderRuns,
    ladderRunning,
    ladderDoneCount,
    ladderFailedCount,
    byId: (id: string) => runs.value.find((r) => r.run_id === id) ?? null,
  }
}
