<template>
  <div class="page-stack">
    <el-alert
      v-if="lastActionMessage"
      :title="lastActionMessage"
      type="success"
      :closable="true"
      @close="lastActionMessage = ''"
    />

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
            <el-button
              v-if="canCreateSettlement"
              type="primary"
              link
              :loading="settlingBatchId === row.batch_id"
              @click="submitSettlement(row.batch_id)"
            >
              发起结算审批
            </el-button>
            <span v-else class="muted-text">无发起权限</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>审批工作台</span>
          <div class="header-actions">
            <el-select v-model="filters.status" style="width: 140px" @change="loadApprovals(true)">
              <el-option label="全部状态" value="all" />
              <el-option label="待处理" value="pending" />
              <el-option label="已通过" value="approved" />
              <el-option label="已驳回" value="rejected" />
            </el-select>
            <el-select v-model="filters.request_type" style="width: 160px" @change="loadApprovals(true)">
              <el-option label="全部类型" value="all" />
              <el-option label="充值入账" value="recharge" />
              <el-option label="批次申请" value="batch_purchase" />
              <el-option label="授信结算" value="settlement" />
              <el-option label="额度调整" value="credit_adjust" />
            </el-select>
            <el-input v-model.trim="filters.keyword" clearable placeholder="搜索审批单号" style="width: 220px" />
            <el-button @click="loadApprovals(true)">查询</el-button>
            <el-button @click="refreshData">刷新</el-button>
          </div>
        </div>
      </template>

      <div class="toolbar">
        <div class="selection-note">
          已选择 {{ selectedPendingRequestIds.length }} 条待处理审批，当前总数 {{ totalApprovals }}
        </div>
        <div class="toolbar-actions">
          <el-button
            v-if="canBatchApprove"
            type="primary"
            :disabled="!selectedPendingRequestIds.length"
            :loading="batchActionLoading === 'approve'"
            @click="batchApprove"
          >
            批量通过
          </el-button>
          <el-button
            v-if="canBatchReject"
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

      <el-empty v-if="!approvals.length" description="当前筛选条件下没有审批记录" />
      <el-table
        v-else
        :data="approvals"
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
              <el-button
                v-if="canApprove"
                type="primary"
                link
                :loading="processingRequestId === row.request_id"
                @click="approve(row.request_id)"
              >
                通过
              </el-button>
              <el-button
                v-if="canReject"
                type="danger"
                link
                :loading="processingRequestId === row.request_id"
                @click="reject(row.request_id)"
              >
                驳回
              </el-button>
              <span v-if="!canApprove && !canReject" class="muted-text">无处理权限</span>
            </template>
            <span v-else class="muted-text">已处理</span>
          </template>
        </el-table-column>
      </el-table>
      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="pagination.currentPage"
          v-model:page-size="pagination.pageSize"
          background
          layout="total, sizes, prev, pager, next"
          :page-sizes="[20, 50, 100]"
          :total="totalApprovals"
          @current-change="handlePageChange"
          @size-change="handleSizeChange"
        />
      </div>
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
  adminListApprovalRequests,
  adminRejectRequest,
} from '@/api/admin'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { approvalLabel, centsToYuan, formatDateTime } from '@/utils/adminConsole'

const store = useAdminConsoleStore()
const canCreateSettlement = computed(() => store.hasPermission('agents.write'))
const canApprove = computed(() => store.hasPermission('approvals.approve'))
const canReject = computed(() => store.hasPermission('approvals.reject'))
const canBatchApprove = computed(() => store.hasPermission('approvals.batch'))
const canBatchReject = computed(() => store.hasPermission('approvals.batch'))
const canReadAgents = computed(() => store.hasPermission('agents.read'))
const canReadBatches = computed(() => store.hasPermission('batches.read'))
const settlingBatchId = ref('')
const processingRequestId = ref('')
const batchActionLoading = ref<'approve' | 'reject' | ''>('')
const selectedRows = ref<ApprovalRequest[]>([])
const approvals = ref<ApprovalRequest[]>([])
const totalApprovals = ref(0)
const lastActionMessage = ref('')
const filters = reactive({
  status: 'all',
  request_type: 'all',
  keyword: '',
})
const pagination = reactive({
  currentPage: 1,
  pageSize: 20,
})

const mySettlementBatches = computed(() => {
  if (!canReadBatches.value) return []
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

const pendingApprovals = computed(() => approvals.value.filter((item) => item.status === 'pending'))
const pendingApprovalCount = computed(() => pendingApprovals.value.length)
const pendingRechargeItems = computed(() => pendingApprovals.value.filter((item) => item.request_type === 'recharge'))
const pendingBatchPurchaseItems = computed(() => pendingApprovals.value.filter((item) => item.request_type === 'batch_purchase'))
const pendingRechargeCount = computed(() => pendingRechargeItems.value.length)
const pendingRechargeAmount = computed(() => pendingRechargeItems.value.reduce((sum, item) => sum + (item.amount_cents || 0), 0))
const pendingBatchPurchaseCount = computed(() => pendingBatchPurchaseItems.value.length)
const pendingBatchPurchaseAmount = computed(() => pendingBatchPurchaseItems.value.reduce((sum, item) => sum + (item.amount_cents || 0), 0))

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

const loadApprovals = async (resetPage = false) => {
  if (resetPage) pagination.currentPage = 1
  const response = await adminListApprovalRequests({
    status: filters.status,
    request_type: filters.request_type,
    keyword: filters.keyword || undefined,
    limit: pagination.pageSize,
    offset: (pagination.currentPage - 1) * pagination.pageSize,
  })
  approvals.value = response.data.items
  totalApprovals.value = response.data.total
  if (!approvals.value.length && totalApprovals.value > 0 && pagination.currentPage > 1) {
    pagination.currentPage -= 1
    await loadApprovals()
  }
}

const refreshData = async () => {
  const tasks: Promise<unknown>[] = [store.loadProfile(), loadApprovals()]
  if (canReadAgents.value) {
    tasks.push(store.loadAccounts())
  }
  if (canReadBatches.value) {
    tasks.push(store.loadBatches())
  }
  await Promise.all(tasks)
}

const handlePageChange = async () => {
  await loadApprovals()
}

const handleSizeChange = async () => {
  pagination.currentPage = 1
  await loadApprovals()
}

const submitSettlement = async (batchId: string) => {
  if (!canCreateSettlement.value) {
    ElMessage.warning('当前账号无权发起结算审批')
    return
  }
  settlingBatchId.value = batchId
  try {
    await adminCreateSettlementRequest({
      payload_json: { batch_id: batchId },
    })
    await refreshData()
    lastActionMessage.value = '结算审批已发起'
    ElMessage.success('结算审批已发起')
  } finally {
    settlingBatchId.value = ''
  }
}

const approve = async (requestId: string) => {
  if (!canApprove.value) {
    ElMessage.warning('当前账号无权通过审批')
    return
  }
  processingRequestId.value = requestId
  try {
    await adminApproveRequest(requestId)
    await refreshData()
    lastActionMessage.value = '审批已通过'
    ElMessage.success('审批已通过')
  } finally {
    processingRequestId.value = ''
  }
}

const reject = async (requestId: string) => {
  if (!canReject.value) {
    ElMessage.warning('当前账号无权驳回审批')
    return
  }
  processingRequestId.value = requestId
  try {
    await adminRejectRequest(requestId)
    await refreshData()
    lastActionMessage.value = '审批已驳回'
    ElMessage.success('审批已驳回')
  } finally {
    processingRequestId.value = ''
  }
}

const showBatchFeedback = (actionLabel: string, result: { success_count: number; failed_count: number; failed_items: Array<{ request_id: string; detail: string }> }) => {
  const summary = `${actionLabel}完成，成功 ${result.success_count} 条，失败 ${result.failed_count} 条`
  lastActionMessage.value = summary
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
  if (!canBatchApprove.value) {
    ElMessage.warning('当前账号无权批量审批')
    return
  }
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
  if (!canBatchReject.value) {
    ElMessage.warning('当前账号无权批量驳回')
    return
  }
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

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
