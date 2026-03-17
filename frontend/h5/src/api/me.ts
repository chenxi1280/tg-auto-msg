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

export interface CurrentSubscription {
  id: number
  plan_code: string | null
  source: string
  card_code: string | null
  start_at: string | null
  end_at: string | null
  status: string
}

export interface SubscriptionStatus {
  is_active: boolean
  current: CurrentSubscription | null
  remain_days: number | null
  tg_account_limit: {
    account_count: number
    plan_limit: number | null
    override_limit: number | null
    effective_limit: number
    remaining_slots: number | null
    is_at_limit: boolean
    is_over_limit: boolean
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
    created_at: string
  }
  subscription: {
    is_active: boolean
    current: CurrentSubscription | null
    remain_days: number | null
  }
  tg_account_limit: {
    account_count: number
    plan_limit: number | null
    override_limit: number | null
    effective_limit: number
    remaining_slots: number | null
    is_at_limit: boolean
    is_over_limit: boolean
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

export const getSubscription = (): Promise<ApiResponse<SubscriptionStatus>> => {
  return request.get('/me/subscription')
}

export const activateCard = (cardCode: string): Promise<ApiResponse<SubscriptionStatus>> => {
  return request.post('/me/activate-card', { card_code: cardCode })
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
