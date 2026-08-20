/**
 * Axios 请求封装
 */
import axios, { type AxiosInstance, type AxiosError, type InternalAxiosRequestConfig, type AxiosResponse } from 'axios'
import { ElMessage } from 'element-plus'

// 请求响应接口
export interface ApiResponse<T = unknown> {
  success: boolean
  data: T
  message?: string
  error?: string
  detail?: string | { code?: string; message?: string }
}

const errorText = (data?: ApiResponse) => {
  if (typeof data?.detail === 'string') return data.detail
  if (data?.detail && typeof data.detail === 'object') {
    const code = data.detail.code ? `${data.detail.code}：` : ''
    return `${code}${data.detail.message || '请求失败'}`
  }
  return data?.message || data?.error || '请求失败'
}

// 创建 axios 实例
const api: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 30000
})

const clearAuthStorage = () => {
  localStorage.removeItem('token')
  localStorage.removeItem('user_id')
  localStorage.removeItem('username')
}

// 请求拦截器
api.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // 从 localStorage 获取 token
    const token = localStorage.getItem('token')
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error: AxiosError) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
// 注意：拦截器将 AxiosResponse<ApiResponse<T>> 解包为 ApiResponse<T>，
// 调用方直接拿到 ApiResponse 而非 AxiosResponse。
api.interceptors.response.use(
  (response: AxiosResponse<ApiResponse>) => {
    const { data } = response

    // 检查业务状态码
    if (data.success === false) {
      ElMessage.error(data.message || data.error || '请求失败')
      return Promise.reject(new Error(data.message || data.error || '请求失败'))
    }

    // 返回 response.data，这样调用方可以直接获取 data 字段
    return data as unknown as AxiosResponse
  },
  (error: AxiosError<ApiResponse>) => {
    const { response } = error

    if (response) {
      const { status, data } = response
      const reqUrl = error.config?.url || ''
      const isAuthLogin = reqUrl.includes('/auth/login')

      switch (status) {
        case 400:
          ElMessage.error(errorText(data) || '请求参数错误')
          break
        case 401:
          if (isAuthLogin) {
            ElMessage.error(errorText(data) || '用户名或密码错误')
          } else {
            ElMessage.error(errorText(data) || '未授权，请重新登录')
            clearAuthStorage()

            if (!window.location.pathname.startsWith('/login')) {
              const redirect = encodeURIComponent(window.location.pathname + window.location.search)
              window.location.href = `/login?redirect=${redirect}`
            }
          }
          break
        case 403:
          ElMessage.error(errorText(data) || '无权访问')
          break
        case 404:
          ElMessage.error(errorText(data) || '请求的资源不存在')
          break
        case 500:
          ElMessage.error(errorText(data) || '服务器错误')
          break
        default:
          ElMessage.error(errorText(data) || `请求失败 (${status})`)
      }
    } else if (error.code === 'ECONNABORTED') {
      ElMessage.error('请求超时，请稍后重试')
    } else {
      ElMessage.error('网络错误，请检查网络连接')
    }

    return Promise.reject(error)
  }
)

export default api
