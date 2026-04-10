<template>
  <div class="page-stack">
    <div class="stats-grid" v-if="store.profile">
      <el-card shadow="hover">
        <div class="stat-label">当前账号</div>
        <div class="stat-value">{{ store.profile.account.display_name }}</div>
        <div class="stat-meta">{{ accountIdentitySummary(store.profile.account) }}</div>
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
        <div class="stat-label">授信预抵</div>
        <div class="stat-value">¥{{ centsToYuan(store.profile.account.credit_prepay_cents) }}</div>
        <div class="stat-meta">待用于逐批结清</div>
      </el-card>
      <el-card shadow="hover">
        <div class="stat-label">可见账号范围</div>
        <div class="stat-value">{{ store.profile.visible_account_count }}</div>
        <div class="stat-meta">当前角色权限范围内</div>
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
        <el-table v-if="!isCompact" :data="store.plans.slice(0, 5)" size="small">
          <el-table-column prop="display_name" label="规格" min-width="160" />
          <el-table-column label="价格" width="120">
            <template #default="{ row }">¥{{ centsToYuan(row.price_cents) }}</template>
          </el-table-column>
          <el-table-column prop="duration_days" label="天数" width="100" />
        </el-table>
        <div v-else class="mobile-card-list">
          <div v-for="plan in store.plans.slice(0, 5)" :key="plan.plan_code" class="mobile-data-card">
            <div class="mobile-data-card__header">
              <div>
                <div class="mobile-data-card__title">{{ plan.display_name }}</div>
                <div class="mobile-data-card__subtitle">{{ plan.duration_days }} 天</div>
              </div>
              <el-tag :type="plan.is_active ? 'success' : 'info'">{{ plan.is_active ? '启用' : '停用' }}</el-tag>
            </div>
            <div class="mobile-data-card__grid">
              <div class="mobile-data-card__row">
                <span class="mobile-data-card__label">统一价格</span>
                <span class="mobile-data-card__value">¥{{ centsToYuan(plan.price_cents) }}</span>
              </div>
              <div class="mobile-data-card__row">
                <span class="mobile-data-card__label">时长</span>
                <span class="mobile-data-card__value">{{ plan.duration_days }} 天</span>
              </div>
            </div>
          </div>
        </div>
      </el-card>

      <el-card shadow="hover">
        <template #header>
          <div class="card-header">
            <span>最近批次</span>
            <el-button v-if="canReadBatches" link type="primary" @click="router.push('/admin/card-center')">查看全部</el-button>
          </div>
        </template>
        <el-table v-if="!isCompact" :data="store.batches.slice(0, 6)" size="small">
          <el-table-column label="规格" width="120">
            <template #default="{ row }">{{ planDisplayName(row.plan_code, row.plan_display_name) }}</template>
          </el-table-column>
          <el-table-column label="已使用 / 总数" width="120">
            <template #default="{ row }">{{ row.used_count || 0 }} / {{ row.total_count || row.quantity }}</template>
          </el-table-column>
          <el-table-column label="总额" width="120">
            <template #default="{ row }">¥{{ centsToYuan(row.total_amount_cents) }}</template>
          </el-table-column>
          <el-table-column prop="payment_status" label="支付" width="100" />
        </el-table>
        <div v-else class="mobile-card-list">
          <div v-for="batch in store.batches.slice(0, 6)" :key="batch.batch_id" class="mobile-data-card">
            <div class="mobile-data-card__header">
              <div>
                <div class="mobile-data-card__title">{{ planDisplayName(batch.plan_code, batch.plan_display_name) }}</div>
                <div class="mobile-data-card__subtitle">{{ formatDateTime(batch.created_at) }}</div>
              </div>
              <el-tag :type="batch.payment_status === 'paid' ? 'success' : 'warning'">{{ batch.payment_status }}</el-tag>
            </div>
            <div class="mobile-data-card__grid">
              <div class="mobile-data-card__row">
                <span class="mobile-data-card__label">已使用 / 总数</span>
                <span class="mobile-data-card__value">{{ batch.used_count || 0 }} / {{ batch.total_count || batch.quantity }}</span>
              </div>
              <div class="mobile-data-card__row">
                <span class="mobile-data-card__label">总额</span>
                <span class="mobile-data-card__value">¥{{ centsToYuan(batch.total_amount_cents) }}</span>
              </div>
            </div>
          </div>
        </div>
      </el-card>
    </div>

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>最近卡密</span>
          <el-button v-if="canReadBatches" link type="primary" @click="router.push('/admin/card-center?tab=cards')">卡密中心</el-button>
        </div>
      </template>
      <el-empty v-if="!store.cards.length" description="当前没有卡密记录" />
      <el-table v-else-if="!isCompact" :data="store.cards.slice(0, 8)" size="small">
        <el-table-column prop="card_code" label="卡密" min-width="180" />
        <el-table-column label="规格" width="120">
          <template #default="{ row }">{{ planDisplayName(row.plan_code, row.plan_display_name) }}</template>
        </el-table-column>
        <el-table-column prop="card_source_type" label="来源" width="120" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">{{ row.is_used ? '已使用' : '可用' }}</template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="160">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>
      <div v-else class="mobile-card-list">
        <div v-for="card in store.cards.slice(0, 8)" :key="card.id" class="mobile-data-card">
          <div class="mobile-data-card__header">
            <div>
              <div class="mobile-data-card__title">{{ card.card_code }}</div>
              <div class="mobile-data-card__subtitle">{{ planDisplayName(card.plan_code, card.plan_display_name) }}</div>
            </div>
            <el-tag :type="card.is_used ? 'warning' : 'success'">{{ card.is_used ? '已使用' : '可用' }}</el-tag>
          </div>
          <div class="mobile-data-card__grid">
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">来源</span>
              <span class="mobile-data-card__value">{{ card.card_source_type }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">创建时间</span>
              <span class="mobile-data-card__value">{{ formatDateTime(card.created_at) }}</span>
            </div>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { accountIdentitySummary, centsToYuan, formatDateTime } from '@/utils/adminConsole'
import { useResponsive } from '@/composables/useResponsive'

const router = useRouter()
const store = useAdminConsoleStore()
const { isCompact } = useResponsive()
const canReadPricing = computed(() => store.hasPermission('pricing.read'))
const canReadBatches = computed(() => store.hasPermission('batches.read'))
const planDisplayName = (planCode?: string | null, planDisplayNameValue?: string | null) =>
  planDisplayNameValue || store.plans.find((plan) => plan.plan_code === planCode)?.display_name || '规格已记录'

onMounted(async () => {
  const tasks: Promise<unknown>[] = [store.loadProfile()]
  if (canReadPricing.value) {
    tasks.push(store.loadPlans())
  }
  if (canReadBatches.value) {
    tasks.push(store.loadBatches())
    tasks.push(store.loadCards())
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
