<script setup lang="ts">
import { computed } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import type { IconName } from '@/types'

defineProps<{
  title: string
  subtitle?: string
  icon: IconName
  badge?: string
  badgeCls?: string
}>()

const open = defineModel<boolean>({ default: false })

const cls = computed(() => ['acc', open.value ? 'acc--open' : ''])
</script>

<template>
  <div :class="cls">
    <button class="acc__head" type="button" :aria-expanded="open" @click="open = !open">
      <span class="acc__icon"><AppIcon :name="icon" /></span>
      <span class="acc__titles">
        <span class="acc__title">{{ title }}</span>
        <span v-if="subtitle" class="acc__sub">{{ subtitle }}</span>
      </span>
      <span v-if="badge" class="badge" :class="badgeCls">{{ badge }}</span>
      <AppIcon class="acc__chevron" name="chevron" />
    </button>

    <div class="acc__body">
      <div class="acc__inner">
        <div class="acc__content">
          <slot />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.acc {
  border-radius: var(--r-sm);
  transition: background-color var(--t) var(--ease);
}

.acc--open {
  background: var(--surface-2);
}

.acc__head {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  width: 100%;
  padding: var(--s-4);
  background: none;
  border: none;
  border-radius: var(--r-sm);
  text-align: start;
  cursor: pointer;
  transition: background-color var(--t-fast) var(--ease);
}

.acc__head:hover {
  background: var(--surface-3);
}

.acc__icon {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex: none;
  border-radius: var(--r-xs);
  background: var(--accent-soft);
  color: var(--accent);
}

.acc__titles {
  display: grid;
  gap: 1px;
  margin-inline-end: auto;
  min-width: 0;
}

.acc__title {
  font-weight: 600;
}

.acc__sub {
  font-size: 12.5px;
  color: var(--text-faint);
}

.acc__chevron {
  color: var(--text-faint);
  transition: rotate var(--t) var(--ease), color var(--t) var(--ease);
}

.acc--open .acc__chevron {
  rotate: 180deg;
  color: var(--accent);
}

/* Плавное раскрытие без замера высоты: 0fr -> 1fr. */
.acc__body {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows var(--t-slow) var(--ease-out);
}

.acc--open .acc__body {
  grid-template-rows: 1fr;
}

.acc__inner {
  overflow: hidden;
}

.acc__content {
  padding: 0 var(--s-4) var(--s-5) calc(var(--s-4) + 34px + var(--s-3));
  opacity: 0;
  transform: translateY(-6px);
  transition: opacity var(--t) var(--ease) 60ms, transform var(--t) var(--ease) 60ms;
}

.acc--open .acc__content {
  opacity: 1;
  transform: none;
}

@media (max-width: 640px) {
  .acc__content {
    padding-inline-start: var(--s-4);
  }
}
</style>
