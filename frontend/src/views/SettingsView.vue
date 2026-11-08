<script setup lang="ts">
import { ref } from 'vue'

import AccordionItem from '@/components/AccordionItem.vue'
import AppIcon from '@/components/AppIcon.vue'
import NumberField from '@/components/NumberField.vue'
import { useConnections } from '@/composables/useConnections'

const { items, testing, test } = useConnections()

const open = ref<Record<string, boolean>>({ llm: true, embed: false, rerank: false })

const badgeFor = (status: string) =>
  status === 'ok'
    ? { text: 'подключено', cls: 'badge--ok' }
    : status === 'error'
      ? { text: 'ошибка', cls: 'badge--bad' }
      : { text: 'не настроено', cls: '' }

const iconFor = (kind: string) => (kind === 'llm' ? 'activity' : kind === 'embed' ? 'file' : 'shield')
</script>

<template>
  <main class="page">
    <header class="page-head">
      <div>
        <p class="eyebrow">Шаг настройки</p>
        <h1>Настройки</h1>
        <p class="lede">
          Три подключения: поиск по документам, досортировка найденного и сама модель.
        </p>
      </div>
      <RouterLink class="btn btn--ghost back" :to="{ name: 'home' }">
        <AppIcon name="arrow-right" size="sm" />
        На главную
      </RouterLink>
    </header>

    <section class="card card--pad-lg area reveal" aria-labelledby="conn-title">
      <div class="area__head">
        <span class="area__icon"><AppIcon name="plug" /></span>
        <div>
          <h2 id="conn-title">Подключения</h2>
          <p class="muted area__sub">Ключи остаются на сервере и не показываются в интерфейсе.</p>
        </div>
      </div>

      <div class="area__list">
        <AccordionItem
          v-for="c in items"
          :key="c.kind"
          v-model:open="open[c.kind]"
          :icon="iconFor(c.kind)"
          :title="c.label"
          :subtitle="c.hint"
          :badge="badgeFor(c.status).text"
          :badge-cls="badgeFor(c.status).cls"
        >
          <div class="grid">
            <label class="field">
              <span class="field__label">Base URL</span>
              <input v-model="c.baseUrl" class="input" type="url" spellcheck="false" placeholder="https://api.example.com/v1" />
            </label>

            <label class="field">
              <span class="field__label">API key</span>
              <input
                v-model="c.apiKey"
                class="input"
                type="password"
                spellcheck="false"
                autocomplete="off"
                placeholder="sk-…"
              />
            </label>
          </div>

          <div v-if="c.kind === 'llm'" class="params">
            <NumberField
              v-model="c.params.temperature"
              label="Температура"
              :min="0"
              :max="2"
              :step="0.1"
              hint="Для честного замера «было/стало» держим 0."
            />
            <NumberField
              v-model="c.params.concurrency"
              label="Параллельных запросов"
              :min="1"
              :max="16"
              :step="1"
              hint="Сколько вопросов обрабатывать одновременно."
            />
            <NumberField
              v-model="c.params.contextWindow"
              label="Контекст модели"
              unit="токенов"
              :min="4096"
              :max="1048576"
              :step="1024"
              hint="Сколько текста закупки влезает в один запрос."
            />
          </div>

          <div class="check">
            <button class="btn" type="button" :disabled="testing === c.kind" @click="test(c.kind)">
              <span v-if="testing === c.kind" class="check__spin" />
              <AppIcon v-else name="refresh" size="sm" />
              {{ testing === c.kind ? 'Проверяем…' : 'Проверить соединение' }}
            </button>

            <transition name="fade-slide">
              <span v-if="c.checked" class="check__msg" :class="c.checked.ok ? 'is-ok' : 'is-bad'">
                <AppIcon :name="c.checked.ok ? 'check' : 'alert'" size="sm" />
                {{ c.checked.message }}
              </span>
            </transition>
          </div>
        </AccordionItem>
      </div>
    </section>
  </main>
</template>

<style scoped>
.back .icon {
  rotate: 180deg;
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

.grid {
  display: grid;
  gap: var(--s-4);
  max-width: 640px;
}

.params {
  display: grid;
  gap: var(--s-4);
  margin-top: var(--s-5);
  padding-top: var(--s-4);
  border-top: 1px dashed var(--border);
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

@media (min-width: 760px) {
  .grid {
    grid-template-columns: 1fr 1fr;
  }

  .params {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    max-width: 760px;
  }
}
</style>
