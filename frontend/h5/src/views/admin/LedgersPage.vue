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
          <span class="card-tip">直接上级或超管可在这里直接把线下充值记入余额</span>
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
          <el-button type="primary" :loading="submittingRecharge" @click="submitRecharge">直接入账</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>我的资金流水</span>
          <div class="header-actions">
            <el-button v-if="isCompact" class="mobile-filter-trigger" @click="selfFiltersVisible = true">筛选条件</el-button>
            <template v-else>
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
            </template>
          </div>
        </div>
      </template>
      <el-table v-if="!isCompact" :data="selfLedgerRows" stripe>
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
      <div v-else class="mobile-card-list">
        <div v-for="row in selfLedgerRows" :key="row.id" class="mobile-data-card">
          <div class="mobile-data-card__header">
            <div>
              <div class="mobile-data-card__title">{{ ledgerBizLabel(row.biz_type) }}</div>
              <div class="mobile-data-card__subtitle">{{ formatDateTime(row.created_at) }}</div>
            </div>
            <el-tag :type="row.direction === 'in' ? 'success' : 'warning'">{{ row.direction === 'in' ? '入账' : '扣减' }}</el-tag>
          </div>
          <div class="mobile-data-card__grid">
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">金额</span>
              <span class="mobile-data-card__value">¥{{ centsToYuan(row.amount_cents) }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">对手方</span>
              <span class="mobile-data-card__value">{{ row.counterparty_name || '-' }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">余额后</span>
              <span class="mobile-data-card__value">{{ row.balance_after_cents == null ? '-' : `¥${centsToYuan(row.balance_after_cents)}` }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">备注</span>
              <span class="mobile-data-card__value">{{ row.remark || '-' }}</span>
            </div>
          </div>
        </div>
      </div>
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
            <el-button v-if="isCompact" class="mobile-filter-trigger" @click="visibleFiltersVisible = true">筛选条件</el-button>
            <template v-else>
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
            </template>
          </div>
        </div>
      </template>
      <div class="selection-bar">当前审计流水 {{ visibleTotal }} 条，当前页 {{ visibleLedgerRows.length }} 条</div>
        <el-table v-if="!isCompact" :data="visibleLedgerRows" stripe>
        <el-table-column label="主体账号" min-width="170">
          <template #default="{ row }">{{ row.account_name || '未命名账号' }}</template>
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
      <div v-else class="mobile-card-list">
        <div v-for="row in visibleLedgerRows" :key="row.id" class="mobile-data-card">
          <div class="mobile-data-card__header">
            <div>
              <div class="mobile-data-card__title">{{ row.account_name || '未命名账号' }}</div>
              <div class="mobile-data-card__subtitle">{{ formatDateTime(row.created_at) }}</div>
            </div>
            <el-tag>{{ ledgerBizLabel(row.biz_type) }}</el-tag>
          </div>
          <div class="mobile-data-card__grid">
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">金额</span>
              <span class="mobile-data-card__value">¥{{ centsToYuan(row.amount_cents) }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">对手方</span>
              <span class="mobile-data-card__value">{{ row.counterparty_name || '-' }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">操作人</span>
              <span class="mobile-data-card__value">{{ row.operator_name || '-' }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">备注</span>
              <span class="mobile-data-card__value">{{ row.remark || '-' }}</span>
            </div>
          </div>
        </div>
      </div>
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

    <el-drawer v-model="selfFiltersVisible" title="筛选我的流水" size="100%" append-to-body>
      <div class="mobile-card-list">
        <el-select v-model="selfFilters.biz_type">
          <el-option label="全部业务" value="all" />
          <el-option label="充值入账" value="recharge" />
          <el-option label="余额扣费" value="consume_balance" />
          <el-option label="授信生成" value="credit_generate" />
          <el-option label="授信结清" value="credit_settlement" />
        </el-select>
        <el-select v-model="selfFilters.direction">
          <el-option label="全部方向" value="all" />
          <el-option label="入账" value="in" />
          <el-option label="扣减" value="out" />
        </el-select>
        <el-input v-model.trim="selfFilters.keyword" clearable placeholder="搜索对手方/备注/批次" />
        <div class="mobile-action-bar">
          <el-button @click="selfFiltersVisible = false">关闭</el-button>
          <el-button @click="loadSelfLedgers()">刷新</el-button>
          <el-button type="primary" @click="applySelfFilters">应用筛选</el-button>
        </div>
      </div>
    </el-drawer>

    <el-drawer v-model="visibleFiltersVisible" title="筛选下级流水" size="100%" append-to-body>
      <div class="mobile-card-list">
        <el-select v-model="visibleLedgerAccountId" clearable filterable placeholder="筛选账号">
          <el-option
            v-for="account in store.accounts"
            :key="account.id"
            :label="`${account.display_name} (${account.username})`"
            :value="account.id"
          />
        </el-select>
        <el-select v-model="visibleFilters.biz_type">
          <el-option label="全部业务" value="all" />
          <el-option label="充值入账" value="recharge" />
          <el-option label="余额扣费" value="consume_balance" />
          <el-option label="授信生成" value="credit_generate" />
          <el-option label="授信结清" value="credit_settlement" />
        </el-select>
        <el-select v-model="visibleFilters.direction">
          <el-option label="全部方向" value="all" />
          <el-option label="入账" value="in" />
          <el-option label="扣减" value="out" />
        </el-select>
        <el-input v-model.trim="visibleFilters.keyword" clearable placeholder="搜索账号/备注/批次" />
        <div class="mobile-action-bar">
          <el-button @click="visibleFiltersVisible = false">关闭</el-button>
          <el-button @click="loadVisibleLedgers()">刷新</el-button>
          <el-button type="primary" @click="applyVisibleFilters">应用筛选</el-button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { FundLedger } from '@/api/admin'
import {
  adminCreateRechargeEntry,
  adminListSelfFundLedgers,
  adminListVisibleFundLedgers,
} from '@/api/admin'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { centsToYuan, formatDateTime, ledgerBizLabel, yuanToCents } from '@/utils/adminConsole'
import { useResponsive } from '@/composables/useResponsive'

const store = useAdminConsoleStore()
const { isCompact } = useResponsive()
const canCreateRecharge = computed(() => store.hasPermission('agents.write'))
const submittingRecharge = ref(false)
const visibleLedgerAccountId = ref<number | undefined>(undefined)
const lastActionMessage = ref('')
const selfFiltersVisible = ref(false)
const visibleFiltersVisible = ref(false)
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
  if (!store.accounts.length) return [store.profile.account]
  if (store.hasRole('super_admin')) return store.accounts
  return store.accounts.filter((account) => account.parent_account_id === store.profile?.account.id)
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

const applySelfFilters = async () => {
  selfFiltersVisible.value = false
  await loadSelfLedgers(true)
}

const applyVisibleFilters = async () => {
  visibleFiltersVisible.value = false
  await loadVisibleLedgers(true)
}

const submitRecharge = async () => {
  if (!canCreateRecharge.value) {
    ElMessage.warning('当前账号无权直接充值入账')
    return
  }
  if (!rechargeForm.subject_account_id || rechargeForm.amount_yuan <= 0) {
    ElMessage.warning('请选择充值主体并填写金额')
    return
  }
  submittingRecharge.value = true
  try {
    const amountCents = yuanToCents(rechargeForm.amount_yuan)
    const response = await adminCreateRechargeEntry({
      subject_account_id: rechargeForm.subject_account_id,
      amount_cents: amountCents,
      remark: rechargeForm.remark || undefined,
    })
    rechargeForm.amount_yuan = 0
    rechargeForm.remark = ''
    const tasks: Promise<unknown>[] = [store.loadProfile(), loadSelfLedgers(true), loadVisibleLedgers(true)]
    if (canCreateRecharge.value || store.canViewVisibleLedgers) {
      tasks.push(store.loadAccounts())
    }
    await Promise.all(tasks)
    lastActionMessage.value = `${response.data.display_name} 已直接充值入账 ¥${centsToYuan(amountCents)}`
    ElMessage.success('充值已直接入账')
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
  await Promise.all(tasks)
  if (store.profile) {
    rechargeForm.subject_account_id = rechargeTargets.value[0]?.id || store.profile.account.id
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
  flex-wrap: wrap;
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
