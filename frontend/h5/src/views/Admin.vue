<template>
  <div class="admin-console" v-loading="store.loading.profile && !store.profile">
    <el-container class="admin-shell">
      <el-aside class="admin-aside" width="240px">
        <div class="brand-block">
          <img class="brand-logo" src="/quanqiu.png" alt="全球通" />
          <div>
            <div class="brand-title">省级后台</div>
            <div class="brand-subtitle">Element Admin Console</div>
          </div>
        </div>
        <el-menu :default-active="activeMenu" class="admin-menu" router>
          <el-menu-item v-for="item in mainMenus" :key="item.path" :index="item.path">{{ item.title }}</el-menu-item>
          <el-sub-menu v-if="systemMenus.length" index="super-admin-system">
            <template #title>系统后台</template>
            <el-menu-item v-for="item in systemMenus" :key="item.path" :index="item.path">{{ item.title }}</el-menu-item>
          </el-sub-menu>
        </el-menu>
      </el-aside>

      <el-container>
        <el-header class="admin-header">
          <div>
            <div class="page-title">{{ route.meta.title || '管理后台' }}</div>
            <el-breadcrumb separator="/">
              <el-breadcrumb-item>后台</el-breadcrumb-item>
              <el-breadcrumb-item>{{ route.meta.title || '管理后台' }}</el-breadcrumb-item>
            </el-breadcrumb>
          </div>
          <div class="header-actions">
            <div class="account-pill" v-if="store.profile">
              <strong>{{ store.profile.account.display_name }}</strong>
              <span>{{ roleLabel(store.profile.account.role_code) }} · {{ store.profile.province_code }}</span>
            </div>
            <el-button @click="refreshProfile">刷新</el-button>
            <el-button type="danger" plain @click="handleLogout">退出</el-button>
          </div>
        </el-header>
        <el-main class="admin-main">
          <router-view />
        </el-main>
      </el-container>
    </el-container>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { clearAdminAccessToken, adminLogout } from '@/api/admin'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { roleLabel } from '@/utils/adminConsole'

const router = useRouter()
const route = useRoute()
const store = useAdminConsoleStore()

const menuItems = [
  { path: '/admin/dashboard', title: '仪表盘', permissions: ['dashboard.read'], group: 'main' },
  { path: '/admin/security', title: '账户与安全', permissions: ['security.read'], group: 'main' },
  { path: '/admin/agents', title: '代理管理', permissions: ['agents.read'], group: 'main' },
  { path: '/admin/pricing', title: '统一价格', permissions: ['pricing.read'], group: 'main' },
  { path: '/admin/ledgers', title: '资金流水', permissions: ['ledgers.read'], group: 'main' },
  { path: '/admin/batches', title: '卡密批次', permissions: ['batches.read'], group: 'main' },
  { path: '/admin/approvals', title: '审批中心', permissions: ['approvals.read'], group: 'main' },
  { path: '/admin/audit', title: '审计日志', permissions: ['audit.read', 'audit.system.read'], group: 'main' },
  { path: '/admin/system-settings', title: '系统配置', permissions: ['system.settings.read'], group: 'system' },
  { path: '/admin/developer-apps', title: '开发者应用', permissions: ['developer_apps.read'], group: 'system' },
  { path: '/admin/system-proxies', title: '系统代理', permissions: ['system_proxies.read'], group: 'system' },
  { path: '/admin/legacy-cards', title: '旧卡密总后台', permissions: ['legacy_cards.read'], group: 'system' },
  { path: '/admin/users-auth', title: '用户与授权', permissions: ['users.read'], group: 'system' },
  { path: '/admin/admin-accounts', title: '后台账号', permissions: ['admin_accounts.read'], group: 'system' },
  { path: '/admin/rbac-roles', title: '角色管理', permissions: ['rbac.roles.read'], group: 'system' },
  { path: '/admin/rbac-permissions', title: '权限管理', permissions: ['rbac.permissions.read'], group: 'system' },
] as const

const activeMenu = computed(() => route.path)
const canAccessMenu = (permissions: readonly string[]) => store.hasAnyPermission([...permissions])
const mainMenus = computed(() => menuItems.filter((item) => item.group === 'main' && canAccessMenu(item.permissions)))
const systemMenus = computed(() => menuItems.filter((item) => item.group === 'system' && canAccessMenu(item.permissions)))
const accessibleMenus = computed(() => [...mainMenus.value, ...systemMenus.value])

const refreshProfile = async () => {
  await store.loadProfile()
}

const ensureRouteAccess = async () => {
  if (!store.profile) {
    await store.bootstrap()
  }
  const requiredPermissions = Array.isArray(route.meta.permissions) ? route.meta.permissions : []
  if (requiredPermissions.length && !store.hasAnyPermission(requiredPermissions as string[])) {
    const fallback = accessibleMenus.value[0]?.path || '/admin/login'
    if (route.path !== fallback) {
      await router.replace(fallback)
    }
  }
}

const handleLogout = async () => {
  try {
    await adminLogout()
  } catch {
    // ignore logout network errors and clear local session anyway
  }
  clearAdminAccessToken()
  store.reset()
  await router.replace('/admin/login')
}

onMounted(async () => {
  await ensureRouteAccess()
})

watch(
  () => [route.fullPath, (store.profile?.roles || []).join('|'), (store.profile?.permissions || []).join('|')],
  async () => {
    await ensureRouteAccess()
  },
)
</script>

<style scoped>
.admin-console {
  min-height: 100vh;
  background: #f5f7fb;
}

.admin-shell {
  min-height: 100vh;
}

.admin-aside {
  background: linear-gradient(180deg, #0f172a 0%, #172554 100%);
  color: #fff;
  padding: 20px 0 16px;
  box-shadow: 8px 0 24px rgba(15, 23, 42, 0.16);
}

.brand-block {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 0 20px 20px;
}

.brand-logo {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.12);
  padding: 6px;
}

.brand-title {
  font-size: 18px;
  font-weight: 700;
}

.brand-subtitle {
  margin-top: 4px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.72);
}

:deep(.admin-menu) {
  border-right: none;
  background: transparent;
}

:deep(.admin-menu .el-menu-item) {
  color: rgba(255, 255, 255, 0.76);
  margin: 4px 12px;
  border-radius: 10px;
}

:deep(.admin-menu .el-menu-item.is-active) {
  color: #fff;
  background: rgba(59, 130, 246, 0.26);
}

:deep(.admin-menu .el-menu-item:hover) {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}

.admin-header {
  height: 72px;
  background: rgba(255, 255, 255, 0.92);
  border-bottom: 1px solid #e8edf5;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
}

.page-title {
  margin-bottom: 6px;
  font-size: 22px;
  font-weight: 700;
  color: #0f172a;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.account-pill {
  display: flex;
  flex-direction: column;
  padding: 8px 14px;
  border-radius: 14px;
  background: #eff6ff;
  color: #1e3a8a;
  min-width: 180px;
}

.account-pill span {
  margin-top: 2px;
  font-size: 12px;
  color: #476082;
}

.admin-main {
  padding: 24px;
}

@media (max-width: 960px) {
  .admin-header {
    height: auto;
    padding: 16px;
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }

  .admin-main {
    padding: 16px;
  }
}
</style>
