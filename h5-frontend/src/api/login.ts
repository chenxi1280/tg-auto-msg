/**
 * 登录相关 API
 */
import request from './request'
import type { ApiResponse } from './request'

/**
 * 登录状态枚举
 */
export enum LoginStatus {
  PENDING = 'pending',
  SCANNING = 'scanning',
  CONFIRMED = 'confirmed',
  EXPIRED = 'expired',
  ERROR = 'error'
}

/**
 * 登录会话接口
 */
export interface LoginSession {
  login_id: string
  qr_url: string
  expires_at: string
}

/**
 * 登录状态响应
 */
export interface LoginStatusResponse {
  status: LoginStatus
  qr_url?: string
  bind_code?: string
  tg_user_id?: number
  username?: string
  error?: string
}

/**
 * 创建登录会话
 */
export const createLoginSession = (): Promise<ApiResponse<LoginSession>> => {
  return request.post('/login/create')
}

/**
 * 获取登录状态
 */
export const getLoginStatus = (loginId: string): Promise<ApiResponse<LoginStatusResponse>> => {
  return request.get('/login/status', { params: { login_id: loginId } })
}

/**
 * 检查 Userbot 登录状态
 */
export const checkLoginStatus = (): Promise<ApiResponse<{ is_logged_in: boolean }>> => {
  return request.get('/login/check')
}
