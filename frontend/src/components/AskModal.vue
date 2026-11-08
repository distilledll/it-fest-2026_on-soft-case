<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import { askStream } from '@/api/ask'
import { listDatasets } from '@/api/datasets'
import { ApiError, isCanceled } from '@/api/http'
import { useAskModal } from '@/composables/useAskModal'
import { useDataset } from '@/composables/useDataset'
import type { Answer, DatasetInfo, TraceStep } from '@/types'
import { plural, statusMeta } from '@/utils/presentation'

const { open, preset, hide } = useAskModal()
const { active } = useDataset()

const datasets = ref<DatasetInfo[]>([])
const datasetId = ref('')
const packageId = ref('')
const question = ref('')
const asking = ref(false)
const answer = ref<Answer | null>(null)
const steps = ref<TraceStep[]>([])
const error = ref('')

let controller: AbortController | null = null

const packages = computed(() => datasets.value.find((d) => d.id === datasetId.value)?.packages ?? [])
const canAsk = computed(() => !asking.value && !!datasetId.value && !!packageId.value && question.value.trim().length >= 3)

function stop() {
  controller?.abort()
  controller = null
}

function reset() {
  stop()
  asking.value = false
  steps.value = []
  answer.value = null
  error.value = ''
}

async function ask() {
  if (!canAsk.value) return
  asking.value = true
  answer.value = null
  steps.value = []
  error.value = ''
  controller = new AbortController()
  try {
    await askStream(
      { dataset: datasetId.value, package: packageId.value, question: question.value.trim(), guard: true },
      {
        onStep: (s) => steps.value.push(s),
        onAnswer: (a) => {
          answer.value = a
        },
      },
      controller.signal,
    )
  } catch (e) {
    if (e instanceof ApiError) {
      if (!isCanceled(e)) error.value = e.message
    } else {
      error.value = 'Не удалось спросить — сервер не отвечает'
    }
  } finally {
    asking.value = false
    controller = null
  }
}

function close() {
  reset()
  hide()
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && open.value) close()
}

watch(datasetId, () => {
  if (!packages.value.includes(packageId.value)) packageId.value = packages.value[0] ?? ''
})

watch(open, async (v) => {
  document.body.style.overflow = v ? 'hidden' : ''
  if (v) {
    window.addEventListener('keydown', onKey)
    reset()
    question.value = preset.value
    try {
      datasets.value = await listDatasets()
    } catch {
      datasets.value = []
    }
    const prefer = active.value && datasets.value.some((d) => d.id === active.value?.id) ? active.value.id : (datasets.value[0]?.id ?? '')
    datasetId.value = prefer
    if (!packages.value.includes(packageId.value)) packageId.value = packages.value[0] ?? ''
  } else {
    window.removeEventListener('keydown', onKey)
    reset()
    question.value = ''
  }
})

onUnmounted(() => {
  document.body.style.overflow = ''
  window.removeEventListener('keydown', onKey)
  stop()
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

        <p v-if="!datasets.length" class="callout callout--warn">
          Ни одного датасета на сервере нет — сначала загрузите архив на странице «Загрузка».
        </p>

        <form class="ask" @submit.prevent="ask">
          <div class="ask__row">
            <label class="field ask__pick">
              <span class="field__label">Набор</span>
              <select v-model="datasetId" class="select">
                <option v-for="d in datasets" :key="d.id" :value="d.id">{{ d.name }}</option>
              </select>
            </label>
            <label class="field ask__pick">
              <span class="field__label">Закупка</span>
              <select v-model="packageId" class="select">
                <option v-for="p in packages" :key="p" :value="p">{{ p }}</option>
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
            <button class="btn btn--primary" type="submit" :disabled="!canAsk">
              <span v-if="asking" class="ask__spin" />
              <AppIcon v-else name="message" size="sm" />
              {{ asking ? 'Ищем ответ в документах…' : 'Спросить' }}
            </button>
          </div>
        </form>

        <p v-if="error" class="callout callout--bad">{{ error }}</p>

        <transition name="fade-slide">
          <ol v-if="steps.length" class="trace" aria-label="Что делала система">
            <li
              v-for="(s, i) in steps"
              :key="`${s.node}-${i}`"
              class="trace__item"
              :class="s.ok === false ? 'is-bad' : s.ok ? 'is-ok' : ''"
            >
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
              <span class="answer__time muted">
                {{ answer.elapsed_s.toFixed(2) }} с · {{ plural(answer.llm_calls, ['обращение', 'обращения', 'обращений']) }} к модели
              </span>
            </div>
            <p class="answer__value">{{ answer.answer }}</p>
            <blockquote v-if="answer.quote" class="answer__quote">
              «{{ answer.quote }}»
              <cite v-if="answer.file" class="answer__file mono">{{ packageId }}/{{ answer.file }}</cite>
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

.ask__pick {
  max-width: 200px;
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
    grid-template-columns: 1fr 140px 1.6fr;
  }

  .ask__pick {
    max-width: none;
  }
}
</style>
