<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import { mockAnswer, mockTrace } from '@/api/mock'
import { useAskModal } from '@/composables/useAskModal'
import type { Answer, TraceStep } from '@/types'
import { statusMeta } from '@/utils/presentation'

const { open, hide } = useAskModal()

const packageId = ref('P01')
const question = ref('')
const asking = ref(false)
const answer = ref<Answer | null>(null)
const steps = ref<TraceStep[]>([])

let timers: number[] = []

function clearTimers() {
  timers.forEach(clearTimeout)
  timers = []
}

function ask() {
  if (asking.value || question.value.trim().length < 3) return
  asking.value = true
  answer.value = null
  steps.value = []
  clearTimers()
  // Заглушка: позже — POST /api/ask/stream (SSE), шаги приходят событием `step`.
  mockTrace.forEach((step, i) => {
    timers.push(window.setTimeout(() => steps.value.push(step), 420 * (i + 1)))
  })
  timers.push(
    window.setTimeout(() => {
      answer.value = { ...mockAnswer, id: 'adhoc' }
      asking.value = false
    }, 420 * (mockTrace.length + 1)),
  )
}

function close() {
  clearTimers()
  asking.value = false
  hide()
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && open.value) close()
}

watch(open, (v) => {
  document.body.style.overflow = v ? 'hidden' : ''
  if (v) {
    window.addEventListener('keydown', onKey)
  } else {
    window.removeEventListener('keydown', onKey)
    clearTimers()
    asking.value = false
    steps.value = []
    answer.value = null
    question.value = ''
  }
})

onUnmounted(() => {
  document.body.style.overflow = ''
  window.removeEventListener('keydown', onKey)
  clearTimers()
})
</script>

<template>
  <transition name="scale-fade">
    <div v-if="open" class="modal-backdrop" @click.self="close">
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="ask-title">
        <button class="icon-btn modal__close" type="button" aria-label="Закрыть" @click="close">
          <AppIcon name="close" />
        </button>

        <header class="modal__head">
          <p class="eyebrow">Живой вопрос</p>
          <h2 id="ask-title">Спросить напрямую</h2>
          <p class="muted">
            Не только вопросы из набора: можно спросить своими словами, как это сделает жюри на защите.
          </p>
        </header>

        <form class="ask" @submit.prevent="ask">
          <div class="ask__row">
            <label class="field ask__package">
              <span class="field__label">Закупка</span>
              <select v-model="packageId" class="select">
                <option v-for="p in ['P01', 'P02', 'P03', 'P04', 'P05', 'P06']" :key="p" :value="p">
                  {{ p }}
                </option>
              </select>
            </label>
            <label class="field ask__text">
              <span class="field__label">Вопрос</span>
              <textarea
                v-model="question"
                class="textarea"
                rows="2"
                placeholder="Какой размер обеспечения заявки, в рублях?"
              />
            </label>
          </div>

          <div class="ask__actions">
            <button class="btn btn--primary" type="submit" :disabled="asking || question.trim().length < 3">
              <span v-if="asking" class="ask__spin" />
              <AppIcon v-else name="message" size="sm" />
              {{ asking ? 'Ищем ответ в документах…' : 'Спросить' }}
            </button>
          </div>
        </form>

        <transition name="fade-slide">
          <ol v-if="steps.length" class="trace" aria-label="Что делала система">
            <li v-for="(s, i) in steps" :key="`${s.node}-${i}`" class="trace__item" :class="s.ok === false ? 'is-bad' : s.ok ? 'is-ok' : ''">
              <span class="trace__dot">
                <AppIcon :name="s.ok === false ? 'close' : 'check'" size="sm" />
              </span>
              <span class="trace__node mono">{{ s.node }}</span>
              <span class="trace__msg">{{ s.message }}</span>
            </li>
          </ol>
        </transition>

        <transition name="fade-slide">
          <div v-if="answer" class="answer">
            <div class="answer__head">
              <span class="badge" :class="statusMeta[answer.status].cls">
                {{ statusMeta[answer.status].label }}
              </span>
              <span class="answer__time muted">{{ answer.elapsed_s }} с · {{ answer.llm_calls }} запроса</span>
            </div>
            <p class="answer__value">{{ answer.answer }}</p>
            <blockquote class="answer__quote">
              «{{ answer.quote }}»
              <cite class="answer__file mono">{{ packageId }}/{{ answer.file }}</cite>
            </blockquote>
          </div>
        </transition>

        <footer class="modal__foot">
          <button class="btn btn--ghost" type="button" @click="close">Закрыть</button>
        </footer>
      </div>
    </div>
  </transition>
</template>

<style scoped>
.ask {
  display: grid;
  gap: var(--s-4);
}

.ask__row {
  display: grid;
  gap: var(--s-3);
  align-items: end;
}

.ask__package {
  max-width: 140px;
}

.ask__actions {
  display: flex;
  justify-content: flex-end;
}

.ask__spin {
  width: 15px;
  height: 15px;
  border-radius: 50%;
  border: 2px solid color-mix(in srgb, var(--on-accent) 40%, transparent);
  border-top-color: var(--on-accent);
  animation: spin 800ms linear infinite;
}

.trace {
  display: grid;
  gap: var(--s-2);
  margin: var(--s-5) 0 0;
  padding: var(--s-4);
  list-style: none;
  background: var(--surface-inset);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
}

.trace__item {
  display: grid;
  grid-template-columns: 20px 128px 1fr;
  align-items: center;
  gap: var(--s-2);
  font-size: 13.5px;
  animation: step-in var(--t) var(--ease-out) both;
}

.trace__dot {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--surface-3);
  color: var(--text-faint);
}

.trace__item.is-ok .trace__dot {
  background: var(--ok-soft);
  color: var(--ok);
}

.trace__item.is-bad .trace__dot {
  background: var(--bad-soft);
  color: var(--bad);
}

.trace__node {
  color: var(--text-muted);
}

.trace__item.is-bad .trace__msg {
  color: var(--bad);
}

.answer {
  margin-top: var(--s-5);
  padding: var(--s-4);
  border: 1px solid var(--accent-line);
  border-radius: var(--r-sm);
  background: var(--accent-soft);
}

.answer__head {
  display: flex;
  align-items: center;
  gap: var(--s-3);
}

.answer__time {
  font-size: 12.5px;
}

.answer__value {
  margin-top: var(--s-3);
  font-size: 26px;
  font-weight: 660;
  letter-spacing: -0.02em;
}

.answer__quote {
  position: relative;
  margin: var(--s-3) 0 0;
  padding-inline-start: var(--s-3);
  border-inline-start: 2px solid var(--accent-line);
  color: var(--text-muted);
  font-size: 14px;
}

.answer__file {
  display: block;
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-faint);
  font-style: normal;
}

@keyframes step-in {
  from {
    opacity: 0;
    transform: translateX(-6px);
  }
}

@media (min-width: 620px) {
  .ask__row {
    grid-template-columns: 140px 1fr;
  }

  .ask__package {
    max-width: none;
  }
}
</style>
