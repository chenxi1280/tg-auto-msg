<template>
  <div class="admin-auth-page">
    <div class="auth-shell">
      <section class="brand-panel">
        <img class="brand-logo" src="/quanqiu.png" alt="全球通" />
        <p class="eyebrow">Province Admin Console</p>
        <h1>省级总代与多级代理后台</h1>
        <p class="desc">
          使用后台账号登录，进入账号中心、卡密中心、额度配置与审计中心。
        </p>
        <ul class="feature-list">
          <li>支持后台员工账号与代理链路账号统一登录</li>
          <li>支持 TG 绑定与统一后台运营管理</li>
          <li>支持卡密批次、Excel 导出与 10 条内快速复制</li>
        </ul>
      </section>

      <section class="form-panel">
        <div class="panel-card">
          <h2>后台登录</h2>
          <p class="panel-desc">登录后会自动校验当前后台权限与省份归属。</p>

          <el-form label-position="top" @submit.prevent>
            <el-form-item label="账号">
              <el-input
                v-model.trim="form.username"
                placeholder="请输入后台账号"
                autocomplete="username"
                @keyup.enter="submitLogin"
              />
            </el-form-item>
            <el-form-item label="密码">
              <el-input
                v-model="form.password"
                type="password"
                show-password
                placeholder="请输入密码"
                autocomplete="current-password"
                @keyup.enter="submitLogin"
              />
            </el-form-item>
            <el-button class="submit-btn" type="primary" :loading="loading" @click="submitLogin">
              登录后台
            </el-button>
          </el-form>

          <p class="footnote">
            初始化账号由部署环境自动创建，首次登录会被要求尽快修改密码。
          </p>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { adminLogin, hasAdminSession, setAdminAccessToken } from '@/api/admin'

const router = useRouter()
const loading = ref(false)

const form = reactive({
  username: '',
  password: '',
})

const submitLogin = async () => {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入后台账号和密码')
    return
  }

  loading.value = true
  try {
    const response = await adminLogin({
      username: form.username,
      password: form.password,
    })
    setAdminAccessToken(response.data.access_token)
    ElMessage.success('登录成功')
    await router.replace('/admin/dashboard')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  if (hasAdminSession()) {
    await router.replace('/admin/dashboard')
  }
})
</script>

<style scoped>
.admin-auth-page {
  min-height: 100vh;
  padding: 24px;
  background:
    radial-gradient(circle at top left, rgba(15, 103, 255, 0.16), transparent 34%),
    radial-gradient(circle at bottom right, rgba(12, 189, 120, 0.14), transparent 28%),
    linear-gradient(135deg, #f5f8ff 0%, #eef4f1 100%);
}

.auth-shell {
  min-height: calc(100vh - 48px);
  max-width: 1160px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: 1.1fr 0.9fr;
  gap: 24px;
  align-items: stretch;
}

.brand-panel,
.panel-card {
  border-radius: 28px;
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(18px);
  box-shadow: 0 18px 50px rgba(18, 47, 88, 0.12);
}

.brand-panel {
  padding: 40px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.brand-logo {
  width: 132px;
  max-width: 38%;
  margin-bottom: 20px;
}

.eyebrow {
  margin: 0 0 10px;
  font-size: 13px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #0f67ff;
  font-weight: 700;
}

h1 {
  margin: 0;
  font-size: 40px;
  line-height: 1.15;
  color: #17233b;
}

.desc {
  margin: 18px 0 0;
  font-size: 16px;
  line-height: 1.8;
  color: #4f607c;
}

.feature-list {
  margin: 28px 0 0;
  padding-left: 20px;
  color: #233453;
  line-height: 1.9;
}

.form-panel {
  display: flex;
  align-items: center;
  justify-content: center;
}

.panel-card {
  width: 100%;
  max-width: 440px;
  padding: 34px 28px 28px;
}

h2 {
  margin: 0;
  font-size: 28px;
  color: #17233b;
}

.panel-desc {
  margin: 10px 0 28px;
  color: #5e6f8d;
  line-height: 1.7;
}

.submit-btn {
  width: 100%;
  margin-top: 8px;
  height: 44px;
}

.footnote {
  margin: 20px 0 0;
  color: #7182a0;
  font-size: 13px;
  line-height: 1.7;
}

@media (max-width: 900px) {
  .auth-shell {
    grid-template-columns: 1fr;
  }

  .brand-panel {
    padding: 28px 24px;
  }

  .panel-card {
    max-width: none;
  }

  h1 {
    font-size: 32px;
  }
}
</style>
