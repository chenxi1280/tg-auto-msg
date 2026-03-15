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
  PASSWORD_REQUIRED = 'password_required',
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
  password_hint?: string
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

/**
 * 绑定账号响应接口
 */
export interface BindAccountResponse {
  token: string
  user_id: number
  username: string
}

export interface SubmitPasswordResponse {
  bind_code: string
  tg_user_id: number
  username: string
}

/**
 * 验证绑定码并获取 token
 */
export const bindAccount = (bindCode: string): Promise<ApiResponse<BindAccountResponse>> => {
  return request.post('/login/bind', { bind_code: bindCode })
}

export const submitLoginPassword = (
  loginId: string,
  password: string
): Promise<ApiResponse<SubmitPasswordResponse>> => {
  return request.post('/login/password', {
    login_id: loginId,
    password
  })
}

/**
 * 获取已登录 userbot 的 token
 */
export const getExistingToken = (): Promise<ApiResponse<BindAccountResponse>> => {
  return request.get('/login/get-token')
}
