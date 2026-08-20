<template>
  <div v-if="showEditor" class="editor card">
    <div class="editor-header">
      <h2>{{ editingTaskId ? '编辑任务' : (form.triggerMode === 'manual_shortcut' ? '创建手动任务' : '创建定时任务') }}</h2>
      <el-button text @click="closeEditor">返回任务管理</el-button>
    </div>
    <el-form label-position="top">
      <el-form-item label="任务名称">
        <el-input v-model="form.title" placeholder="例如：午间频道推送；不填则自动生成未命名任务" />
      </el-form-item>

      <el-form-item v-if="editingTaskId" label="任务类型">
        <el-radio-group v-model="form.triggerMode" @change="onTriggerModeChange">
          <el-radio label="scheduled">定时任务</el-radio>
          <el-radio label="manual_shortcut">手动任务</el-radio>
        </el-radio-group>
        <div class="hint-text">
          手动任务不会自动调度，只会在 Bot 底部快捷按钮或"立即执行一次"时触发。
        </div>
      </el-form-item>

      <template v-if="form.triggerMode === 'manual_shortcut'">
        <el-form-item label="Bot 底部按钮名称" :error="shortcutLabelError || undefined">
          <el-input
            v-model="form.shortcutLabel"
            maxlength="20"
            show-word-limit
            placeholder="例如：开课通知"
          />
          <div class="hint-text">
            将出现在 Bot 底部按钮中，建议使用简短、容易识别的名称。
          </div>
        </el-form-item>
        <div class="hint-text">
          手动任务创建后会自动占用 1-3 号按钮位中的一个，普通用户最多只能保留 3 个手动任务。
        </div>
      </template>

      <el-form-item label="执行账号">
        <el-select v-model="form.accountId" placeholder="请选择账号" style="width: 100%" @change="onAccountChange">
          <el-option
            v-for="account in accounts"
            :key="account.account_id"
            :label="account.username || account.phone || '未命名账号'"
            :value="account.account_id"
          />
        </el-select>
      </el-form-item>

      <el-form-item label="目标聊天（支持多选）">
        <el-select
          v-model="form.targetKeys"
          multiple
          filterable
          clearable
          :filter-method="onTargetFilter"
          collapse-tags
          collapse-tags-tooltip
          :placeholder="form.accountId ? '请选择群组/频道/用户' : '请先选择执行账号'"
          style="width: 100%"
          :disabled="!form.accountId"
        >
          <el-option
            v-for="res in filteredResources"
            :key="resourceKey(res)"
            :label="resourceLabel(res)"
            :value="resourceKey(res)"
          />
        </el-select>
        <div v-if="loadingResources" class="hint-text">正在加载聊天资源...</div>
        <div v-else class="hint-text">共 {{ resources.length }} 个聊天，当前筛选 {{ filteredResources.length }} 个</div>
      </el-form-item>

      <el-form-item label="消息文本">
        <el-input
          v-model="form.text"
          type="textarea"
          :rows="5"
          maxlength="4096"
          show-word-limit
          placeholder="支持文本和表情；有媒体时这里作为媒体说明文字"
        />
      </el-form-item>

      <el-form-item label="Telegram 媒体（单张图片/视频/动图）">
        <div class="media-actions">
          <el-button
            type="primary"
            plain
            :loading="mediaCaptureLoading"
            :disabled="!editingTaskId || !form.accountId"
            @click="startMediaCapture"
          >前往 Telegram Bot 设置媒体</el-button>
          <el-button v-if="activeCaptureId" :loading="mediaCaptureLoading" @click="refreshMediaCapture">
            检查设置状态
          </el-button>
          <el-button v-if="hasMedia" type="danger" plain :loading="mediaCaptureLoading" @click="clearMedia">
            清除媒体
          </el-button>
        </div>
        <div class="hint-text" v-if="!editingTaskId">请先保存任务，再通过执行账号进入 Telegram Bot 设置媒体。</div>
        <div class="hint-text" v-else-if="hasMedia">
          当前媒体：{{ mediaSummary }}；来源保存在执行账号的 Telegram 收藏夹，服务器不保存文件。
        </div>
        <div class="hint-text" v-else>
          未设置媒体；任务将按纯文本发送。普通文件、贴纸、语音和相册不支持。
        </div>
        <div v-if="activeCaptureId" class="hint-text">捕获状态：{{ mediaCaptureState }}</div>
      </el-form-item>

      <div class="grid-two">
        <el-form-item label="任务优先级">
          <el-input-number v-model="form.priority" :min="0" :max="1000" style="width: 100%" />
        </el-form-item>
        <el-form-item label="发送间隔（分钟）">
          <el-input-number
            v-model="form.repeatIntervalMin"
            :min="1"
            :max="1440"
            :disabled="form.triggerMode === 'manual_shortcut'"
            style="width: 100%"
          />
        </el-form-item>
      </div>

      <div class="hint-text" v-if="form.triggerMode !== 'manual_shortcut'">
        系统会自动生成 30 秒到 5 分钟的随机延迟与抖动参数，不需要手工配置。
      </div>
      <div class="hint-text" v-else>
        手动任务不参与自动调度，开始/结束时间与下次执行时间不生效。
      </div>

      <div v-if="form.triggerMode !== 'manual_shortcut'" class="grid-two">
        <el-form-item label="开始时间（可选）">
          <el-input v-model="form.startAtLocal" type="datetime-local" />
        </el-form-item>
        <el-form-item label="结束时间（可选）">
          <el-input v-model="form.endAtLocal" type="datetime-local" />
        </el-form-item>
      </div>

      <div class="grid-two">
        <el-form-item label="启用任务">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-form-item label="删除上一条">
          <el-switch v-model="form.deletePrevious" />
        </el-form-item>
      </div>

      <div class="form-actions">
        <el-button type="primary" :loading="submitting" @click="submitTask">
          {{ editingTaskId ? '保存修改' : (form.triggerMode === 'manual_shortcut' ? '创建手动任务' : '创建定时任务') }}
        </el-button>
        <el-button
          v-if="editingTaskId"
          type="success"
          plain
          :disabled="!form.enabled"
          @click="emit('runOnce', editingTaskId, form.title)"
        >
          立即执行一次
        </el-button>
        <el-button v-if="editingTaskId" @click="cancelEdit">取消编辑</el-button>
        <el-button @click="closeEditor">返回任务管理</el-button>
      </div>
    </el-form>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useAccountStore } from '@/stores/account'
import type { TaskItem } from '@/api/task'
import { createTask, getTask, updateTask } from '@/api/task'
import { useTaskMediaCapture } from '@/composables/useTaskMediaCapture'
import { useTaskResources } from '@/composables/useTaskResources'
import {
  resourceKey,
  resourceLabel,
  parseResourceKey,
  toUnix,
  fromUnix,
  type ResourceOption
} from '@/utils/taskHelpers'

const props = defineProps<{
  accounts: Array<{ account_id: string; username?: string | null; first_name?: string | null; phone?: string | null }>
  tasks: TaskItem[]
  isCompact: boolean
}>()

const emit = defineEmits<{
  (e: 'update:resources', resources: ResourceOption[]): void
  (e: 'close'): void
  (e: 'saved'): void
  (e: 'draftCreated'): void
  (e: 'runOnce', taskId: string, title: string): void
}>()

const accountStore = useAccountStore()

const showEditor = ref(false)
const editingTaskId = ref('')
const submitting = ref(false)
const persistedAccountId = ref('')
const persistedText = ref('')
const form = reactive({
  title: '',
  accountId: '',
  targetKeys: [] as string[],
  text: '',
  triggerMode: 'scheduled',
  shortcutLabel: '',
  priority: 0,
  repeatIntervalMin: 60,
  mediaType: 'none',
  mediaSourceState: 'none',
  mediaSourceMeta: null as Record<string, unknown> | null,
  revision: 1,
  startAtLocal: '',
  endAtLocal: '',
  enabled: false,
  deletePrevious: false
})

const {
  loading: mediaCaptureLoading,
  captureId: activeCaptureId,
  captureState: mediaCaptureState,
  hasMedia,
  summary: mediaSummary,
  reset: resetMediaCapture,
  start: requestMediaCapture,
  refresh: refreshMediaCapture,
  clear: clearMedia
} = useTaskMediaCapture(form, editingTaskId)

const startMediaCapture = async () => {
  const captureFieldsChanged = (
    form.accountId !== persistedAccountId.value || form.text !== persistedText.value
  )
  if (captureFieldsChanged) {
    ElMessage.warning('执行账号或消息文本有未保存修改，请先保存任务，再设置媒体')
    return
  }
  await requestMediaCapture()
}

const {
  keyword: resourceKeyword,
  resources,
  loading: loadingResources,
  filtered: filteredResources,
  load: loadResources
} = useTaskResources(accountStore, form, (items) => emit('update:resources', items))

const normalizeShortcutLabel = (value: string | null | undefined) =>
  (value || '').trim().toLocaleLowerCase()

const shortcutLabelError = computed(() => {
  if (form.triggerMode !== 'manual_shortcut') return ''
  const label = form.shortcutLabel.trim()
  if (!label) return ''
  const normalized = normalizeShortcutLabel(label)
  const duplicated = props.tasks.some((task) => {
    if (task.trigger_mode !== 'manual_shortcut') return false
    if (editingTaskId.value && task.task_id === editingTaskId.value) return false
    return normalizeShortcutLabel(task.shortcut_label) === normalized
  })
  return duplicated ? '快捷名称已存在，请换一个名称' : ''
})

const onAccountChange = async () => {
  resourceKeyword.value = ''
  resetMediaCapture()
  await loadResources(true, false)
}

const onTriggerModeChange = () => {
  if (form.triggerMode !== 'manual_shortcut') {
    form.shortcutLabel = ''
  }
}

const onTargetFilter = (keyword: string) => {
  resourceKeyword.value = keyword || ''
}

const resetForm = (keepCurrentAccount = true) => {
  const currentAccountId = form.accountId
  editingTaskId.value = ''
  persistedAccountId.value = ''
  persistedText.value = ''
  form.title = ''
  form.targetKeys = []
  form.text = ''
  form.triggerMode = 'scheduled'
  form.shortcutLabel = ''
  form.priority = 0
  form.repeatIntervalMin = 60
  form.mediaType = 'none'
  form.mediaSourceState = 'none'
  form.mediaSourceMeta = null
  form.revision = 1
  form.startAtLocal = ''
  form.endAtLocal = ''
  form.enabled = false
  form.deletePrevious = false
  resetMediaCapture()
  if (keepCurrentAccount) {
    form.accountId = currentAccountId
  } else {
    form.accountId = ''
  }
}

const closeEditor = () => {
  showEditor.value = false
  editingTaskId.value = ''
  emit('close')
}

const cancelEdit = () => {
  resetForm(true)
  showEditor.value = false
  emit('close')
}

const buildPayload = (
  targets: ResourceOption[]
) => ({
  ...(() => {
    const primaryTarget = targets[0]!
    return {
      chat_id: primaryTarget.peer_id,
      target_peer_id: primaryTarget.peer_id,
      target_peer_type: primaryTarget.peer_type,
      target_access_hash: primaryTarget.access_hash
    }
  })(),
  account_id: form.accountId,
  target_peers: targets.map((target) => ({
    peer_id: target.peer_id,
    peer_type: target.peer_type,
    access_hash: target.access_hash
  })),
  title: form.title,
  enabled: form.enabled,
  trigger_mode: form.triggerMode,
  shortcut_label: form.triggerMode === 'manual_shortcut' ? (form.shortcutLabel.trim() || null) : null,
  priority: form.priority,
  repeat_interval_min: form.repeatIntervalMin,
  start_at: form.triggerMode === 'manual_shortcut' ? null : toUnix(form.startAtLocal),
  end_at: form.triggerMode === 'manual_shortcut' ? null : toUnix(form.endAtLocal),
  text: form.text || null,
  delete_previous: form.deletePrevious,
  ...(editingTaskId.value ? { expected_revision: form.revision } : {})
})

const submitTask = async () => {
  if (!form.accountId) {
    ElMessage.warning('请选择执行账号')
    return
  }
  if (form.targetKeys.length === 0) {
    ElMessage.warning('请至少选择一个目标聊天')
    return
  }
  if (form.triggerMode === 'manual_shortcut' && !form.shortcutLabel.trim()) {
    ElMessage.warning('请填写手动任务的按钮名称')
    return
  }
  if (shortcutLabelError.value) {
    ElMessage.warning(shortcutLabelError.value)
    return
  }

  const startAt = toUnix(form.startAtLocal)
  const endAt = toUnix(form.endAtLocal)
  if (form.triggerMode !== 'manual_shortcut' && startAt && endAt && endAt < startAt) {
    ElMessage.warning('结束时间不能早于开始时间')
    return
  }

  submitting.value = true
  try {
    const targets = form.targetKeys
      .map((key) => parseResourceKey(key, resources.value))
      .filter((v): v is ResourceOption => Boolean(v))

    if (targets.length === 0) {
      ElMessage.warning('目标聊天无效，请重新选择')
      return
    }

    const createAsMediaDraft = !editingTaskId.value && !form.text.trim() && !hasMedia.value
    const payload = {
      ...buildPayload(targets),
      ...(createAsMediaDraft ? { enabled: false } : {})
    }

    if (editingTaskId.value) {
      const response = await updateTask(editingTaskId.value, payload)
      form.revision = response.data.revision
      ElMessage.success('任务已更新')
    } else {
      const response = await createTask(payload)
      if (createAsMediaDraft) {
        editingTaskId.value = response.data.task_id
        form.revision = response.data.revision
        form.enabled = false
        persistedAccountId.value = form.accountId
        persistedText.value = form.text
        ElMessage.info('禁用草稿已创建，现在可以前往 Telegram Bot 设置媒体')
        emit('draftCreated')
        return
      }
      ElMessage.success(`任务已创建，目标数 ${targets.length}`)
    }

    resetForm(true)
    showEditor.value = false
    emit('saved')
  } catch {
    // HTTP errors already handled by the response interceptor
  } finally {
    submitting.value = false
  }
}

const openCreateForm = async (mode: 'scheduled' | 'manual_shortcut', initialAccountId?: string): Promise<boolean> => {
  resetForm(true)
  form.triggerMode = mode
  form.enabled = mode === 'manual_shortcut'
  if (initialAccountId) {
    form.accountId = initialAccountId
  } else if (!form.accountId && props.accounts.length > 0) {
    form.accountId = props.accounts[0]!.account_id
  }
  if (form.accountId) {
    await loadResources(true, false)
  }
  showEditor.value = true
  return true
}

const startEdit = async (task: TaskItem): Promise<boolean> => {
  try {
    const detail = (await getTask(task.task_id)).data

    resourceKeyword.value = ''
    editingTaskId.value = detail.task_id
    form.title = detail.title
    form.accountId = detail.account_id || ''
    form.text = detail.text || ''
    persistedAccountId.value = form.accountId
    persistedText.value = form.text
    form.triggerMode = detail.trigger_mode || 'scheduled'
    form.shortcutLabel = detail.shortcut_label || ''
    form.priority = detail.priority || 0
    form.repeatIntervalMin = detail.repeat_interval_min
    form.mediaType = (detail.media_type || 'none').toLowerCase()
    form.mediaSourceState = detail.media_source_state || 'none'
    form.mediaSourceMeta = detail.media_source_meta
    form.revision = detail.revision
    form.startAtLocal = fromUnix(detail.start_at)
    form.endAtLocal = fromUnix(detail.end_at)
    form.enabled = detail.enabled
    form.deletePrevious = detail.delete_previous

    if (form.accountId) {
      await loadResources(false, false)
      if (Array.isArray(detail.target_peers) && detail.target_peers.length > 0) {
        form.targetKeys = detail.target_peers.map((peer) => `${peer.peer_type}:${peer.peer_id}`)
      } else if (detail.target_peer_id && detail.target_peer_type) {
        form.targetKeys = [`${detail.target_peer_type}:${detail.target_peer_id}`]
      } else if (detail.chat_id) {
        const found = resources.value.find(r => r.peer_id === detail.chat_id)
        form.targetKeys = found ? [resourceKey(found)] : []
      }
    }
    showEditor.value = true
    return true
  } catch {
    // HTTP errors already handled by the response interceptor
    return false
  }
}

const setTargetKeys = (keys: string[]) => {
  form.targetKeys = keys
}

defineExpose({ openCreateForm, startEdit, setTargetKeys })
</script>

<style scoped src="@/assets/task-editor.css"></style>
