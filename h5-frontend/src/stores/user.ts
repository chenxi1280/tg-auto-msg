/**
 * 用户状态管理
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useUserStore = defineStore(
  'user',
  () => {
    // 状态
    const userId = ref<number | null>(null)
    const token = ref<string | null>(null)
    const isAuthenticated = ref(false)

    // 设置用户
    const setUser = (id: number, tkn: string) => {
      userId.value = id
      token.value = tkn
      isAuthenticated.value = true
      // 持久化到 localStorage
      localStorage.setItem('user_id', String(id))
      localStorage.setItem('token', tkn)
    }

    // 清除用户
    const clearUser = () => {
      userId.value = null
      token.value = null
      isAuthenticated.value = false
      localStorage.removeItem('user_id')
      localStorage.removeItem('token')
    }

    // 从 localStorage 恢复用户状态
    const restoreUser = () => {
      const storedUserId = localStorage.getItem('user_id')
      const storedToken = localStorage.getItem('token')
      if (storedUserId && storedToken) {
        userId.value = Number(storedUserId)
        token.value = storedToken
        isAuthenticated.value = true
      }
    }

    return {
      userId,
      token,
      isAuthenticated,
      setUser,
      clearUser,
      restoreUser
    }
  }
)
