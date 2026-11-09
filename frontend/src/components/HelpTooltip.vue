<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'
</script>

<template>
  <span class="tip tip--bottom">
    <button class="icon-btn" type="button" aria-label="Как это читать">
      <AppIcon name="help" />
    </button>

    <span class="tip__bubble" role="tooltip">
      <span class="tip__title">Как читать ответы системы</span>
      Система отвечает по документам закупки и обязана привести дословную цитату. Каждую проверку
      считает оценщик:
      <span class="tip__list">
        <span>
          <b class="ok-text">верно</b> — ответ и цитата есть в документе.
        </span>
        <span>
          <b class="warn-text">осторожно</b> — система сказала «не знаю»: баллов не даёт, но и не
          обманывает.
        </span>
        <span>
          <b class="bad-text">обман</b> — числа в документе нет или цитату в тексте не найти.
        </span>
      </span>
      <span class="tip__formula">
        Индекс доверия = (верно − обманы) ÷ все вопросы × 100
      </span>
    </span>
  </span>
</template>

<style scoped>
.tip__title {
  display: block;
}

.tip__list {
  display: grid;
  gap: 3px;
  margin-top: var(--s-2);
}

.tip__formula {
  display: block;
  margin-top: var(--s-3);
  padding-top: var(--s-2);
  border-top: 1px dashed var(--border);
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-muted);
}

.ok-text {
  color: var(--ok);
}

.warn-text {
  color: var(--warn);
}

.bad-text {
  color: var(--bad);
}
</style>
