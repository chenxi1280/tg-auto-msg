import { computed, reactive, ref } from 'vue'
import { defineStore } from 'pinia'
import type {
  AdminAuditLog,
  AdminProfile,
  AgentAccount,
  AgentCard,
  AgentPlan,
  ApprovalRequest,
  CardBatch,
  FundLedger,
} from '@/api/admin'
import {
  adminListAccounts,
  adminListApprovalRequests,
  adminListAuditLogs,
  adminListCardBatches,
  adminListCards,
  adminListPendingApprovals,
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
  const pendingApprovals = ref<ApprovalRequest[]>([])
  const approvalRequests = ref<ApprovalRequest[]>([])
  const auditLogs = ref<AdminAuditLog[]>([])
  const selfLedgers = ref<FundLedger[]>([])
  const visibleLedgers = ref<FundLedger[]>([])

  const loading = reactive({
    profile: false,
    accounts: false,
    plans: false,
    batches: false,
    cards: false,
    approvals: false,
    approvalRequests: false,
    auditLogs: false,
    selfLedgers: false,
    visibleLedgers: false,
  })

  const currentRole = computed(() => profile.value?.account.role_code || '')
  const isSuperAdmin = computed(() => currentRole.value === 'super_admin')
  const canManageAgents = computed(() => currentRole.value === 'super_admin' || currentRole.value === 'master_agent' || currentRole.value === 'sub_agent')
  const canViewVisibleLedgers = computed(() => currentRole.value === 'super_admin' || currentRole.value === 'master_agent')
  const accountMap = computed(() => {
    return new Map(accounts.value.map((account) => [account.id, account]))
  })

  const reset = () => {
    profile.value = null
    accounts.value = []
    plans.value = []
    batches.value = []
    cards.value = []
    pendingApprovals.value = []
    approvalRequests.value = []
    auditLogs.value = []
    selfLedgers.value = []
    visibleLedgers.value = []
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
      const response = await adminListAccounts()
      accounts.value = response.data
      return response.data
    } finally {
      loading.accounts = false
    }
  }

  const loadPlans = async () => {
    loading.plans = true
    try {
      const response = await adminListPricingPlans()
      plans.value = response.data
      return response.data
    } finally {
      loading.plans = false
    }
  }

  const loadBatches = async () => {
    loading.batches = true
    try {
      const response = await adminListCardBatches()
      batches.value = response.data
      return response.data
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

  const loadPendingApprovals = async () => {
    loading.approvals = true
    try {
      const response = await adminListPendingApprovals()
      pendingApprovals.value = response.data
      return response.data
    } finally {
      loading.approvals = false
    }
  }

  const loadApprovalRequests = async (params?: {
    status?: string
    request_type?: string
    limit?: number
  }) => {
    loading.approvalRequests = true
    try {
      const response = await adminListApprovalRequests(params)
      approvalRequests.value = response.data
      return response.data
    } finally {
      loading.approvalRequests = false
    }
  }

  const loadAuditLogs = async () => {
    loading.auditLogs = true
    try {
      const response = await adminListAuditLogs(200)
      auditLogs.value = response.data
      return response.data
    } finally {
      loading.auditLogs = false
    }
  }

  const loadSelfLedgers = async () => {
    loading.selfLedgers = true
    try {
      const response = await adminListSelfFundLedgers(200)
      selfLedgers.value = response.data
      return response.data
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
      })
      visibleLedgers.value = response.data
      return response.data
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
    pendingApprovals,
    approvalRequests,
    auditLogs,
    selfLedgers,
    visibleLedgers,
    loading,
    currentRole,
    isSuperAdmin,
    canManageAgents,
    canViewVisibleLedgers,
    accountMap,
    reset,
    bootstrap,
    loadProfile,
    loadAccounts,
    loadPlans,
    loadBatches,
    loadCards,
    loadPendingApprovals,
    loadApprovalRequests,
    loadAuditLogs,
    loadSelfLedgers,
    loadVisibleLedgers,
  }
})
