import { adminApi } from './client'
import type { AdminRole, AdminPermission } from './types'

export const adminListRbacPermissions = (): Promise<{ success: boolean; data: { items: AdminPermission[]; total: number } }> =>
  adminApi.get('/admin/rbac/permissions')

export const adminListRbacRoles = (): Promise<{ success: boolean; data: { items: AdminRole[]; total: number } }> =>
  adminApi.get('/admin/rbac/roles')

export const adminCreateRbacRole = (payload: {
  role_key: string
  display_name: string
  description?: string
}): Promise<{ success: boolean; data: AdminRole }> =>
  adminApi.post('/admin/rbac/roles', payload)

export const adminUpdateRbacRole = (
  roleId: number,
  payload: {
    display_name?: string
    description?: string
    status?: string
  },
): Promise<{ success: boolean; data: AdminRole }> =>
  adminApi.put(`/admin/rbac/roles/${roleId}`, payload)

export const adminUpdateRbacRolePermissions = (
  roleId: number,
  permissionCodes: string[],
): Promise<{ success: boolean; data: AdminRole }> =>
  adminApi.put(`/admin/rbac/roles/${roleId}/permissions`, { permission_codes: permissionCodes })
