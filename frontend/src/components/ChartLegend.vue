<script setup lang="ts">
import type { LegendItem } from '@/types'

defineProps<{ items: LegendItem[] }>()

const hidden = defineModel<string[]>({ default: () => [] })

function toggle(id: string) {
  hidden.value = hidden.value.includes(id) ? hidden.value.filter((x) => x !== id) : [...hidden.value, id]
}
</script>

<template>
  <div class="legend" role="group" aria-label="Условные обозначения">
    <button
      v-for="it in items"
      :key="it.id"
      class="legend__item"
      :class="{ 'is-hidden': hidden.includes(it.id) }"
      type="button"
      :aria-pressed="!hidden.includes(it.id)"
      @click="toggle(it.id)"
    >
      <svg class="legend__swatch" viewBox="0 0 28 12" aria-hidden="true">
        <template v-if="it.kind === 'line-dashed'">
          <path d="M1 6h26" :stroke="it.color" stroke-width="2.5" stroke-dasharray="5 4" />
          <circle cx="14" cy="6" r="4" :fill="it.color" stroke="var(--surface)" stroke-width="2" />
        </template>
        <template v-else-if="it.kind === 'line-solid'">
          <path d="M1 5h26v7H1z" :fill="it.color" opacity="0.16" />
          <path d="M1 5h26" :stroke="it.color" stroke-width="2.5" />
          <circle cx="14" cy="5" r="4" :fill="it.color" stroke="var(--surface)" stroke-width="2" />
        </template>
        <rect v-else x="8" y="0" width="12" height="12" rx="3.5" :fill="it.color" />
      </svg>

      <span class="legend__label">{{ it.label }}</span>
      <b v-if="it.value !== undefined" class="legend__value">{{ it.value }}</b>
    </button>
  </div>
</template>

<style scoped>
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s-2) var(--s-4);
}

.legend__item {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  padding: 4px 8px;
  border: 1px solid transparent;
  border-radius: var(--r-pill);
  background: none;
  color: var(--text);
  font: inherit;
  font-size: 13.5px;
  cursor: pointer;
  transition: background-color var(--t-fast) var(--ease), border-color var(--t-fast) var(--ease),
    opacity var(--t-fast) var(--ease);
}

.legend__item:hover {
  background: var(--surface-3);
  border-color: var(--border);
}

.legend__item.is-hidden {
  opacity: 0.45;
}

.legend__item.is-hidden .legend__label {
  text-decoration: line-through;
}

.legend__swatch {
  width: 28px;
  height: 12px;
  flex: none;
  overflow: visible;
}

.legend__label {
  font-weight: 560;
  white-space: nowrap;
}

.legend__value {
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
}
</style>
