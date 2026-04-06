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
          绑定账号
        </el-button>
        <el-button @click="refreshAccounts" :loading="loading">
          <el-icon><Refresh /></el-icon>
          刷新状态
        </el-button>
        <el-button @click="goToMy">
          我的
        </el-button>
        <el-button type="primary" plain @click="goBindAccount">
          系统账号绑定到 TG Bot
        </el-button>
        <el-button type="danger" plain @click="handleLogout">
          退出系统
        </el-button>
        <div class="stats">
          <el-tag>总计: {{ accounts.length }}</el-tag>
          <el-tag>
            已绑定账号:
            {{ `${licenseOverview.account_count}/1` }}
          </el-tag>
          <el-tag type="success">已授权: {{ licensedAccounts.length }}</el-tag>
          <el-tag type="warning">未授权: {{ unlicensedAccounts.length }}</el-tag>
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
          <el-button type="primary" @click="goToLogin">绑定第一个账号</el-button>
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
                <span class="label">自动发送权限:</span>
                <span class="value">
                  {{
                    account.authorization_status === 'licensed'
                      ? '已授权'
                      : account.authorization_status === 'expired'
                        ? '已到期'
                        : '未授权'
                  }}
                </span>
              </div>
              <div v-if="account.authorization_end_at" class="detail-row">
                <span class="label">授权到期:</span>
                <span class="value">{{ formatDateTime(account.authorization_end_at) }}</span>
              </div>
              <div v-if="account.authorization_card_count" class="detail-row">
                <span class="label">已用卡密数:</span>
                <span class="value">{{ account.authorization_card_count }}</span>
              </div>
              <div v-if="account.authorization_status !== 'unlicensed'" class="detail-row">
                <span class="label">当前授权:</span>
                <span class="value">{{ account.has_active_authorization ? '已生效' : '待续费' }}</span>
              </div>
              <div v-if="account.authorization_grant_source_label" class="detail-row">
                <span class="label">授权来源:</span>
                <span class="value">{{ account.authorization_grant_source_label }}</span>
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
                  :disabled="!account.can_create_tasks || isAccountSyncing(account.account_id)"
                  @click="createTaskFromAccount(account)"
                >
                  任务管理
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
                <el-button
                  v-if="account.can_renew_authorization"
                  size="small"
                  type="warning"
                  plain
                  :disabled="isAccountSyncing(account.account_id)"
                  @click="openRenewDialog(account)"
                >
                  续费卡密
                </el-button>
              </template>
              <el-button
                v-else-if="needRelogin(account)"
                size="small"
                type="primary"
                @click="reloginAccount(account)"
              >
                重新绑定
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
                解绑
              </el-button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <el-dialog v-model="renewDialog.visible" title="续费当前授权" width="420px">
      <div v-if="renewDialog.account">
        <p class="slot-dialog-hint">
          为当前账号对应的唯一授权追加新的卡密时长。
        </p>
        <div class="renew-target">
          <strong>{{ renewDialog.account.username || renewDialog.account.phone || renewDialog.account.account_id }}</strong>
          <span>到期：{{ formatDateTime(renewDialog.account.authorization_end_at || '') }}</span>
        </div>
        <el-input
          v-model.trim="renewDialog.cardCode"
          placeholder="请输入新的续费卡密"
          @keyup.enter="confirmRenewSlot"
        />
      </div>
      <template #footer>
        <el-button @click="renewDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="renewDialog.loading" :disabled="!renewDialog.cardCode" @click="confirmRenewSlot">
          确认续费
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { reactive, computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Check, Close, Delete } from '@element-plus/icons-vue'
import { useAccountStore } from '@/stores/account'
import { useUserStore } from '@/stores/user'
import * as authApi from '@/api/auth'
import { renewAccountAuthorization, syncAllAccountResources, type Account } from '@/api/account'
import { createBotBindLink } from '@/api/login'
import { getLicenseStatus } from '@/api/me'

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
const licensedAccounts = computed(() => accounts.value.filter((item) => item.can_create_tasks))
const unlicensedAccounts = computed(() => accounts.value.filter((item) => !item.can_create_tasks))
const syncLoading = reactive<Record<string, boolean>>({})
const licenseOverview = reactive({
  account_count: 0,
  max_account_count: 1,
  is_over_limit: false,
  is_at_limit: false,
  can_bind_account: true,
})
const botInfo = reactive({
  username: '',
})
const renewDialog = reactive<{
  visible: boolean
  account: Account | null
  cardCode: string
  loading: boolean
}>({
  visible: false,
  account: null,
  cardCode: '',
  loading: false,
})

const isAccountSyncing = (accountId: string) => syncLoading[accountId] === true
const canOperateAccount = (account: Account) => account.is_active && account.health_status === 'online'
const needRelogin = (account: Account) =>
  account.health_status !== 'online' || account.reauth_required === true

// 跳转到 TG 账号绑定页
const goToLogin = async () => {
  try {
    const res = await getLicenseStatus()
    licenseOverview.account_count = res.data.authorization_overview?.account_count ?? 0
    licenseOverview.max_account_count = res.data.authorization_overview?.max_account_count ?? 1
    licenseOverview.is_over_limit = res.data.authorization_overview?.is_over_limit ?? false
    licenseOverview.is_at_limit = res.data.authorization_overview?.is_at_limit ?? false
    licenseOverview.can_bind_account = res.data.authorization_overview?.can_bind_account ?? true
    botInfo.username = res.data.bot?.username || ''
    if (!licenseOverview.can_bind_account) {
      ElMessage.warning('当前系统账号仅支持绑定 1 个 TG 账号。如需更换，请先解绑当前账号后再绑定新的 TG 账号。')
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
      const res = await getLicenseStatus()
      licenseOverview.account_count = res.data.authorization_overview?.account_count ?? 0
      licenseOverview.max_account_count = res.data.authorization_overview?.max_account_count ?? 1
      licenseOverview.is_over_limit = res.data.authorization_overview?.is_over_limit ?? false
      licenseOverview.is_at_limit = res.data.authorization_overview?.is_at_limit ?? false
      licenseOverview.can_bind_account = res.data.authorization_overview?.can_bind_account ?? true
      botInfo.username = res.data.bot?.username || ''
    } catch (_err) {
      // ignore
    }
  }
}

const reloginAccount = (account: Account) => {
  ElMessage.warning(`账号 ${account.username || account.phone || account.account_id} 当前离线，请重新绑定`)
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
  if (!account.can_create_tasks) {
    ElMessage.warning('当前 TG 账号尚未获得自动发送授权，请先在“我的”页面激活卡密')
    router.push('/me')
    return
  }
  router.push({
    path: '/tasks',
    query: {
      account_id: account.account_id
    }
  })
}

const goBindAccount = async () => {
  try {
    const res = await createBotBindLink()
    const link = res.data.bot_bind_url
    if (!link) {
      ElMessage.warning('当前未配置 TG Bot 入口，请稍后重试')
      return
    }
    window.location.href = link
  } catch (err: any) {
    ElMessage.error(err.message || '生成 Bot 绑定入口失败')
  }
}

const syncAllAccountsOnEntry = async () => {
  try {
    const res = await syncAllAccountResources(false)
    if (!(res as any).already_running) {
      ElMessage.success(res.message || '已开始同步当前系统账号下的全部资源')
    }
  } catch (err: any) {
    ElMessage.warning(err.message || '已进入账号页，但后台资源同步启动失败')
  }
}

const openRenewDialog = (account: Account) => {
  if (!account.can_renew_authorization) {
    ElMessage.warning('当前账号没有可续费的授权，请先绑定 TG 账号触发 7 天试用或输入卡密开通当前授权')
    return
  }
  renewDialog.account = account
  renewDialog.cardCode = ''
  renewDialog.visible = true
}

const confirmRenewSlot = async () => {
  if (!renewDialog.account || !renewDialog.cardCode) return
  renewDialog.loading = true
  try {
    await renewAccountAuthorization(renewDialog.account.account_id, renewDialog.cardCode)
    ElMessage.success('授权续费成功')
    renewDialog.visible = false
    renewDialog.cardCode = ''
    await refreshAccounts()
  } catch (err: any) {
    ElMessage.error(err.message || '授权续费失败')
  } finally {
    renewDialog.loading = false
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
      `确定要解绑账号 ${account.username || account.phone} 吗？此操作不可恢复！\n\n解绑后，当前唯一授权会保留剩余时间，后续可重新绑定到新的 TG 账号。`,
      '确认解绑',
      {
        type: 'error',
        confirmButtonText: '确定解绑',
        cancelButtonText: '取消'
      }
    )
    await accountStore.deleteAccount(account.account_id)
    ElMessage.success('账号已解绑')
  } catch (err: any) {
    if (err !== 'cancel') {
      ElMessage.error(err.message || '解绑失败')
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
    syncAllAccountsOnEntry()
    refreshAccounts()
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
