<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import AccordionItem from '@/components/AccordionItem.vue'
import AppIcon from '@/components/AppIcon.vue'
import NumberField from '@/components/NumberField.vue'
import {
  createProfile,
  deleteProfile,
  listModels,
  patchProfile,
  remoteModels,
  setRoles,
  testProfile,
} from '@/api/models'
import { ApiError } from '@/api/http'
import type { ModelProfilePublic, ProfilePatch, ProfileTest, RoleMap, RoleName } from '@/types'

const profiles = ref<ModelProfilePublic[]>([])
const roles = ref<RoleMap>({})
const roleNames = ref<RoleName[]>(['answer', 'critic', 'embed', 'rerank'])
const loading = ref(true)
const error = ref('')
const note = ref('')
const open = ref<Record<string, boolean>>({})

const ROLE_LABEL: Record<RoleName, string> = {
  answer: 'ответ',
  critic: 'критик',
  embed: 'эмбеддинги',
  rerank: 'реранк',
}

const ROLE_HINT: Record<RoleName, string> = {
  answer: 'модель, которая отвечает на вопрос',
  critic: 'критик-модель и перепроверка ответа',
  embed: 'эмбеддинги для поиска фрагментов (POST /embeddings)',
  rerank: 'модельная пересортировка фрагментов (опция пайплайна rerank)',
}

/** Черновик правок профиля: сравнением с сервером решаем, что отправи́ть. */
interface Draft {
  name: string
  baseUrl: string
  model: string
  apiKey: string
  clearKey: boolean
  keyEnv: string
  headers: string
  temperature: number
  maxTokens: number | null
  concurrency: number
  contextWindow: number
  noThinking: boolean
  jsonMode: boolean
  reasoning: string
}

const openTypes = reactive({ llm: true, embed: false, rerank: false })
const draftOpen = ref(false)

/** Черновик новой embedding-модели; протокол шлюза добавляет к запросу нестандартные поля task. */
const embedDraft = reactive({
  name: '',
  baseUrl: '',
  model: '',
  apiKey: '',
  protocol: 'gateway' as 'gateway' | 'openai',
  queryTask: 'retrieval.query',
  passageTask: 'retrieval.passage',
  dimensions: 256,
})

const boundName = (role: RoleName) => {
  const p = profiles.value.find((x) => x.id === roles.value[role])
  return p ? `${p.name} · ${p.model}` : ''
}

/** Чат-модели отвечают и проверяют, embedding-модели — векторы; бэкенд не даёт mixes путать (422 по kind). */
const chatProfiles = computed(() => profiles.value.filter((p) => p.kind !== 'embedding'))
const embedProfiles = computed(() => profiles.value.filter((p) => p.kind === 'embedding'))

const drafts = reactive<Record<string, Draft>>({})

const asDraft = (p: ModelProfilePublic): Draft => ({
  name: p.name,
  baseUrl: p.base_url,
  model: p.model,
  apiKey: '',
  clearKey: false,
  keyEnv: p.api_key_env,
  headers: p.extra_headers,
  temperature: p.temperature,
  maxTokens: p.max_tokens,
  concurrency: p.concurrency,
  contextWindow: p.context_window,
  noThinking: p.disable_thinking,
  jsonMode: p.json_mode,
  reasoning: p.reasoning_effort ?? '',
})

function patchOf(p: ModelProfilePublic): ProfilePatch {
  const d = drafts[p.id]
  if (!d) return {}
  const out: ProfilePatch = {}
  if (d.name.trim() !== p.name) out.name = d.name.trim()
  if (d.baseUrl.trim() !== p.base_url) out.base_url = d.baseUrl.trim()
  if (d.model.trim() !== p.model) out.model = d.model.trim()
  if (d.keyEnv.trim() !== p.api_key_env) out.api_key_env = d.keyEnv.trim()
  if (d.headers !== p.extra_headers) out.extra_headers = d.headers
  if (d.temperature !== p.temperature) out.temperature = d.temperature
  if (d.maxTokens !== p.max_tokens) out.max_tokens = d.maxTokens
  if (d.concurrency !== p.concurrency) out.concurrency = d.concurrency
  if (d.contextWindow !== p.context_window) out.context_window = d.contextWindow
  if (d.noThinking !== p.disable_thinking) out.disable_thinking = d.noThinking
  if (d.jsonMode !== p.json_mode) out.json_mode = d.jsonMode
  if (d.reasoning.trim() !== (p.reasoning_effort ?? '')) out.reasoning_effort = d.reasoning.trim()
  // пустая строка ключа на бэкенде означает «стереть сохранённый ключ»
  if (d.clearKey) out.api_key = ''
  else if (d.apiKey) out.api_key = d.apiKey
  return out
}

const isDirty = (p: ModelProfilePublic) => Object.keys(patchOf(p)).length > 0

const saving = ref('')
const results = reactive<Record<string, ProfileTest | 'pending'>>({})
const remote = reactive<Record<string, string[] | 'loading' | string>>({})
const toDelete = ref('')

const creating = ref(false)
const creatingEmbed = ref(false)
interface Fresh extends Draft {
  name: string
  baseUrl: string
  model: string
  apiKey: string
}
const FRESH_DEFAULTS: Fresh = {
  name: '',
  baseUrl: '',
  model: '',
  apiKey: '',
  clearKey: false,
  keyEnv: '',
  headers: '',
  temperature: 0,
  maxTokens: null,
  concurrency: 4,
  contextWindow: 32768,
  noThinking: false,
  jsonMode: true,
  reasoning: '',
}
const fresh = reactive<Fresh>({ ...FRESH_DEFAULTS })
const canCreate = computed(
  () => !!fresh.name.trim() && !!fresh.baseUrl.trim() && !!fresh.model.trim() && !creating.value,
)

const reason = (e: unknown) => (e instanceof ApiError ? e.message : 'сервер не отвечает')
const hostOf = (url: string) => {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

async function load() {
  loading.value = true
  try {
    const reg = await listModels()
    profiles.value = reg.profiles
    roles.value = reg.roles
    if (reg.role_names?.length) roleNames.value = reg.role_names
    for (const p of reg.profiles) if (!drafts[p.id]) drafts[p.id] = asDraft(p)
    error.value = ''
  } catch (e) {
    error.value = reason(e)
  } finally {
    loading.value = false
  }
}

async function save(p: ModelProfilePublic) {
  const body = patchOf(p)
  if (!Object.keys(body).length) return
  saving.value = p.id
  try {
    const next = await patchProfile(p.id, body)
    profiles.value = profiles.value.map((x) => (x.id === p.id ? next : x))
    drafts[p.id] = asDraft(next)
    note.value = `Модель «${next.name}» сохранена`
    error.value = ''
  } catch (e) {
    note.value = ''
    error.value = reason(e)
  } finally {
    saving.value = ''
  }
}

async function assignRole(role: RoleName, value: string) {
  try {
    roles.value = await setRoles({ [role]: value })
    note.value = `Роль «${ROLE_LABEL[role]}» → ${value || 'не назначена'}`
    error.value = ''
  } catch (e) {
    note.value = ''
    error.value = reason(e)
  }
}

async function check(p: ModelProfilePublic) {
  results[p.id] = 'pending'
  try {
    results[p.id] = await testProfile(p.id)
  } catch (e) {
    results[p.id] = { ok: false, error: reason(e) }
  }
}

async function loadRemote(p: ModelProfilePublic) {
  remote[p.id] = 'loading'
  try {
    remote[p.id] = await remoteModels(p.id)
  } catch (e) {
    remote[p.id] = reason(e)
  }
}

async function create() {
  if (!canCreate.value) return
  creating.value = true
  try {
    const created = await createProfile({
      name: fresh.name.trim(),
      base_url: fresh.baseUrl.trim(),
      model: fresh.model.trim(),
      api_key: fresh.apiKey,
      temperature: fresh.temperature,
      max_tokens: fresh.maxTokens,
      concurrency: fresh.concurrency,
      context_window: fresh.contextWindow,
      disable_thinking: fresh.noThinking,
      json_mode: fresh.jsonMode,
      reasoning_effort: fresh.reasoning.trim(),
    })
    Object.assign(fresh, { ...FRESH_DEFAULTS })
    note.value = `Модель «${created.name}» создана`
    draftOpen.value = false
    await load()
    drafts[created.id] = asDraft(created)
  } catch (e) {
    error.value = reason(e)
  } finally {
    creating.value = false
  }
}

const canCreateEmbed = computed(
  () =>
    !!embedDraft.name.trim() && !!embedDraft.baseUrl.trim() && !!embedDraft.model.trim() && !creatingEmbed.value,
)

/** kind='embedding'; формат шлюза добавляет к запросу нестандартные поля task, OpenAI понимает только dimensions. */
async function createEmbed() {
  if (!canCreateEmbed.value) return
  creatingEmbed.value = true
  const gateway = embedDraft.protocol === 'gateway'
  try {
    const created = await createProfile({
      name: embedDraft.name.trim(),
      base_url: embedDraft.baseUrl.trim(),
      model: embedDraft.model.trim(),
      api_key: embedDraft.apiKey,
      kind: 'embedding',
      embed_dimensions: embedDraft.dimensions || null,
      embed_query_task: gateway ? embedDraft.queryTask.trim() || 'retrieval.query' : null,
      embed_passage_task: gateway ? embedDraft.passageTask.trim() || 'retrieval.passage' : null,
    })
    Object.assign(embedDraft, { name: '', baseUrl: '', model: '', apiKey: '' })
    note.value = `Модель «${created.name}» создана`
    error.value = ''
    await load()
  } catch (e) {
    note.value = ''
    error.value = reason(e)
  } finally {
    creatingEmbed.value = false
  }
}

async function remove(p: ModelProfilePublic) {
  try {
    await deleteProfile(p.id)
    delete drafts[p.id]
    delete results[p.id]
    toDelete.value = ''
    note.value = `Модель «${p.name}» удалена`
    await load()
  } catch (e) {
    error.value = reason(e)
  }
}

/** Подпись результата проверки подключения одной строкой (embedding-модель отвечает размерностью вектора). */
function testText(id: string): string {
  const r = results[id]
  if (!r || r === 'pending') return ''
  if (!r.ok) return r.error
  return r.dimensions
    ? `вектор размерности ${r.dimensions} за ${r.latency_s} с`
    : `ответ «${r.reply}» за ${r.latency_s} с`
}
const testOk = (id: string) => results[id] !== undefined && results[id] !== 'pending' && (results[id] as ProfileTest).ok

const remoteError = (id: string) => {
  const r = remote[id]
  return typeof r === 'string' && r !== 'loading' ? r : ''
}
const remoteList = (id: string) => (Array.isArray(remote[id]) ? (remote[id] as string[]) : null)

const badgeFor = (p: ModelProfilePublic) =>
  p.has_key ? { text: 'ключ есть', cls: 'badge--ok' } : { text: 'без ключа', cls: 'badge--warn' }

onMounted(load)
</script>

<template>
  <main class="page">
    <header class="page-head">
      <div>
        <p class="eyebrow">Шаг настройки</p>
        <h1>Настройки</h1>
        <p class="lede">
          Профили — подключения к OpenAI-совместимому API, и роли, на которые они назначены: ответ,
          критик, эмбеддинги, реранк.
        </p>
      </div>
      <RouterLink class="btn btn--ghost back" :to="{ name: 'home' }">
        <AppIcon name="arrow-right" size="sm" />
        На главную
      </RouterLink>
    </header>

    <p v-if="error" class="msg msg--bad"><AppIcon name="alert" size="sm" /> {{ error }}</p>
    <p v-else-if="note" class="msg">
      <AppIcon name="check" size="sm" /> {{ note }}
    </p>

    <section class="card card--pad-lg area reveal" aria-labelledby="types-title">
      <div class="area__head">
        <span class="area__icon"><AppIcon name="settings" /></span>
        <div>
          <h2 id="types-title">Привязки LLM</h2>
          <p class="muted area__sub">
            Прогон берёт модели из привязок ниже. Одну модель можно назначить сразу на несколько типов.
          </p>
        </div>
      </div>

      <div class="types">
        <AccordionItem
          data-kind="type"
          v-model:open="openTypes.llm"
          icon="activity"
          title="LLM — ответ и критика"
          subtitle="модель, которая отвечает, и модель-критик для перепроверки"
          :badge="roles.answer ? 'привязана' : 'не назначена'"
          :badge-cls="roles.answer ? 'badge--ok' : 'badge--warn'"
        >
          <div class="types__grid">
            <label class="field roles__row">
              <span class="field__label">{{ ROLE_LABEL.answer }} <span class="mono">answer</span></span>
              <select
                class="select"
                :value="roles.answer ?? ''"
                :disabled="loading || !chatProfiles.length"
                @change="assignRole('answer', ($event.target as HTMLSelectElement).value)"
              >
                <option value="">не назначено</option>
                <option v-for="p in chatProfiles" :key="p.id" :value="p.id">{{ p.name }} · {{ p.model }}</option>
              </select>
              <span class="field__hint">{{ ROLE_HINT.answer }}</span>
            </label>
            <label class="field roles__row">
              <span class="field__label">{{ ROLE_LABEL.critic }} <span class="mono">critic</span></span>
              <select
                class="select"
                :value="roles.critic ?? ''"
                :disabled="loading || !chatProfiles.length"
                @change="assignRole('critic', ($event.target as HTMLSelectElement).value)"
              >
                <option value="">не назначено</option>
                <option v-for="p in chatProfiles" :key="p.id" :value="p.id">{{ p.name }} · {{ p.model }}</option>
              </select>
              <span class="field__hint">{{ ROLE_HINT.critic }}</span>
            </label>
          </div>
        </AccordionItem>

      </div>
    </section>

    <section class="card card--pad-lg area reveal reveal-2" aria-labelledby="profiles-title">
      <div class="area__head">
        <span class="area__icon"><AppIcon name="plug" /></span>
        <div>
          <h2 id="profiles-title">Модели</h2>
          <p class="muted area__sub">
            Ключ хранится на сервере и в интерфейс не возвращается — видно только «ключ есть».
          </p>
        </div>
      </div>

      <p v-if="loading" class="muted empty">Загружаем модели…</p>
      <p v-else-if="!chatProfiles.length" class="muted empty">
        Пока нет ни одной модели — добавьте её кнопкой ниже или включите бэкенд.
      </p>

      <div v-else class="area__list">
        <AccordionItem
          v-for="p in chatProfiles"
          :key="p.id"
          data-kind="profile"
          v-model:open="open[p.id]"
          icon="activity"
          :title="p.name"
          :subtitle="`${p.model} @ ${hostOf(p.base_url)}`"
          :badge="badgeFor(p).text"
          :badge-cls="badgeFor(p).cls"
        >
          <div class="grid">
            <label class="field">
              <span class="field__label">Название</span>
              <input v-model="drafts[p.id].name" class="input" type="text" />
            </label>
            <label class="field">
              <span class="field__label">Base URL</span>
              <input v-model="drafts[p.id].baseUrl" class="input" type="url" spellcheck="false" placeholder="https://api.example.com/v1" />
            </label>

            <template v-if="remoteList(p.id)">
              <label class="field">
                <span class="field__label">Модель из API</span>
                <select v-model="drafts[p.id].model" class="select">
                  <option v-for="m in remoteList(p.id) ?? []" :key="m" :value="m">{{ m }}</option>
                </select>
                <span class="field__hint">Список от <span class="mono">GET /models</span> провайдера.</span>
              </label>
            </template>
            <template v-else>
              <label class="field">
                <span class="field__label">Модель</span>
                <input v-model="drafts[p.id].model" class="input" type="text" spellcheck="false" placeholder="gpt-4o-mini" />
                <span class="field__hint">Можно выбрать из списка кнопкой ниже.</span>
              </label>
            </template>

            <label class="field">
              <span class="field__label">API key</span>
              <input
                v-model="drafts[p.id].apiKey"
                class="input"
                type="password"
                spellcheck="false"
                autocomplete="off"
                :placeholder="p.has_key ? 'ключ сохранён — введите новый, чтобы заменить' : 'sk-…'"
              />
              <span class="field__hint">
                <button v-if="p.has_key" class="link" type="button" @click="drafts[p.id].clearKey = true">
                  стереть сохранённый ключ
                </button>
                <template v-else>Ключ уйдёт на сервер и больше не покажется.</template>
              </span>
            </label>

            <label class="field">
              <span class="field__label">Переменная с ключом</span>
              <input v-model="drafts[p.id].keyEnv" class="input" type="text" spellcheck="false" placeholder="LLM_API_KEY" />
              <span class="field__hint">Если ключ лежит в окружении сервера.</span>
            </label>

            <label class="field">
              <span class="field__label">Доп. заголовки</span>
              <input v-model="drafts[p.id].headers" class="input" type="text" spellcheck="false" placeholder="User-Agent=curl/8" />
              <span class="field__hint">Через <span class="mono">;</span>, как в <span class="mono">extra_headers</span>.</span>
            </label>
          </div>

          <div class="params">
            <NumberField
              v-model="drafts[p.id].temperature"
              label="Температура"
              :min="0"
              :max="2"
              :step="0.1"
              hint="Для честного замера держим 0."
            />
            <label class="field">
              <span class="field__label">Max tokens</span>
              <input
                class="input"
                type="number"
                min="1"
                step="1"
                :value="drafts[p.id].maxTokens ?? ''"
                @input="
                  drafts[p.id].maxTokens =
                    ($event.target as HTMLInputElement).value === ''
                      ? null
                      : Number(($event.target as HTMLInputElement).value)
                "
              />
              <span class="field__hint">Пусто — лимит не передаём.</span>
            </label>
            <NumberField
              v-model="drafts[p.id].concurrency"
              label="Параллельных запросов"
              :min="1"
              :max="16"
              :step="1"
              hint="Личный лимит модели; общий потолок — на сервере."
            />
            <NumberField
              v-model="drafts[p.id].contextWindow"
              label="Контекст модели"
              :min="512"
              :max="4000000"
              :step="512"
              unit="токенов"
              hint="Справка о модели: во сколько токенов она видит."
            />
            <label class="field">
              <span class="field__label">Режим размышлений</span>
              <span class="checks">
                <input v-model="drafts[p.id].noThinking" type="checkbox" />
                <span>выключать thinking у vLLM/Qwen</span>
              </span>
              <span class="field__hint">
                <label class="checks">
                  <input v-model="drafts[p.id].jsonMode" type="checkbox" />
                  <span>JSON-режим (<span class="mono">response_format</span>)</span>
                </label>
              </span>
            </label>
            <label class="field">
              <span class="field__label">Усилие рассуждений</span>
              <select v-model="drafts[p.id].reasoning" class="select">
                <option value="">обычный режим</option>
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
              </select>
              <span class="field__hint">Для моделей с рассуждениями (<span class="mono">reasoning_effort</span>).</span>
            </label>
          </div>

          <div class="check">
            <button
              class="btn btn--primary"
              type="button"
              :disabled="!isDirty(p) || saving === p.id"
              @click="save(p)"
            >
              {{ saving === p.id ? 'Сохраняем…' : 'Сохранить' }}
            </button>
            <button class="btn" type="button" :disabled="results[p.id] === 'pending'" @click="check(p)">
              <span v-if="results[p.id] === 'pending'" class="check__spin" />
              <AppIcon v-else name="refresh" size="sm" />
              Проверить соединение
            </button>
            <button class="btn btn--ghost" type="button" :disabled="remote[p.id] === 'loading'" @click="loadRemote(p)">
              {{ remote[p.id] === 'loading' ? 'Спрашиваем API…' : 'Список моделей API' }}
            </button>
            <button v-if="toDelete !== p.id" class="btn btn--ghost" type="button" @click="toDelete = p.id">
              Удалить
            </button>
            <template v-else>
              <button class="btn btn--danger" type="button" @click="remove(p)">Точно удалить</button>
              <button class="btn btn--ghost" type="button" @click="toDelete = ''">Отмена</button>
            </template>
          </div>

          <transition name="fade-slide">
            <p v-if="remoteError(p.id)" class="msg msg--bad">
              <AppIcon name="alert" size="sm" /> {{ remoteError(p.id) }}
            </p>
          </transition>

          <transition name="fade-slide">
            <p v-if="results[p.id] && results[p.id] !== 'pending'" class="check__msg" :class="testOk(p.id) ? 'is-ok' : 'is-bad'">
              <AppIcon :name="testOk(p.id) ? 'check' : 'alert'" size="sm" />
              {{ testText(p.id) }}
            </p>
          </transition>
        </AccordionItem>
      </div>

      <div class="models__types">
        <AccordionItem
          data-kind="type"
          v-model:open="openTypes.embed"
          icon="file"
          title="Эмбеддинги"
          subtitle="смысловой поиск фрагментов (POST /embeddings)"
          :badge="roles.embed ? 'привязана' : 'не назначена'"
          :badge-cls="roles.embed ? 'badge--ok' : 'badge--warn'"
        >
          <label class="field roles__row">
            <span class="field__label">{{ ROLE_LABEL.embed }} <span class="mono">embed</span></span>
            <select
              class="select"
              :value="roles.embed ?? ''"
              :disabled="loading || !embedProfiles.length"
              @change="assignRole('embed', ($event.target as HTMLSelectElement).value)"
            >
              <option value="">не назначено</option>
              <option v-for="p in embedProfiles" :key="p.id" :value="p.id">{{ p.name }} · {{ p.model }}</option>
            </select>
            <span class="field__hint">
              <template v-if="roles.embed">привязано: {{ boundName('embed') }}</template>
              <template v-else>пока привязки нет, поиск идёт только по словам (BM25)</template>
            </span>
          </label>

          <div v-if="embedProfiles.length" class="embed__list">
            <div v-for="p in embedProfiles" :key="p.id" class="embed__row">
              <div class="embed__who">
                <strong>{{ p.name }}</strong>
                <span class="muted mono">{{ p.model }} @ {{ hostOf(p.base_url) }}</span>
                <span class="badge" :class="badgeFor(p).cls">{{ badgeFor(p).text }}</span>
                <span v-if="p.embed_dimensions" class="badge">{{ p.embed_dimensions }} мерн.</span>
              </div>
              <div class="check">
                <button class="btn" type="button" :disabled="results[p.id] === 'pending'" @click="check(p)">
                  <span v-if="results[p.id] === 'pending'" class="check__spin" />
                  <AppIcon v-else name="refresh" size="sm" />
                  Проверить
                </button>
                <button v-if="toDelete !== p.id" class="btn btn--ghost" type="button" @click="toDelete = p.id">
                  Удалить
                </button>
                <template v-else>
                  <button class="btn btn--danger" type="button" @click="remove(p)">Точно удалить</button>
                  <button class="btn btn--ghost" type="button" @click="toDelete = ''">Отмена</button>
                </template>
              </div>
              <transition name="fade-slide">
                <p v-if="results[p.id] && results[p.id] !== 'pending'" class="check__msg" :class="testOk(p.id) ? 'is-ok' : 'is-bad'">
                  <AppIcon :name="testOk(p.id) ? 'check' : 'alert'" size="sm" />
                  {{ testText(p.id) }}
                </p>
              </transition>
            </div>
          </div>

          <div class="types__pending">
            <div class="grid">
              <label class="field">
                <span class="field__label">Название</span>
                <input v-model="embedDraft.name" class="input" type="text" placeholder="Эмбеддинги шлюза" />
              </label>
              <label class="field">
                <span class="field__label">Base URL</span>
                <input v-model="embedDraft.baseUrl" class="input" type="url" spellcheck="false" placeholder="https://…/v1" />
              </label>
              <label class="field">
                <span class="field__label">Модель</span>
                <input v-model="embedDraft.model" class="input" type="text" spellcheck="false" placeholder="cifra48/embedding" />
              </label>
              <label class="field">
                <span class="field__label">API key</span>
                <input v-model="embedDraft.apiKey" class="input" type="password" spellcheck="false" autocomplete="off" />
              </label>
            </div>
            <div class="params">
              <label class="field">
                <span class="field__label">Протокол эмбеддингов</span>
                <select v-model="embedDraft.protocol" class="select">
                  <option value="gateway">формат шлюза (не OpenAI)</option>
                  <option value="openai">OpenAI-совместимый</option>
                </select>
                <span class="field__hint">
                  Формат шлюза добавляет в запрос <span class="mono">task</span>; OpenAI понимает только
                  <span class="mono">dimensions</span>.
                </span>
              </label>
              <template v-if="embedDraft.protocol === 'gateway'">
                <label class="field">
                  <span class="field__label">Поле task для вопроса</span>
                  <input v-model="embedDraft.queryTask" class="input" type="text" spellcheck="false" placeholder="retrieval.query" />
                  <span class="field__hint">Уйдёт в <span class="mono">embed_query_task</span>.</span>
                </label>
                <label class="field">
                  <span class="field__label">Поле task для фрагментов</span>
                  <input v-model="embedDraft.passageTask" class="input" type="text" spellcheck="false" placeholder="retrieval.passage" />
                  <span class="field__hint">Уйдёт в <span class="mono">embed_passage_task</span>.</span>
                </label>
              </template>
              <label class="field">
                <span class="field__label">Размерность векторов</span>
                <input v-model.number="embedDraft.dimensions" class="input" type="number" min="64" max="8192" step="64" />
                <span class="field__hint">Попадёт в <span class="mono">embed_dimensions</span> запроса.</span>
              </label>
            </div>
            <div class="check">
              <button class="btn btn--primary" type="button" :disabled="!canCreateEmbed" @click="createEmbed">
                {{ creatingEmbed ? 'Создаём…' : 'Создать модель' }}
              </button>
              <span class="field__hint">Первая модель сама займёт роль <span class="mono">embed</span>.</span>
            </div>
          </div>
        </AccordionItem>

        <AccordionItem
          data-kind="type"
          v-model:open="openTypes.rerank"
          icon="shield"
          title="Реранкер"
          subtitle="пересортировка найденных фрагментов (опция пайплайна rerank)"
          :badge="roles.rerank ? 'привязан' : 'по роли — ответчик'"
          :badge-cls="roles.rerank ? 'badge--ok' : ''"
        >
          <label class="field roles__row">
            <span class="field__label">{{ ROLE_LABEL.rerank }} <span class="mono">rerank</span></span>
            <select
              class="select"
              :value="roles.rerank ?? ''"
              :disabled="loading || !chatProfiles.length"
                @change="assignRole('rerank', ($event.target as HTMLSelectElement).value)"
              >
                <option value="">не назначено</option>
                <option v-for="p in chatProfiles" :key="p.id" :value="p.id">{{ p.name }} · {{ p.model }}</option>
            </select>
            <span class="field__hint">
              <template v-if="roles.rerank">привязано: {{ boundName('rerank') }}</template>
              <template v-else>без своей роли перечитку делает модель-ответчик</template>
            </span>
          </label>
          <p class="types__note muted">
            <AppIcon name="alert" size="sm" />
            Отдельного реранкера в шлюзе нет: пайплайн пересортирует фрагменты чат-запросом этой модели.
          </p>
        </AccordionItem>
      </div>

      <transition name="fade-slide" mode="out-in">
        <button
          v-if="!draftOpen"
          class="btn btn--ghost add-model"
          type="button"
          @click="draftOpen = true"
        >
          <AppIcon name="plus" size="sm" />
          Добавить модель
        </button>
        <AccordionItem
          v-else
          data-kind="draft"
          v-model:open="draftOpen"
          icon="plus"
          title="Новая модель"
          subtitle="Подключение к OpenAI-совместимому API"
        >
        <div class="grid">
          <label class="field">
            <span class="field__label">Название</span>
            <input v-model="fresh.name" class="input" type="text" placeholder="Своя модель" />
          </label>
          <label class="field">
            <span class="field__label">Base URL</span>
            <input v-model="fresh.baseUrl" class="input" type="url" spellcheck="false" placeholder="https://api.example.com/v1" />
          </label>
          <label class="field">
            <span class="field__label">Модель</span>
            <input v-model="fresh.model" class="input" type="text" spellcheck="false" placeholder="gpt-4o-mini" />
          </label>
          <label class="field">
            <span class="field__label">API key</span>
            <input v-model="fresh.apiKey" class="input" type="password" spellcheck="false" autocomplete="off" />
          </label>
        </div>
        <div class="params">
          <NumberField
            v-model="fresh.temperature"
            label="Температура"
            :min="0"
            :max="2"
            :step="0.1"
            hint="Для честного замера держим 0."
          />
          <label class="field">
            <span class="field__label">Max tokens</span>
            <input
              class="input"
              type="number"
              min="1"
              step="1"
              :value="fresh.maxTokens ?? ''"
              @input="
                fresh.maxTokens =
                  ($event.target as HTMLInputElement).value === ''
                    ? null
                    : Number(($event.target as HTMLInputElement).value)
              "
            />
            <span class="field__hint">Пусто — лимит не передаём.</span>
          </label>
          <NumberField
            v-model="fresh.concurrency"
            label="Параллельных запросов"
            :min="1"
            :max="16"
            :step="1"
            hint="Личный лимит модели; общий потолок — на сервере."
          />
          <NumberField
            v-model="fresh.contextWindow"
            label="Контекст модели"
            :min="512"
            :max="4000000"
            :step="512"
            unit="токенов"
            hint="Справка о модели: во сколько токенов она видит."
          />
          <label class="field">
            <span class="field__label">Режим размышлений</span>
            <span class="checks">
              <input v-model="fresh.noThinking" type="checkbox" />
              <span>выключать thinking у vLLM/Qwen</span>
            </span>
            <span class="field__hint">
              <label class="checks">
                <input v-model="fresh.jsonMode" type="checkbox" />
                <span>JSON-режим (<span class="mono">response_format</span>)</span>
              </label>
            </span>
          </label>
          <label class="field">
            <span class="field__label">Усилие рассуждений</span>
            <select v-model="fresh.reasoning" class="select">
              <option value="">обычный режим</option>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
            </select>
            <span class="field__hint">Для моделей с рассуждениями (<span class="mono">reasoning_effort</span>).</span>
          </label>
        </div>
        <div class="check">
          <button class="btn btn--primary" type="button" :disabled="!canCreate" @click="create">
            {{ creating ? 'Создаём…' : 'Создать модель' }}
          </button>
        </div>
        </AccordionItem>
      </transition>
    </section>

    <p class="env muted">
      Общий потолок параллельности держит сервер (<span class="mono">MAX_CONCURRENCY</span> и
      <span class="mono">LLM_CONCURRENCY</span> в <span class="mono">backend/.env</span>), а личный лимит
      каждой модели настраивается выше.
    </p>
  </main>
</template>

<style scoped>
.back .icon {
  rotate: 180deg;
}

.msg {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: var(--s-4);
  font-size: 13.5px;
  color: var(--text-muted);
}

.msg--bad {
  color: var(--bad);
}

.area__head {
  display: flex;
  align-items: flex-start;
  gap: var(--s-3);
  padding-bottom: var(--s-4);
}

.area__icon {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  flex: none;
  border-radius: var(--r-xs);
  background: var(--accent-soft);
  color: var(--accent);
}

.area__sub {
  font-size: 13.5px;
  margin-top: 2px;
}

.area__list {
  display: grid;
  border-top: 1px solid var(--border);
}

.area__list > * + * {
  border-top: 1px solid var(--border);
}

.empty {
  font-size: 13.5px;
  padding: var(--s-4) 0;
}

.types {
  display: grid;
  gap: var(--s-3);
}

.types__grid {
  display: grid;
  gap: var(--s-4);
}

.types__pending {
  display: grid;
  gap: var(--s-4);
  margin-top: var(--s-4);
  padding-top: var(--s-4);
  border-top: 1px dashed var(--border);
}

.embed__list {
  display: grid;
  gap: var(--s-3);
  margin-top: var(--s-4);
}

.embed__row {
  display: grid;
  gap: var(--s-2);
  padding: var(--s-3) var(--s-4);
  border: 1px solid var(--border);
  border-radius: var(--r-md, 10px);
}

.embed__who {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s-3);
}

.models__types {
  display: grid;
  gap: var(--s-3);
  margin-top: var(--s-4);
}

.add-model {
  margin-top: var(--s-4);
}

.types__note {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 13px;
}

.grid {
  display: grid;
  gap: var(--s-4);
}

.params {
  display: grid;
  gap: var(--s-4);
  margin-top: var(--s-5);
  padding-top: var(--s-4);
  border-top: 1px dashed var(--border);
}

.checks {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  font-size: 13.5px;
  color: var(--text-muted);
  accent-color: var(--accent);
}

.link {
  border: none;
  padding: 0;
  background: none;
  color: var(--accent);
  font: inherit;
  cursor: pointer;
  text-decoration: underline;
}

.check {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s-3);
  margin-top: var(--s-5);
}

.check__msg {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13.5px;
}

.check__msg.is-ok {
  color: var(--ok);
}

.check__msg.is-bad {
  color: var(--bad);
}

.check__spin {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid var(--border-strong);
  border-top-color: var(--accent);
  animation: spin 800ms linear infinite;
}

.env {
  margin-top: var(--s-4);
  font-size: 12.5px;
}

@media (min-width: 760px) {
  .grid,

  .params {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>
