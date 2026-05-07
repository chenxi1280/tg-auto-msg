import { adminApi } from './client'
import type { AgentPlan, PaginatedResponse } from './types'

// ── Agent Pricing Plans ──────────────────────────────────────────────────────

export const adminListPlans = (params?: {
  search?: string
  is_active?: boolean
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: PaginatedResponse<AgentPlan> }> =>
  adminApi.get('/agent/plans', { params })

export const adminListPricingPlans = (params?: {
  search?: string
  is_active?: boolean
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: PaginatedResponse<AgentPlan> }> =>
  adminApi.get('/admin/pricing/plans', { params })

export const adminUpdatePricingPlan = (
  planCode: string,
  priceCents: number,
): Promise<{ success: boolean; data: AgentPlan }> =>
  adminApi.put(`/admin/pricing/plans/${encodeURIComponent(planCode)}`, {
    price_cents: priceCents,
  })

// ── License Plans ────────────────────────────────────────────────────────────

export const adminListLicensePlans = (): Promise<{ success: boolean; data: AgentPlan[] }> =>
  adminApi.get('/admin/license-plans')

export const adminCreateLicensePlan = (payload: {
  plan_code: string
  display_name: string
  billing_cycle?: string
  price_cents: number
  duration_days: number
  is_active?: boolean
  sort_order?: number
}): Promise<{ success: boolean; data: AgentPlan }> =>
  adminApi.post('/admin/license-plans', payload)

export const adminUpdateLicensePlan = (
  planCode: string,
  payload: {
    display_name?: string
    billing_cycle?: string
    price_cents?: number
    duration_days?: number
    is_active?: boolean
    sort_order?: number
  },
): Promise<{ success: boolean; data: AgentPlan }> =>
  adminApi.put(`/admin/license-plans/${encodeURIComponent(planCode)}`, payload)

export const adminDeleteLicensePlan = (planCode: string): Promise<{ success: boolean; data: Record<string, unknown> }> =>
  adminApi.delete(`/admin/license-plans/${encodeURIComponent(planCode)}`)
