<template>
  <div class="resources-page">
    <!-- 头部 -->
    <header class="header">
      <div class="container">
        <router-link to="/accounts" class="back-link">← 返回账号列表</router-link>
        <div class="brand-header">
          <img class="brand-logo" src="/quanqiu.png" alt="全球通" />
          <h1>全球通资源列表</h1>
        </div>
      </div>
    </header>

    <!-- 筛选器 -->
    <div class="toolbar">
      <div class="container">
        <el-select
          v-model="selectedAccountId"
          placeholder="选择账号"
          style="width: 200px"
          @change="loadResources"
        >
          <el-option
            v-for="account in accounts"
            :key="account.account_id"
            :label="account.username || account.phone || 'Unknown'"
            :value="account.account_id"
          />
        </el-select>

        <el-select
          v-model="selectedPeerType"
          placeholder="资源类型"
          style="width: 150px"
          clearable
          @change="loadResources"
        >
          <el-option label="用户" value="user" />
          <el-option label="群组" value="chat" />
          <el-option label="超级群组" value="supergroup" />
          <el-option label="频道" value="channel" />
        </el-select>

        <el-input
          v-model="searchQuery"
          placeholder="搜索资源..."
          style="width: 250px"
          clearable
          @change="loadResources"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>

        <el-button
          type="primary"
          :disabled="!selectedAccountId"
          @click="syncResources"
        >
          <el-icon><Refresh /></el-icon>
          同步资源
        </el-button>
      </div>
    </div>

    <!-- 资源列表 -->
    <div class="main">
      <div class="container">
        <el-empty v-if="!loading && resources.length === 0" description="暂无资源">
          <el-button
            v-if="accounts.length > 0 && accounts[0]"
            type="primary"
            @click="selectedAccountId = accounts[0].account_id; loadResources()"
          >
            选择账号并加载资源
          </el-button>
          <el-button v-else type="primary" @click="$router.push('/accounts')">
            先添加账号
          </el-button>
        </el-empty>

        <div v-else class="table-wrap">
          <el-table :data="resources" stripe v-loading="loading">
            <el-table-column prop="title" label="名称" min-width="200">
              <template #default="{ row }">
                <div class="resource-name">
                  <span>{{ row.title }}</span>
                  <el-tag v-if="row.is_verified" type="success" size="small">✓</el-tag>
                </div>
              </template>
            </el-table-column>

            <el-table-column prop="peer_type" label="类型" width="120">
              <template #default="{ row }">
                <el-tag :type="getPeerTypeColor(row.peer_type)" size="small">
                  {{ getPeerTypeName(row.peer_type) }}
                </el-tag>
              </template>
            </el-table-column>

            <el-table-column prop="username" label="用户名" width="150">
              <template #default="{ row }">
                <span v-if="row.username">@{{ row.username }}</span>
                <span v-else class="text-muted">-</span>
              </template>
            </el-table-column>

            <el-table-column prop="participants_count" label="成员数" width="100" align="right">
              <template #default="{ row }">
                <span v-if="row.participants_count">
                  {{ formatNumber(row.participants_count) }}
                </span>
                <span v-else class="text-muted">-</span>
              </template>
            </el-table-column>

            <el-table-column prop="last_sync_at" label="同步时间" width="180">
              <template #default="{ row }">
                <span v-if="row.last_sync_at">{{ formatDateTime(row.last_sync_at) }}</span>
                <span v-else class="text-muted">-</span>
              </template>
            </el-table-column>

            <el-table-column label="操作" width="140" fixed="right">
              <template #default="{ row }">
                <el-button
                  size="small"
                  type="primary"
                  link
                  @click="viewResource(row)"
                >
                  查看
                </el-button>
                <el-button
                  size="small"
                  type="success"
                  link
                  @click="goCreateTask(row)"
                >
                  建任务
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <!-- 分页 -->
        <div v-if="resources.length > 0" class="pagination">
          <el-pagination
            v-model:current-page="currentPage"
            :page-size="pageSize"
            :total="total"
            layout="total, prev, pager, next"
            @current-change="loadResources"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Search, Refresh } from '@element-plus/icons-vue'
import { useAccountStore } from '@/stores/account'
import { useUserStore } from '@/stores/user'
import type { Resource } from '@/api/resource'

const accountStore = useAccountStore()
const userStore = useUserStore()
const route = useRoute()
const router = useRouter()

// 状态
const accounts = computed(() => accountStore.accounts)
const selectedAccountId = ref('')
const selectedPeerType = ref('')
const searchQuery = ref('')
const resources = ref<Resource[]>([])
const loading = ref(false)
const currentPage = ref(1)
const pageSize = ref(50)
const total = ref(0)

// 加载资源列表
const loadResources = async () => {
  if (!selectedAccountId.value) {
    resources.value = []
    return
  }

  loading.value = true
  try {
    const params: any = {
      is_active: true
    }

    if (selectedPeerType.value) {
      params.peer_type = selectedPeerType.value
    }

    if (searchQuery.value) {
      params.search = searchQuery.value
    }

    resources.value = await accountStore.getAccountResources(selectedAccountId.value, params)
    total.value = resources.value.length
  } catch (err: any) {
    ElMessage.error(err.message || '加载资源失败')
  } finally {
    loading.value = false
  }
}

// 同步资源
const syncResources = async () => {
  if (!selectedAccountId.value) return

  try {
    await accountStore.syncAccount(selectedAccountId.value, true)
    ElMessage.success('资源同步完成')
    await loadResources()
  } catch (err: any) {
    ElMessage.error(err.message || '同步失败')
  }
}

// 查看资源详情
const viewResource = (resource: Resource) => {
  ElMessage.info(`资源 ID: ${resource.resource_id}, Peer ID: ${resource.peer_id}`)
}

const goCreateTask = (resource: Resource) => {
  router.push({
    path: '/tasks',
    query: {
      account_id: selectedAccountId.value,
      peer_id: String(resource.peer_id),
      peer_type: resource.peer_type
    }
  })
}

// 获取 Peer 类型颜色（返回 Element Plus Tag 类型）
const getPeerTypeColor = (type: string): 'primary' | 'success' | 'warning' | 'info' | 'danger' | undefined => {
  const colors: Record<string, 'primary' | 'success' | 'warning' | 'info' | 'danger'> = {
    user: 'success',
    chat: 'info',
    supergroup: 'warning',
    channel: 'danger'
  }
  return colors[type] || undefined
}

// 获取 Peer 类型名称
const getPeerTypeName = (type: string) => {
  const names: Record<string, string> = {
    user: '用户',
    chat: '群组',
    supergroup: '超级群组',
    channel: '频道'
  }
  return names[type] || type
}

// 格式化数字
const formatNumber = (num: number) => {
  if (num >= 1000000) {
    return (num / 1000000).toFixed(1) + 'M'
  } else if (num >= 1000) {
    return (num / 1000).toFixed(1) + 'K'
  }
  return String(num)
}

// 格式化日期时间
const formatDateTime = (dateStr: string) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString()
}

// 组件挂载
onMounted(async () => {
  userStore.restoreUser()
  if (userStore.userId) {
    await accountStore.fetchAccounts(userStore.userId)
    const accountIdFromQuery = typeof route.query.account_id === 'string' ? route.query.account_id : ''
    const peerTypeFromQuery = typeof route.query.peer_type === 'string' ? route.query.peer_type : ''

    if (accountIdFromQuery && accounts.value.some(a => a.account_id === accountIdFromQuery)) {
      selectedAccountId.value = accountIdFromQuery
    } else if (accounts.value.length > 0) {
      selectedAccountId.value = accounts.value[0]!.account_id
    }

    if (peerTypeFromQuery) {
      selectedPeerType.value = peerTypeFromQuery
    }

    if (selectedAccountId.value) {
      await loadResources()
    }
  } else {
    ElMessage.warning('请先登录')
  }
})
</script>

<style scoped>
.resources-page {
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
  flex-wrap: wrap;
}

.main {
  padding: 2rem 0;
}

.resource-name {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.table-wrap {
  width: 100%;
  overflow-x: auto;
}

.text-muted {
  color: #adb5bd;
}

.pagination {
  margin-top: 1.5rem;
  display: flex;
  justify-content: center;
}

@media (max-width: 900px) {
  .container {
    padding: 0 0.9rem;
  }

  .main {
    padding: 1rem 0;
  }
}

@media (max-width: 640px) {
  .header {
    padding: 1rem 0;
  }

  .header h1 {
    font-size: 1.25rem;
  }

  .toolbar .container {
    gap: 0.6rem;
  }

  .toolbar :deep(.el-select),
  .toolbar :deep(.el-input),
  .toolbar :deep(.el-button) {
    width: 100% !important;
  }

  .table-wrap {
    margin: 0 -0.15rem;
    padding: 0 0.15rem;
  }

  .pagination {
    justify-content: flex-start;
    overflow-x: auto;
  }
}
</style>
