<template>
  <div class="purchase-page">
    <header class="header">
      <div class="container">
        <router-link to="/accounts" class="back-link">← 返回账号管理</router-link>
        <div class="brand-line">
          <img class="brand-logo" src="/quanqiu.png" alt="全球通" />
          <div>
            <h1>全球通 Key 购买</h1>
            <p class="sub-title">一个系统账号只绑定 1 个 TG 账号。首次成功绑定 TG 账号会赠送 7 天试用，之后可通过卡密续费当前授权。</p>
          </div>
        </div>
      </div>
    </header>

    <main class="container content" v-loading="loading">
      <el-alert
        v-if="licenseStatus?.is_active"
        type="success"
        :closable="false"
        title="当前授权已生效，如需继续使用可继续购买新的卡密续费当前授权"
      />

      <el-alert
        v-else
        type="warning"
        :closable="false"
        title="当前还没有可用授权，请先购买卡密或在“我的”页面输入卡密续费"
      />

      <el-card shadow="hover" class="mt16">
        <template #header>
          <div class="card-title">可选 Key 规格</div>
        </template>

        <el-empty v-if="plans.length === 0" description="暂无可购买 Key 规格" />

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
        <p class="helper-text">点击下方按钮跳转 Telegram 购买全球通卡密。购买后可在“我的”页面输入卡密，为当前唯一授权续费。</p>
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
import type { PricingPlan, AuthorizationStatus } from '@/api/me'
import { getLicenseStatus } from '@/api/me'

const router = useRouter()
const loading = ref(false)
const plans = ref<PricingPlan[]>([])
const licenseStatus = ref<AuthorizationStatus | null>(null)
const purchase = ref({
  url: '',
  button_text: '去 TG 购买',
})

const loadData = async () => {
  loading.value = true
  try {
    const res = await getLicenseStatus()
    licenseStatus.value = res.data
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

.brand-line {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
}

.brand-logo {
  width: 84px;
  height: auto;
  display: block;
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
