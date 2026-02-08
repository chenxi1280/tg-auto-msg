/**
 * 代理状态管理
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as proxyApi from '@/api/proxy'
import type { Proxy } from '@/api/proxy'

export const useProxyStore = defineStore('proxy', () => {
  // 状态
  const proxies = ref<Proxy[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  // 计算属性
  const healthyProxies = computed(() => proxies.value.filter(p => p.is_healthy))
  const availableProxies = computed(() => proxies.value.filter(p => p.is_active && p.is_healthy))
  const assignedProxies = computed(() => proxies.value.filter(p => p.assigned_account_id))

  // 获取代理列表
  const fetchProxies = async () => {
    loading.value = true
    error.value = null
    try {
      const res = await proxyApi.getProxies()
      proxies.value = res.data || []
    } catch (err: any) {
      error.value = err.message || '获取代理列表失败'
      console.error('获取代理列表失败:', err)
    } finally {
      loading.value = false
    }
  }

  // 添加代理
  const addProxy = async (data: {
    proxy_type: string
    host: string
    port: number
    username?: string
    password?: string
  }) => {
    try {
      const res = await proxyApi.addProxy(data)
      // 重新获取列表
      await fetchProxies()
      return res.data
    } catch (err: any) {
      console.error('添加代理失败:', err)
      throw err
    }
  }

  // 检查代理健康状态
  const checkHealth = async (proxyId: number) => {
    try {
      const res = await proxyApi.checkProxyHealth(proxyId)
      // 更新本地状态
      const proxy = proxies.value.find(p => p.proxy_id === proxyId)
      if (proxy) {
        proxy.is_healthy = res.data.is_healthy
        proxy.response_time_ms = res.data.response_time_ms
      }
      return res.data
    } catch (err: any) {
      console.error('检查代理健康状态失败:', err)
      throw err
    }
  }

  // 删除代理
  const deleteProxy = async (proxyId: number) => {
    try {
      await proxyApi.deleteProxy(proxyId)
      // 从本地状态移除
      proxies.value = proxies.value.filter(p => p.proxy_id !== proxyId)
    } catch (err: any) {
      console.error('删除代理失败:', err)
      throw err
    }
  }

  // 分配代理
  const assignProxy = async (proxyId: number, accountId: string) => {
    try {
      await proxyApi.assignProxy(proxyId, accountId)
      // 更新本地状态
      const proxy = proxies.value.find(p => p.proxy_id === proxyId)
      if (proxy) {
        proxy.assigned_account_id = accountId
      }
    } catch (err: any) {
      console.error('分配代理失败:', err)
      throw err
    }
  }

  // 解绑代理
  const unassignProxy = async (proxyId: number) => {
    try {
      await proxyApi.unassignProxy(proxyId)
      // 更新本地状态
      const proxy = proxies.value.find(p => p.proxy_id === proxyId)
      if (proxy) {
        proxy.assigned_account_id = null
      }
    } catch (err: any) {
      console.error('解绑代理失败:', err)
      throw err
    }
  }

  return {
    proxies,
    loading,
    error,
    healthyProxies,
    availableProxies,
    assignedProxies,
    fetchProxies,
    addProxy,
    checkHealth,
    deleteProxy,
    assignProxy,
    unassignProxy
  }
})
