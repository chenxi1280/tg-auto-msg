import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const MOBILE_BREAKPOINT = 960
const COMPACT_BREAKPOINT = 768

export const useResponsive = () => {
  const width = ref(typeof window === 'undefined' ? 1280 : window.innerWidth)

  const updateWidth = () => {
    width.value = window.innerWidth
  }

  onMounted(() => {
    updateWidth()
    window.addEventListener('resize', updateWidth, { passive: true })
  })

  onBeforeUnmount(() => {
    window.removeEventListener('resize', updateWidth)
  })

  const isMobile = computed(() => width.value <= MOBILE_BREAKPOINT)
  const isCompact = computed(() => width.value <= COMPACT_BREAKPOINT)

  return {
    width,
    isMobile,
    isCompact,
  }
}
