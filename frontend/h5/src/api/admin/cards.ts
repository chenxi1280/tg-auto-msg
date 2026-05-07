import { adminApi } from './client'
import type { CardBatch, AgentCard, LegacyLicenseCard, LicenseCardsPageData, PaginatedResponse } from './types'

export const adminGenerateCardBatch = (payload: {
  plan_code: string
  quantity: number
  prefix?: string
  valid_days?: number | null
  funding_source: 'balance' | 'credit'
}): Promise<{ success: boolean; data: { batch: CardBatch; cards: AgentCard[]; copied_text: string } }> =>
  adminApi.post('/agent/card-batches/generate', payload)

export const adminListCardBatches = (params?: {
  plan_code?: string
  payment_status?: string
  settlement_status?: string
  keyword?: string
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: PaginatedResponse<CardBatch> }> =>
  adminApi.get('/agent/card-batches', { params })

export const adminListCards = (params?: {
  plan_code?: string
  batch_id?: string
  status?: string
  source_type?: string
  keyword?: string
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: PaginatedResponse<AgentCard> }> =>
  adminApi.get('/agent/cards', { params })

export const adminExportCardsXlsx = (params?: {
  plan_code?: string
  batch_id?: string
  status?: string
  source_type?: string
  keyword?: string
}): Promise<Blob> =>
  adminApi.get('/agent/cards/export', { params, responseType: 'blob' })

export const adminCopyCards = (payload: {
  card_ids: number[]
  with_meta?: boolean
}): Promise<{ success: boolean; data: { count: number; copied_text: string } }> =>
  adminApi.post('/agent/cards/copy', payload)

export const adminSettleBatchDirect = (batchId: string): Promise<{ success: boolean; data: CardBatch }> =>
  adminApi.post(`/admin/card-batches/${encodeURIComponent(batchId)}/settle`)

// ── License Cards (Legacy) ──────────────────────────────────────────────────

export const adminGenerateLegacyCards = (payload: {
  plan_code: string
  quantity: number
  valid_days?: number
  prefix?: string
}): Promise<{ success: boolean; data: LegacyLicenseCard[] }> =>
  adminApi.post('/admin/license-cards/generate', payload)

export const adminListLicenseCards = (params?: {
  plan_code?: string
  is_used?: boolean
  is_active?: boolean
  keyword?: string
  sort_by?: string
  sort_order?: string
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: LicenseCardsPageData }> =>
  adminApi.get('/admin/license-cards', { params })

export const adminExportLicenseCards = (params?: {
  plan_code?: string
  is_used?: boolean
  is_active?: boolean
}): Promise<Blob> =>
  adminApi.get('/admin/license-cards/export', { params, responseType: 'blob' })

export const adminEnableLicenseCard = (cardCode: string): Promise<{ success: boolean; data: LegacyLicenseCard }> =>
  adminApi.post(`/admin/license-cards/${encodeURIComponent(cardCode)}/enable`)

export const adminDisableLicenseCard = (cardCode: string): Promise<{ success: boolean; data: LegacyLicenseCard }> =>
  adminApi.post(`/admin/license-cards/${encodeURIComponent(cardCode)}/disable`)
