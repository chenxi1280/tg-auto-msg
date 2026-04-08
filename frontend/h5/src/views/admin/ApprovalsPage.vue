<template>
  <div class="page-stack">
    <div class="stats-grid">
      <el-card shadow="hover">
        <div class="stat-label">待处理审批</div>
        <div class="stat-value">{{ pendingApprovalCount }}</div>
        <div class="stat-meta">等待你处理的充值、批次、结算和调额审批</div>
      </el-card>
      <el-card shadow="hover">
        <div class="stat-label">待充值审批</div>
        <div class="stat-value">{{ pendingRechargeCount }}</div>
        <div class="stat-meta">金额 ¥{{ centsToYuan(pendingRechargeAmount) }}</div>
      </el-card>
      <el-card shadow="hover">
        <div class="stat-label">待批次申请</div>
        <div class="stat-value">{{ pendingBatchPurchaseCount }}</div>
        <div class="stat-meta">金额 ¥{{ centsToYuan(pendingBatchPurchaseAmount) }}</div>
      </el-card>
      <el-card shadow="hover">
        <div class="stat-label">待结算授信批次</div>
        <div class="stat-value">{{ mySettlementBatches.length }}</div>
        <div class="stat-meta">总额 ¥{{ centsToYuan(settlementBatchAmount) }}</div>
      </el-card>
    </div>

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>待结算授信批次</span>
          <span class="card-tip">仅显示当前由你负责继续结算的授信批次</span>
        </div>
      </template>
      <el-empty v-if="!mySettlementBatches.length" description="暂无待结算授信批次" />
      <el-table v-else :data="mySettlementBatches" stripe>
        <el-table-column prop="batch_id" label="批次号" min-width="200" />
        <el-table-column prop="plan_code" label="规格" width="120" />
        <el-table-column prop="quantity" label="数量" width="100" />
        <el-table-column label="待结金额" width="120">
          <template #default="{ row }">¥{{ centsToYuan(row.total_amount_cents) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button type="primary" link :loading="settlingBatchId === row.batch_id" @click="submitSettlement(row.batch_id)">
              发起结算审批
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>审批工作台</span>
          <div class="header-actions">
            <el-select v-model="filters.status" style="width: 140px" @change="loadApprovals">
              <el-option label="全部状态" value="all" />
              <el-option label="待处理" value="pending" />
              <el-option label="已通过" value="approved" />
              <el-option label="已驳回" value="rejected" />
            </el-select>
            <el-select v-model="filters.request_type" style="width: 160px" @change="loadApprovals">
              <el-option label="全部类型" value="all" />
              <el-option label="充值入账" value="recharge" />
              <el-option label="批次申请" value="batch_purchase" />
              <el-option label="授信结算" value="settlement" />
              <el-option label="额度调整" value="credit_adjust" />
            </el-select>
            <el-input v-model.trim="filters.keyword" clearable placeholder="搜索审批单号/批次/规格" style="width: 220px" />
            <el-button @click="refreshData">刷新</el-button>
          </div>
        </div>
      </template>

      <div class="toolbar">
        <div class="selection-note">
          已选择 {{ selectedPendingRequestIds.length }} 条待处理审批
        </div>
        <div class="toolbar-actions">
          <el-button
            type="primary"
            :disabled="!selectedPendingRequestIds.length"
            :loading="batchActionLoading === 'approve'"
            @click="batchApprove"
          >
            批量通过
          </el-button>
          <el-button
            type="danger"
            plain
            :disabled="!selectedPendingRequestIds.length"
            :loading="batchActionLoading === 'reject'"
            @click="batchReject"
          >
            批量驳回
          </el-button>
        </div>
      </div>

      <el-empty v-if="!filteredApprovals.length" description="当前筛选条件下没有审批记录" />
      <el-table
        v-else
        :data="filteredApprovals"
        stripe
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="48" :selectable="isRowSelectable" />
        <el-table-column prop="request_id" label="审批单号" min-width="200" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="130">
          <template #default="{ row }">{{ approvalLabel(row.request_type) }}</template>
        </el-table-column>
        <el-table-column label="主体账号" width="160">
          <template #default="{ row }">{{ store.accountMap.get(row.subject_account_id)?.display_name || row.subject_account_id }}</template>
        </el-table-column>
        <el-table-column label="金额" width="120">
          <template #default="{ row }">{{ row.amount_cents == null ? '-' : `¥${centsToYuan(row.amount_cents)}` }}</template>
        </el-table-column>
        <el-table-column label="摘要" min-width="240">
          <template #default="{ row }">{{ summaryText(row.payload_json) }}</template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="160">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="处理时间" min-width="160">
          <template #default="{ row }">{{ formatDateTime(row.approved_at || row.rejected_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <template v-if="row.status === 'pending'">
              <el-button type="primary" link :loading="processingRequestId === row.request_id" @click="approve(row.request_id)">通过</el-button>
              <el-button type="danger" link :loading="processingRequestId === row.request_id" @click="reject(row.request_id)">驳回</el-button>
            </template>
            <span v-else class="muted-text">已处理</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { ApprovalRequest } from '@/api/admin'
import {
  adminApproveRequest,
  adminBatchApproveRequests,
  adminBatchRejectRequests,
  adminCreateSettlementRequest,
  adminRejectRequest,
} from '@/api/admin'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { approvalLabel, centsToYuan, formatDateTime } from '@/utils/adminConsole'

const store = useAdminConsoleStore()
const settlingBatchId = ref('')
const processingRequestId = ref('')
const batchActionLoading = ref<'approve' | 'reject' | ''>('')
const selectedRows = ref<ApprovalRequest[]>([])
const filters = reactive({
  status: 'all',
  request_type: 'all',
  keyword: '',
})

const mySettlementBatches = computed(() => {
  const currentId = store.profile?.account.id
  if (!currentId) return []
  return store.batches.filter(
    (batch) =>
      batch.payment_status === 'credit' &&
      batch.settlement_status !== 'settled' &&
      batch.current_liability_account_id === currentId,
  )
})

const settlementBatchAmount = computed(() =>
  mySettlementBatches.value.reduce((sum, batch) => sum + (batch.total_amount_cents || 0), 0),
)

const pendingApprovals = computed(() => store.approvalRequests.filter((item) => item.status === 'pending'))
const pendingApprovalCount = computed(() => pendingApprovals.value.length)
const pendingRechargeItems = computed(() => pendingApprovals.value.filter((item) => item.request_type === 'recharge'))
const pendingBatchPurchaseItems = computed(() => pendingApprovals.value.filter((item) => item.request_type === 'batch_purchase'))
const pendingRechargeCount = computed(() => pendingRechargeItems.value.length)
const pendingRechargeAmount = computed(() => pendingRechargeItems.value.reduce((sum, item) => sum + (item.amount_cents || 0), 0))
const pendingBatchPurchaseCount = computed(() => pendingBatchPurchaseItems.value.length)
const pendingBatchPurchaseAmount = computed(() => pendingBatchPurchaseItems.value.reduce((sum, item) => sum + (item.amount_cents || 0), 0))

const filteredApprovals = computed(() => {
  const keyword = filters.keyword.trim().toLowerCase()
  if (!keyword) return store.approvalRequests
  return store.approvalRequests.filter((item) => {
    const payload = item.payload_json || {}
    return [
      item.request_id,
      String(payload.batch_id || ''),
      String(payload.plan_code || ''),
      String(payload.quantity || ''),
      String(store.accountMap.get(item.subject_account_id)?.display_name || ''),
    ].some((part) => part.toLowerCase().includes(keyword))
  })
})

const selectedPendingRequestIds = computed(() =>
  selectedRows.value.filter((row) => row.status === 'pending').map((row) => row.request_id),
)

const summaryText = (payload: Record<string, any>) => {
  if (!payload) return '-'
  const parts = []
  if (payload.plan_code) parts.push(`规格 ${payload.plan_code}`)
  if (payload.quantity) parts.push(`数量 ${payload.quantity}`)
  if (payload.batch_id) parts.push(`批次 ${payload.batch_id}`)
  if (payload.remark) parts.push(`备注 ${payload.remark}`)
  return parts.join(' / ') || '-'
}

const statusLabel = (status: string) => {
  if (status === 'pending') return '待处理'
  if (status === 'approved') return '已通过'
  if (status === 'rejected') return '已驳回'
  return status || '-'
}

const statusTagType = (status: string) => {
  if (status === 'pending') return 'warning'
  if (status === 'approved') return 'success'
  if (status === 'rejected') return 'info'
  return 'info'
}

const isRowSelectable = (row: ApprovalRequest) => row.status === 'pending'

const handleSelectionChange = (rows: ApprovalRequest[]) => {
  selectedRows.value = rows
}

const loadApprovals = async () => {
  await store.loadApprovalRequests({
    status: filters.status,
    request_type: filters.request_type,
    limit: 300,
  })
}

const refreshData = async () => {
  await Promise.all([store.loadProfile(), store.loadAccounts(), store.loadBatches(), loadApprovals()])
}

const submitSettlement = async (batchId: string) => {
  settlingBatchId.value = batchId
  try {
    await adminCreateSettlementRequest({
      payload_json: { batch_id: batchId },
    })
    await refreshData()
    ElMessage.success('结算审批已发起')
  } finally {
    settlingBatchId.value = ''
  }
}

const approve = async (requestId: string) => {
  processingRequestId.value = requestId
  try {
    await adminApproveRequest(requestId)
    await refreshData()
    ElMessage.success('审批已通过')
  } finally {
    processingRequestId.value = ''
  }
}

const reject = async (requestId: string) => {
  processingRequestId.value = requestId
  try {
    await adminRejectRequest(requestId)
    await refreshData()
    ElMessage.success('审批已驳回')
  } finally {
    processingRequestId.value = ''
  }
}

const showBatchFeedback = (actionLabel: string, result: { success_count: number; failed_count: number; failed_items: Array<{ request_id: string; detail: string }> }) => {
  if (!result.failed_count) {
    ElMessage.success(`${actionLabel}完成，成功 ${result.success_count} 条`)
    return
  }
  const sample = result.failed_items
    .slice(0, 3)
    .map((item) => `${item.request_id}: ${item.detail}`)
    .join('\n')
  ElMessage.warning(`${actionLabel}完成，成功 ${result.success_count} 条，失败 ${result.failed_count} 条${sample ? `\n${sample}` : ''}`)
}

const batchApprove = async () => {
  if (!selectedPendingRequestIds.value.length) return
  try {
    await ElMessageBox.confirm(`确认批量通过 ${selectedPendingRequestIds.value.length} 条审批吗？`, '批量通过确认', {
      type: 'warning',
    })
  } catch {
    return
  }
  batchActionLoading.value = 'approve'
  try {
    const response = await adminBatchApproveRequests(selectedPendingRequestIds.value)
    await refreshData()
    showBatchFeedback('批量通过', response.data)
    selectedRows.value = []
  } finally {
    batchActionLoading.value = ''
  }
}

const batchReject = async () => {
  if (!selectedPendingRequestIds.value.length) return
  try {
    await ElMessageBox.confirm(`确认批量驳回 ${selectedPendingRequestIds.value.length} 条审批吗？`, '批量驳回确认', {
      type: 'warning',
    })
  } catch {
    return
  }
  batchActionLoading.value = 'reject'
  try {
    const response = await adminBatchRejectRequests(selectedPendingRequestIds.value)
    await refreshData()
    showBatchFeedback('批量驳回', response.data)
    selectedRows.value = []
  } finally {
    batchActionLoading.value = ''
  }
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

.stat-meta {
  margin-top: 10px;
  color: #64748b;
  font-size: 13px;
}

.card-header,
.header-actions,
.toolbar,
.toolbar-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.card-tip,
.selection-note,
.muted-text {
  color: #94a3b8;
  font-size: 12px;
}

.toolbar {
  margin-bottom: 16px;
  padding: 12px 14px;
  border-radius: 12px;
  background: #f8fafc;
}

.muted-text {
  display: inline-block;
}
</style>
