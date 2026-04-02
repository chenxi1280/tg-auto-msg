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
  slot_id?: string | null
  bound_account_id?: string | null
  bound_account_name?: string | null
  slot_end_at?: string | null
  created_at: string | null
}

export interface AdminCardsPage {
  items: AdminCard[]
  total: number
  limit: number
  offset: number
  stats: {
    total: number
    used: number
    unused: number
  }
}

export interface AdminLicenseSlot {
  slot_id: string
  user_id: number
  owner_username: string
  status: string
  current_account_id: string | null
  current_account_username: string | null
  current_account_phone: string | null
  current_account_tg_user_id: number | null
  total_duration_days: number
  start_at: string | null
  end_at: string | null
  created_at: string | null
  updated_at: string | null
}

export interface AdminUserSummary {
  id: number
  username: string
  email: string | null
  is_active: boolean
  created_at: string | null
  account_count: number
  developer_app_id?: number | null
  current_license: {
    start_at: string | null
    end_at: string | null
    status: string | null
  }
  license_slot_count?: number
  active_license_slot_count?: number
  unbound_active_slot_count?: number
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
  selection_weight: number
  health_status: string
  last_health_check_at: string | null
  last_health_error: string | null
  last_health_latency_ms: number | null
  health_fail_count: number
  credentials_version: number
  last_rotated_at: string | null
  notes: string | null
  is_default: boolean
  account_usage: number
  created_at: string | null
  updated_at: string | null
}

export interface AdminDeveloperAppSettings {
  assignment_mode: 'round_robin' | 'weight'
  alert_tg_user_ids: number[]
  alert_tg_user_ids_text: string
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
  payload: Partial<Pick<AdminPlan, 'display_name' | 'billing_cycle' | 'price_cents' | 'duration_days' | 'is_active' | 'sort_order'>>,
): Promise<{ success: boolean; data: AdminPlan }> =>
  adminApi.put(`/admin/plans/${planCode}`, payload)

export const adminCreatePlan = (payload: {
  plan_code: string
  display_name: string
  billing_cycle: string
  price_cents: number
  duration_days: number
  is_active?: boolean
  sort_order?: number
}): Promise<{ success: boolean; data: AdminPlan }> => adminApi.post('/admin/plans', payload)

export const adminDeletePlan = (
  planCode: string,
): Promise<{ success: boolean; data: { plan_code: string; disabled_unused_cards: number; used_cards_kept: number } }> =>
  adminApi.delete(`/admin/plans/${encodeURIComponent(planCode)}`)

export const adminListDeveloperApps = (): Promise<{ success: boolean; data: { apps: AdminDeveloperApp[]; settings: AdminDeveloperAppSettings } }> =>
  adminApi.get('/admin/developer-apps')

export const adminGetDeveloperAppSettings = (): Promise<{ success: boolean; data: AdminDeveloperAppSettings }> =>
  adminApi.get('/admin/settings/developer-apps')

export const adminCreateDeveloperApp = (payload: {
  app_name: string
  api_id: number
  api_hash: string
  is_active?: boolean
  max_accounts?: number
  selection_weight?: number
  notes?: string
}): Promise<{ success: boolean; data: AdminDeveloperApp }> => adminApi.post('/admin/developer-apps', payload)

export const adminUpdateDeveloperApp = (
  appId: number,
  payload: {
    app_name?: string
    api_hash?: string
    is_active?: boolean
    max_accounts?: number
    selection_weight?: number
    notes?: string
  },
): Promise<{ success: boolean; data: AdminDeveloperApp & { rotated_accounts?: number } }> =>
  adminApi.put(`/admin/developer-apps/${appId}`, payload)

export const adminUpdateDeveloperAppSettings = (payload: {
  assignment_mode: 'round_robin' | 'weight'
  alert_tg_user_ids: string
}): Promise<{ success: boolean; data: AdminDeveloperAppSettings }> =>
  adminApi.put('/admin/settings/developer-apps', payload)

export const adminSetDefaultDeveloperApp = (appId: number): Promise<{ success: boolean }> =>
  adminApi.post(`/admin/developer-apps/${appId}/set-default`)

export const adminCheckDeveloperAppHealth = (
  appId: number,
): Promise<{
  success: boolean
  data: {
    app_id: number
    app_name: string
    previous_status: string
    current_status: string
    checked_at: string
    last_health_error: string | null
    last_health_latency_ms: number | null
    migrated_account_ids: string[]
    stalled_account_ids: string[]
    notified_recipients: number[]
  }
}> => adminApi.post(`/admin/developer-apps/${appId}/check`)

export const adminGenerateCards = (payload: {
  plan_code: string
  quantity: number
  valid_days?: number | null
  prefix?: string
}): Promise<{ success: boolean; data: AdminCard[] }> => adminApi.post('/admin/cards/generate', payload)

export const adminListCards = (params?: {
  plan_code?: string
  is_used?: boolean
  is_active?: boolean
  sort_by?: 'created_at' | 'used_at' | 'expires_at'
  sort_order?: 'asc' | 'desc'
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: AdminCardsPage }> => adminApi.get('/admin/cards', { params })

export const adminExportCardsXlsx = (params?: {
  plan_code?: string
  is_used?: boolean
  is_active?: boolean
}): Promise<Blob> => adminApi.get('/admin/cards/export', { params, responseType: 'blob' })

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
