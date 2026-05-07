<template>
  <div class="my-page">
    <header class="header">
      <div class="container">
        <router-link to="/accounts" class="back-link">← 返回账号管理</router-link>
        <div class="brand-header">
          <img class="brand-logo" src="/quanqiu.png" alt="全球通" />
          <h1>全球通 · 我的</h1>
        </div>
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
              <div class="card-title">当前授权</div>
            </template>
            <div class="license-status-card">
              <el-tag :type="licenseStatus?.is_active ? 'success' : 'warning'" size="large">
                {{ licenseStatus?.is_active ? '授权生效中' : '当前未授权' }}
              </el-tag>
              <div class="license-status-meta">
                <p>剩余天数：{{ licenseStatus?.remain_days ?? 0 }}</p>
                <p>到期时间：{{ formatDateTime(licenseStatus?.current_authorization?.end_at) }}</p>
                <p>
                  可登录 TG 账号：
                  {{ `${profile?.authorization_overview?.account_count ?? 0} / 1` }}
                </p>
                <p>授权来源：{{ licenseStatus?.current_authorization?.grant_source_label || '未开通' }}</p>
              </div>
            </div>
            <el-alert
              title="点击“系统账号绑定到 TG Bot”后，可把当前系统账号直接绑定到 TG Bot 中使用。"
              type="info"
              :closable="false"
              class="license-status-tip"
            />
            <div class="plan-list">
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
              type="primary"
              class="buy-btn"
              @click="goPurchase"
            >
              去购买卡密
            </el-button>
            <el-button class="bind-bot-btn" @click="goBindBot">
              系统账号绑定到 TG Bot
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
              <el-alert
                title="卡密只会续费当前系统账号下的唯一授权，不再新开第二条授权。首次绑定 TG 账号会自动赠送 7 天试用。"
                type="info"
                :closable="false"
                class="license-status-tip"
              />
              <el-button type="primary" :loading="activating" @click="handleActivateCard">
                激活
              </el-button>
            </el-form>
          </el-card>
        </el-col>
      </el-row>

      <el-row :gutter="16" class="mt16" v-if="profile?.current_authorization">
        <el-col :xs="24" :md="24">
          <el-card shadow="hover">
            <template #header>
              <div class="card-title">当前授权详情</div>
            </template>
            <div class="plan-list">
              <div class="plan-item" :key="profile.current_authorization.authorization_id">
                <div class="plan-main">
                  <strong>{{ profile.current_authorization.account_name || '未绑定 TG 账号' }}</strong>
                  <span>{{ profile.current_authorization.status === 'active' ? '生效中' : profile.current_authorization.status === 'expired' ? '已过期' : '未启用' }}</span>
                </div>
                <div class="plan-sub">
                  <span>开始 {{ formatDateTime(profile.current_authorization.start_at) }}</span>
                  <span>到期 {{ formatDateTime(profile.current_authorization.end_at) }}</span>
                </div>
                <div class="plan-sub">
                  <span>累计 {{ profile.current_authorization.duration_days }} 天</span>
                  <span>剩余 {{ profile.current_authorization.remaining_days ?? 0 }} 天</span>
                  <span>已用卡密 {{ profile.current_authorization.card_count }}</span>
                </div>
                <div class="plan-sub">
                  <span>来源 {{ profile.current_authorization.grant_source_label || (profile.current_authorization.grant_source === 'bot_trial' ? '首次绑定 TG 赠送试用' : '卡密续费') }}</span>
                  <span>首张卡密 {{ profile.current_authorization.source_card_code_masked || '-' }}</span>
                  <span>最近续费 {{ profile.current_authorization.latest_card_code_masked || '-' }}</span>
                </div>
                <div class="slot-actions">
                  <el-button type="warning" plain size="small" @click="openRenewDialog(profile.current_authorization)">
                    续费卡密
                  </el-button>
                </div>
              </div>
            </div>
          </el-card>
        </el-col>
      </el-row>

      <ResponsiveFormLayer
        v-model="renewDialogVisible"
        title="续费当前授权"
        width="420px"
      >
        <div v-if="renewTargetSlot">
          <p class="dialog-tip">为当前唯一授权追加新的卡密时长。</p>
          <p class="password-hint">绑定账号：{{ renewTargetSlot.account_name || '未绑定账号' }}</p>
          <p class="password-hint">当前到期：{{ formatDateTime(renewTargetSlot.end_at) }}</p>
          <el-input
            v-model.trim="renewCardCode"
            placeholder="请输入新的续费卡密"
            @keyup.enter="handleRenewSlot"
          />
        </div>
        <template #footer>
          <el-button @click="renewDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="renewingSlot" @click="handleRenewSlot">
            确认续费
          </el-button>
        </template>
      </ResponsiveFormLayer>

      <ResponsiveFormLayer
        v-model="editDialogVisible"
        title="修改基本信息"
        width="520px"
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
      </ResponsiveFormLayer>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { CurrentAuthorization, MeProfile, PricingPlan } from '@/api/me'
import { activateCard, changePassword, getMe, updateProfile } from '@/api/me'
import { createBotBindLink } from '@/api/login'
import ResponsiveFormLayer from '@/components/responsive/ResponsiveFormLayer.vue'

const router = useRouter()
const loading = ref(false)
const activating = ref(false)
const changingPassword = ref(false)
const savingProfile = ref(false)
const editDialogVisible = ref(false)

const profile = ref<MeProfile | null>(null)
const licenseStatus = ref<MeProfile['authorization_status'] | null>(null)
const plans = ref<PricingPlan[]>([])
const cardCode = ref('')
const renewDialogVisible = ref(false)
const renewingSlot = ref(false)
const renewTargetSlot = ref<CurrentAuthorization | null>(null)
const renewCardCode = ref('')
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

const goBindBot = async () => {
  try {
    const res = await createBotBindLink()
    if (!res.data.bot_bind_url) {
      ElMessage.warning('当前未配置 TG Bot 入口，请稍后重试')
      return
    }
    window.location.href = res.data.bot_bind_url
  } catch {
    // HTTP errors already handled by the response interceptor
  }
}

const loadData = async () => {
  loading.value = true
  try {
    const res = await getMe()
    profile.value = res.data
    licenseStatus.value = res.data.authorization_status
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
    licenseStatus.value = res.data
    plans.value = res.data.plans
    cardCode.value = ''
    ElMessage.success('授权续费成功')
    await loadData()
  } finally {
    activating.value = false
  }
}

const openRenewDialog = (slot: CurrentAuthorization) => {
  renewTargetSlot.value = slot
  renewCardCode.value = ''
  renewDialogVisible.value = true
}

const handleRenewSlot = async () => {
  if (!renewTargetSlot.value || !renewCardCode.value) {
    ElMessage.warning('请输入续费 Key')
    return
  }
  renewingSlot.value = true
  try {
    await activateCard(renewCardCode.value)
    ElMessage.success('授权续费成功')
    renewDialogVisible.value = false
    renewCardCode.value = ''
    await loadData()
  } finally {
    renewingSlot.value = false
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

.brand-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-logo {
  width: 72px;
  height: auto;
  display: block;
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

.license-status-card {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.license-status-meta p {
  margin: 0 0 8px;
  color: #606266;
}

.license-status-tip {
  margin: 12px 0;
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

  .license-status-card {
    flex-direction: column;
  }
}
</style>
