<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import BeforeAfterChart from '@/components/BeforeAfterChart.vue'
import TypeHistogram from '@/components/TypeHistogram.vue'
import { useCountUp } from '@/composables/useCountUp'
import { QUESTION_TYPES, indexByType, mockAfter, mockBefore, shortType, total } from '@/api/mock'
import { formatIndex, signed } from '@/utils/presentation'

const before = mockBefore
const after = mockAfter

const labels = QUESTION_TYPES.map(shortType)
const lineBefore = indexByType(before.breakdown)
const lineAfter = indexByType(after.breakdown)

const totals = total(after.breakdown)
const all = totals.верно + totals.осторожно + totals.обман
const share = {
  верно: Math.round((totals.верно / all) * 100),
  осторожно: Math.round((totals.осторожно / all) * 100),
  обман: Math.round((totals.обман / all) * 100),
}

const histogram = {
  верно: QUESTION_TYPES.map((t) => after.breakdown[t]?.верно ?? 0),
  осторожно: QUESTION_TYPES.map((t) => after.breakdown[t]?.осторожно ?? 0),
  обман: QUESTION_TYPES.map((t) => after.breakdown[t]?.обман ?? 0),
}

const lineLegend = [
  `было · ${formatIndex(before.score.index)}`,
  `стало · ${formatIndex(after.score.index)}`,
]

const barLegend = [
  `верно · ${totals.верно}`,
  `осторожно · ${totals.осторожно}`,
  `обман · ${totals.обман}`,
]

const indexValue = useCountUp(() => after.score.index)
const delta = Math.round((after.score.index - before.score.index) * 10) / 10

const revealed = ref(false)
onMounted(() => requestAnimationFrame(() => (revealed.value = true)))
const barWidth = (pct: number) => ({ width: revealed.value ? `${pct}%` : '0%' })

const downloaded = ref(false)

/** Заглушка: позже — ссылка на GET /api/runs/{id}/answers.csv. */
function downloadCurrent() {
  const head = 'id;type;verdict;why\n'
  const rows = QUESTION_TYPES.flatMap((type, i) => {
    const b = after.breakdown[type]
    if (!b) return []
    return [
      `P0${i + 1}-01;${type};верно;`,
      `P0${i + 1}-02;${type};${b.осторожно > 0 ? 'осторожно' : 'верно'};система сказала «не знаю»`,
      `P0${i + 1}-03;${type};${b.обман > 0 ? 'обман' : 'верно'};числа из ответа нет в цитате`,
    ]
  })
  const blob = new Blob([head + rows.join('\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${after.meta.run_id}-result.csv`
  a.click()
  URL.revokeObjectURL(url)
  downloaded.value = true
  setTimeout(() => (downloaded.value = false), 2200)
}

const verdictRows = computed(() => [
  { key: 'верно', label: 'верно', n: totals.верно, pct: share.верно, cls: 'is-ok' },
  { key: 'осторожно', label: 'осторожно', n: totals.осторожно, pct: share.осторожно, cls: 'is-warn' },
  { key: 'обман', label: 'обман', n: totals.обман, pct: share.обман, cls: 'is-bad' },
])
</script>

<template>
  <main class="page">
    <header class="page-head">
      <div>
        <p class="eyebrow">Замер «было / стало»</p>
        <h1>Дашборд</h1>
      </div>
    </header>

    <div class="dash">
      <!-- 1. Числовой индекс -->
      <section class="card index reveal" aria-label="Индекс доверия">
        <p class="eyebrow">Индекс доверия</p>
        <p class="index__num">
          {{ formatIndex(indexValue) }}<span class="index__of">/100</span>
        </p>
        <p class="index__delta">
          <span class="badge" :class="delta >= 0 ? 'badge--ok' : 'badge--bad'">
            {{ signed(delta) }} к прогону «было»
          </span>
        </p>

        <div class="index__bar" role="img" aria-label="Доли вердиктов">
          <span
            v-for="row in verdictRows"
            :key="row.key"
            class="index__seg"
            :class="row.cls"
            :style="barWidth(row.pct)"
          />
        </div>

        <ul class="index__legend">
          <li v-for="row in verdictRows" :key="row.key">
            <span class="dot" :class="row.cls" />
            <span class="index__legend-label">{{ row.label }}</span>
            <b>{{ row.n }}</b>
          </li>
        </ul>

        <dl class="index__meta">
          <div>
            <dt>запросов к модели</dt>
            <dd>{{ after.meta.llm_calls }}</dd>
          </div>
          <div>
            <dt>на набор</dt>
            <dd>{{ after.meta.elapsed_s }} с</dd>
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
          :labels="labels"
          :before="lineBefore"
          :after="lineAfter"
          :legend-labels="lineLegend"
        />
      </section>

      <!-- 3. Гистограмма по типам вопросов -->
      <section class="card panel reveal reveal-3" aria-label="Вердикты по типам вопросов">
        <h2>Где именно обманывал ИИ</h2>
        <p class="muted chart-sub">
          Столбик — все вопросы типа, цифра сверху — их количество. Красный сегмент там, где система
          была уверена и неправа.
        </p>
        <TypeHistogram :labels="labels" :counts="histogram" :legend-labels="barLegend" />
      </section>
    </div>

    <div class="dash__foot">
      <button class="btn btn--lg" type="button" @click="downloadCurrent">
        <AppIcon name="download" size="sm" />
        Скачать текущие данные
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

.dash > section:nth-child(3) {
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
  .dash > section:nth-child(3) {
    grid-column: span 12;
  }
}
</style>
