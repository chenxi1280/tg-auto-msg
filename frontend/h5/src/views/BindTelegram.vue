<template>
  <div class="login-page">
    <div class="login-container">
      <!-- 头部 -->
      <div class="login-header">
        <router-link to="/accounts" class="back-link">← 返回账号列表</router-link>
        <h1>绑定 Telegram 账号</h1>
      </div>

      <!-- 扫码阶段 -->
      <div v-if="status === LoginStatus.SCANNING" class="login-content">
        <div class="qr-section">
          <div class="qr-placeholder">
            <div v-if="loading" class="loading-spinner">
              <el-icon class="is-loading"><Loading /></el-icon>
              <span>生成二维码中...</span>
            </div>
            <div v-else-if="qrUrl" class="qr-code">
              <!-- 这里使用 QR Code 库显示二维码 -->
              <img :src="qrUrl" alt="扫码登录" />
            </div>
          </div>
          <div class="instructions">
            <h3>扫码绑定</h3>
            <ol class="steps">
              <li>打开 Telegram 手机应用</li>
              <li>点击 Settings → Devices → Link Desktop Device</li>
              <li>扫描上方二维码</li>
            </ol>
          </div>
        </div>
      </div>

      <!-- 绑定码显示阶段 -->
      <div v-if="status === LoginStatus.CONFIRMED" class="login-content">
        <div class="bind-code-section">
          <div class="success-icon">✓</div>
          <h3>扫码成功！</h3>
          <p class="bind-code-label">绑定码</p>
          <div class="bind-code">{{ bindCode }}</div>
          <div class="bind-instructions">
            <p>请发送以下命令到 Telegram Bot：</p>
            <code class="command">/bind {{ bindCode }}</code>
          </div>
          <el-button type="primary" @click="copyCommand">
            复制命令
          </el-button>
        </div>
      </div>

      <!-- 错误状态 -->
      <div v-if="status === LoginStatus.ERROR" class="login-content">
        <div class="error-section">
          <div class="error-icon">⚠️</div>
          <h3>绑定失败</h3>
          <p>{{ error || '未知错误' }}</p>
          <el-button type="primary" @click="handleRetry">
            重试
          </el-button>
        </div>
      </div>

      <!-- 过期状态 -->
      <div v-if="status === LoginStatus.EXPIRED" class="login-content">
        <div class="expired-section">
          <div class="expired-icon">⏱️</div>
          <h3>会话已过期</h3>
          <p>绑定会话已过期，请重新开始</p>
          <el-button type="primary" @click="handleRetry">
            重新生成
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import { createLoginSession, getLoginStatus, LoginStatus, bindAccount } from '@/api/login'
import { getSubscription } from '@/api/me'
import QRCode from 'qrcode'

const router = useRouter()

// 状态
const status = ref<LoginStatus>(LoginStatus.PENDING)
const loginId = ref('')
const bindCode = ref('')
const qrUrl = ref('')
const qrUrlData = ref('')
const loading = ref(false)
const error = ref('')

let pollTimer: ReturnType<typeof setInterval> | null = null

// 创建登录会话
const createSession = async () => {
  loading.value = true
  status.value = LoginStatus.PENDING
  error.value = ''
  qrUrl.value = ''
  qrUrlData.value = ''

  try {
    const res = await createLoginSession()
    loginId.value = res.data.login_id
    qrUrlData.value = res.data.qr_url
    status.value = LoginStatus.SCANNING

    await generateQRWithLogo()
    startPolling()
  } catch (err: any) {
    error.value = err.message || '创建绑定会话失败'
    status.value = LoginStatus.ERROR
  } finally {
    loading.value = false
  }
}

// 轮询状态
const pollStatus = async () => {
  if (!loginId.value) return

  try {
    const res = await getLoginStatus(loginId.value)
    const data = res.data

    status.value = data.status

    // 若后端刷新了二维码，更新前端展示
    if (data.qr_url && data.qr_url !== qrUrlData.value) {
      qrUrlData.value = data.qr_url
      await generateQRWithLogo()
    }

    if (data.status === LoginStatus.CONFIRMED && data.bind_code) {
      bindCode.value = data.bind_code

      // 自动尝试绑定
      try {
        await bindAccount(data.bind_code)

        ElMessage.success('绑定成功！')
        stopPolling()

        // 延迟跳转
        setTimeout(() => {
          router.push('/accounts')
        }, 1500)
      } catch (err: any) {
        // 如果后端还在处理，可能需要用户手动发 /bind，这里保持显示绑定码界面
        console.error('自动绑定请求失败(可能需手动发送命令):', err)
      }
      return
    } else if (data.status === LoginStatus.ERROR) {
      error.value = data.error || '绑定失败'
      stopPolling()
    } else if (data.status === LoginStatus.EXPIRED) {
      stopPolling()
    }
  } catch (err: any) {
    console.error('获取状态失败:', err)
  }
}

const startPolling = () => {
  pollStatus()
  pollTimer = setInterval(pollStatus, 2000)
}

const stopPolling = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const generateQRWithLogo = async () => {
  if (!qrUrlData.value) return

  try {
    const canvas = document.createElement('canvas')
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const size = 300
    canvas.width = size
    canvas.height = size

    await QRCode.toCanvas(canvas, qrUrlData.value, {
      width: size,
      margin: 2,
      color: { dark: '#000000', light: '#FFFFFF' }
    })

    const logoSvg = `
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#0088cc">
        <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69a.2.2 0 00-.05-.18c-.06-.05-.14-.03-.21-.02-.09.02-1.49.95-4.22 2.79-.4.27-.76.41-1.08.4-.36-.01-1.04-.2-1.55-.37-.63-.2-1.12-.31-1.08-.66.02-.18.27-.36.74-.55 2.92-1.27 4.86-2.11 5.83-2.51 2.78-1.16 3.35-1.36 3.73-1.36.08 0 .27.02.39.12.1.08.13.19.14.27-.01.06.01.24 0 .38z"/>
      </svg>
    `
    const logoUrl = 'data:image/svg+xml;base64,' + btoa(logoSvg)
    const logo = new Image()

    logo.onload = () => {
      const logoSize = 50
      const x = (size - logoSize) / 2
      const y = (size - logoSize) / 2
      ctx.fillStyle = '#FFFFFF'
      const padding = 5
      const radius = 8
      ctx.beginPath()
      ctx.roundRect(x - padding, y - padding, logoSize + padding * 2, logoSize + padding * 2, radius)
      ctx.fill()
      ctx.drawImage(logo, x, y, logoSize, logoSize)
      qrUrl.value = canvas.toDataURL('image/png')
    }
    logo.src = logoUrl
  } catch (err) {
    console.error('生成二维码失败:', err)
  }
}

const copyCommand = () => {
  const command = `/bind ${bindCode.value}`
  navigator.clipboard.writeText(command)
    .then(() => ElMessage.success('命令已复制'))
    .catch(() => ElMessage.error('复制失败'))
}

const handleRetry = () => createSession()

onMounted(async () => {
  try {
    const res = await getSubscription()
    if (!res.data.is_active) {
      ElMessage.warning('未开通套餐，请先购买套餐')
      router.replace('/purchase')
      return
    }
  } catch (_err) {
    router.replace('/accounts')
    return
  }
  createSession()
})

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
/* 复用之前的样式，稍作调整 */
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f7fa; /* 改为浅色背景，区别于登录页 */
  padding: 1rem;
}

.login-container {
  background: white;
  border-radius: 16px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.05);
  max-width: 500px;
  width: 100%;
  overflow: hidden;
}

.login-header {
  padding: 1.5rem;
  border-bottom: 1px solid #eee;
  text-align: center;
}

.login-header h1 {
  margin: 0.5rem 0 0 0;
  font-size: 1.5rem;
  color: #2c3e50;
}

.back-link {
  color: #667eea;
  text-decoration: none;
  font-size: 0.9rem;
  float: left;
}

.login-content {
  padding: 2rem;
}

.qr-placeholder {
  width: 300px;
  height: 300px;
  margin: 0 auto 2rem;
  border: 2px dashed #ddd;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.qr-code img {
  max-width: 100%;
  border-radius: 8px;
}

.steps {
  text-align: left;
  color: #606266;
  line-height: 1.8;
}

.bind-code {
  font-size: 2.5rem;
  font-weight: 700;
  letter-spacing: 0.3em;
  color: #667eea;
  margin: 1rem 0;
  text-align: center;
  font-family: monospace;
}

.bind-code-section, .error-section, .expired-section {
  text-align: center;
}

.command {
  background: #f0f2f5;
  padding: 0.5rem;
  border-radius: 4px;
  color: #e6a23c;
  display: block;
  margin: 0.5rem 0;
}

@media (max-width: 640px) {
  .login-container {
    border-radius: 12px;
  }

  .login-header {
    padding: 1rem;
  }

  .login-header h1 {
    font-size: 1.25rem;
  }

  .back-link {
    float: none;
    display: inline-block;
    margin-bottom: 0.5rem;
  }

  .login-content {
    padding: 1rem;
  }

  .qr-placeholder {
    width: 230px;
    height: 230px;
    margin-bottom: 1rem;
  }

  .bind-code {
    font-size: 2rem;
    letter-spacing: 0.15em;
    word-break: break-all;
  }
}
</style>
