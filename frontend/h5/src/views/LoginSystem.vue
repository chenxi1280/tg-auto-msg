<template>
  <div class="login-page">
    <div class="login-container">
      <div class="login-header">
        <img class="brand-logo" src="/quanqiu.png" alt="全球通" />
        <h1>全球通</h1>
        <p class="subtitle">Web 管理入口，可使用 Bot 注册后获得的账号密码登录</p>
      </div>

      <div class="bot-tip">
        推荐先在 Telegram Bot 内完成注册、激活和账号登录，Web 端用于补充管理任务、账号和订阅信息。
      </div>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        class="login-form"
        @keyup.enter="handleLogin"
      >
        <el-form-item label="用户名" prop="username">
          <el-input
            v-model="form.username"
            placeholder="请输入用户名"
            prefix-icon="User"
            size="large"
          />
        </el-form-item>

        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            prefix-icon="Lock"
            show-password
            size="large"
          />
        </el-form-item>

        <div class="form-actions">
          <el-button
            type="primary"
            class="submit-btn"
            :loading="loading"
            @click="handleLogin"
            size="large"
          >
            登录
          </el-button>
        </div>

        <div class="form-footer">
          <span>还没有账号？</span>
          <router-link to="/register">Web 注册</router-link>
        </div>
      </el-form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import * as authApi from '@/api/auth'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const formRef = ref<FormInstance>()
const loading = ref(false)

const form = reactive({
  username: '',
  password: ''
})

const rules = reactive<FormRules>({
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, message: '长度至少 3 个字符', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '长度至少 6 个字符', trigger: 'blur' }
  ]
})

const handleLogin = async () => {
  if (!formRef.value) return

  await formRef.value.validate(async (valid) => {
    if (valid) {
      loading.value = true
      try {
        const username = form.username.trim()
        if (!username) {
          ElMessage.warning('请输入用户名')
          return
        }

        const res = await authApi.login({
          username,
          password: form.password
        })

        // 兼容处理：支持 { success, data } 与直接返回 data 两种结构
        const data = 'data' in (res as any) ? (res as any).data : (res as any)
        const { user, access_token } = data

        if (!access_token || !user?.id) {
          throw new Error('登录响应数据不完整')
        }

        // 更新 Store
        userStore.login(user, access_token)

        ElMessage.success('登录成功')
        const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/accounts'
        router.replace(redirect)

      } catch (err: any) {
        console.error('登录失败:', err)
        // 错误已经在 request 拦截器中处理了，这里不需要重复弹窗，
        // 除非我们需要特定的错误处理逻辑
      } finally {
        loading.value = false
      }
    }
  })
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 1rem;
}

.login-container {
  background: white;
  border-radius: 16px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
  max-width: 400px;
  width: 100%;
  padding: 2.5rem;
}

.login-header {
  text-align: center;
  margin-bottom: 2rem;
}

.brand-logo {
  width: 120px;
  max-width: 42%;
  height: auto;
  display: block;
  margin: 0 auto 0.8rem;
}

.login-header h1 {
  margin: 0 0 0.5rem 0;
  font-size: 1.8rem;
  color: #2c3e50;
}

.subtitle {
  color: #6c757d;
  margin: 0;
  font-size: 0.9rem;
}

.submit-btn {
  width: 100%;
  font-weight: 600;
  letter-spacing: 1px;
}

.bot-tip {
  margin-bottom: 1rem;
  padding: 0.9rem 1rem;
  border-radius: 12px;
  background: #f3f5ff;
  color: #4a5680;
  font-size: 0.9rem;
  line-height: 1.6;
}

.form-footer {
  margin-top: 1.5rem;
  text-align: center;
  font-size: 0.9rem;
  color: #6c757d;
}

.form-footer a {
  color: #667eea;
  text-decoration: none;
  font-weight: 600;
  margin-left: 0.5rem;
}

.form-footer a:hover {
  text-decoration: underline;
}

@media (max-width: 480px) {
  .login-container {
    padding: 1.2rem;
    border-radius: 12px;
  }

  .login-header {
    margin-bottom: 1rem;
  }

  .login-header h1 {
    font-size: 1.4rem;
  }
}
</style>
