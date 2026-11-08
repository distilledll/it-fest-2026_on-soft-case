import { Chart } from 'chart.js/auto'

/** Цвета берём из CSS-токенов, чтобы графики жили в одной теме с интерфейсом. */
export function palette() {
  const css = getComputedStyle(document.documentElement)
  const v = (name: string) => css.getPropertyValue(name).trim()
  return {
    text: v('--text'),
    muted: v('--text-muted'),
    faint: v('--text-faint'),
    grid: v('--border'),
    strong: v('--border-strong'),
    surface: v('--surface'),
    accent: v('--accent'),
    ok: v('--ok'),
    warn: v('--warn'),
    bad: v('--bad'),
  }
}

export function alpha(color: string, a: number): string {
  const c = color.trim()
  if (c.startsWith('#')) {
    const hex = c.slice(1)
    const full = hex.length === 3 ? [...hex].map((h) => h + h).join('') : hex
    const n = parseInt(full, 16)
    const r = (n >> 16) & 255
    const g = (n >> 8) & 255
    const b = n & 255
    return `rgba(${r}, ${g}, ${b}, ${a})`
  }
  return c
}

export function applyChartDefaults() {
  const p = palette()
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily
  Chart.defaults.font.size = 12
  Chart.defaults.color = p.muted
  Chart.defaults.plugins.tooltip.backgroundColor = p.surface
  Chart.defaults.plugins.tooltip.titleColor = p.text
  Chart.defaults.plugins.tooltip.bodyColor = p.text
  Chart.defaults.plugins.tooltip.borderColor = p.grid
  Chart.defaults.plugins.tooltip.borderWidth = 1
  Chart.defaults.plugins.tooltip.cornerRadius = 10
  Chart.defaults.plugins.tooltip.padding = 10
  Chart.defaults.plugins.tooltip.usePointStyle = true
  Chart.defaults.plugins.tooltip.boxPadding = 4
}
