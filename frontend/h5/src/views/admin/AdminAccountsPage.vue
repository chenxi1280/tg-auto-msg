<template>
  <div class="page-stack">
    <el-alert v-if="lastActionMessage" :title="lastActionMessage" type="success" :closable="true" @close="lastActionMessage = ''" />

    <el-alert
      title="这里管理的是员工后台账号，只用于系统后台运营、RBAC 和配置管理，不参与代理额度、授信白名单、结算模式或卡密责任链。"
      type="info"
      :closable="false"
    />

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>员工后台账号</span>
          <div class="header-actions">
            <el-input v-model.trim="filters.search" clearable placeholder="搜索账号/显示名" style="width: 220px" />
            <el-select v-model="filters.status" clearable placeholder="状态" style="width: 140px">
              <el-option label="启用" value="active" />
              <el-option label="停用" value="disabled" />
            </el-select>
            <el-select v-if="canReadRoles" v-model="filters.role_key" clearable placeholder="角色" style="width: 180px">
              <el-option v-for="role in staffRoles" :key="role.id" :label="role.display_name" :value="role.role_key" />
            </el-select>
            <el-button @click="loadData(true)">查询</el-button>
            <el-button @click="loadData()">刷新</el-button>
            <el-button v-if="store.hasPermission('admin_accounts.write')" type="primary" @click="openCreateDialog">新增员工账号</el-button>
          </div>
        </div>
      </template>

      <el-table v-if="!isCompact" :data="accounts" stripe>
        <el-table-column prop="username" label="账号" min-width="160" />
        <el-table-column prop="display_name" label="显示名" min-width="160" />
        <el-table-column label="账号类型" width="120">
          <template #default="{ row }">{{ accountTypeLabel(row.account_type) }}</template>
        </el-table-column>
        <el-table-column label="身份摘要" min-width="180">
          <template #default="{ row }">{{ accountIdentitySummary(row) }}</template>
        </el-table-column>
        <el-table-column label="绑定角色" min-width="220">
          <template #default="{ row }">
            <el-space wrap>
              <el-tag v-for="role in row.assigned_roles || []" :key="`${row.id}-${role.role_key}`" size="small">
                {{ role.display_name }}
              </el-tag>
            </el-space>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'info'">{{ row.status === 'active' ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近登录" min-width="160">
          <template #default="{ row }">{{ formatDateTime(row.last_login_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="320" fixed="right">
          <template #default="{ row }">
            <el-button v-if="store.hasPermission('admin_accounts.write')" link type="primary" @click="openEditDialog(row)">编辑</el-button>
            <el-button v-if="canManageRoleBindings" link type="success" @click="openRolesDialog(row)">绑定角色</el-button>
            <el-button v-if="store.hasPermission('admin_accounts.reset_password')" link type="warning" @click="openResetDialog(row)">重置密码</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-else class="mobile-card-list">
        <div v-for="row in accounts" :key="row.id" class="mobile-data-card">
          <div class="mobile-data-card__header">
            <div>
              <div class="mobile-data-card__title">{{ row.display_name }}</div>
              <div class="mobile-data-card__subtitle">{{ row.username }} · {{ accountIdentitySummary(row) }}</div>
            </div>
            <el-tag :type="row.status === 'active' ? 'success' : 'info'">{{ row.status === 'active' ? '启用' : '停用' }}</el-tag>
          </div>
          <div class="mobile-data-card__grid">
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">绑定角色</span>
              <span class="mobile-data-card__value">{{ (row.assigned_roles || []).map((item) => item.display_name).join(' / ') || '-' }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">最近登录</span>
              <span class="mobile-data-card__value">{{ formatDateTime(row.last_login_at) }}</span>
            </div>
          </div>
          <div class="mobile-action-bar">
            <el-button v-if="store.hasPermission('admin_accounts.write')" type="primary" plain @click="openEditDialog(row)">编辑</el-button>
            <el-button v-if="canManageRoleBindings" type="success" plain @click="openRolesDialog(row)">绑定角色</el-button>
            <el-button v-if="store.hasPermission('admin_accounts.reset_password')" type="warning" plain @click="openResetDialog(row)">重置密码</el-button>
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

    <ResponsiveFormLayer v-model="createDialog.visible" title="新增员工后台账号" width="640px">
      <el-form label-position="top">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="登录账号">
              <el-input v-model.trim="createDialog.form.username" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="显示名称">
              <el-input v-model.trim="createDialog.form.display_name" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="初始密码">
              <el-input v-model="createDialog.form.password" show-password type="password" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="账号类型">
              <el-input model-value="员工后台账号（不参与代理额度和白名单）" disabled />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="24">
            <el-form-item v-if="canReadRoles" label="绑定角色">
              <el-select v-model="createDialog.form.role_keys" multiple filterable>
                <el-option v-for="role in staffRoles" :key="role.id" :label="role.display_name" :value="role.role_key" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="联系人">
              <el-input v-model.trim="createDialog.form.contact_name" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="联系电话">
              <el-input v-model.trim="createDialog.form.contact_phone" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="createDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建</el-button>
      </template>
    </ResponsiveFormLayer>

    <ResponsiveFormLayer v-model="editDialog.visible" title="编辑员工后台账号" width="520px">
      <el-form label-position="top">
        <el-form-item label="显示名称">
          <el-input v-model.trim="editDialog.form.display_name" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="editDialog.form.status">
            <el-option label="启用" value="active" />
            <el-option label="停用" value="disabled" />
          </el-select>
        </el-form-item>
        <el-form-item label="联系人">
          <el-input v-model.trim="editDialog.form.contact_name" />
        </el-form-item>
        <el-form-item label="联系电话">
          <el-input v-model.trim="editDialog.form.contact_phone" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitEdit">保存</el-button>
      </template>
    </ResponsiveFormLayer>

    <ResponsiveFormLayer v-model="rolesDialog.visible" title="绑定员工后台角色" width="520px">
      <el-form label-position="top">
        <el-form-item label="角色列表">
          <el-select v-model="rolesDialog.role_keys" multiple filterable>
            <el-option v-for="role in staffRoles" :key="role.id" :label="role.display_name" :value="role.role_key" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="rolesDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="savingRoles" @click="submitRoles">保存</el-button>
      </template>
    </ResponsiveFormLayer>

    <ResponsiveFormLayer v-model="resetDialog.visible" title="重置员工后台账号密码" width="420px">
      <el-form label-position="top">
        <el-form-item label="新密码">
          <el-input v-model="resetDialog.new_password" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resetDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="resettingPassword" @click="submitResetPassword">重置</el-button>
      </template>
    </ResponsiveFormLayer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { AdminRole, AgentAccount } from '@/api/admin'
import {
  adminCreateAdminAccount,
  adminListAdminAccounts,
  adminListRbacRoles,
  adminResetAdminAccountPassword,
  adminUpdateAdminAccount,
  adminUpdateAdminAccountRoles,
} from '@/api/admin'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { accountIdentitySummary, accountTypeLabel, formatDateTime } from '@/utils/adminConsole'
import { useResponsive } from '@/composables/useResponsive'
import ResponsiveFormLayer from '@/components/responsive/ResponsiveFormLayer.vue'

const store = useAdminConsoleStore()
const { isCompact } = useResponsive()
const canReadRoles = computed(() => store.hasPermission('rbac.roles.read'))
const canManageRoleBindings = computed(() => store.hasPermission('admin_accounts.write') && canReadRoles.value)
const accounts = ref<AgentAccount[]>([])
const roles = ref<AdminRole[]>([])
const staffRoles = computed(() => roles.value.filter((role) => !['master_agent', 'sub_agent'].includes(role.role_key)))
const total = ref(0)
const lastActionMessage = ref('')
const creating = ref(false)
const saving = ref(false)
const savingRoles = ref(false)
const resettingPassword = ref(false)

const filters = reactive({
  search: '',
  status: '',
  role_key: '',
})

const pagination = reactive({
  currentPage: 1,
  pageSize: 20,
})

const createDialog = reactive({
  visible: false,
  form: {
    username: '',
    password: '',
    display_name: '',
    role_keys: [] as string[],
    contact_name: '',
    contact_phone: '',
  },
})

const editDialog = reactive({
  visible: false,
  accountId: 0,
  form: {
    display_name: '',
    status: 'active',
    contact_name: '',
    contact_phone: '',
  },
})

const rolesDialog = reactive({
  visible: false,
  accountId: 0,
  role_keys: [] as string[],
})

const resetDialog = reactive({
  visible: false,
  accountId: 0,
  new_password: '',
})

const loadRoles = async () => {
  if (!canReadRoles.value) {
    roles.value = []
    return
  }
  const response = await adminListRbacRoles()
  roles.value = response.data.items
}

const loadData = async (resetPage = false) => {
  if (resetPage) pagination.currentPage = 1
  const response = await adminListAdminAccounts({
    search: filters.search || undefined,
    status: filters.status || undefined,
    role_key: filters.role_key || undefined,
    account_type: 'staff',
    limit: pagination.pageSize,
    offset: (pagination.currentPage - 1) * pagination.pageSize,
  })
  accounts.value = response.data.items
  total.value = response.data.total
  if (!accounts.value.length && total.value > 0 && pagination.currentPage > 1) {
    pagination.currentPage -= 1
    await loadData()
  }
}

const openCreateDialog = () => {
  createDialog.visible = true
  Object.assign(createDialog.form, {
    username: '',
    password: '',
    display_name: '',
    role_keys: [],
    contact_name: '',
    contact_phone: '',
  })
}

const openEditDialog = (account: AgentAccount) => {
  editDialog.visible = true
  editDialog.accountId = account.id
  Object.assign(editDialog.form, {
    display_name: account.display_name,
    status: account.status,
    contact_name: account.contact_name || '',
    contact_phone: account.contact_phone || '',
  })
}

const openRolesDialog = (account: AgentAccount) => {
  if (!canManageRoleBindings.value) {
    ElMessage.warning('当前账号无权绑定后台角色')
    return
  }
  rolesDialog.visible = true
  rolesDialog.accountId = account.id
  rolesDialog.role_keys = (account.assigned_roles || []).map((item) => item.role_key)
}

const openResetDialog = (account: AgentAccount) => {
  resetDialog.visible = true
  resetDialog.accountId = account.id
  resetDialog.new_password = ''
}

const submitCreate = async () => {
  if (!createDialog.form.role_keys.length) {
    ElMessage.warning('请至少绑定一个后台角色')
    return
  }
  creating.value = true
  try {
    await adminCreateAdminAccount({
      ...createDialog.form,
      role_keys: createDialog.form.role_keys,
      contact_name: createDialog.form.contact_name || undefined,
      contact_phone: createDialog.form.contact_phone || undefined,
    })
    createDialog.visible = false
    await loadData(true)
    lastActionMessage.value = '后台账号已创建'
    ElMessage.success(lastActionMessage.value)
  } finally {
    creating.value = false
  }
}

const submitEdit = async () => {
  saving.value = true
  try {
    await adminUpdateAdminAccount(editDialog.accountId, {
      ...editDialog.form,
      contact_name: editDialog.form.contact_name || undefined,
      contact_phone: editDialog.form.contact_phone || undefined,
    })
    editDialog.visible = false
    await loadData()
    lastActionMessage.value = '后台账号已更新'
    ElMessage.success(lastActionMessage.value)
  } finally {
    saving.value = false
  }
}

const submitRoles = async () => {
  if (!canManageRoleBindings.value) {
    ElMessage.warning('当前账号无权绑定后台角色')
    return
  }
  savingRoles.value = true
  try {
    await adminUpdateAdminAccountRoles(rolesDialog.accountId, rolesDialog.role_keys)
    rolesDialog.visible = false
    await loadData()
    lastActionMessage.value = '后台账号角色已更新'
    ElMessage.success(lastActionMessage.value)
  } finally {
    savingRoles.value = false
  }
}

const submitResetPassword = async () => {
  resettingPassword.value = true
  try {
    await adminResetAdminAccountPassword(resetDialog.accountId, resetDialog.new_password)
    resetDialog.visible = false
    lastActionMessage.value = '后台账号密码已重置'
    ElMessage.success(lastActionMessage.value)
  } finally {
    resettingPassword.value = false
  }
}

const handlePageChange = async () => {
  await loadData()
}

const handleSizeChange = async () => {
  pagination.currentPage = 1
  await loadData()
}

onMounted(async () => {
  await Promise.all([loadRoles(), loadData()])
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

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
