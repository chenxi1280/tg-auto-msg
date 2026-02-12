import axios, { type AxiosInstance } from 'axios'
import { ElMessage } from 'element-plus'

const ADMIN_TOKEN_KEY = 'admin_token'

const adminApi: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 30000,
})

adminApi.interceptors.request.use((config) => {
  const token = localStorage.getItem(ADMIN_TOKEN_KEY) || ''
  if (token && config.headers) {
    config.headers['X-Admin-Token'] = token
  }
  return config
})

adminApi.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const message = error?.response?.data?.detail || error?.message || '请求失败'
    ElMessage.error(message)
    return Promise.reject(error)
  },
)

export const getAdminToken = (): string => localStorage.getItem(ADMIN_TOKEN_KEY) || ''
export const setAdminToken = (token: string) => localStorage.setItem(ADMIN_TOKEN_KEY, token)
export const hasAdminToken = (): boolean => Boolean(getAdminToken())

export interface AdminPlan {
  plan_code: string
  display_name: string
  billing_cycle: string
  price_cents: number
  price_yuan: string
  duration_days: number
  is_active: boolean
  sort_order: number
}

export interface AdminCard {
  id: number
  card_code: string
  plan_code: string | null
  duration_days: number | null
  is_active: boolean
  is_used: boolean
  expires_at: string | null
  used_by_user_id: number | null
  used_at: string | null
  created_at: string | null
}

export interface AdminUserSummary {
  id: number
  username: string
  email: string | null
  is_active: boolean
  created_at: string | null
  account_count: number
  developer_app_id?: number | null
  subscription: {
    plan_code: string | null
    start_at: string | null
    end_at: string | null
    status: string | null
  }
}

export interface AdminAccount {
  account_id: string
  tg_user_id: number | null
  username: string | null
  first_name: string | null
  phone: string | null
  developer_app_id?: number | null
  is_active: boolean
  is_banned: boolean
  health_status: string
  is_flooding: boolean
  messages_sent: number
  created_at: string | null
}

export interface AdminProxy {
  proxy_id: number
  proxy_type: string
  host: string
  port: number
  username: string | null
  is_active: boolean
  is_healthy: boolean
  response_time_ms: number | null
  usage_count: number
  assigned_account_id: string | null
  last_check_at: string | null
  created_at: string | null
}

export interface AdminAccountOption {
  account_id: string
  username: string | null
  phone: string | null
  tg_user_id: number | null
  owner_user_id: number
  owner_username: string
  label: string
}

export interface AdminAuditLog {
  id: number
  actor: string
  action: string
  action_label?: string
  target_type: string | null
  target_type_label?: string | null
  target_id: string | null
  developer_app_id?: number | null
  old_value?: Record<string, any> | null
  new_value?: Record<string, any> | null
  detail: Record<string, any> | null
  ip_address: string | null
  created_at: string | null
}

export interface AdminDeveloperApp {
  id: number
  app_name: string
  api_id: number
  is_active: boolean
  max_accounts: number
  credentials_version: number
  last_rotated_at: string | null
  notes: string | null
  is_default: boolean
  account_usage: number
  created_at: string | null
  updated_at: string | null
}

export interface AdminPurchaseSettings {
  purchase_url: string
  purchase_button_text: string
}

export const adminListPlans = (): Promise<{ success: boolean; data: AdminPlan[] }> =>
  adminApi.get('/admin/plans')

export const adminGetPurchaseSettings = (): Promise<{ success: boolean; data: AdminPurchaseSettings }> =>
  adminApi.get('/admin/settings/purchase')

export const adminUpdatePurchaseSettings = (
  payload: AdminPurchaseSettings,
): Promise<{ success: boolean; data: AdminPurchaseSettings }> => adminApi.put('/admin/settings/purchase', payload)

export const adminUpdatePlan = (
  planCode: string,
  payload: Partial<Pick<AdminPlan, 'display_name' | 'price_cents' | 'duration_days' | 'is_active' | 'sort_order'>>,
): Promise<{ success: boolean; data: AdminPlan }> =>
  adminApi.put(`/admin/plans/${planCode}`, payload)

export const adminListDeveloperApps = (): Promise<{ success: boolean; data: { apps: AdminDeveloperApp[] } }> =>
  adminApi.get('/admin/developer-apps')

export const adminCreateDeveloperApp = (payload: {
  app_name: string
  api_id: number
  api_hash: string
  is_active?: boolean
  max_accounts?: number
  notes?: string
}): Promise<{ success: boolean; data: AdminDeveloperApp }> => adminApi.post('/admin/developer-apps', payload)

export const adminUpdateDeveloperApp = (
  appId: number,
  payload: {
    app_name?: string
    api_hash?: string
    is_active?: boolean
    max_accounts?: number
    notes?: string
  },
): Promise<{ success: boolean; data: AdminDeveloperApp & { rotated_accounts?: number } }> =>
  adminApi.put(`/admin/developer-apps/${appId}`, payload)

export const adminSetDefaultDeveloperApp = (appId: number): Promise<{ success: boolean }> =>
  adminApi.post(`/admin/developer-apps/${appId}/set-default`)

export const adminGenerateCards = (payload: {
  plan_code: string
  quantity: number
  duration_days?: number | null
  valid_days?: number | null
  prefix?: string
}): Promise<{ success: boolean; data: AdminCard[] }> => adminApi.post('/admin/cards/generate', payload)

export const adminListCards = (params?: {
  plan_code?: string
  is_used?: boolean
  is_active?: boolean
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: AdminCard[] }> => adminApi.get('/admin/cards', { params })

export const adminDisableCard = (cardCode: string): Promise<{ success: boolean }> =>
  adminApi.post(`/admin/cards/${encodeURIComponent(cardCode)}/disable`)

export const adminEnableCard = (cardCode: string): Promise<{ success: boolean }> =>
  adminApi.post(`/admin/cards/${encodeURIComponent(cardCode)}/enable`)

export const adminListUsers = (params?: {
  search?: string
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: AdminUserSummary[] }> => adminApi.get('/admin/users', { params })

export const adminListUserAccounts = (userId: number): Promise<{ success: boolean; data: AdminAccount[] }> =>
  adminApi.get(`/admin/users/${userId}/accounts`)

export const adminDeleteAccount = (accountId: string): Promise<{ success: boolean }> =>
  adminApi.delete(`/admin/accounts/${accountId}`)

export const adminResetUserPassword = (
  userId: number,
  newPassword: string,
): Promise<{ success: boolean }> => adminApi.post(`/admin/users/${userId}/reset-password`, { new_password: newPassword })

export const adminUpdateUserSubscription = (
  userId: number,
  payload: {
    plan_code?: string | null
    end_at?: string | null
    extend_days?: number | null
    set_inactive?: boolean
  },
): Promise<{ success: boolean; data: any }> => adminApi.put(`/admin/users/${userId}/subscription`, payload)

export const adminSetUserDeveloperApp = (
  userId: number,
  developerAppId?: number | null,
): Promise<{ success: boolean; data: any }> =>
  adminApi.put(`/admin/users/${userId}/developer-app`, { developer_app_id: developerAppId || null })

export const adminListAccountOptions = (params?: {
  search?: string
  limit?: number
}): Promise<{ success: boolean; data: AdminAccountOption[] }> => adminApi.get('/admin/accounts/options', { params })

export const adminListProxies = (): Promise<{ success: boolean; data: AdminProxy[] }> =>
  adminApi.get('/admin/proxies')

export const adminAddProxy = (payload: {
  proxy_type: string
  host: string
  port: number
  username?: string
  password?: string
}): Promise<{ success: boolean; data: AdminProxy }> => adminApi.post('/admin/proxies', payload)

export const adminCheckProxyHealth = (
  proxyId: number,
): Promise<{ success: boolean; data: { is_healthy: boolean; response_time_ms: number; error?: string | null } }> =>
  adminApi.post(`/admin/proxies/${proxyId}/check`)

export const adminDeleteProxy = (proxyId: number): Promise<{ success: boolean }> =>
  adminApi.delete(`/admin/proxies/${proxyId}`)

export const adminAssignProxy = (proxyId: number, accountId: string): Promise<{ success: boolean }> =>
  adminApi.post(`/admin/proxies/${proxyId}/assign`, { account_id: accountId })

export const adminUnassignProxy = (proxyId: number): Promise<{ success: boolean }> =>
  adminApi.post(`/admin/proxies/${proxyId}/unassign`)

export const adminListAuditLogs = (params?: {
  action?: string
  target_type?: string
  target_id?: string
  developer_app_id?: number
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: AdminAuditLog[] }> => adminApi.get('/admin/audit-logs', { params })
