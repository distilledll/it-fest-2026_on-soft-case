<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import { useAuth } from '@/composables/useAuth'

const router = useRouter()
const { signIn } = useAuth()

const login = ref('')
const password = ref('')
const peek = ref(false)
const busy = ref(false)

const error = ref('')
const canSubmit = computed(() => login.value.trim().length > 2 && password.value.length > 0)

async function submit() {
  if (!canSubmit.value || busy.value) return
  busy.value = true
  error.value = ''
  await new Promise((r) => setTimeout(r, 650))
  busy.value = false
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

      <form class="form" novalidate @submit.prevent="submit">
        <label class="field">
          <span class="field__label">Логин</span>
          <span class="input-wrap">
            <input
              v-model="login"
              class="input"
              type="text"
              name="login"
              autocomplete="username"
              placeholder="manager"
              :disabled="busy"
            />
          </span>
        </label>

        <label class="field">
          <span class="field__label">Пароль</span>
          <span class="input-wrap">
            <input
              v-model="password"
              class="input"
              :type="peek ? 'text' : 'password'"
              name="password"
              autocomplete="current-password"
              placeholder="••••••••"
              :disabled="busy"
            />
            <button
              class="icon-btn input-wrap__peek"
              type="button"
              :aria-label="peek ? 'Скрыть пароль' : 'Показать пароль'"
              @click="peek = !peek"
            >
              <AppIcon :name="peek ? 'eye-off' : 'eye'" size="sm" />
            </button>
          </span>
        </label>

        <transition name="fade-slide">
          <p v-if="error" class="login__error">
            <AppIcon name="alert" size="sm" />
            {{ error }}
          </p>
        </transition>

        <button class="btn btn--primary btn--lg btn--block" type="submit" :disabled="!canSubmit || busy">
          <span v-if="busy" class="btn__spin" />
          {{ busy ? 'Проверяем…' : 'Войти' }}
        </button>
      </form>
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

.form {
  display: grid;
  gap: var(--s-4);
}

.login__error {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  color: var(--bad);
  font-size: 13.5px;
}

.btn__spin {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 2px solid color-mix(in srgb, var(--on-accent) 40%, transparent);
  border-top-color: var(--on-accent);
  animation: spin 800ms linear infinite;
}
</style>
