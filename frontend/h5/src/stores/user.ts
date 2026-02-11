/**
 * 用户状态管理
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { User } from '@/api/auth'

const STORAGE_KEYS = {
  userId: 'user_id',
  username: 'username',
  token: 'token'
}

export const useUserStore = defineStore(
  'user',
  () => {
    // 状态
    const userId = ref<number | null>(null)
    const username = ref<string | null>(null)
    const token = ref<string | null>(null)
    const isAuthenticated = ref(false)

    // 设置用户
    const setUser = (id: number, name: string, tkn: string) => {
      userId.value = id
      username.value = name
      token.value = tkn
      isAuthenticated.value = true
      // 持久化到 localStorage
      localStorage.setItem(STORAGE_KEYS.userId, String(id))
      localStorage.setItem(STORAGE_KEYS.username, name)
      localStorage.setItem(STORAGE_KEYS.token, tkn)
    }

    // 清除用户
    const clearUser = () => {
      userId.value = null
      username.value = null
      token.value = null
      isAuthenticated.value = false
      localStorage.removeItem(STORAGE_KEYS.userId)
      localStorage.removeItem(STORAGE_KEYS.username)
      localStorage.removeItem(STORAGE_KEYS.token)
    }

    // 从 localStorage 恢复用户状态
    const restoreUser = () => {
      const storedUserId = localStorage.getItem(STORAGE_KEYS.userId)
      const storedUsername = localStorage.getItem(STORAGE_KEYS.username)
      const storedToken = localStorage.getItem(STORAGE_KEYS.token)

      if (!storedUserId || !storedToken) {
        clearUser()
        return
      }

      const parsedUserId = Number(storedUserId)
      if (!Number.isInteger(parsedUserId) || parsedUserId <= 0) {
        clearUser()
        return
      }

      userId.value = parsedUserId
      username.value = storedUsername
      token.value = storedToken
      isAuthenticated.value = true
    }

    // 登录
    const login = (userData: User, accessToken: string) => {
      setUser(userData.id, userData.username, accessToken)
    }

    // 登出
    const logout = () => {
      clearUser()
    }

    return {
      userId,
      username,
      token,
      isAuthenticated,
      setUser,
      clearUser,
      restoreUser,
      login,
      logout
    }
  }
)
