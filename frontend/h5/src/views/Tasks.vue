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

    <div class=”container main”>
      <TaskEditor
        ref=”editorRef”
        :accounts=”accounts”
        :tasks=”tasks”
        :is-compact=”isCompact”
        @update:resources=”onResourcesUpdate”
        @close=”onEditorClose”
        @saved=”onEditorSaved”
        @run-once=”runTaskOnce”
      />

      <div v-if=”!showEditor” class=”list card”>
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
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAccountStore } from '@/stores/account'
import { useUserStore } from '@/stores/user'
import type { TaskItem } from '@/api/task'
import { deleteTask, getTasks, triggerTask, updateTask } from '@/api/task'
import { useResponsive } from '@/composables/useResponsive'
import { resourceKey, getPeerTypeMeta, displayResourceName, formatUnix, type ResourceOption } from '@/utils/taskHelpers'
import TaskEditor from './TaskEditor.vue'

const accountStore = useAccountStore()
const userStore = useUserStore()
const route = useRoute()
const router = useRouter()
const { isCompact } = useResponsive()

const editorRef = ref<InstanceType<typeof TaskEditor> | null>(null)
const tasks = ref<TaskItem[]>([])
const resources = ref<ResourceOption[]>([])
const loadingTasks = ref(false)
const showEditor = ref(false)

const accounts = computed(() => accountStore.accounts as Array<{ account_id: string; username?: string | null; first_name?: string | null; phone?: string | null }>)
const manualTaskCount = computed(() => tasks.value.filter((task) => task.trigger_mode === 'manual_shortcut').length)

const loadTasks = async () => {
  loadingTasks.value = true
  try {
    const res = await getTasks()
    tasks.value = res.data || []
  } catch {
    // HTTP errors already handled by the response interceptor
  } finally {
    loadingTasks.value = false
  }
}

const onResourcesUpdate = (newResources: ResourceOption[]) => {
  resources.value = newResources
}

const onEditorClose = () => {
  showEditor.value = false
}

const onEditorSaved = async () => {
  showEditor.value = false
  await loadTasks()
}

const openCreateForm = async (mode: 'scheduled' | 'manual_shortcut') => {
  const manualTaskCount = tasks.value.filter((t) => t.trigger_mode === 'manual_shortcut').length
  if (mode === 'manual_shortcut' && manualTaskCount >= 3) {
    ElMessage.warning('每个用户最多只能创建 3 个手动任务，请先删除一个后再试')
    return
  }
  showEditor.value = true
  await editorRef.value?.openCreateForm(mode)
}

const startEdit = async (task: TaskItem) => {
  showEditor.value = true
  await editorRef.value?.startEdit(task)
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
  } catch {
    // HTTP errors already handled by the response interceptor
  }
}

const toggleTaskEnabled = async (task: TaskItem, enabled: boolean) => {
  try {
    await updateTask(task.task_id, { enabled })
  } catch {
    task.enabled = !enabled
    // HTTP errors already handled by the response interceptor
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
      // HTTP errors already handled by the response interceptor
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
    if (!Number.isNaN(peerIdFromQuery)) {
      showEditor.value = true
      const editor = editorRef.value
      if (editor) {
        await editor.openCreateForm('scheduled', accountIdFromQuery)
        const target = resources.value.find(
          r => r.peer_id === peerIdFromQuery && (!peerTypeFromQuery || r.peer_type === peerTypeFromQuery)
        )
        if (target) {
          editor.setTargetKeys([resourceKey(target)])
        }
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

.card h2 {
  margin: 0;
  font-size: 1.05rem;
  color: #2c3e50;
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

  .table-wrap {
    margin: 0 -0.25rem;
    padding: 0 0.25rem;
  }
}

@media (max-width: 480px) {
  .toolbar-inner :deep(.el-button) {
    flex-basis: 100%;
  }
}
</style>
