/**
 * 系统用户认证 API
 */
import request from './request'
import type { ApiResponse } from './request'

/**
 * 用户信息接口
 */
export interface User {
  id: number
  username: string
  email?: string
  is_active: boolean
  created_at: string
}

/**
 * 认证响应接口 (包含 Token 和 用户信息)
 */
export interface AuthResponse {
  access_token: string
  token_type: string
  user: User
}

/**
 * 注册请求参数
 */
export interface RegisterRequest {
  username: string
  password: string
  email?: string
}

/**
 * 登录请求参数 (OAuth2 密码模式)
 * 注意：FastAPI OAuth2PasswordRequestForm 需要 form-data 格式，
 * 但通常前端库会处理，或者我们可以直接传 JSON 如果后端做了兼容。
 * 我们的后端使用的是 OAuth2PasswordRequestForm，所以需要传 FormData。
 */
export interface LoginRequest {
  username: string
  password: string
}

/**
 * 注册
 */
export const register = (data: RegisterRequest): Promise<ApiResponse<AuthResponse>> => {
  return request.post('/auth/register', data)
}

/**
 * 登录
 * 使用 form-data 格式发送数据
 */
export const login = (data: LoginRequest): Promise<ApiResponse<AuthResponse>> => {
  const params = new URLSearchParams()
  params.append('username', data.username)
  params.append('password', data.password)

  return request.post('/auth/login', params, {
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded'
    }
  })
}

/**
 * 获取当前用户信息
 */
export const getMe = (): Promise<ApiResponse<User>> => {
  return request.get('/auth/me')
}

/**
 * 登出
 */
export const logout = (): Promise<ApiResponse<any>> => {
  return request.post('/auth/logout')
}
