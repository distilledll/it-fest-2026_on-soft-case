<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import CircleProgress from '@/components/CircleProgress.vue'

type Phase = 'idle' | 'uploading' | 'done'

const phase = ref<Phase>('idle')
const progress = ref(0)
const files = ref<File[]>([])
const dragging = ref(false)
const input = ref<HTMLInputElement | null>(null)

let timer: number | undefined

const sizeLabel = computed(() => {
  const bytes = files.value.reduce((sum, f) => sum + f.size, 0)
  if (!bytes) return ''
  const mb = bytes / 1024 ** 2
  return mb >= 1 ? `${mb.toFixed(1)} МБ` : `${Math.max(1, Math.round(bytes / 1024))} КБ`
})

function pick() {
  input.value?.click()
}

function onFiles(list: FileList | null) {
  if (!list?.length) return
  files.value = [...list]
  start()
}

function start() {
  phase.value = 'uploading'
  progress.value = 0
  clearInterval(timer)
  // Заглушка загрузки: позже — XHR/fetch с progress на POST /api/datasets.
  timer = window.setInterval(() => {
    progress.value = Math.min(100, progress.value + Math.random() * 14 + 4)
    if (progress.value >= 100) {
      clearInterval(timer)
      setTimeout(() => (phase.value = 'done'), 320)
    }
  }, 180)
}

function reset() {
  clearInterval(timer)
  files.value = []
  progress.value = 0
  phase.value = 'idle'
}

onUnmounted(() => clearInterval(timer))
</script>

<template>
  <main class="page">
    <header class="page-head">
      <div>
        <p class="eyebrow">Данные для разбора</p>
        <h1>Загрузка новых данных</h1>
        <p class="lede">
          Архив с закупками: папка <span class="mono">packages</span> с текстовыми файлами,
          при желании <span class="mono">questions.csv</span> и <span class="mono">answers_public.json</span>.
        </p>
      </div>
      <RouterLink class="btn btn--ghost back" :to="{ name: 'dashboard' }">
        <AppIcon name="arrow-right" size="sm" />
        К дашборду
      </RouterLink>
    </header>

    <section class="card card--pad-lg drop reveal" :class="{ 'drop--over': dragging }"
             @dragenter.prevent="dragging = true"
             @dragover.prevent="dragging = true"
             @dragleave.prevent="dragging = false"
             @drop.prevent="dragging = false; onFiles($event.dataTransfer?.files ?? null)"
    >
      <input
        ref="input"
        class="visually-hidden"
        type="file"
        accept=".zip,.txt,.csv,.json"
        multiple
        @change="onFiles(($event.target as HTMLInputElement).files)"
      />

      <template v-if="phase === 'idle'">
        <span class="drop__icon"><AppIcon name="upload" size="lg" /></span>
        <h2 class="drop__title">Перетащите файлы сюда</h2>
        <p class="muted drop__hint">
          Или выберите вручную. Один <span class="mono">.zip</span> от организатора либо несколько
          <span class="mono">.txt</span> одной закупки.
        </p>
        <button class="btn btn--primary" type="button" @click="pick">Обзор</button>
      </template>

      <template v-else-if="phase === 'uploading'">
        <CircleProgress :value="progress" label="Загрузка файлов" />
        <h2 class="drop__title">Загружаем…</h2>
        <p class="muted drop__hint">
          {{ files.length === 1 ? files[0]?.name : `${files.length} файла` }} · {{ sizeLabel }}
        </p>
        <div class="progress drop__bar">
          <div class="progress__bar" :style="{ width: `${progress}%` }" />
        </div>
        <button class="btn btn--ghost" type="button" @click="reset">Отменить</button>
      </template>

      <template v-else>
        <span class="drop__icon drop__icon--ok"><AppIcon name="check" size="lg" /></span>
        <h2 class="drop__title">Данные на месте</h2>
        <p class="muted drop__hint">
          6 закупок, 27 документов, 71 вопрос. Проверки пройдут на следующем шаге.
        </p>
        <div class="btn-row drop__done">
          <RouterLink class="btn btn--primary" :to="{ name: 'dashboard' }">
            Перейти в дашборд
            <AppIcon name="arrow-right" size="sm" />
          </RouterLink>
          <button class="btn" type="button" @click="reset">Загрузить ещё</button>
        </div>
      </template>
    </section>

    <p class="drop__note muted">
      <AppIcon name="alert" size="sm" />
      Файлы остаются на вашем компьютере и уходят только на наш сервер — никуда дальше.
    </p>
  </main>
</template>

<style scoped>
.back .icon {
  rotate: 180deg;
}

.drop {
  display: grid;
  justify-items: center;
  gap: var(--s-3);
  padding: var(--s-8) var(--s-5);
  text-align: center;
  border-style: dashed;
  border-width: 1.5px;
  transition: border-color var(--t) var(--ease), background-color var(--t) var(--ease);
}

.drop--over {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.drop__icon {
  display: grid;
  place-items: center;
  width: 62px;
  height: 62px;
  border-radius: var(--r-md);
  background: var(--accent-soft);
  color: var(--accent);
  animation: float 3.2s var(--ease) infinite;
}

.drop__icon--ok {
  background: var(--ok-soft);
  color: var(--ok);
  animation: none;
}

.drop__title {
  font-size: 19px;
}

.drop__hint {
  font-size: 14px;
  max-width: 46ch;
}

.drop__bar {
  width: min(360px, 100%);
}

.drop__done {
  justify-content: center;
  margin-top: var(--s-2);
}

.drop__note {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-top: var(--s-4);
  font-size: 13px;
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}

@keyframes float {
  0%,
  100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-5px);
  }
}
</style>
