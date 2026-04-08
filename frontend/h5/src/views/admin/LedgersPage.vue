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
        <div class="stat-label">当前筛选入账</div>
        <div class="stat-value">¥{{ centsToYuan(selfInAmount) }}</div>
        <div class="stat-meta">{{ selfInCount }} 条流水</div>
      </el-card>
      <el-card shadow="hover">
        <div class="stat-label">当前筛选扣减</div>
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

    <el-card shadow="hover">
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
            <el-button @click="store.loadSelfLedgers()">刷新</el-button>
          </div>
        </div>
      </template>
      <el-table :data="filteredSelfLedgers" stripe>
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
    </el-card>

    <el-card v-if="store.canViewVisibleLedgers" shadow="hover">
      <template #header>
        <div class="card-header">
          <span>下级资金流水审计</span>
          <div class="header-actions">
            <el-select v-model="visibleLedgerAccountId" clearable filterable placeholder="筛选账号" style="width: 240px" @change="loadVisibleLedgers">
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
            <el-input v-model.trim="visibleFilters.keyword" clearable placeholder="搜索账号/备注/批次" style="width: 240px" />
            <el-button @click="loadVisibleLedgers">刷新</el-button>
          </div>
        </div>
      </template>
      <div class="selection-bar">当前审计流水 {{ filteredVisibleLedgers.length }} 条</div>
      <el-table :data="filteredVisibleLedgers" stripe>
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
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { adminCreateRechargeRequest } from '@/api/admin'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { centsToYuan, formatDateTime, ledgerBizLabel, yuanToCents } from '@/utils/adminConsole'

const store = useAdminConsoleStore()
const submittingRecharge = ref(false)
const visibleLedgerAccountId = ref<number | undefined>(undefined)
const lastActionMessage = ref('')

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
  keyword: '',
})

const rechargeTargets = computed(() => {
  if (!store.profile) return []
  return store.accounts.length ? store.accounts : [store.profile.account]
})

const filteredSelfLedgers = computed(() => {
  const keyword = selfFilters.keyword.trim().toLowerCase()
  return store.selfLedgers.filter((row) => {
    if (selfFilters.biz_type !== 'all' && row.biz_type !== selfFilters.biz_type) return false
    if (selfFilters.direction !== 'all' && row.direction !== selfFilters.direction) return false
    if (
      keyword &&
      ![
        String(row.counterparty_name || ''),
        String(row.remark || ''),
        String(row.related_batch_id || ''),
      ].some((part) => part.toLowerCase().includes(keyword))
    ) {
      return false
    }
    return true
  })
})

const filteredVisibleLedgers = computed(() => {
  const keyword = visibleFilters.keyword.trim().toLowerCase()
  return store.visibleLedgers.filter((row) => {
    if (visibleFilters.biz_type !== 'all' && row.biz_type !== visibleFilters.biz_type) return false
    if (
      keyword &&
      ![
        String(row.account_name || ''),
        String(row.counterparty_name || ''),
        String(row.operator_name || ''),
        String(row.remark || ''),
        String(row.related_batch_id || ''),
      ].some((part) => part.toLowerCase().includes(keyword))
    ) {
      return false
    }
    return true
  })
})

const selfInRows = computed(() => filteredSelfLedgers.value.filter((row) => row.direction === 'in'))
const selfOutRows = computed(() => filteredSelfLedgers.value.filter((row) => row.direction === 'out'))
const selfInCount = computed(() => selfInRows.value.length)
const selfOutCount = computed(() => selfOutRows.value.length)
const selfInAmount = computed(() => selfInRows.value.reduce((sum, row) => sum + (row.amount_cents || 0), 0))
const selfOutAmount = computed(() => selfOutRows.value.reduce((sum, row) => sum + (row.amount_cents || 0), 0))

const loadVisibleLedgers = async () => {
  await store.loadVisibleLedgers(visibleLedgerAccountId.value)
}

const submitRecharge = async () => {
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
    await Promise.all([store.loadApprovalRequests({ status: 'pending', limit: 100 }), store.loadSelfLedgers(), store.loadVisibleLedgers()])
    lastActionMessage.value = `充值审批 ${response.data.request_id} 已发起，等待上级确认入账`
    ElMessage.success('充值审批已发起')
  } finally {
    submittingRecharge.value = false
  }
}

onMounted(async () => {
  await Promise.all([
    store.loadProfile(),
    store.loadAccounts(),
    store.loadSelfLedgers(),
    store.loadVisibleLedgers(),
    store.loadApprovalRequests({ status: 'pending', limit: 100 }),
  ])
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
</style>
