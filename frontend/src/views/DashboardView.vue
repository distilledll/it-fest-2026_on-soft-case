<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import BeforeAfterChart from '@/components/BeforeAfterChart.vue'
import RunsPanel from '@/components/RunsPanel.vue'
import TypeHistogram from '@/components/TypeHistogram.vue'
import { QUESTION_TYPES, mockAfter, mockBefore, shortType } from '@/api/mock'
import { ApiError } from '@/api/http'
import { answersCsvUrl, compareRuns } from '@/api/runs'
import { useCountUp } from '@/composables/useCountUp'
import { useRuns } from '@/composables/useRuns'
import { formatIndex, shortTime, signed } from '@/utils/presentation'
import { indexOfRow, indexOfType, shareOf, sumOf, sumVerdicts } from '@/utils/score'
import type { CompareResult, RunMeta, Status, TypeBreakdown } from '@/types'

/** Минимум, который нужен экрану от прогона: разбивка по типам, индекс и метаданные. */
interface RunView {
  meta: RunMeta
  byType: TypeBreakdown
  scored: boolean
  index: number | null
}

const STATUS_ROWS: { key: Status; label: string; cls: string }[] = [
  { key: 'ответ', label: 'ответ', cls: 'is-ok' },
  { key: 'расхождение', label: 'расхождение', cls: 'is-warn' },
  { key: 'нет в документах', label: 'нет в документах', cls: 'is-info' },
  { key: 'не знаю', label: 'не знаю', cls: 'is-unknown' },
]

function viewOf(meta: RunMeta): RunView {
  const byType = (meta.score?.by_type ?? {}) as TypeBreakdown
  const scored = Object.keys(byType).length > 0
  const fromCheck = meta.score?.index
  const index = typeof fromCheck === 'number' ? fromCheck : scored ? indexOfRow(sumVerdicts(byType)) : null
  return { meta, byType, scored, index }
}

const demo = (m: typeof mockAfter): RunView => ({
  meta: m.meta,
  byType: m.breakdown,
  scored: true,
  index: m.score.index,
})

const { finished, byId, refresh } = useRuns()

const beforeId = ref('')
const afterId = ref('')
const autoPick = ref(true)
const pair = ref<CompareResult | null>(null)
const pairError = ref('')

/* «было» — самый старый готовый прогон, «стало» — самый свежий; выбор можно поменять руками. */
watch(
  finished,
  (list) => {
    if (!list.length) {
      beforeId.value = ''
      afterId.value = ''
      return
    }
    const byTime = [...list].sort(
      (a, b) => a.created_at.localeCompare(b.created_at) || a.run_id.localeCompare(b.run_id),
    )
    if (autoPick.value || !byId(beforeId.value) || !byId(afterId.value)) {
      afterId.value = byTime[byTime.length - 1]!.run_id
      beforeId.value = byTime[0]!.run_id
    }
  },
  { immediate: true },
)

watch([beforeId, afterId], async ([b, a]) => {
  pairError.value = ''
  if (!b || !a || b === a) {
    pair.value = null
    return
  }
  try {
    pair.value = await compareRuns(b, a)
  } catch (e) {
    pair.value = null
    pairError.value = e instanceof ApiError ? e.message : 'не удалось получить сравнение прогонов'
  }
})

const before = computed<RunView>(() => (pair.value ? viewOf(pair.value.before) : demo(mockBefore)))
const after = computed<RunView>(() => (pair.value ? viewOf(pair.value.after) : demo(mockAfter)))
const isDemo = computed(() => !pair.value)

const types = computed<string[]>(() => {
  if (!pair.value) return [...QUESTION_TYPES]
  const both = new Set([...Object.keys(before.value.byType), ...Object.keys(after.value.byType)])
  return [...both].sort()
})

const labels = computed(() => types.value.map(shortType))
const chartsReady = computed(() => before.value.scored && after.value.scored && types.value.length > 0)
const lineBefore = computed(() => types.value.map((t) => indexOfType(before.value.byType, t)))
const lineAfter = computed(() => types.value.map((t) => indexOfType(after.value.byType, t)))

const totals = computed(() => sumVerdicts(after.value.byType))
const questions = computed(() => sumOf(totals.value))
const histogram = computed(() => ({
  верно: types.value.map((t) => after.value.byType[t]?.верно ?? 0),
  осторожно: types.value.map((t) => after.value.byType[t]?.осторожно ?? 0),
  обман: types.value.map((t) => after.value.byType[t]?.обман ?? 0),
}))

const indexValue = useCountUp(() => after.value.index ?? 0)
const delta = computed<number | null>(() => {
  if (after.value.index === null || before.value.index === null) return null
  return Math.round((after.value.index - before.value.index) * 10) / 10
})

/** Вердикты, если есть оценка check.py; иначе честная разбивка по статусам ответов. */
const rows = computed(() => {
  if (after.value.scored) {
    const t = totals.value
    return [
      { key: 'верно', label: 'верно', n: t.верно, pct: shareOf(t.верно, questions.value), cls: 'is-ok' },
      {
        key: 'осторожно',
        label: 'осторожно («не знаю»)',
        n: t.осторожно,
        pct: shareOf(t.осторожно, questions.value),
        cls: 'is-warn',
      },
      { key: 'обман', label: 'обман', n: t.обман, pct: shareOf(t.обман, questions.value), cls: 'is-bad' },
    ]
  }
  const s = after.value.meta.statuses
  if (!s) return []
  const all = Object.values(s).reduce((a, b) => a + b, 0)
  return STATUS_ROWS.map((r) => ({
    key: r.key,
    label: r.label,
    n: s[r.key] ?? 0,
    pct: shareOf(s[r.key] ?? 0, all),
    cls: r.cls,
  }))
})

const lineLegend = computed(() => [
  `было · ${before.value.index === null ? 'нет оценки' : formatIndex(before.value.index)}`,
  `стало · ${after.value.index === null ? 'нет оценки' : formatIndex(after.value.index)}`,
])

const barLegend = computed(() => [
  `верно · ${totals.value.верно}`,
  `осторожно · ${totals.value.осторожно}`,
  `обман · ${totals.value.обман}`,
])

const runTitle = (r: RunMeta) =>
  `${r.label || r.dataset_name || r.dataset} · ${r.pipeline} · ${shortTime(r.created_at)}`

const revealed = ref(false)
onMounted(() => requestAnimationFrame(() => (revealed.value = true)))
const barWidth = (pct: number) => ({ width: revealed.value ? `${pct}%` : '0%' })

const downloaded = ref(false)

/** Отдаём бэкендовый CSV — тех же ответов, что ушли жюри. */
function downloadCurrent() {
  if (!afterId.value) return
  window.location.assign(answersCsvUrl(afterId.value))
  downloaded.value = true
  setTimeout(() => (downloaded.value = false), 2200)
}
</script>

<template>
  <main class="page">
    <header class="page-head">
      <div>
        <p class="eyebrow">Замер «было / стало»</p>
        <h1>Дашборд</h1>
      </div>

      <div class="pair">
        <span v-if="isDemo" class="badge badge--warn">демо-данные</span>
        <label class="field pair__field">
          <span class="field__label">прогон «было»</span>
          <select v-model="beforeId" class="select" @change="autoPick = false">
            <option value="" disabled>не выбран</option>
            <option v-for="r in finished" :key="r.run_id" :value="r.run_id">{{ runTitle(r) }}</option>
          </select>
        </label>
        <label class="field pair__field">
          <span class="field__label">прогон «стало»</span>
          <select v-model="afterId" class="select" @change="autoPick = false">
            <option value="" disabled>не выбран</option>
            <option v-for="r in finished" :key="r.run_id" :value="r.run_id">{{ runTitle(r) }}</option>
          </select>
        </label>
        <button class="btn btn--ghost btn--sm pair__refresh" type="button" @click="refresh()">
          <AppIcon name="refresh" size="sm" />
          Обновить
        </button>
      </div>
    </header>

    <p v-if="pairError" class="dash__note dash__note--bad">
      <AppIcon name="alert" size="sm" /> {{ pairError }}
    </p>
    <p v-else-if="isDemo" class="dash__note">
      <AppIcon name="alert" size="sm" />
      Сравнения прогонов пока нет — ниже цифры из демо-набора. Запустите прогон в блоке «Прогоны на
      сервере».
    </p>

    <div class="dash">
      <!-- 1. Числовой индекс -->
      <section class="card index reveal" aria-label="Индекс доверия">
        <p class="eyebrow">Индекс доверия</p>
        <p class="index__num">
          {{ after.index === null ? '—' : formatIndex(indexValue) }}<span class="index__of">/100</span>
        </p>
        <p class="index__delta">
          <span v-if="delta !== null" class="badge" :class="delta >= 0 ? 'badge--ok' : 'badge--bad'">
            {{ signed(delta) }} к прогону «было»
          </span>
          <span v-else class="badge">оценки нет — сравнение недоступно</span>
        </p>

        <div v-if="rows.length" class="index__bar" role="img" aria-label="Доли вердиктов">
          <span
            v-for="row in rows"
            :key="row.key"
            class="index__seg"
            :class="row.cls"
            :style="barWidth(row.pct)"
          />
        </div>

        <ul v-if="rows.length" class="index__legend">
          <li v-for="row in rows" :key="row.key">
            <span class="dot" :class="row.cls" />
            <span class="index__legend-label">{{ row.label }}</span>
            <b>{{ row.n }}</b>
          </li>
        </ul>

        <dl class="index__meta">
          <div>
            <dt>вопросов</dt>
            <dd>{{ after.meta.n ?? '—' }}</dd>
          </div>
          <div>
            <dt>запросов к модели</dt>
            <dd>{{ after.meta.llm_calls ?? '—' }}</dd>
          </div>
          <div>
            <dt>проверки кодом</dt>
            <dd>{{ after.meta.guard ? 'включены' : 'выключены' }}</dd>
          </div>
        </dl>
      </section>

      <!-- 2. Линейный график было/стало -->
      <section class="card panel reveal reveal-2" aria-label="Индекс доверия по типам вопросов">
        <h2>Индекс доверия по типам вопросов</h2>
        <p class="muted chart-sub">
          Пунктир — как отвечала модель «как есть». Сплошная линия — после проверок.
        </p>
        <BeforeAfterChart
          v-if="chartsReady"
          :labels="labels"
          :before="lineBefore"
          :after="lineAfter"
          :legend-labels="lineLegend"
        />
        <p v-else class="panel__empty muted">
          Разбивки по типам нет: прогон не оценён <span class="mono">check.py</span>. Он появляется,
          когда в датасете есть <span class="mono">answers_public.json</span>, а на сервере —
          <span class="mono">data/sample/check.py</span>.
        </p>
      </section>

      <!-- 3. Гистограмма по типам вопросов -->
      <section class="card panel reveal reveal-3" aria-label="Вердикты по типам вопросов">
        <h2>Где именно обманывал ИИ</h2>
        <p class="muted chart-sub">
          Столбик — все вопросы типа, цифра сверху — их количество. Красный сегмент там, где система
          была уверена и неправа.
        </p>
        <TypeHistogram v-if="chartsReady" :labels="labels" :counts="histogram" :legend-labels="barLegend" />
        <p v-else class="panel__empty muted">
          Те же причины, что у графика выше: без оценки нечего раскладывать по типам.
        </p>
      </section>

      <!-- 4. Прогоны: запуск и живой прогресс -->
      <RunsPanel />
    </div>

    <div class="dash__foot">
      <button class="btn btn--lg" type="button" :disabled="!afterId" @click="downloadCurrent">
        <AppIcon name="download" size="sm" />
        Скачать ответы прогона
      </button>
      <RouterLink class="btn btn--primary btn--lg" :to="{ name: 'upload' }">
        <AppIcon name="upload" size="sm" />
        Загрузить новые данные
      </RouterLink>
      <transition name="fade-slide">
        <span v-if="downloaded" class="dash__hint">
          <AppIcon name="check" size="sm" />
          файл сохранён
        </span>
      </transition>
    </div>
  </main>
</template>

<style scoped>
.dot {
  width: 8px;
  height: 8px;
  flex: none;
  border-radius: 50%;
  background: var(--text-faint);
}

.is-ok {
  background: var(--ok);
}

.is-warn {
  background: var(--warn);
}

.is-bad {
  background: var(--bad);
}

.is-info {
  background: var(--info);
}

.is-unknown {
  background: var(--border-strong);
}

.pair {
  display: flex;
  flex-wrap: wrap;
  align-items: end;
  gap: var(--s-3);
}

.pair__field {
  min-width: 210px;
}

.pair__refresh {
  margin-block-end: 1px;
}

.dash__note {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: var(--s-4);
  font-size: 13.5px;
  color: var(--text-muted);
}

.dash__note--bad {
  color: var(--bad);
}

.dash {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: var(--s-4);
}

.index {
  grid-column: span 4;
  display: flex;
  flex-direction: column;
}

.dash > section:nth-child(2) {
  grid-column: span 8;
}

.dash > section:nth-child(3),
.dash > section:nth-child(4) {
  grid-column: span 12;
}

.index__num {
  font-size: clamp(56px, 7vw, 78px);
  font-weight: 700;
  line-height: 1;
  letter-spacing: -0.04em;
  font-variant-numeric: tabular-nums;
  color: var(--accent);
}

.index__of {
  font-size: 20px;
  font-weight: 560;
  color: var(--text-faint);
  letter-spacing: 0;
  margin-inline-start: 4px;
}

.index__delta {
  margin-block: var(--s-3) var(--s-5);
}

.index__bar {
  display: flex;
  height: 12px;
  gap: 2px;
  border-radius: var(--r-pill);
  overflow: hidden;
}

.index__seg {
  transition: width var(--t-slow) var(--ease-out);
}

.index__legend {
  display: grid;
  gap: var(--s-2);
  margin: var(--s-4) 0 0;
  padding: 0;
  list-style: none;
}

.index__legend li {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  font-size: 14px;
}

.index__legend b {
  margin-inline-start: auto;
  font-variant-numeric: tabular-nums;
}

.index__legend-label {
  color: var(--text-muted);
}

.index__meta {
  display: grid;
  grid-template-columns: repeat(3, auto);
  justify-content: space-between;
  gap: var(--s-2) var(--s-3);
  margin: auto 0 0;
  padding-top: var(--s-4);
  border-top: 1px solid var(--border);
}

/* Метка растягивается по высоте, поэтому значения всегда на одной линии. */
.index__meta > div {
  display: flex;
  flex-direction: column;
}

.index__meta dt {
  flex: 1;
  font-size: 11.5px;
  color: var(--text-faint);
  white-space: nowrap;
}

.index__meta dd {
  margin: 2px 0 0;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.panel h2 {
  margin-bottom: 2px;
}

.chart-sub {
  font-size: 13.5px;
  margin-top: 2px;
  margin-bottom: var(--s-4);
  max-width: 62ch;
}

.panel__empty {
  font-size: 13.5px;
  padding: var(--s-5) 0;
  border-top: 1px dashed var(--border);
  max-width: 70ch;
}

.dash__foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s-3);
  margin-top: var(--s-5);
}

.dash__hint {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--ok);
  font-size: 13.5px;
}

@media (max-width: 1000px) {
  .index,
  .dash > section:nth-child(2),
  .dash > section:nth-child(3),
  .dash > section:nth-child(4) {
    grid-column: span 12;
  }
}
</style>
