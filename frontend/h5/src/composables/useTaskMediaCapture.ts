import { computed, ref, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  clearTaskMedia,
  createTaskMediaCapture,
  getTask,
  getTaskMediaCapture
} from '@/api/task'

export interface TaskMediaFormState {
  accountId: string
  mediaType: string
  mediaSourceState: string
  mediaSourceMeta: Record<string, unknown> | null
  revision: number
}

export const useTaskMediaCapture = (form: TaskMediaFormState, taskId: Ref<string>) => {
  const loading = ref(false)
  const captureId = ref('')
  const captureState = ref('')
  const hasMedia = computed(() => form.mediaType !== 'none' && form.mediaSourceState === 'valid')
  const summary = computed(() => {
    const filename = String(form.mediaSourceMeta?.filename || '').trim()
    const labels: Record<string, string> = { photo: '图片', video: '视频', animation: '动图' }
    const label = labels[form.mediaType] || form.mediaType
    return filename ? `${label}（${filename}）` : label
  })

  const reset = () => {
    form.mediaType = 'none'
    form.mediaSourceState = 'none'
    form.mediaSourceMeta = null
    captureId.value = ''
    captureState.value = ''
  }

  const start = async () => {
    if (!taskId.value) return
    const telegramWindow = window.open('', '_blank')
    if (!telegramWindow) {
      ElMessage.error('浏览器拦截了 Telegram 窗口，请允许本站打开新窗口后重试')
      return
    }
    telegramWindow.opener = null
    loading.value = true
    try {
      const capture = (await createTaskMediaCapture(taskId.value, form.revision)).data
      captureId.value = capture.capture_id
      captureState.value = capture.state
      telegramWindow.location.href = capture.bot_deep_link
      ElMessage.info('请在 Bot 中直接回复一张图片、一个视频或一个 GIF，系统会自动识别类型')
    } catch (error) {
      telegramWindow.close()
      throw error
    } finally {
      loading.value = false
    }
  }

  const refresh = async () => {
    if (!taskId.value || !captureId.value) return
    loading.value = true
    try {
      const capture = (await getTaskMediaCapture(taskId.value, captureId.value)).data
      captureState.value = capture.state
      if (capture.state === 'completed') await reloadCompletedMedia()
      if (capture.state === 'failed' || capture.state === 'expired') {
        ElMessage.error(capture.error_code || '媒体设置失败')
      }
    } finally {
      loading.value = false
    }
  }

  const reloadCompletedMedia = async () => {
    const detail = (await getTask(taskId.value)).data
    form.mediaType = detail.media_type
    form.mediaSourceState = detail.media_source_state
    form.mediaSourceMeta = detail.media_source_meta
    form.revision = detail.revision
    ElMessage.success('Telegram 媒体已设置')
  }

  const clear = async () => {
    if (!taskId.value) return
    loading.value = true
    try {
      const response = await clearTaskMedia(taskId.value, form.revision)
      form.revision = response.data.revision
      reset()
      ElMessage.success('任务媒体引用已清除，Telegram 收藏夹原消息未删除')
    } finally {
      loading.value = false
    }
  }

  return { loading, captureId, captureState, hasMedia, summary, reset, start, refresh, clear }
}
