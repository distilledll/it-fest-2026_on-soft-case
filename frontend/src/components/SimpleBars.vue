<script setup lang="ts">
import { Chart, type ChartConfiguration } from 'chart.js/auto'
import { onMounted, onUnmounted, ref, watch } from 'vue'

import { useTheme } from '@/composables/useTheme'
import { alpha, applyChartDefaults, palette } from '@/utils/chartTheme'

/** Тон серии — цвет из токенов темы, чтобы графики жили в одной палитре с интерфейсом. */
export type BarTone = 'before' | 'after' | 'ok' | 'warn' | 'bad' | 'muted'

export interface BarSeries {
  label: string
  data: number[]
  tone: BarTone
}

const props = withDefaults(
  defineProps<{
    labels: string[]
    series: BarSeries[]
    /** Сегменты друг на друге (вклад) — или рядом (сравнение). */
    stacked?: boolean
    /** Горизонтальные столбики — для длинных подписей (названия проверок). */
    horizontal?: boolean
    axisTitle?: string
    height?: number
    ariaLabel?: string
  }>(),
  { stacked: false, horizontal: false, axisTitle: 'вопросов', height: 300, ariaLabel: 'График' },
)

const host = ref<HTMLCanvasElement | null>(null)
const { theme } = useTheme()
let chart: Chart | null = null

function toneColor(t: BarTone): string {
  const p = palette()
  return { before: alpha(p.faint || '#9a9a9a', 0.55), after: p.accent, ok: p.ok, warn: p.warn, bad: p.bad, muted: p.faint }[t]
}

function build() {
  chart?.destroy()
  if (!host.value) return
  const p = palette()
  const valueAxis = props.horizontal ? 'x' : 'y'
  const catAxis = props.horizontal ? 'y' : 'x'
  const config: ChartConfiguration<'bar'> = {
    type: 'bar',
    data: {
      labels: props.labels,
      datasets: props.series.map((s) => ({
        label: s.label,
        data: s.data,
        backgroundColor: toneColor(s.tone),
        hoverBackgroundColor: toneColor(s.tone),
        borderRadius: 4,
        borderSkipped: false,
        maxBarThickness: 36,
      })),
    },
    options: {
      indexAxis: props.horizontal ? 'y' : 'x',
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 700, easing: 'easeOutQuart' },
      plugins: {
        legend: {
          position: 'top',
          align: 'end',
          labels: { usePointStyle: true, pointStyle: 'rectRounded', boxHeight: 12, padding: 16, color: p.text,
                    font: { size: 13, weight: 600 } },
        },
        tooltip: {
          callbacks: { label: (item) => ` ${item.dataset.label}: ${props.horizontal ? item.parsed.x : item.parsed.y}` },
        },
      },
      scales: {
        [catAxis]: {
          stacked: props.stacked,
          grid: { display: false },
          border: { color: p.strong },
          ticks: { color: p.text, font: { size: 12.5 }, autoSkip: false },
        },
        [valueAxis]: {
          stacked: props.stacked,
          beginAtZero: true,
          border: { display: false },
          ticks: { precision: 0, color: p.muted },
          grid: { color: p.grid },
          title: { display: !!props.axisTitle, text: props.axisTitle, color: p.faint, font: { size: 11.5 } },
        },
      },
    },
  }
  chart = new Chart(host.value, config)
}

onMounted(() => {
  applyChartDefaults()
  build()
})
onUnmounted(() => chart?.destroy())
watch([theme, () => props.labels, () => props.series], () => build(), { deep: true })
</script>

<template>
  <div class="chart" :style="{ height: `${height}px` }">
    <canvas ref="host" role="img" :aria-label="ariaLabel" />
  </div>
</template>

<style scoped>
.chart {
  position: relative;
}
</style>
