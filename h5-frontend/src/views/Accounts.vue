<template>
  <div class="accounts-page">
    <!-- 头部 -->
    <header class="header">
      <div class="container">
        <router-link to="/" class="back-link">← 返回首页</router-link>
        <h1>账号管理</h1>
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
        <div class="stats">
          <el-tag>总计: {{ accounts.length }}</el-tag>
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
            :class="{
              'account-offline': account.health_status !== 'online',
              'account-flooding': account.is_flooding,
              'account-banned': account.is_banned,
              'account-inactive': !account.is_active
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
              <el-button size="small" @click="syncAccount(account.account_id)">
                <el-icon><Refresh /></el-icon>
                同步资源
              </el-button>
              <el-button
                v-if="account.is_active"
                size="small"
                type="warning"
                @click="confirmDisable(account)"
              >
                <el-icon><Close /></el-icon>
                禁用
              </el-button>
              <el-button
                v-else
                size="small"
                type="success"
                @click="enableAccount(account.account_id)"
              >
                <el-icon><Check /></el-icon>
                启用
              </el-button>
              <el-button
                size="small"
                type="danger"
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
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Check, Close, Delete } from '@element-plus/icons-vue'
import { useAccountStore } from '@/stores/account'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const accountStore = useAccountStore()
const userStore = useUserStore()

// 获取账号列表
const accounts = computed(() => accountStore.accounts)
const loading = computed(() => accountStore.loading)
const onlineAccounts = computed(() => accountStore.onlineAccounts)
const floodingAccounts = computed(() => accountStore.floodingAccounts)
const bannedAccounts = computed(() => accountStore.bannedAccounts)

// 跳转到登录页
const goToLogin = () => {
  router.push('/login')
}

// 刷新账号列表
const refreshAccounts = async () => {
  if (userStore.userId) {
    await accountStore.fetchAccounts(userStore.userId)
  }
}

// 同步账号资源
const syncAccount = async (accountId: string) => {
  try {
    await accountStore.syncAccount(accountId)
    ElMessage.success('资源同步已启动，请稍后查看')
  } catch (err: any) {
    ElMessage.error(err.message || '同步失败')
  }
}

// 禁用账号
const confirmDisable = async (account: any) => {
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
const confirmDelete = async (account: any) => {
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
const getStatusType = (account: any) => {
  if (account.is_banned) return 'danger'
  if (account.is_flooding) return 'warning'
  if (!account.is_active) return 'info'
  if (account.health_status === 'online') return 'success'
  return 'danger'
}

// 获取状态文本
const getStatusText = (account: any) => {
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
    accountStore.fetchAccounts(userStore.userId)
  } else {
    ElMessage.warning('请先登录')
    router.push('/login')
  }
})
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

.account-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.account-actions .el-button {
  flex: 1;
  min-width: 80px;
}
</style>
