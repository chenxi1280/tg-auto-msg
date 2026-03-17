<template>
  <div class="task-logs-page">
    <header class="header">
      <div class="container">
        <router-link to="/tasks" class="back-link">← 返回任务管理</router-link>
        <h1>任务发送记录</h1>
        <p class="subtitle">任务ID：{{ taskId }}</p>
      </div>
    </header>

    <div class="container main">
      <section class="card overview">
        <div class="overview-row">
          <span class="label">任务名称</span>
          <span class="value">{{ taskTitle || '-' }}</span>
        </div>
        <div class="overview-row">
          <span class="label">记录总数（当前拉取）</span>
          <span class="value">{{ logs.length }}</span>
        </div>
        <div class="actions">
          <el-button @click="loadData" :loading="loading">刷新</el-button>
        </div>
      </section>

      <section class="card table-card">
        <el-table :data="logs" stripe v-loading="loading" empty-text="暂无发送记录">
          <el-table-column prop="send_at" label="发送时间" min-width="180">
            <template #default="{ row }">
              {{ formatTime(row.send_at) }}
            </template>
          </el-table-column>
          <el-table-column prop="result" label="结果" width="100">
            <template #default="{ row }">
              <el-tag :type="row.result === 'success' ? 'success' : 'danger'">
                {{ row.result === 'success' ? '成功' : '失败' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="message_id" label="消息ID" width="110" />
          <el-table-column prop="error_code" label="错误码" width="140" show-overflow-tooltip />
          <el-table-column prop="error_message" label="错误信息" min-width="260" show-overflow-tooltip />
        </el-table>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { TaskLogItem } from '@/api/task'
import { getTask, getTaskLogs } from '@/api/task'

const route = useRoute()
const taskId = String(route.params.taskId || '')

const taskTitle = ref('')
const logs = ref<TaskLogItem[]>([])
const loading = ref(false)

const formatTime = (iso: string | null) => {
  if (!iso) return '-'
  return new Date(iso).toLocaleString()
}

const loadData = async () => {
  if (!taskId) {
    ElMessage.error('任务ID无效')
    return
  }
  loading.value = true
  try {
    const [taskRes, logsRes] = await Promise.all([
      getTask(taskId),
      getTaskLogs(taskId, 200)
    ])
    taskTitle.value = taskRes.data?.title || ''
    logs.value = logsRes.data || []
  } catch (err: any) {
    ElMessage.error(err?.message || '加载任务记录失败')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadData()
})
</script>

<style scoped>
.task-logs-page {
  min-height: 100vh;
  background: #f3f4f6;
}

.header {
  background: #fff;
  border-bottom: 1px solid #e5e7eb;
}

.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 16px;
}

.back-link {
  color: #4f46e5;
  text-decoration: none;
}

h1 {
  margin: 8px 0 4px;
  font-size: 24px;
}

.subtitle {
  margin: 0;
  color: #6b7280;
  font-size: 13px;
}

.main {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.card {
  background: #fff;
  border-radius: 12px;
  border: 1px solid #e5e7eb;
  padding: 16px;
}

.overview {
  display: grid;
  gap: 10px;
}

.overview-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.label {
  color: #6b7280;
}

.value {
  color: #111827;
  font-weight: 600;
}

.actions {
  margin-top: 6px;
}

.table-card {
  overflow: hidden;
}
</style>
