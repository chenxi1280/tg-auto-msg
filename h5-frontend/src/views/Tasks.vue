<template>
  <div class="tasks-page">
    <header class="header">
      <div class="container">
        <router-link to="/" class="back-link">← 返回首页</router-link>
        <h1>任务管理</h1>
      </div>
    </header>

    <div class="toolbar">
      <div class="container toolbar-inner">
        <el-button type="primary" @click="resetForm">
          新建任务
        </el-button>
        <el-button :loading="loadingTasks" @click="loadTasks">
          刷新任务
        </el-button>
        <span class="summary">共 {{ tasks.length }} 个任务</span>
      </div>
    </div>

    <div class="container main">
      <div class="editor card">
        <h2>{{ editingTaskId ? '编辑任务' : '新建任务' }}</h2>
        <el-form label-position="top">
          <el-form-item label="任务名称">
            <el-input v-model="form.title" placeholder="例如：午间频道推送" />
          </el-form-item>

          <el-form-item label="执行账号">
            <el-select v-model="form.accountId" placeholder="请选择账号" style="width: 100%" @change="onAccountChange">
              <el-option
                v-for="account in accounts"
                :key="account.account_id"
                :label="account.username || account.phone || account.account_id"
                :value="account.account_id"
              />
            </el-select>
          </el-form-item>

          <el-form-item label="目标聊天（支持多选）">
            <el-select
              v-model="form.targetKeys"
              multiple
              filterable
              collapse-tags
              collapse-tags-tooltip
              placeholder="请选择群组/频道/用户"
              style="width: 100%"
              :disabled="!form.accountId"
            >
              <el-option
                v-for="res in resources"
                :key="resourceKey(res)"
                :label="resourceLabel(res)"
                :value="resourceKey(res)"
              />
            </el-select>
          </el-form-item>

          <el-form-item label="消息文本">
            <el-input
              v-model="form.text"
              type="textarea"
              :rows="5"
              maxlength="4096"
              show-word-limit
              placeholder="支持纯文本/emoji，媒体上传后续可接入"
            />
          </el-form-item>

          <div class="grid-two">
            <el-form-item label="媒体类型">
              <el-select v-model="form.mediaType" style="width: 100%">
                <el-option label="无" value="none" />
                <el-option label="图片" value="photo" />
                <el-option label="视频" value="video" />
                <el-option label="贴纸" value="sticker" />
                <el-option label="动图" value="animation" />
              </el-select>
            </el-form-item>
            <el-form-item label="媒体 File ID">
              <el-input
                v-model="form.mediaFileId"
                :disabled="form.mediaType === 'none'"
                placeholder="输入 Telegram media file_id"
              />
            </el-form-item>
          </div>

          <div class="grid-two">
            <el-form-item label="任务优先级">
              <el-input-number v-model="form.priority" :min="0" :max="1000" style="width: 100%" />
            </el-form-item>
            <el-form-item label="发送间隔（分钟）">
              <el-input-number v-model="form.repeatIntervalMin" :min="1" :max="1440" style="width: 100%" />
            </el-form-item>
          </div>

          <div class="grid-two">
            <el-form-item label="随机延迟下限（秒）">
              <el-input-number v-model="form.delayMinSeconds" :min="0" :max="3600" style="width: 100%" />
            </el-form-item>
            <el-form-item label="随机延迟上限（秒）">
              <el-input-number v-model="form.delayMaxSeconds" :min="0" :max="3600" style="width: 100%" />
            </el-form-item>
          </div>

          <div class="grid-two">
            <el-form-item label="兼容抖动上限（秒）">
              <el-input-number v-model="form.jitterSeconds" :min="0" :max="300" style="width: 100%" />
            </el-form-item>
          </div>

          <div class="grid-two">
            <el-form-item label="开始时间（可选）">
              <el-input v-model="form.startAtLocal" type="datetime-local" />
            </el-form-item>
            <el-form-item label="结束时间（可选）">
              <el-input v-model="form.endAtLocal" type="datetime-local" />
            </el-form-item>
          </div>

          <div class="grid-two">
            <el-form-item label="每日发送起始小时">
              <el-input-number v-model="form.dayStartHour" :min="0" :max="23" style="width: 100%" />
            </el-form-item>
            <el-form-item label="每日发送结束小时">
              <el-input-number v-model="form.dayEndHour" :min="0" :max="23" style="width: 100%" />
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

          <el-form-item label="置顶消息">
            <el-switch v-model="form.pinMessage" />
          </el-form-item>

          <div class="form-actions">
            <el-button type="primary" :loading="submitting" @click="submitTask">
              {{ editingTaskId ? '保存修改' : '创建任务' }}
            </el-button>
            <el-button v-if="editingTaskId" @click="resetForm">取消编辑</el-button>
          </div>
        </el-form>
      </div>

      <div class="list card">
        <h2>任务列表</h2>
        <el-table :data="tasks" stripe v-loading="loadingTasks">
          <el-table-column prop="title" label="任务名" min-width="200" />
          <el-table-column label="优先级" width="90">
            <template #default="{ row }">
              {{ row.priority ?? 0 }}
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-switch v-model="row.enabled" @change="(val) => toggleTaskEnabled(row, Boolean(val))" />
            </template>
          </el-table-column>
          <el-table-column label="间隔/抖动" width="130">
            <template #default="{ row }">
              {{ row.repeat_interval_min }}m / {{ row.jitter_seconds }}s
            </template>
          </el-table-column>
          <el-table-column label="下次执行" width="170">
            <template #default="{ row }">
              {{ formatUnix(row.next_run_at) }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link @click="startEdit(row)">编辑</el-button>
              <el-button type="danger" link @click="removeTask(row.task_id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAccountStore } from '@/stores/account'
import { useUserStore } from '@/stores/user'
import type { TaskItem } from '@/api/task'
import { createTask, deleteTask, getTask, getTasks, updateTask } from '@/api/task'

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

const tasks = ref<TaskItem[]>([])
const resources = ref<ResourceOption[]>([])
const loadingTasks = ref(false)
const loadingResources = ref(false)
const submitting = ref(false)
const editingTaskId = ref<string>('')

const accounts = computed(() => accountStore.activeAccounts)

const form = reactive({
  title: '',
  accountId: '',
  targetKeys: [] as string[],
  text: '',
  priority: 0,
  repeatIntervalMin: 60,
  jitterSeconds: 0,
  delayMinSeconds: 0,
  delayMaxSeconds: 0,
  mediaType: 'none',
  mediaFileId: '',
  startAtLocal: '',
  endAtLocal: '',
  dayStartHour: null as number | null,
  dayEndHour: null as number | null,
  enabled: false,
  deletePrevious: true,
  pinMessage: false
})

const resourceKey = (res: ResourceOption) => `${res.peer_type}:${res.peer_id}`
const resourceLabel = (res: ResourceOption) =>
  `[${res.peer_type}] ${res.title}${res.username ? ` (@${res.username})` : ''}`

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

const loadResources = async (autoSyncIfEmpty = false) => {
  resources.value = []
  form.targetKeys = []
  if (!form.accountId) return

  loadingResources.value = true
  try {
    const query = { is_active: true }
    const data = await accountStore.getAccountResources(form.accountId, query)
    resources.value = (data || []) as ResourceOption[]

    if (autoSyncIfEmpty && resources.value.length === 0) {
      ElMessage.info('正在同步聊天资源，请稍候...')
      await accountStore.syncAccount(form.accountId, true)
      const retried = await accountStore.getAccountResources(form.accountId, query)
      resources.value = (retried || []) as ResourceOption[]
      if (resources.value.length === 0) {
        ElMessage.warning('该账号暂无可用聊天，请确认账号已加入群组/频道')
      }
    }
  } catch (err: any) {
    ElMessage.error(err.message || '加载聊天资源失败')
  } finally {
    loadingResources.value = false
  }
}

const onAccountChange = async () => {
  await loadResources(true)
}

const resetForm = () => {
  editingTaskId.value = ''
  form.title = ''
  form.accountId = ''
  form.targetKeys = []
  form.text = ''
  form.priority = 0
  form.repeatIntervalMin = 60
  form.jitterSeconds = 0
  form.delayMinSeconds = 0
  form.delayMaxSeconds = 0
  form.mediaType = 'none'
  form.mediaFileId = ''
  form.startAtLocal = ''
  form.endAtLocal = ''
  form.dayStartHour = null
  form.dayEndHour = null
  form.enabled = false
  form.deletePrevious = true
  form.pinMessage = false
}

const startEdit = async (task: TaskItem) => {
  try {
    const detail = (await getTask(task.task_id)).data

    editingTaskId.value = detail.task_id
    form.title = detail.title
    form.accountId = detail.account_id || ''
    form.text = detail.text || ''
    form.priority = detail.priority || 0
    form.repeatIntervalMin = detail.repeat_interval_min
    form.jitterSeconds = detail.jitter_seconds || 0
    form.delayMinSeconds = detail.delay_min_seconds || 0
    form.delayMaxSeconds = detail.delay_max_seconds || 0
    form.mediaType = detail.media_type || 'none'
    form.mediaFileId = detail.media_file_id || ''
    form.startAtLocal = fromUnix(detail.start_at)
    form.endAtLocal = fromUnix(detail.end_at)
    form.dayStartHour = detail.day_start_hour
    form.dayEndHour = detail.day_end_hour
    form.enabled = detail.enabled
    form.deletePrevious = detail.delete_previous
    form.pinMessage = detail.pin_message

    if (form.accountId) {
      await loadResources()
      if (detail.target_peer_id && detail.target_peer_type) {
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

const buildPayloadForTarget = (target: ResourceOption) => ({
  account_id: form.accountId,
  chat_id: target.peer_id,
  target_peer_id: target.peer_id,
  target_peer_type: target.peer_type,
  target_access_hash: target.access_hash,
  title: form.title,
  enabled: form.enabled,
  priority: form.priority,
  repeat_interval_min: form.repeatIntervalMin,
  jitter_seconds: form.jitterSeconds,
  delay_min_seconds: form.delayMinSeconds,
  delay_max_seconds: form.delayMaxSeconds,
  day_start_hour: form.dayStartHour,
  day_end_hour: form.dayEndHour,
  start_at: toUnix(form.startAtLocal),
  end_at: toUnix(form.endAtLocal),
  text: form.text || null,
  media_type: form.mediaType,
  media_file_id: form.mediaType === 'none' ? null : (form.mediaFileId || null),
  delete_previous: form.deletePrevious,
  pin_message: form.pinMessage
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
  if (form.delayMinSeconds > form.delayMaxSeconds) {
    ElMessage.warning('随机延迟下限不能大于上限')
    return
  }
  if (form.mediaType !== 'none' && !form.mediaFileId.trim()) {
    ElMessage.warning('请选择媒体类型后请填写 media file_id')
    return
  }

  submitting.value = true
  try {
    const targets = form.targetKeys
      .map(parseResourceKey)
      .filter((v): v is ResourceOption => Boolean(v))

    if (targets.length === 0) {
      ElMessage.warning('目标聊天无效，请重新选择')
      return
    }

    if (editingTaskId.value) {
      const payload = buildPayloadForTarget(targets[0]!)
      await updateTask(editingTaskId.value, payload)
      ElMessage.success('任务已更新')
    } else {
      const jobs = targets.map(target => createTask(buildPayloadForTarget(target)))
      const results = await Promise.allSettled(jobs)
      const successCount = results.filter(r => r.status === 'fulfilled').length
      const failedCount = results.length - successCount

      if (successCount > 0 && failedCount === 0) {
        ElMessage.success(`创建成功，共 ${successCount} 个任务`)
      } else if (successCount > 0) {
        ElMessage.warning(`部分成功：成功 ${successCount}，失败 ${failedCount}`)
      } else {
        ElMessage.error('任务创建失败')
      }
    }

    await loadTasks()
    resetForm()
  } catch (err: any) {
    ElMessage.error(err.message || '提交失败')
  } finally {
    submitting.value = false
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
    await loadResources(true)

    if (!Number.isNaN(peerIdFromQuery)) {
      const target = resources.value.find(
        r => r.peer_id === peerIdFromQuery && (!peerTypeFromQuery || r.peer_type === peerTypeFromQuery)
      )
      if (target) {
        form.targetKeys = [resourceKey(target)]
      }
    }
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
  max-width: 1280px;
  margin: 0 auto;
  padding: 0 1.5rem;
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

.main {
  display: grid;
  grid-template-columns: 420px 1fr;
  gap: 1rem;
  padding: 1rem 1.5rem 2rem;
}

.card {
  background: white;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  padding: 1rem;
}

.card h2 {
  margin: 0 0 0.8rem;
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

@media (max-width: 1080px) {
  .main {
    grid-template-columns: 1fr;
  }
}
</style>
