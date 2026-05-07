import { adminApi } from './client'
import type { LegacyUser, LegacyUserAccount, LicenseAuthorization, PaginatedResponse } from './types'

export const adminListUsers = (params?: {
  search?: string
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: PaginatedResponse<LegacyUser> }> =>
  adminApi.get('/admin/users', { params })

export const adminListUserAccounts = (userId: number): Promise<{ success: boolean; data: LegacyUserAccount[] }> =>
  adminApi.get(`/admin/users/${userId}/accounts`)

export const adminResetUserPassword = (userId: number, newPassword: string): Promise<{ success: boolean; message: string }> =>
  adminApi.post(`/admin/users/${userId}/reset-password`, { new_password: newPassword })

export const adminSetUserDeveloperApp = (userId: number, developerAppId: number | null): Promise<{ success: boolean; data: Record<string, unknown> }> =>
  adminApi.put(`/admin/users/${userId}/developer-app`, { developer_app_id: developerAppId })

export const adminListLicenseSlots = (params?: {
  status?: string
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: PaginatedResponse<LicenseAuthorization> }> =>
  adminApi.get('/admin/license-slots', { params })
