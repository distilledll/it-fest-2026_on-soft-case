<script setup lang="ts">
import { computed, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    label: string
    unit?: string
    hint?: string
    min?: number
    max?: number
    step?: number
  }>(),
  { min: 0, max: 100, step: 1 },
)

const model = defineModel<number>({ required: true })

const text = ref(String(model.value))
watch(model, (v) => {
  if (parse(text.value) !== v) text.value = String(v)
})

function parse(raw: string): number {
  return Number.parseFloat(raw.replace(',', '.'))
}

function clamp(n: number): number {
  if (!Number.isFinite(n)) return props.min
  const fixed = Math.round(n * 1000) / 1000
  return Math.min(props.max, Math.max(props.min, fixed))
}

function commit() {
  model.value = clamp(parse(text.value))
  text.value = String(model.value)
}

function bump(dir: number) {
  model.value = clamp(parse(text.value) + dir * props.step)
  text.value = String(model.value)
}

const atMin = computed(() => parse(text.value) <= props.min)
const atMax = computed(() => parse(text.value) >= props.max)
</script>

<template>
  <label class="num">
    <span class="field__label">{{ label }}</span>
    <span class="num__control">
      <button class="num__step" type="button" :disabled="atMin" aria-label="Уменьшить" @click="bump(-1)">
        &minus;
      </button>
      <input
        v-model="text"
        class="num__input"
        type="number"
        inputmode="decimal"
        :min="min"
        :max="max"
        :step="step"
        @blur="commit"
        @keydown.enter.prevent="commit"
      />
      <span v-if="unit" class="num__unit">{{ unit }}</span>
      <button class="num__step" type="button" :disabled="atMax" aria-label="Увеличить" @click="bump(1)">
        +
      </button>
    </span>
    <span v-if="hint" class="field__hint">{{ hint }}</span>
  </label>
</template>

<style scoped>
.num {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.num__control {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  background: var(--surface-inset);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  transition: border-color var(--t-fast) var(--ease), background-color var(--t-fast) var(--ease),
    box-shadow var(--t-fast) var(--ease);
}

.num__control:hover {
  border-color: var(--border-strong);
}

.num__control:focus-within {
  border-color: var(--accent);
  background: var(--surface);
  box-shadow: var(--ring);
}

.num__input {
  flex: 1;
  min-width: 0;
  width: 100%;
  padding: 7px 2px;
  border: none;
  background: none;
  color: var(--text);
  font: inherit;
  font-weight: 560;
  font-variant-numeric: tabular-nums;
  text-align: center;
  appearance: textfield;
}

.num__input:focus {
  outline: none;
}

.num__input::-webkit-outer-spin-button,
.num__input::-webkit-inner-spin-button {
  appearance: none;
  margin: 0;
}

.num__unit {
  font-size: 12px;
  color: var(--text-faint);
  white-space: nowrap;
}

.num__step {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  flex: none;
  border: none;
  border-radius: var(--r-xs);
  background: var(--surface-3);
  color: var(--text-muted);
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  transition: background-color var(--t-fast) var(--ease), color var(--t-fast) var(--ease),
    opacity var(--t-fast) var(--ease);
}

.num__step:hover:not(:disabled) {
  background: var(--accent-soft);
  color: var(--accent);
}

.num__step:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
