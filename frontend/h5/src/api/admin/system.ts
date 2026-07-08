import { adminApi } from './client'
import type {
  PurchaseSettings,
  BotNoticeSettings,
  SystemTodayStats,
  DeveloperApp,
  DeveloperAppSettings,
  ClashAddress,
  SystemProxy,
  AdminAuditLog,
  PaginatedResponse,
} from './types'

// ── Purchase Settings ────────────────────────────────────────────────────────

export const adminGetPurchaseSettings = (): Promise<{ success: boolean; data: PurchaseSettings }> =>
  adminApi.get('/admin/system/purchase-settings')

export const adminUpdatePurchaseSettings = (payload: PurchaseSettings): Promise<{ success: boolean; data: PurchaseSettings }> =>
  adminApi.put('/admin/system/purchase-settings', payload)

// ── Bot Notice Settings ──────────────────────────────────────────────────────

export const adminGetBotNoticeSettings = (): Promise<{ success: boolean; data: BotNoticeSettings }> =>
  adminApi.get('/admin/system/bot-notice')

export const adminUpdateBotNoticeSettings = (payload: {
  enabled: boolean
  entry_button_text: string
  message_text: string
  target_url: string
}): Promise<{ success: boolean; data: BotNoticeSettings }> =>
  adminApi.put('/admin/system/bot-notice', payload)

// ── Clash Addresses ─────────────────────────────────────────────────────────

export const adminListClashAddresses = (params?: {
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: PaginatedResponse<ClashAddress> }> =>
  adminApi.get('/admin/system/clash-addresses', { params })

export const adminCreateClashAddress = (payload: {
  name: string
  url: string
  is_active: boolean
  remark: string
}): Promise<{ success: boolean; data: ClashAddress }> =>
  adminApi.post('/admin/system/clash-addresses', payload)

export const adminUpdateClashAddress = (
  addressId: number,
  payload: {
    name: string
    url?: string
    is_active: boolean
    remark: string
  },
): Promise<{ success: boolean; data: ClashAddress }> =>
  adminApi.put(`/admin/system/clash-addresses/${addressId}`, payload)

export const adminDeleteClashAddress = (addressId: number): Promise<{ success: boolean; message: string }> =>
  adminApi.delete(`/admin/system/clash-addresses/${addressId}`)

export const adminActivateClashAddress = (addressId: number): Promise<{ success: boolean; data: ClashAddress }> =>
  adminApi.post(`/admin/system/clash-addresses/${addressId}/activate`)

// ── System Stats ─────────────────────────────────────────────────────────────

export const adminGetTodaySystemStats = (): Promise<{ success: boolean; data: SystemTodayStats }> =>
  adminApi.get('/admin/system/stats/today')

// ── Developer Apps ───────────────────────────────────────────────────────────

export const adminListDeveloperApps = (params?: {
  search?: string
  health_status?: string
  is_active?: boolean
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: PaginatedResponse<DeveloperApp> & { settings: DeveloperAppSettings } }> =>
  adminApi.get('/admin/developer-apps', { params })

export const adminCreateDeveloperApp = (payload: {
  app_name: string
  api_id: number
  api_hash: string
  is_active?: boolean
  max_accounts?: number
  selection_weight?: number
  notes?: string
}): Promise<{ success: boolean; data: DeveloperApp }> =>
  adminApi.post('/admin/developer-apps', payload)

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
): Promise<{ success: boolean; data: Record<string, unknown> }> =>
  adminApi.put(`/admin/developer-apps/${appId}`, payload)

export const adminGetDeveloperAppSettings = (): Promise<{ success: boolean; data: DeveloperAppSettings }> =>
  adminApi.get('/admin/developer-apps/settings')

export const adminUpdateDeveloperAppSettings = (payload: {
  assignment_mode: string
  alert_tg_user_ids: string
}): Promise<{ success: boolean; data: DeveloperAppSettings }> =>
  adminApi.put('/admin/developer-apps/settings', payload)

export const adminSetDefaultDeveloperApp = (appId: number): Promise<{ success: boolean; message: string }> =>
  adminApi.post(`/admin/developer-apps/${appId}/set-default`)

export const adminCheckDeveloperApp = (appId: number): Promise<{ success: boolean; data: Record<string, unknown> }> =>
  adminApi.post(`/admin/developer-apps/${appId}/check`)

// ── System Proxies ───────────────────────────────────────────────────────────

export const adminListSystemProxies = (params?: {
  search?: string
  is_healthy?: boolean
  is_assigned?: boolean
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: PaginatedResponse<SystemProxy> }> =>
  adminApi.get('/admin/system-proxies', { params })

export const adminAddSystemProxy = (payload: {
  proxy_type: string
  host: string
  port: number
  username?: string
  password?: string
}): Promise<{ success: boolean; data: SystemProxy }> =>
  adminApi.post('/admin/system-proxies', payload)

export const adminDeleteSystemProxy = (proxyId: number): Promise<{ success: boolean; message: string }> =>
  adminApi.delete(`/admin/system-proxies/${proxyId}`)

export const adminCheckSystemProxy = (proxyId: number): Promise<{ success: boolean; data: Record<string, unknown> }> =>
  adminApi.post(`/admin/system-proxies/${proxyId}/check`)

export const adminAssignSystemProxy = (proxyId: number, accountId: string): Promise<{ success: boolean; message: string }> =>
  adminApi.post(`/admin/system-proxies/${proxyId}/assign`, { account_id: accountId })

export const adminUnassignSystemProxy = (proxyId: number): Promise<{ success: boolean; message: string }> =>
  adminApi.post(`/admin/system-proxies/${proxyId}/unassign`)

// ── Audit Logs ───────────────────────────────────────────────────────────────

export const adminListSystemAuditLogs = (params?: {
  action?: string
  target_type?: string
  target_id?: string
  developer_app_id?: number
  keyword?: string
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: PaginatedResponse<AdminAuditLog> }> =>
  adminApi.get('/admin/audit-logs', { params })
