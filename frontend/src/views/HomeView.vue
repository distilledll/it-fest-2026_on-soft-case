<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'
import { formatIndex } from '@/utils/presentation'
import { releaseAfter } from '@/api/benchmark'

const indexNow = releaseAfter.score!.index!
</script>

<template>
  <main class="page home">
    <div class="home__hero">
      <p class="eyebrow">ОНСОФТ · документы госзакупок</p>
      <h1>ИИ, который честно говорит «не знаю»</h1>

      <p class="lede home__text">
        Загрузите документы закупки и задайте вопрос. Система сверит условия, укажет источник
        и покажет расхождения между документами. Ответы на весь набор можно скачать в CSV.
      </p>

      <div class="btn-row home__actions">
        <RouterLink class="btn btn--primary btn--lg" :to="{ name: 'dashboard' }">
          Перейти в дашборд
          <AppIcon name="arrow-right" size="sm" />
        </RouterLink>
        <RouterLink class="btn btn--lg" :to="{ name: 'upload' }">
          <AppIcon name="upload" size="sm" />
          Загрузить новые данные
        </RouterLink>
      </div>
    </div>

    <section class="card home__strip reveal reveal-2" aria-label="Результат проверки релиза">
      <div class="strip__cell">
        <span class="strip__label">Датасет</span>
        <span class="strip__value">Пример организатора</span>
      </div>
      <span class="strip__sep" aria-hidden="true" />
      <div class="strip__cell">
        <span class="strip__label">Замер релиза · 8 ноября</span>
        <span class="strip__value">
          {{ releaseAfter.label }}
        </span>
      </div>
      <span class="strip__sep" aria-hidden="true" />
      <div class="strip__cell">
        <span class="strip__label">Индекс доверия</span>
        <span class="strip__value strip__value--num">{{ formatIndex(indexNow) }}</span>
      </div>
    </section>
  </main>
</template>

<style scoped>
.home {
  display: grid;
  align-content: center;
  gap: var(--s-7);
  min-height: 100svh;
}

.home__hero {
  max-width: 720px;
}

.home__hero h1 {
  font-size: clamp(30px, 4.4vw, 46px);
  max-width: 20ch;
}

.home__text {
  margin-top: var(--s-4);
}

.home__actions {
  margin-top: var(--s-6);
}

.home__strip {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s-5);
  padding: var(--s-4) var(--s-5);
}

.strip__cell {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.strip__label {
  font-size: 12px;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  color: var(--text-faint);
}

.strip__value {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  font-weight: 580;
}

.strip__value--num {
  font-size: 24px;
  font-weight: 680;
  letter-spacing: -0.02em;
  color: var(--accent);
  font-variant-numeric: tabular-nums;
}

.strip__sep {
  width: 1px;
  height: 34px;
  background: var(--border);
}

@media (max-width: 720px) {
  .home {
    align-content: start;
  }

  .strip__sep {
    display: none;
  }
}
</style>
