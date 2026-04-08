<template>
  <div class="page-stack">
    <el-alert v-if="lastActionMessage" :title="lastActionMessage" type="success" :closable="true" @close="lastActionMessage = ''" />

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>用户与授权</span>
          <div class="header-actions">
            <el-input v-model.trim="filters.search" clearable placeholder="搜索用户名或邮箱" style="width: 240px" @change="queryUsers" />
            <el-button @click="refreshUsers">刷新</el-button>
          </div>
        </div>
      </template>
      <div class="toolbar-bar">
        <span class="card-tip">共 {{ total }} 个用户</span>
      </div>
      <el-table :data="users" stripe highlight-current-row @current-change="handleCurrentUserChange">
        <el-table-column prop="id" label="用户 ID" width="100" />
        <el-table-column prop="username" label="用户名" min-width="160" />
        <el-table-column prop="email" label="邮箱" min-width="220" />
        <el-table-column label="账号数" width="100">
          <template #default="{ row }">{{ row.account_count }}</template>
        </el-table-column>
        <el-table-column label="授权状态" min-width="180">
          <template #default="{ row }">
            {{ row.current_authorization?.status || '未授权' }}
            <span class="muted-text"> / 到期 {{ formatDateTime(row.current_authorization?.end_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="开发者应用" min-width="140">
          <template #default="{ row }">
            {{ developerAppName(row.developer_app_id) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="220" fixed="right">
          <template #default="{ row }">
            <el-button v-if="canResetPassword" link type="primary" @click="openPasswordDialog(row.id)">重置密码</el-button>
            <el-button v-if="canManageUsers && canReadDeveloperApps" link type="success" @click="openDeveloperAppDialog(row.id, row.developer_app_id)">设置应用</el-button>
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
          :total="total"
          @current-change="handlePageChange"
          @size-change="handleSizeChange"
        />
      </div>
    </el-card>

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>用户 TG 账号</span>
          <span class="card-tip">{{ selectedUserId ? `当前查看用户 ${selectedUserId}` : '请先从上方选择一个用户' }}</span>
        </div>
      </template>
      <el-empty v-if="!selectedUserId" description="请选择要查看的用户" />
      <el-table v-else :data="userAccounts" stripe>
        <el-table-column prop="account_id" label="账号 ID" min-width="180" />
        <el-table-column prop="username" label="TG 用户名" width="140" />
        <el-table-column prop="phone" label="手机号" width="140" />
        <el-table-column prop="health_status" label="健康状态" width="120" />
        <el-table-column label="开发者应用" min-width="140">
          <template #default="{ row }">{{ developerAppName(row.developer_app_id) }}</template>
        </el-table-column>
        <el-table-column label="授权到期" min-width="160">
          <template #default="{ row }">{{ formatDateTime(row.authorization_end_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button v-if="canManageUsers" link type="danger" @click="deleteAccount(row.account_id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="passwordDialog.visible" title="重置用户密码" width="420px">
      <el-form label-position="top">
        <el-form-item label="新密码">
          <el-input v-model="passwordDialog.new_password" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="passwordDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="savingPassword" @click="savePassword">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="developerAppDialog.visible" title="设置用户开发者应用" width="420px">
      <el-form label-position="top">
        <el-form-item label="开发者应用">
          <el-select v-model="developerAppDialog.developer_app_id" clearable style="width: 100%">
            <el-option v-for="app in developerApps" :key="app.id" :label="app.app_name" :value="app.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="developerAppDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="savingDeveloperApp" @click="saveDeveloperApp">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { DeveloperApp, LegacyUser, LegacyUserAccount } from '@/api/admin'
import {
  adminDeleteManagedAccount,
  adminListDeveloperApps,
  adminListUserAccounts,
  adminListUsers,
  adminResetUserPassword,
  adminSetUserDeveloperApp,
} from '@/api/admin'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { formatDateTime } from '@/utils/adminConsole'

const store = useAdminConsoleStore()
const canManageUsers = computed(() => store.hasPermission('users.write'))
const canResetPassword = computed(() => store.hasPermission('users.reset_password'))
const canReadDeveloperApps = computed(() => store.hasPermission('developer_apps.read'))
const filters = reactive({
  search: '',
})

const users = ref<LegacyUser[]>([])
const userAccounts = ref<LegacyUserAccount[]>([])
const developerApps = ref<DeveloperApp[]>([])
const selectedUserId = ref<number | null>(null)
const total = ref(0)
const lastActionMessage = ref('')

const savingPassword = ref(false)
const savingDeveloperApp = ref(false)

const pagination = reactive({
  currentPage: 1,
  pageSize: 20,
})

const passwordDialog = reactive({
  visible: false,
  user_id: 0,
  new_password: '',
})

const developerAppDialog = reactive({
  visible: false,
  user_id: 0,
  developer_app_id: null as number | null,
})

const developerAppName = (appId?: number | null) => {
  if (!appId) return '跟随系统'
  return developerApps.value.find((item) => item.id === appId)?.app_name || `应用#${appId}`
}

const loadUsers = async (resetPage = false) => {
  if (resetPage) pagination.currentPage = 1
  const response = await adminListUsers({
    search: filters.search || undefined,
    limit: pagination.pageSize,
    offset: (pagination.currentPage - 1) * pagination.pageSize,
  })
  users.value = response.data.items
  total.value = response.data.total
  if (!users.value.length && total.value > 0 && pagination.currentPage > 1) {
    pagination.currentPage -= 1
    await loadUsers()
  }
}

const handlePageChange = async () => {
  await loadUsers()
}

const handleSizeChange = async () => {
  pagination.currentPage = 1
  await loadUsers()
}

const queryUsers = async () => {
  await loadUsers(true)
}

const refreshUsers = async () => {
  await loadUsers()
}

const loadDeveloperApps = async () => {
  if (!canReadDeveloperApps.value) {
    developerApps.value = []
    return
  }
  const response = await adminListDeveloperApps({ limit: 500, offset: 0 })
  developerApps.value = response.data.items
}

const loadUserAccounts = async () => {
  if (!selectedUserId.value) {
    userAccounts.value = []
    return
  }
  const response = await adminListUserAccounts(selectedUserId.value)
  userAccounts.value = response.data
}

const handleCurrentUserChange = async (row?: LegacyUser) => {
  selectedUserId.value = row?.id || null
  await loadUserAccounts()
}

const openPasswordDialog = (userId: number) => {
  passwordDialog.visible = true
  passwordDialog.user_id = userId
  passwordDialog.new_password = ''
}

const savePassword = async () => {
  savingPassword.value = true
  try {
    await adminResetUserPassword(passwordDialog.user_id, passwordDialog.new_password)
    passwordDialog.visible = false
    lastActionMessage.value = '用户密码已重置'
    ElMessage.success(lastActionMessage.value)
  } finally {
    savingPassword.value = false
  }
}

const openDeveloperAppDialog = (userId: number, developerAppId: number | null) => {
  developerAppDialog.visible = true
  developerAppDialog.user_id = userId
  developerAppDialog.developer_app_id = developerAppId
}

const saveDeveloperApp = async () => {
  savingDeveloperApp.value = true
  try {
    await adminSetUserDeveloperApp(developerAppDialog.user_id, developerAppDialog.developer_app_id)
    developerAppDialog.visible = false
    await loadUsers()
    if (selectedUserId.value === developerAppDialog.user_id) {
      await loadUserAccounts()
    }
    lastActionMessage.value = '用户开发者应用已更新'
    ElMessage.success(lastActionMessage.value)
  } finally {
    savingDeveloperApp.value = false
  }
}

const deleteAccount = async (accountId: string) => {
  await ElMessageBox.confirm('删除该 TG 账号后无法恢复，确定继续吗？', '删除 TG 账号', { type: 'warning' })
  await adminDeleteManagedAccount(accountId)
  await loadUserAccounts()
  lastActionMessage.value = '账号已删除'
  ElMessage.success(lastActionMessage.value)
}

onMounted(async () => {
  await Promise.all([loadUsers(), loadDeveloperApps()])
})
</script>

<style scoped>
.page-stack {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.card-header,
.header-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.card-tip,
.muted-text {
  color: #64748b;
  font-size: 13px;
}

.toolbar-bar,
.pagination-wrap {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.toolbar-bar {
  margin-bottom: 16px;
}

.pagination-wrap {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
