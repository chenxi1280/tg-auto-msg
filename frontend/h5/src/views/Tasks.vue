<template>
  <div class="tasks-page">
    <header class="header">
      <div class="container">
        <router-link to="/accounts" class="back-link">← 返回账号列表</router-link>
        <div class="brand-header">
          <img class="brand-logo" src="/quanqiu.png" alt="全球通" />
          <h1>全球通任务管理</h1>
        </div>
      </div>
    </header>

    <div v-if="!showEditor" class="toolbar">
      <div class="container toolbar-inner">
        <el-button type="primary" @click="openCreateForm('scheduled')">
          创建定时任务
        </el-button>
        <el-button
          type="success"
          plain
          :disabled="manualTaskCount >= 3"
          @click="openCreateForm('manual_shortcut')"
        >
          创建手动任务
        </el-button>
        <el-button :loading="loadingTasks" @click="loadTasks">
          刷新任务
        </el-button>
        <span class="summary">共 {{ tasks.length }} 个任务</span>
      </div>
    </div>

    <div class="container main">
      <div v-if="showEditor" class="editor card">
        <div class="editor-header">
          <h2>{{ editingTaskId ? '编辑任务' : (form.triggerMode === 'manual_shortcut' ? '创建手动任务' : '创建定时任务') }}</h2>
          <el-button text @click="closeEditor">返回任务管理</el-button>
        </div>
        <el-form label-position="top">
          <el-form-item label="任务名称">
            <el-input v-model="form.title" placeholder="例如：午间频道推送" />
          </el-form-item>

          <el-form-item v-if="editingTaskId" label="任务类型">
            <el-radio-group v-model="form.triggerMode" @change="onTriggerModeChange">
              <el-radio label="scheduled">定时任务</el-radio>
              <el-radio label="manual_shortcut">手动任务</el-radio>
            </el-radio-group>
            <div class="hint-text">
              手动任务不会自动调度，只会在 Bot 底部快捷按钮或“立即执行一次”时触发。
            </div>
          </el-form-item>

          <template v-if="form.triggerMode === 'manual_shortcut'">
            <el-form-item label="快捷名称">
              <el-input
                v-model="form.shortcutLabel"
                maxlength="20"
                show-word-limit
                placeholder="例如：开课通知"
              />
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
              @click="runTaskOnce(editingTaskId, form.title)"
            >
              立即执行一次
            </el-button>
            <el-button v-if="editingTaskId" @click="cancelEdit">取消编辑</el-button>
            <el-button @click="closeEditor">返回任务管理</el-button>
          </div>
        </el-form>
      </div>

      <div v-if="!showEditor" class="list card">
        <h2>任务列表</h2>
        <div class="table-wrap">
          <el-table v-if="!isCompact" :data="tasks" stripe v-loading="loadingTasks">
            <el-table-column prop="title" label="任务名" min-width="260" show-overflow-tooltip />
            <el-table-column label="类型/快捷栏" width="150">
              <template #default="{ row }">
                <div>{{ row.trigger_mode === 'manual_shortcut' ? '手动任务' : '定时任务' }}</div>
                <div class="table-subtext">
                  {{ row.shortcut_slot ? `槽位 ${row.shortcut_slot}` : '-' }}
                </div>
              </template>
            </el-table-column>
            <el-table-column label="目标" min-width="280">
              <template #default="{ row }">
                {{ renderTaskTarget(row) }}
              </template>
            </el-table-column>
            <el-table-column label="优先级" width="90">
              <template #default="{ row }">
                {{ row.priority ?? 0 }}
              </template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-switch v-model="row.enabled" @change="handleTaskEnabledChange(row, $event)" />
              </template>
            </el-table-column>
            <el-table-column label="间隔/抖动" width="140">
              <template #default="{ row }">
                {{ row.trigger_mode === 'manual_shortcut' ? '手动触发' : `${row.repeat_interval_min}m / ${row.jitter_seconds}s` }}
              </template>
            </el-table-column>
            <el-table-column label="下次执行" width="185">
              <template #default="{ row }">
                {{ row.trigger_mode === 'manual_shortcut' ? '-' : formatUnix(row.next_run_at) }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="280" fixed="right">
              <template #default="{ row }">
                <el-button type="success" link @click="runTaskOnce(row.task_id, row.title)">立即执行</el-button>
                <el-button type="primary" link @click="openTaskLogs(row.task_id)">发送记录</el-button>
                <el-button type="primary" link @click="startEdit(row)">编辑</el-button>
                <el-button type="danger" link @click="removeTask(row.task_id)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div v-else class="mobile-card-list" v-loading="loadingTasks">
            <div v-for="row in tasks" :key="row.task_id" class="mobile-data-card">
              <div class="mobile-data-card__header">
                <div>
                  <div class="mobile-data-card__title">{{ row.title }}</div>
                  <div class="mobile-data-card__subtitle">{{ renderTaskTarget(row) }}</div>
                </div>
                <el-switch v-model="row.enabled" @change="handleTaskEnabledChange(row, $event)" />
              </div>
              <div class="mobile-data-card__grid">
                <div class="mobile-data-card__row">
                  <span class="mobile-data-card__label">类型/快捷栏</span>
                  <span class="mobile-data-card__value">
                    {{ row.trigger_mode === 'manual_shortcut' ? '手动任务' : '定时任务' }}
                    <template v-if="row.shortcut_slot"> · 槽位 {{ row.shortcut_slot }}</template>
                  </span>
                </div>
                <div class="mobile-data-card__row">
                  <span class="mobile-data-card__label">优先级</span>
                  <span class="mobile-data-card__value">{{ row.priority ?? 0 }}</span>
                </div>
                <div class="mobile-data-card__row">
                  <span class="mobile-data-card__label">间隔/抖动</span>
                  <span class="mobile-data-card__value">
                    {{ row.trigger_mode === 'manual_shortcut' ? '手动触发' : `${row.repeat_interval_min}m / ${row.jitter_seconds}s` }}
                  </span>
                </div>
                <div class="mobile-data-card__row">
                  <span class="mobile-data-card__label">下次执行</span>
                  <span class="mobile-data-card__value">{{ row.trigger_mode === 'manual_shortcut' ? '-' : formatUnix(row.next_run_at) }}</span>
                </div>
              </div>
              <div class="mobile-action-bar">
                <el-button type="success" plain @click="runTaskOnce(row.task_id, row.title)">立即执行</el-button>
                <el-button type="primary" plain @click="openTaskLogs(row.task_id)">发送记录</el-button>
                <el-button type="primary" plain @click="startEdit(row)">编辑</el-button>
                <el-button type="danger" plain @click="removeTask(row.task_id)">删除</el-button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAccountStore } from '@/stores/account'
import { useUserStore } from '@/stores/user'
import type { TaskItem, TaskDetail } from '@/api/task'
import { createTask, deleteTask, getTask, getTasks, triggerTask, updateTask, uploadTaskMedia } from '@/api/task'
import { useResponsive } from '@/composables/useResponsive'

interface ResourceOption {
  peer_id: number
  peer_type: string
  access_hash: number | null
  title: string
  username?: string | null
}

const accountStore = useAccountStore()
const userStore = useUserStore()
const route = useRoute()
const router = useRouter()
const { isCompact } = useResponsive()

const tasks = ref<TaskItem[]>([])
const resources = ref<ResourceOption[]>([])
const loadingTasks = ref(false)
const loadingResources = ref(false)
const submitting = ref(false)
const showEditor = ref(false)
const editingTaskId = ref<string>('')
const mediaInputRef = ref<HTMLInputElement | null>(null)
const resourceKeyword = ref('')

const accounts = computed(() => accountStore.accounts)
const manualTaskCount = computed(() => tasks.value.filter((task) => task.trigger_mode === 'manual_shortcut').length)

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

const hasMedia = computed(() => Boolean(form.mediaFile || form.mediaFileId))
const peerTypeMeta: Record<string, { icon: string; label: string }> = {
  user: { icon: '👤', label: '个人' },
  chat: { icon: '👥', label: '群组' },
  supergroup: { icon: '👥', label: '群组' },
  channel: { icon: '📢', label: '频道' }
}

const getPeerTypeMeta = (peerType: string) => {
  return peerTypeMeta[peerType] || { icon: '💬', label: peerType || '未知' }
}

const resourceKey = (res: ResourceOption) => `${res.peer_type}:${res.peer_id}`

const displayResourceName = (res: ResourceOption): string => {
  const title = (res.title || '').trim()
  if (title) return title
  if (res.username) return `@${res.username}`
  return `未命名${getPeerTypeMeta(res.peer_type).label}`
}

const resourceLabel = (res: ResourceOption) => {
  const meta = getPeerTypeMeta(res.peer_type)
  const name = displayResourceName(res)
  const suffix = res.username && !name.includes(`@${res.username}`) ? ` (@${res.username})` : ''
  return `${meta.icon} ${meta.label} · ${name}${suffix}`
}

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

const normalizeButtonUrl = (rawUrl: string): string => {
  const candidate = rawUrl.trim()
  if (!candidate) return ''
  const withProtocol = /^https?:\/\//i.test(candidate) ? candidate : `https://${candidate}`
  try {
    const parsed = new URL(withProtocol)
    if (!['http:', 'https:'].includes(parsed.protocol)) return ''
    return parsed.toString()
  } catch (_err) {
    return ''
  }
}

const parseButtonsText = (text: string): Array<Array<{ text: string; url: string }>> | null => {
  const normalized = (text || '').trim()
  if (!normalized) return null

  const rows = normalized
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  if (rows.length > 3) {
    throw new Error('最多支持 3 行按钮')
  }

  const buttons: Array<Array<{ text: string; url: string }>> = []
  for (const row of rows) {
    const cols = row
      .split('&&')
      .map((col) => col.trim())
      .filter(Boolean)
    if (cols.length > 3) {
      throw new Error('每行最多支持 3 个按钮')
    }

    const rowButtons: Array<{ text: string; url: string }> = []
    for (const col of cols) {
      const delimiterIndex = col.indexOf(' - ')
      if (delimiterIndex <= 0) {
        throw new Error(`按钮格式错误: ${col}（请使用 “文字 - 链接”）`)
      }

      const textPart = col.slice(0, delimiterIndex).trim()
      const urlPart = col.slice(delimiterIndex + 3).trim()
      const url = normalizeButtonUrl(urlPart)
      if (!textPart || !url) {
        throw new Error(`按钮格式错误: ${col}`)
      }
      rowButtons.push({ text: textPart, url })
    }

    if (rowButtons.length > 0) {
      buttons.push(rowButtons)
    }
  }

  return buttons.length > 0 ? buttons : null
}

const formatButtonsText = (buttons: TaskDetail['buttons']): string => {
  if (!buttons || buttons.length === 0) return ''
  return buttons
    .map((row) => row.map((btn) => `${btn.text} - ${btn.url}`).join(' && '))
    .join('\n')
}

const parseResourceKey = (key: string): ResourceOption | null => {
  const [peerType, peerIdStr] = key.split(':')
  const peerId = Number(peerIdStr)
  if (!peerType || Number.isNaN(peerId)) return null
  return resources.value.find(r => r.peer_type === peerType && r.peer_id === peerId) || null
}

const toUnix = (localValue: string): number | null => {
  if (!localValue) return null
  const ts = Math.floor(new Date(localValue).getTime() / 1000)
  return Number.isNaN(ts) ? null : ts
}

const fromUnix = (ts: number | null | undefined): string => {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const formatUnix = (ts: number | null) => {
  if (!ts) return '-'
  return new Date(ts * 1000).toLocaleString()
}

const prettyMediaType = (type: string) => {
  const normalized = (type || 'none').toLowerCase()
  const labelMap: Record<string, string> = {
    none: '纯文本',
    photo: '图片',
    video: '视频',
    animation: 'GIF',
    sticker: '贴纸'
  }
  return labelMap[normalized] || normalized
}

const extractFileName = (value: string | null | undefined): string => {
  if (!value) return ''
  if (value.startsWith('tgmsg://')) {
    const messageId = value.split('/').pop() || ''
    return messageId ? `Telegram媒体 #${messageId}` : 'Telegram媒体'
  }
  const parts = value.split(/[\\/]/)
  return parts[parts.length - 1] || value
}

const loadTasks = async () => {
  loadingTasks.value = true
  try {
    const res = await getTasks()
    tasks.value = res.data || []
  } catch (err: any) {
    ElMessage.error(err.message || '加载任务失败')
  } finally {
    loadingTasks.value = false
  }
}

const loadResources = async (autoSyncIfEmpty = false, preserveTargets = true) => {
  if (!form.accountId) {
    resources.value = []
    form.targetKeys = []
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
  } catch (err: any) {
    ElMessage.error(err.message || '加载聊天资源失败')
  } finally {
    loadingResources.value = false
  }
}

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

const openCreateForm = async (mode: 'scheduled' | 'manual_shortcut') => {
  if (mode === 'manual_shortcut' && manualTaskCount.value >= 3) {
    ElMessage.warning('每个用户最多只能创建 3 个手动任务，请先删除一个后再试')
    return
  }
  resetForm(true)
  form.triggerMode = mode
  form.enabled = mode === 'manual_shortcut'
  if (!form.accountId && accounts.value.length > 0) {
    form.accountId = accounts.value[0]!.account_id
    await loadResources(true, false)
  }
  showEditor.value = true
}

const closeEditor = () => {
  showEditor.value = false
  editingTaskId.value = ''
}

const cancelEdit = () => {
  resetForm(true)
  showEditor.value = false
}

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
  } catch (err: any) {
    ElMessage.error(err.message || '加载任务详情失败')
  }
}

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
  if (!form.title.trim()) {
    ElMessage.warning('请填写任务名称')
    return
  }
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
      .map(parseResourceKey)
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

    await loadTasks()
    resetForm(true)
    showEditor.value = false
  } catch (err: any) {
    ElMessage.error(err.message || '提交失败')
  } finally {
    submitting.value = false
  }
}

const runTaskOnce = async (taskId: string, title: string) => {
  try {
    const summary = (await triggerTask(taskId)).data
    const statusLabel = summary.status === 'partial_success'
      ? '部分成功'
      : summary.status === 'success'
        ? '执行成功'
        : summary.status === 'failed'
          ? '执行失败'
          : '已处理'
    const message = `${title}：${statusLabel}（成功 ${summary.success_count} / 失败 ${summary.failed_count}）`
    if (summary.status === 'success') {
      ElMessage.success(message)
    } else if (summary.status === 'partial_success') {
      ElMessage.warning(message)
    } else if (summary.status === 'failed') {
      ElMessage.error(message)
    } else {
      ElMessage.info(message)
    }
    if (summary.error_summary) {
      ElMessageBox.alert(summary.error_summary, `${title} 执行摘要`, {
        confirmButtonText: '知道了'
      })
    }
    await loadTasks()
  } catch (err: any) {
    ElMessage.error(err.message || '执行任务失败')
  }
}

const toggleTaskEnabled = async (task: TaskItem, enabled: boolean) => {
  try {
    await updateTask(task.task_id, { enabled })
  } catch (err: any) {
    task.enabled = !enabled
    ElMessage.error(err.message || '状态更新失败')
  }
}

const handleTaskEnabledChange = (task: TaskItem, value: string | number | boolean) => {
  void toggleTaskEnabled(task, Boolean(value))
}

const removeTask = async (taskId: string) => {
  try {
    await ElMessageBox.confirm('确认删除该任务吗？', '提示', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
    await deleteTask(taskId)
    ElMessage.success('任务已删除')
    await loadTasks()
  } catch (err: any) {
    if (err !== 'cancel') {
      ElMessage.error(err.message || '删除失败')
    }
  }
}

const openTaskLogs = (taskId: string) => {
  router.push({ path: `/tasks/${taskId}/logs` })
}

const renderTaskTarget = (task: TaskItem) => {
  const peers = Array.isArray(task.target_peers) ? task.target_peers : []
  if (peers.length > 1) {
    const preview = peers
      .slice(0, 2)
      .map((peer) => {
        const meta = getPeerTypeMeta(peer.peer_type || '')
        const matchedResource = resources.value.find(
          (resource) => resource.peer_type === peer.peer_type && resource.peer_id === peer.peer_id,
        )
        const peerName = matchedResource ? displayResourceName(matchedResource) : meta.label
        return `${meta.icon}${peerName}`
      })
      .join('、')
    const suffix = peers.length > 2 ? ` 等 ${peers.length} 个` : ` 共 ${peers.length} 个`
    return `🎯 ${preview}${suffix}`
  }
  const singlePeer = peers.length === 1 ? peers[0] : null
  const peerType = singlePeer?.peer_type || task.target_peer_type || ''
  const meta = getPeerTypeMeta(peerType)
  const matchedResource = singlePeer
    ? resources.value.find((resource) => resource.peer_type === singlePeer.peer_type && resource.peer_id === singlePeer.peer_id)
    : null
  const targetName = matchedResource ? displayResourceName(matchedResource) : meta.label
  return `${meta.icon} ${targetName}`
}

onMounted(async () => {
  userStore.restoreUser()
  if (!userStore.userId) {
    return
  }

  await accountStore.fetchAccounts(userStore.userId)
  const accountIdFromQuery = typeof route.query.account_id === 'string' ? route.query.account_id : ''
  const peerIdFromQuery = typeof route.query.peer_id === 'string' ? Number(route.query.peer_id) : NaN
  const peerTypeFromQuery = typeof route.query.peer_type === 'string' ? route.query.peer_type : ''

  if (accountIdFromQuery && accounts.value.some(a => a.account_id === accountIdFromQuery)) {
    form.accountId = accountIdFromQuery
    await loadResources(true, false)

    if (!Number.isNaN(peerIdFromQuery)) {
      showEditor.value = true
      const target = resources.value.find(
        r => r.peer_id === peerIdFromQuery && (!peerTypeFromQuery || r.peer_type === peerTypeFromQuery)
      )
      if (target) {
        form.targetKeys = [resourceKey(target)]
      }
    }
  } else if (accounts.value.length > 0) {
    form.accountId = accounts.value[0]!.account_id
    await loadResources(false, false)
  }

  await loadTasks()

  const taskIdFromQuery = typeof route.query.task_id === 'string' ? route.query.task_id : ''
  if (taskIdFromQuery) {
    await startEdit({ task_id: taskIdFromQuery } as TaskItem)
  }
})
</script>

<style scoped>
.tasks-page {
  min-height: 100vh;
  background: #f5f7fa;
}

.header {
  background: white;
  padding: 1.5rem 0;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
}

.container {
  max-width: 1600px;
  margin: 0 auto;
  padding: 0 1.5rem;
}

.brand-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-logo {
  width: 72px;
  height: auto;
  display: block;
}

.back-link {
  color: #667eea;
  text-decoration: none;
  display: inline-block;
  margin-bottom: 1rem;
}

.back-link:hover {
  text-decoration: underline;
}

.header h1 {
  margin: 0;
  font-size: 1.5rem;
  color: #2c3e50;
}

.toolbar {
  background: white;
  margin-top: 1rem;
  border-bottom: 1px solid #eee;
}

.toolbar-inner {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.9rem 1.5rem;
}

.summary {
  margin-left: auto;
  color: #606266;
}

.table-subtext {
  color: #909399;
  font-size: 12px;
}

.main {
  padding: 1rem 1.5rem 2rem;
}

.card {
  background: white;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  padding: 1rem;
}

.table-wrap {
  width: 100%;
  overflow-x: auto;
}

.editor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.8rem;
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

@media (max-width: 1080px) {
  .container {
    padding: 0 0.9rem;
  }

  .main {
    padding: 0.8rem 0 1.2rem;
  }

  .toolbar-inner {
    padding: 0.75rem 0;
  }
}

@media (max-width: 768px) {
  .header {
    padding: 1rem 0;
  }

  .header h1 {
    font-size: 1.25rem;
  }

  .toolbar-inner {
    flex-wrap: wrap;
    gap: 0.6rem;
  }

  .toolbar-inner :deep(.el-button) {
    flex: 1 1 calc(50% - 0.3rem);
    min-width: 0;
  }

  .summary {
    width: 100%;
    margin-left: 0;
  }

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

  .table-wrap {
    margin: 0 -0.25rem;
    padding: 0 0.25rem;
  }
}

@media (max-width: 480px) {
  .toolbar-inner :deep(.el-button),
  .media-actions :deep(.el-button),
  .form-actions :deep(.el-button) {
    flex-basis: 100%;
  }
}
</style>
