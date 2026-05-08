export interface ApiResponse<T = unknown> {
  success: boolean
  data: T
}

export interface PaginatedResponse<T, TStats = Record<string, unknown>> {
  items: T[]
  total: number
  limit: number
  offset: number
  stats?: TStats
  settings?: Record<string, unknown>
}

// ── Auth / Session ───────────────────────────────────────────────────────────

export interface AuthTokens {
  access_token: string
  token_type: string
}

export interface AdminAssignedRole {
  role_id: number
  role_key: string
  display_name: string
  is_system: boolean
}

export interface AdminProfileAccount {
  id: number
  username: string
  display_name: string
  role_code: string
  account_type: 'staff' | 'agent'
  business_identity: 'master_agent' | 'sub_agent' | null
  province_code: string
  parent_account_id: number | null
  root_master_account_id: number | null
  level_depth: number
  status: string
  settlement_mode: string
  is_credit_whitelisted: boolean
  credit_limit_cents: number
  allocated_credit_limit_cents: number
  credit_used_cents: number
  credit_prepay_cents: number
  balance_cents: number
  force_password_change: boolean
  contact_name: string | null
  contact_phone: string | null
  last_login_at: string | null
  created_at: string | null
  updated_at: string | null
  assigned_roles?: AdminAssignedRole[]
  permissions?: string[]
}

export interface AdminProfile {
  account: AdminProfileAccount
  visible_account_count: number
  province_code: string
  roles: string[]
  permissions: string[]
}

export interface AgentPlan {
  plan_code: string
  display_name: string
  billing_cycle: string
  price_cents: number
  price_yuan: string
  duration_days: number
  is_active: boolean
  sort_order: number
}

export interface AgentAccount extends AdminProfileAccount {}

// ── RBAC ─────────────────────────────────────────────────────────────────────

export interface AdminRole {
  id: number
  role_key: string
  display_name: string
  description: string | null
  status: string
  is_system: boolean
  permission_codes: string[]
  permission_count: number
  account_count: number
  created_at: string | null
  updated_at: string | null
}

export interface AdminPermission {
  id: number
  permission_code: string
  module_key: string
  display_name: string
  description: string | null
}

// ── Cards ────────────────────────────────────────────────────────────────────

export interface CardBatch {
  batch_id: string
  province_code: string
  creator_account_id: number
  owner_account_id: number
  direct_parent_account_id: number | null
  root_master_account_id: number | null
  current_liability_account_id: number | null
  current_counterparty_account_id: number | null
  current_counterparty_name?: string | null
  plan_code: string
  plan_display_name?: string | null
  quantity: number
  duration_days: number
  unit_price_cents: number
  total_amount_cents: number
  settlement_status: string
  payment_status: string
  export_count: number
  used_count?: number
  total_count?: number
  last_exported_at: string | null
  remark: string | null
  created_at: string | null
}

export interface AgentCard {
  id: number
  card_code: string
  plan_code: string | null
  plan_display_name?: string | null
  duration_days: number | null
  is_active: boolean
  is_used: boolean
  expires_at: string | null
  used_by_user_id: number | null
  used_at: string | null
  batch_id: string | null
  owner_account_id: number | null
  direct_parent_account_id: number | null
  root_master_account_id: number | null
  settlement_unit_price_cents: number
  card_source_type: string
  copy_status: string
  created_at: string | null
}

// ── Audit / Logs ─────────────────────────────────────────────────────────────

export interface AdminAuditLog {
  id: number
  actor: string
  action: string
  action_label?: string | null
  target_type: string | null
  target_type_label?: string | null
  target_id: string | null
  developer_app_id?: number | null
  old_value?: Record<string, unknown> | null
  new_value?: Record<string, unknown> | null
  detail: Record<string, unknown> | null
  ip_address: string | null
  created_at: string | null
}

// ── Fund Ledger ──────────────────────────────────────────────────────────────

export interface FundLedger {
  id: number
  ledger_scope: string
  account_id: number
  account_name: string | null
  counterparty_account_id: number | null
  counterparty_name: string | null
  biz_type: string
  direction: string
  amount_cents: number
  balance_after_cents: number | null
  credit_used_after_cents: number | null
  related_batch_id: string | null
  related_request_id: string | null
  remark: string | null
  operator_account_id: number | null
  operator_name: string | null
  created_at: string | null
}

export interface OperationLog {
  log_type: 'recharge' | 'card_generate' | 'credit_settlement'
  occurred_at: string | null
  operator_account_id: number | null
  operator_name: string | null
  subject_account_id: number | null
  subject_name: string | null
  counterparty_account_id: number | null
  counterparty_name: string | null
  amount_cents: number
  plan_code: string | null
  plan_display_name?: string | null
  quantity: number | null
  batch_id: string | null
  funding_source: string | null
  ledger_scope: string | null
  remark: string | null
}

// ── System Settings ──────────────────────────────────────────────────────────

export interface PurchaseSettings {
  purchase_url: string
  purchase_button_text: string
  purchase_buttons?: PurchaseButton[]
}

export interface PurchaseButton {
  text: string
  url: string
}

export interface BotNoticeSettings {
  enabled: boolean
  entry_button_text: string
  message_text: string
  target_url: string
  updated_at?: string | null
  refresh_summary?: {
    total_users?: number
    updated?: number
    failed?: number
    pin_attempted_users?: number
    pin_failed_users?: number
    results?: Record<string, unknown>[]
  }
}

export interface SystemTodayStats {
  date: string
  timezone: string
  today_sent_messages: number
  today_bound_cards: number
  today_new_users: number
  today_activations: number
  today_card_renewals: number
  today_sent_messages_total: number
  today_sent_success: number
  today_sent_failed: number
}

export interface DeveloperApp {
  id: number
  app_name: string
  api_id: number
  is_active: boolean
  max_accounts: number
  selection_weight: number
  health_status: string
  last_health_check_at: string | null
  last_health_error: string | null
  last_health_latency_ms: number | null
  health_fail_count: number
  credentials_version: number
  last_rotated_at: string | null
  notes: string | null
  account_count?: number
  active_account_count?: number
  account_items?: DeveloperAppAccount[]
}

export interface DeveloperAppAccount {
  account_id: string
  tg_user_id: number | null
  username: string | null
  tg_account_name: string
  first_name: string | null
  phone: string | null
  owner_user_id: number
  owner_username: string | null
  is_active: boolean
  health_status: string | null
  messages_sent: number
  task_count: number
  enabled_task_count: number
  created_at: string | null
}

export interface DeveloperAppSettings {
  assignment_mode: string
  alert_tg_user_ids: number[]
  alert_tg_user_ids_text: string
  default_developer_app_id?: number | null
  default_developer_app_name?: string | null
  default_developer_app_active?: boolean
}

// ── Proxies ──────────────────────────────────────────────────────────────────

export interface SystemProxy {
  proxy_id: number
  proxy_type: string
  host: string
  port: number
  username: string | null
  is_active: boolean
  is_healthy: boolean
  response_time_ms: number | null
  usage_count: number
  assigned_account_id: string | null
  assigned_account_name?: string | null
  last_check_at: string | null
  created_at: string | null
}

export interface LegacyProxy extends SystemProxy {}

// ── License / Legacy Cards ───────────────────────────────────────────────────

export interface LegacyLicenseCard {
  id: number
  card_code: string
  plan_code: string | null
  duration_days: number | null
  is_active: boolean
  is_used: boolean
  expires_at: string | null
  used_by_user_id: number | null
  used_by_username?: string | null
  used_at: string | null
  authorization_id?: string | null
  bound_account_id?: string | null
  bound_account_name?: string | null
  authorization_end_at?: string | null
  created_at: string | null
  updated_at?: string | null
}

export interface LicenseCardsPageData {
  items: LegacyLicenseCard[]
  total: number
  limit: number
  offset: number
  stats?: {
    total: number
    used: number
    unused: number
  }
}

export interface LicenseAuthorization {
  authorization_id: string
  user_id: number
  owner_username: string | null
  status: string
  current_account_id: string | null
  current_account_username: string | null
  current_account_phone: string | null
  current_account_tg_user_id: number | null
  total_duration_days: number
  start_at: string | null
  end_at: string | null
  created_at: string | null
  updated_at: string | null
}

// ── Legacy Users ─────────────────────────────────────────────────────────────

export interface LegacyUser {
  id: number
  username: string | null
  email: string | null
  is_active: boolean
  created_at: string | null
  account_count: number
  authorization_count: number
  developer_app_id: number | null
  tg_account_names?: string[]
  tg_account_summary?: string
  task_count?: number
  enabled_task_count?: number
  current_authorization: {
    start_at: string | null
    end_at: string | null
    status: string | null
  }
}

export interface LegacyUserAccount {
  account_id: string
  tg_user_id: number | null
  username: string | null
  tg_account_name?: string
  first_name: string | null
  phone: string | null
  developer_app_id: number | null
  is_active: boolean
  is_banned: boolean
  health_status: string | null
  is_flooding: boolean
  messages_sent: number
  task_count?: number
  enabled_task_count?: number
  send_log_count?: number
  send_success_count?: number
  send_failed_count?: number
  last_send_at?: string | null
  last_send_result?: string | null
  last_send_error_message?: string | null
  created_at: string | null
  authorization_id?: string | null
  authorization_status?: string | null
  authorization_end_at?: string | null
}

export interface LegacyUserAccountSendLog {
  id: number
  task_id: string
  task_title: string
  send_at: string | null
  result: string
  trigger_source: string
  error_code: string | null
  error_message: string | null
  message_id: number | null
}

export interface AccountOption {
  account_id: string
  username: string | null
  phone: string | null
  tg_user_id: number | null
  owner_user_id: number
  owner_username: string | null
  label: string
}

// ── Admin Account Reset Result ───────────────────────────────────────────────

export interface AdminAccountResetResult {
  account_id: number
  username: string
  force_password_change: boolean
}
