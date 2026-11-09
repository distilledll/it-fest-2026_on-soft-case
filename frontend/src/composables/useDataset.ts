import { ref } from 'vue'

import type { DatasetInfo } from '@/types'

const KEY = 'onsoft.dataset'

function restore(): DatasetInfo | null {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as DatasetInfo) : null
  } catch {
    return null
  }
}

const active = ref<DatasetInfo | null>(restore())

/** Последний загруженный датасет — он понадобится при запуске прогона и на дашборде. */
export function useDataset() {
  return {
    active,
    setActive(d: DatasetInfo) {
      active.value = d
      localStorage.setItem(KEY, JSON.stringify(d))
    },
    clear() {
      active.value = null
      localStorage.removeItem(KEY)
    },
  }
}
