<template>
  <div class="page-grid">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>账号信息</span>
          <el-tag v-if="store.profile">{{ accountIdentitySummary(store.profile.account) }}</el-tag>
        </div>
      </template>
      <el-descriptions v-if="store.profile" :column="1" border>
        <el-descriptions-item label="显示名">{{ store.profile.account.display_name }}</el-descriptions-item>
        <el-descriptions-item label="账号">{{ store.profile.account.username }}</el-descriptions-item>
        <el-descriptions-item label="省份">{{ store.profile.province_code }}</el-descriptions-item>
        <el-descriptions-item label="绑定角色">
          <div class="tag-list">
            <el-tag v-for="roleKey in store.profile.roles" :key="roleKey" size="small">
              {{ roleLabel(roleKey) }}
            </el-tag>
          </div>
        </el-descriptions-item>
        <el-descriptions-item label="余额">¥{{ centsToYuan(store.profile.account.balance_cents) }}</el-descriptions-item>
        <el-descriptions-item label="授信预抵">¥{{ centsToYuan(store.profile.account.credit_prepay_cents) }}</el-descriptions-item>
        <el-descriptions-item label="授信白名单">
          <el-tag :type="store.profile.account.is_credit_whitelisted ? 'success' : 'info'">
            {{ store.profile.account.is_credit_whitelisted ? '已开通' : '未开通' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="TG 绑定状态">
          <el-tag :type="store.profile.account.tg_binding.bind_status === 'bound' ? 'success' : 'info'">
            {{ store.profile.account.tg_binding.bind_status === 'bound' ? '已绑定' : '未绑定' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="上次登录">{{ formatDateTime(store.profile.account.last_login_at) }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>权限摘要</span>
          <el-tag type="info">{{ store.profile?.permissions?.length || 0 }} 项</el-tag>
        </div>
      </template>
      <div v-if="store.profile" class="tag-list">
        <el-tag v-for="permission in store.profile.permissions" :key="permission" size="small" type="info">
          {{ permission }}
        </el-tag>
      </div>
    </el-card>

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>TG 绑定</span>
          <el-button
            v-if="store.hasPermission('security.update')"
            link
            type="primary"
            @click="issueBindCode"
            :loading="issuingBindCode"
          >
            生成绑定码
          </el-button>
        </div>
      </template>
      <div v-if="store.profile" class="tg-section">
        <el-alert
          :type="store.profile.account.tg_binding.bind_status === 'bound' ? 'success' : 'info'"
          :title="store.profile.account.tg_binding.bind_status === 'bound' ? '当前账号已绑定 Telegram' : '当前账号尚未绑定 Telegram'"
          :closable="false"
        />
        <div v-if="store.profile.account.tg_binding.tg_username" class="tg-meta">
          已绑定：@{{ store.profile.account.tg_binding.tg_username }}
        </div>
        <div v-if="bindResult" class="bind-panel">
          <p>绑定码：<strong>{{ bindResult.bind_code }}</strong></p>
          <p>Bot：@{{ bindResult.bot_username }}</p>
          <p>过期时间：{{ formatDateTime(bindResult.expires_at) }}</p>
          <div class="bind-actions">
            <el-button @click="copyText(bindResult.bind_code)">复制绑定码</el-button>
            <el-button type="primary" @click="openBindUrl">打开 Bot</el-button>
          </div>
        </div>
        <el-button
          v-if="store.profile.account.tg_binding.bind_status === 'bound' && store.hasPermission('security.update')"
          class="danger-action"
          type="danger"
          plain
          :loading="unbinding"
          @click="handleUnbind"
        >
          解绑 Telegram
        </el-button>
      </div>
    </el-card>

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>修改密码</span>
        </div>
      </template>
      <el-form label-position="top">
        <el-form-item label="当前密码">
          <el-input v-model="passwordForm.current_password" type="password" show-password :disabled="!store.hasPermission('security.update')" />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="passwordForm.new_password" type="password" show-password :disabled="!store.hasPermission('security.update')" />
        </el-form-item>
        <el-button v-if="store.hasPermission('security.update')" type="primary" :loading="changingPassword" @click="submitChangePassword">
          更新密码
        </el-button>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { adminChangePassword, adminIssueTgBindCode, adminUnbindTg } from '@/api/admin'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { accountIdentitySummary, centsToYuan, formatDateTime, roleLabel } from '@/utils/adminConsole'

const store = useAdminConsoleStore()
const issuingBindCode = ref(false)
const unbinding = ref(false)
const changingPassword = ref(false)
const bindResult = ref<{ bind_code: string; expires_at: string; bot_username: string; bot_bind_url: string } | null>(null)
const passwordForm = reactive({
  current_password: '',
  new_password: '',
})

const copyText = async (value: string) => {
  await navigator.clipboard.writeText(value)
  ElMessage.success('已复制')
}

const openBindUrl = () => {
  if (!bindResult.value) return
  window.open(bindResult.value.bot_bind_url, '_blank', 'noopener')
}

const issueBindCode = async () => {
  issuingBindCode.value = true
  try {
    const response = await adminIssueTgBindCode()
    bindResult.value = response.data
  } finally {
    issuingBindCode.value = false
  }
}

const handleUnbind = async () => {
  unbinding.value = true
  try {
    await adminUnbindTg()
    bindResult.value = null
    await store.loadProfile()
    ElMessage.success('TG 已解绑')
  } finally {
    unbinding.value = false
  }
}

const submitChangePassword = async () => {
  if (!passwordForm.current_password || !passwordForm.new_password) {
    ElMessage.warning('请填写当前密码和新密码')
    return
  }
  changingPassword.value = true
  try {
    await adminChangePassword(passwordForm)
    passwordForm.current_password = ''
    passwordForm.new_password = ''
    await store.loadProfile()
    ElMessage.success('密码已更新')
  } finally {
    changingPassword.value = false
  }
}

onMounted(async () => {
  await store.loadProfile()
})
</script>

<style scoped>
.page-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 20px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.tg-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.tg-meta {
  color: #475569;
}

.bind-panel {
  padding: 16px;
  border-radius: 12px;
  background: #f8fafc;
}

.bind-actions {
  display: flex;
  gap: 12px;
  margin-top: 12px;
}

.danger-action {
  align-self: flex-start;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

@media (max-width: 768px) {
  .page-grid {
    grid-template-columns: 1fr;
    gap: 16px;
  }

  .card-header {
    align-items: flex-start;
    flex-direction: column;
    gap: 10px;
  }

  .bind-actions {
    flex-direction: column;
  }

  .bind-actions :deep(.el-button),
  .danger-action {
    width: 100%;
  }
}
</style>
