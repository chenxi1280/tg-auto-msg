<template>
  <div class="page-stack">
    <div class="stats-grid">
      <el-card v-if="canGenerateBatches && canReadPricing" shadow="hover">
        <div class="stat-label">批次数</div>
        <div class="stat-value">{{ batchTotal }}</div>
        <div class="stat-meta">当前筛选结果总数</div>
      </el-card>
      <el-card v-if="canGenerateBatches && canReadPricing" shadow="hover">
        <div class="stat-label">余额已付批次</div>
        <div class="stat-value">{{ batchStats.page_paid_count }}</div>
        <div class="stat-meta">当前页统计</div>
      </el-card>
      <el-card shadow="hover">
        <div class="stat-label">授信批次</div>
        <div class="stat-value">{{ batchStats.page_credit_count }}</div>
        <div class="stat-meta">当前页统计</div>
      </el-card>
      <el-card shadow="hover">
        <div class="stat-label">待结算批次</div>
        <div class="stat-value">{{ batchStats.page_pending_settlement_count }}</div>
        <div class="stat-meta">当前页金额 ¥{{ centsToYuan(batchStats.page_total_amount_cents) }}</div>
      </el-card>
    </div>

    <el-alert
      v-if="lastActionMessage"
      :title="lastActionMessage"
      type="success"
      :closable="true"
      @close="lastActionMessage = ''"
    />

    <div class="form-grid">
      <el-card shadow="hover">
        <template #header>
          <div class="card-header">
            <span>立即生成卡密</span>
            <span class="card-tip">{{ generationTip }}</span>
          </div>
        </template>
        <el-form label-position="top">
          <el-form-item label="规格">
            <el-select v-model="batchForm.plan_code" filterable>
              <el-option
                v-for="plan in activePlans"
                :key="plan.plan_code"
                :label="`${plan.display_name} / ¥${centsToYuan(plan.price_cents)}`"
                :value="plan.plan_code"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="数量">
            <el-input-number v-model="batchForm.quantity" :min="1" :max="500" />
          </el-form-item>
          <el-form-item label="前缀">
            <el-input v-model.trim="batchForm.prefix" />
          </el-form-item>
          <el-form-item label="有效天数">
            <el-input-number v-model="batchForm.valid_days" :min="1" />
          </el-form-item>
          <el-form-item v-if="!isPlatformOperator" label="资金来源">
            <el-radio-group v-model="batchForm.funding_source">
              <el-radio-button label="balance">余额直接生成</el-radio-button>
              <el-radio-button label="credit" :disabled="!store.profile?.account.is_credit_whitelisted">授信兜底生成</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <div v-if="!isPlatformOperator && balanceWarning" class="warning-tip">{{ balanceWarning }}</div>
          <el-button type="primary" :loading="submittingBatch" @click="submitGenerateBatch">提交生成</el-button>
        </el-form>
      </el-card>
    </div>

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>卡密批次</span>
          <div class="header-actions">
            <el-select v-model="batchFilters.plan_code" clearable placeholder="规格" style="width: 140px">
              <el-option v-for="plan in activePlans" :key="plan.plan_code" :label="plan.display_name" :value="plan.plan_code" />
            </el-select>
            <el-select v-model="batchFilters.payment_status" placeholder="支付状态" style="width: 140px">
              <el-option label="全部支付" value="all" />
              <el-option label="已支付" value="paid" />
              <el-option label="授信" value="credit" />
            </el-select>
            <el-select v-model="batchFilters.settlement_status" placeholder="结算状态" style="width: 140px">
              <el-option label="全部结算" value="all" />
              <el-option label="已结算" value="settled" />
              <el-option label="待结算" value="pending" />
            </el-select>
            <el-input v-model.trim="batchFilters.keyword" clearable placeholder="搜索批次号/规格" style="width: 220px" />
            <el-button @click="loadBatchRows(true)">查询</el-button>
            <el-button @click="loadBatchRows()">刷新</el-button>
          </div>
        </div>
      </template>
      <el-table :data="batchRows" stripe>
        <el-table-column prop="batch_id" label="批次号" min-width="200" />
        <el-table-column prop="plan_code" label="规格" width="120" />
        <el-table-column prop="quantity" label="数量" width="100" />
        <el-table-column label="单价" width="120">
          <template #default="{ row }">¥{{ centsToYuan(row.unit_price_cents) }}</template>
        </el-table-column>
        <el-table-column label="总额" width="120">
          <template #default="{ row }">¥{{ centsToYuan(row.total_amount_cents) }}</template>
        </el-table-column>
        <el-table-column label="支付" width="110">
          <template #default="{ row }">
            <el-tag :type="row.payment_status === 'paid' ? 'success' : 'warning'">{{ paymentStatusLabel(row.payment_status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="结算" width="110">
          <template #default="{ row }">
            <el-tag :type="row.settlement_status === 'settled' ? 'success' : 'warning'">{{ settlementStatusLabel(row.settlement_status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="时间" min-width="160">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>
      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="batchPagination.currentPage"
          v-model:page-size="batchPagination.pageSize"
          background
          layout="total, sizes, prev, pager, next"
          :page-sizes="[20, 50, 100]"
          :total="batchTotal"
          @current-change="handleBatchPageChange"
          @size-change="handleBatchSizeChange"
        />
      </div>
    </el-card>

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>卡密明细</span>
          <div class="header-actions">
            <el-select v-model="cardFilters.plan_code" clearable placeholder="规格" style="width: 140px">
              <el-option v-for="plan in activePlans" :key="plan.plan_code" :label="plan.display_name" :value="plan.plan_code" />
            </el-select>
            <el-select v-model="cardFilters.status" placeholder="卡密状态" style="width: 140px">
              <el-option label="全部状态" value="all" />
              <el-option label="可用" value="available" />
              <el-option label="已使用" value="used" />
            </el-select>
            <el-select v-model="cardFilters.source_type" placeholder="来源" style="width: 140px">
              <el-option label="全部来源" value="all" />
              <el-option label="余额" value="balance" />
              <el-option label="授信" value="credit" />
              <el-option label="平台直生" value="platform" />
              <el-option label="审批（历史）" value="approval" />
            </el-select>
            <el-input v-model.trim="cardFilters.keyword" clearable placeholder="搜索卡密/批次" style="width: 220px" />
            <el-button @click="loadCardRows(true)">查询</el-button>
            <el-button v-if="canExportCards" @click="exportExcel">导出 Excel</el-button>
            <el-button v-if="canCopyCards" type="primary" :disabled="!selectedCards.length" @click="copySelectedCards(false)">复制卡密</el-button>
            <el-button v-if="canCopyCards" type="primary" plain :disabled="!selectedCards.length" @click="copySelectedCards(true)">复制卡密+元数据</el-button>
          </div>
        </div>
      </template>
      <div class="selection-bar">已选择 {{ selectedCards.length }} 条卡密，当前总数 {{ cardTotal }}，单次最多复制 10 条</div>
      <el-table :data="cardRows" stripe @selection-change="handleSelectionChange">
        <el-table-column type="selection" width="48" />
        <el-table-column prop="card_code" label="卡密" min-width="180" />
        <el-table-column prop="plan_code" label="规格" width="120" />
        <el-table-column prop="batch_id" label="批次" min-width="180" />
        <el-table-column prop="card_source_type" label="来源" width="120" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_used ? 'warning' : 'success'">{{ row.is_used ? '已使用' : '可用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="时间" min-width="160">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>
      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="cardPagination.currentPage"
          v-model:page-size="cardPagination.pageSize"
          background
          layout="total, sizes, prev, pager, next"
          :page-sizes="[20, 50, 100]"
          :total="cardTotal"
          @current-change="handleCardPageChange"
          @size-change="handleCardSizeChange"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { AgentCard, CardBatch } from '@/api/admin'
import {
  adminCopyCards,
  adminExportCardsXlsx,
  adminGenerateCardBatch,
  adminListCardBatches,
  adminListCards,
} from '@/api/admin'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { centsToYuan, formatDateTime } from '@/utils/adminConsole'

const store = useAdminConsoleStore()
const canGenerateBatches = computed(() => store.hasPermission('batches.generate'))
const canExportCards = computed(() => store.hasPermission('batches.export'))
const canCopyCards = computed(() => store.hasPermission('batches.copy'))
const canReadApprovals = computed(() => store.hasPermission('approvals.read'))
const canReadPricing = computed(() => store.hasPermission('pricing.read'))
const canReadLedgers = computed(() => store.hasPermission('ledgers.read'))
const isPlatformOperator = computed(() => store.hasRole('super_admin'))
const submittingBatch = ref(false)
const selectedCards = ref<AgentCard[]>([])
const lastActionMessage = ref('')
const batchRows = ref<CardBatch[]>([])
const cardRows = ref<AgentCard[]>([])
const batchTotal = ref(0)
const cardTotal = ref(0)
const batchStats = reactive({
  page_total_amount_cents: 0,
  page_paid_count: 0,
  page_credit_count: 0,
  page_pending_settlement_count: 0,
})

const activePlans = computed(() => store.plans.filter((plan) => plan.is_active))
const selectedPlan = computed(() => activePlans.value.find((plan) => plan.plan_code === batchForm.plan_code))
const estimatedBatchAmountCents = computed(() => (selectedPlan.value?.price_cents || 0) * Number(batchForm.quantity || 0))
const generationTip = computed(() => {
  if (isPlatformOperator.value) {
    return '超管走平台直生，不占用余额、不走授信、不经过审批'
  }
  return '默认先扣余额生成；余额不足时，只有授信白名单代理可走授信兜底'
})
const balanceWarning = computed(() => {
  if (isPlatformOperator.value) return ''
  const amount = estimatedBatchAmountCents.value
  if (!amount) return ''
  const balance = Number(store.profile?.account.balance_cents || 0)
  if (balance >= amount) return ''
  if (store.profile?.account.is_credit_whitelisted) {
    return `当前余额不足 ¥${centsToYuan(amount - balance)}，如需立即出卡可切换到“授信兜底生成”。`
  }
  return `当前余额不足 ¥${centsToYuan(amount - balance)}，且未开通授信白名单，请先发起线下充值入账。`
})
const batchPagination = reactive({
  currentPage: 1,
  pageSize: 20,
})
const cardPagination = reactive({
  currentPage: 1,
  pageSize: 20,
})

const batchForm = reactive({
  plan_code: '',
  quantity: 1,
  prefix: '',
  valid_days: 30,
  funding_source: 'balance' as 'balance' | 'credit',
})

const batchFilters = reactive({
  plan_code: '',
  payment_status: 'all',
  settlement_status: 'all',
  keyword: '',
})

const cardFilters = reactive({
  plan_code: '',
  status: 'all',
  source_type: 'all',
  keyword: '',
})

const initDefaultPlan = () => {
  const firstPlan = activePlans.value[0]
  if (firstPlan && !batchForm.plan_code) {
    batchForm.plan_code = firstPlan.plan_code
  }
}

const loadBatchRows = async (resetPage = false) => {
  if (resetPage) batchPagination.currentPage = 1
  const response = await adminListCardBatches({
    plan_code: batchFilters.plan_code || undefined,
    payment_status: batchFilters.payment_status === 'all' ? undefined : batchFilters.payment_status,
    settlement_status: batchFilters.settlement_status === 'all' ? undefined : batchFilters.settlement_status,
    keyword: batchFilters.keyword || undefined,
    limit: batchPagination.pageSize,
    offset: (batchPagination.currentPage - 1) * batchPagination.pageSize,
  })
  batchRows.value = response.data.items
  batchTotal.value = response.data.total
  if (!batchRows.value.length && batchTotal.value > 0 && batchPagination.currentPage > 1) {
    batchPagination.currentPage -= 1
    await loadBatchRows()
    return
  }
  Object.assign(batchStats, response.data.stats || {
    page_total_amount_cents: 0,
    page_paid_count: 0,
    page_credit_count: 0,
    page_pending_settlement_count: 0,
  })
}

const loadCardRows = async (resetPage = false) => {
  if (resetPage) cardPagination.currentPage = 1
  const response = await adminListCards({
    plan_code: cardFilters.plan_code || undefined,
    status: cardFilters.status === 'all' ? undefined : cardFilters.status,
    source_type: cardFilters.source_type === 'all' ? undefined : cardFilters.source_type,
    keyword: cardFilters.keyword || undefined,
    limit: cardPagination.pageSize,
    offset: (cardPagination.currentPage - 1) * cardPagination.pageSize,
  })
  cardRows.value = response.data.items
  cardTotal.value = response.data.total
  selectedCards.value = []
  if (!cardRows.value.length && cardTotal.value > 0 && cardPagination.currentPage > 1) {
    cardPagination.currentPage -= 1
    await loadCardRows()
  }
}

const refreshData = async () => {
  const tasks: Promise<unknown>[] = [
    loadBatchRows(),
    loadCardRows(),
  ]
  if (canReadPricing.value) {
    tasks.push(store.loadPlans())
  }
  if (canReadApprovals.value) {
    tasks.push(store.loadApprovalRequests({ status: 'pending', limit: 100 }))
  }
  await Promise.all(tasks)
  initDefaultPlan()
}

const handleBatchPageChange = async () => {
  await loadBatchRows()
}

const handleBatchSizeChange = async () => {
  batchPagination.currentPage = 1
  await loadBatchRows()
}

const handleCardPageChange = async () => {
  await loadCardRows()
}

const handleCardSizeChange = async () => {
  cardPagination.currentPage = 1
  await loadCardRows()
}

const paymentStatusLabel = (status: string) => (status === 'paid' ? '已支付' : status === 'credit' ? '授信' : status || '-')
const settlementStatusLabel = (status: string) => (status === 'settled' ? '已结算' : status === 'pending' ? '待结算' : status || '-')

const submitGenerateBatch = async () => {
  if (!canGenerateBatches.value) {
    ElMessage.warning('当前账号无权生成卡密批次')
    return
  }
  if (!isPlatformOperator.value && batchForm.funding_source === 'balance') {
    const balance = Number(store.profile?.account.balance_cents || 0)
    if (balance < estimatedBatchAmountCents.value) {
      if (store.profile?.account.is_credit_whitelisted) {
        ElMessage.warning('当前余额不足，请切换到“授信兜底生成”或先充值到账')
      } else {
        ElMessage.warning('当前余额不足且未开通授信白名单，请先充值到账')
      }
      return
    }
  }
  if (!isPlatformOperator.value && batchForm.funding_source === 'credit' && !store.profile?.account.is_credit_whitelisted) {
    ElMessage.warning('当前账号未开通授信白名单，不能使用授信生成')
    return
  }
  submittingBatch.value = true
  try {
    const response = await adminGenerateCardBatch(batchForm)
    const tasks: Promise<unknown>[] = [store.loadProfile(), loadBatchRows(), loadCardRows()]
    if (canReadLedgers.value) {
      tasks.push(store.loadSelfLedgers())
    }
    await Promise.all(tasks)
    lastActionMessage.value = `批次 ${response.data.batch.batch_id} 已生成，共 ${response.data.batch.quantity} 张，金额 ¥${centsToYuan(response.data.batch.total_amount_cents)}`
    ElMessage.success('卡密批次已生成')
  } finally {
    submittingBatch.value = false
  }
}

const handleSelectionChange = (rows: AgentCard[]) => {
  selectedCards.value = rows
}

const copySelectedCards = async (withMeta: boolean) => {
  if (!canCopyCards.value) {
    ElMessage.warning('当前账号无权复制卡密')
    return
  }
  if (!selectedCards.value.length) {
    ElMessage.warning('请先选择卡密')
    return
  }
  const response = await adminCopyCards({
    card_ids: selectedCards.value.map((item) => item.id),
    with_meta: withMeta,
  })
  await navigator.clipboard.writeText(response.data.copied_text)
  lastActionMessage.value = `已复制 ${response.data.count} 条卡密${withMeta ? '（附带元数据）' : ''}`
  ElMessage.success(`已复制 ${response.data.count} 条卡密`)
}

const exportExcel = async () => {
  if (!canExportCards.value) {
    ElMessage.warning('当前账号无权导出卡密')
    return
  }
  const file = await adminExportCardsXlsx({
    plan_code: cardFilters.plan_code || undefined,
    status: cardFilters.status === 'all' ? undefined : cardFilters.status,
    source_type: cardFilters.source_type === 'all' ? undefined : cardFilters.source_type,
    keyword: cardFilters.keyword || undefined,
  })
  const url = window.URL.createObjectURL(file)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `agent-cards-${Date.now()}.xlsx`
  anchor.click()
  window.URL.revokeObjectURL(url)
  lastActionMessage.value = '卡密 Excel 已导出'
}

onMounted(async () => {
  await refreshData()
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
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 20px;
}

.stat-label {
  color: #64748b;
  font-size: 13px;
}

.stat-value {
  margin-top: 10px;
  font-size: 28px;
  font-weight: 700;
  color: #0f172a;
}

.stat-meta,
.selection-bar {
  margin-top: 10px;
  color: #64748b;
  font-size: 13px;
}

.warning-tip {
  margin: 4px 0 16px;
  color: #b45309;
  font-size: 13px;
  line-height: 1.6;
}

.form-grid {
  display: block;
}

.card-header,
.header-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.card-tip {
  color: #94a3b8;
  font-size: 12px;
}
</style>
