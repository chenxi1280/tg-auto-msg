<template>
  <div class="page-stack">
    <el-alert v-if="lastActionMessage" :title="lastActionMessage" type="success" :closable="true" @close="lastActionMessage = ''" />

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>开发者应用策略</span>
          <el-button @click="refreshList">刷新</el-button>
        </div>
      </template>
        <el-form inline class="toolbar-form">
        <el-form-item label="分配模式">
          <el-select v-model="settingsForm.assignment_mode" :disabled="!canWrite" style="width: 180px">
            <el-option label="轮询" value="round_robin" />
            <el-option label="权重" value="weight" />
          </el-select>
        </el-form-item>
        <el-form-item label="告警 TG 用户 ID">
          <el-input v-model.trim="settingsForm.alert_tg_user_ids" :disabled="!canWrite" placeholder="多个用逗号分隔" style="width: 260px" />
        </el-form-item>
        <el-form-item>
          <el-button v-if="canWrite" type="primary" :loading="savingSettings" @click="saveSettings">保存策略</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card v-if="canWrite" shadow="hover">
      <template #header>
        <div class="card-header">
          <span>新增开发者应用</span>
          <span class="card-tip">支持凭证轮换、默认应用和健康检查</span>
        </div>
      </template>
      <el-form class="toolbar-form" inline>
        <el-form-item label="应用名">
          <el-input v-model.trim="createForm.app_name" style="width: 180px" />
        </el-form-item>
        <el-form-item label="API ID">
          <el-input-number v-model="createForm.api_id" :min="1" />
        </el-form-item>
        <el-form-item label="API Hash">
          <el-input v-model.trim="createForm.api_hash" style="width: 220px" />
        </el-form-item>
        <el-form-item label="最大账号数">
          <el-input-number v-model="createForm.max_accounts" :min="0" />
        </el-form-item>
        <el-form-item label="权重">
          <el-input-number v-model="createForm.selection_weight" :min="1" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="creating" @click="createApp">新增</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>开发者应用池</span>
          <div class="header-actions">
            <el-input v-model.trim="filters.search" clearable placeholder="搜索应用/API ID/备注" style="width: 220px" />
            <el-select v-model="filters.health_status" style="width: 140px">
              <el-option label="全部健康" value="all" />
              <el-option label="healthy" value="healthy" />
              <el-option label="unhealthy" value="unhealthy" />
              <el-option label="disabled" value="disabled" />
            </el-select>
            <el-select v-model="filters.is_active" style="width: 140px">
              <el-option label="全部状态" value="all" />
              <el-option label="启用" value="true" />
              <el-option label="停用" value="false" />
            </el-select>
            <el-button @click="loadData(true)">查询</el-button>
          </div>
        </div>
      </template>
      <div class="toolbar-bar">
        <span class="card-tip">共 {{ total }} 个应用，当前页 {{ apps.length }} 条</span>
        <el-button v-if="canCheck" type="warning" plain :disabled="!selectedAppIds.length" :loading="batchChecking" @click="batchCheck">
          批量检查
        </el-button>
      </div>
      <el-table :data="apps" stripe @selection-change="handleSelectionChange">
        <el-table-column type="selection" width="48" />
        <el-table-column prop="app_name" label="应用名" min-width="160" />
        <el-table-column prop="api_id" label="API ID" width="100" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="健康" width="120">
          <template #default="{ row }">
            <el-tag :type="healthTagType(row.health_status)">{{ row.health_status || '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="容量" width="140">
          <template #default="{ row }">{{ row.max_accounts || '不限' }}</template>
        </el-table-column>
        <el-table-column label="权重" width="100">
          <template #default="{ row }">{{ row.selection_weight }}</template>
        </el-table-column>
        <el-table-column label="检查时间" min-width="160">
          <template #default="{ row }">{{ formatDateTime(row.last_health_check_at) }}</template>
        </el-table-column>
        <el-table-column label="备注" min-width="180">
          <template #default="{ row }">{{ row.notes || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="280" fixed="right">
          <template #default="{ row }">
            <el-button v-if="canWrite" link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button v-if="canCheck" link type="success" @click="setDefault(row)">设为默认</el-button>
            <el-button v-if="canCheck" link type="warning" :loading="checkingId === row.id" @click="check(row)">检查</el-button>
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

    <el-dialog v-model="editor.visible" title="编辑开发者应用" width="520px">
      <el-form label-position="top">
        <el-form-item label="应用名">
          <el-input v-model.trim="editor.app_name" :disabled="!canWrite" />
        </el-form-item>
        <el-form-item label="API Hash">
          <el-input v-model.trim="editor.api_hash" :disabled="!canWrite" placeholder="留空表示不更新" />
        </el-form-item>
        <el-form-item label="启用状态">
          <el-switch v-model="editor.is_active" :disabled="!canWrite" />
        </el-form-item>
        <el-form-item label="最大账号数">
          <el-input-number v-model="editor.max_accounts" :min="0" :disabled="!canWrite" />
        </el-form-item>
        <el-form-item label="选择权重">
          <el-input-number v-model="editor.selection_weight" :min="1" :disabled="!canWrite" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model.trim="editor.notes" :disabled="!canWrite" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editor.visible = false">取消</el-button>
        <el-button v-if="canWrite" type="primary" :loading="savingEditor" @click="saveEditor">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { DeveloperApp } from '@/api/admin'
import {
  adminCheckDeveloperApp,
  adminCreateDeveloperApp,
  adminListDeveloperApps,
  adminSetDefaultDeveloperApp,
  adminUpdateDeveloperApp,
  adminUpdateDeveloperAppSettings,
} from '@/api/admin'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { formatDateTime } from '@/utils/adminConsole'

const store = useAdminConsoleStore()
const canWrite = computed(() => store.hasPermission('developer_apps.write'))
const canCheck = computed(() => store.hasPermission('developer_apps.check'))
const apps = ref<DeveloperApp[]>([])
const loading = ref(false)
const creating = ref(false)
const savingSettings = ref(false)
const savingEditor = ref(false)
const checkingId = ref<number | null>(null)
const batchChecking = ref(false)
const total = ref(0)
const selectedAppIds = ref<number[]>([])
const lastActionMessage = ref('')

const pagination = reactive({
  currentPage: 1,
  pageSize: 20,
})

const filters = reactive({
  search: '',
  health_status: 'all',
  is_active: 'all',
})

const settingsForm = reactive({
  assignment_mode: 'round_robin',
  alert_tg_user_ids: '',
})

const createForm = reactive({
  app_name: '',
  api_id: 0,
  api_hash: '',
  max_accounts: 0,
  selection_weight: 100,
})

const editor = reactive({
  visible: false,
  id: 0,
  app_name: '',
  api_hash: '',
  is_active: true,
  max_accounts: 0,
  selection_weight: 100,
  notes: '',
})

const healthTagType = (status: string) => {
  if (status === 'healthy') return 'success'
  if (status === 'unhealthy') return 'danger'
  if (status === 'disabled') return 'info'
  return 'warning'
}

const loadData = async (resetPage = false) => {
  if (resetPage) pagination.currentPage = 1
  loading.value = true
  try {
    const response = await adminListDeveloperApps({
      search: filters.search || undefined,
      health_status: filters.health_status === 'all' ? undefined : filters.health_status,
      is_active: filters.is_active === 'all' ? undefined : filters.is_active === 'true',
      limit: pagination.pageSize,
      offset: (pagination.currentPage - 1) * pagination.pageSize,
    })
    apps.value = response.data.items
    total.value = response.data.total
    if (!apps.value.length && total.value > 0 && pagination.currentPage > 1) {
      pagination.currentPage -= 1
      await loadData()
      return
    }
    settingsForm.assignment_mode = response.data.settings.assignment_mode || 'round_robin'
    settingsForm.alert_tg_user_ids = response.data.settings.alert_tg_user_ids_text || ''
  } finally {
    loading.value = false
  }
}

const handleSizeChange = async () => {
  pagination.currentPage = 1
  await loadData()
}

const handlePageChange = async () => {
  await loadData()
}

const refreshList = async () => {
  await loadData()
}

const handleSelectionChange = (rows: DeveloperApp[]) => {
  selectedAppIds.value = rows.map((row) => row.id)
}

const saveSettings = async () => {
  savingSettings.value = true
  try {
    await adminUpdateDeveloperAppSettings({ ...settingsForm })
    ElMessage.success('开发者应用策略已保存')
  } finally {
    savingSettings.value = false
  }
}

const createApp = async () => {
  creating.value = true
  try {
    await adminCreateDeveloperApp({
      app_name: createForm.app_name,
      api_id: createForm.api_id,
      api_hash: createForm.api_hash,
      max_accounts: createForm.max_accounts,
      selection_weight: createForm.selection_weight,
    })
    createForm.app_name = ''
    createForm.api_id = 0
    createForm.api_hash = ''
    createForm.max_accounts = 0
    createForm.selection_weight = 100
    await loadData()
    lastActionMessage.value = '开发者应用已新增'
    ElMessage.success(lastActionMessage.value)
  } finally {
    creating.value = false
  }
}

const openEdit = (row: DeveloperApp) => {
  editor.visible = true
  editor.id = row.id
  editor.app_name = row.app_name
  editor.api_hash = ''
  editor.is_active = row.is_active
  editor.max_accounts = row.max_accounts
  editor.selection_weight = row.selection_weight
  editor.notes = row.notes || ''
}

const saveEditor = async () => {
  savingEditor.value = true
  try {
    await adminUpdateDeveloperApp(editor.id, {
      app_name: editor.app_name,
      api_hash: editor.api_hash || undefined,
      is_active: editor.is_active,
      max_accounts: editor.max_accounts,
      selection_weight: editor.selection_weight,
      notes: editor.notes || undefined,
    })
    editor.visible = false
    await loadData()
    lastActionMessage.value = '开发者应用已更新'
    ElMessage.success(lastActionMessage.value)
  } finally {
    savingEditor.value = false
  }
}

const setDefault = async (row: DeveloperApp) => {
  await adminSetDefaultDeveloperApp(row.id)
  lastActionMessage.value = `已将 ${row.app_name} 设为默认应用`
  ElMessage.success(lastActionMessage.value)
}

const check = async (row: DeveloperApp) => {
  checkingId.value = row.id
  try {
    await adminCheckDeveloperApp(row.id)
    await loadData()
    lastActionMessage.value = `应用 ${row.app_name} 健康检查已完成`
    ElMessage.success(lastActionMessage.value)
  } finally {
    checkingId.value = null
  }
}

const batchCheck = async () => {
  if (!selectedAppIds.value.length) return
  batchChecking.value = true
  try {
    const results = await Promise.allSettled(selectedAppIds.value.map((appId) => adminCheckDeveloperApp(appId)))
    const successCount = results.filter((item) => item.status === 'fulfilled').length
    const failedItems = results
      .map((item, index) => ({ item, appId: selectedAppIds.value[index] }))
      .filter((entry) => entry.item.status === 'rejected')
      .slice(0, 3)
      .map((entry) => `应用#${entry.appId}`)
    await loadData()
    lastActionMessage.value = `批量检查完成，成功 ${successCount} 个，失败 ${results.length - successCount} 个${failedItems.length ? `，失败示例：${failedItems.join('、')}` : ''}`
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

.card-tip {
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
