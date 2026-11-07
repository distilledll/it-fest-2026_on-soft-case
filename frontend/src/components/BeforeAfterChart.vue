<script setup lang="ts">
import { Chart, type ChartConfiguration, type Plugin, type ScriptableScaleContext } from 'chart.js/auto'
import { onMounted, onUnmounted, ref, watch } from 'vue'

import { useTheme } from '@/composables/useTheme'
import { alpha, applyChartDefaults, palette } from '@/utils/chartTheme'

const props = withDefaults(defineProps<{ labels: string[]; before: number[]; after: number[]; hidden?: string[] }>(), {
  hidden: () => [],
})

const host = ref<HTMLCanvasElement | null>(null)
const { theme } = useTheme()
let chart: Chart | null = null

const BEFORE = 'before'
const AFTER = 'after'

function label(v: unknown): string {
  const n = Number(v)
  return Number.isInteger(n) ? `${n}` : n.toFixed(1)
}

function build() {
  chart?.destroy()
  if (!host.value) return
  const p = palette()
  const beforeColor = p.muted
  const afterColor = p.accent
  const family = getComputedStyle(document.body).fontFamily

  /* Подписи значений рисует сами: на графике они важнее подписей оси. */
  const valueLabels: Plugin<'line'> = {
    id: 'valueLabels',
    afterDatasetsDraw(c) {
      const ctx = c.ctx
      ctx.save()
      ctx.font = `600 11.5px ${family}`
      ctx.textAlign = 'center'
      ctx.lineJoin = 'round'
      ctx.lineWidth = 4
      ctx.strokeStyle = p.surface
      c.data.datasets.forEach((ds, di) => {
        if (!c.isDatasetVisible(di)) return
        const meta = c.getDatasetMeta(di)
        const above = di === 1
        ctx.fillStyle = di === 1 ? afterColor : beforeColor
        meta.data.forEach((el, i) => {
          const text = label(ds.data[i])
          const y = el.y + (above ? -12 : 20)
          ctx.strokeText(text, el.x, y)
          ctx.fillText(text, el.x, y)
        })
      })
      ctx.restore()
    },
  }

  const dot = (color: string) => ({
    pointRadius: 5,
    pointHoverRadius: 7.5,
    pointHitRadius: 16,
    pointBorderWidth: 2.5,
    pointBorderColor: p.surface,
    pointHoverBorderColor: p.surface,
    pointBackgroundColor: color,
    pointHoverBackgroundColor: color,
  })

  const zeroLine = (ctx: ScriptableScaleContext) => (ctx.tick.value === 0 ? p.strong : p.grid)

  const config: ChartConfiguration<'line'> = {
    type: 'line',
    data: {
      labels: props.labels,
      datasets: [
        {
          label: 'было',
          data: props.before,
          borderColor: beforeColor,
          backgroundColor: beforeColor,
          borderDash: [6, 4],
          borderWidth: 2,
          tension: 0.35,
          fill: false,
          ...dot(beforeColor),
        },
        {
          label: 'стало',
          data: props.after,
          borderColor: afterColor,
          backgroundColor: alpha(afterColor, 0.14),
          borderWidth: 2.5,
          tension: 0.35,
          fill: true,
          ...dot(afterColor),
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      layout: { padding: { top: 20, bottom: 16, right: 8 } },
      interaction: { mode: 'index', intersect: false },
      animation: { duration: 900, easing: 'easeOutQuart' },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: { label: (item) => ` ${item.dataset.label}: ${label(item.parsed.y)} из 100` },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          border: { color: p.strong },
          ticks: { maxRotation: 0, padding: 6, color: p.muted, font: { size: 12.5 } },
        },
        y: {
          min: -120,
          max: 120,
          border: { display: false },
          title: { display: true, text: 'индекс доверия, из 100', color: p.faint, font: { size: 11.5 } },
          ticks: { stepSize: 60, padding: 8, color: p.muted },
          grid: { color: zeroLine, lineWidth: (ctx: ScriptableScaleContext) => (ctx.tick.value === 0 ? 1.5 : 1) },
        },
      },
    },
    plugins: [valueLabels],
  }

  chart = new Chart(host.value, config)
  props.hidden.forEach((id) => chart?.setDatasetVisibility(id === AFTER ? 1 : 0, false))
  chart.update('none')
}

onMounted(() => {
  applyChartDefaults()
  build()
})

onUnmounted(() => chart?.destroy())

watch([theme, () => props.before, () => props.after], () => build(), { deep: true })

watch(
  () => props.hidden,
  () => {
    if (!chart) return
    chart.setDatasetVisibility(0, !props.hidden.includes(BEFORE))
    chart.setDatasetVisibility(1, !props.hidden.includes(AFTER))
    chart.update()
  },
)
</script>

<template>
  <div class="chart">
    <canvas ref="host" role="img" aria-label="Индекс доверия по типам вопросов: было и стало" />
  </div>
</template>

<style scoped>
.chart {
  position: relative;
  height: 300px;
}
</style>
