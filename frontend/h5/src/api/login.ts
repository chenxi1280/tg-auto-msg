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
  PHONE_INPUT_REQUIRED = 'phone_input_required',
  CODE_INPUT_REQUIRED = 'code_input_required',
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
  phone_number?: string
  tg_user_id?: number
  username?: string
  bot_bind_url?: string
  bot_username?: string
  password_hint?: string
  error?: string
  trial_authorization?: LoginTrialAuthorization | null
}

export interface LoginTrialAuthorization {
  authorization_id: string
  end_at: string | null
  grant_source?: string | null
}

/**
 * 创建登录会话
 */
export const createLoginSession = (): Promise<ApiResponse<LoginSession>> => {
  return request.post('/login/create')
}

export interface PhoneLoginSession {
  login_id: string
  expires_at: string
  status: LoginStatus
}

export const createPhoneLoginSession = (): Promise<ApiResponse<PhoneLoginSession>> => {
  return request.post('/login/phone/create')
}

/**
 * 获取登录状态
 */
export const getLoginStatus = (loginId: string): Promise<ApiResponse<LoginStatusResponse>> => {
  return request.get('/login/status', { params: { login_id: loginId } })
}

export interface PhoneSendCodeResponse {
  login_id: string
  status: LoginStatus
  phone_number: string
}

export const sendPhoneLoginCode = (
  loginId: string,
  phoneNumber: string
): Promise<ApiResponse<PhoneSendCodeResponse>> => {
  return request.post('/login/phone/send-code', {
    login_id: loginId,
    phone_number: phoneNumber
  })
}

export interface PhoneSubmitCodeResponse extends SubmitPasswordResponse {
  status: LoginStatus
  password_hint?: string
}

export const submitPhoneLoginCode = (
  loginId: string,
  code: string
): Promise<ApiResponse<PhoneSubmitCodeResponse>> => {
  return request.post('/login/phone/code', {
    login_id: loginId,
    code
  })
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
export interface SubmitPasswordResponse {
  tg_user_id: number
  username: string
  bot_bind_url: string
  bot_username: string
  trial_authorization?: LoginTrialAuthorization | null
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
export const getExistingToken = (): Promise<ApiResponse<DeprecatedLoginTokenResponse>> => {
  return request.get('/login/get-token')
}

export interface BotBindLinkResponse {
  bot_username: string
  bind_token: string
  bot_bind_url: string
}

export const createBotBindLink = (): Promise<ApiResponse<BotBindLinkResponse>> => {
  return request.post('/login/bot-bind-link')
}
export interface DeprecatedLoginTokenResponse {
  token: string
  user_id: number
  username: string
}
