import request from './request'
import type { ApiResponse } from './request'

export interface PricingPlan {
  plan_code: string
  display_name: string
  billing_cycle: string
  price_cents: number
  price_yuan: string
  duration_days: number
  is_active: boolean
  sort_order: number
}

export interface CurrentAuthorization {
  authorization_id: string
  account_id: string | null
  account_name?: string | null
  start_at?: string | null
  end_at: string | null
  duration_days: number
  card_count: number
  status: string
  remaining_days?: number | null
  grant_source?: string | null
  grant_source_label?: string | null
  source_card_code_masked?: string | null
  latest_card_code_masked?: string | null
}

export interface AuthorizationStatus {
  is_active: boolean
  current_authorization: CurrentAuthorization | null
  remain_days: number | null
  authorization_overview?: {
    account_count: number
    max_account_count: number
    can_bind_account: boolean
    is_at_limit: boolean
    is_over_limit: boolean
    has_active_authorization: boolean
    next_expiring_at: string | null
  }
  bot: {
    username: string
    bind_deep_link_base: string
  }
  plans: PricingPlan[]
  purchase: {
    url: string
    button_text: string
  }
}

export interface MeProfile {
  user: {
    id: number
    username: string
    email?: string | null
    is_active: boolean
    bot_trial_eligible_at?: string | null
    bot_trial_granted_at?: string | null
    bot_trial_authorization_id?: string | null
    created_at: string
    bot_initial_password_viewable?: boolean
  }
  authorization_status: {
    is_active: boolean
    current_authorization: CurrentAuthorization | null
    remain_days: number | null
  }
  authorization_overview?: {
    account_count: number
    max_account_count: number
    can_bind_account: boolean
    is_at_limit: boolean
    is_over_limit: boolean
    has_active_authorization: boolean
    next_expiring_at: string | null
  }
  current_authorization?: CurrentAuthorization | null
  bot: {
    username: string
    bind_deep_link_base: string
  }
  plans: PricingPlan[]
  purchase: {
    url: string
    button_text: string
  }
}

export interface UserProfileBasic {
  id: number
  username: string
  email?: string | null
  is_active: boolean
  created_at: string | null
}

export const getMe = (): Promise<ApiResponse<MeProfile>> => {
  return request.get('/me')
}

export const getLicenseStatus = (): Promise<ApiResponse<AuthorizationStatus>> => {
  return request.get('/me/license-status')
}

export const activateCard = (
  cardCode: string,
): Promise<ApiResponse<AuthorizationStatus>> => {
  return request.post('/me/activate-card', {
    card_code: cardCode,
  })
}

export const changePassword = (
  oldPassword: string,
  newPassword: string,
): Promise<ApiResponse<{ message: string }>> => {
  return request.post('/me/change-password', {
    old_password: oldPassword,
    new_password: newPassword,
  })
}

export const updateProfile = (email?: string | null): Promise<ApiResponse<UserProfileBasic>> => {
  return request.put('/me/profile', { email: email ?? null })
}
