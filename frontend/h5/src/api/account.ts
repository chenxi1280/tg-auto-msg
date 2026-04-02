/**
 * 账号相关 API
 */
import request from './request'
import type { ApiResponse } from './request'

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
  license_status?: 'licensed' | 'unlicensed' | 'expired'
  can_create_tasks?: boolean
  license_end_at?: string | null
  license_key_count?: number
  slot_id?: string | null
  has_active_slot?: boolean
  slot_end_at?: string | null
  slot_grant_source?: string | null
  slot_grant_source_label?: string | null
  slot_remaining_days?: number | null
  can_renew_slot?: boolean
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
): Promise<ApiResponse<{ message: string; data?: Record<string, any> }>> => {
  return request.post(`/accounts/${accountId}/sync`, null, {
    params: { wait }
  })
}

export const syncAllAccountResources = (
  wait = false
): Promise<(ApiResponse<{ data?: Record<string, any> }> & { already_running?: boolean })> => {
  return request.post('/accounts/sync-all', null, {
    params: { wait }
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

export interface BindSlotResponse {
  slot_id: string
  account_id: string | null
  status: string
  end_at: string | null
  license_status: string
  can_create_tasks: boolean
}

export const bindAccountSlot = (
  accountId: string,
  slotId: string,
): Promise<ApiResponse<BindSlotResponse>> => {
  return request.post(`/accounts/${accountId}/bind-slot`, {
    slot_id: slotId,
  })
}

export interface RenewSlotResponse extends BindSlotResponse {
  license_key_count: number
}

export const renewAccountSlot = (
  accountId: string,
  cardCode: string,
): Promise<ApiResponse<RenewSlotResponse>> => {
  return request.post(`/accounts/${accountId}/renew-slot`, {
    card_code: cardCode,
  })
}
