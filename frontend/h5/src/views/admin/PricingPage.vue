<template>
  <div class="page-stack">
    <el-alert
      :title="store.hasPermission('pricing.write') ? '卡密价格统一由超管维护，修改后新批次立即按新价格扣费。' : '当前页面为只读视图，卡密统一价格仅允许超管修改。'"
      type="info"
      :closable="false"
    />

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>全局卡密价格</span>
          <div class="header-actions">
            <el-button v-if="isCompact" class="mobile-filter-trigger" @click="filtersVisible = true">筛选条件</el-button>
            <template v-else>
              <el-input v-model.trim="filters.search" clearable placeholder="搜索规格名称/编码" style="width: 220px" />
              <el-select v-model="filters.is_active" clearable placeholder="状态" style="width: 140px">
                <el-option label="启用" value="true" />
                <el-option label="停用" value="false" />
              </el-select>
              <el-button @click="loadData(true)">查询</el-button>
              <el-button @click="loadData()">刷新</el-button>
            </template>
          </div>
        </div>
      </template>
      <el-table v-if="!isCompact" :data="planRows" stripe>
        <el-table-column prop="display_name" label="规格名称" min-width="180" />
        <el-table-column prop="plan_code" label="规格编码" width="140" />
        <el-table-column prop="duration_days" label="时长（天）" width="120" />
        <el-table-column label="统一价格" width="140">
          <template #default="{ row }">¥{{ centsToYuan(row.price_cents) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button v-if="store.hasPermission('pricing.write')" link type="primary" @click="openEditor(row)">修改价格</el-button>
            <span v-else class="readonly-text">只读</span>
          </template>
        </el-table-column>
      </el-table>
      <div v-else class="mobile-card-list">
        <div v-for="row in planRows" :key="row.plan_code" class="mobile-data-card">
          <div class="mobile-data-card__header">
            <div>
              <div class="mobile-data-card__title">{{ row.display_name }}</div>
              <div class="mobile-data-card__subtitle">{{ row.plan_code }}</div>
            </div>
            <el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '停用' }}</el-tag>
          </div>
          <div class="mobile-data-card__grid">
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">时长</span>
              <span class="mobile-data-card__value">{{ row.duration_days }} 天</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">统一价格</span>
              <span class="mobile-data-card__value">¥{{ centsToYuan(row.price_cents) }}</span>
            </div>
          </div>
          <div class="mobile-action-bar">
            <el-button v-if="store.hasPermission('pricing.write')" type="primary" plain @click="openEditor(row)">修改价格</el-button>
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

    <ResponsiveFormLayer v-model="editor.visible" title="修改统一价格" width="420px">
      <el-form label-position="top">
        <el-form-item label="规格">
          <el-input :model-value="editor.plan?.display_name || ''" disabled />
        </el-form-item>
        <el-form-item label="价格（元）">
          <el-input-number v-model="editor.price_yuan" :min="0" :step="10" :precision="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editor.visible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitEditor">保存</el-button>
      </template>
    </ResponsiveFormLayer>

    <el-drawer v-model="filtersVisible" title="筛选价格规格" size="100%" append-to-body>
      <div class="mobile-card-list">
        <el-input v-model.trim="filters.search" clearable placeholder="搜索规格名称/编码" />
        <el-select v-model="filters.is_active" clearable placeholder="状态">
          <el-option label="启用" value="true" />
          <el-option label="停用" value="false" />
        </el-select>
        <div class="mobile-action-bar">
          <el-button @click="filtersVisible = false">关闭</el-button>
          <el-button @click="loadData()">刷新</el-button>
          <el-button type="primary" @click="applyMobileFilters">应用筛选</el-button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { AgentPlan } from '@/api/admin'
import { adminListPricingPlans, adminUpdatePricingPlan } from '@/api/admin'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { centsToYuan, yuanToCents } from '@/utils/adminConsole'
import { useResponsive } from '@/composables/useResponsive'
import ResponsiveFormLayer from '@/components/responsive/ResponsiveFormLayer.vue'

const store = useAdminConsoleStore()
const { isCompact } = useResponsive()
const submitting = ref(false)
const planRows = ref<AgentPlan[]>([])
const total = ref(0)
const filtersVisible = ref(false)
const pagination = reactive({
  currentPage: 1,
  pageSize: 20,
})
const filters = reactive({
  search: '',
  is_active: '',
})
const editor = reactive<{
  visible: boolean
  plan: AgentPlan | null
  price_yuan: number
}>({
  visible: false,
  plan: null,
  price_yuan: 0,
})

const loadData = async (resetPage = false) => {
  if (resetPage) pagination.currentPage = 1
  const response = await adminListPricingPlans({
    search: filters.search || undefined,
    is_active: filters.is_active ? filters.is_active === 'true' : undefined,
    limit: pagination.pageSize,
    offset: (pagination.currentPage - 1) * pagination.pageSize,
  })
  planRows.value = response.data.items
  total.value = response.data.total
  if (!planRows.value.length && total.value > 0 && pagination.currentPage > 1) {
    pagination.currentPage -= 1
    await loadData()
  }
}

const handlePageChange = async () => {
  await loadData()
}

const handleSizeChange = async () => {
  pagination.currentPage = 1
  await loadData()
}

const applyMobileFilters = async () => {
  filtersVisible.value = false
  await loadData(true)
}

const openEditor = (plan: AgentPlan) => {
  editor.visible = true
  editor.plan = plan
  editor.price_yuan = plan.price_cents / 100
}

const submitEditor = async () => {
  if (!editor.plan) return
  submitting.value = true
  try {
    await adminUpdatePricingPlan(editor.plan.plan_code, yuanToCents(editor.price_yuan))
    editor.visible = false
    await Promise.all([store.loadPlans(), loadData()])
    ElMessage.success('统一价格已更新')
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  await Promise.all([store.loadPlans(), loadData()])
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
  flex-wrap: wrap;
}

.readonly-text {
  color: #94a3b8;
  font-size: 13px;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
