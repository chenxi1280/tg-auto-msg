/**
 * 账号相关 API
 */
import request from './request'
import type { ApiResponse } from './request'

const ACCOUNT_SYNC_REQUEST_TIMEOUT_MS = 285_000

export type AccountSyncStatus = 'enqueued' | 'reprioritized' | 'queued' | 'running' | 'completed'

export interface AccountSyncResult {
  account_id: string
  user_id: number
  trigger_source: string
  profile_sync_ok: boolean
  resource_sync_ok: boolean
  resource_synced_count: number
  error?: string | null
}

export interface AccountSyncBatchResult {
  queued_accounts: number
  reprioritized_accounts: number
  already_running_accounts: number
  total_accounts: number
}

export interface AccountSyncResponse extends Omit<ApiResponse<AccountSyncResult | AccountSyncBatchResult>, 'data'> {
  data?: AccountSyncResult | AccountSyncBatchResult
  status: AccountSyncStatus
  already_running?: boolean
}

/**
 * 账号接口
 */
export interface Account {
  account_id: string
  username: string | null
  first_name: string | null
  phone: string | null
  developer_app_id?: number | null
  is_active: boolean
  is_banned: boolean
  health_status: 'online' | 'offline' | 'banned'
  developer_app_version?: number
  reauth_required?: boolean
  reauth_reason?: string | null
  reauth_required_at?: string | null
  is_flooding: boolean
  flood_until: string | null
  messages_sent: number
  last_used_at: string | null
  created_at: string | null
  authorization_status?: 'licensed' | 'unlicensed' | 'expired'
  can_create_tasks?: boolean
  authorization_end_at?: string | null
  authorization_card_count?: number
  authorization_id?: string | null
  has_active_authorization?: boolean
  authorization_grant_source?: string | null
  authorization_grant_source_label?: string | null
  authorization_remaining_days?: number | null
  can_renew_authorization?: boolean
}

/**
 * 获取账号列表
 */
export const getAccounts = (
  userId?: number,
  probe = false
): Promise<ApiResponse<Account[]>> => {
  return request.get('/accounts/', {
    params: { probe }
  })
}

/**
 * 同步账号资源
 */
export const syncAccountResources = (
  accountId: string,
  wait = false
): Promise<AccountSyncResponse> => {
  return request.post(`/accounts/${accountId}/sync`, null, {
    params: { wait },
    timeout: ACCOUNT_SYNC_REQUEST_TIMEOUT_MS
  })
}

export const syncAllAccountResources = (
  wait = false
): Promise<AccountSyncResponse> => {
  return request.post('/accounts/sync-all', null, {
    params: { wait },
    timeout: ACCOUNT_SYNC_REQUEST_TIMEOUT_MS
  })
}

/**
 * 获取账号资源列表
 */
export const getAccountResources = (
  accountId: string,
  params?: {
    peer_type?: string
    is_active?: boolean
    search?: string
  }
): Promise<ApiResponse<any[]>> => {
  return request.get(`/accounts/${accountId}/resources`, { params })
}

/**
 * 禁用账号
 */
export const disableAccount = (accountId: string): Promise<ApiResponse<{ message: string }>> => {
  return request.post(`/accounts/${accountId}/disable`)
}

/**
 * 启用账号
 */
export const enableAccount = (accountId: string): Promise<ApiResponse<{ message: string }>> => {
  return request.post(`/accounts/${accountId}/enable`)
}

/**
 * 删除账号
 */
export const deleteAccount = (accountId: string): Promise<ApiResponse<{ message: string }>> => {
  return request.delete(`/accounts/${accountId}`)
}

export interface RenewAuthorizationResponse {
  authorization_id: string
  account_id: string | null
  status: string
  end_at: string | null
  authorization_status: string
  can_create_tasks: boolean
  authorization_card_count: number
}

export const renewAccountAuthorization = (
  accountId: string,
  cardCode: string,
): Promise<ApiResponse<RenewAuthorizationResponse>> => {
  return request.post(`/accounts/${accountId}/renew-authorization`, {
    card_code: cardCode,
  })
}
