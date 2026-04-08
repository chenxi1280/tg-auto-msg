<template>
  <div class="page-stack">
    <el-alert v-if="lastActionMessage" :title="lastActionMessage" type="success" :closable="true" @close="lastActionMessage = ''" />

    <div class="form-grid">
      <el-card v-if="store.canCreateMasterAgents" shadow="hover">
        <template #header>
          <div class="card-header">
            <span>创建省总代</span>
            <span class="card-tip">每省仅允许一个总代账号</span>
          </div>
        </template>
        <el-form label-position="top">
          <el-form-item label="登录账号">
            <el-input v-model.trim="masterForm.username" />
          </el-form-item>
          <el-form-item label="显示名称">
            <el-input v-model.trim="masterForm.display_name" />
          </el-form-item>
          <el-form-item label="初始密码">
            <el-input v-model="masterForm.password" type="password" show-password />
          </el-form-item>
          <el-form-item label="总代总额度（元）">
            <el-input-number v-model="masterForm.credit_limit_yuan" :min="0" :step="100" :precision="2" />
          </el-form-item>
          <el-form-item label="授信白名单">
            <el-switch v-model="masterForm.is_credit_whitelisted" />
          </el-form-item>
          <el-button type="primary" :loading="submittingMaster" @click="submitCreateMaster">创建总代</el-button>
        </el-form>
      </el-card>

      <el-card v-if="store.canCreateChildAgents && !store.hasRole('super_admin')" shadow="hover">
        <template #header>
          <div class="card-header">
            <span>创建直属下级</span>
            <span class="card-tip">默认走线下充值余额制</span>
          </div>
        </template>
        <el-form label-position="top">
          <el-form-item label="登录账号">
            <el-input v-model.trim="childForm.username" />
          </el-form-item>
          <el-form-item label="显示名称">
            <el-input v-model.trim="childForm.display_name" />
          </el-form-item>
          <el-form-item label="初始密码">
            <el-input v-model="childForm.password" type="password" show-password />
          </el-form-item>
          <el-form-item label="结算模式">
            <el-select v-model="childForm.settlement_mode">
              <el-option label="预付余额" value="prepaid" />
              <el-option label="授信" value="credit" />
              <el-option label="混合" value="hybrid" />
            </el-select>
          </el-form-item>
          <el-form-item label="初始受限额度（元）">
            <el-input-number v-model="childForm.credit_limit_yuan" :min="0" :step="100" :precision="2" />
          </el-form-item>
          <el-button type="primary" :loading="submittingChild" @click="submitCreateChild">创建下级</el-button>
        </el-form>
      </el-card>
    </div>

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>代理树与后台账号</span>
          <div class="header-actions">
            <el-input v-model.trim="filters.search" clearable placeholder="搜索账号/显示名" style="width: 220px" />
            <el-select v-model="filters.role_code" clearable placeholder="角色" style="width: 140px">
              <el-option label="超管" value="super_admin" />
              <el-option label="总代" value="master_agent" />
              <el-option label="下级代理" value="sub_agent" />
            </el-select>
            <el-select v-model="filters.status" clearable placeholder="状态" style="width: 140px">
              <el-option label="启用" value="active" />
              <el-option label="停用" value="disabled" />
            </el-select>
            <el-button @click="loadAccountsPage(true)">查询</el-button>
            <el-button @click="refreshData">刷新</el-button>
          </div>
        </div>
      </template>
      <el-table :data="accountRows" stripe>
        <el-table-column label="账号" min-width="220">
          <template #default="{ row }">
            <div class="account-cell" :style="{ paddingLeft: `${12 + row.level_depth * 18}px` }">
              <div class="account-title">{{ row.display_name }}</div>
              <div class="account-subtitle">{{ row.username }}</div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="角色" width="110">
          <template #default="{ row }">
            <el-tag>{{ roleLabel(row.role_code) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="结算模式" width="120">
          <template #default="{ row }">{{ settlementLabel(row.settlement_mode) }}</template>
        </el-table-column>
        <el-table-column label="余额" width="120">
          <template #default="{ row }">¥{{ centsToYuan(row.balance_cents) }}</template>
        </el-table-column>
        <el-table-column label="总额度" width="120">
          <template #default="{ row }">¥{{ centsToYuan(row.credit_limit_cents) }}</template>
        </el-table-column>
        <el-table-column label="已分配" width="120">
          <template #default="{ row }">¥{{ centsToYuan(row.allocated_credit_limit_cents) }}</template>
        </el-table-column>
        <el-table-column label="授信白名单" width="120">
          <template #default="{ row }">
            <el-tag :type="row.is_credit_whitelisted ? 'success' : 'info'">
              {{ row.is_credit_whitelisted ? '已开通' : '未开通' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="320" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="store.canManageMasterCredit && row.role_code === 'master_agent'"
              link
              type="primary"
              @click="openCreditDialog(row, 'master')"
            >
              设置总代额度
            </el-button>
            <el-button
              v-if="row.parent_account_id && store.hasPermission('agents.write')"
              link
              type="primary"
              @click="openCreditDialog(row, 'child')"
            >
              设置下级额度
            </el-button>
            <el-button
              v-if="row.id !== store.profile?.account.id && store.hasPermission('agents.write')"
              link
              type="primary"
              @click="openSettlementDialog(row)"
            >
              结算模式
            </el-button>
            <el-button
              v-if="store.canManageMasterCredit"
              link
              type="warning"
              @click="toggleWhitelist(row)"
            >
              {{ row.is_credit_whitelisted ? '取消白名单' : '授信白名单' }}
            </el-button>
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
          :total="totalAccounts"
          @current-change="handlePageChange"
          @size-change="handleSizeChange"
        />
      </div>
    </el-card>

    <el-dialog v-model="creditDialog.visible" :title="creditDialog.mode === 'master' ? '设置总代额度' : '设置下级额度'" width="420px">
      <el-form label-position="top">
        <el-form-item label="目标账号">
          <el-input :model-value="creditDialog.account?.display_name || ''" disabled />
        </el-form-item>
        <el-form-item label="额度（元）">
          <el-input-number v-model="creditDialog.credit_limit_yuan" :min="0" :step="100" :precision="2" />
        </el-form-item>
        <el-form-item v-if="creditDialog.mode === 'master'" label="授信白名单">
          <el-switch v-model="creditDialog.is_credit_whitelisted" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="creditDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="submittingCredit" @click="submitCreditUpdate">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="settlementDialog.visible" title="调整结算模式" width="420px">
      <el-form label-position="top">
        <el-form-item label="目标账号">
          <el-input :model-value="settlementDialog.account?.display_name || ''" disabled />
        </el-form-item>
        <el-form-item label="结算模式">
          <el-select v-model="settlementDialog.settlement_mode">
            <el-option label="预付余额" value="prepaid" />
            <el-option label="授信" value="credit" />
            <el-option label="混合" value="hybrid" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="settlementDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="submittingSettlementMode" @click="submitSettlementMode">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { AgentAccount } from '@/api/admin'
import {
  adminCreateAgentAccount,
  adminCreateMasterAgent,
  adminListAccounts,
  adminSetChildCreditLimit,
  adminSetCreditWhitelist,
  adminSetMasterCreditLimit,
  adminSetSettlementMode,
} from '@/api/admin'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { centsToYuan, roleLabel, settlementLabel, yuanToCents } from '@/utils/adminConsole'

const store = useAdminConsoleStore()
const lastActionMessage = ref('')
const accountRows = ref<AgentAccount[]>([])
const totalAccounts = ref(0)
const pagination = reactive({
  currentPage: 1,
  pageSize: 20,
})
const filters = reactive({
  search: '',
  role_code: '',
  status: '',
})

const masterForm = reactive({
  username: '',
  password: '',
  display_name: '',
  credit_limit_yuan: 0,
  is_credit_whitelisted: false,
})

const childForm = reactive({
  username: '',
  password: '',
  display_name: '',
  settlement_mode: 'prepaid',
  credit_limit_yuan: 0,
})

const creditDialog = reactive<{
  visible: boolean
  mode: 'master' | 'child'
  account: AgentAccount | null
  credit_limit_yuan: number
  is_credit_whitelisted: boolean
}>({
  visible: false,
  mode: 'child',
  account: null,
  credit_limit_yuan: 0,
  is_credit_whitelisted: false,
})

const settlementDialog = reactive<{
  visible: boolean
  account: AgentAccount | null
  settlement_mode: string
}>({
  visible: false,
  account: null,
  settlement_mode: 'prepaid',
})

const submittingMaster = ref(false)
const submittingChild = ref(false)
const submittingCredit = ref(false)
const submittingSettlementMode = ref(false)

const loadAccountsPage = async (resetPage = false) => {
  if (resetPage) pagination.currentPage = 1
  const response = await adminListAccounts({
    search: filters.search || undefined,
    role_code: filters.role_code || undefined,
    status: filters.status || undefined,
    limit: pagination.pageSize,
    offset: (pagination.currentPage - 1) * pagination.pageSize,
  })
  accountRows.value = response.data.items
  totalAccounts.value = response.data.total
  if (!accountRows.value.length && totalAccounts.value > 0 && pagination.currentPage > 1) {
    pagination.currentPage -= 1
    await loadAccountsPage()
  }
}

const refreshData = async () => {
  await Promise.all([store.loadProfile(), store.loadAccounts(), loadAccountsPage()])
}

const handlePageChange = async () => {
  await loadAccountsPage()
}

const handleSizeChange = async () => {
  pagination.currentPage = 1
  await loadAccountsPage()
}

const submitCreateMaster = async () => {
  if (!store.profile) return
  submittingMaster.value = true
  try {
    await adminCreateMasterAgent(store.profile.province_code, {
      username: masterForm.username,
      password: masterForm.password,
      display_name: masterForm.display_name,
      credit_limit_cents: yuanToCents(masterForm.credit_limit_yuan),
      is_credit_whitelisted: masterForm.is_credit_whitelisted,
    })
    Object.assign(masterForm, {
      username: '',
      password: '',
      display_name: '',
      credit_limit_yuan: 0,
      is_credit_whitelisted: false,
    })
    await refreshData()
    lastActionMessage.value = '总代已创建'
    ElMessage.success(lastActionMessage.value)
  } finally {
    submittingMaster.value = false
  }
}

const submitCreateChild = async () => {
  submittingChild.value = true
  try {
    await adminCreateAgentAccount({
      username: childForm.username,
      password: childForm.password,
      display_name: childForm.display_name,
      settlement_mode: childForm.settlement_mode,
      credit_limit_cents: yuanToCents(childForm.credit_limit_yuan),
    })
    Object.assign(childForm, {
      username: '',
      password: '',
      display_name: '',
      settlement_mode: 'prepaid',
      credit_limit_yuan: 0,
    })
    await refreshData()
    lastActionMessage.value = '下级代理已创建'
    ElMessage.success(lastActionMessage.value)
  } finally {
    submittingChild.value = false
  }
}

const openCreditDialog = (account: AgentAccount, mode: 'master' | 'child') => {
  creditDialog.visible = true
  creditDialog.mode = mode
  creditDialog.account = account
  creditDialog.credit_limit_yuan = account.credit_limit_cents / 100
  creditDialog.is_credit_whitelisted = account.is_credit_whitelisted
}

const submitCreditUpdate = async () => {
  if (!creditDialog.account) return
  submittingCredit.value = true
  try {
    if (creditDialog.mode === 'master') {
      await adminSetMasterCreditLimit(creditDialog.account.id, {
        credit_limit_cents: yuanToCents(creditDialog.credit_limit_yuan),
        is_credit_whitelisted: creditDialog.is_credit_whitelisted,
      })
    } else {
      await adminSetChildCreditLimit(creditDialog.account.id, yuanToCents(creditDialog.credit_limit_yuan))
    }
    creditDialog.visible = false
    await refreshData()
    lastActionMessage.value = '额度已更新'
    ElMessage.success(lastActionMessage.value)
  } finally {
    submittingCredit.value = false
  }
}

const openSettlementDialog = (account: AgentAccount) => {
  settlementDialog.visible = true
  settlementDialog.account = account
  settlementDialog.settlement_mode = account.settlement_mode
}

const submitSettlementMode = async () => {
  if (!settlementDialog.account) return
  submittingSettlementMode.value = true
  try {
    await adminSetSettlementMode(settlementDialog.account.id, settlementDialog.settlement_mode)
    settlementDialog.visible = false
    await refreshData()
    lastActionMessage.value = '结算模式已更新'
    ElMessage.success(lastActionMessage.value)
  } finally {
    submittingSettlementMode.value = false
  }
}

const toggleWhitelist = async (account: AgentAccount) => {
  await adminSetCreditWhitelist(account.id, !account.is_credit_whitelisted)
  await refreshData()
  lastActionMessage.value = '授信白名单已更新'
  ElMessage.success(lastActionMessage.value)
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

.form-grid {
  display: grid;
  gap: 20px;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
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

.card-tip {
  color: #94a3b8;
  font-size: 12px;
}

.account-cell {
  display: flex;
  flex-direction: column;
}

.account-title {
  font-weight: 600;
  color: #0f172a;
}

.account-subtitle {
  font-size: 12px;
  color: #64748b;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
