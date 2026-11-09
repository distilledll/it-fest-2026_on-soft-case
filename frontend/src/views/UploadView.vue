<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import CircleProgress from '@/components/CircleProgress.vue'
import { countDocuments, deleteDataset, getDataset, getQuestions, listDatasets, uploadDataset } from '@/api/datasets'
import { ApiError, isCanceled } from '@/api/http'
import { getHealth } from '@/api/system'
import { useDataset } from '@/composables/useDataset'
import { plural } from '@/utils/presentation'
import type { DatasetDetail, DatasetInfo, HealthInfo } from '@/types'

type Phase = 'idle' | 'ready' | 'sending' | 'checking' | 'done'

const phase = ref<Phase>('idle')
const progress = ref(0)
const files = ref<File[]>([])
const dragging = ref(false)
const input = ref<HTMLInputElement | null>(null)
const datasetName = ref('')
const packageCode = ref('P01')
const problem = ref('')
const note = ref('')
const dataset = ref<DatasetInfo | null>(null)
const detail = ref<DatasetDetail | null>(null)
const questionCount = ref(0)
const health = ref<HealthInfo | null>(null)
const offline = ref(false)

const { active, setActive, clear } = useDataset()

const uploaded = ref<DatasetInfo[]>([])
const removing = ref('')

async function refreshList() {
  try {
    uploaded.value = await listDatasets()
  } catch {
    uploaded.value = []
  }
}

async function removeDataset(d: DatasetInfo) {
  removing.value = d.id
  problem.value = ''
  try {
    await deleteDataset(d.id)
    if (active.value?.id === d.id) clear()
    if (dataset.value?.id === d.id) reset()
  } catch (e) {
    fail(reason(e))
  } finally {
    removing.value = ''
    await refreshList()
  }
}

let controller: AbortController | null = null

const isZip = (f?: File) => !!f && f.name.toLowerCase().endsWith('.zip')
const oneZip = computed(() => files.value.length === 1 && isZip(files.value[0]))
const looseTxt = computed(() => files.value.length > 0 && !oneZip.value)

const sizeLabel = computed(() => {
  const bytes = files.value.reduce((sum, f) => sum + f.size, 0)
  if (!bytes) return ''
  const mb = bytes / 1024 ** 2
  return mb >= 1 ? `${mb.toFixed(1)} МБ` : `${Math.max(1, Math.round(bytes / 1024))} КБ`
})

const filesLabel = computed(() =>
  files.value.length === 1 ? (files.value[0]?.name ?? '') : plural(files.value.length, ['файл', 'файла', 'файлов']),
)

const docCount = computed(() => (detail.value ? countDocuments(detail.value) : null))
const emptyDocs = computed(() =>
  detail.value
    ? Object.values(detail.value.files)
        .flat()
        .filter((d) => d.is_empty).length
    : 0,
)

function fail(message: string) {
  problem.value = message
}

function reason(e: unknown): string {
  if (e instanceof ApiError) return e.status === 413 ? 'Файл больше разрешённого размера.' : e.message
  return 'Не получилось связаться с сервером.'
}

function onFiles(list: FileList | null) {
  const picked = [...(list ?? [])]
  if (!picked.length) return
  if (picked.some(isZip) && picked.length > 1) {
    return fail('Архив передают один — уберите остальные файлы или распакуйте его.')
  }
  if (picked.some((f) => !isZip(f) && !f.name.toLowerCase().endsWith('.txt'))) {
    return fail('Отдельно принимаем только .txt. questions.csv и answers_public.json кладите внутрь архива.')
  }
  problem.value = ''
  note.value = ''
  files.value = picked
  phase.value = 'ready'
  if (input.value) input.value.value = ''
}

function pick() {
  input.value?.click()
}

async function start() {
  if (!files.value.length) return
  problem.value = ''
  note.value = ''
  progress.value = 0
  phase.value = 'sending'
  controller = new AbortController()
  try {
    const saved = await uploadDataset({
      files: files.value,
      name: datasetName.value.trim(),
      packageCode: packageCode.value.trim() || 'P01',
      signal: controller.signal,
      onProgress: (p) => {
        if (p.total) progress.value = Math.min(100, (p.sent / p.total) * 100)
        if (p.sent_all) phase.value = 'checking'
      },
    })
    dataset.value = saved
    detail.value = null
    questionCount.value = 0
    setActive(saved)
    phase.value = 'done'
    void loadStats(saved)
    void refreshList()
  } catch (e) {
    phase.value = 'ready'
    if (isCanceled(e)) note.value = 'Загрузка отменена — можно отправить эти же файлы заново.'
    else problem.value = reason(e)
  } finally {
    controller = null
  }
}

/** Документов и вопросов в датасете — из тех же эндпоинтов, что читает дашборд. */
async function loadStats(saved: DatasetInfo) {
  try {
    detail.value = await getDataset(saved.id)
    questionCount.value = saved.has_questions ? (await getQuestions(saved.id)).length : 0
  } catch {
    fail('Датасет на сервере, но посчитать документы не вышло — обновите страницу.')
  }
}

function cancel() {
  controller?.abort()
}

function reset() {
  controller?.abort()
  controller = null
  files.value = []
  progress.value = 0
  problem.value = ''
  note.value = ''
  dataset.value = null
  detail.value = null
  questionCount.value = 0
  phase.value = 'idle'
}

onMounted(async () => {
  void refreshList()
  try {
    health.value = await getHealth()
  } catch {
    offline.value = true
  }
})

onUnmounted(() => controller?.abort())
</script>

<template>
  <main class="page">
    <header class="page-head">
      <div>
        <p class="eyebrow">Данные для разбора</p>
        <h1>Загрузка новых данных</h1>
        <p class="lede">
          Архив с закупками: папка <span class="mono">packages</span> с текстовыми файлами, при
          желании <span class="mono">questions.csv</span> и
          <span class="mono">answers_public.json</span>.
        </p>
      </div>
    </header>

    <section
      class="card card--pad-lg drop reveal"
      :class="{ 'drop--over': dragging }"
      @dragenter.prevent="dragging = true"
      @dragover.prevent="dragging = true"
      @dragleave.prevent="dragging = false"
      @drop.prevent="((dragging = false), onFiles($event.dataTransfer?.files ?? null))"
    >
      <input
        ref="input"
        class="visually-hidden"
        type="file"
        accept=".zip,.txt"
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

      <template v-else-if="phase === 'ready'">
        <span class="drop__icon"><AppIcon name="file" size="lg" /></span>
        <h2 class="drop__title">{{ filesLabel }}</h2>
        <p class="muted drop__hint">Готово к отправке · {{ sizeLabel }}</p>

        <div class="opts">
          <label class="field">
            <span class="field__label">Название датасета</span>
            <input v-model="datasetName" class="input" type="text" placeholder="Например: контроль-2026" />
            <span class="field__hint">Пусто — возьмём имя архива.</span>
          </label>
          <label v-if="looseTxt" class="field">
            <span class="field__label">Код закупки</span>
            <input v-model="packageCode" class="input" type="text" placeholder="P01" spellcheck="false" />
            <span class="field__hint">Файлы лягут в <span class="mono">packages/{{ packageCode || 'P01' }}</span>.</span>
          </label>
        </div>

        <div class="btn-row drop__done">
          <button class="btn btn--primary" type="button" @click="start">Загрузить на сервер</button>
          <button class="btn btn--ghost" type="button" @click="reset">Другие файлы</button>
        </div>
      </template>

      <template v-else-if="phase === 'sending' || phase === 'checking'">
        <CircleProgress :value="phase === 'checking' ? 100 : Math.round(progress)" label="Загрузка файлов" />
        <h2 class="drop__title">
          {{ phase === 'sending' ? 'Отправляем файлы…' : 'Сервер распаковывает и проверяет…' }}
        </h2>
        <p class="muted drop__hint">
          {{ filesLabel }} · {{ sizeLabel }}
        </p>
        <div class="progress drop__bar">
          <div class="progress__bar" :style="{ width: `${Math.round(progress)}%` }" />
        </div>
        <button v-if="phase === 'sending'" class="btn btn--ghost" type="button" @click="cancel">
          Отменить
        </button>
      </template>

      <template v-else>
        <span class="drop__icon drop__icon--ok"><AppIcon name="check" size="lg" /></span>
        <h2 class="drop__title">Данные на сервере</h2>
        <p class="muted drop__hint">
          {{ dataset?.name }} · <span class="mono">{{ dataset?.id }}</span>
        </p>

        <div class="stats">
          <p class="stat">
            <b>{{ dataset ? plural(dataset.packages.length, ['закупка', 'закупки', 'закупок']) : '—' }}</b>
            <span>в датасете</span>
          </p>
          <p class="stat">
            <b>{{ docCount === null ? '…' : plural(docCount, ['документ', 'документа', 'документов']) }}</b>
            <span>текстовых файлов</span>
          </p>
          <p class="stat">
            <b>{{
              dataset?.has_questions
                ? plural(questionCount, ['вопрос', 'вопроса', 'вопросов'])
                : 'нет'
            }}</b>
            <span>questions.csv</span>
          </p>
        </div>

        <p class="badges">
          <span class="badge" :class="dataset?.has_gold ? 'badge--ok' : ''">
            {{ dataset?.has_gold ? 'есть эталонные ответы' : 'эталонных ответов нет' }}
          </span>
          <span v-if="emptyDocs" class="badge badge--warn">{{ plural(emptyDocs, ['пустой файл', 'пустых файла', 'пустых файлов']) }}</span>
        </p>

        <div class="btn-row drop__done">
          <RouterLink
            v-if="dataset?.has_questions"
            class="btn btn--primary"
            :to="{ name: 'dashboard', query: { start: '1', dataset: dataset.id } }"
          >
            Запустить прогон
            <AppIcon name="arrow-right" size="sm" />
          </RouterLink>
          <RouterLink class="btn" :class="{ 'btn--primary': !dataset?.has_questions }" :to="{ name: 'dashboard' }">
            Перейти в дашборд
          </RouterLink>
          <button class="btn btn--ghost" type="button" @click="reset">Загрузить ещё</button>
        </div>
      </template>

      <p v-if="problem" class="msg msg--bad"><AppIcon name="alert" size="sm" /> {{ problem }}</p>
      <p v-else-if="note" class="msg">{{ note }}</p>
    </section>

    <section v-if="uploaded.length" class="card card--pad library reveal">
      <div class="library__head">
        <h2 class="card__title">Уже на сервере</h2>
        <p class="muted">Текущий набор подставляется в дашборд и в живой вопрос.</p>
      </div>
      <ul class="lib">
        <li
          v-for="d in uploaded"
          :key="d.id"
          class="lib__row"
          :class="{ 'is-current': d.id === active?.id }"
        >
          <div class="lib__name">
            <p class="lib__title">
              {{ d.name }}
              <span v-if="d.id === active?.id" class="badge badge--ok">текущий</span>
            </p>
            <p class="muted lib__sub">
              <span class="mono">{{ d.id }}</span> ·
              {{ plural(d.packages.length, ['закупка', 'закупки', 'закупок']) }}
              <span class="mono">{{ d.packages.slice(0, 4).join(', ') }}{{ d.packages.length > 4 ? '…' : '' }}</span>
            </p>
          </div>
          <p class="lib__flags">
            <span v-if="d.has_questions" class="badge badge--info">вопросы</span>
            <span v-if="d.has_gold" class="badge badge--ok">эталон</span>
          </p>
          <div class="lib__acts">
            <button
              class="btn btn--ghost btn--sm"
              type="button"
              :disabled="d.id === active?.id"
              @click="setActive(d)"
            >
              Сделать текущим
            </button>
            <button
              class="btn btn--ghost btn--sm btn--danger"
              type="button"
              :disabled="removing === d.id"
              @click="removeDataset(d)"
            >
              {{ removing === d.id ? 'Удаляем…' : 'Удалить' }}
            </button>
          </div>
        </li>
      </ul>
    </section>

    <p class="drop__note muted">
      <AppIcon name="alert" size="sm" />
      Файлы остаются на вашем компьютере и уходят только на наш сервер — никуда дальше.
    </p>

    <p class="status">
      <span
        class="status__dot"
        :class="health ? 'status__dot--ok' : offline ? 'status__dot--bad' : ''"
      />
      <template v-if="health">
        сервер на связи · режим: <span class="mono">{{ health.default_pipeline }}</span> · доступны:
        <span class="mono">{{ health.pipelines.map((p) => p.name).join(' · ') }}</span>
      </template>
      <template v-else-if="offline">бэкенд не отвечает — поднимите <span class="mono">uvicorn app.main:app</span></template>
      <template v-else>проверяем связь с сервером…</template>
    </p>
  </main>
</template>

<style scoped>
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

.opts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: var(--s-4);
  width: min(560px, 100%);
  text-align: start;
}

.stats {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--s-6);
}

.stat {
  display: grid;
  gap: 2px;
}

.stat b {
  font-size: 19px;
  font-variant-numeric: tabular-nums;
}

.stat span {
  font-size: 12.5px;
  color: var(--text-muted);
}

.badges {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--s-2);
}

.msg {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13.5px;
  color: var(--text-muted);
}

.msg--bad {
  color: var(--bad);
}

.drop__note {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-top: var(--s-4);
  font-size: 13px;
}

.status {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-top: var(--s-2);
  font-size: 12.5px;
  color: var(--text-faint);
}

.status__dot {
  width: 7px;
  height: 7px;
  flex: none;
  border-radius: 50%;
  background: var(--text-faint);
}

.status__dot--ok {
  background: var(--ok);
}

.status__dot--bad {
  background: var(--bad);
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}

.library {
  margin-top: var(--s-6);
  display: grid;
  gap: var(--s-4);
}

.library__head {
  display: grid;
  gap: 2px;
}

.lib {
  display: grid;
  gap: var(--s-2);
  list-style: none;
}

.lib__row {
  display: grid;
  align-items: center;
  gap: var(--s-3);
  padding: var(--s-3) var(--s-4);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  background: var(--surface-inset);
}

.lib__row.is-current {
  border-color: var(--accent-line);
  background: var(--accent-soft);
}

.lib__title {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  font-weight: 600;
}

.lib__sub {
  font-size: 12.5px;
}

.lib__flags {
  display: flex;
  gap: var(--s-2);
}

.lib__acts {
  display: flex;
  justify-content: flex-end;
  gap: var(--s-2);
}

@media (min-width: 760px) {
  .lib__row {
    grid-template-columns: 1fr auto auto;
  }
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
