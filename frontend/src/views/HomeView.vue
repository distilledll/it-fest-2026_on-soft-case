<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'
import { formatIndex } from '@/utils/presentation'
import { mockAfter } from '@/api/mock'

const indexNow = mockAfter.score.index
</script>

<template>
  <main class="page home">
    <div class="home__hero">
      <p class="eyebrow">ОНСОФТ · документы госзакупок</p>
      <h1>ИИ, который честно говорит «не знаю»</h1>

      <!-- Текст заменим на ваш. -->
      <p class="lede home__text">
        Lorem ipsum dolor sit amet, consectetur adipiscing elit. Integer pretium, sem vitae vehicula
        faucibus, nisl augue viverra lorem, in tincidunt urna nibh vitae ipsum. Curabitur a elit a nibh
        fringilla sagittis. Donec pulvinar, arcu eget tincidunt dictum, justo augue tempor nisi, eget
        semper mi nunc non urna. Vestibulum ante ipsum primis in faucibus orci luctus et ultrices posuere
        cubilia curae; Sed commodo tellus a lectus ultricies, eget vestibulum nibh blandit.
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

    <section class="card home__strip reveal reveal-2" aria-label="Текущее состояние">
      <div class="strip__cell">
        <span class="strip__label">Датасет</span>
        <span class="strip__value">Пример организатора</span>
      </div>
      <span class="strip__sep" aria-hidden="true" />
      <div class="strip__cell">
        <span class="strip__label">Последний прогон</span>
        <span class="strip__value">
          {{ mockAfter.meta.label }}
          <span class="badge badge--ok">готово</span>
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
