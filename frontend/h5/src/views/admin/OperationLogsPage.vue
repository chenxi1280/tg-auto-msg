<template>
  <div class="page-stack">
    <div class="stats-grid">
      <el-card shadow="hover">
        <div class="stat-label">充值入账</div>
        <div class="stat-value">¥{{ centsToYuan(stats.recharge_amount_cents) }}</div>
        <div class="stat-meta">{{ stats.recharge_count }} 笔</div>
      </el-card>
      <el-card shadow="hover">
        <div class="stat-label">卡密生成</div>
        <div class="stat-value">¥{{ centsToYuan(stats.card_generate_amount_cents) }}</div>
        <div class="stat-meta">{{ stats.card_generate_count }} 批</div>
      </el-card>
      <el-card shadow="hover">
        <div class="stat-label">授信结清</div>
        <div class="stat-value">¥{{ centsToYuan(stats.credit_settlement_amount_cents) }}</div>
        <div class="stat-meta">{{ stats.credit_settlement_count }} 笔</div>
      </el-card>
    </div>

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>操作日志</span>
          <div class="header-actions">
            <el-button v-if="isCompact" class="mobile-filter-trigger" @click="filtersVisible = true">筛选条件</el-button>
            <template v-else>
              <el-select v-model="filters.log_type" style="width: 160px">
                <el-option label="全部类型" value="all" />
                <el-option label="充值入账" value="recharge" />
                <el-option label="卡密生成" value="card_generate" />
                <el-option label="授信结清" value="credit_settlement" />
              </el-select>
              <el-select
                v-if="canFilterAccounts"
                v-model="filters.account_id"
                clearable
                filterable
                placeholder="筛选账号"
                style="width: 240px"
              >
                <el-option
                  v-for="account in store.accounts"
                  :key="account.id"
                  :label="`${account.display_name} (${account.username})`"
                  :value="account.id"
                />
              </el-select>
              <el-date-picker
                v-model="filters.date_range"
                type="daterange"
                range-separator="至"
                start-placeholder="开始日期"
                end-placeholder="结束日期"
                value-format="YYYY-MM-DD"
              />
              <el-input v-model.trim="filters.keyword" clearable placeholder="搜索操作人/账号/批次/备注" style="width: 240px" />
              <el-button @click="loadLogs(true)">查询</el-button>
              <el-button @click="loadLogs()">刷新</el-button>
            </template>
          </div>
        </div>
      </template>
      <el-table v-if="!isCompact" :data="rows" stripe>
        <el-table-column label="类型" width="120">
          <template #default="{ row }">
            <el-tag :type="tagType(row.log_type)">{{ operationLogLabel(row.log_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作人" min-width="150">
          <template #default="{ row }">{{ row.operator_name || '-' }}</template>
        </el-table-column>
        <el-table-column label="主体账号" min-width="170">
          <template #default="{ row }">{{ row.subject_name || '未命名账号' }}</template>
        </el-table-column>
        <el-table-column label="对手方" min-width="170">
          <template #default="{ row }">{{ row.counterparty_name || '-' }}</template>
        </el-table-column>
        <el-table-column label="规格 / 数量" min-width="170">
          <template #default="{ row }">
            <span v-if="row.log_type === 'card_generate'">{{ planDisplayName(row.plan_code) }} / {{ row.quantity || 0 }}</span>
            <span v-else>{{ planDisplayName(row.plan_code) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="金额" width="120">
          <template #default="{ row }">¥{{ centsToYuan(row.amount_cents) }}</template>
        </el-table-column>
        <el-table-column label="资金来源" width="120">
          <template #default="{ row }">{{ fundingSourceLabel(row.funding_source) }}</template>
        </el-table-column>
        <el-table-column label="备注" min-width="220">
          <template #default="{ row }">{{ row.remark || '-' }}</template>
        </el-table-column>
        <el-table-column label="时间" min-width="160">
          <template #default="{ row }">{{ formatDateTime(row.occurred_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openLogDetail(row)">查看详情</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-else class="mobile-card-list">
        <div v-for="row in rows" :key="`${row.log_type}-${row.batch_id || row.occurred_at}-${row.subject_account_id}`" class="mobile-data-card">
          <div class="mobile-data-card__header">
            <div>
              <div class="mobile-data-card__title">{{ operationLogLabel(row.log_type) }}</div>
              <div class="mobile-data-card__subtitle">{{ formatDateTime(row.occurred_at) }}</div>
            </div>
            <el-tag :type="tagType(row.log_type)">{{ fundingSourceLabel(row.funding_source) }}</el-tag>
          </div>
          <div class="mobile-data-card__grid">
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">操作人</span>
              <span class="mobile-data-card__value">{{ row.operator_name || '-' }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">主体账号</span>
              <span class="mobile-data-card__value">{{ row.subject_name || '未命名账号' }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">对手方</span>
              <span class="mobile-data-card__value">{{ row.counterparty_name || '-' }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">规格/数量</span>
              <span class="mobile-data-card__value">{{ planDisplayName(row.plan_code) }} / {{ row.quantity || 0 }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">金额</span>
              <span class="mobile-data-card__value">¥{{ centsToYuan(row.amount_cents) }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">备注</span>
              <span class="mobile-data-card__value">{{ row.remark || '-' }}</span>
            </div>
          </div>
          <div class="mobile-action-bar">
            <el-button type="primary" plain @click="openLogDetail(row)">查看详情</el-button>
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

    <el-drawer v-model="filtersVisible" title="筛选操作日志" size="100%" append-to-body>
      <div class="mobile-card-list">
        <el-select v-model="filters.log_type">
          <el-option label="全部类型" value="all" />
          <el-option label="充值入账" value="recharge" />
          <el-option label="卡密生成" value="card_generate" />
          <el-option label="授信结清" value="credit_settlement" />
        </el-select>
        <el-select v-if="canFilterAccounts" v-model="filters.account_id" clearable filterable placeholder="筛选账号">
          <el-option
            v-for="account in store.accounts"
            :key="account.id"
            :label="`${account.display_name} (${account.username})`"
            :value="account.id"
          />
        </el-select>
        <el-date-picker
          v-model="filters.date_range"
          type="daterange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          value-format="YYYY-MM-DD"
        />
        <el-input v-model.trim="filters.keyword" clearable placeholder="搜索操作人/账号/批次/备注" />
        <div class="mobile-action-bar">
          <el-button @click="filtersVisible = false">关闭</el-button>
          <el-button @click="loadLogs()">刷新</el-button>
          <el-button type="primary" @click="applyMobileFilters">应用筛选</el-button>
        </div>
      </div>
    </el-drawer>

    <el-drawer v-model="detailDrawerVisible" title="操作详情" size="420px" append-to-body>
      <div v-if="detailRow" class="mobile-card-list">
        <div class="mobile-data-card">
          <div class="mobile-data-card__grid">
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">类型</span>
              <span class="mobile-data-card__value">{{ operationLogLabel(detailRow.log_type) }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">操作人</span>
              <span class="mobile-data-card__value">{{ detailRow.operator_name || '-' }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">主体账号</span>
              <span class="mobile-data-card__value">{{ detailRow.subject_name || detailRow.subject_account_id || '-' }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">对手方</span>
              <span class="mobile-data-card__value">{{ detailRow.counterparty_name || detailRow.counterparty_account_id || '-' }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">规格</span>
              <span class="mobile-data-card__value">{{ planDisplayName(detailRow.plan_code) }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">批次号</span>
              <span class="mobile-data-card__value">{{ detailRow.batch_id || '-' }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">金额</span>
              <span class="mobile-data-card__value">¥{{ centsToYuan(detailRow.amount_cents) }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">时间</span>
              <span class="mobile-data-card__value">{{ formatDateTime(detailRow.occurred_at) }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">备注</span>
              <span class="mobile-data-card__value">{{ detailRow.remark || '-' }}</span>
            </div>
          </div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import type { OperationLog } from '@/api/admin'
import { adminListOperationLogs } from '@/api/admin'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { centsToYuan, formatDateTime, operationLogLabel } from '@/utils/adminConsole'
import { useResponsive } from '@/composables/useResponsive'

const store = useAdminConsoleStore()
const { isCompact } = useResponsive()
const rows = ref<OperationLog[]>([])
const total = ref(0)
const filtersVisible = ref(false)
const detailDrawerVisible = ref(false)
const detailRow = ref<OperationLog | null>(null)
const stats = reactive({
  recharge_count: 0,
  recharge_amount_cents: 0,
  card_generate_count: 0,
  card_generate_amount_cents: 0,
  credit_settlement_count: 0,
  credit_settlement_amount_cents: 0,
})
const filters = reactive({
  log_type: 'all',
  account_id: undefined as number | undefined,
  keyword: '',
  date_range: [] as string[],
})
const pagination = reactive({
  currentPage: 1,
  pageSize: 20,
})

const canFilterAccounts = computed(() =>
  store.hasPermission('operation_logs.scope.read') && store.hasPermission('agents.read'),
)

const planDisplayName = (planCode?: string | null) => {
  if (!planCode) return '-'
  return store.plans.find((plan) => plan.plan_code === planCode)?.display_name || '规格已记录'
}

const fundingSourceLabel = (value?: string | null) => {
  if (!value) return '-'
  if (value === 'platform') return '平台直生'
  if (value === 'balance') return '余额'
  if (value === 'credit') return '授信'
  return value
}

const tagType = (logType: string) => {
  if (logType === 'recharge') return 'success'
  if (logType === 'card_generate') return 'primary'
  if (logType === 'credit_settlement') return 'warning'
  return 'info'
}

const openLogDetail = (row: OperationLog) => {
  detailRow.value = row
  detailDrawerVisible.value = true
}

const loadLogs = async (resetPage = false) => {
  if (resetPage) pagination.currentPage = 1
  const [dateFrom, dateTo] = filters.date_range || []
  const response = await adminListOperationLogs({
    log_type: filters.log_type === 'all' ? undefined : filters.log_type,
    account_id: filters.account_id,
    keyword: filters.keyword || undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    limit: pagination.pageSize,
    offset: (pagination.currentPage - 1) * pagination.pageSize,
  })
  rows.value = response.data.items
  total.value = response.data.total
  Object.assign(stats, {
    recharge_count: response.data.stats?.recharge_count || 0,
    recharge_amount_cents: response.data.stats?.recharge_amount_cents || 0,
    card_generate_count: response.data.stats?.card_generate_count || 0,
    card_generate_amount_cents: response.data.stats?.card_generate_amount_cents || 0,
    credit_settlement_count: response.data.stats?.credit_settlement_count || 0,
    credit_settlement_amount_cents: response.data.stats?.credit_settlement_amount_cents || 0,
  })
  if (!rows.value.length && total.value > 0 && pagination.currentPage > 1) {
    pagination.currentPage -= 1
    await loadLogs()
  }
}

const handlePageChange = async () => {
  await loadLogs()
}

const handleSizeChange = async () => {
  pagination.currentPage = 1
  await loadLogs()
}

const applyMobileFilters = async () => {
  filtersVisible.value = false
  await loadLogs(true)
}

onMounted(async () => {
  if (!store.profile) {
    await store.bootstrap()
  }
  if (!store.plans.length && store.hasPermission('pricing.read')) {
    await store.loadPlans()
  }
  if (canFilterAccounts.value && !store.accounts.length) {
    await store.loadAccounts()
  }
  await loadLogs()
})
</script>

<style scoped>
.page-stack {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.stat-label {
  color: #64748b;
  font-size: 13px;
}

.stat-value {
  margin-top: 8px;
  font-size: 28px;
  font-weight: 700;
  color: #0f172a;
}

.stat-meta {
  margin-top: 8px;
  color: #94a3b8;
  font-size: 13px;
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

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
