<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import { getDocument } from '@/api/datasets'
import { ApiError } from '@/api/http'
import { useDocViewer } from '@/composables/useDocViewer'

const { open, request, hide } = useDocViewer()

const text = ref('')
const meta = ref<{ encoding?: string; warnings: string[]; is_empty?: boolean } | null>(null)
const loading = ref(false)
const error = ref('')
const preEl = ref<HTMLElement | null>(null)

const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** Ищем цитату терпимо: точное вхождение, иначе — по словам с любыми пробелами (переносы строк в таблицах). */
function findQuote(hay: string, needle: string): [number, number] | null {
  const q = needle.trim()
  if (!hay || !q) return null
  const exact = hay.indexOf(q)
  if (exact >= 0) return [exact, exact + q.length]
  const words = q.split(/\s+/).filter(Boolean).map(esc)
  if (!words.length) return null
  const m = new RegExp(words.join('\\s+'), 'i').exec(hay) ?? new RegExp(words.join('\\s*'), 'i').exec(hay)
  return m && m[0] ? [m.index, m.index + m[0].length] : null
}

const pieces = computed(() => {
  const t = text.value
  const q = request.value?.quote ?? ''
  const at = findQuote(t, q)
  if (!at) return [{ t, hit: false }]
  return [
    { t: t.slice(0, at[0]), hit: false },
    { t: t.slice(at[0], at[1]), hit: true },
    { t: t.slice(at[1]), hit: false },
  ]
})

const found = computed(() => pieces.value.some((p) => p.hit))

async function load() {
  const req = request.value
  if (!req || !open.value) return
  loading.value = true
  error.value = ''
  text.value = ''
  meta.value = null
  try {
    const doc = await getDocument(req.dataset, req.package, req.file)
    if (!open.value || request.value !== req) return
    text.value = doc.text ?? ''
    meta.value = { encoding: doc.encoding, warnings: doc.warnings ?? [], is_empty: doc.is_empty }
    loading.value = false
    await nextTick()
    preEl.value?.querySelector('mark')?.scrollIntoView({ block: 'center' })
  } catch (e) {
    if (!open.value || request.value !== req) return
    error.value = e instanceof ApiError ? e.message : 'не удалось открыть документ'
  } finally {
    if (open.value && request.value === req) loading.value = false
  }
}

watch([open, request], load)

function onKey(e: KeyboardEvent) {
  if (e.key !== 'Escape' || !open.value) return
  // Escape закрывает только зритель документа — вопрос под ним остаётся живым
  e.stopPropagation()
  hide()
}

watch(open, (on) => {
  if (on) window.addEventListener('keydown', onKey, true)
  else window.removeEventListener('keydown', onKey, true)
})
</script>

<template>
  <transition name="scale-fade">
    <div v-if="open && request" class="modal-backdrop doc__backdrop" @click.self="hide">
      <div class="modal doc" role="dialog" aria-modal="true" aria-labelledby="doc-title">
        <button class="icon-btn modal__close" type="button" aria-label="Закрыть" @click="hide">
          <AppIcon name="close" />
        </button>

        <header class="modal__head doc__head">
          <p class="eyebrow">Оригинал документа</p>
          <h2 id="doc-title" class="mono doc__file">{{ request.file }}</h2>
          <p class="muted doc__where">
            закупка {{ request.package }}
            <template v-if="meta?.encoding"> · кодировка {{ meta.encoding }}</template>
          </p>
          <p v-if="request.quote" class="doc__needled muted">
            Ищем в тексте: «{{ request.quote.length > 140 ? request.quote.slice(0, 140) + '…' : request.quote }}»
          </p>
        </header>

        <p v-if="error" class="callout callout--bad">
          <AppIcon name="alert" size="sm" /> {{ error }}
        </p>
        <p v-else-if="loading" class="doc__wait muted"><AppIcon name="activity" size="sm" /> Открываем документ…</p>
        <p v-else-if="meta?.warnings.length" class="callout callout--warn doc__warn">
          <AppIcon name="alert" size="sm" /> {{ meta.warnings.join(' · ') }}
        </p>
        <p v-else-if="!found && request.quote" class="callout callout--warn doc__warn">
          <AppIcon name="alert" size="sm" /> Цитату дословно в этом файле не нашли — возможно, модель
          пересказала её своими словами. Показываем текст целиком, ничего не подсвечиваем.
        </p>

        <pre v-if="!loading && !error" ref="preEl" class="doc__text"><template v-for="(p, i) in pieces"><mark v-if="p.hit" :key="i">{{ p.t }}</mark><template v-else>{{ p.t }}</template></template></pre>
      </div>
    </div>
  </transition>
</template>

<style scoped>
.doc__backdrop {
  z-index: 90;
}

.doc {
  width: min(860px, 100%);
}

.doc__head {
  margin-bottom: var(--s-4);
}

.doc__file {
  font-size: 16px;
  word-break: break-all;
}

.doc__where,
.doc__needled {
  font-size: 13px;
  margin-top: 2px;
}

.doc__needled {
  color: var(--text-muted);
}

.doc__wait {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13.5px;
}

.doc__warn {
  margin-bottom: var(--s-4);
}

.doc__text {
  margin: 0;
  padding: var(--s-4);
  max-height: 56vh;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 12.5px;
  line-height: 1.55;
  background: var(--surface-inset);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
}

.doc__text mark {
  background: color-mix(in srgb, var(--accent) 26%, transparent);
  color: inherit;
  border-radius: 3px;
  padding: 1px 0;
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 45%, transparent);
}
</style>
