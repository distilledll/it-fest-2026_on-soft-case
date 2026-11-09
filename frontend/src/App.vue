<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import AskModal from '@/components/AskModal.vue'
import HelpTooltip from '@/components/HelpTooltip.vue'
import { useTheme } from '@/composables/useTheme'

const route = useRoute()
const router = useRouter()
const { theme, toggle } = useTheme()

const bare = computed(() => route.meta.bare === true)

/** Назад по истории; если history пуст (глубокая ссылка) — на главную. */
function goBack(): void {
  if (window.history.state?.back) router.back()
  else void router.push({ name: 'home' })
}
</script>

<template>
  <div class="app">
    <router-view v-slot="{ Component }">
      <transition name="fade-slide" mode="out-in">
        <component :is="Component" />
      </transition>
    </router-view>

    <div class="dock dock--top">
      <!-- Кнопку «Задать вопрос» вернём, когда модалку будет чем открыть из интерфейса. -->
      <button
        class="icon-btn"
        type="button"
        :aria-label="theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'"
        @click="toggle()"
      >
        <AppIcon :name="theme === 'dark' ? 'sun' : 'moon'" />
      </button>
      <HelpTooltip v-if="!bare" />
    </div>

    <button v-if="!bare" class="dock dock--back" type="button" aria-label="Назад" title="Назад" @click="goBack">
      <AppIcon name="arrow-right" />
    </button>

    <RouterLink v-if="!bare" class="dock dock--gear" to="/settings" title="Настройки">
      <AppIcon name="settings" />
      <span class="dock__gear-label">Настройки</span>
    </RouterLink>

    <AskModal />
  </div>
</template>

<style scoped>
.app {
  min-height: 100%;
  display: flex;
  flex-direction: column;
}

.app > :first-child {
  flex: 1;
}

.dock {
  position: fixed;
  z-index: 50;
  display: flex;
  align-items: center;
  gap: var(--s-1);
  padding: 6px;
  background: color-mix(in srgb, var(--surface) 82%, transparent);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  box-shadow: var(--shadow-2);
  backdrop-filter: blur(10px);
  animation: dock-in var(--t-slow) var(--ease-out) both 120ms;
}

.dock--top {
  top: var(--s-4);
  inset-inline-end: var(--s-4);
}

/* Стрелка «назад» в левом верхнем углу — одна на все страницы. */
.dock--back {
  top: var(--s-4);
  inset-inline-start: var(--s-4);
  color: var(--text-muted);
  cursor: pointer;
  transition: color var(--t) var(--ease), border-color var(--t) var(--ease);
}

.dock--back:hover {
  color: var(--accent);
  border-color: var(--accent-line);
}

.dock--back .icon {
  rotate: 180deg;
}

.dock .icon-btn {
  border-radius: var(--r-xs);
}

/* Шестерёнка внизу слева: подпись раскрывается при наведении. */
.dock--gear {
  bottom: var(--s-4);
  inset-inline-start: var(--s-4);
  gap: 0;
  padding: 0 8px;
  height: 36px;
  color: var(--text-muted);
  text-decoration: none;
  transition: color var(--t) var(--ease), border-color var(--t) var(--ease);
}

.dock--gear:hover {
  color: var(--accent);
  border-color: var(--accent-line);
}

.dock__gear-label {
  max-width: 0;
  overflow: hidden;
  white-space: nowrap;
  font-size: 14px;
  font-weight: 560;
  opacity: 0;
  transition: max-width var(--t) var(--ease), opacity var(--t) var(--ease),
    margin-inline-start var(--t) var(--ease);
}

.dock--gear:hover .dock__gear-label,
.dock--gear:focus-visible .dock__gear-label {
  max-width: 120px;
  opacity: 1;
  margin-inline-start: var(--s-2);
}

.dock--gear .icon {
  transition: rotate var(--t-slow) var(--ease);
}

.dock--gear:hover .icon {
  rotate: 60deg;
}

@keyframes dock-in {
  from {
    opacity: 0;
    transform: translateY(-8px);
  }
}
</style>
