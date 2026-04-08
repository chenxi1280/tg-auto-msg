export const ROLE_LABELS: Record<string, string> = {
  super_admin: '超管',
  master_agent: '省总代',
  sub_agent: '下级代理',
}

export const SETTLEMENT_LABELS: Record<string, string> = {
  prepaid: '预付余额',
  credit: '授信',
  hybrid: '混合',
}

export const APPROVAL_LABELS: Record<string, string> = {
  recharge: '充值入账',
  settlement: '授信结算',
  credit_adjust: '额度调整',
  batch_purchase: '批次申请（历史）',
}

export const LEDGER_LABELS: Record<string, string> = {
  recharge: '充值入账',
  consume_balance: '余额扣费',
  credit_generate: '授信生成',
  credit_settlement: '授信结清',
}

export const centsToYuan = (value?: number | null): string => ((value || 0) / 100).toFixed(2)

export const yuanToCents = (value?: number | null): number => Math.round((value || 0) * 100)

export const formatDateTime = (value?: string | null): string => {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

export const roleLabel = (role?: string | null): string => ROLE_LABELS[role || ''] || role || '-'

export const settlementLabel = (value?: string | null): string => SETTLEMENT_LABELS[value || ''] || value || '-'

export const approvalLabel = (value?: string | null): string => APPROVAL_LABELS[value || ''] || value || '-'

export const ledgerBizLabel = (value?: string | null): string => LEDGER_LABELS[value || ''] || value || '-'
