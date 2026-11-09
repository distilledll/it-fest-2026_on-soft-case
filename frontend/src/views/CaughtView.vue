<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import { caughtRun } from '@/api/runs'
import { ApiError } from '@/api/http'
import { statusMeta, verdictMeta } from '@/utils/presentation'
import type { Caught, CaughtRow, Verdict } from '@/types'

const route = useRoute()
const runId = computed(() => String(route.params.runId ?? ''))

const data = ref<Caught | null>(null)
const loading = ref(false)
const error = ref('')

const statusCls = (s?: string | null) => (s && statusMeta[s as keyof typeof statusMeta]?.cls) || ''
const statusLabel = (s?: string | null) => (s && statusMeta[s as keyof typeof statusMeta]?.label) || s || '—'
const verdictCls = (v?: string) => verdictMeta[v as Verdict]?.cls || ''
const verdictLabel = (v?: string) => verdictMeta[v as Verdict]?.label || v || 'нет оценки'

const failedSteps = (row: CaughtRow) => row.steps.filter((s) => s.ok === false || s.ok === null)

async function load() {
  const id = runId.value
  if (!id) {
    data.value = null
    return
  }
  loading.value = true
  error.value = ''
  try {
    const got = await caughtRun(id)
    if (runId.value === id) data.value = got
  } catch (e) {
    if (runId.value !== id) return
    data.value = null
    error.value = e instanceof ApiError ? e.message : 'не удалось получить разбор пойманных обманов'
  } finally {
    if (runId.value === id) loading.value = false
  }
}

watch(runId, load, { immediate: true })
</script>

<template>
  <main class="page">
    <header class="page-head">
      <div>
        <p class="eyebrow">Проверки кода и критики</p>
        <h1>Пойманные обманы</h1>
        <p class="caught__lede muted">
          Здесь вопросы, где черновой ответ модели оказался обманом, а финальный — уже нет: система
          поймала противоречие и ушла в честное «не знаю» или исправила ответ.
        </p>
      </div>
      <RouterLink class="btn btn--ghost btn--sm caught__back" :to="{ name: 'dashboard' }">
        <AppIcon name="arrow-right" size="sm" class="is-flip" /> К дашборду
      </RouterLink>
    </header>

    <p v-if="error" class="callout callout--bad">
      <AppIcon name="alert" size="sm" /> {{ error }}
    </p>
    <p v-else-if="loading && !data" class="caught__wait muted">
      <AppIcon name="activity" size="sm" /> Разбираем, что поймали проверки…
    </p>

    <template v-else-if="data">
      <p v-if="!data.has_gold" class="dash__note">
        <AppIcon name="alert" size="sm" />
        Эталонных ответов в датасете нет — вердикты «обман / верно» приблизительные и опираются на
        проверки кода, а не на правильный ответ жюри.
      </p>

      <div class="caught__stats">
        <div class="caught__stat caught__stat--ok">
          <b>{{ data.caught.length }}</b>
          <span>пойманных обманов</span>
        </div>
        <div class="caught__stat caught__stat--warn">
          <b>{{ data.false_alarms.length }}</b>
          <span>ложных срабатываний</span>
        </div>
        <div class="caught__per">
          <span class="caught__per-title muted">по проверкам:</span>
          <span v-for="(c, key) in data.per_critic" :key="key" class="caught__per-item">
            <b>{{ key }}</b> — сработала {{ c.fired }}, поймала {{ c.caught }}, шум {{ c.false_alarm }}
          </span>
          <span v-if="!Object.keys(data.per_critic).length" class="muted">проверки не срабатывали</span>
        </div>
      </div>

      <p v-if="!data.caught.length && !data.false_alarms.length" class="caught__none muted">
        <AppIcon name="check" size="sm" />
        Этот прогон не довёл ни один черновой обман до финала — ловить здесь нечего.
      </p>

      <ul v-if="data.caught.length" class="caught__list" aria-label="Пойманные обманы">
        <li v-for="row in data.caught" :key="row.id" class="card card--pad caught__card">
          <div class="caught__qhead">
            <span class="mono caught__id">{{ row.id }}</span>
            <span class="badge">{{ row.type }}</span>
          </div>
          <p class="caught__q">{{ row.question }}</p>

          <div class="caught__ba">
            <div class="caught__half caught__half--bad">
              <span class="caught__half-label">Было · черновик модели</span>
              <p class="caught__ans">{{ row.draft.answer || '—' }}</p>
              <p class="caught__badges">
                <span class="badge" :class="statusCls(row.draft.status)">{{ statusLabel(row.draft.status) }}</span>
                <span class="badge" :class="verdictCls(row.draft_verdict)">{{ verdictLabel(row.draft_verdict) }}</span>
              </p>
            </div>
            <AppIcon name="arrow-right" size="sm" class="caught__arrow" />
            <div class="caught__half caught__half--ok">
              <span class="caught__half-label">Стало · итог системы</span>
              <p class="caught__ans">{{ row.final.answer || row.final.status || '—' }}</p>
              <p class="caught__badges">
                <span class="badge" :class="statusCls(row.final.status)">{{ statusLabel(row.final.status) }}</span>
                <span class="badge" :class="verdictCls(row.final_verdict)">{{ verdictLabel(row.final_verdict) }}</span>
              </p>
            </div>
          </div>

          <p v-if="row.critics.length" class="caught__critics">
            поймали: <span v-for="c in row.critics" :key="c" class="badge badge--accent">{{ c }}</span>
          </p>

          <details v-if="failedSteps(row).length" class="caught__steps">
            <summary>Что делали проверки ({{ failedSteps(row).length }})</summary>
            <ul>
              <li v-for="(s, i) in failedSteps(row)" :key="i" class="caught__step">
                <b>{{ s.node }}</b>
                <span class="muted">{{ s.message }}</span>
              </li>
            </ul>
          </details>
        </li>
      </ul>

      <section v-if="data.false_alarms.length" class="caught__fa">
        <h2 class="caught__fa-title">Ложные срабатывания</h2>
        <p class="muted caught__sub">
          Честно о обратном: здесь черновой ответ был верным, а после проверок итог стал хуже. Таких
          случаев немного, но мы их не прячем.
        </p>
        <ul class="caught__list">
          <li v-for="row in data.false_alarms" :key="row.id" class="card card--pad caught__card caught__card--fa">
            <div class="caught__qhead">
              <span class="mono caught__id">{{ row.id }}</span>
              <span class="badge">{{ row.type }}</span>
            </div>
            <p class="caught__q">{{ row.question }}</p>
            <div class="caught__ba">
              <div class="caught__half caught__half--ok">
                <span class="caught__half-label">Было · черновик модели</span>
                <p class="caught__ans">{{ row.draft.answer || '—' }}</p>
                <p class="caught__badges">
                  <span class="badge" :class="verdictCls(row.draft_verdict)">{{ verdictLabel(row.draft_verdict) }}</span>
                </p>
              </div>
              <AppIcon name="arrow-right" size="sm" class="caught__arrow" />
              <div class="caught__half caught__half--bad">
                <span class="caught__half-label">Стало · итог системы</span>
                <p class="caught__ans">{{ row.final.answer || row.final.status || '—' }}</p>
                <p class="caught__badges">
                  <span class="badge" :class="verdictCls(row.final_verdict)">{{ verdictLabel(row.final_verdict) }}</span>
                </p>
              </div>
            </div>
            <p v-if="row.critics.length" class="caught__critics">
              шум подняли: <span v-for="c in row.critics" :key="c" class="badge badge--warn">{{ c }}</span>
            </p>
          </li>
        </ul>
      </section>
    </template>
  </main>
</template>

<style scoped>
.caught__lede {
  font-size: 13.5px;
  margin-top: 4px;
  max-width: 70ch;
}

.caught__back {
  align-self: start;
}

.caught__back .is-flip {
  rotate: 180deg;
}

.caught__wait {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13.5px;
}

.caught__stats {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s-4) var(--s-6);
  padding: var(--s-4);
  margin-bottom: var(--s-5);
  background: var(--surface-inset);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
}

.caught__stat {
  display: flex;
  align-items: baseline;
  gap: var(--s-2);
}

.caught__stat b {
  font-size: 30px;
  font-weight: 700;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.caught__stat--ok b {
  color: var(--ok);
}

.caught__stat--warn b {
  color: var(--warn);
}

.caught__stat span {
  font-size: 13px;
  color: var(--text-muted);
}

.caught__per {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s-3);
  font-size: 12.5px;
  color: var(--text-muted);
}

.caught__per-title {
  width: 100%;
}

.caught__per-item b {
  color: var(--text);
}

.caught__none {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
}

.caught__list {
  list-style: none;
  display: grid;
  gap: var(--s-4);
  margin: 0;
  padding: 0;
}

.caught__card {
  display: grid;
  gap: var(--s-3);
}

.caught__qhead {
  display: flex;
  align-items: center;
  gap: var(--s-2);
}

.caught__id {
  font-size: 12px;
  color: var(--text-faint);
}

.caught__q {
  font-size: 15px;
  font-weight: 600;
}

.caught__ba {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: stretch;
  gap: var(--s-3);
}

.caught__half {
  padding: var(--s-3);
  border-radius: var(--r-md);
  border: 1px solid var(--border);
  background: var(--surface-inset);
}

.caught__half--bad {
  border-color: color-mix(in srgb, var(--bad) 40%, var(--border));
}

.caught__half--ok {
  border-color: color-mix(in srgb, var(--ok) 40%, var(--border));
}

.caught__half-label {
  font-size: 11.5px;
  color: var(--text-faint);
}

.caught__ans {
  font-size: 14px;
  margin: 4px 0 var(--s-2);
  min-height: 1.2em;
}

.caught__badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.caught__arrow {
  align-self: center;
  color: var(--text-faint);
}

.caught__critics {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: var(--text-muted);
}

.caught__steps {
  font-size: 13px;
}

.caught__steps summary {
  cursor: pointer;
  color: var(--text-muted);
}

.caught__steps ul {
  list-style: none;
  margin: var(--s-2) 0 0;
  padding: 0;
  display: grid;
  gap: 4px;
}

.caught__step {
  display: flex;
  gap: var(--s-2);
  font-size: 12.5px;
}

.caught__fa {
  margin-top: var(--s-6);
}

.caught__fa-title {
  margin-bottom: 2px;
}

.caught__sub {
  font-size: 13.5px;
  margin-bottom: var(--s-4);
  max-width: 70ch;
}

.caught__card--fa {
  border-color: color-mix(in srgb, var(--warn) 30%, var(--border));
}

@media (max-width: 720px) {
  .caught__ba {
    grid-template-columns: 1fr;
  }

  .caught__arrow {
    rotate: 90deg;
    justify-self: center;
  }
}
</style>
