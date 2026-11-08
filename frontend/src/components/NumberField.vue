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

/**
 * Пишем только из text: одно направление потока, без обработчиков blur —
 * на number-инпуте они ведут себя непредсказуемо. Значение вне диапазона
 * подсвечиваем, а в модель уходит уже ограниченное число.
 */
const text = ref(String(model.value))
let lastSet = model.value

function parse(raw: string | number): number {
  return typeof raw === 'number' ? raw : Number.parseFloat(raw.replace(',', '.'))
}

function clamp(n: number): number {
  if (!Number.isFinite(n)) return props.min
  return Math.min(props.max, Math.max(props.min, Math.round(n * 1000) / 1000))
}

const parsed = computed(() => parse(text.value))
const invalid = computed(() => !Number.isFinite(parsed.value) || parsed.value < props.min || parsed.value > props.max)
const atMin = computed(() => parsed.value <= props.min)
const atMax = computed(() => parsed.value >= props.max)

watch(text, () => {
  if (!Number.isFinite(parsed.value)) return
  lastSet = clamp(parsed.value)
  model.value = lastSet
})

watch(model, (v) => {
  if (v === lastSet) return
  lastSet = v
  text.value = String(v)
})

function bump(dir: number) {
  text.value = String(clamp((Number.isFinite(parsed.value) ? parsed.value : lastSet) + dir * props.step))
}
</script>

<template>
  <label class="num">
    <span class="field__label">{{ label }}</span>
    <span class="num__control" :class="{ 'num__control--bad': invalid }">
      <button class="num__step" type="button" :disabled="atMin" aria-label="Уменьшить" @click="bump(-1)">
        &minus;
      </button>
      <input
        v-model="text"
        class="num__input"
        type="text"
        inputmode="decimal"
        autocomplete="off"
        :aria-invalid="invalid"
      />
      <span v-if="unit" class="num__unit">{{ unit }}</span>
      <button class="num__step" type="button" :disabled="atMax" aria-label="Увеличить" @click="bump(1)">
        +
      </button>
    </span>
    <span class="field__hint" :class="{ 'field__hint--bad': invalid }">
      {{ invalid ? `Допустимо от ${min} до ${max}` : hint }}
    </span>
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

.num__control--bad,
.num__control--bad:focus-within {
  border-color: var(--bad);
  box-shadow: 0 0 0 3px var(--bad-soft);
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

.field__hint--bad {
  color: var(--bad);
}
</style>
