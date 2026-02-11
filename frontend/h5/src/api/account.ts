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
  is_active: boolean
  is_banned: boolean
  health_status: 'online' | 'offline' | 'banned'
  is_flooding: boolean
  flood_until: string | null
  messages_sent: number
  last_used_at: string | null
  created_at: string | null
  bind_code: string | null
  bind_code_expires_at: string | null
}

/**
 * 获取账号列表
 */
export const getAccounts = (userId?: number): Promise<ApiResponse<Account[]>> => {
  return request.get('/accounts/')
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

export interface AccountBindCode {
  bind_code: string
  expires_at: string | null
  ttl_seconds: number
}

export const refreshAccountBindCode = (
  accountId: string,
  refresh = true
): Promise<ApiResponse<AccountBindCode>> => {
  return request.post(`/accounts/${accountId}/bind-code`, null, {
    params: { refresh }
  })
}
