import { computed, ref } from 'vue'

const KEY = 'onsoft.signedIn'

const state = ref(localStorage.getItem(KEY) === '1')

/** Заглушка до появления /api/auth: сессия хранится в localStorage. */
export function useAuth() {
  return {
    signedIn: computed(() => state.value),
    signIn() {
      state.value = true
      localStorage.setItem(KEY, '1')
    },
    signOut() {
      state.value = false
      localStorage.removeItem(KEY)
    },
  }
}
