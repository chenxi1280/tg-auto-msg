<template>
  <div class="page-stack">
    <div class="stats-grid" v-if="store.profile">
      <el-card shadow="hover">
        <div class="stat-label">当前余额</div>
        <div class="stat-value">¥{{ centsToYuan(store.profile.account.balance_cents) }}</div>
        <div class="stat-meta">线下充值确认后入账</div>
      </el-card>
      <el-card shadow="hover">
        <div class="stat-label">授信占用</div>
        <div class="stat-value">¥{{ centsToYuan(store.profile.account.credit_used_cents) }}</div>
        <div class="stat-meta">仅白名单代理可用</div>
      </el-card>
      <el-card shadow="hover">
        <div class="stat-label">当前页入账</div>
        <div class="stat-value">¥{{ centsToYuan(selfInAmount) }}</div>
        <div class="stat-meta">{{ selfInCount }} 条流水</div>
      </el-card>
      <el-card shadow="hover">
        <div class="stat-label">当前页扣减</div>
        <div class="stat-value">¥{{ centsToYuan(selfOutAmount) }}</div>
        <div class="stat-meta">{{ selfOutCount }} 条流水</div>
      </el-card>
    </div>

    <el-alert
      v-if="lastActionMessage"
      :title="lastActionMessage"
      type="success"
      :closable="true"
      @close="lastActionMessage = ''"
    />

    <el-card v-if="canCreateRecharge" shadow="hover">
      <template #header>
        <div class="card-header">
          <span>线下充值入账</span>
          <span class="card-tip">由直接上级或超管确认后增加余额</span>
        </div>
      </template>
      <el-form class="recharge-form" inline>
        <el-form-item label="充值主体">
          <el-select v-model="rechargeForm.subject_account_id" filterable style="width: 240px">
            <el-option
              v-for="account in rechargeTargets"
              :key="account.id"
              :label="`${account.display_name} (${account.username})`"
              :value="account.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="金额（元）">
          <el-input-number v-model="rechargeForm.amount_yuan" :min="0" :step="100" :precision="2" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model.trim="rechargeForm.remark" placeholder="线下充值说明" style="width: 240px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="submittingRecharge" @click="submitRecharge">发起充值审批</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>我的资金流水</span>
          <div class="header-actions">
            <el-select v-model="selfFilters.biz_type" style="width: 160px">
              <el-option label="全部业务" value="all" />
              <el-option label="充值入账" value="recharge" />
              <el-option label="余额扣费" value="consume_balance" />
              <el-option label="授信生成" value="credit_generate" />
              <el-option label="授信结清" value="credit_settlement" />
            </el-select>
            <el-select v-model="selfFilters.direction" style="width: 140px">
              <el-option label="全部方向" value="all" />
              <el-option label="入账" value="in" />
              <el-option label="扣减" value="out" />
            </el-select>
            <el-input v-model.trim="selfFilters.keyword" clearable placeholder="搜索对手方/备注/批次" style="width: 240px" />
            <el-button @click="loadSelfLedgers(true)">查询</el-button>
            <el-button @click="loadSelfLedgers()">刷新</el-button>
          </div>
        </div>
      </template>
      <el-table :data="selfLedgerRows" stripe>
        <el-table-column label="业务类型" width="130">
          <template #default="{ row }">{{ ledgerBizLabel(row.biz_type) }}</template>
        </el-table-column>
        <el-table-column label="方向" width="90">
          <template #default="{ row }">
            <el-tag :type="row.direction === 'in' ? 'success' : 'warning'">{{ row.direction === 'in' ? '入账' : '扣减' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="金额" width="120">
          <template #default="{ row }">¥{{ centsToYuan(row.amount_cents) }}</template>
        </el-table-column>
        <el-table-column label="对手方" min-width="160">
          <template #default="{ row }">{{ row.counterparty_name || '-' }}</template>
        </el-table-column>
        <el-table-column label="余额后" width="120">
          <template #default="{ row }">{{ row.balance_after_cents == null ? '-' : `¥${centsToYuan(row.balance_after_cents)}` }}</template>
        </el-table-column>
        <el-table-column label="备注" min-width="220">
          <template #default="{ row }">{{ row.remark || '-' }}</template>
        </el-table-column>
        <el-table-column label="时间" min-width="160">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>
      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="selfPagination.currentPage"
          v-model:page-size="selfPagination.pageSize"
          background
          layout="total, sizes, prev, pager, next"
          :page-sizes="[20, 50, 100]"
          :total="selfTotal"
          @current-change="handleSelfPageChange"
          @size-change="handleSelfSizeChange"
        />
      </div>
    </el-card>

    <el-card v-if="store.canViewVisibleLedgers" shadow="hover">
      <template #header>
        <div class="card-header">
          <span>下级资金流水审计</span>
          <div class="header-actions">
            <el-select v-model="visibleLedgerAccountId" clearable filterable placeholder="筛选账号" style="width: 240px" @change="loadVisibleLedgers(true)">
              <el-option
                v-for="account in store.accounts"
                :key="account.id"
                :label="`${account.display_name} (${account.username})`"
                :value="account.id"
              />
            </el-select>
            <el-select v-model="visibleFilters.biz_type" style="width: 160px">
              <el-option label="全部业务" value="all" />
              <el-option label="充值入账" value="recharge" />
              <el-option label="余额扣费" value="consume_balance" />
              <el-option label="授信生成" value="credit_generate" />
              <el-option label="授信结清" value="credit_settlement" />
            </el-select>
            <el-select v-model="visibleFilters.direction" style="width: 140px">
              <el-option label="全部方向" value="all" />
              <el-option label="入账" value="in" />
              <el-option label="扣减" value="out" />
            </el-select>
            <el-input v-model.trim="visibleFilters.keyword" clearable placeholder="搜索账号/备注/批次" style="width: 240px" />
            <el-button @click="loadVisibleLedgers(true)">查询</el-button>
            <el-button @click="loadVisibleLedgers()">刷新</el-button>
          </div>
        </div>
      </template>
      <div class="selection-bar">当前审计流水 {{ visibleTotal }} 条，当前页 {{ visibleLedgerRows.length }} 条</div>
      <el-table :data="visibleLedgerRows" stripe>
        <el-table-column label="主体账号" min-width="170">
          <template #default="{ row }">{{ row.account_name || row.account_id }}</template>
        </el-table-column>
        <el-table-column label="业务类型" width="130">
          <template #default="{ row }">{{ ledgerBizLabel(row.biz_type) }}</template>
        </el-table-column>
        <el-table-column label="金额" width="120">
          <template #default="{ row }">¥{{ centsToYuan(row.amount_cents) }}</template>
        </el-table-column>
        <el-table-column label="对手方" min-width="160">
          <template #default="{ row }">{{ row.counterparty_name || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作人" min-width="150">
          <template #default="{ row }">{{ row.operator_name || '-' }}</template>
        </el-table-column>
        <el-table-column label="备注" min-width="220">
          <template #default="{ row }">{{ row.remark || '-' }}</template>
        </el-table-column>
        <el-table-column label="时间" min-width="160">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>
      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="visiblePagination.currentPage"
          v-model:page-size="visiblePagination.pageSize"
          background
          layout="total, sizes, prev, pager, next"
          :page-sizes="[20, 50, 100]"
          :total="visibleTotal"
          @current-change="handleVisiblePageChange"
          @size-change="handleVisibleSizeChange"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { FundLedger } from '@/api/admin'
import {
  adminCreateRechargeRequest,
  adminListSelfFundLedgers,
  adminListVisibleFundLedgers,
} from '@/api/admin'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { centsToYuan, formatDateTime, ledgerBizLabel, yuanToCents } from '@/utils/adminConsole'

const store = useAdminConsoleStore()
const canCreateRecharge = computed(() => store.hasPermission('agents.write'))
const canReadApprovals = computed(() => store.hasPermission('approvals.read'))
const submittingRecharge = ref(false)
const visibleLedgerAccountId = ref<number | undefined>(undefined)
const lastActionMessage = ref('')
const selfLedgerRows = ref<FundLedger[]>([])
const visibleLedgerRows = ref<FundLedger[]>([])
const selfTotal = ref(0)
const visibleTotal = ref(0)
const selfPagination = reactive({
  currentPage: 1,
  pageSize: 20,
})
const visiblePagination = reactive({
  currentPage: 1,
  pageSize: 20,
})
const selfStats = reactive({
  page_in_amount_cents: 0,
  page_out_amount_cents: 0,
})

const rechargeForm = reactive({
  subject_account_id: 0,
  amount_yuan: 0,
  remark: '',
})

const selfFilters = reactive({
  biz_type: 'all',
  direction: 'all',
  keyword: '',
})

const visibleFilters = reactive({
  biz_type: 'all',
  direction: 'all',
  keyword: '',
})

const rechargeTargets = computed(() => {
  if (!store.profile) return []
  return store.accounts.length ? store.accounts : [store.profile.account]
})

const selfInRows = computed(() => selfLedgerRows.value.filter((row) => row.direction === 'in'))
const selfOutRows = computed(() => selfLedgerRows.value.filter((row) => row.direction === 'out'))
const selfInCount = computed(() => selfInRows.value.length)
const selfOutCount = computed(() => selfOutRows.value.length)
const selfInAmount = computed(() => selfStats.page_in_amount_cents)
const selfOutAmount = computed(() => selfStats.page_out_amount_cents)

const loadSelfLedgers = async (resetPage = false) => {
  if (resetPage) selfPagination.currentPage = 1
  const response = await adminListSelfFundLedgers({
    biz_type: selfFilters.biz_type === 'all' ? undefined : selfFilters.biz_type,
    direction: selfFilters.direction === 'all' ? undefined : selfFilters.direction,
    keyword: selfFilters.keyword || undefined,
    limit: selfPagination.pageSize,
    offset: (selfPagination.currentPage - 1) * selfPagination.pageSize,
  })
  selfLedgerRows.value = response.data.items
  selfTotal.value = response.data.total
  Object.assign(selfStats, response.data.stats || {
    page_in_amount_cents: 0,
    page_out_amount_cents: 0,
  })
  if (!selfLedgerRows.value.length && selfTotal.value > 0 && selfPagination.currentPage > 1) {
    selfPagination.currentPage -= 1
    await loadSelfLedgers()
  }
}

const loadVisibleLedgers = async (resetPage = false) => {
  if (!store.canViewVisibleLedgers) return
  if (resetPage) visiblePagination.currentPage = 1
  const response = await adminListVisibleFundLedgers({
    account_id: visibleLedgerAccountId.value,
    biz_type: visibleFilters.biz_type === 'all' ? undefined : visibleFilters.biz_type,
    direction: visibleFilters.direction === 'all' ? undefined : visibleFilters.direction,
    keyword: visibleFilters.keyword || undefined,
    limit: visiblePagination.pageSize,
    offset: (visiblePagination.currentPage - 1) * visiblePagination.pageSize,
  })
  visibleLedgerRows.value = response.data.items
  visibleTotal.value = response.data.total
  if (!visibleLedgerRows.value.length && visibleTotal.value > 0 && visiblePagination.currentPage > 1) {
    visiblePagination.currentPage -= 1
    await loadVisibleLedgers()
  }
}

const handleSelfPageChange = async () => {
  await loadSelfLedgers()
}

const handleSelfSizeChange = async () => {
  selfPagination.currentPage = 1
  await loadSelfLedgers()
}

const handleVisiblePageChange = async () => {
  await loadVisibleLedgers()
}

const handleVisibleSizeChange = async () => {
  visiblePagination.currentPage = 1
  await loadVisibleLedgers()
}

const submitRecharge = async () => {
  if (!canCreateRecharge.value) {
    ElMessage.warning('当前账号无权发起充值审批')
    return
  }
  if (!rechargeForm.subject_account_id || rechargeForm.amount_yuan <= 0) {
    ElMessage.warning('请选择充值主体并填写金额')
    return
  }
  submittingRecharge.value = true
  try {
    const response = await adminCreateRechargeRequest({
      subject_account_id: rechargeForm.subject_account_id,
      amount_cents: yuanToCents(rechargeForm.amount_yuan),
      payload_json: rechargeForm.remark ? { remark: rechargeForm.remark } : undefined,
    })
    rechargeForm.amount_yuan = 0
    rechargeForm.remark = ''
    const tasks: Promise<unknown>[] = [loadSelfLedgers(true), loadVisibleLedgers(true)]
    if (canReadApprovals.value) {
      tasks.push(store.loadApprovalRequests({ status: 'pending', limit: 100 }))
    }
    await Promise.all(tasks)
    lastActionMessage.value = `充值审批 ${response.data.request_id} 已发起，等待上级确认入账`
    ElMessage.success('充值审批已发起')
  } finally {
    submittingRecharge.value = false
  }
}

onMounted(async () => {
  await store.loadProfile()
  const tasks: Promise<unknown>[] = [loadSelfLedgers(), loadVisibleLedgers()]
  if (canCreateRecharge.value || store.canViewVisibleLedgers) {
    tasks.push(store.loadAccounts())
  }
  if (canReadApprovals.value) {
    tasks.push(store.loadApprovalRequests({ status: 'pending', limit: 100 }))
  }
  await Promise.all(tasks)
  if (store.profile) {
    rechargeForm.subject_account_id = store.profile.account.id
  }
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

.recharge-form {
  display: flex;
  flex-wrap: wrap;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
