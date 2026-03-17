<template>
  <div class="admin-auth-page">
    <div class="panel">
      <img class="brand-logo" src="/quanqiu.png" alt="全球通" />
      <h1>全球通 · 管理员入口</h1>
      <p class="desc">请输入管理员密钥后进入后台</p>
      <el-input
        v-model.trim="token"
        type="password"
        show-password
        placeholder="ADMIN_API_TOKEN"
        @keyup.enter="enterAdmin"
      />
      <div class="actions">
        <el-button type="primary" :loading="loading" @click="enterAdmin">进入后台</el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { adminListPlans, setAdminToken } from '@/api/admin'

const token = ref('')
const loading = ref(false)
const router = useRouter()

const enterAdmin = async () => {
  if (!token.value) {
    ElMessage.warning('请输入管理员密钥')
    return
  }
  loading.value = true
  try {
    setAdminToken(token.value)
    await adminListPlans()
    ElMessage.success('验证通过')
    router.replace('/admin/dashboard')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.admin-auth-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f3f5f8;
  padding: 16px;
}

.panel {
  width: 100%;
  max-width: 420px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.08);
  padding: 24px;
}

h1 {
  margin: 0 0 8px;
  font-size: 24px;
}

.brand-logo {
  width: 120px;
  max-width: 42%;
  height: auto;
  display: block;
  margin: 0 auto 12px;
}

.desc {
  margin: 0 0 16px;
  color: #606266;
}

.actions {
  margin-top: 14px;
}
</style>
