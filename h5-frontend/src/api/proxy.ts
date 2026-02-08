/**
 * 代理相关 API
 */
import request from './request'
import type { ApiResponse } from './request'

/**
 * 代理接口
 */
export interface Proxy {
  proxy_id: number
  proxy_type: 'socks5' | 'http' | 'mtproto'
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

/**
 * 代理类型枚举
 */
export enum ProxyType {
  SOCKS5 = 'socks5',
  HTTP = 'http',
  MTPROTO = 'mtproto'
}

/**
 * 获取代理列表
 */
export const getProxies = (): Promise<ApiResponse<Proxy[]>> => {
  return request.get('/proxies/')
}

/**
 * 添加代理
 */
export const addProxy = (data: {
  proxy_type: string
  host: string
  port: number
  username?: string
  password?: string
}): Promise<ApiResponse<{ proxy_id: number; proxy_type: string; host: string; port: number }>> => {
  return request.post('/proxies/', data)
}

/**
 * 检查代理健康状态
 */
export const checkProxyHealth = (proxyId: number): Promise<ApiResponse<{ is_healthy: boolean; response_time_ms: number }>> => {
  return request.post(`/proxies/${proxyId}/check`)
}

/**
 * 删除代理
 */
export const deleteProxy = (proxyId: number): Promise<ApiResponse<{ message: string }>> => {
  return request.delete(`/proxies/${proxyId}`)
}

/**
 * 分配代理给账号
 */
export const assignProxy = (proxyId: number, accountId: string): Promise<ApiResponse<{ message: string }>> => {
  return request.post(`/proxies/${proxyId}/assign`, null, { params: { account_id: accountId } })
}

/**
 * 解绑代理
 */
export const unassignProxy = (proxyId: number): Promise<ApiResponse<{ message: string }>> => {
  return request.post(`/proxies/${proxyId}/unassign`)
}
