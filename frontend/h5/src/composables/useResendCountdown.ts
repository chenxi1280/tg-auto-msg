import { computed, onUnmounted, ref } from 'vue'

const MILLISECONDS_PER_SECOND = 1000

const normalizeSeconds = (value: unknown): number => {
  const seconds = Number(value)
  return Number.isFinite(seconds) ? Math.max(0, Math.ceil(seconds)) : 0
}

export const useResendCountdown = () => {
  const resendRemainingSeconds = ref(0)
  let deadlineMs = 0
  let timer: ReturnType<typeof setInterval> | null = null

  const canResend = computed(() => resendRemainingSeconds.value === 0)

  const stopResendCountdown = () => {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
    deadlineMs = 0
    resendRemainingSeconds.value = 0
  }

  const refreshRemainingSeconds = () => {
    const millisecondsRemaining = deadlineMs - Date.now()
    resendRemainingSeconds.value = Math.max(0, Math.ceil(millisecondsRemaining / MILLISECONDS_PER_SECOND))
    if (resendRemainingSeconds.value === 0) {
      stopResendCountdown()
    }
  }

  const startResendCountdown = (seconds: unknown) => {
    const normalizedSeconds = normalizeSeconds(seconds)
    stopResendCountdown()
    if (normalizedSeconds === 0) {
      return
    }
    deadlineMs = Date.now() + normalizedSeconds * MILLISECONDS_PER_SECOND
    refreshRemainingSeconds()
    timer = setInterval(refreshRemainingSeconds, MILLISECONDS_PER_SECOND)
  }

  onUnmounted(stopResendCountdown)

  return {
    canResend,
    resendRemainingSeconds,
    startResendCountdown,
    stopResendCountdown
  }
}
