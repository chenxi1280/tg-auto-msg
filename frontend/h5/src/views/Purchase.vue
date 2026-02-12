<template>
  <div class="purchase-page">
    <header class="header">
      <div class="container">
        <router-link to="/accounts" class="back-link">← 返回账号管理</router-link>
        <h1>套餐购买</h1>
        <p class="sub-title">开通套餐后才可添加 Telegram 账号</p>
      </div>
    </header>

    <main class="container content" v-loading="loading">
      <el-alert
        v-if="subscription?.is_active"
        type="success"
        :closable="false"
        title="当前账号已开通服务，无需重复购买"
      />

      <el-alert
        v-else
        type="warning"
        :closable="false"
        title="当前未开通服务，请先购买套餐或激活卡密"
      />

      <el-card shadow="hover" class="mt16">
        <template #header>
          <div class="card-title">可选套餐</div>
        </template>

        <el-empty v-if="plans.length === 0" description="暂无可购买套餐" />

        <div v-else class="plan-grid">
          <div v-for="plan in plans" :key="plan.plan_code" class="plan-card">
            <div class="plan-name">{{ plan.display_name }}</div>
            <div class="plan-price">¥{{ plan.price_yuan }}</div>
            <div class="plan-duration">{{ plan.duration_days }} 天</div>
            <el-tag size="small" :type="plan.billing_cycle === 'yearly' ? 'success' : 'info'">
              {{ plan.billing_cycle === 'yearly' ? '年付' : '月付' }}
            </el-tag>
          </div>
        </div>
      </el-card>

      <el-card shadow="hover" class="mt16">
        <template #header>
          <div class="card-title">购买方式</div>
        </template>
        <p class="helper-text">点击下方按钮跳转 Telegram 联系购买，购买后在“我的”页面输入卡密激活。</p>
        <div class="actions">
          <el-button type="primary" size="large" @click="goTelegramPurchase">
            {{ purchase.button_text || '去 TG 购买' }}
          </el-button>
          <el-button size="large" @click="goMy">去激活卡密</el-button>
        </div>
      </el-card>
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { PricingPlan, SubscriptionStatus } from '@/api/me'
import { getSubscription } from '@/api/me'

const router = useRouter()
const loading = ref(false)
const plans = ref<PricingPlan[]>([])
const subscription = ref<SubscriptionStatus | null>(null)
const purchase = ref({
  url: '',
  button_text: '去 TG 购买',
})

const loadData = async () => {
  loading.value = true
  try {
    const res = await getSubscription()
    subscription.value = res.data
    plans.value = res.data.plans || []
    purchase.value = res.data.purchase || purchase.value
  } finally {
    loading.value = false
  }
}

const goTelegramPurchase = () => {
  if (!purchase.value.url) {
    ElMessage.warning('购买链接暂未配置，请联系管理员')
    return
  }
  window.open(purchase.value.url, '_blank')
}

const goMy = () => {
  router.push('/me')
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.purchase-page {
  min-height: 100vh;
  background: #f7f8fa;
}

.header {
  background: #fff;
  border-bottom: 1px solid #ebeef5;
}

.container {
  max-width: 1100px;
  margin: 0 auto;
  padding: 16px;
}

.back-link {
  color: #409eff;
  text-decoration: none;
  font-size: 14px;
}

h1 {
  margin: 8px 0 6px;
  font-size: 24px;
}

.sub-title {
  margin: 0;
  color: #606266;
}

.content {
  padding-top: 20px;
}

.card-title {
  font-weight: 600;
}

.mt16 {
  margin-top: 16px;
}

.plan-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}

.plan-card {
  border: 1px solid #ebeef5;
  border-radius: 10px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.plan-name {
  color: #303133;
  font-weight: 600;
}

.plan-price {
  color: #f56c6c;
  font-size: 26px;
  font-weight: 700;
}

.plan-duration {
  color: #606266;
}

.helper-text {
  margin: 0 0 12px;
  color: #606266;
  line-height: 1.6;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

@media (max-width: 768px) {
  .container {
    padding: 12px;
  }

  h1 {
    font-size: 20px;
  }

  .plan-grid {
    grid-template-columns: 1fr;
  }

  .actions :deep(.el-button) {
    width: 100%;
  }
}
</style>
