import axios, { type AxiosInstance } from 'axios'
import { ElMessage } from 'element-plus'

const ADMIN_ACCESS_TOKEN_KEY = 'admin_access_token'

const adminApi: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 30000,
})

const clearAdminStorage = () => {
  localStorage.removeItem(ADMIN_ACCESS_TOKEN_KEY)
}

const showAdminErrorMessage = (message: string) => {
  ElMessage.error(message)
}

adminApi.interceptors.request.use((config) => {
  const token = localStorage.getItem(ADMIN_ACCESS_TOKEN_KEY) || ''
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

adminApi.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const status = error?.response?.status
    const message = error?.response?.data?.detail || error?.message || '请求失败'
    if (status === 401) {
      clearAdminStorage()
      if (window.location.pathname !== '/admin/login') {
        window.location.href = '/admin/login'
      }
    }
    showAdminErrorMessage(message)
    return Promise.reject(error)
  },
)

export const getAdminAccessToken = (): string => localStorage.getItem(ADMIN_ACCESS_TOKEN_KEY) || ''
export const setAdminAccessToken = (token: string) => localStorage.setItem(ADMIN_ACCESS_TOKEN_KEY, token)
export const clearAdminAccessToken = clearAdminStorage
export const hasAdminSession = (): boolean => Boolean(getAdminAccessToken())

export interface AdminBindingInfo {
  bind_status: string
  tg_user_id: number | null
  tg_username: string | null
  bound_at: string | null
}

export interface AdminAssignedRole {
  role_id: number
  role_key: string
  display_name: string
  is_system: boolean
}

export interface AdminProfileAccount {
  id: number
  username: string
  display_name: string
  role_code: string
  account_type: 'staff' | 'agent'
  business_identity: 'master_agent' | 'sub_agent' | null
  province_code: string
  parent_account_id: number | null
  root_master_account_id: number | null
  level_depth: number
  status: string
  settlement_mode: string
  is_credit_whitelisted: boolean
  credit_limit_cents: number
  allocated_credit_limit_cents: number
  credit_used_cents: number
  credit_prepay_cents: number
  balance_cents: number
  force_password_change: boolean
  contact_name: string | null
  contact_phone: string | null
  last_login_at: string | null
  created_at: string | null
  updated_at: string | null
  tg_binding: AdminBindingInfo
  assigned_roles?: AdminAssignedRole[]
  permissions?: string[]
}

export interface AdminProfile {
  account: AdminProfileAccount
  visible_account_count: number
  province_code: string
  roles: string[]
  permissions: string[]
}

export interface PaginatedResponse<T, TStats = Record<string, any>> {
  items: T[]
  total: number
  limit: number
  offset: number
  stats?: TStats
  settings?: Record<string, any>
}

export interface AgentPlan {
  plan_code: string
  display_name: string
  billing_cycle: string
  price_cents: number
  price_yuan: string
  duration_days: number
  is_active: boolean
  sort_order: number
}

export interface AgentAccount extends AdminProfileAccount {}

export interface AdminRole {
  id: number
  role_key: string
  display_name: string
  description: string | null
  status: string
  is_system: boolean
  permission_codes: string[]
  permission_count: number
  account_count: number
  created_at: string | null
  updated_at: string | null
}

export interface AdminPermission {
  id: number
  permission_code: string
  module_key: string
  display_name: string
  description: string | null
}

export interface CardBatch {
  batch_id: string
  province_code: string
  creator_account_id: number
  owner_account_id: number
  direct_parent_account_id: number | null
  root_master_account_id: number | null
  current_liability_account_id: number | null
  current_counterparty_account_id: number | null
  current_counterparty_name?: string | null
  plan_code: string
  plan_display_name?: string | null
  quantity: number
  duration_days: number
  unit_price_cents: number
  total_amount_cents: number
  settlement_status: string
  payment_status: string
  export_count: number
  used_count?: number
  total_count?: number
  last_exported_at: string | null
  remark: string | null
  created_at: string | null
}

export interface AgentCard {
  id: number
  card_code: string
  plan_code: string | null
  plan_display_name?: string | null
  duration_days: number | null
  is_active: boolean
  is_used: boolean
  expires_at: string | null
  used_by_user_id: number | null
  used_at: string | null
  batch_id: string | null
  owner_account_id: number | null
  direct_parent_account_id: number | null
  root_master_account_id: number | null
  settlement_unit_price_cents: number
  card_source_type: string
  copy_status: string
  created_at: string | null
}

export interface AdminAuditLog {
  id: number
  actor: string
  action: string
  action_label?: string | null
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

export interface FundLedger {
  id: number
  ledger_scope: string
  account_id: number
  account_name: string | null
  counterparty_account_id: number | null
  counterparty_name: string | null
  biz_type: string
  direction: string
  amount_cents: number
  balance_after_cents: number | null
  credit_used_after_cents: number | null
  related_batch_id: string | null
  related_request_id: string | null
  remark: string | null
  operator_account_id: number | null
  operator_name: string | null
  created_at: string | null
}

export interface OperationLog {
  log_type: 'recharge' | 'card_generate' | 'credit_settlement'
  occurred_at: string | null
  operator_account_id: number | null
  operator_name: string | null
  subject_account_id: number | null
  subject_name: string | null
  counterparty_account_id: number | null
  counterparty_name: string | null
  amount_cents: number
  plan_code: string | null
  plan_display_name?: string | null
  quantity: number | null
  batch_id: string | null
  funding_source: string | null
  ledger_scope: string | null
  remark: string | null
}

export interface PurchaseSettings {
  purchase_url: string
  purchase_button_text: string
}

export interface BotNoticeSettings {
  enabled: boolean
  entry_button_text: string
  message_text: string
  target_url: string
  updated_at?: string | null
  refresh_summary?: {
    total_users?: number
    updated?: number
    failed?: number
    pin_attempted_users?: number
    pin_failed_users?: number
    results?: Record<string, any>[]
  }
}

export interface SystemTodayStats {
  date: string
  timezone: string
  today_sent_messages: number
  today_bound_cards: number
  today_new_users: number
}

export interface DeveloperApp {
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
}

export interface DeveloperAppSettings {
  assignment_mode: string
  alert_tg_user_ids: number[]
  alert_tg_user_ids_text: string
  default_developer_app_id?: number | null
  default_developer_app_name?: string | null
  default_developer_app_active?: boolean
}

export interface LegacyProxy {
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
  assigned_account_name?: string | null
  last_check_at: string | null
  created_at: string | null
}

export interface LegacyLicenseCard {
  id: number
  card_code: string
  plan_code: string | null
  duration_days: number | null
  is_active: boolean
  is_used: boolean
  expires_at: string | null
  used_by_user_id: number | null
  used_by_username?: string | null
  used_at: string | null
  authorization_id?: string | null
  bound_account_id?: string | null
  bound_account_name?: string | null
  authorization_end_at?: string | null
  created_at: string | null
  updated_at?: string | null
}

export interface LicenseCardsPageData {
  items: LegacyLicenseCard[]
  total: number
  limit: number
  offset: number
  stats?: {
    total: number
    used: number
    unused: number
  }
}

export interface LicenseAuthorization {
  authorization_id: string
  user_id: number
  owner_username: string | null
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

export interface LegacyUser {
  id: number
  username: string | null
  email: string | null
  is_active: boolean
  created_at: string | null
  account_count: number
  authorization_count: number
  developer_app_id: number | null
  current_authorization: {
    start_at: string | null
    end_at: string | null
    status: string | null
  }
}

export interface LegacyUserAccount {
  account_id: string
  tg_user_id: number | null
  username: string | null
  first_name: string | null
  phone: string | null
  developer_app_id: number | null
  is_active: boolean
  is_banned: boolean
  health_status: string | null
  is_flooding: boolean
  messages_sent: number
  created_at: string | null
  authorization_id?: string | null
  authorization_status?: string | null
  authorization_end_at?: string | null
}

export interface AccountOption {
  account_id: string
  username: string | null
  phone: string | null
  tg_user_id: number | null
  owner_user_id: number
  owner_username: string | null
  label: string
}

export const adminLogin = (payload: {
  username: string
  password: string
}): Promise<{ success: boolean; data: { access_token: string; token_type: string } & AdminProfile }> =>
  adminApi.post('/admin-auth/login', payload)

export const adminMe = (): Promise<{ success: boolean; data: AdminProfile }> =>
  adminApi.get('/admin-auth/me')

export const adminLogout = (): Promise<{ success: boolean; message: string }> =>
  adminApi.post('/admin-auth/logout')

export const adminChangePassword = (payload: {
  current_password: string
  new_password: string
}): Promise<{ success: boolean; data: AdminProfile }> => adminApi.post('/admin-auth/change-password', payload)

export const adminIssueTgBindCode = (): Promise<{ success: boolean; data: { bind_code: string; expires_at: string; bot_username: string; bot_bind_url: string } }> =>
  adminApi.post('/admin-auth/tg-bind-code')

export const adminUnbindTg = (): Promise<{ success: boolean; message: string }> =>
  adminApi.post('/admin-auth/tg-unbind')

export const adminListPlans = (params?: {
  search?: string
  is_active?: boolean
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: PaginatedResponse<AgentPlan> }> =>
  adminApi.get('/agent/plans', { params })

export const adminListAccounts = (params?: {
  search?: string
  role_code?: string
  business_identity?: string
  status?: string
  parent_account_id?: number
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: PaginatedResponse<AgentAccount> }> =>
  adminApi.get('/agent/accounts', { params })

export const adminCreateMasterAgent = (provinceCode: string, payload: {
  username: string
  password: string
  display_name: string
  credit_limit_cents?: number
  is_credit_whitelisted?: boolean
  contact_name?: string
  contact_phone?: string
}): Promise<{ success: boolean; data: AgentAccount }> => adminApi.post(`/admin/provinces/${provinceCode}/master-agent`, payload)

export const adminCreateAgentAccount = (payload: {
  username: string
  password: string
  display_name: string
  settlement_mode: string
  credit_limit_cents?: number
  contact_name?: string
  contact_phone?: string
}): Promise<{ success: boolean; data: AgentAccount }> => adminApi.post('/agent/accounts', payload)

export const adminSetMasterCreditLimit = (
  accountId: number,
  payload: { credit_limit_cents: number; is_credit_whitelisted?: boolean }
): Promise<{ success: boolean; data: AgentAccount }> => adminApi.put(`/admin/accounts/${accountId}/credit-limit`, payload)

export const adminSetCreditWhitelist = (
  accountId: number,
  isCreditWhitelisted: boolean,
): Promise<{ success: boolean; data: AgentAccount }> => adminApi.put(`/admin/accounts/${accountId}/credit-whitelist`, {
  is_credit_whitelisted: isCreditWhitelisted,
})

export const adminSetSettlementMode = (
  accountId: number,
  settlementMode: string,
): Promise<{ success: boolean; data: AgentAccount }> => adminApi.put(`/agent/accounts/${accountId}/settlement-mode`, {
  settlement_mode: settlementMode,
})

export const adminSetChildCreditLimit = (
  accountId: number,
  creditLimitCents: number,
): Promise<{ success: boolean; data: AgentAccount }> => adminApi.put(`/agent/accounts/${accountId}/credit-limit`, {
  credit_limit_cents: creditLimitCents,
})

export const adminListPricingPlans = (params?: {
  search?: string
  is_active?: boolean
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: PaginatedResponse<AgentPlan> }> =>
  adminApi.get('/admin/pricing/plans', { params })

export const adminUpdatePricingPlan = (
  planCode: string,
  priceCents: number,
): Promise<{ success: boolean; data: AgentPlan }> =>
  adminApi.put(`/admin/pricing/plans/${encodeURIComponent(planCode)}`, {
    price_cents: priceCents,
  })

export const adminGenerateCardBatch = (payload: {
  plan_code: string
  quantity: number
  prefix?: string
  valid_days?: number | null
  funding_source: 'balance' | 'credit'
}): Promise<{ success: boolean; data: { batch: CardBatch; cards: AgentCard[]; copied_text: string } }> =>
  adminApi.post('/agent/card-batches/generate', payload)

export const adminListCardBatches = (params?: {
  plan_code?: string
  payment_status?: string
  settlement_status?: string
  keyword?: string
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: PaginatedResponse<CardBatch> }> =>
  adminApi.get('/agent/card-batches', { params })

export const adminListSelfFundLedgers = (params?: {
  biz_type?: string
  direction?: string
  keyword?: string
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: PaginatedResponse<FundLedger> }> =>
  adminApi.get('/agent/fund-ledgers', { params })

export const adminListVisibleFundLedgers = (params?: {
  biz_type?: string
  direction?: string
  keyword?: string
  limit?: number
  account_id?: number
  offset?: number
}): Promise<{ success: boolean; data: PaginatedResponse<FundLedger> }> =>
  adminApi.get('/admin/fund-ledgers', { params })

export const adminListCards = (params?: {
  plan_code?: string
  batch_id?: string
  status?: string
  source_type?: string
  keyword?: string
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: PaginatedResponse<AgentCard> }> =>
  adminApi.get('/agent/cards', { params })

export const adminExportCardsXlsx = (params?: {
  plan_code?: string
  batch_id?: string
  status?: string
  source_type?: string
  keyword?: string
}): Promise<Blob> =>
  adminApi.get('/agent/cards/export', { params, responseType: 'blob' })

export const adminCopyCards = (payload: {
  card_ids: number[]
  with_meta?: boolean
}): Promise<{ success: boolean; data: { count: number; copied_text: string } }> =>
  adminApi.post('/agent/cards/copy', payload)

export const adminCreateRechargeEntry = (payload: {
  amount_cents: number
  subject_account_id: number
  remark?: string
}): Promise<{ success: boolean; data: AgentAccount }> =>
  adminApi.post('/admin/fund-ledgers/recharge', payload)

export const adminSettleBatchDirect = (
  batchId: string,
): Promise<{ success: boolean; data: CardBatch }> =>
  adminApi.post(`/admin/card-batches/${encodeURIComponent(batchId)}/settle`)

export const adminListOperationLogs = (params?: {
  log_type?: string
  account_id?: number
  keyword?: string
  date_from?: string
  date_to?: string
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: PaginatedResponse<OperationLog> }> =>
  adminApi.get('/admin/operation-logs', { params })

export const adminListAuditLogs = (params?: {
  action?: string
  target_type?: string
  keyword?: string
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: PaginatedResponse<AdminAuditLog> }> =>
  adminApi.get('/agent/audit-logs', { params })

export const adminGetPurchaseSettings = (): Promise<{ success: boolean; data: PurchaseSettings }> =>
  adminApi.get('/admin/system/purchase-settings')

export const adminUpdatePurchaseSettings = (payload: PurchaseSettings): Promise<{ success: boolean; data: PurchaseSettings }> =>
  adminApi.put('/admin/system/purchase-settings', payload)

export const adminGetBotNoticeSettings = (): Promise<{ success: boolean; data: BotNoticeSettings }> =>
  adminApi.get('/admin/system/bot-notice')

export const adminUpdateBotNoticeSettings = (payload: {
  enabled: boolean
  entry_button_text: string
  message_text: string
  target_url: string
}): Promise<{ success: boolean; data: BotNoticeSettings }> =>
  adminApi.put('/admin/system/bot-notice', payload)

export const adminGetTodaySystemStats = (): Promise<{ success: boolean; data: SystemTodayStats }> =>
  adminApi.get('/admin/system/stats/today')

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
): Promise<{ success: boolean; data: Record<string, any> }> =>
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

export const adminCheckDeveloperApp = (appId: number): Promise<{ success: boolean; data: Record<string, any> }> =>
  adminApi.post(`/admin/developer-apps/${appId}/check`)

export const adminListSystemProxies = (params?: {
  search?: string
  is_healthy?: boolean
  is_assigned?: boolean
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: PaginatedResponse<LegacyProxy> }> =>
  adminApi.get('/admin/system-proxies', { params })

export const adminAddSystemProxy = (payload: {
  proxy_type: string
  host: string
  port: number
  username?: string
  password?: string
}): Promise<{ success: boolean; data: LegacyProxy }> =>
  adminApi.post('/admin/system-proxies', payload)

export const adminDeleteSystemProxy = (proxyId: number): Promise<{ success: boolean; message: string }> =>
  adminApi.delete(`/admin/system-proxies/${proxyId}`)

export const adminCheckSystemProxy = (proxyId: number): Promise<{ success: boolean; data: Record<string, any> }> =>
  adminApi.post(`/admin/system-proxies/${proxyId}/check`)

export const adminAssignSystemProxy = (proxyId: number, accountId: string): Promise<{ success: boolean; message: string }> =>
  adminApi.post(`/admin/system-proxies/${proxyId}/assign`, { account_id: accountId })

export const adminUnassignSystemProxy = (proxyId: number): Promise<{ success: boolean; message: string }> =>
  adminApi.post(`/admin/system-proxies/${proxyId}/unassign`)

export const adminListLicensePlans = (): Promise<{ success: boolean; data: AgentPlan[] }> =>
  adminApi.get('/admin/license-plans')

export const adminCreateLicensePlan = (payload: {
  plan_code: string
  display_name: string
  billing_cycle?: string
  price_cents: number
  duration_days: number
  is_active?: boolean
  sort_order?: number
}): Promise<{ success: boolean; data: AgentPlan }> =>
  adminApi.post('/admin/license-plans', payload)

export const adminUpdateLicensePlan = (
  planCode: string,
  payload: {
    display_name?: string
    billing_cycle?: string
    price_cents?: number
    duration_days?: number
    is_active?: boolean
    sort_order?: number
  },
): Promise<{ success: boolean; data: AgentPlan }> =>
  adminApi.put(`/admin/license-plans/${encodeURIComponent(planCode)}`, payload)

export const adminDeleteLicensePlan = (planCode: string): Promise<{ success: boolean; data: Record<string, any> }> =>
  adminApi.delete(`/admin/license-plans/${encodeURIComponent(planCode)}`)

export const adminGenerateLegacyCards = (payload: {
  plan_code: string
  quantity: number
  valid_days?: number
  prefix?: string
}): Promise<{ success: boolean; data: LegacyLicenseCard[] }> =>
  adminApi.post('/admin/license-cards/generate', payload)

export const adminListLicenseCards = (params?: {
  plan_code?: string
  is_used?: boolean
  is_active?: boolean
  keyword?: string
  sort_by?: string
  sort_order?: string
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: LicenseCardsPageData }> =>
  adminApi.get('/admin/license-cards', { params })

export const adminExportLicenseCards = (params?: {
  plan_code?: string
  is_used?: boolean
  is_active?: boolean
}): Promise<Blob> =>
  adminApi.get('/admin/license-cards/export', { params, responseType: 'blob' })

export const adminEnableLicenseCard = (cardCode: string): Promise<{ success: boolean; data: LegacyLicenseCard }> =>
  adminApi.post(`/admin/license-cards/${encodeURIComponent(cardCode)}/enable`)

export const adminDisableLicenseCard = (cardCode: string): Promise<{ success: boolean; data: LegacyLicenseCard }> =>
  adminApi.post(`/admin/license-cards/${encodeURIComponent(cardCode)}/disable`)

export const adminListLicenseSlots = (params?: {
  status?: string
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: PaginatedResponse<LicenseAuthorization> }> =>
  adminApi.get('/admin/license-slots', { params })

export const adminListUsers = (params?: {
  search?: string
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: PaginatedResponse<LegacyUser> }> =>
  adminApi.get('/admin/users', { params })

export const adminListUserAccounts = (userId: number): Promise<{ success: boolean; data: LegacyUserAccount[] }> =>
  adminApi.get(`/admin/users/${userId}/accounts`)

export const adminResetUserPassword = (userId: number, newPassword: string): Promise<{ success: boolean; message: string }> =>
  adminApi.post(`/admin/users/${userId}/reset-password`, { new_password: newPassword })

export const adminSetUserDeveloperApp = (userId: number, developerAppId: number | null): Promise<{ success: boolean; data: Record<string, any> }> =>
  adminApi.put(`/admin/users/${userId}/developer-app`, { developer_app_id: developerAppId })

export const adminListAccountOptions = (params?: {
  search?: string
  limit?: number
}): Promise<{ success: boolean; data: AccountOption[] }> =>
  adminApi.get('/admin/accounts/options', { params })

export const adminDeleteManagedAccount = (accountId: string): Promise<{ success: boolean; message: string }> =>
  adminApi.delete(`/admin/accounts/${encodeURIComponent(accountId)}`)

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

export const adminListRbacPermissions = (): Promise<{ success: boolean; data: { items: AdminPermission[]; total: number } }> =>
  adminApi.get('/admin/rbac/permissions')

export const adminListRbacRoles = (): Promise<{ success: boolean; data: { items: AdminRole[]; total: number } }> =>
  adminApi.get('/admin/rbac/roles')

export const adminCreateRbacRole = (payload: {
  role_key: string
  display_name: string
  description?: string
}): Promise<{ success: boolean; data: AdminRole }> =>
  adminApi.post('/admin/rbac/roles', payload)

export const adminUpdateRbacRole = (
  roleId: number,
  payload: {
    display_name?: string
    description?: string
    status?: string
  },
): Promise<{ success: boolean; data: AdminRole }> =>
  adminApi.put(`/admin/rbac/roles/${roleId}`, payload)

export const adminUpdateRbacRolePermissions = (
  roleId: number,
  permissionCodes: string[],
): Promise<{ success: boolean; data: AdminRole }> =>
  adminApi.put(`/admin/rbac/roles/${roleId}/permissions`, { permission_codes: permissionCodes })

export const adminListAdminAccounts = (params?: {
  search?: string
  status?: string
  role_key?: string
  account_type?: string
  business_identity?: string
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: PaginatedResponse<AgentAccount> }> =>
  adminApi.get('/admin/admin-accounts', { params })

export const adminCreateAdminAccount = (payload: {
  username: string
  password: string
  display_name: string
  role_keys: string[]
  contact_name?: string
  contact_phone?: string
}): Promise<{ success: boolean; data: AgentAccount }> =>
  adminApi.post('/admin/admin-accounts', payload)

export const adminUpdateAdminAccount = (
  accountId: number,
  payload: {
    display_name?: string
    status?: string
    contact_name?: string
    contact_phone?: string
  },
): Promise<{ success: boolean; data: AgentAccount }> =>
  adminApi.put(`/admin/admin-accounts/${accountId}`, payload)

export const adminUpdateAdminAccountRoles = (
  accountId: number,
  roleKeys: string[],
): Promise<{ success: boolean; data: AgentAccount }> =>
  adminApi.put(`/admin/admin-accounts/${accountId}/roles`, { role_keys: roleKeys })

export const adminResetAdminAccountPassword = (
  accountId: number,
  newPassword: string,
): Promise<{ success: boolean; data: { account_id: number; username: string; force_password_change: boolean } }> =>
  adminApi.post(`/admin/admin-accounts/${accountId}/reset-password`, { new_password: newPassword })
