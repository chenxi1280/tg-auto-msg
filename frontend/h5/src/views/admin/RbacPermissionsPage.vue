<template>
  <div class="page-stack">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>权限点字典</span>
          <div class="header-actions">
            <el-input v-model.trim="keyword" clearable placeholder="搜索权限名称/编码/模块" style="width: 260px" />
            <el-button @click="loadData">刷新</el-button>
          </div>
        </div>
      </template>

      <div class="permission-grid">
        <el-card v-for="group in filteredGroups" :key="group.moduleKey" shadow="never">
          <template #header>
            <div class="module-title">{{ group.moduleKey }}</div>
          </template>
          <div class="permission-list">
            <div v-for="permission in group.items" :key="permission.permission_code" class="permission-row">
              <div class="permission-name">{{ permission.display_name }}</div>
              <div class="permission-code">{{ permission.permission_code }}</div>
              <div class="permission-desc">{{ permission.description || '-' }}</div>
            </div>
          </div>
        </el-card>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { AdminPermission } from '@/api/admin'
import { adminListRbacPermissions } from '@/api/admin'

const permissions = ref<AdminPermission[]>([])
const keyword = ref('')

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

const filteredGroups = computed(() => {
  const normalizedKeyword = keyword.value.trim().toLowerCase()
  if (!normalizedKeyword) return permissionGroups.value
  return permissionGroups.value
    .map((group) => ({
      moduleKey: group.moduleKey,
      items: group.items.filter((permission) =>
        [permission.display_name, permission.permission_code, permission.module_key, permission.description || '']
          .join(' ')
          .toLowerCase()
          .includes(normalizedKeyword),
      ),
    }))
    .filter((group) => group.items.length)
})

const loadData = async () => {
  const response = await adminListRbacPermissions()
  permissions.value = response.data.items
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
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 16px;
}

.module-title {
  font-weight: 600;
  color: #0f172a;
}

.permission-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.permission-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.permission-name {
  font-weight: 600;
  color: #0f172a;
}

.permission-code,
.permission-desc {
  color: #64748b;
  font-size: 12px;
}
</style>
