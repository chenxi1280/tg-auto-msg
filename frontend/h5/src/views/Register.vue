<template>
  <div class="register-page">
    <div class="register-container">
      <div class="register-header">
        <h1>注册账号</h1>
        <p class="subtitle">创建您的系统管理账号</p>
      </div>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        class="register-form"
        @keyup.enter="handleRegister"
      >
        <el-form-item label="用户名" prop="username">
          <el-input
            v-model="form.username"
            placeholder="设置用户名（3-50字符）"
            prefix-icon="User"
            size="large"
          />
        </el-form-item>

        <el-form-item label="邮箱（可选）" prop="email">
          <el-input
            v-model="form.email"
            placeholder="请输入邮箱"
            prefix-icon="Message"
            size="large"
          />
        </el-form-item>

        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="设置密码（至少6字符）"
            prefix-icon="Lock"
            show-password
            size="large"
          />
        </el-form-item>

        <el-form-item label="确认密码" prop="confirmPassword">
          <el-input
            v-model="form.confirmPassword"
            type="password"
            placeholder="请再次输入密码"
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
            @click="handleRegister"
            size="large"
          >
            注册
          </el-button>
        </div>

        <div class="form-footer">
          <span>已有账号？</span>
          <router-link to="/login">立即登录</router-link>
        </div>
      </el-form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { User, Lock, Message } from '@element-plus/icons-vue'
import * as authApi from '@/api/auth'

const router = useRouter()
const formRef = ref<FormInstance>()
const loading = ref(false)

const form = reactive({
  username: '',
  email: '',
  password: '',
  confirmPassword: ''
})

const validatePass2 = (rule: any, value: any, callback: any) => {
  if (value === '') {
    callback(new Error('请再次输入密码'))
  } else if (value !== form.password) {
    callback(new Error('两次输入密码不一致!'))
  } else {
    callback()
  }
}

const rules = reactive<FormRules>({
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 50, message: '长度在 3 到 50 个字符', trigger: 'blur' }
  ],
  email: [
    { type: 'email', message: '请输入正确的邮箱地址', trigger: ['blur', 'change'] }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '长度至少 6 个字符', trigger: 'blur' }
  ],
  confirmPassword: [
    { validator: validatePass2, trigger: 'blur' }
  ]
})

const handleRegister = async () => {
  if (!formRef.value) return

  await formRef.value.validate(async (valid) => {
    if (valid) {
      loading.value = true
      try {
        const res = await authApi.register({
          username: form.username,
          password: form.password,
          email: form.email || undefined
        })

        if (!('data' in (res as any)) || !(res as any).data?.access_token) {
          throw new Error('注册响应数据不完整')
        }

        ElMessage.success('注册成功，请登录')
        router.push('/login')

      } catch (err: any) {
        console.error('注册失败:', err)
      } finally {
        loading.value = false
      }
    }
  })
}
</script>

<style scoped>
.register-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 1rem;
}

.register-container {
  background: white;
  border-radius: 16px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
  max-width: 400px;
  width: 100%;
  padding: 2.5rem;
}

.register-header {
  text-align: center;
  margin-bottom: 2rem;
}

.register-header h1 {
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
  .register-container {
    padding: 1.2rem;
    border-radius: 12px;
  }

  .register-header {
    margin-bottom: 1rem;
  }

  .register-header h1 {
    font-size: 1.4rem;
  }
}
</style>
