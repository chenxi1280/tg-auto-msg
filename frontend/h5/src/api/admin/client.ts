import axios, { type AxiosInstance } from 'axios'
import { ElMessage } from 'element-plus'

const ADMIN_ACCESS_TOKEN_KEY = 'admin_access_token'

const adminApi: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 30000,
})

const clearAdminStorage = () => {
  localStorage.removeItem(ADMIN_ACCESS_TOKEN_KEY)
}

const showAdminErrorMessage = (message: string) => {
  ElMessage.error(message)
}

adminApi.interceptors.request.use((config) => {
  const token = localStorage.getItem(ADMIN_ACCESS_TOKEN_KEY) || ''
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

adminApi.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const status = error?.response?.status
    const message = error?.response?.data?.detail || error?.message || '请求失败'
    if (status === 401) {
      clearAdminStorage()
      if (window.location.pathname !== '/admin/login') {
        window.location.href = '/admin/login'
      }
    }
    showAdminErrorMessage(message)
    return Promise.reject(error)
  },
)

export const getAdminAccessToken = (): string => localStorage.getItem(ADMIN_ACCESS_TOKEN_KEY) || ''
export const setAdminAccessToken = (token: string) => localStorage.setItem(ADMIN_ACCESS_TOKEN_KEY, token)
export const clearAdminAccessToken = clearAdminStorage
export const hasAdminSession = (): boolean => Boolean(getAdminAccessToken())

export { adminApi }
