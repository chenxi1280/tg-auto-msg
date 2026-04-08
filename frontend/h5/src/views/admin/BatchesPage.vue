<template>
  <div class="page-stack">
    <div class="stats-grid">
      <el-card shadow="hover">
        <div class="stat-label">批次数</div>
        <div class="stat-value">{{ filteredBatches.length }}</div>
        <div class="stat-meta">当前筛选结果</div>
      </el-card>
      <el-card shadow="hover">
        <div class="stat-label">余额已付批次</div>
        <div class="stat-value">{{ paidBatchCount }}</div>
        <div class="stat-meta">总额 ¥{{ centsToYuan(paidBatchAmount) }}</div>
      </el-card>
      <el-card shadow="hover">
        <div class="stat-label">授信批次</div>
        <div class="stat-value">{{ creditBatchCount }}</div>
        <div class="stat-meta">总额 ¥{{ centsToYuan(creditBatchAmount) }}</div>
      </el-card>
      <el-card shadow="hover">
        <div class="stat-label">待结算批次</div>
        <div class="stat-value">{{ pendingSettlementCount }}</div>
        <div class="stat-meta">总额 ¥{{ centsToYuan(pendingSettlementAmount) }}</div>
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
            <span class="card-tip">默认消耗余额，授信仅对白名单代理开放</span>
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
          <el-form-item label="资金来源">
            <el-radio-group v-model="batchForm.funding_source">
              <el-radio-button label="balance">余额直接生成</el-radio-button>
              <el-radio-button label="credit" :disabled="!store.profile?.account.is_credit_whitelisted">授信快速生成</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-button type="primary" :loading="submittingBatch" @click="submitGenerateBatch">提交生成</el-button>
        </el-form>
      </el-card>

      <el-card shadow="hover">
        <template #header>
          <div class="card-header">
            <span>提交批次申请</span>
            <span class="card-tip">上级审批通过后系统自动生成</span>
          </div>
        </template>
        <el-form label-position="top">
          <el-form-item label="规格">
            <el-select v-model="purchaseForm.plan_code" filterable>
              <el-option
                v-for="plan in activePlans"
                :key="plan.plan_code"
                :label="`${plan.display_name} / ¥${centsToYuan(plan.price_cents)}`"
                :value="plan.plan_code"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="数量">
            <el-input-number v-model="purchaseForm.quantity" :min="1" :max="500" />
          </el-form-item>
          <el-form-item label="前缀">
            <el-input v-model.trim="purchaseForm.prefix" />
          </el-form-item>
          <el-form-item label="有效天数">
            <el-input-number v-model="purchaseForm.valid_days" :min="1" />
          </el-form-item>
          <el-button type="primary" :loading="submittingPurchase" @click="submitBatchPurchase">发起批次申请</el-button>
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
            <el-button @click="store.loadBatches()">刷新</el-button>
          </div>
        </div>
      </template>
      <el-table :data="filteredBatches" stripe>
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
              <el-option label="审批" value="approval" />
            </el-select>
            <el-input v-model.trim="cardFilters.keyword" clearable placeholder="搜索卡密/批次" style="width: 220px" />
            <el-button @click="exportExcel">导出 Excel</el-button>
            <el-button type="primary" :disabled="!selectedCards.length" @click="copySelectedCards(false)">复制卡密</el-button>
            <el-button type="primary" plain :disabled="!selectedCards.length" @click="copySelectedCards(true)">复制卡密+元数据</el-button>
          </div>
        </div>
      </template>
      <div class="selection-bar">已选择 {{ selectedCards.length }} 条卡密，单次最多复制 10 条</div>
      <el-table :data="filteredCards" stripe @selection-change="handleSelectionChange">
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
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { AgentCard, CardBatch } from '@/api/admin'
import {
  adminCopyCards,
  adminCreateBatchPurchaseRequest,
  adminExportCardsXlsx,
  adminGenerateCardBatch,
} from '@/api/admin'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { centsToYuan, formatDateTime } from '@/utils/adminConsole'

const store = useAdminConsoleStore()
const submittingBatch = ref(false)
const submittingPurchase = ref(false)
const selectedCards = ref<AgentCard[]>([])
const lastActionMessage = ref('')

const activePlans = computed(() => store.plans.filter((plan) => plan.is_active))

const batchForm = reactive({
  plan_code: '',
  quantity: 1,
  prefix: '',
  valid_days: 30,
  funding_source: 'balance' as 'balance' | 'credit',
})

const purchaseForm = reactive({
  plan_code: '',
  quantity: 1,
  prefix: '',
  valid_days: 30,
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
    purchaseForm.plan_code = firstPlan.plan_code
  }
}

const filteredBatches = computed(() => {
  const keyword = batchFilters.keyword.trim().toLowerCase()
  return store.batches.filter((batch) => {
    if (batchFilters.plan_code && batch.plan_code !== batchFilters.plan_code) return false
    if (batchFilters.payment_status !== 'all' && batch.payment_status !== batchFilters.payment_status) return false
    if (batchFilters.settlement_status !== 'all' && batch.settlement_status !== batchFilters.settlement_status) return false
    if (
      keyword &&
      ![String(batch.batch_id || ''), String(batch.plan_code || '')].some((part) => part.toLowerCase().includes(keyword))
    ) {
      return false
    }
    return true
  })
})

const paidBatches = computed(() => store.batches.filter((batch) => batch.payment_status === 'paid'))
const creditBatches = computed(() => store.batches.filter((batch) => batch.payment_status === 'credit'))
const pendingSettlementBatches = computed(() => store.batches.filter((batch) => batch.settlement_status === 'pending'))
const paidBatchCount = computed(() => paidBatches.value.length)
const paidBatchAmount = computed(() => paidBatches.value.reduce((sum, batch) => sum + (batch.total_amount_cents || 0), 0))
const creditBatchCount = computed(() => creditBatches.value.length)
const creditBatchAmount = computed(() => creditBatches.value.reduce((sum, batch) => sum + (batch.total_amount_cents || 0), 0))
const pendingSettlementCount = computed(() => pendingSettlementBatches.value.length)
const pendingSettlementAmount = computed(() => pendingSettlementBatches.value.reduce((sum, batch) => sum + (batch.total_amount_cents || 0), 0))

const filteredCards = computed(() => {
  const keyword = cardFilters.keyword.trim().toLowerCase()
  return store.cards.filter((card) => {
    if (cardFilters.plan_code && card.plan_code !== cardFilters.plan_code) return false
    if (cardFilters.status === 'available' && card.is_used) return false
    if (cardFilters.status === 'used' && !card.is_used) return false
    if (cardFilters.source_type !== 'all' && card.card_source_type !== cardFilters.source_type) return false
    if (
      keyword &&
      ![String(card.card_code || ''), String(card.batch_id || ''), String(card.plan_code || '')].some((part) =>
        part.toLowerCase().includes(keyword),
      )
    ) {
      return false
    }
    return true
  })
})

const refreshData = async () => {
  await Promise.all([
    store.loadPlans(),
    store.loadBatches(),
    store.loadCards(),
    store.loadApprovalRequests({ status: 'pending', limit: 100 }),
  ])
  initDefaultPlan()
}

const paymentStatusLabel = (status: string) => (status === 'paid' ? '已支付' : status === 'credit' ? '授信' : status || '-')
const settlementStatusLabel = (status: string) => (status === 'settled' ? '已结算' : status === 'pending' ? '待结算' : status || '-')

const submitGenerateBatch = async () => {
  submittingBatch.value = true
  try {
    const response = await adminGenerateCardBatch(batchForm)
    await Promise.all([store.loadProfile(), store.loadBatches(), store.loadCards(), store.loadSelfLedgers()])
    lastActionMessage.value = `批次 ${response.data.batch.batch_id} 已生成，共 ${response.data.batch.quantity} 张，金额 ¥${centsToYuan(response.data.batch.total_amount_cents)}`
    ElMessage.success('卡密批次已生成')
  } finally {
    submittingBatch.value = false
  }
}

const submitBatchPurchase = async () => {
  submittingPurchase.value = true
  try {
    const response = await adminCreateBatchPurchaseRequest({
      payload_json: {
        plan_code: purchaseForm.plan_code,
        quantity: purchaseForm.quantity,
        prefix: purchaseForm.prefix,
        valid_days: purchaseForm.valid_days,
      },
    })
    await store.loadApprovalRequests({ status: 'pending', limit: 100 })
    lastActionMessage.value = `批次申请 ${response.data.request_id} 已发起，等待上级审批`
    ElMessage.success('批次申请已发起')
  } finally {
    submittingPurchase.value = false
  }
}

const handleSelectionChange = (rows: AgentCard[]) => {
  selectedCards.value = rows
}

const copySelectedCards = async (withMeta: boolean) => {
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
  const file = await adminExportCardsXlsx()
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

.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 20px;
}

.card-header,
.header-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.card-tip {
  color: #94a3b8;
  font-size: 12px;
}
</style>
