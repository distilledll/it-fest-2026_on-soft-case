<script setup lang="ts">
import { ref, watch } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import { runInsights } from '@/api/runs'
import { ApiError } from '@/api/http'
import type { Insights } from '@/types'

const props = defineProps<{ runId: string }>()

const SHOW = 6
const data = ref<Insights | null>(null)
const loading = ref(false)
const error = ref('')
const expanded = ref(false)

const outcomeCls: Record<string, string> = {
  fixed: 'is-ok',
  refused: 'is-warn',
  kept: 'is-info',
}

async function load() {
  const id = props.runId
  expanded.value = false
  if (!id) {
    data.value = null
    return
  }
  loading.value = true
  error.value = ''
  try {
    const got = await runInsights(id)
    if (props.runId === id) data.value = got
  } catch (e) {
    if (props.runId !== id) return
    data.value = null
    error.value = e instanceof ApiError ? e.message : 'не удалось получить разбор проверок'
  } finally {
    if (props.runId === id) loading.value = false
  }
}

watch(() => props.runId, load, { immediate: true })
</script>

<template>
  <section v-if="runId" class="card card--pad-lg insights reveal" aria-labelledby="insights-title">
    <div class="insights__head">
      <div>
        <p class="eyebrow">Проверки кода</p>
        <h2 id="insights-title">Что заметили проверки</h2>
        <p class="muted insights__sub">
          Проверки кода смотрят, читала ли модель всё, сходятся ли расчёты и файлы. Здесь — где они
          споткнулись и чем это кончилось.
        </p>
      </div>
    </div>

    <p v-if="error" class="callout callout--bad">
      <AppIcon name="alert" size="sm" /> {{ error }}
    </p>
    <p v-else-if="loading && !data" class="insights__wait muted">
      <AppIcon name="activity" size="sm" /> Считаем, что заметили проверки…
    </p>

    <template v-else-if="data">
      <div class="insights__stats">
        <div class="insights__stat">
          <b>{{ data.clean }}</b>
          <span>из {{ data.n }} — ответили сразу, замечаний нет</span>
        </div>
        <div class="insights__stat insights__stat--warn">
          <b>{{ data.with_checks }}</b>
          <span>— проверка что-то заметила</span>
        </div>
        <div class="insights__stat insights__stat--ok">
          <b>{{ data.outcomes.fixed ?? 0 }}</b>
          <span>исправили ответ</span>
        </div>
        <div class="insights__stat insights__stat--muted">
          <b>{{ data.outcomes.refused ?? 0 }}</b>
          <span>стали честнее: «не знаю» вместо риска</span>
        </div>
      </div>

      <ul v-if="data.checks.length" class="insights__checks">
        <li v-for="c in data.checks" :key="c.check" class="insights__check">
          <div class="insights__check-top">
            <span class="insights__check-title">{{ c.title }}</span>
            <span class="badge badge--accent">сработала {{ c.fired }}</span>
          </div>
          <p v-if="c.what" class="insights__check-what muted">{{ c.what }}</p>
          <p class="insights__check-out muted">
            <span v-if="c.fixed" class="is-ok-text">исправили {{ c.fixed }}</span>
            <span v-if="c.refused" class="is-warn-text">ушли в «не знаю» {{ c.refused }}</span>
            <span v-if="c.kept" class="is-info-text">подтвердили {{ c.kept }}</span>
          </p>
        </li>
      </ul>

      <p v-if="!data.events.length" class="insights__none muted">
        <AppIcon name="check" size="sm" />
        Ни одна проверка не споткнулась — все ответы сошлись с первого раза.
      </p>

      <ol v-else class="insights__feed" aria-label="Вопросы, где сработали проверки">
        <li
          v-for="ev in expanded ? data.events : data.events.slice(0, SHOW)"
          :key="ev.id"
          class="insights__event"
        >
          <span class="insights__event-id mono">{{ ev.id }}</span>
          <div class="insights__event-body">
            <p class="insights__event-q">{{ ev.question || ev.id }}</p>
            <p class="insights__event-checks">
              <span v-for="c in ev.checks" :key="c.check" class="badge">{{ c.title }}</span>
            </p>
            <p v-if="ev.draft" class="insights__event-draft muted">
              было: {{ ev.draft }} → стало: {{ ev.final?.status || '—' }}
            </p>
          </div>
          <span class="insights__outcome" :class="outcomeCls[ev.outcome] ?? ''">{{ ev.outcome_title }}</span>
        </li>
      </ol>

      <button
        v-if="data.events.length > SHOW"
        class="btn btn--ghost btn--sm insights__more"
        type="button"
        @click="expanded = !expanded"
      >
        {{ expanded ? 'Свернуть' : `Показать все ${data.events.length}` }}
      </button>
    </template>
  </section>
</template>

<style scoped>
.insights__head {
  margin-bottom: var(--s-4);
}

.insights__sub {
  font-size: 13.5px;
  margin-top: 2px;
  max-width: 68ch;
}

.insights__wait {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13.5px;
}

.insights__stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: var(--s-3);
  padding-bottom: var(--s-4);
  border-bottom: 1px solid var(--border);
}

.insights__stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.insights__stat b {
  font-size: 26px;
  font-weight: 700;
  line-height: 1;
  font-variant-numeric: tabular-nums;
  color: var(--accent);
}

.insights__stat span {
  font-size: 12.5px;
  color: var(--text-muted);
}

.insights__stat--ok b {
  color: var(--ok);
}

.insights__stat--warn b {
  color: var(--warn);
}

.insights__stat--muted b {
  color: var(--text-faint);
}

.insights__checks {
  list-style: none;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--s-3);
  padding: var(--s-4) 0;
  margin: 0;
}

.insights__check {
  padding: var(--s-3);
  background: var(--surface-inset);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
}

.insights__check-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-2);
}

.insights__check-title {
  font-weight: 600;
  font-size: 14px;
}

.insights__check-what {
  font-size: 12.5px;
  margin-top: 4px;
}

.insights__check-out {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s-3);
  font-size: 12px;
  margin-top: 6px;
}

.is-ok-text {
  color: var(--ok);
}

.is-warn-text {
  color: var(--warn);
}

.is-info-text {
  color: var(--info);
}

.insights__none {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13.5px;
  padding-top: var(--s-4);
}

.insights__feed {
  list-style: none;
  display: grid;
  gap: var(--s-2);
  margin: var(--s-4) 0 0;
  padding: 0;
}

.insights__event {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: start;
  gap: var(--s-3);
  padding: var(--s-3) 0;
  border-top: 1px solid var(--border);
}

.insights__event-id {
  font-size: 12px;
  color: var(--text-faint);
  padding-top: 2px;
}

.insights__event-q {
  font-size: 13.5px;
  font-weight: 550;
}

.insights__event-checks {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.insights__event-draft {
  font-size: 12.5px;
  margin-top: 6px;
}

.insights__outcome {
  font-size: 12px;
  font-weight: 550;
  padding: 3px 9px;
  border-radius: var(--r-pill);
  background: var(--surface-inset);
  border: 1px solid var(--border);
  color: var(--text-muted);
  white-space: nowrap;
}

.insights__outcome.is-ok {
  color: var(--ok);
  border-color: var(--ok);
}

.insights__outcome.is-warn {
  color: var(--warn);
  border-color: var(--warn);
}

.insights__outcome.is-info {
  color: var(--info);
  border-color: var(--info);
}

.insights__more {
  margin-top: var(--s-3);
}

@media (max-width: 620px) {
  .insights__event {
    grid-template-columns: auto 1fr;
  }

  .insights__outcome {
    grid-column: 2;
    justify-self: start;
  }
}
</style>
