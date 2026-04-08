<template>
  <div class="page-stack">
    <div class="stats-grid" v-if="store.profile">
      <el-card shadow="hover">
        <div class="stat-label">当前账号</div>
        <div class="stat-value">{{ store.profile.account.display_name }}</div>
        <div class="stat-meta">{{ roleLabel(store.profile.account.role_code) }}</div>
      </el-card>
      <el-card shadow="hover">
        <div class="stat-label">可用余额</div>
        <div class="stat-value">¥{{ centsToYuan(store.profile.account.balance_cents) }}</div>
        <div class="stat-meta">线下充值确认后入账</div>
      </el-card>
      <el-card shadow="hover">
        <div class="stat-label">授信占用</div>
        <div class="stat-value">¥{{ centsToYuan(store.profile.account.credit_used_cents) }}</div>
        <div class="stat-meta">
          总额度 ¥{{ centsToYuan(store.profile.account.credit_limit_cents) }}
        </div>
      </el-card>
      <el-card shadow="hover">
        <div class="stat-label">待审批</div>
        <div class="stat-value">{{ store.pendingApprovals.length }}</div>
        <div class="stat-meta">H5/TG 双通道可处理</div>
      </el-card>
    </div>

    <div class="content-grid">
      <el-card shadow="hover">
        <template #header>
          <div class="card-header">
            <span>统一价格概览</span>
            <el-button v-if="canReadPricing" link type="primary" @click="router.push('/admin/pricing')">前往管理</el-button>
          </div>
        </template>
        <el-table :data="store.plans.slice(0, 5)" size="small">
          <el-table-column prop="display_name" label="规格" min-width="160" />
          <el-table-column prop="plan_code" label="编码" width="140" />
          <el-table-column label="价格" width="120">
            <template #default="{ row }">¥{{ centsToYuan(row.price_cents) }}</template>
          </el-table-column>
          <el-table-column prop="duration_days" label="天数" width="100" />
        </el-table>
      </el-card>

      <el-card shadow="hover">
        <template #header>
          <div class="card-header">
            <span>最近批次</span>
            <el-button v-if="canReadBatches" link type="primary" @click="router.push('/admin/batches')">查看全部</el-button>
          </div>
        </template>
        <el-table :data="store.batches.slice(0, 6)" size="small">
          <el-table-column prop="batch_id" label="批次号" min-width="180" />
          <el-table-column prop="plan_code" label="规格" width="120" />
          <el-table-column prop="quantity" label="数量" width="90" />
          <el-table-column label="总额" width="120">
            <template #default="{ row }">¥{{ centsToYuan(row.total_amount_cents) }}</template>
          </el-table-column>
          <el-table-column prop="payment_status" label="支付" width="100" />
        </el-table>
      </el-card>
    </div>

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>待处理审批</span>
          <el-button v-if="canReadApprovals" link type="primary" @click="router.push('/admin/approvals')">审批中心</el-button>
        </div>
      </template>
      <el-empty v-if="!store.pendingApprovals.length" description="当前没有待处理审批" />
      <el-table v-else :data="store.pendingApprovals.slice(0, 8)" size="small">
        <el-table-column prop="request_id" label="审批单号" min-width="180" />
        <el-table-column label="类型" width="120">
          <template #default="{ row }">{{ approvalLabel(row.request_type) }}</template>
        </el-table-column>
        <el-table-column prop="subject_account_id" label="主体账号" width="120" />
        <el-table-column label="金额" width="120">
          <template #default="{ row }">{{ row.amount_cents == null ? '-' : `¥${centsToYuan(row.amount_cents)}` }}</template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="160">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { approvalLabel, centsToYuan, formatDateTime, roleLabel } from '@/utils/adminConsole'

const router = useRouter()
const store = useAdminConsoleStore()
const canReadApprovals = computed(() => store.hasPermission('approvals.read'))
const canReadPricing = computed(() => store.hasPermission('pricing.read'))
const canReadBatches = computed(() => store.hasPermission('batches.read'))

onMounted(async () => {
  const tasks: Promise<unknown>[] = [store.loadProfile()]
  if (canReadPricing.value) {
    tasks.push(store.loadPlans())
  }
  if (canReadBatches.value) {
    tasks.push(store.loadBatches())
  }
  if (canReadApprovals.value) {
    tasks.push(store.loadPendingApprovals())
  }
  await Promise.all(tasks)
})
</script>

<style scoped>
.page-stack {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.stats-grid,
.content-grid {
  display: grid;
  gap: 20px;
}

.stats-grid {
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}

.content-grid {
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
}

.stat-label {
  color: #64748b;
  font-size: 13px;
}

.stat-value {
  margin-top: 12px;
  font-size: 30px;
  font-weight: 700;
  color: #0f172a;
}

.stat-meta {
  margin-top: 10px;
  color: #64748b;
  font-size: 13px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
