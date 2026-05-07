import { adminApi } from './client'
import type {
  AdminProfile,
  AgentAccount,
  AccountOption,
  AdminAccountResetResult,
  PaginatedResponse,
} from './types'

// ── Auth / Session ───────────────────────────────────────────────────────────

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
}): Promise<{ success: boolean; data: AdminProfile }> =>
  adminApi.post('/admin-auth/change-password', payload)

// ── Agent Accounts ───────────────────────────────────────────────────────────

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

export const adminCreateMasterAgent = (
  provinceCode: string,
  payload: {
    username: string
    password: string
    display_name: string
    credit_limit_cents?: number
    is_credit_whitelisted?: boolean
    contact_name?: string
    contact_phone?: string
  },
): Promise<{ success: boolean; data: AgentAccount }> =>
  adminApi.post(`/admin/provinces/${provinceCode}/master-agent`, payload)

export const adminCreateAgentAccount = (payload: {
  username: string
  password: string
  display_name: string
  settlement_mode: string
  credit_limit_cents?: number
  contact_name?: string
  contact_phone?: string
}): Promise<{ success: boolean; data: AgentAccount }> =>
  adminApi.post('/agent/accounts', payload)

export const adminSetMasterCreditLimit = (
  accountId: number,
  payload: { credit_limit_cents: number; is_credit_whitelisted?: boolean },
): Promise<{ success: boolean; data: AgentAccount }> =>
  adminApi.put(`/admin/accounts/${accountId}/credit-limit`, payload)

export const adminSetCreditWhitelist = (
  accountId: number,
  isCreditWhitelisted: boolean,
): Promise<{ success: boolean; data: AgentAccount }> =>
  adminApi.put(`/admin/accounts/${accountId}/credit-whitelist`, {
    is_credit_whitelisted: isCreditWhitelisted,
  })

export const adminSetSettlementMode = (
  accountId: number,
  settlementMode: string,
): Promise<{ success: boolean; data: AgentAccount }> =>
  adminApi.put(`/agent/accounts/${accountId}/settlement-mode`, {
    settlement_mode: settlementMode,
  })

export const adminSetChildCreditLimit = (
  accountId: number,
  creditLimitCents: number,
): Promise<{ success: boolean; data: AgentAccount }> =>
  adminApi.put(`/agent/accounts/${accountId}/credit-limit`, {
    credit_limit_cents: creditLimitCents,
  })

export const adminListAccountOptions = (params?: {
  search?: string
  limit?: number
}): Promise<{ success: boolean; data: AccountOption[] }> =>
  adminApi.get('/admin/accounts/options', { params })

export const adminDeleteManagedAccount = (accountId: string): Promise<{ success: boolean; message: string }> =>
  adminApi.delete(`/admin/accounts/${encodeURIComponent(accountId)}`)

// ── Admin (Staff) Accounts ───────────────────────────────────────────────────

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
): Promise<{ success: boolean; data: AdminAccountResetResult }> =>
  adminApi.post(`/admin/admin-accounts/${accountId}/reset-password`, { new_password: newPassword })
