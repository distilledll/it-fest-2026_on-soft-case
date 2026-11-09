import { onMounted, ref, watch, type Ref } from 'vue'

/** Плавный набор числа от 0 к значению — для крупного индекса на дашборде. */
export function useCountUp(source: () => number, duration = 900): Ref<number> {
  const display = ref(0)
  let frame = 0

  function to(target: number) {
    cancelAnimationFrame(frame)
    const from = display.value
    const start = performance.now()
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      const eased = 1 - Math.pow(1 - t, 3)
      display.value = Math.round((from + (target - from) * eased) * 10) / 10
      if (t < 1) frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
  }

  onMounted(() => to(source()))
  watch(source, (v) => to(v))

  return display
}
