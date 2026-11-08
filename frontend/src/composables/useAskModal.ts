import { ref } from 'vue'

const open = ref(false)
const preset = ref('')

export function useAskModal() {
  return {
    open,
    preset,
    /** q — вопрос для автозаполнения (например, клик по строке на дашборде). */
    show: (q?: string) => {
      preset.value = q ?? ''
      open.value = true
    },
    hide: () => (open.value = false),
  }
}
