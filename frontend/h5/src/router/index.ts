/**
 * 路由配置
 */
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { hasAdminSession } from '@/api/admin'

// 布局组件（暂不使用）
// import Layout from '@/components/Layout.vue'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'Home',
    component: () => import('@/views/Home.vue'),
    meta: { title: '全球通' }
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginSystem.vue'),
    meta: { title: '系统登录' }
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/views/Register.vue'),
    meta: { title: '注册账号' }
  },
  {
    path: '/bind-tg',
    name: 'BindTelegram',
    component: () => import('@/views/BindTelegram.vue'),
    meta: { title: '绑定 Telegram', requiresAuth: true }
  },
  {
    path: '/accounts',
    name: 'Accounts',
    component: () => import('@/views/Accounts.vue'),
    meta: { title: '账号管理', requiresAuth: true }
  },
  {
    path: '/resources',
    name: 'Resources',
    component: () => import('@/views/Resources.vue'),
    meta: { title: '资源列表', requiresAuth: true }
  },
  {
    path: '/proxies',
    name: 'Proxies',
    component: () => import('@/views/Proxies.vue'),
    meta: { title: '代理管理', requiresAuth: true }
  },
  {
    path: '/tasks',
    name: 'Tasks',
    component: () => import('@/views/Tasks.vue'),
    meta: { title: '任务管理', requiresAuth: true }
  },
  {
    path: '/tasks/:taskId/logs',
    name: 'TaskLogs',
    component: () => import('@/views/TaskLogs.vue'),
    meta: { title: '任务发送记录', requiresAuth: true }
  },
  {
    path: '/me',
    name: 'Me',
    component: () => import('@/views/My.vue'),
    meta: { title: '我的', requiresAuth: true }
  },
  {
    path: '/purchase',
    name: 'Purchase',
    component: () => import('@/views/Purchase.vue'),
    meta: { title: '购买卡密', requiresAuth: true }
  },
  {
    path: '/admin/login',
    name: 'AdminAuth',
    component: () => import('@/views/AdminAuth.vue'),
    meta: { title: '后台登录' }
  },
  {
    path: '/admin',
    component: () => import('@/views/Admin.vue'),
    meta: { title: '管理员后台', requiresAdminSession: true },
    children: [
      {
        path: '',
        redirect: '/admin/dashboard'
      },
      {
        path: 'dashboard',
        name: 'AdminDashboard',
        component: () => import('@/views/admin/DashboardPage.vue'),
        meta: { title: '仪表盘', requiresAdminSession: true, permissions: ['dashboard.read'] }
      },
      {
        path: 'security',
        name: 'AdminSecurity',
        component: () => import('@/views/admin/SecurityPage.vue'),
        meta: { title: '账户与安全', requiresAdminSession: true, permissions: ['security.read'] }
      },
      {
        path: 'agents',
        name: 'AdminAgents',
        component: () => import('@/views/admin/AgentsPage.vue'),
        meta: { title: '代理管理', requiresAdminSession: true, permissions: ['agents.read'] }
      },
      {
        path: 'pricing',
        name: 'AdminPricing',
        component: () => import('@/views/admin/PricingPage.vue'),
        meta: { title: '统一价格', requiresAdminSession: true, permissions: ['pricing.read'] }
      },
      {
        path: 'ledgers',
        name: 'AdminLedgers',
        component: () => import('@/views/admin/LedgersPage.vue'),
        meta: { title: '资金流水', requiresAdminSession: true, permissions: ['ledgers.read'] }
      },
      {
        path: 'batches',
        name: 'AdminBatches',
        component: () => import('@/views/admin/BatchesPage.vue'),
        meta: { title: '卡密批次', requiresAdminSession: true, permissions: ['batches.read'] }
      },
      {
        path: 'approvals',
        name: 'AdminApprovals',
        component: () => import('@/views/admin/ApprovalsPage.vue'),
        meta: { title: '审批中心', requiresAdminSession: true, permissions: ['approvals.read'] }
      },
      {
        path: 'audit',
        name: 'AdminAudit',
        component: () => import('@/views/admin/AuditPage.vue'),
        meta: { title: '审计日志', requiresAdminSession: true, permissions: ['audit.read', 'audit.system.read'] }
      },
      {
        path: 'system-settings',
        name: 'AdminSystemSettings',
        component: () => import('@/views/admin/SystemSettingsPage.vue'),
        meta: { title: '系统配置', requiresAdminSession: true, permissions: ['system.settings.read'] }
      },
      {
        path: 'developer-apps',
        name: 'AdminDeveloperApps',
        component: () => import('@/views/admin/DeveloperAppsPage.vue'),
        meta: { title: '开发者应用', requiresAdminSession: true, permissions: ['developer_apps.read'] }
      },
      {
        path: 'system-proxies',
        name: 'AdminSystemProxies',
        component: () => import('@/views/admin/SystemProxiesPage.vue'),
        meta: { title: '系统代理', requiresAdminSession: true, permissions: ['system_proxies.read'] }
      },
      {
        path: 'legacy-cards',
        name: 'AdminLegacyCards',
        component: () => import('@/views/admin/LegacyCardsPage.vue'),
        meta: { title: '旧卡密总后台', requiresAdminSession: true, permissions: ['legacy_cards.read'] }
      },
      {
        path: 'users-auth',
        name: 'AdminUsersAuth',
        component: () => import('@/views/admin/UsersAuthPage.vue'),
        meta: { title: '用户与授权', requiresAdminSession: true, permissions: ['users.read'] }
      },
      {
        path: 'admin-accounts',
        name: 'AdminAccountsManage',
        component: () => import('@/views/admin/AdminAccountsPage.vue'),
        meta: { title: '后台账号', requiresAdminSession: true, permissions: ['admin_accounts.read'] }
      },
      {
        path: 'rbac-roles',
        name: 'AdminRbacRoles',
        component: () => import('@/views/admin/RbacRolesPage.vue'),
        meta: { title: '角色管理', requiresAdminSession: true, permissions: ['rbac.roles.read'] }
      },
      {
        path: 'rbac-permissions',
        name: 'AdminRbacPermissions',
        component: () => import('@/views/admin/RbacPermissionsPage.vue'),
        meta: { title: '权限管理', requiresAdminSession: true, permissions: ['rbac.permissions.read'] }
      }
    ]
  },
  {
    path: '/task/:taskId',
    name: 'TaskLegacyRedirect',
    redirect: (to) => ({
      path: '/tasks',
      query: { task_id: String(to.params.taskId || '') }
    })
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    redirect: () => (isAuthenticated() ? '/accounts' : '/')
  }
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
})

// 简单的认证检查（可根据需要调整）
const isAuthenticated = (): boolean => {
  const token = localStorage.getItem('token')
  const rawUserId = localStorage.getItem('user_id')
  const userId = Number(rawUserId)
  return Boolean(token && Number.isInteger(userId) && userId > 0)
}

// 路由守卫
router.beforeEach((to, _from, next) => {
  // 设置页面标题
  if (to.meta?.title) {
    document.title = `${to.meta.title} - 全球通`
  }

  // 已登录时访问登录/注册页，统一回到主业务页
  if ((to.path === '/login' || to.path === '/register') && isAuthenticated()) {
    next('/accounts')
    return
  }

  if (to.path === '/' && isAuthenticated()) {
    next('/accounts')
    return
  }

  // 检查认证
  if (to.meta?.requiresAuth && !isAuthenticated()) {
    // 保存原始跳转路径
    next({
      path: '/login',
      query: { redirect: to.fullPath }
    })
  } else if (to.meta?.requiresAdminSession && !hasAdminSession()) {
    next({ path: '/admin/login' })
  } else {
    if (to.path === '/admin/login' && hasAdminSession()) {
      next('/admin/dashboard')
      return
    }
    next()
  }
})

export default router
