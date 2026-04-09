<template>
  <div class="page-stack">
    <el-alert v-if="lastActionMessage" :title="lastActionMessage" type="success" :closable="true" @close="lastActionMessage = ''" />

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>角色管理</span>
          <div class="header-actions">
            <el-button @click="loadData">刷新</el-button>
            <el-button v-if="canWriteRoles" type="primary" @click="openCreateDialog">新增角色</el-button>
          </div>
        </div>
      </template>

      <el-table v-if="!isCompact" :data="roles" stripe>
        <el-table-column prop="display_name" label="角色名称" min-width="180" />
        <el-table-column prop="role_key" label="角色标识" min-width="180" />
        <el-table-column label="类型" width="120">
          <template #default="{ row }">
            <el-tag :type="row.is_system ? 'warning' : 'success'">{{ row.is_system ? '内置角色' : '自定义角色' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'info'">{{ row.status === 'active' ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="account_count" label="绑定账号数" width="120" />
        <el-table-column prop="permission_count" label="权限数" width="100" />
        <el-table-column prop="description" label="说明" min-width="220" />
        <el-table-column label="操作" min-width="240" fixed="right">
          <template #default="{ row }">
            <el-button v-if="canWriteRoles" link type="primary" @click="openEditDialog(row)">编辑</el-button>
            <el-button v-if="canManageRolePermissions" link type="success" @click="openPermissionDialog(row)">配置权限</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-else class="mobile-card-list">
        <div v-for="row in roles" :key="row.id" class="mobile-data-card">
          <div class="mobile-data-card__header">
            <div>
              <div class="mobile-data-card__title">{{ row.display_name }}</div>
              <div class="mobile-data-card__subtitle">{{ row.role_key }}</div>
            </div>
            <el-tag :type="row.is_system ? 'warning' : 'success'">{{ row.is_system ? '内置角色' : '自定义角色' }}</el-tag>
          </div>
          <div class="mobile-data-card__grid">
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">状态</span>
              <span class="mobile-data-card__value">{{ row.status === 'active' ? '启用' : '停用' }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">绑定账号数</span>
              <span class="mobile-data-card__value">{{ row.account_count }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">权限数</span>
              <span class="mobile-data-card__value">{{ row.permission_count }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">说明</span>
              <span class="mobile-data-card__value">{{ row.description || '-' }}</span>
            </div>
          </div>
          <div class="mobile-action-bar">
            <el-button v-if="canWriteRoles" type="primary" plain @click="openEditDialog(row)">编辑</el-button>
            <el-button v-if="canManageRolePermissions" type="success" plain @click="openPermissionDialog(row)">配置权限</el-button>
          </div>
        </div>
      </div>
    </el-card>

    <ResponsiveFormLayer v-model="editor.visible" :title="editor.id ? '编辑角色' : '新增角色'" width="520px">
      <el-form label-position="top">
        <el-form-item label="角色标识" v-if="!editor.id">
          <el-input v-model.trim="editor.role_key" />
        </el-form-item>
        <el-form-item label="角色名称">
          <el-input v-model.trim="editor.display_name" />
        </el-form-item>
        <el-form-item label="状态" v-if="editor.id">
          <el-select v-model="editor.status">
            <el-option label="启用" value="active" />
            <el-option label="停用" value="disabled" />
          </el-select>
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model.trim="editor.description" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editor.visible = false">取消</el-button>
        <el-button type="primary" :loading="savingRole" @click="submitRole">保存</el-button>
      </template>
    </ResponsiveFormLayer>

    <ResponsiveFormLayer v-model="permissionDialog.visible" title="配置角色权限" width="760px">
      <div class="permission-grid">
        <el-card v-for="group in permissionGroups" :key="group.moduleKey" shadow="never">
          <template #header>
            <div class="permission-group-title">{{ group.moduleKey }}</div>
          </template>
          <el-checkbox-group v-model="permissionDialog.permission_codes">
            <div class="checkbox-stack">
              <el-checkbox v-for="permission in group.items" :key="permission.permission_code" :value="permission.permission_code">
                <div class="permission-item">
                  <div>{{ permission.display_name }}</div>
                  <div class="permission-desc">{{ permission.permission_code }}</div>
                </div>
              </el-checkbox>
            </div>
          </el-checkbox-group>
        </el-card>
      </div>
      <template #footer>
        <el-button @click="permissionDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="savingPermissions" @click="submitPermissions">保存权限</el-button>
      </template>
    </ResponsiveFormLayer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { AdminPermission, AdminRole } from '@/api/admin'
import {
  adminCreateRbacRole,
  adminListRbacPermissions,
  adminListRbacRoles,
  adminUpdateRbacRole,
  adminUpdateRbacRolePermissions,
} from '@/api/admin'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { useResponsive } from '@/composables/useResponsive'
import ResponsiveFormLayer from '@/components/responsive/ResponsiveFormLayer.vue'

const store = useAdminConsoleStore()
const { isCompact } = useResponsive()
const canWriteRoles = computed(() => store.hasPermission('rbac.roles.write'))
const canReadPermissionDictionary = computed(() => store.hasPermission('rbac.permissions.read'))
const canManageRolePermissions = computed(() => canWriteRoles.value && canReadPermissionDictionary.value)
const roles = ref<AdminRole[]>([])
const permissions = ref<AdminPermission[]>([])
const lastActionMessage = ref('')
const savingRole = ref(false)
const savingPermissions = ref(false)

const editor = reactive({
  visible: false,
  id: 0,
  role_key: '',
  display_name: '',
  description: '',
  status: 'active',
})

const permissionDialog = reactive({
  visible: false,
  roleId: 0,
  permission_codes: [] as string[],
})

const permissionGroups = computed(() => {
  const map = new Map<string, AdminPermission[]>()
  for (const permission of permissions.value) {
    const items = map.get(permission.module_key) || []
    items.push(permission)
    map.set(permission.module_key, items)
  }
  return Array.from(map.entries()).map(([moduleKey, items]) => ({
    moduleKey,
    items,
  }))
})

const loadData = async () => {
  const roleResponse = await adminListRbacRoles()
  roles.value = roleResponse.data.items
  if (!canReadPermissionDictionary.value) {
    permissions.value = []
    return
  }
  const permissionResponse = await adminListRbacPermissions()
  permissions.value = permissionResponse.data.items
}

const openCreateDialog = () => {
  Object.assign(editor, {
    visible: true,
    id: 0,
    role_key: '',
    display_name: '',
    description: '',
    status: 'active',
  })
}

const openEditDialog = (role: AdminRole) => {
  Object.assign(editor, {
    visible: true,
    id: role.id,
    role_key: role.role_key,
    display_name: role.display_name,
    description: role.description || '',
    status: role.status,
  })
}

const openPermissionDialog = (role: AdminRole) => {
  if (!canManageRolePermissions.value) {
    ElMessage.warning('当前账号无权配置角色权限')
    return
  }
  permissionDialog.visible = true
  permissionDialog.roleId = role.id
  permissionDialog.permission_codes = [...role.permission_codes]
}

const submitRole = async () => {
  savingRole.value = true
  try {
    if (editor.id) {
      await adminUpdateRbacRole(editor.id, {
        display_name: editor.display_name,
        description: editor.description || undefined,
        status: editor.status,
      })
      lastActionMessage.value = '角色已更新'
    } else {
      await adminCreateRbacRole({
        role_key: editor.role_key,
        display_name: editor.display_name,
        description: editor.description || undefined,
      })
      lastActionMessage.value = '角色已创建'
    }
    editor.visible = false
    await loadData()
    ElMessage.success(lastActionMessage.value)
  } finally {
    savingRole.value = false
  }
}

const submitPermissions = async () => {
  if (!canManageRolePermissions.value) {
    ElMessage.warning('当前账号无权配置角色权限')
    return
  }
  savingPermissions.value = true
  try {
    await adminUpdateRbacRolePermissions(permissionDialog.roleId, permissionDialog.permission_codes)
    permissionDialog.visible = false
    await loadData()
    lastActionMessage.value = '角色权限已更新'
    ElMessage.success(lastActionMessage.value)
  } finally {
    savingPermissions.value = false
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

.permission-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 16px;
}

.permission-group-title {
  font-weight: 600;
  color: #0f172a;
}

.checkbox-stack {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.permission-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.permission-desc {
  color: #64748b;
  font-size: 12px;
}
</style>
