<template>
  <div class="accounts-page">
    <!-- 头部 -->
    <header class="header">
      <div class="container">
        <div class="brand-header">
          <img class="brand-logo" src="/quanqiu.png" alt="全球通" />
          <div>
            <h1>全球通账号管理</h1>
          </div>
        </div>
      </div>
    </header>

    <!-- 操作栏 -->
    <div class="toolbar">
      <div class="container">
        <el-button type="primary" @click="goToLogin">
          <el-icon><Plus /></el-icon>
          添加账号
        </el-button>
        <el-button @click="refreshAccounts" :loading="loading">
          <el-icon><Refresh /></el-icon>
          刷新状态
        </el-button>
        <el-button @click="goToMy">
          我的
        </el-button>
        <el-button type="danger" plain @click="handleLogout">
          注销
        </el-button>
        <div class="stats">
          <el-tag>总计: {{ accounts.length }}</el-tag>
          <el-tag>
            TG账号上限:
            {{ accountLimit.effective_limit === 0 ? '∞' : `${accountLimit.account_count}/${accountLimit.effective_limit}` }}
          </el-tag>
          <el-tag type="success">在线: {{ onlineAccounts.length }}</el-tag>
          <el-tag type="warning">限制中: {{ floodingAccounts.length }}</el-tag>
          <el-tag type="danger">封禁: {{ bannedAccounts.length }}</el-tag>
        </div>
      </div>
    </div>

    <!-- 账号列表 -->
    <div class="main">
      <div class="container">
        <el-empty v-if="!loading && accounts.length === 0" description="暂无账号">
          <el-button type="primary" @click="goToLogin">添加第一个账号</el-button>
        </el-empty>

        <div v-else class="account-grid">
          <div
            v-for="account in accounts"
            :key="account.account_id"
            class="account-card"
            v-loading="isAccountSyncing(account.account_id)"
            element-loading-text="同步中..."
            :class="{
              'account-offline': account.health_status !== 'online',
              'account-flooding': account.is_flooding,
              'account-banned': account.is_banned,
              'account-inactive': !account.is_active,
              'account-syncing': isAccountSyncing(account.account_id)
            }"
          >
            <!-- 账号头部 -->
            <div class="account-header">
              <div class="account-avatar">
                {{ account.username ? account.username.charAt(0).toUpperCase() : '?' }}
              </div>
              <div class="account-info">
                <h3>{{ account.username || account.phone || 'Unknown' }}</h3>
                <p>{{ account.first_name || '' }}</p>
              </div>
              <div class="account-status">
                <el-tag
                  :type="getStatusType(account)"
                  size="small"
                >
                  {{ getStatusText(account) }}
                </el-tag>
              </div>
            </div>

            <!-- 账号详情 -->
            <div class="account-details">
              <div class="detail-row">
                <span class="label">账号 ID:</span>
                <span class="value">{{ account.account_id.slice(0, 8) }}...</span>
              </div>
              <div class="detail-row">
                <span class="label">消息发送:</span>
                <span class="value">{{ account.messages_sent }} 条</span>
              </div>
              <div class="detail-row">
                <span class="label">绑定码:</span>
                <span class="value mono">{{ account.bind_code || '未生成' }}</span>
              </div>
              <div v-if="account.bind_code_expires_at" class="detail-row">
                <span class="label">绑定码到期:</span>
                <span class="value">{{ formatDateTime(account.bind_code_expires_at) }}</span>
              </div>
              <div v-if="account.last_used_at" class="detail-row">
                <span class="label">最后使用:</span>
                <span class="value">{{ formatDate(account.last_used_at) }}</span>
              </div>
              <div v-if="account.is_flooding && account.flood_until" class="detail-row warning">
                <span class="label">解除时间:</span>
                <span class="value">{{ formatDateTime(account.flood_until) }}</span>
              </div>
            </div>

            <!-- 操作按钮 -->
            <div class="account-actions">
              <template v-if="canOperateAccount(account)">
                <el-button size="small" type="primary" plain @click="viewAccountGroups(account)">
                  查看群组
                </el-button>
                <el-button
                  size="small"
                  type="success"
                  plain
                  :disabled="isAccountSyncing(account.account_id)"
                  @click="createTaskFromAccount(account)"
                >
                  任务管理
                </el-button>
                <el-button
                  size="small"
                  type="info"
                  :loading="bindCodeLoading[account.account_id] === true"
                  :disabled="isAccountSyncing(account.account_id)"
                  @click="refreshBindCode(account)"
                >
                  {{ account.bind_code ? '刷新绑定码' : '获取绑定码' }}
                </el-button>
                <el-button
                  size="small"
                  :disabled="!account.bind_code || isAccountSyncing(account.account_id)"
                  @click="copyBindCommand(account)"
                >
                  复制 /bind
                </el-button>
                <el-button
                  size="small"
                  :loading="isAccountSyncing(account.account_id)"
                  :disabled="isAccountSyncing(account.account_id)"
                  @click="syncAccount(account.account_id)"
                >
                  <el-icon><Refresh /></el-icon>
                  同步资源
                </el-button>
              </template>
              <el-button
                v-else-if="needRelogin(account)"
                size="small"
                type="primary"
                @click="reloginAccount(account)"
              >
                重新登录
              </el-button>
              <el-button
                v-if="account.is_active"
                size="small"
                type="warning"
                :disabled="isAccountSyncing(account.account_id)"
                @click="confirmDisable(account)"
              >
                <el-icon><Close /></el-icon>
                禁用
              </el-button>
              <el-button
                v-else
                size="small"
                type="success"
                :disabled="isAccountSyncing(account.account_id)"
                @click="enableAccount(account.account_id)"
              >
                <el-icon><Check /></el-icon>
                启用
              </el-button>
              <el-button
                size="small"
                type="danger"
                :disabled="isAccountSyncing(account.account_id)"
                @click="confirmDelete(account)"
              >
                <el-icon><Delete /></el-icon>
                删除
              </el-button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Check, Close, Delete } from '@element-plus/icons-vue'
import { useAccountStore } from '@/stores/account'
import { useUserStore } from '@/stores/user'
import * as authApi from '@/api/auth'
import { refreshAccountBindCode, type Account } from '@/api/account'
import { getSubscription } from '@/api/me'

const router = useRouter()
const route = useRoute()
const accountStore = useAccountStore()
const userStore = useUserStore()

// 获取账号列表
const accounts = computed(() => accountStore.accounts)
const loading = computed(() => accountStore.loading)
const onlineAccounts = computed(() => accountStore.onlineAccounts)
const floodingAccounts = computed(() => accountStore.floodingAccounts)
const bannedAccounts = computed(() => accountStore.bannedAccounts)
const bindCodeLoading = reactive<Record<string, boolean>>({})
const syncLoading = reactive<Record<string, boolean>>({})
const accountLimit = reactive({
  account_count: 0,
  effective_limit: 0,
  remaining_slots: null as number | null,
  is_over_limit: false,
})

const isAccountSyncing = (accountId: string) => syncLoading[accountId] === true
const canOperateAccount = (account: Account) => account.is_active && account.health_status === 'online'
const needRelogin = (account: Account) =>
  account.health_status !== 'online' || account.reauth_required === true

// 跳转到 TG 账号绑定页
const goToLogin = async () => {
  try {
    const res = await getSubscription()
    if (!res.data.is_active) {
      ElMessage.warning('未开通套餐，请先购买或激活卡密')
      router.push('/purchase')
      return
    }
    accountLimit.account_count = res.data.tg_account_limit?.account_count ?? 0
    accountLimit.effective_limit = res.data.tg_account_limit?.effective_limit ?? 0
    accountLimit.remaining_slots = res.data.tg_account_limit?.remaining_slots ?? null
    accountLimit.is_over_limit = res.data.tg_account_limit?.is_over_limit ?? false
    if (res.data.tg_account_limit?.is_at_limit || res.data.tg_account_limit?.is_over_limit) {
      const limitText = accountLimit.effective_limit === 0 ? '∞' : String(accountLimit.effective_limit)
      ElMessage.warning(
        `当前账号最多可登录 ${limitText} 个 Telegram 账号，已达上限。现有账号可继续使用，但暂时不能新增账号。请删除闲置账号、升级套餐或联系管理员调整。`,
      )
      return
    }
    router.push('/bind-tg')
  } catch (_err) {
    // 失败时由全局拦截器提示，这里不重复弹窗
  }
}

const goToMy = () => {
  router.push('/me')
}

const handleLogout = async () => {
  try {
    await authApi.logout()
  } catch (_err) {
    // 后端登出失败不阻塞本地态清理
  } finally {
    userStore.logout()
    router.replace('/login')
  }
}

// 刷新账号列表
const refreshAccounts = async () => {
  if (userStore.userId) {
    await accountStore.fetchAccounts(userStore.userId, true)
    try {
      const res = await getSubscription()
      accountLimit.account_count = res.data.tg_account_limit?.account_count ?? 0
      accountLimit.effective_limit = res.data.tg_account_limit?.effective_limit ?? 0
      accountLimit.remaining_slots = res.data.tg_account_limit?.remaining_slots ?? null
      accountLimit.is_over_limit = res.data.tg_account_limit?.is_over_limit ?? false
    } catch (_err) {
      // ignore
    }
  }
}

const reloginAccount = (account: Account) => {
  ElMessage.warning(`账号 ${account.username || account.phone || account.account_id} 当前离线，请重新扫码登录`)
  router.push({
    path: '/bind-tg',
    query: {
      relogin_account_id: account.account_id
    }
  })
}

const viewAccountGroups = (account: Account) => {
  if (!canOperateAccount(account)) {
    reloginAccount(account)
    return
  }
  router.push({
    path: '/resources',
    query: {
      account_id: account.account_id
    }
  })
}

const createTaskFromAccount = (account: Account) => {
  if (!canOperateAccount(account)) {
    reloginAccount(account)
    return
  }
  router.push({
    path: '/tasks',
    query: {
      account_id: account.account_id
    }
  })
}

const refreshBindCode = async (account: Account) => {
  bindCodeLoading[account.account_id] = true
  try {
    const res = await refreshAccountBindCode(account.account_id, true)
    account.bind_code = res.data.bind_code
    account.bind_code_expires_at = res.data.expires_at
    ElMessage.success(`绑定码已更新: ${res.data.bind_code}`)
  } catch (err: any) {
    ElMessage.error(err.message || '获取绑定码失败')
  } finally {
    bindCodeLoading[account.account_id] = false
  }
}

const copyBindCommand = async (account: Account) => {
  if (!account.bind_code) {
    ElMessage.warning('请先获取绑定码')
    return
  }

  const command = `/bind ${account.bind_code}`
  try {
    await navigator.clipboard.writeText(command)
    ElMessage.success('已复制绑定命令')
  } catch (_err) {
    ElMessage.error('复制失败，请手动复制')
  }
}

// 同步账号资源
const syncAccount = async (accountId: string) => {
  if (syncLoading[accountId]) return
  syncLoading[accountId] = true
  try {
    await accountStore.syncAccount(accountId, true)
    ElMessage.success('资源同步完成')
  } catch (err: any) {
    ElMessage.error(err.message || '同步失败')
  } finally {
    syncLoading[accountId] = false
  }
}

// 禁用账号
const confirmDisable = async (account: Account) => {
  try {
    await ElMessageBox.confirm(
      `确定要禁用账号 ${account.username || account.phone} 吗？`,
      '确认操作',
      {
        type: 'warning'
      }
    )
    await accountStore.disableAccount(account.account_id)
    ElMessage.success('账号已禁用')
  } catch (err: any) {
    if (err !== 'cancel') {
      ElMessage.error(err.message || '操作失败')
    }
  }
}

// 启用账号
const enableAccount = async (accountId: string) => {
  try {
    await accountStore.enableAccount(accountId)
    ElMessage.success('账号已启用')
  } catch (err: any) {
    ElMessage.error(err.message || '操作失败')
  }
}

// 删除账号
const confirmDelete = async (account: Account) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除账号 ${account.username || account.phone} 吗？此操作不可恢复！`,
      '确认删除',
      {
        type: 'error',
        confirmButtonText: '确定删除',
        cancelButtonText: '取消'
      }
    )
    await accountStore.deleteAccount(account.account_id)
    ElMessage.success('账号已删除')
  } catch (err: any) {
    if (err !== 'cancel') {
      ElMessage.error(err.message || '删除失败')
    }
  }
}

// 获取状态类型
const getStatusType = (account: Account) => {
  if (account.is_banned) return 'danger'
  if (account.is_flooding) return 'warning'
  if (!account.is_active) return 'info'
  if (account.health_status === 'online') return 'success'
  return 'danger'
}

// 获取状态文本
const getStatusText = (account: Account) => {
  if (account.is_banned) return '已封禁'
  if (account.is_flooding) return '限制中'
  if (!account.is_active) return '已禁用'
  if (account.health_status === 'online') return '在线'
  return '离线'
}

// 格式化日期
const formatDate = (dateStr: string) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleDateString()
}

// 格式化日期时间
const formatDateTime = (dateStr: string) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString()
}

// 组件挂载
onMounted(() => {
  // 恢复用户状态
  userStore.restoreUser()
  if (userStore.userId) {
    accountStore.fetchAccounts(userStore.userId, route.query.refresh === '1')
  } else {
    ElMessage.warning('请先登录')
    router.push('/login')
  }
})

watch(
  () => route.query.refresh,
  async (refreshFlag) => {
    if (refreshFlag !== '1' || !userStore.userId) return
    await accountStore.fetchAccounts(userStore.userId, true)
    router.replace('/accounts')
  }
)
</script>

<style scoped>
.accounts-page {
  min-height: 100vh;
  background: #f5f7fa;
}

.header {
  background: white;
  padding: 1.5rem 0;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
}

.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 1.5rem;
}

.brand-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-logo {
  width: 72px;
  height: auto;
  display: block;
}

.back-link {
  color: #667eea;
  text-decoration: none;
  display: inline-block;
  margin-bottom: 1rem;
}

.back-link:hover {
  text-decoration: underline;
}

.header h1 {
  margin: 0;
  font-size: 1.5rem;
  color: #2c3e50;
}

.toolbar {
  background: white;
  padding: 1rem 0;
  margin-top: 1rem;
  border-bottom: 1px solid #eee;
}

.toolbar .container {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.stats {
  margin-left: auto;
  display: flex;
  gap: 0.5rem;
}

.main {
  padding: 2rem 0;
}

.account-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
  gap: 1.5rem;
}

.account-card {
  background: white;
  border-radius: 12px;
  padding: 1.5rem;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  transition: all 0.2s;
}

.account-syncing {
  pointer-events: none;
}

.account-card:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
}

.account-inactive {
  opacity: 0.6;
}

.account-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1rem;
}

.account-avatar {
  width: 50px;
  height: 50px;
  border-radius: 50%;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.2rem;
  font-weight: 600;
}

.account-info {
  flex: 1;
}

.account-info h3 {
  margin: 0;
  font-size: 1.1rem;
  color: #2c3e50;
}

.account-info p {
  margin: 0;
  color: #6c757d;
  font-size: 0.9rem;
}

.account-details {
  margin-bottom: 1rem;
}

.detail-row {
  display: flex;
  justify-content: space-between;
  padding: 0.5rem 0;
  border-bottom: 1px solid #f5f5f5;
}

.detail-row:last-child {
  border-bottom: none;
}

.detail-row.warning {
  color: #e6a23c;
}

.detail-row .label {
  color: #6c757d;
  font-size: 0.9rem;
}

.detail-row .value {
  color: #2c3e50;
  font-size: 0.9rem;
  font-weight: 500;
}

.detail-row .value.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  letter-spacing: 0.5px;
}

.account-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.account-actions .el-button {
  flex: 1;
  min-width: 80px;
}

@media (max-width: 900px) {
  .container {
    padding: 0 0.9rem;
  }

  .toolbar .container {
    flex-wrap: wrap;
    gap: 0.65rem;
  }

  .stats {
    width: 100%;
    margin-left: 0;
    flex-wrap: wrap;
  }

  .main {
    padding: 1rem 0;
  }

  .account-grid {
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 0.9rem;
  }
}

@media (max-width: 640px) {
  .header {
    padding: 1rem 0;
  }

  .header h1 {
    font-size: 1.25rem;
  }

  .toolbar .container :deep(.el-button) {
    width: 100%;
  }

  .account-grid {
    grid-template-columns: 1fr;
  }

  .account-card {
    padding: 1rem;
    border-radius: 10px;
  }

  .account-header {
    align-items: flex-start;
  }

  .account-avatar {
    width: 42px;
    height: 42px;
    font-size: 1rem;
  }

  .detail-row {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.2rem;
  }

  .account-actions .el-button {
    flex: 1 1 calc(50% - 0.25rem);
    min-width: 0;
  }
}

@media (max-width: 420px) {
  .account-actions .el-button {
    flex-basis: 100%;
  }
}
</style>
