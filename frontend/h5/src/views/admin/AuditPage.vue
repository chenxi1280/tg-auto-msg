<template>
  <div class="page-stack">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>{{ store.canViewSystemAudit ? '统一审计日志' : '审计日志' }}</span>
          <div class="header-actions">
            <el-input v-if="store.canViewSystemAudit" v-model.trim="filters.action" clearable placeholder="筛选动作" style="width: 220px" />
            <el-select v-if="store.canViewSystemAudit" v-model="filters.target_type" clearable placeholder="对象类型" style="width: 180px">
              <el-option label="用户" value="user" />
              <el-option label="账号" value="account" />
              <el-option label="卡密规格" value="plan" />
              <el-option label="卡密" value="card" />
              <el-option label="代理" value="proxy" />
              <el-option label="配置" value="settings" />
              <el-option label="开发者应用" value="developer_app" />
            </el-select>
            <el-input v-model.trim="filters.keyword" clearable placeholder="搜索操作人/动作/对象" style="width: 220px" />
            <el-button @click="refreshAudit">刷新</el-button>
          </div>
        </div>
      </template>
      <el-table :data="auditRows" stripe>
        <el-table-column prop="actor" label="操作人" min-width="160" />
        <el-table-column label="动作" min-width="200">
          <template #default="{ row }">{{ row.action_label || row.action }}</template>
        </el-table-column>
        <el-table-column label="对象类型" width="140">
          <template #default="{ row }">{{ row.target_type_label || row.target_type || '-' }}</template>
        </el-table-column>
        <el-table-column prop="target_id" label="对象 ID" min-width="160" />
        <el-table-column label="详情" min-width="280">
          <template #default="{ row }">{{ summarize(row.detail) }}</template>
        </el-table-column>
        <el-table-column prop="ip_address" label="IP" width="140" />
        <el-table-column label="时间" min-width="160">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>
      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="pagination.currentPage"
          v-model:page-size="pagination.pageSize"
          background
          layout="total, sizes, prev, pager, next"
          :page-sizes="[20, 50, 100]"
          :total="total"
          @current-change="handlePageChange"
          @size-change="handleSizeChange"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import type { AdminAuditLog } from '@/api/admin'
import { adminListAuditLogs, adminListSystemAuditLogs } from '@/api/admin'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { formatDateTime } from '@/utils/adminConsole'

const store = useAdminConsoleStore()
const auditRows = ref<AdminAuditLog[]>([])
const total = ref(0)
const filters = reactive({
  action: '',
  target_type: '',
  keyword: '',
})
const pagination = reactive({
  currentPage: 1,
  pageSize: 20,
})

const summarize = (detail: Record<string, any> | null | undefined) => {
  if (!detail) return '-'
  return Object.entries(detail)
    .slice(0, 4)
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join(' | ')
}

const loadAuditData = async (resetPage = false) => {
  if (resetPage) pagination.currentPage = 1
  if (store.canViewSystemAudit) {
    const response = await adminListSystemAuditLogs({
      action: filters.action || undefined,
      target_type: filters.target_type || undefined,
      keyword: filters.keyword || undefined,
      limit: pagination.pageSize,
      offset: (pagination.currentPage - 1) * pagination.pageSize,
    })
    auditRows.value = response.data.items
    total.value = response.data.total
    if (!auditRows.value.length && total.value > 0 && pagination.currentPage > 1) {
      pagination.currentPage -= 1
      await loadAuditData()
    }
    return
  }
  const response = await adminListAuditLogs({
    action: filters.action || undefined,
    target_type: filters.target_type || undefined,
    keyword: filters.keyword || undefined,
    limit: pagination.pageSize,
    offset: (pagination.currentPage - 1) * pagination.pageSize,
  })
  auditRows.value = response.data.items
  total.value = response.data.total
  if (!auditRows.value.length && total.value > 0 && pagination.currentPage > 1) {
    pagination.currentPage -= 1
    await loadAuditData()
  }
}

const handlePageChange = async () => {
  await loadAuditData()
}

const handleSizeChange = async () => {
  pagination.currentPage = 1
  await loadAuditData()
}

const refreshAudit = async () => {
  await loadAuditData()
}

onMounted(async () => {
  await loadAuditData()
})
</script>

<style scoped>
.page-stack {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
