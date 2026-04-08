<template>
  <el-card shadow="hover">
    <template #header>
      <div class="card-header">
        <span>审计日志</span>
        <el-button @click="store.loadAuditLogs()">刷新</el-button>
      </div>
    </template>
    <el-table :data="store.auditLogs" stripe>
      <el-table-column prop="actor" label="操作人" min-width="160" />
      <el-table-column prop="action" label="动作" min-width="180" />
      <el-table-column prop="target_type" label="对象类型" width="140" />
      <el-table-column prop="target_id" label="对象 ID" min-width="160" />
      <el-table-column label="详情" min-width="260">
        <template #default="{ row }">{{ summarize(row.detail) }}</template>
      </el-table-column>
      <el-table-column prop="ip_address" label="IP" width="140" />
      <el-table-column label="时间" min-width="160">
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { formatDateTime } from '@/utils/adminConsole'

const store = useAdminConsoleStore()

const summarize = (detail: Record<string, any> | null | undefined) => {
  if (!detail) return '-'
  return Object.entries(detail)
    .slice(0, 4)
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join(' | ')
}

onMounted(async () => {
  await store.loadAuditLogs()
})
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
