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
        <el-descriptions-item label="账号类型">{{ accountTypeLabel(store.profile.account.account_type) }}</el-descriptions-item>
        <el-descriptions-item label="省份">{{ store.profile.province_code }}</el-descriptions-item>
        <el-descriptions-item label="绑定角色">
          <div class="tag-list">
            <el-tag v-for="roleKey in store.profile.roles" :key="roleKey" size="small">
              {{ roleLabel(roleKey) }}
            </el-tag>
          </div>
        </el-descriptions-item>
        <template v-if="isAgentAccount">
          <el-descriptions-item label="余额">¥{{ centsToYuan(store.profile.account.balance_cents) }}</el-descriptions-item>
          <el-descriptions-item label="授信预抵">¥{{ centsToYuan(store.profile.account.credit_prepay_cents) }}</el-descriptions-item>
          <el-descriptions-item label="授信白名单">
            <el-tag :type="store.profile.account.is_credit_whitelisted ? 'success' : 'info'">
              {{ store.profile.account.is_credit_whitelisted ? '已开通' : '未开通' }}
            </el-tag>
          </el-descriptions-item>
        </template>
        <el-descriptions-item label="上次登录">{{ formatDateTime(store.profile.account.last_login_at) }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card v-if="!isAgentAccount" shadow="hover">
      <template #header>
        <div class="card-header">
          <span>账号说明</span>
        </div>
      </template>
      <el-alert
        title="当前是员工后台账号，只用于后台运营、RBAC 和系统配置，不参与代理链路的额度、白名单、授信或结算。"
        type="info"
        :closable="false"
      />
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
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { adminChangePassword } from '@/api/admin'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { accountIdentitySummary, accountTypeLabel, centsToYuan, formatDateTime, roleLabel } from '@/utils/adminConsole'

const store = useAdminConsoleStore()
const changingPassword = ref(false)
const passwordForm = reactive({
  current_password: '',
  new_password: '',
})
const isAgentAccount = computed(() => store.profile?.account.account_type === 'agent')

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
}
</style>
