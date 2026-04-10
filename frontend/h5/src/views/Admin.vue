<template>
  <div class="admin-console" v-loading="store.loading.profile && !store.profile">
    <el-container class="admin-shell">
      <el-aside v-if="!isMobile" class="admin-aside" width="240px">
        <div class="brand-block">
          <img class="brand-logo" src="/quanqiu.png" alt="全球通" />
          <div>
            <div class="brand-title">省级后台</div>
            <div class="brand-subtitle">Element Admin Console</div>
          </div>
        </div>
        <el-menu :default-active="activeMenu" class="admin-menu" router>
          <el-menu-item v-for="item in mainMenus" :key="item.path" :index="item.path">{{ item.title }}</el-menu-item>
          <el-sub-menu v-if="systemMenus.length" index="super-admin-system" popper-class="admin-menu-popper">
            <template #title>系统后台</template>
            <el-menu-item v-for="item in systemMenus" :key="item.path" :index="item.path">{{ item.title }}</el-menu-item>
          </el-sub-menu>
        </el-menu>
      </el-aside>

      <el-container>
        <el-header class="admin-header">
          <div class="header-main">
            <el-button v-if="isMobile" class="menu-trigger" circle @click="mobileMenuVisible = true">
              <el-icon><Menu /></el-icon>
            </el-button>
            <div class="page-title">{{ route.meta.title || '管理后台' }}</div>
            <el-breadcrumb separator="/">
              <el-breadcrumb-item>后台</el-breadcrumb-item>
              <el-breadcrumb-item>{{ route.meta.title || '管理后台' }}</el-breadcrumb-item>
            </el-breadcrumb>
          </div>
          <div class="header-actions">
            <div class="account-pill" v-if="store.profile">
              <strong>{{ store.profile.account.display_name }}</strong>
              <span>{{ accountIdentitySummary(store.profile.account) }} · {{ store.profile.province_code }}</span>
            </div>
            <template v-if="!isMobile">
              <el-button @click="refreshProfile">刷新</el-button>
              <el-button type="danger" plain @click="handleLogout">退出</el-button>
            </template>
            <el-dropdown v-else trigger="click">
              <el-button circle>
                <el-icon><MoreFilled /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item @click="refreshProfile">刷新</el-dropdown-item>
                  <el-dropdown-item divided @click="handleLogout">退出登录</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </el-header>
        <el-main class="admin-main">
          <router-view />
        </el-main>
      </el-container>
    </el-container>

    <el-drawer
      v-model="mobileMenuVisible"
      class="mobile-admin-drawer"
      title="后台导航"
      :size="drawerSize"
      append-to-body
      direction="ltr"
    >
      <div class="mobile-brand-block">
        <img class="brand-logo" src="/quanqiu.png" alt="全球通" />
        <div>
          <div class="brand-title">省级后台</div>
          <div class="brand-subtitle">Element Admin Console</div>
        </div>
      </div>
      <div class="mobile-menu-group">
        <div class="mobile-menu-title">常用功能</div>
        <div class="mobile-menu-list">
          <el-button
            v-for="item in mainMenus"
            :key="item.path"
            class="mobile-menu-button"
            :type="activeMenu === item.path ? 'primary' : 'default'"
            @click="navigateTo(item.path)"
          >
            {{ item.title }}
          </el-button>
        </div>
      </div>
      <div v-if="systemMenus.length" class="mobile-menu-group">
        <div class="mobile-menu-title">系统后台</div>
        <div class="mobile-menu-list">
          <el-button
            v-for="item in systemMenus"
            :key="item.path"
            class="mobile-menu-button"
            :type="activeMenu === item.path ? 'primary' : 'default'"
            @click="navigateTo(item.path)"
          >
            {{ item.title }}
          </el-button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Menu, MoreFilled } from '@element-plus/icons-vue'
import { clearAdminAccessToken, adminLogout } from '@/api/admin'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { accountIdentitySummary } from '@/utils/adminConsole'
import { useResponsive } from '@/composables/useResponsive'

const router = useRouter()
const route = useRoute()
const store = useAdminConsoleStore()
const { isMobile, width } = useResponsive()
const mobileMenuVisible = ref(false)

const menuItems = [
  { path: '/admin/dashboard', title: '仪表盘', permissions: ['dashboard.read'], group: 'main' },
  { path: '/admin/account-center', title: '账号中心', permissions: ['security.read', 'agents.read'], group: 'main' },
  { path: '/admin/pricing', title: '统一价格', permissions: ['pricing.read'], group: 'main' },
  { path: '/admin/ledgers', title: '资金流水', permissions: ['ledgers.read'], group: 'main' },
  { path: '/admin/operation-logs', title: '操作日志', permissions: ['operation_logs.read', 'operation_logs.scope.read'], group: 'main' },
  { path: '/admin/card-center', title: '卡密中心', permissions: ['batches.read', 'legacy_cards.read'], group: 'main' },
  { path: '/admin/audit', title: '审计日志', permissions: ['audit.system.read'], group: 'main' },
  { path: '/admin/users-auth', title: '业务用户与授权', permissions: ['users.read'], group: 'system' },
  { path: '/admin/admin-accounts', title: '员工后台账号', permissions: ['admin_accounts.read'], group: 'system' },
  { path: '/admin/license-plans', title: '卡密规格', permissions: ['legacy_cards.read'], group: 'system' },
  { path: '/admin/system-stats', title: '数据统计', permissions: ['system.stats.read'], group: 'system' },
  { path: '/admin/system-settings', title: '系统配置', permissions: ['system.settings.read'], group: 'system' },
  { path: '/admin/developer-apps', title: '开发者应用', permissions: ['developer_apps.read'], group: 'system' },
  { path: '/admin/system-proxies', title: '系统代理', permissions: ['system_proxies.read'], group: 'system' },
  { path: '/admin/rbac-roles', title: '角色管理', permissions: ['rbac.roles.read'], group: 'system' },
  { path: '/admin/rbac-permissions', title: '权限管理', permissions: ['rbac.permissions.read'], group: 'system' },
] as const

const activeMenu = computed(() => route.path)
const drawerSize = computed(() => (width.value <= 768 ? '88%' : '360px'))
const canAccessMenu = (permissions: readonly string[]) => store.hasAnyPermission([...permissions])
const mainMenus = computed(() => menuItems.filter((item) => item.group === 'main' && canAccessMenu(item.permissions)))
const systemMenus = computed(() => menuItems.filter((item) => item.group === 'system' && canAccessMenu(item.permissions)))
const accessibleMenus = computed(() => [...mainMenus.value, ...systemMenus.value])

const refreshProfile = async () => {
  await store.loadProfile()
}

const navigateTo = async (path: string) => {
  mobileMenuVisible.value = false
  if (route.path !== path) {
    await router.push(path)
  }
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
    mobileMenuVisible.value = false
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
  backdrop-filter: blur(20px);
  border-right: 1px solid rgba(148, 163, 184, 0.12);
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
  padding: 8px 0;
}

:deep(.admin-menu .el-menu-item) {
  color: rgba(255, 255, 255, 0.86);
  margin: 4px 12px;
  border-radius: 10px;
  min-height: 44px;
  line-height: 44px;
  background: rgba(15, 23, 42, 0.18);
  backdrop-filter: blur(10px);
}

:deep(.admin-menu .el-menu-item.is-active) {
  color: #fff;
  background: linear-gradient(90deg, rgba(59, 130, 246, 0.34), rgba(37, 99, 235, 0.18));
  box-shadow: inset 0 0 0 1px rgba(147, 197, 253, 0.24);
}

:deep(.admin-menu .el-menu-item:hover) {
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
}

:deep(.admin-menu .el-sub-menu) {
  margin: 6px 12px 0;
  border-radius: 12px;
  overflow: hidden;
  background: rgba(15, 23, 42, 0.18);
  backdrop-filter: blur(10px);
}

:deep(.admin-menu .el-sub-menu__title) {
  color: rgba(255, 255, 255, 0.9);
  border-radius: 12px;
  min-height: 46px;
  line-height: 46px;
  margin: 0;
}

:deep(.admin-menu .el-sub-menu__title:hover) {
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
}

:deep(.admin-menu .el-sub-menu.is-opened > .el-sub-menu__title) {
  background: rgba(59, 130, 246, 0.18);
  color: #fff;
}

:deep(.admin-menu .el-sub-menu .el-menu) {
  background: rgba(15, 23, 42, 0.24);
  padding: 4px 0 8px;
}

:deep(.admin-menu .el-sub-menu .el-menu-item) {
  margin: 4px 10px;
  min-height: 40px;
  line-height: 40px;
}

:deep(.admin-menu-popper.el-popper),
:deep(.admin-menu-popper .el-menu) {
  background: rgba(15, 23, 42, 0.92) !important;
  backdrop-filter: blur(18px);
  border: 1px solid rgba(148, 163, 184, 0.16);
  box-shadow: 0 18px 40px rgba(15, 23, 42, 0.28);
  border-radius: 14px;
}

:deep(.admin-menu-popper .el-menu-item) {
  color: rgba(255, 255, 255, 0.88);
  border-radius: 10px;
  margin: 6px 8px;
}

:deep(.admin-menu-popper .el-menu-item:hover) {
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
}

:deep(.admin-menu-popper .el-menu-item.is-active) {
  background: linear-gradient(90deg, rgba(59, 130, 246, 0.34), rgba(37, 99, 235, 0.16));
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

.header-main {
  display: flex;
  align-items: center;
  gap: 14px;
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

.menu-trigger {
  flex-shrink: 0;
}

.mobile-brand-block {
  display: flex;
  align-items: center;
  gap: 14px;
  padding-bottom: 20px;
}

.mobile-menu-group + .mobile-menu-group {
  margin-top: 20px;
}

.mobile-menu-title {
  margin-bottom: 10px;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.mobile-menu-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.mobile-menu-button {
  justify-content: flex-start;
  min-height: 44px;
}

.admin-main {
  padding: 24px;
}

@media (max-width: 960px) {
  .admin-aside {
    display: none;
  }

  .admin-header {
    height: auto;
    padding: 16px;
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }

  .header-main,
  .header-actions {
    justify-content: space-between;
  }

  .account-pill {
    min-width: 0;
    flex: 1;
  }

  .admin-main {
    padding: 16px;
  }
}

@media (max-width: 768px) {
  .page-title {
    margin-bottom: 4px;
    font-size: 18px;
  }

  .admin-main {
    padding: 12px;
  }
}
</style>
