import { ref } from 'vue'

/** Что показать: документ датасета и цитату, которую надо подсветить. */
export interface DocRequest {
  dataset: string
  package: string
  file: string
  quote?: string
}

const open = ref(false)
const request = ref<DocRequest | null>(null)

/** Зритель оригинала документа с подсветкой цитаты — один на все экраны. */
export function useDocViewer() {
  return {
    open,
    request,
    show(req: DocRequest) {
      request.value = req
      open.value = true
    },
    hide() {
      open.value = false
    },
  }
}
