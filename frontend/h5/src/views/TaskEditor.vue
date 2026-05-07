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
          placeholder="支持文本和表情，媒体请通过下方上传"
        />
      </el-form-item>

      <el-form-item label="消息按钮（可选）">
        <el-input
          v-model="form.buttonsText"
          type="textarea"
          :rows="4"
          placeholder="每行一个按钮，格式：文字 - https://example.com&#10;同一行多个按钮用 && 分隔"
        />
        <div class="hint-text">
          示例：官网 - https://example.com && 社群 - https://t.me/yourgroup
        </div>
      </el-form-item>

      <el-form-item label="媒体文件（图片/GIF/视频）">
        <div class="media-actions">
          <input
            ref="mediaInputRef"
            class="hidden-input"
            type="file"
            accept="image/*,video/*,.gif"
            @change="onMediaFileChange"
          />
          <el-button @click="triggerMediaPicker" :disabled="!form.accountId">选择文件</el-button>
          <el-button v-if="hasMedia" type="danger" plain @click="clearMedia">清除媒体</el-button>
        </div>
        <div class="hint-text" v-if="!form.accountId">请先选择执行账号后再上传媒体</div>
        <div class="hint-text" v-else-if="form.mediaName">
          当前媒体: {{ form.mediaName }} ({{ prettyMediaType(form.mediaType) }})
        </div>
        <div class="hint-text" v-else>
          媒体将上传到 Telegram 收藏夹并复用，不占服务器磁盘；不上传则按纯文本发送
        </div>
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
import { createTask, getTask, updateTask, uploadTaskMedia } from '@/api/task'
import {
  resourceKey,
  resourceLabel,
  parseResourceKey,
  getPeerTypeMeta,
  displayResourceName,
  normalizeButtonUrl,
  parseButtonsText,
  formatButtonsText,
  toUnix,
  fromUnix,
  prettyMediaType,
  extractFileName,
  type ResourceOption
} from '@/utils/taskHelpers'

/* --------------- props & emits --------------- */

const props = defineProps<{
  accounts: Array<{ account_id: string; username?: string | null; first_name?: string | null; phone?: string | null }>
  tasks: TaskItem[]
  isCompact: boolean
}>()

const emit = defineEmits<{
  (e: 'update:resources', resources: ResourceOption[]): void
  (e: 'close'): void
  (e: 'saved'): void
  (e: 'runOnce', taskId: string, title: string): void
}>()

const accountStore = useAccountStore()

/* --------------- internal state --------------- */

const showEditor = ref(false)
const editingTaskId = ref('')
const submitting = ref(false)
const mediaInputRef = ref<HTMLInputElement | null>(null)
const resourceKeyword = ref('')
const resources = ref<ResourceOption[]>([])
const loadingResources = ref(false)

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
  mediaFileId: '',
  mediaName: '',
  mediaFile: null as File | null,
  startAtLocal: '',
  endAtLocal: '',
  enabled: false,
  deletePrevious: false,
  buttonsText: ''
})

/* --------------- computed --------------- */

const hasMedia = computed(() => Boolean(form.mediaFile || form.mediaFileId))

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

const filteredResources = computed(() => {
  const keyword = resourceKeyword.value.trim().toLowerCase()
  if (!keyword) return resources.value
  return resources.value.filter((res) => {
    const meta = getPeerTypeMeta(res.peer_type)
    const searchable = [
      displayResourceName(res),
      res.username || '',
      String(res.peer_id),
      meta.label,
      res.peer_type
    ]
      .join(' ')
      .toLowerCase()
    return searchable.includes(keyword)
  })
})

/* --------------- resource loading --------------- */

const loadResources = async (autoSyncIfEmpty = false, preserveTargets = true) => {
  if (!form.accountId) {
    resources.value = []
    form.targetKeys = []
    emit('update:resources', [])
    return
  }

  const previousTargetKeys = preserveTargets ? [...form.targetKeys] : []
  resources.value = []
  if (!preserveTargets) {
    form.targetKeys = []
  }

  loadingResources.value = true
  try {
    const query = { is_active: true }
    const data = await accountStore.getAccountResources(form.accountId, query)
    resources.value = (data || []) as ResourceOption[]

    if (autoSyncIfEmpty && resources.value.length === 0) {
      ElMessage.info('正在同步聊天资源，请稍候...')
      const syncResult = await accountStore.syncAccount(form.accountId, true)
      ElMessage.info(syncResult.message || '该账号已加入同步队列，请稍后刷新资源列表')
    }

    if (preserveTargets && previousTargetKeys.length > 0) {
      const keySet = new Set(resources.value.map((item) => resourceKey(item)))
      form.targetKeys = previousTargetKeys.filter((key) => keySet.has(key))
    }

    emit('update:resources', [...resources.value])
  } catch {
    // HTTP errors already handled by the response interceptor
  } finally {
    loadingResources.value = false
  }
}

/* --------------- form handlers --------------- */

const onAccountChange = async () => {
  resourceKeyword.value = ''
  clearMedia()
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
  form.title = ''
  form.targetKeys = []
  form.text = ''
  form.triggerMode = 'scheduled'
  form.shortcutLabel = ''
  form.priority = 0
  form.repeatIntervalMin = 60
  form.mediaType = 'none'
  form.mediaFileId = ''
  form.mediaName = ''
  form.mediaFile = null
  form.startAtLocal = ''
  form.endAtLocal = ''
  form.enabled = false
  form.deletePrevious = false
  form.buttonsText = ''
  if (keepCurrentAccount) {
    form.accountId = currentAccountId
  } else {
    form.accountId = ''
  }
  if (mediaInputRef.value) {
    mediaInputRef.value.value = ''
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

/* --------------- media --------------- */

const triggerMediaPicker = () => {
  if (!form.accountId) {
    ElMessage.warning('请先选择执行账号')
    return
  }
  mediaInputRef.value?.click()
}

const onMediaFileChange = (event: Event) => {
  const target = event.target as HTMLInputElement
  const file = target.files && target.files[0] ? target.files[0] : null
  if (!file) return

  const maxSize = 20 * 1024 * 1024
  if (file.size > maxSize) {
    ElMessage.warning('媒体文件不能超过 20MB')
    target.value = ''
    return
  }

  const type = file.type.toLowerCase()
  const name = file.name.toLowerCase()
  let mediaType = 'none'

  if (type.startsWith('image/')) {
    mediaType = type === 'image/gif' || name.endsWith('.gif') ? 'animation' : 'photo'
  } else if (type.startsWith('video/')) {
    mediaType = 'video'
  } else if (name.endsWith('.gif')) {
    mediaType = 'animation'
  } else {
    ElMessage.warning('仅支持图片、GIF、视频文件')
    target.value = ''
    return
  }

  form.mediaFile = file
  form.mediaName = file.name
  form.mediaType = mediaType
  form.mediaFileId = ''
}

const clearMedia = () => {
  form.mediaFile = null
  form.mediaName = ''
  form.mediaType = 'none'
  form.mediaFileId = ''
  if (mediaInputRef.value) {
    mediaInputRef.value.value = ''
  }
}

/* --------------- payload & submit --------------- */

const buildPayload = (
  targets: ResourceOption[],
  mediaType: string,
  mediaFileId: string | null,
  buttons: Array<Array<{ text: string; url: string }>> | null
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
  media_type: mediaType,
  media_file_id: mediaType === 'none' ? null : mediaFileId,
  buttons,
  delete_previous: form.deletePrevious
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
    const buttons = parseButtonsText(form.buttonsText)
    let mediaType = (form.mediaType || 'none').toLowerCase()
    let mediaFileId: string | null = form.mediaFileId || null

    if (form.mediaFile) {
      const uploaded = await uploadTaskMedia(form.accountId, form.mediaFile)
      mediaType = (uploaded.data.media_type || 'none').toLowerCase()
      mediaFileId = uploaded.data.media_file_id
      form.mediaType = mediaType
      form.mediaFileId = mediaFileId || ''
      form.mediaName = uploaded.data.filename || form.mediaName
      form.mediaFile = null
      if (mediaInputRef.value) {
        mediaInputRef.value.value = ''
      }
    }

    if (!mediaFileId) {
      mediaType = 'none'
    }

    if (form.triggerMode === 'manual_shortcut' && !form.text.trim() && mediaType === 'none' && !buttons) {
      ElMessage.warning('手动任务至少需要填写文本、按钮或上传媒体中的一种内容')
      return
    }

    const targets = form.targetKeys
      .map((key) => parseResourceKey(key, resources.value))
      .filter((v): v is ResourceOption => Boolean(v))

    if (targets.length === 0) {
      ElMessage.warning('目标聊天无效，请重新选择')
      return
    }

    const payload = buildPayload(targets, mediaType, mediaFileId, buttons)

    if (editingTaskId.value) {
      await updateTask(editingTaskId.value, payload)
      ElMessage.success('任务已更新')
    } else {
      await createTask(payload)
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

/* --------------- public methods --------------- */

const openCreateForm = async (mode: 'scheduled' | 'manual_shortcut', initialAccountId?: string) => {
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
}

const startEdit = async (task: TaskItem) => {
  try {
    const detail = (await getTask(task.task_id)).data

    showEditor.value = true
    resourceKeyword.value = ''
    editingTaskId.value = detail.task_id
    form.title = detail.title
    form.accountId = detail.account_id || ''
    form.text = detail.text || ''
    form.triggerMode = detail.trigger_mode || 'scheduled'
    form.shortcutLabel = detail.shortcut_label || ''
    form.priority = detail.priority || 0
    form.repeatIntervalMin = detail.repeat_interval_min
    form.mediaType = (detail.media_type || 'none').toLowerCase()
    form.mediaFileId = detail.media_file_id || ''
    form.mediaName = detail.media_file_id ? extractFileName(detail.media_file_id) : ''
    form.mediaFile = null
    form.startAtLocal = fromUnix(detail.start_at)
    form.endAtLocal = fromUnix(detail.end_at)
    form.enabled = detail.enabled
    form.deletePrevious = detail.delete_previous
    form.buttonsText = formatButtonsText(detail.buttons)

    if (mediaInputRef.value) {
      mediaInputRef.value.value = ''
    }

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
  } catch {
    // HTTP errors already handled by the response interceptor
  }
}

const setTargetKeys = (keys: string[]) => {
  form.targetKeys = keys
}

defineExpose({ openCreateForm, startEdit, setTargetKeys })
</script>

<style scoped>
.editor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.8rem;
}

.card {
  background: white;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  padding: 1rem;
}

.card h2 {
  margin: 0;
  font-size: 1.05rem;
  color: #2c3e50;
}

.grid-two {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.8rem;
}

.form-actions {
  display: flex;
  gap: 0.6rem;
}

.hidden-input {
  display: none;
}

.media-actions {
  display: flex;
  gap: 0.6rem;
}

.hint-text {
  margin-top: 0.35rem;
  color: #606266;
  font-size: 0.85rem;
  line-height: 1.4;
}

@media (max-width: 768px) {
  .card {
    padding: 0.85rem;
  }

  .editor-header {
    align-items: flex-start;
    gap: 0.4rem;
    flex-direction: column;
  }

  .grid-two {
    grid-template-columns: 1fr;
    gap: 0.2rem;
  }

  .media-actions {
    flex-wrap: wrap;
  }

  .media-actions :deep(.el-button) {
    flex: 1 1 calc(50% - 0.3rem);
    min-width: 0;
  }

  .form-actions {
    flex-wrap: wrap;
  }

  .form-actions :deep(.el-button) {
    flex: 1 1 calc(50% - 0.3rem);
    min-width: 0;
  }
}

@media (max-width: 480px) {
  .media-actions :deep(.el-button),
  .form-actions :deep(.el-button) {
    flex-basis: 100%;
  }
}
</style>
