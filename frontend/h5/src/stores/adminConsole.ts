import { computed, reactive, ref } from 'vue'
import { defineStore } from 'pinia'
import type {
  AdminAuditLog,
  DeveloperAppSettings,
  AdminProfile,
  AgentAccount,
  AgentCard,
  AgentPlan,
  CardBatch,
  FundLedger,
} from '@/api/admin'
import {
  adminListAccounts,
  adminListAuditLogs,
  adminListCardBatches,
  adminListCards,
  adminListPricingPlans,
  adminListSelfFundLedgers,
  adminListVisibleFundLedgers,
  adminMe,
} from '@/api/admin'

export const useAdminConsoleStore = defineStore('adminConsole', () => {
  const profile = ref<AdminProfile | null>(null)
  const accounts = ref<AgentAccount[]>([])
  const plans = ref<AgentPlan[]>([])
  const batches = ref<CardBatch[]>([])
  const cards = ref<AgentCard[]>([])
  const auditLogs = ref<AdminAuditLog[]>([])
  const selfLedgers = ref<FundLedger[]>([])
  const visibleLedgers = ref<FundLedger[]>([])
  const developerAppSettings = ref<DeveloperAppSettings | null>(null)

  const loading = reactive({
    profile: false,
    accounts: false,
    plans: false,
    batches: false,
    cards: false,
    auditLogs: false,
    selfLedgers: false,
    visibleLedgers: false,
  })

  const roleKeys = computed(() => profile.value?.roles || [])
  const permissionSet = computed(() => new Set(profile.value?.permissions || []))
  const hasPermission = (permissionCode: string) => permissionSet.value.has(permissionCode)
  const hasAnyPermission = (permissionCodes: string[]) => permissionCodes.some((permissionCode) => permissionSet.value.has(permissionCode))
  const hasRole = (roleKey: string) => roleKeys.value.includes(roleKey)
  const canManageAgents = computed(() => hasAnyPermission(['agents.read', 'agents.write']))
  const canCreateMasterAgents = computed(() => hasPermission('agents.master.create'))
  const canCreateChildAgents = computed(() => hasPermission('agents.child.create'))
  const canManageMasterCredit = computed(() => hasPermission('agents.credit.master.write'))
  const canViewVisibleLedgers = computed(() => hasPermission('ledgers.scope.read'))
  const canViewSystemAudit = computed(() => hasPermission('audit.system.read'))
  const accountMap = computed(() => {
    return new Map(accounts.value.map((account) => [account.id, account]))
  })

  const reset = () => {
    profile.value = null
    accounts.value = []
    plans.value = []
    batches.value = []
    cards.value = []
    auditLogs.value = []
    selfLedgers.value = []
    visibleLedgers.value = []
    developerAppSettings.value = null
  }

  const loadProfile = async () => {
    loading.profile = true
    try {
      const response = await adminMe()
      profile.value = response.data
      return response.data
    } finally {
      loading.profile = false
    }
  }

  const loadAccounts = async () => {
    loading.accounts = true
    try {
      const response = await adminListAccounts({ limit: 500, offset: 0 })
      accounts.value = response.data.items
      return response.data.items
    } finally {
      loading.accounts = false
    }
  }

  const loadPlans = async () => {
    loading.plans = true
    try {
      const response = await adminListPricingPlans({ limit: 500, offset: 0 })
      plans.value = response.data.items
      return response.data.items
    } finally {
      loading.plans = false
    }
  }

  const loadBatches = async () => {
    loading.batches = true
    try {
      const response = await adminListCardBatches({ limit: 500, offset: 0 })
      batches.value = response.data.items
      return response.data.items
    } finally {
      loading.batches = false
    }
  }

  const loadCards = async () => {
    loading.cards = true
    try {
      const response = await adminListCards({ limit: 200, offset: 0 })
      cards.value = response.data.items
      return response.data.items
    } finally {
      loading.cards = false
    }
  }

  const loadAuditLogs = async () => {
    loading.auditLogs = true
    try {
      const response = await adminListAuditLogs({ limit: 200, offset: 0 })
      auditLogs.value = response.data.items
      return response.data.items
    } finally {
      loading.auditLogs = false
    }
  }

  const loadSelfLedgers = async () => {
    loading.selfLedgers = true
    try {
      const response = await adminListSelfFundLedgers({ limit: 200, offset: 0 })
      selfLedgers.value = response.data.items
      return response.data.items
    } finally {
      loading.selfLedgers = false
    }
  }

  const loadVisibleLedgers = async (accountId?: number) => {
    if (!canViewVisibleLedgers.value) {
      visibleLedgers.value = []
      return []
    }
    loading.visibleLedgers = true
    try {
      const response = await adminListVisibleFundLedgers({
        limit: 200,
        account_id: accountId,
        offset: 0,
      })
      visibleLedgers.value = response.data.items
      return response.data.items
    } finally {
      loading.visibleLedgers = false
    }
  }

  const bootstrap = async () => {
    await loadProfile()
  }

  return {
    profile,
    accounts,
    plans,
    batches,
    cards,
    auditLogs,
    selfLedgers,
    visibleLedgers,
    developerAppSettings,
    loading,
    roleKeys,
    permissionSet,
    hasPermission,
    hasAnyPermission,
    hasRole,
    canManageAgents,
    canCreateMasterAgents,
    canCreateChildAgents,
    canManageMasterCredit,
    canViewVisibleLedgers,
    canViewSystemAudit,
    accountMap,
    reset,
    bootstrap,
    loadProfile,
    loadAccounts,
    loadPlans,
    loadBatches,
    loadCards,
    loadAuditLogs,
    loadSelfLedgers,
    loadVisibleLedgers,
  }
})
