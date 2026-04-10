export const ROLE_LABELS: Record<string, string> = {
  super_admin: '超管',
  master_agent: '省总代',
  sub_agent: '下级代理',
  staff: '后台人员',
}

export const ACCOUNT_TYPE_LABELS: Record<string, string> = {
  staff: '员工后台账号',
  agent: '代理账号',
}

export const BUSINESS_IDENTITY_LABELS: Record<string, string> = {
  master_agent: '省总代',
  sub_agent: '下级代理',
}

export const SETTLEMENT_LABELS: Record<string, string> = {
  prepaid: '预付余额',
  credit: '授信',
  hybrid: '混合',
}

export const LEDGER_LABELS: Record<string, string> = {
  recharge: '充值入账',
  consume_balance: '余额扣费',
  credit_generate: '授信生成',
  credit_settlement: '授信结清',
}

export const OPERATION_LOG_LABELS: Record<string, string> = {
  recharge: '充值入账',
  card_generate: '卡密生成',
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

export const accountTypeLabel = (value?: string | null): string =>
  ACCOUNT_TYPE_LABELS[value || ''] || value || '-'

export const businessIdentityLabel = (value?: string | null): string =>
  BUSINESS_IDENTITY_LABELS[value || ''] || value || '-'

export const accountIdentitySummary = (account?: {
  account_type?: string | null
  business_identity?: string | null
  assigned_roles?: Array<{ display_name?: string | null }>
} | null): string => {
  if (!account) return '-'
  const roleNames = (account.assigned_roles || [])
    .map((role) => String(role.display_name || '').trim())
    .filter(Boolean)
  const businessIdentity = businessIdentityLabel(account.business_identity)
  const accountType = accountTypeLabel(account.account_type)
  if (account.account_type === 'agent' && account.business_identity) {
    return `${accountType} · ${businessIdentity}`
  }
  if (roleNames.length) {
    return `${accountType} · ${roleNames.join(' / ')}`
  }
  return accountType
}

export const settlementLabel = (value?: string | null): string => SETTLEMENT_LABELS[value || ''] || value || '-'

export const ledgerBizLabel = (value?: string | null): string => LEDGER_LABELS[value || ''] || value || '-'

export const operationLogLabel = (value?: string | null): string => OPERATION_LOG_LABELS[value || ''] || value || '-'
