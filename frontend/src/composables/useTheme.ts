import { ref } from 'vue'

export type Theme = 'light' | 'dark'

const KEY = 'onsoft.theme'

function initial(): Theme {
  const saved = localStorage.getItem(KEY)
  if (saved === 'light' || saved === 'dark') return saved
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

const theme = ref<Theme>(initial())

function apply(next: Theme) {
  theme.value = next
  document.documentElement.dataset.theme = next
  localStorage.setItem(KEY, next)
}

apply(theme.value)

export function useTheme() {
  return {
    theme,
    isDark: () => theme.value === 'dark',
    toggle: () => apply(theme.value === 'dark' ? 'light' : 'dark'),
  }
}
