<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import { listDatasets } from '@/api/datasets'
import { ApiError } from '@/api/http'
import { answersCsvUrl } from '@/api/runs'
import { listStrategies } from '@/api/strategies'
import { getHealth } from '@/api/system'
import { useDataset } from '@/composables/useDataset'
import { useRuns } from '@/composables/useRuns'
import { agoLabel, shortTime } from '@/utils/presentation'
import type { DatasetInfo, HealthInfo, RunMeta, Strategy } from '@/types'

const {
  runs,
  running,
  loading,
  error,
  loadedAt,
  refresh,
  resume,
  start,
  startBoth,
  ladderId,
  ladderRuns,
  ladderRunning,
} = useRuns()
const { active } = useDataset()
const route = useRoute()
const router = useRouter()

const datasets = ref<DatasetInfo[]>([])
const health = ref<HealthInfo | null>(null)
const strategies = ref<Strategy[]>([])
const datasetId = ref('')
const strategy = ref('auto')
const pipeline = ref('')
const label = ref('')
const guard = ref(true)
watch(pipeline, (p) => { guard.value = p !== 'direct' && p !== 'baseline' })
const busy = ref(false)
const bothBusy = ref(false)
const problem = ref('')
const notice = ref('')
const ready = ref(false)
const resuming = ref('')

const now = ref(Date.now())
let tick: number | undefined

const runnable = computed(() => datasets.value.filter((d) => d.has_questions))
const datasetChosen = computed(() => runnable.value.some((d) => d.id === datasetId.value))
const canStartBoth = computed(() => datasetChosen.value && !bothBusy.value && !ladderRunning.value)
const canStart = computed(() => datasetChosen.value && !!pipeline.value && !busy.value)
/** Отдаём strategy в body только когда выбрали нестандартный режим — «авто» и так по умолчанию. */
const runOptions = computed<Record<string, unknown> | undefined>(() =>
  strategy.value && strategy.value !== 'auto' ? { strategy: strategy.value } : undefined,
)
const strategyHint = computed(
  () => strategies.value.find((s) => s.id === strategy.value)?.description ?? '',
)
/** Короткие подписи сегментов; полноe название и описание — в title и подсказке. */
const STRATEGY_SHORT: Record<string, string> = { auto: 'авто', map: 'map-reduce', full: 'без map-reduce' }
const ladderTotal = 2
const ladderPct = computed(() => {
  if (!ladderId.value) return 0
  const settled = ladderRuns.value.filter((r) => r.status !== 'running').length
  return Math.round((Math.min(settled, ladderTotal) / ladderTotal) * 100)
})
/** Два шага лесенки по порядку: «было» (baseline) и «стало» (hybrid — то, что сдаём). */
const LADDER_LABELS: Record<string, string> = {
  baseline: 'Было · один запрос, всё скопом',
  hybrid: 'Стало · агент с проверками и резервным проходом',
}
const ladderSteps = computed(() => {
  const byStep = new Map(ladderRuns.value.map((r) => [r.ladder?.step, r]))
  return (['baseline', 'hybrid'] as const).map((step) => ({
    step,
    title: LADDER_LABELS[step] ?? step,
    run: byStep.get(step) ?? null,
  }))
})
const currentWithoutRuns = computed(
  () =>
    !!active.value &&
    loadedAt.value > 0 &&
    !loading.value &&
    !runs.value.some((r) => r.dataset === active.value?.id),
)

const statusBadge: Record<RunMeta['status'], string> = {
  running: 'badge--accent',
  done: 'badge--ok',
  failed: 'badge--bad',
  interrupted: 'badge--warn',
}

const progressOf = (r: RunMeta) =>
  r.progress && r.progress.total ? Math.round((r.progress.done / r.progress.total) * 100) : 0
const indexOf = (r: RunMeta) => (typeof r.score?.index === 'number' ? r.score.index : null)
/** Дозапуск нужен, если прогон оборвался или часть вопросов упала (шлюз отвалился и т.п.). */
const resumable = (r: RunMeta) =>
  !resuming.value && (r.status === 'interrupted' || r.status === 'failed' || (r.status === 'done' && !!r.failed))

async function onResume(r: RunMeta) {
  problem.value = ''
  resuming.value = r.run_id
  try {
    await resume(r.run_id)
    notice.value = `Дозапускаем ${r.run_id} — долетят только недостающие и упавшие вопросы`
  } catch (e) {
    problem.value = e instanceof ApiError ? e.message : 'не удалось дозапустить прогон'
  } finally {
    resuming.value = ''
  }
}

async function load() {
  try {
    datasets.value = await listDatasets()
  } catch {
    datasets.value = []
  }
  try {
    health.value = await getHealth()
  } catch {
    health.value = null
  }
  try {
    strategies.value = await listStrategies()
  } catch {
    strategies.value = []
  }
  pipeline.value = health.value?.default_pipeline ?? 'baseline'
  datasetId.value =
    active.value && runnable.value.some((d) => d.id === active.value?.id)
      ? active.value.id
      : (runnable.value[0]?.id ?? '')
  ready.value = true
}

async function onStart() {
  problem.value = ''
  notice.value = ''
  busy.value = true
  try {
    const id = await start({
      dataset: datasetId.value,
      pipeline: pipeline.value,
      label: label.value.trim(),
      guard: guard.value,
      options: runOptions.value,
    })
    notice.value = `Прогон ${id} запущен — прогресс ниже`
    label.value = ''
  } catch (e) {
    problem.value = e instanceof ApiError ? e.message : 'не удалось запустить прогон'
  } finally {
    busy.value = false
  }
}

/** Главная кнопка: выбрать только датасет — оба конвейера («было» и «стало») пойдут по очереди. */
async function onStartBoth() {
  problem.value = ''
  notice.value = ''
  bothBusy.value = true
  try {
    await startBoth(datasetId.value, strategy.value)
  } catch (e) {
    problem.value = e instanceof ApiError ? e.message : 'не удалось запустить измерение'
  } finally {
    bothBusy.value = false
  }
}

// Лесенка завершилась (шаги разошлись по статусам) — честно докладываем итог.
watch(ladderId, (id, prev) => {
  if (id || !prev) return
  const failed = runs.value.filter((r) => r.ladder?.id === prev && r.status !== 'done').length
  notice.value = failed
    ? 'Лесенка завершилась с ошибками — статусы прогонов ниже'
    : 'Готово: «было» и «стало» прогнаны — дашборд подхватил пару'
})

const formEl = ref<HTMLDivElement | null>(null)

onMounted(async () => {
  await load()
  const q = route.query
  if (typeof q.dataset === 'string' && runnable.value.some((d) => d.id === q.dataset)) {
    datasetId.value = q.dataset
  }
  if (q.start === '1') {
    await nextTick()
    formEl.value?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    formEl.value?.querySelector<HTMLSelectElement>('select')?.focus({ preventScroll: true })
    const { start: _start, dataset: _ds, pipeline: _pl, ...rest } = route.query
    void router.replace({ query: rest })
  }
  tick = window.setInterval(() => (now.value = Date.now()), 1000)
})

onBeforeUnmount(() => clearInterval(tick))
</script>

<template>
  <section class="card card--pad-lg runs reveal" aria-labelledby="runs-title">
    <div class="runs__head">
      <div>
        <h2 id="runs-title">Прогоны на сервере</h2>
        <p class="muted runs__sub">
          <template v-if="running.length">
            идёт {{ running.length }} — обновляем каждые 2 секунды
          </template>
          <template v-else>список обновлён {{ agoLabel(now - loadedAt) }}</template>
        </p>
      </div>
      <button class="btn btn--ghost btn--sm" type="button" :disabled="loading" @click="refresh()">
        <AppIcon name="refresh" size="sm" />
        Обновить
      </button>
    </div>

    <p v-if="currentWithoutRuns" class="runs__msg">
      Для текущего датасета «{{ active?.name }}» прогонов ещё нет — запустите первый, и он появится в сравнении.
    </p>

    <div ref="formEl" class="runs__form">
      <label class="field">
        <span class="field__label">Датасет</span>
        <select v-model="datasetId" class="select">
          <option v-if="!datasets.length" value="" disabled>нет ни одного датасета — загрузите архив</option>
          <option
            v-for="d in datasets"
            :key="d.id"
            :value="d.id"
            :disabled="!d.has_questions"
            :title="d.has_questions ? '' : 'В архиве нет questions.csv — прогон по вопросам невозможен'"
          >
            {{ d.name }} · {{ d.id }}{{ d.has_questions ? '' : ' — нет questions.csv' }}
          </option>
        </select>
        <span class="field__hint">Прогон возможен только с <span class="mono">questions.csv</span>.</span>
      </label>

      <div v-if="strategies.length" class="field">
        <span class="field__label">Режим чтения закупки</span>
        <div class="runs__mode" role="group" aria-label="Режим чтения закупки">
          <button
            v-for="s in strategies"
            :key="s.id"
            type="button"
            class="runs__mode-btn"
            :class="{ 'is-on': strategy === s.id }"
            :aria-pressed="strategy === s.id"
            :disabled="bothBusy || busy"
            :title="s.description"
            @click="strategy = s.id"
          >
            {{ STRATEGY_SHORT[s.id] ?? s.title }}
          </button>
        </div>
        <span class="field__hint">{{ strategyHint || 'Как модель читает закупку: целиком или по частям.' }}</span>
      </div>

      <div class="runs__go">
        <button class="btn btn--primary" type="button" :disabled="!canStartBoth" @click="onStartBoth">
          {{ bothBusy ? 'Запускаем…' : ladderRunning ? 'Идёт проверка…' : 'Запустить проверку' }}
        </button>
        <span class="field__hint">
          Один запуск — два прогона по очереди на одном датасете: «как есть» и итоговая система (агент с проверками и резервным проходом).
        </span>
      </div>
    </div>

    <div v-if="ladderId" class="ladder">
      <div class="progress ladder__bar" aria-hidden="true">
        <div class="progress__bar" :style="{ width: `${ladderPct}%` }" />
      </div>
      <ul class="ladder__steps">
        <li v-for="st in ladderSteps" :key="st.step" class="ladder__step">
          <span
            class="badge"
            :class="
              st.run?.status === 'done'
                ? 'badge--ok'
                : st.run?.status === 'running'
                  ? 'badge--accent'
                  : st.run
                    ? 'badge--bad'
                    : ''
            "
          >
            {{ st.run ? st.run.status : 'в очереди' }}
          </span>
          <span :class="{ 'ladder__title--now': st.run?.status === 'running' }">{{ st.title }}</span>
        </li>
      </ul>
    </div>

    <details class="runs__adv">
      <summary class="runs__adv-sum">Одиночный прогон — выбрать один пайплайн вручную</summary>
      <div class="runs__form runs__form--adv">
        <label class="field">
          <span class="field__label">Пайплайн</span>
          <select v-model="pipeline" class="select">
            <option v-for="p in health?.pipelines ?? []" :key="p.name" :value="p.name" :disabled="!p.available">
              {{ p.title }}
            </option>
          </select>
          <span class="field__hint">baseline — «как есть», agent — с проверками.</span>
        </label>

        <label class="field">
          <span class="field__label">Подпись прогона</span>
          <input v-model="label" class="input" type="text" placeholder="стало: критики" />
          <span class="field__hint">Видно в сравнении «было / стало».</span>
        </label>

        <div class="runs__go">
          <label class="runs__guard">
            <input v-model="guard" type="checkbox" />
            проверки кодом
          </label>
          <button class="btn btn--ghost" type="button" :disabled="!canStart" @click="onStart">
            {{ busy ? 'Запускаем…' : 'Запустить прогон' }}
          </button>
        </div>
      </div>
    </details>

    <p v-if="problem" class="runs__msg runs__msg--bad">
      <AppIcon name="alert" size="sm" /> {{ problem }}
    </p>
    <p v-else-if="notice" class="runs__msg">{{ notice }}</p>
    <p v-else-if="error" class="runs__msg runs__msg--bad"><AppIcon name="alert" size="sm" /> {{ error }}</p>

    <p v-if="ready && !runs.length" class="runs__empty muted">
      Прогонов ещё нет — запустите первый, дашборд подхватит цифры сам.
    </p>

    <ul v-else class="runs__list">
      <li v-for="r in runs" :key="r.run_id" class="runs__row">
        <div class="runs__main">
          <span class="runs__name">{{ r.label || r.dataset_name || r.dataset }}</span>
          <span class="mono runs__id">{{ r.run_id }}</span>
          <span class="badge" :class="statusBadge[r.status]">{{ r.status }}</span>
          <span class="badge">{{ r.pipeline }}</span>
          <span class="badge">{{ r.guard ? 'проверки вкл' : 'без проверок' }}</span>
          <span v-if="indexOf(r) !== null" class="badge badge--accent">индекс {{ indexOf(r) }}</span>
          <span v-else-if="r.score?.error" class="badge badge--warn">оценка не получилась</span>
          <span v-if="r.failed" class="badge badge--warn">упало {{ r.failed }}</span>
          <button v-if="resumable(r)" class="btn btn--ghost btn--sm" type="button" @click="onResume(r)">
            {{ resuming === r.run_id ? 'Дозапускаем…' : 'Дозапустить' }}
          </button>
        </div>

        <div class="runs__meta muted">
          <span>из {{ r.n ?? '—' }} вопросов</span>
          <span v-if="r.llm_calls !== undefined">{{ r.llm_calls }} запросов к модели</span>
          <span v-if="r.elapsed_s !== undefined">{{ r.elapsed_s }} с</span>
          <span>{{ shortTime(r.created_at) }}</span>
          <RouterLink
            v-if="r.status === 'done' && r.guard"
            :to="{ name: 'caught', params: { runId: r.run_id } }"
          >
            Пойманные обманы
          </RouterLink>
          <a v-if="r.status === 'done'" :href="answersCsvUrl(r.run_id)" download>Скачать answers.csv</a>
        </div>

        <div v-if="r.status === 'running'" class="progress runs__bar">
          <div class="progress__bar" :style="{ width: `${progressOf(r)}%` }" />
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.runs__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s-4);
  margin-bottom: var(--s-4);
}

.runs__sub {
  font-size: 13.5px;
  margin-top: 2px;
}

.runs__form {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--s-4);
  padding-bottom: var(--s-4);
  border-bottom: 1px solid var(--border);
}

.runs__go {
  display: grid;
  align-content: end;
  gap: var(--s-2);
}

.runs__mode {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 3px;
  padding: 3px;
  background: var(--surface-inset);
  border: 1px solid var(--border);
  border-radius: var(--r-pill);
}

.runs__mode-btn {
  padding: 6px 12px;
  border: 0;
  border-radius: var(--r-pill);
  background: transparent;
  color: var(--text-muted);
  font: inherit;
  font-size: 13px;
  font-weight: 550;
  cursor: pointer;
  transition: background var(--t) var(--ease), color var(--t) var(--ease);
}

.runs__mode-btn:disabled {
  opacity: 0.55;
  cursor: default;
}

.runs__mode-btn.is-on {
  background: var(--accent);
  color: var(--on-accent);
}

.runs__guard {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-muted);
  accent-color: var(--accent);
}

.runs__msg {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: var(--s-3);
  font-size: 13.5px;
  color: var(--text-muted);
}

.runs__msg--bad {
  color: var(--bad);
}

.runs__empty {
  margin-top: var(--s-4);
  font-size: 13.5px;
}

.runs__list {
  list-style: none;
  display: grid;
  gap: var(--s-3);
  margin-top: var(--s-4);
}

.runs__row {
  display: grid;
  gap: 4px;
}

.runs__main {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s-2);
}

.runs__name {
  font-weight: 600;
}

.runs__id {
  font-size: 12.5px;
  color: var(--text-faint);
}

.runs__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s-3);
  font-size: 12.5px;
}

.runs__bar {
  margin-top: 4px;
}

.ladder {
  display: grid;
  gap: var(--s-3);
  margin-top: var(--s-4);
}

.ladder__bar {
  height: 8px;
}

.ladder__steps {
  list-style: none;
  display: grid;
  gap: var(--s-2);
}

.ladder__step {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  font-size: 13.5px;
}

.ladder__title--now {
  font-weight: 600;
}

.runs__adv {
  margin-top: var(--s-4);
  border-top: 1px solid var(--border);
  padding-top: var(--s-3);
}

.runs__adv-sum {
  cursor: pointer;
  font-size: 13px;
  color: var(--text-muted);
}

.runs__form--adv {
  border-bottom: none;
  padding-bottom: 0;
  padding-top: var(--s-4);
}
</style>
