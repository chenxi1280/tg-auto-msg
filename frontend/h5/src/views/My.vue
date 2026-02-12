<template>
  <div class="my-page">
    <header class="header">
      <div class="container">
        <router-link to="/accounts" class="back-link">← 返回账号管理</router-link>
        <h1>我的</h1>
      </div>
    </header>

    <div class="container content" v-loading="loading">
      <el-row :gutter="16">
        <el-col :xs="24" :md="12">
          <el-card shadow="hover">
            <template #header>
              <div class="card-title">基本信息</div>
            </template>
            <div class="info-row">
              <span class="label">用户 ID</span>
              <span class="value">{{ profile?.user.id || '-' }}</span>
            </div>
            <div class="info-row">
              <span class="label">用户名</span>
              <span class="value">{{ profile?.user.username || '-' }}</span>
            </div>
            <div class="info-row">
              <span class="label">邮箱</span>
              <span class="value">{{ profile?.user.email || '未设置' }}</span>
            </div>
            <div class="info-row">
              <span class="label">注册时间</span>
              <span class="value">{{ formatDateTime(profile?.user.created_at) }}</span>
            </div>
            <div class="info-actions">
              <el-button type="primary" @click="openEditProfileDialog">修改基本信息</el-button>
            </div>
          </el-card>
        </el-col>

        <el-col :xs="24" :md="12">
          <el-card shadow="hover">
            <template #header>
              <div class="card-title">订阅状态</div>
            </template>
            <div class="subscription">
              <el-tag :type="subscription?.is_active ? 'success' : 'warning'" size="large">
                {{ subscription?.is_active ? '已开通' : '未开通' }}
              </el-tag>
              <div class="subscription-meta">
                <p>剩余天数：{{ subscription?.remain_days ?? 0 }}</p>
                <p>到期时间：{{ formatDateTime(subscription?.current?.end_at) }}</p>
              </div>
            </div>
            <el-alert
              v-if="!subscription?.is_active"
              title="未开通服务，添加账号前请先激活卡密"
              type="warning"
              :closable="false"
            />
            <div v-if="!subscription?.is_active" class="plan-list">
              <div class="plan-item" v-for="plan in plans" :key="plan.plan_code">
                <div class="plan-main">
                  <strong>{{ plan.display_name }}</strong>
                  <span>¥{{ plan.price_yuan }}</span>
                </div>
                <div class="plan-sub">
                  <span>{{ plan.duration_days }} 天</span>
                  <span>{{ plan.billing_cycle === 'yearly' ? '年付' : '月付' }}</span>
                </div>
              </div>
            </div>
            <el-button
              v-if="!subscription?.is_active"
              type="primary"
              class="buy-btn"
              @click="goPurchase"
            >
              去购买套餐
            </el-button>
          </el-card>
        </el-col>
      </el-row>

      <el-row :gutter="16" class="mt16">
        <el-col :xs="24" :md="24">
          <el-card shadow="hover">
            <template #header>
              <div class="card-title">卡密激活</div>
            </template>
            <el-form label-position="top">
              <el-form-item label="输入卡密">
                <el-input
                  v-model.trim="cardCode"
                  placeholder="请输入发卡系统提供的卡密"
                  @keyup.enter="handleActivateCard"
                />
              </el-form-item>
              <el-button type="primary" :loading="activating" @click="handleActivateCard">
                激活
              </el-button>
            </el-form>
          </el-card>
        </el-col>
      </el-row>

      <el-dialog
        v-model="editDialogVisible"
        title="修改基本信息"
        width="520px"
        destroy-on-close
      >
        <el-form label-position="top">
          <el-form-item label="邮箱">
            <el-input v-model.trim="editForm.email" placeholder="请输入邮箱，可留空" />
          </el-form-item>

          <el-divider>修改密码（不修改可留空）</el-divider>

          <el-form-item label="原密码">
            <el-input
              v-model="editForm.oldPassword"
              type="password"
              show-password
              placeholder="请输入原密码"
            />
          </el-form-item>
          <el-form-item label="新密码">
            <el-input
              v-model="editForm.newPassword"
              type="password"
              show-password
              placeholder="请输入新密码（至少6位）"
            />
          </el-form-item>
          <el-form-item label="确认新密码">
            <el-input
              v-model="editForm.confirmPassword"
              type="password"
              show-password
              placeholder="请再次输入新密码"
            />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="editDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="savingProfile" @click="handleSaveProfile">
            保存
          </el-button>
        </template>
      </el-dialog>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { MeProfile, PricingPlan, SubscriptionStatus } from '@/api/me'
import { activateCard, changePassword, getMe, updateProfile } from '@/api/me'

const router = useRouter()
const loading = ref(false)
const activating = ref(false)
const changingPassword = ref(false)
const savingProfile = ref(false)
const editDialogVisible = ref(false)

const profile = ref<MeProfile | null>(null)
const subscription = ref<SubscriptionStatus | null>(null)
const plans = ref<PricingPlan[]>([])

const cardCode = ref('')
const editForm = ref({
  email: '',
  oldPassword: '',
  newPassword: '',
  confirmPassword: '',
})

const formatDateTime = (value?: string | null) => {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(
    date.getDate(),
  ).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(
    date.getMinutes(),
  ).padStart(2, '0')}`
}

const loadData = async () => {
  loading.value = true
  try {
    const res = await getMe()
    profile.value = res.data
    subscription.value = {
      is_active: res.data.subscription.is_active,
      current: res.data.subscription.current,
      remain_days: res.data.subscription.remain_days,
      plans: res.data.plans,
      purchase: res.data.purchase,
    }
    plans.value = res.data.plans
  } finally {
    loading.value = false
  }
}

const handleActivateCard = async () => {
  if (!cardCode.value) {
    ElMessage.warning('请输入卡密')
    return
  }

  activating.value = true
  try {
    const res = await activateCard(cardCode.value)
    subscription.value = res.data
    plans.value = res.data.plans
    cardCode.value = ''
    ElMessage.success('卡密激活成功')
    await loadData()
  } finally {
    activating.value = false
  }
}

const goPurchase = () => router.push('/purchase')

const openEditProfileDialog = () => {
  editForm.value = {
    email: profile.value?.user.email || '',
    oldPassword: '',
    newPassword: '',
    confirmPassword: '',
  }
  editDialogVisible.value = true
}

const handleSaveProfile = async () => {
  const needChangeEmail = (editForm.value.email || '') !== (profile.value?.user.email || '')
  const needChangePassword = Boolean(editForm.value.oldPassword || editForm.value.newPassword || editForm.value.confirmPassword)

  if (!needChangeEmail && !needChangePassword) {
    ElMessage.info('没有需要保存的修改')
    editDialogVisible.value = false
    return
  }

  savingProfile.value = true
  try {
    if (needChangeEmail) {
      await updateProfile(editForm.value.email || null)
    }

    if (needChangePassword) {
      if (!editForm.value.oldPassword || !editForm.value.newPassword) {
        ElMessage.warning('请填写完整密码信息')
        return
      }
      if (editForm.value.newPassword.length < 6) {
        ElMessage.warning('新密码至少 6 位')
        return
      }
      if (editForm.value.newPassword !== editForm.value.confirmPassword) {
        ElMessage.warning('两次输入的新密码不一致')
        return
      }

      changingPassword.value = true
      try {
        await changePassword(editForm.value.oldPassword, editForm.value.newPassword)
      } finally {
        changingPassword.value = false
      }
    }

    await loadData()
    ElMessage.success('基本信息已更新')
    editDialogVisible.value = false
  } finally {
    savingProfile.value = false
  }
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.my-page {
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

.content {
  padding-top: 20px;
}

.back-link {
  color: #409eff;
  text-decoration: none;
  font-size: 14px;
}

h1 {
  margin: 8px 0 0;
  font-size: 24px;
}

.card-title {
  font-weight: 600;
}

.info-row {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  gap: 12px;
}

.label {
  color: #909399;
  white-space: nowrap;
}

.value {
  color: #303133;
  word-break: break-all;
  text-align: right;
}

.info-actions {
  margin-top: 12px;
}

.subscription {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.subscription-meta p {
  margin: 0 0 8px;
  color: #606266;
}

.plan-list {
  margin-top: 12px;
}

.plan-item {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 10px;
  margin-bottom: 8px;
}

.plan-item:last-child {
  margin-bottom: 0;
}

.plan-main {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  color: #303133;
}

.plan-sub {
  margin-top: 4px;
  display: flex;
  justify-content: space-between;
  color: #606266;
  font-size: 13px;
}

.buy-btn {
  margin-top: 8px;
}

.mt16 {
  margin-top: 16px;
}

@media (max-width: 768px) {
  .container {
    padding: 12px;
  }

  h1 {
    font-size: 20px;
  }

  .subscription {
    flex-direction: column;
  }
}
</style>
