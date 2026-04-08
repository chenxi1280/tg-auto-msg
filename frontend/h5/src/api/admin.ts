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
    ElMessage.error(message)
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

export interface AdminProfileAccount {
  id: number
  username: string
  display_name: string
  role_code: string
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
  balance_cents: number
  force_password_change: boolean
  contact_name: string | null
  contact_phone: string | null
  last_login_at: string | null
  created_at: string | null
  updated_at: string | null
  tg_binding: AdminBindingInfo
}

export interface AdminProfile {
  account: AdminProfileAccount
  visible_account_count: number
  province_code: string
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

export interface CardBatch {
  batch_id: string
  province_code: string
  creator_account_id: number
  owner_account_id: number
  direct_parent_account_id: number | null
  root_master_account_id: number | null
  current_liability_account_id: number | null
  current_counterparty_account_id: number | null
  plan_code: string
  quantity: number
  duration_days: number
  unit_price_cents: number
  total_amount_cents: number
  settlement_status: string
  payment_status: string
  export_count: number
  last_exported_at: string | null
  remark: string | null
  created_at: string | null
}

export interface AgentCard {
  id: number
  card_code: string
  plan_code: string | null
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

export interface ApprovalRequest {
  request_id: string
  province_code: string
  request_type: string
  requester_account_id: number
  subject_account_id: number
  approver_account_id: number
  status: string
  amount_cents: number | null
  credit_delta_cents: number | null
  payload_json: Record<string, any>
  approved_at: string | null
  rejected_at: string | null
  created_at: string | null
  updated_at: string | null
}

export interface BatchApprovalResult {
  decision: string
  success_count: number
  failed_count: number
  success_items: Array<{ request_id: string; result: ApprovalRequest }>
  failed_items: Array<{ request_id: string; detail: string }>
}

export interface AdminAuditLog {
  id: number
  actor: string
  action: string
  target_type: string | null
  target_id: string | null
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

export const adminListPlans = (): Promise<{ success: boolean; data: AgentPlan[] }> =>
  adminApi.get('/agent/plans')

export const adminListAccounts = (): Promise<{ success: boolean; data: AgentAccount[] }> =>
  adminApi.get('/agent/accounts')

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

export const adminListPricingPlans = (): Promise<{ success: boolean; data: AgentPlan[] }> =>
  adminApi.get('/admin/pricing/plans')

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

export const adminListCardBatches = (): Promise<{ success: boolean; data: CardBatch[] }> =>
  adminApi.get('/agent/card-batches')

export const adminListSelfFundLedgers = (limit = 200): Promise<{ success: boolean; data: FundLedger[] }> =>
  adminApi.get('/agent/fund-ledgers', { params: { limit } })

export const adminListVisibleFundLedgers = (params?: {
  limit?: number
  account_id?: number
}): Promise<{ success: boolean; data: FundLedger[] }> =>
  adminApi.get('/admin/fund-ledgers', { params })

export const adminListCards = (params?: {
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: { items: AgentCard[]; total: number; limit: number; offset: number } }> =>
  adminApi.get('/agent/cards', { params })

export const adminExportCardsXlsx = (): Promise<Blob> =>
  adminApi.get('/agent/cards/export', { responseType: 'blob' })

export const adminCopyCards = (payload: {
  card_ids: number[]
  with_meta?: boolean
}): Promise<{ success: boolean; data: { count: number; copied_text: string } }> =>
  adminApi.post('/agent/cards/copy', payload)

export const adminCreateRechargeRequest = (payload: {
  amount_cents: number
  subject_account_id?: number
  payload_json?: Record<string, any>
}): Promise<{ success: boolean; data: ApprovalRequest }> =>
  adminApi.post('/agent/approval-requests/recharge', { request_type: 'recharge', ...payload })

export const adminCreateSettlementRequest = (payload: {
  amount_cents?: number
  subject_account_id?: number
  payload_json?: Record<string, any>
}): Promise<{ success: boolean; data: ApprovalRequest }> =>
  adminApi.post('/agent/approval-requests/settlement', { request_type: 'settlement', ...payload })

export const adminCreateCreditAdjustRequest = (payload: {
  credit_delta_cents?: number
  subject_account_id?: number
  payload_json?: Record<string, any>
}): Promise<{ success: boolean; data: ApprovalRequest }> =>
  adminApi.post('/agent/approval-requests/credit-adjust', { request_type: 'credit_adjust', ...payload })

export const adminCreateBatchPurchaseRequest = (payload: {
  subject_account_id?: number
  payload_json?: Record<string, any>
}): Promise<{ success: boolean; data: ApprovalRequest }> =>
  adminApi.post('/agent/approval-requests/batch-purchase', { request_type: 'batch_purchase', ...payload })

export const adminListPendingApprovals = (): Promise<{ success: boolean; data: ApprovalRequest[] }> =>
  adminApi.get('/agent/approval-requests/pending')

export const adminListApprovalRequests = (params?: {
  status?: string
  request_type?: string
  limit?: number
}): Promise<{ success: boolean; data: ApprovalRequest[] }> =>
  adminApi.get('/agent/approval-requests', { params })

export const adminApproveRequest = (requestId: string): Promise<{ success: boolean; data: ApprovalRequest }> =>
  adminApi.post(`/agent/approval-requests/${encodeURIComponent(requestId)}/approve`)

export const adminRejectRequest = (requestId: string): Promise<{ success: boolean; data: ApprovalRequest }> =>
  adminApi.post(`/agent/approval-requests/${encodeURIComponent(requestId)}/reject`)

export const adminBatchApproveRequests = (requestIds: string[]): Promise<{ success: boolean; data: BatchApprovalResult }> =>
  adminApi.post('/agent/approval-requests/batch-approve', { request_ids: requestIds })

export const adminBatchRejectRequests = (requestIds: string[]): Promise<{ success: boolean; data: BatchApprovalResult }> =>
  adminApi.post('/agent/approval-requests/batch-reject', { request_ids: requestIds })

export const adminListAuditLogs = (limit = 200): Promise<{ success: boolean; data: AdminAuditLog[] }> =>
  adminApi.get('/agent/audit-logs', { params: { limit } })
