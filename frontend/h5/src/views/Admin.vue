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
          <el-menu-item index="/admin/dashboard">仪表盘</el-menu-item>
          <el-menu-item index="/admin/security">账户与安全</el-menu-item>
          <el-menu-item index="/admin/agents">代理管理</el-menu-item>
          <el-menu-item index="/admin/pricing">统一价格</el-menu-item>
          <el-menu-item index="/admin/ledgers">资金流水</el-menu-item>
          <el-menu-item index="/admin/batches">卡密批次</el-menu-item>
          <el-menu-item index="/admin/approvals">审批中心</el-menu-item>
          <el-menu-item index="/admin/audit">审计日志</el-menu-item>
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
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { clearAdminAccessToken, adminLogout } from '@/api/admin'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { roleLabel } from '@/utils/adminConsole'

const router = useRouter()
const route = useRoute()
const store = useAdminConsoleStore()

const activeMenu = computed(() => route.path)

const refreshProfile = async () => {
  await store.loadProfile()
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
  if (!store.profile) {
    await store.bootstrap()
  }
})
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
