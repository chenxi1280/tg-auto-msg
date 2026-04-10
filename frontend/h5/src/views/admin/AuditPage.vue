<template>
  <div class="page-stack">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>系统审计日志</span>
          <div class="header-actions">
            <el-button v-if="isCompact" class="mobile-filter-trigger" @click="filtersVisible = true">筛选条件</el-button>
            <template v-else>
              <el-input v-model.trim="filters.action" clearable placeholder="筛选动作" style="width: 220px" />
              <el-select v-model="filters.target_type" clearable placeholder="对象类型" style="width: 180px">
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
            </template>
          </div>
        </div>
      </template>
      <el-table v-if="!isCompact" :data="auditRows" stripe>
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
      <div v-else class="mobile-card-list">
        <div v-for="row in auditRows" :key="`${row.created_at}-${row.action}-${row.target_id}`" class="mobile-data-card">
          <div class="mobile-data-card__header">
            <div>
              <div class="mobile-data-card__title">{{ row.action_label || row.action }}</div>
              <div class="mobile-data-card__subtitle">{{ formatDateTime(row.created_at) }}</div>
            </div>
            <el-tag>{{ row.target_type_label || row.target_type || '-' }}</el-tag>
          </div>
          <div class="mobile-data-card__grid">
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">操作人</span>
              <span class="mobile-data-card__value">{{ row.actor || '-' }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">对象 ID</span>
              <span class="mobile-data-card__value">{{ row.target_id || '-' }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">详情</span>
              <span class="mobile-data-card__value">{{ summarize(row.detail) }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">IP</span>
              <span class="mobile-data-card__value">{{ row.ip_address || '-' }}</span>
            </div>
          </div>
        </div>
      </div>
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

    <el-drawer v-model="filtersVisible" title="筛选审计日志" size="100%" append-to-body>
      <div class="mobile-card-list">
        <el-input v-model.trim="filters.action" clearable placeholder="筛选动作" />
        <el-select v-model="filters.target_type" clearable placeholder="对象类型">
          <el-option label="用户" value="user" />
          <el-option label="账号" value="account" />
          <el-option label="卡密规格" value="plan" />
          <el-option label="卡密" value="card" />
          <el-option label="代理" value="proxy" />
          <el-option label="配置" value="settings" />
          <el-option label="开发者应用" value="developer_app" />
        </el-select>
        <el-input v-model.trim="filters.keyword" clearable placeholder="搜索操作人/动作/对象" />
        <div class="mobile-action-bar">
          <el-button @click="filtersVisible = false">关闭</el-button>
          <el-button @click="refreshAudit">刷新</el-button>
          <el-button type="primary" @click="applyMobileFilters">应用筛选</el-button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import type { AdminAuditLog } from '@/api/admin'
import { adminListSystemAuditLogs } from '@/api/admin'
import { formatDateTime } from '@/utils/adminConsole'
import { useResponsive } from '@/composables/useResponsive'

const { isCompact } = useResponsive()
const auditRows = ref<AdminAuditLog[]>([])
const total = ref(0)
const filtersVisible = ref(false)
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

const applyMobileFilters = async () => {
  filtersVisible.value = false
  await loadAuditData(true)
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
