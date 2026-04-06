/**
 * 路由配置
 */
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { hasAdminToken } from '@/api/admin'

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
    path: '/admin',
    name: 'AdminAuth',
    component: () => import('@/views/AdminAuth.vue'),
    meta: { title: '管理员密钥' }
  },
  {
    path: '/admin/dashboard',
    name: 'Admin',
    component: () => import('@/views/Admin.vue'),
    meta: { title: '管理员后台', requiresAdminToken: true }
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
  } else if (to.meta?.requiresAdminToken && !hasAdminToken()) {
    next({ path: '/admin' })
  } else {
    next()
  }
})

export default router
