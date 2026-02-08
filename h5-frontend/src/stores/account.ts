/**
 * 账号状态管理
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as accountApi from '@/api/account'
import type { Account } from '@/api/account'

export const useAccountStore = defineStore('account', () => {
  // 状态
  const accounts = ref<Account[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  // 计算属性
  const activeAccounts = computed(() => accounts.value.filter(a => a.is_active))
  const onlineAccounts = computed(() => accounts.value.filter(a => a.health_status === 'online'))
  const floodingAccounts = computed(() => accounts.value.filter(a => a.is_flooding))
  const bannedAccounts = computed(() => accounts.value.filter(a => a.is_banned))

  // 获取账号列表
  const fetchAccounts = async (userId: number) => {
    loading.value = true
    error.value = null
    try {
      const res = await accountApi.getAccounts(userId)
      accounts.value = res.data || []
    } catch (err: any) {
      error.value = err.message || '获取账号列表失败'
      console.error('获取账号列表失败:', err)
    } finally {
      loading.value = false
    }
  }

  // 同步账号资源
  const syncAccount = async (accountId: string) => {
    try {
      const res = await accountApi.syncAccountResources(accountId)
      return res.message
    } catch (err: any) {
      console.error('同步账号资源失败:', err)
      throw err
    }
  }

  // 启用账号
  const enableAccount = async (accountId: string) => {
    try {
      await accountApi.enableAccount(accountId)
      // 更新本地状态
      const account = accounts.value.find(a => a.account_id === accountId)
      if (account) {
        account.is_active = true
      }
    } catch (err: any) {
      console.error('启用账号失败:', err)
      throw err
    }
  }

  // 禁用账号
  const disableAccount = async (accountId: string) => {
    try {
      await accountApi.disableAccount(accountId)
      // 更新本地状态
      const account = accounts.value.find(a => a.account_id === accountId)
      if (account) {
        account.is_active = false
      }
    } catch (err: any) {
      console.error('禁用账号失败:', err)
      throw err
    }
  }

  // 删除账号
  const deleteAccount = async (accountId: string) => {
    try {
      await accountApi.deleteAccount(accountId)
      // 从本地状态移除
      accounts.value = accounts.value.filter(a => a.account_id !== accountId)
    } catch (err: any) {
      console.error('删除账号失败:', err)
      throw err
    }
  }

  // 获取账号资源
  const getAccountResources = async (accountId: string, params?: {
    peer_type?: string
    is_active?: boolean
    search?: string
  }) => {
    try {
      const res = await accountApi.getAccountResources(accountId, params)
      return res.data || []
    } catch (err: any) {
      console.error('获取账号资源失败:', err)
      throw err
    }
  }

  return {
    accounts,
    loading,
    error,
    activeAccounts,
    onlineAccounts,
    floodingAccounts,
    bannedAccounts,
    fetchAccounts,
    syncAccount,
    enableAccount,
    disableAccount,
    deleteAccount,
    getAccountResources
  }
})
