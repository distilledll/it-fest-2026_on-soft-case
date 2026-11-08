<script setup lang="ts">
import { Chart, type ChartConfiguration, type Plugin } from 'chart.js/auto'
import { onMounted, onUnmounted, ref, watch } from 'vue'

import { useTheme } from '@/composables/useTheme'
import { applyChartDefaults, palette } from '@/utils/chartTheme'
import type { Verdict } from '@/types'

const props = withDefaults(
  defineProps<{
    labels: string[]
    counts: Record<Verdict, number[]>
    /** Подписи в легенде внутри холста: ['верно · 61', ...]. */
    legendLabels?: string[]
  }>(),
  { legendLabels: () => [] },
)

const host = ref<HTMLCanvasElement | null>(null)
const { theme } = useTheme()
let chart: Chart | null = null

const SERIES: { key: Verdict; label: string; tone: 'ok' | 'warn' | 'bad' }[] = [
  { key: 'верно', label: 'верно', tone: 'ok' },
  { key: 'осторожно', label: 'осторожно («не знаю»)', tone: 'warn' },
  { key: 'обман', label: 'обман', tone: 'bad' },
]

function build() {
  chart?.destroy()
  if (!host.value) return
  const p = palette()
  const color = { ok: p.ok, warn: p.warn, bad: p.bad }

  /* Сумму вопросов типа пишем над столбиком: внутри сегментов текст нечитаем. */
  const totals: Plugin<'bar'> = {
    id: 'stackTotals',
    afterDatasetsDraw(c) {
      const ctx = c.ctx
      const n = c.data.labels?.length ?? 0
      ctx.save()
      ctx.font = `600 11.5px ${getComputedStyle(document.body).fontFamily}`
      ctx.textAlign = 'center'
      ctx.lineJoin = 'round'
      ctx.lineWidth = 4
      ctx.strokeStyle = p.surface
      ctx.fillStyle = p.muted
      for (let i = 0; i < n; i++) {
        let sum = 0
        let top: number | null = null
        c.data.datasets.forEach((ds, di) => {
          if (!c.isDatasetVisible(di)) return
          sum += Number(ds.data[i]) || 0
          const y = c.getDatasetMeta(di).data[i]?.y
          if (y !== undefined && (top === null || y < top)) top = y
        })
        if (top !== null && sum > 0) {
          ctx.strokeText(String(sum), c.getDatasetMeta(0).data[i]!.x, top - 8)
          ctx.fillText(String(sum), c.getDatasetMeta(0).data[i]!.x, top - 8)
        }
      }
      ctx.restore()
    },
  }

  const config: ChartConfiguration<'bar'> = {
    type: 'bar',
    data: {
      labels: props.labels,
      datasets: SERIES.map((s) => ({
        label: s.label,
        data: props.counts[s.key],
        backgroundColor: color[s.tone],
        hoverBackgroundColor: color[s.tone],
        borderRadius: 4,
        borderSkipped: false,
        maxBarThickness: 40,
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      layout: { padding: { top: 18 } },
      animation: { duration: 800, easing: 'easeOutQuart' },
      plugins: {
        legend: {
          position: 'top',
          align: 'end',
          labels: {
            usePointStyle: true,
            pointStyleWidth: 12,
            boxHeight: 12,
            padding: 16,
            color: p.text,
            font: { size: 13, weight: 600 },
            generateLabels: (c) =>
              c.data.datasets.map((ds, i) => ({
                text: props.legendLabels[i] ?? String(ds.label ?? ''),
                hidden: !c.isDatasetVisible(i),
                datasetIndex: i,
                pointStyle: 'rectRounded',
                strokeStyle: color[SERIES[i]!.tone],
                fillStyle: color[SERIES[i]!.tone],
                lineWidth: 0,
                fontColor: p.text,
              })),
          },
        },
        tooltip: { callbacks: { label: (item) => ` ${item.dataset.label}: ${item.parsed.y}` } },
      },
      scales: {
        x: {
          stacked: true,
          grid: { display: false },
          border: { color: p.strong },
          ticks: { maxRotation: 0, padding: 6, color: p.muted, font: { size: 12.5 } },
        },
        y: {
          stacked: true,
          border: { display: false },
          ticks: { precision: 0, padding: 8, color: p.muted },
          grid: { color: p.grid },
          title: { display: true, text: 'вопросов', color: p.faint, font: { size: 11.5 } },
        },
      },
    },
    plugins: [totals],
  }

  chart = new Chart(host.value, config)
}

onMounted(() => {
  applyChartDefaults()
  build()
})

onUnmounted(() => chart?.destroy())
watch([theme, () => props.counts, () => props.legendLabels], () => build(), { deep: true })
</script>

<template>
  <div class="chart">
    <canvas ref="host" role="img" aria-label="Вердикты по типам вопросов" />
  </div>
</template>

<style scoped>
.chart {
  position: relative;
  height: 300px;
}
</style>
