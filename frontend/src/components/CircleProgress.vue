<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{ value: number; size?: number; label?: string }>(), {
  size: 104,
})

const stroke = 8
const r = (props.size - stroke) / 2
const c = 2 * Math.PI * r

const shown = computed(() => Math.max(0, Math.min(100, Math.round(props.value))))
const offset = computed(() => c - (c * shown.value) / 100)
</script>

<template>
  <div class="ring" :style="{ width: `${size}px`, height: `${size}px` }" role="progressbar"
       :aria-valuenow="shown" aria-valuemin="0" aria-valuemax="100" :aria-label="label">
    <svg :width="size" :height="size" :style="{ transform: 'rotate(-90deg)' }">
      <circle :cx="size / 2" :cy="size / 2" :r="r" fill="none" stroke="var(--surface-3)" :stroke-width="stroke" />
      <circle
        :cx="size / 2"
        :cy="size / 2"
        :r="r"
        fill="none"
        stroke="var(--accent)"
        :stroke-width="stroke"
        stroke-linecap="round"
        :stroke-dasharray="c"
        :stroke-dashoffset="offset"
      />
    </svg>
    <span class="ring__value">{{ shown }}<i>%</i></span>
  </div>
</template>

<style scoped>
.ring {
  position: relative;
  display: grid;
  place-items: center;
}

.ring circle {
  transition: stroke-dashoffset var(--t) var(--ease);
}

.ring__value {
  position: absolute;
  font-size: 21px;
  font-weight: 660;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
}

.ring__value i {
  font-style: normal;
  font-size: 12px;
  color: var(--text-faint);
  margin-inline-start: 1px;
}
</style>
