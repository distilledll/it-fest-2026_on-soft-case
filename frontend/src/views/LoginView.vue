<script setup lang="ts">
import { useRouter } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import { useAuth } from '@/composables/useAuth'

const router = useRouter()
const { signIn } = useAuth()

async function submit() {
  signIn()
  await router.push({ name: 'home' })
}
</script>

<template>
  <main class="login">
    <div class="login__panel card reveal">
      <div class="brand">
        <span class="brand__mark"><AppIcon name="shield" /></span>
        <span>
          <span class="brand__name">ИИ, который не обманывает</span>
          <span class="brand__sub">ОНСОФТ · разбор документов госзакупок</span>
        </span>
      </div>

      <button class="btn btn--primary btn--lg btn--block" type="button" @click="submit">
        Открыть рабочее место
      </button>
    </div>
  </main>
</template>

<style scoped>
.login {
  display: grid;
  place-items: center;
  min-height: 100svh;
  padding: var(--s-5);
}

.login__panel {
  width: min(420px, 100%);
  padding: var(--s-6);
  box-shadow: var(--shadow-3);
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  margin-bottom: var(--s-6);
}

.brand__mark {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: var(--r-sm);
  color: var(--on-accent);
  background: linear-gradient(140deg, var(--accent), color-mix(in srgb, var(--accent) 55%, var(--ok)));
  box-shadow: 0 6px 18px -8px var(--accent-line);
}

.brand__name,
.brand__sub {
  display: block;
}

.brand__name {
  font-weight: 640;
  letter-spacing: -0.01em;
}

.brand__sub {
  font-size: 12.5px;
  color: var(--text-faint);
}

</style>
