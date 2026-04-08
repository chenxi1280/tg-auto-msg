<template>
  <div class="page-stack">
    <el-alert v-if="lastActionMessage" :title="lastActionMessage" type="success" :closable="true" @close="lastActionMessage = ''" />

    <el-card v-if="canWrite" shadow="hover">
      <template #header>
        <div class="card-header">
          <span>新增系统代理</span>
          <el-button @click="refreshList">刷新</el-button>
        </div>
      </template>
      <el-form class="toolbar-form" inline>
        <el-form-item label="类型">
          <el-select v-model="proxyForm.proxy_type" style="width: 140px">
            <el-option label="SOCKS5" value="socks5" />
            <el-option label="HTTP" value="http" />
          </el-select>
        </el-form-item>
        <el-form-item label="主机">
          <el-input v-model.trim="proxyForm.host" style="width: 180px" />
        </el-form-item>
        <el-form-item label="端口">
          <el-input-number v-model="proxyForm.port" :min="1" :max="65535" />
        </el-form-item>
        <el-form-item label="账号">
          <el-input v-model.trim="proxyForm.username" style="width: 140px" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="proxyForm.password" show-password style="width: 160px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="creating" @click="createProxy">新增代理</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>系统代理池</span>
          <div class="header-actions">
            <el-input v-model.trim="filters.search" clearable placeholder="搜索代理/账号" style="width: 220px" />
            <el-select v-model="filters.is_healthy" style="width: 140px">
              <el-option label="全部健康" value="all" />
              <el-option label="健康" value="true" />
              <el-option label="异常" value="false" />
            </el-select>
            <el-select v-model="filters.is_assigned" style="width: 140px">
              <el-option label="全部分配" value="all" />
              <el-option label="已分配" value="true" />
              <el-option label="未分配" value="false" />
            </el-select>
            <el-button @click="loadData(true)">查询</el-button>
          </div>
        </div>
      </template>
      <div class="toolbar-bar">
        <div class="header-actions">
          <el-input
            v-if="canAssignTargets"
            v-model.trim="accountSearch"
            clearable
            placeholder="搜索账号选项"
            style="width: 220px"
            @change="loadAccountOptions"
          />
          <span class="card-tip">共 {{ total }} 条代理</span>
        </div>
        <el-button v-if="canCheck" type="warning" plain :disabled="!selectedProxyIds.length" :loading="batchChecking" @click="batchCheck">
          批量检查
        </el-button>
      </div>
      <el-table :data="proxies" stripe @selection-change="handleSelectionChange">
        <el-table-column type="selection" width="48" />
        <el-table-column label="代理" min-width="220">
          <template #default="{ row }">{{ row.proxy_type }}://{{ row.host }}:{{ row.port }}</template>
        </el-table-column>
        <el-table-column label="健康" width="120">
          <template #default="{ row }">
            <el-tag :type="row.is_healthy ? 'success' : 'danger'">{{ row.is_healthy ? '健康' : '异常' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="响应时间" width="120">
          <template #default="{ row }">{{ row.response_time_ms == null ? '-' : `${row.response_time_ms} ms` }}</template>
        </el-table-column>
        <el-table-column label="分配账号" min-width="180">
          <template #default="{ row }">{{ row.assigned_account_id || '-' }}</template>
        </el-table-column>
        <el-table-column label="最近检查" min-width="160">
          <template #default="{ row }">{{ formatDateTime(row.last_check_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="320" fixed="right">
          <template #default="{ row }">
            <el-select
              v-if="canAssignTargets"
              v-model="assignTargets[row.proxy_id]"
              filterable
              clearable
              placeholder="选择账号"
              style="width: 180px"
            >
              <el-option
                v-for="option in accountOptions"
                :key="option.account_id"
                :label="option.label"
                :value="option.account_id"
              />
            </el-select>
            <el-button v-if="canAssignTargets" link type="primary" @click="assignProxy(row.proxy_id)">分配</el-button>
            <el-button v-if="canCheck" link type="success" :loading="checkingId === row.proxy_id" @click="checkProxy(row.proxy_id)">检查</el-button>
            <el-button v-if="canAssign && row.assigned_account_id" link type="warning" @click="unassignProxy(row.proxy_id)">解绑</el-button>
            <el-button v-if="canWrite" link type="danger" @click="deleteProxy(row.proxy_id)">删除</el-button>
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
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { AccountOption, LegacyProxy } from '@/api/admin'
import {
  adminAddSystemProxy,
  adminAssignSystemProxy,
  adminCheckSystemProxy,
  adminDeleteSystemProxy,
  adminListAccountOptions,
  adminListSystemProxies,
  adminUnassignSystemProxy,
} from '@/api/admin'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { formatDateTime } from '@/utils/adminConsole'

const store = useAdminConsoleStore()
const canWrite = computed(() => store.hasPermission('system_proxies.write'))
const canCheck = computed(() => store.hasPermission('system_proxies.check'))
const canAssign = computed(() => store.hasPermission('system_proxies.assign'))
const canReadUsers = computed(() => store.hasPermission('users.read'))
const canAssignTargets = computed(() => canAssign.value && canReadUsers.value)
const proxies = ref<LegacyProxy[]>([])
const accountOptions = ref<AccountOption[]>([])
const accountSearch = ref('')
const creating = ref(false)
const checkingId = ref<number | null>(null)
const batchChecking = ref(false)
const total = ref(0)
const lastActionMessage = ref('')
const selectedProxyIds = ref<number[]>([])
const assignTargets = reactive<Record<number, string>>({})

const pagination = reactive({
  currentPage: 1,
  pageSize: 20,
})

const filters = reactive({
  search: '',
  is_healthy: 'all',
  is_assigned: 'all',
})

const proxyForm = reactive({
  proxy_type: 'socks5',
  host: '',
  port: 1080,
  username: '',
  password: '',
})

const loadAccountOptions = async () => {
  if (!canAssignTargets.value) {
    accountOptions.value = []
    return
  }
  const response = await adminListAccountOptions({ search: accountSearch.value || undefined, limit: 300 })
  accountOptions.value = response.data
}

const loadData = async (resetPage = false) => {
  if (resetPage) pagination.currentPage = 1
  const [proxyResponse] = await Promise.all([
    adminListSystemProxies({
      search: filters.search || undefined,
      is_healthy: filters.is_healthy === 'all' ? undefined : filters.is_healthy === 'true',
      is_assigned: filters.is_assigned === 'all' ? undefined : filters.is_assigned === 'true',
      limit: pagination.pageSize,
      offset: (pagination.currentPage - 1) * pagination.pageSize,
    }),
    loadAccountOptions(),
  ])
  proxies.value = proxyResponse.data.items
  total.value = proxyResponse.data.total
  if (!proxies.value.length && total.value > 0 && pagination.currentPage > 1) {
    pagination.currentPage -= 1
    await loadData()
  }
}

const handlePageChange = async () => {
  await loadData()
}

const refreshList = async () => {
  await loadData()
}

const handleSizeChange = async () => {
  pagination.currentPage = 1
  await loadData()
}

const handleSelectionChange = (rows: LegacyProxy[]) => {
  selectedProxyIds.value = rows.map((row) => row.proxy_id)
}

const createProxy = async () => {
  creating.value = true
  try {
    await adminAddSystemProxy({
      proxy_type: proxyForm.proxy_type,
      host: proxyForm.host,
      port: proxyForm.port,
      username: proxyForm.username || undefined,
      password: proxyForm.password || undefined,
    })
    proxyForm.host = ''
    proxyForm.port = 1080
    proxyForm.username = ''
    proxyForm.password = ''
    await loadData()
    lastActionMessage.value = '代理已新增'
    ElMessage.success(lastActionMessage.value)
  } finally {
    creating.value = false
  }
}

const checkProxy = async (proxyId: number) => {
  checkingId.value = proxyId
  try {
    await adminCheckSystemProxy(proxyId)
    await loadData()
    lastActionMessage.value = `代理 #${proxyId} 检查完成`
    ElMessage.success(lastActionMessage.value)
  } finally {
    checkingId.value = null
  }
}

const assignProxy = async (proxyId: number) => {
  if (!canAssignTargets.value) {
    ElMessage.warning('当前账号无权分配系统代理')
    return
  }
  const accountId = assignTargets[proxyId]
  if (!accountId) {
    ElMessage.warning('请先选择目标账号')
    return
  }
  await adminAssignSystemProxy(proxyId, accountId)
  await loadData()
  lastActionMessage.value = '代理已分配'
  ElMessage.success(lastActionMessage.value)
}

const unassignProxy = async (proxyId: number) => {
  await adminUnassignSystemProxy(proxyId)
  await loadData()
  lastActionMessage.value = '代理已解绑'
  ElMessage.success(lastActionMessage.value)
}

const deleteProxy = async (proxyId: number) => {
  await ElMessageBox.confirm('删除后将不可恢复，确定继续吗？', '删除代理', { type: 'warning' })
  await adminDeleteSystemProxy(proxyId)
  await loadData()
  lastActionMessage.value = '代理已删除'
  ElMessage.success(lastActionMessage.value)
}

const batchCheck = async () => {
  if (!selectedProxyIds.value.length) return
  batchChecking.value = true
  try {
    const results = await Promise.allSettled(selectedProxyIds.value.map((proxyId) => adminCheckSystemProxy(proxyId)))
    const successCount = results.filter((item) => item.status === 'fulfilled').length
    await loadData()
    lastActionMessage.value = `批量检查完成，成功 ${successCount} 条，失败 ${results.length - successCount} 条`
    ElMessage.success(lastActionMessage.value)
  } finally {
    batchChecking.value = false
  }
}

onMounted(async () => {
  await loadData()
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

.toolbar-form {
  gap: 8px 0;
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

.card-tip {
  color: #64748b;
  font-size: 13px;
}
</style>
