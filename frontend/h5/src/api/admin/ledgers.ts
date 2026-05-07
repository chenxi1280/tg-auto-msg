import { adminApi } from './client'
import type { AgentAccount, FundLedger, OperationLog, PaginatedResponse } from './types'

export const adminListSelfFundLedgers = (params?: {
  biz_type?: string
  direction?: string
  keyword?: string
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: PaginatedResponse<FundLedger> }> =>
  adminApi.get('/agent/fund-ledgers', { params })

export const adminListVisibleFundLedgers = (params?: {
  biz_type?: string
  direction?: string
  keyword?: string
  limit?: number
  account_id?: number
  offset?: number
}): Promise<{ success: boolean; data: PaginatedResponse<FundLedger> }> =>
  adminApi.get('/admin/fund-ledgers', { params })

export const adminCreateRechargeEntry = (payload: {
  amount_cents: number
  subject_account_id: number
  remark?: string
}): Promise<{ success: boolean; data: AgentAccount }> =>
  adminApi.post('/admin/fund-ledgers/recharge', payload)

export const adminListOperationLogs = (params?: {
  log_type?: string
  account_id?: number
  keyword?: string
  date_from?: string
  date_to?: string
  limit?: number
  offset?: number
}): Promise<{ success: boolean; data: PaginatedResponse<OperationLog> }> =>
  adminApi.get('/admin/operation-logs', { params })
