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

export interface CurrentLicenseSlot {
  slot_id: string
  account_id: string | null
  account_name?: string | null
  end_at: string | null
  duration_days: number
  card_count: number
  status: string
  grant_source?: string | null
  grant_source_label?: string | null
}

export interface LicenseSlotItem {
  slot_id: string
  account_id: string | null
  account_name?: string | null
  status: string
  duration_days: number
  start_at: string | null
  end_at: string | null
  card_count: number
  remaining_days: number
  grant_source?: string | null
  grant_source_label?: string | null
  source_card_code_masked?: string | null
  latest_card_code_masked?: string | null
}

export interface LicenseStatus {
  is_active: boolean
  current: CurrentLicenseSlot | null
  remain_days: number | null
  license_overview?: {
    account_count: number
    slot_count: number
    active_slot_count: number
    unbound_active_slot_count: number
    remaining_slots: number
    login_capacity: number
    remaining_login_slots: number
    is_at_limit: boolean
    is_over_limit: boolean
    has_active_license: boolean
    next_expiring_at: string | null
  }
  license_slots?: LicenseSlotItem[]
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
    bot_trial_slot_id?: string | null
    created_at: string
  }
  license_status: {
    is_active: boolean
    current: CurrentLicenseSlot | null
    remain_days: number | null
  }
  license_overview?: {
    account_count: number
    slot_count: number
    active_slot_count: number
    unbound_active_slot_count: number
    remaining_slots: number
    login_capacity: number
    remaining_login_slots: number
    is_at_limit: boolean
    is_over_limit: boolean
    has_active_license: boolean
    next_expiring_at: string | null
  }
  license_slots?: LicenseSlotItem[]
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

export const getLicenseStatus = (): Promise<ApiResponse<LicenseStatus>> => {
  return request.get('/me/license-status')
}

export const activateCard = (
  cardCode: string,
  accountId?: string | null,
  slotId?: string | null,
): Promise<ApiResponse<LicenseStatus>> => {
  return request.post('/me/activate-card', {
    card_code: cardCode,
    account_id: accountId ?? null,
    slot_id: slotId ?? null,
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
