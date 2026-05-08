<template>
  <div class="page-stack">
    <el-alert v-if="lastActionMessage" :title="lastActionMessage" type="success" :closable="true" @close="lastActionMessage = ''" />

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>用户与授权</span>
          <div class="header-actions">
            <el-button v-if="isCompact" class="mobile-filter-trigger" @click="filtersVisible = true">筛选条件</el-button>
            <template v-else>
              <el-input v-model.trim="filters.search" clearable placeholder="搜索用户名或邮箱" style="width: 240px" @change="queryUsers" />
              <el-button @click="refreshUsers">刷新</el-button>
            </template>
          </div>
        </div>
      </template>
      <div class="toolbar-bar">
        <span class="card-tip">共 {{ total }} 个用户</span>
      </div>
      <el-table v-if="!isCompact" :data="users" stripe highlight-current-row @current-change="handleCurrentUserChange">
        <el-table-column prop="username" label="用户名" min-width="160" />
        <el-table-column prop="email" label="邮箱" min-width="220" />
        <el-table-column label="账号数" width="100">
          <template #default="{ row }">{{ row.account_count }}</template>
        </el-table-column>
        <el-table-column label="TG账号" min-width="180">
          <template #default="{ row }">{{ row.tg_account_summary || '-' }}</template>
        </el-table-column>
        <el-table-column label="任务数" width="120">
          <template #default="{ row }">{{ row.enabled_task_count ?? 0 }} / {{ row.task_count ?? 0 }}</template>
        </el-table-column>
        <el-table-column label="授权状态" min-width="180">
          <template #default="{ row }">
            {{ row.current_authorization?.status || '未授权' }}
            <span class="muted-text"> / 到期 {{ formatDateTime(row.current_authorization?.end_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="开发者应用" min-width="140">
          <template #default="{ row }">
            <div class="developer-app-cell">
              <span>{{ developerAppDisplay(row.developer_app_id).label }}</span>
              <el-tag
                v-if="developerAppDisplay(row.developer_app_id).sourceTag"
                size="small"
                :type="developerAppDisplay(row.developer_app_id).sourceTagType"
              >
                {{ developerAppDisplay(row.developer_app_id).sourceTag }}
              </el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="220" fixed="right">
          <template #default="{ row }">
            <el-button v-if="canResetPassword" link type="primary" @click="openPasswordDialog(row.id)">重置密码</el-button>
            <el-button v-if="canManageUsers && canReadDeveloperApps" link type="success" @click="openDeveloperAppDialog(row.id, row.developer_app_id)">设置应用</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-else class="mobile-card-list">
        <div
          v-for="row in users"
          :key="row.id"
          class="mobile-data-card"
          @click="handleCurrentUserChange(row)"
        >
          <div class="mobile-data-card__header">
            <div>
              <div class="mobile-data-card__title">{{ row.username }}</div>
              <div class="mobile-data-card__subtitle">{{ row.email || '未填写邮箱' }}</div>
            </div>
            <el-tag :type="selectedUserId === row.id ? 'primary' : 'info'">{{ selectedUserId === row.id ? '已选中' : `账号 ${row.account_count}` }}</el-tag>
          </div>
          <div class="mobile-data-card__grid">
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">TG账号</span>
              <span class="mobile-data-card__value">{{ row.tg_account_summary || '-' }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">任务数</span>
              <span class="mobile-data-card__value">{{ row.enabled_task_count ?? 0 }} / {{ row.task_count ?? 0 }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">授权状态</span>
              <span class="mobile-data-card__value">{{ row.current_authorization?.status || '未授权' }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">授权到期</span>
              <span class="mobile-data-card__value">{{ formatDateTime(row.current_authorization?.end_at) }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">开发者应用</span>
              <span class="mobile-data-card__value">{{ developerAppDisplay(row.developer_app_id).label }}</span>
            </div>
          </div>
          <div class="mobile-action-bar">
            <el-button v-if="canResetPassword" type="primary" plain @click.stop="openPasswordDialog(row.id)">重置密码</el-button>
            <el-button
              v-if="canManageUsers && canReadDeveloperApps"
              type="success"
              plain
              @click.stop="openDeveloperAppDialog(row.id, row.developer_app_id)"
            >
              设置应用
            </el-button>
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

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>用户 TG 账号</span>
          <span class="card-tip">{{ selectedUserSummary }}</span>
        </div>
      </template>
      <el-empty v-if="!selectedUserId" description="请选择要查看的用户" />
      <el-table v-else-if="!isCompact" :data="userAccounts" stripe>
        <el-table-column label="TG 账号名" min-width="160">
          <template #default="{ row }">{{ row.tg_account_name || row.username || '-' }}</template>
        </el-table-column>
        <el-table-column prop="tg_user_id" label="TG UID" width="130" />
        <el-table-column prop="phone" label="手机号" width="140" />
        <el-table-column prop="health_status" label="健康状态" width="120" />
        <el-table-column label="任务数" width="120">
          <template #default="{ row }">{{ row.enabled_task_count ?? 0 }} / {{ row.task_count ?? 0 }}</template>
        </el-table-column>
        <el-table-column prop="messages_sent" label="发送数" width="100" />
        <el-table-column label="最近发送" min-width="160">
          <template #default="{ row }">{{ formatDateTime(row.last_send_at) }}</template>
        </el-table-column>
        <el-table-column label="最近状态" width="110">
          <template #default="{ row }">
            <el-tag :type="sendStatusTagType(row.last_send_result)" size="small">{{ formatSendResult(row.last_send_result) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="成功/失败" width="120">
          <template #default="{ row }">{{ row.send_success_count ?? 0 }} / {{ row.send_failed_count ?? 0 }}</template>
        </el-table-column>
        <el-table-column label="开发者应用" min-width="140">
          <template #default="{ row }">
            <div class="developer-app-cell">
              <span>{{ developerAppDisplay(row.developer_app_id).label }}</span>
              <el-tag
                v-if="developerAppDisplay(row.developer_app_id).sourceTag"
                size="small"
                :type="developerAppDisplay(row.developer_app_id).sourceTagType"
              >
                {{ developerAppDisplay(row.developer_app_id).sourceTag }}
              </el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="授权到期" min-width="160">
          <template #default="{ row }">{{ formatDateTime(row.authorization_end_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openSendLogs(row)">发送记录</el-button>
            <el-button v-if="canManageUsers" link type="danger" @click="deleteAccount(row.account_id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
        <div v-else class="mobile-card-list">
        <div v-for="row in userAccounts" :key="row.account_id" class="mobile-data-card">
          <div class="mobile-data-card__header">
            <div>
              <div class="mobile-data-card__title">{{ row.tg_account_name || row.username || row.phone || '未命名 TG 账号' }}</div>
              <div class="mobile-data-card__subtitle">UID {{ row.tg_user_id || '-' }} / {{ row.phone || '未绑定手机号' }}</div>
            </div>
            <el-tag>{{ row.health_status || 'unknown' }}</el-tag>
          </div>
          <div class="mobile-data-card__grid">
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">任务数</span>
              <span class="mobile-data-card__value">{{ row.enabled_task_count ?? 0 }} / {{ row.task_count ?? 0 }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">发送数</span>
              <span class="mobile-data-card__value">{{ row.messages_sent ?? 0 }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">最近发送</span>
              <span class="mobile-data-card__value">{{ formatDateTime(row.last_send_at) }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">发送状态</span>
              <span class="mobile-data-card__value">{{ formatSendResult(row.last_send_result) }}（{{ row.send_success_count ?? 0 }} / {{ row.send_failed_count ?? 0 }}）</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">最近错误</span>
              <span class="mobile-data-card__value">{{ row.last_send_error_message || '-' }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">开发者应用</span>
              <span class="mobile-data-card__value">{{ developerAppDisplay(row.developer_app_id).label }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">授权到期</span>
              <span class="mobile-data-card__value">{{ formatDateTime(row.authorization_end_at) }}</span>
            </div>
          </div>
          <div class="mobile-action-bar">
            <el-button type="primary" plain @click="openSendLogs(row)">发送记录</el-button>
            <el-button v-if="canManageUsers" type="danger" plain @click="deleteAccount(row.account_id)">删除</el-button>
          </div>
        </div>
      </div>
    </el-card>

    <ResponsiveFormLayer v-model="passwordDialog.visible" title="重置用户密码" width="420px">
      <el-form label-position="top">
        <el-form-item label="新密码">
          <el-input v-model="passwordDialog.new_password" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="passwordDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="savingPassword" @click="savePassword">保存</el-button>
      </template>
    </ResponsiveFormLayer>

    <ResponsiveFormLayer v-model="developerAppDialog.visible" title="设置用户开发者应用" width="420px">
      <el-form label-position="top">
        <el-form-item label="开发者应用">
          <el-select v-model="developerAppDialog.developer_app_id" clearable style="width: 100%">
            <el-option v-for="app in developerApps" :key="app.id" :label="app.app_name" :value="app.id" />
          </el-select>
          <div class="form-tip">留空表示使用当前系统默认开发应用。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="developerAppDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="savingDeveloperApp" @click="saveDeveloperApp">保存</el-button>
      </template>
    </ResponsiveFormLayer>

    <el-drawer v-model="filtersVisible" title="筛选用户" size="100%" append-to-body>
      <div class="mobile-card-list">
        <el-input v-model.trim="filters.search" clearable placeholder="搜索用户名或邮箱" />
        <div class="mobile-action-bar">
          <el-button @click="filtersVisible = false">关闭</el-button>
          <el-button @click="refreshUsers">刷新</el-button>
          <el-button type="primary" @click="applyMobileFilters">应用筛选</el-button>
        </div>
      </div>
    </el-drawer>

    <el-drawer v-model="sendLogDrawer.visible" :title="sendLogDrawer.title" :size="isCompact ? '100%' : '720px'" append-to-body>
      <div class="send-log-toolbar">
        <el-select v-model="sendLogFilters.result" style="width: 140px" @change="querySendLogs">
          <el-option label="全部状态" value="all" />
          <el-option label="成功" value="success" />
          <el-option label="失败" value="failed" />
        </el-select>
        <el-button :loading="sendLogLoading" @click="loadSendLogs">刷新</el-button>
      </div>
      <el-table v-if="!isCompact" :data="sendLogs" stripe v-loading="sendLogLoading" empty-text="暂无发送记录">
        <el-table-column label="发送时间" min-width="170">
          <template #default="{ row }">{{ formatDateTime(row.send_at) }}</template>
        </el-table-column>
        <el-table-column prop="task_title" label="任务" min-width="160" show-overflow-tooltip />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="sendStatusTagType(row.result)" size="small">{{ formatSendResult(row.result) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="触发方式" width="110">
          <template #default="{ row }">{{ formatTriggerSource(row.trigger_source) }}</template>
        </el-table-column>
        <el-table-column prop="error_code" label="错误码" width="120" show-overflow-tooltip />
        <el-table-column prop="error_message" label="错误信息" min-width="220" show-overflow-tooltip />
      </el-table>
      <div v-else class="mobile-card-list" v-loading="sendLogLoading">
        <div v-for="row in sendLogs" :key="row.id" class="mobile-data-card">
          <div class="mobile-data-card__header">
            <div>
              <div class="mobile-data-card__title">{{ row.task_title || '未命名任务' }}</div>
              <div class="mobile-data-card__subtitle">{{ formatDateTime(row.send_at) }}</div>
            </div>
            <el-tag :type="sendStatusTagType(row.result)">{{ formatSendResult(row.result) }}</el-tag>
          </div>
          <div class="mobile-data-card__grid">
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">触发方式</span>
              <span class="mobile-data-card__value">{{ formatTriggerSource(row.trigger_source) }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">错误码</span>
              <span class="mobile-data-card__value">{{ row.error_code || '-' }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">错误信息</span>
              <span class="mobile-data-card__value">{{ row.error_message || '-' }}</span>
            </div>
          </div>
        </div>
      </div>
      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="sendLogPagination.currentPage"
          v-model:page-size="sendLogPagination.pageSize"
          background
          layout="total, sizes, prev, pager, next"
          :page-sizes="[20, 50, 100]"
          :total="sendLogTotal"
          @current-change="handleSendLogPageChange"
          @size-change="handleSendLogSizeChange"
        />
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { DeveloperApp, LegacyUser, LegacyUserAccount, LegacyUserAccountSendLog } from '@/api/admin'
import {
  adminDeleteManagedAccount,
  adminListDeveloperApps,
  adminListUserAccountSendLogs,
  adminListUserAccounts,
  adminListUsers,
  adminResetUserPassword,
  adminSetUserDeveloperApp,
} from '@/api/admin'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { formatDateTime } from '@/utils/adminConsole'
import { useResponsive } from '@/composables/useResponsive'
import ResponsiveFormLayer from '@/components/responsive/ResponsiveFormLayer.vue'

const store = useAdminConsoleStore()
const { isCompact } = useResponsive()
const canManageUsers = computed(() => store.hasPermission('users.write'))
const canResetPassword = computed(() => store.hasPermission('users.reset_password'))
const canReadDeveloperApps = computed(() => store.hasPermission('developer_apps.read'))
const filters = reactive({
  search: '',
})

const users = ref<LegacyUser[]>([])
const userAccounts = ref<LegacyUserAccount[]>([])
const sendLogs = ref<LegacyUserAccountSendLog[]>([])
const developerApps = ref<DeveloperApp[]>([])
const selectedUserId = ref<number | null>(null)
const total = ref(0)
const lastActionMessage = ref('')
const filtersVisible = ref(false)
const sendLogLoading = ref(false)
const sendLogTotal = ref(0)

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

const sendLogDrawer = reactive({
  visible: false,
  user_id: 0,
  account_id: '',
  title: '发送记录',
})

const sendLogFilters = reactive({
  result: 'all',
})

const sendLogPagination = reactive({
  currentPage: 1,
  pageSize: 20,
})

const defaultDeveloperApp = computed(() => {
  const responseSettings = store.developerAppSettings
  const appId = responseSettings?.default_developer_app_id ?? null
  const appName = responseSettings?.default_developer_app_name?.trim() || ''
  const matchedApp = appId ? developerApps.value.find((item) => item.id === appId) : null
  return {
    id: appId,
    name: appName || matchedApp?.app_name || '',
    isActive:
      responseSettings?.default_developer_app_active ??
      (matchedApp ? Boolean(matchedApp.is_active) : false),
  }
})

const selectedUser = computed(() => users.value.find((item) => item.id === selectedUserId.value) || null)

const selectedUserSummary = computed(() => {
  if (!selectedUser.value) return '请先从上方选择一个用户'
  return `当前查看：${selectedUser.value.username || selectedUser.value.email || '未命名用户'}`
})

const developerAppDisplay = (appId?: number | null) => {
  if (appId) {
    return {
      label: developerApps.value.find((item) => item.id === appId)?.app_name || `应用#${appId}`,
      sourceTag: '',
      sourceTagType: 'info' as const,
    }
  }

  if (!canReadDeveloperApps.value) {
    return {
      label: '系统默认应用',
      sourceTag: '',
      sourceTagType: 'info' as const,
    }
  }

  if (defaultDeveloperApp.value.name) {
    return {
      label: defaultDeveloperApp.value.name,
      sourceTag: '系统默认',
      sourceTagType: defaultDeveloperApp.value.isActive ? ('success' as const) : ('warning' as const),
    }
  }

  return {
    label: '未配置默认应用',
    sourceTag: '需处理',
    sourceTagType: 'danger' as const,
  }
}

const sendStatusTagType = (result?: string | null) => {
  if (result === 'success') return 'success'
  if (result === 'failed') return 'danger'
  return 'info'
}

const formatSendResult = (result?: string | null) => {
  if (result === 'success') return '成功'
  if (result === 'failed') return '失败'
  return '暂无'
}

const formatTriggerSource = (source?: string | null) => {
  const normalized = (source || '').toLowerCase()
  const labels: Record<string, string> = {
    manual: '手动执行',
    manual_shortcut: '手动任务',
    bot_shortcut: '手动任务',
    scheduler: '定时调度',
    scheduled: '定时调度',
    api_manual: '后台触发',
    api: '系统触发',
  }
  return labels[normalized] || '系统触发'
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

const applyMobileFilters = async () => {
  filtersVisible.value = false
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
  store.developerAppSettings = {
    ...store.developerAppSettings,
    ...response.data.settings,
  }
}

const loadUserAccounts = async () => {
  if (!selectedUserId.value) {
    userAccounts.value = []
    return
  }
  const response = await adminListUserAccounts(selectedUserId.value)
  userAccounts.value = response.data
}

const loadSendLogs = async () => {
  if (!sendLogDrawer.user_id || !sendLogDrawer.account_id) {
    sendLogs.value = []
    sendLogTotal.value = 0
    return
  }
  sendLogLoading.value = true
  try {
    const response = await adminListUserAccountSendLogs(sendLogDrawer.user_id, sendLogDrawer.account_id, {
      result: sendLogFilters.result === 'all' ? undefined : sendLogFilters.result,
      limit: sendLogPagination.pageSize,
      offset: (sendLogPagination.currentPage - 1) * sendLogPagination.pageSize,
    })
    sendLogs.value = response.data.items
    sendLogTotal.value = response.data.total
    if (!sendLogs.value.length && sendLogTotal.value > 0 && sendLogPagination.currentPage > 1) {
      sendLogPagination.currentPage -= 1
      await loadSendLogs()
    }
  } finally {
    sendLogLoading.value = false
  }
}

const querySendLogs = async () => {
  sendLogPagination.currentPage = 1
  await loadSendLogs()
}

const handleSendLogPageChange = async () => {
  await loadSendLogs()
}

const handleSendLogSizeChange = async () => {
  sendLogPagination.currentPage = 1
  await loadSendLogs()
}

const openSendLogs = async (account: LegacyUserAccount) => {
  if (!selectedUserId.value) return
  sendLogDrawer.visible = true
  sendLogDrawer.user_id = selectedUserId.value
  sendLogDrawer.account_id = account.account_id
  sendLogDrawer.title = `发送记录：${account.tg_account_name || account.username || account.phone || account.account_id}`
  sendLogFilters.result = 'all'
  sendLogPagination.currentPage = 1
  await loadSendLogs()
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

.developer-app-cell {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.form-tip {
  margin-top: 8px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
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

.send-log-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.pagination-wrap {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
