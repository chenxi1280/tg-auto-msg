<template>
  <div class="login-page">
    <div class="login-container">
      <!-- 头部 -->
      <div class="login-header">
        <router-link to="/accounts" class="back-link">← 返回账号列表</router-link>
        <h1>绑定 Telegram 账号</h1>
      </div>

      <!-- 扫码阶段 -->
      <div
        v-if="status === LoginStatus.PENDING || status === LoginStatus.SCANNING || status === LoginStatus.PASSWORD_REQUIRED"
        class="login-content"
      >
        <div class="qr-section">
          <div class="qr-placeholder">
            <div v-if="loading" class="loading-spinner">
              <el-icon class="is-loading"><Loading /></el-icon>
              <span>生成二维码中...</span>
            </div>
            <div v-else-if="awaitingConfirm || status === LoginStatus.PASSWORD_REQUIRED" class="awaiting-card">
              <el-icon class="is-loading awaiting-card-icon"><Loading /></el-icon>
              <strong v-if="status === LoginStatus.PASSWORD_REQUIRED">已扫码，等待输入二步密码</strong>
              <strong v-else>已扫码，正在等待 Telegram 确认</strong>
              <p v-if="status === LoginStatus.PASSWORD_REQUIRED">
                账号已开启二步验证，请在弹框中输入密码完成登录。
              </p>
              <p v-else>请在手机上完成确认。若长时间无变化，可重新显示二维码后再次扫码。</p>
              <el-button v-if="status !== LoginStatus.PASSWORD_REQUIRED" text type="primary" @click="awaitingConfirm = false">
                重新显示二维码
              </el-button>
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
              <li>扫描上方二维码并在手机上确认登录</li>
            </ol>
            <p v-if="status === LoginStatus.PENDING && !awaitingConfirm" class="scan-tip">
              请扫描二维码登录。扫码完成后系统会自动回调，并切换为等待状态。
            </p>
            <div v-if="awaitingConfirm || status === LoginStatus.PASSWORD_REQUIRED" class="scan-progress">
              <el-icon class="is-loading scan-progress-icon"><Loading /></el-icon>
              <div class="scan-progress-text">
                <strong v-if="status === LoginStatus.PASSWORD_REQUIRED">已识别扫码，等待输入二步密码</strong>
                <strong v-else>已识别扫码，正在等待手机确认登录</strong>
                <p v-if="status === LoginStatus.PASSWORD_REQUIRED">请在弹框中输入 Telegram 二步密码完成登录。</p>
                <p v-else>系统正在处理登录回调，通常需要 5 秒左右。</p>
              </div>
            </div>
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
          <el-button type="primary" @click="copyCommandAndGoHome">
            复制并返回首页
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

      <el-dialog
        v-model="passwordDialogVisible"
        title="输入 Telegram 二步密码"
        width="420px"
        :close-on-click-modal="false"
        :close-on-press-escape="false"
      >
        <p class="dialog-tip">该账号已启用两步验证，请输入密码完成登录。</p>
        <p v-if="passwordHint" class="password-hint">密码提示：{{ passwordHint }}</p>
        <el-input
          v-model="password"
          type="password"
          show-password
          placeholder="请输入 Telegram 二步密码"
          @keyup.enter="handleSubmitPassword"
        />
        <template #footer>
          <el-button @click="handleRetry">重新扫码</el-button>
          <el-button :loading="submittingPassword" type="primary" @click="handleSubmitPassword">
            提交密码
          </el-button>
        </template>
      </el-dialog>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import { createLoginSession, getLoginStatus, LoginStatus, submitLoginPassword } from '@/api/login'
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
const password = ref('')
const passwordHint = ref('')
const submittingPassword = ref(false)
const awaitingConfirm = ref(false)
const passwordDialogVisible = ref(false)

let pollTimer: ReturnType<typeof setInterval> | null = null

// 创建登录会话
const createSession = async () => {
  loading.value = true
  status.value = LoginStatus.PENDING
  error.value = ''
  qrUrl.value = ''
  qrUrlData.value = ''
  password.value = ''
  passwordHint.value = ''
  awaitingConfirm.value = false
  passwordDialogVisible.value = false

  try {
    const res = await createLoginSession()
    loginId.value = res.data.login_id
    qrUrlData.value = res.data.qr_url
    status.value = LoginStatus.PENDING

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
      awaitingConfirm.value = false
      await generateQRWithLogo()
    }

    awaitingConfirm.value = data.status === LoginStatus.SCANNING || data.status === LoginStatus.PASSWORD_REQUIRED

    if (data.status === LoginStatus.CONFIRMED && data.bind_code) {
      bindCode.value = data.bind_code
      stopPolling()
      return
    } else if (data.status === LoginStatus.PASSWORD_REQUIRED) {
      passwordHint.value = data.password_hint || ''
      error.value = data.error || ''
      awaitingConfirm.value = true
      passwordDialogVisible.value = true
      stopPolling()
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

const copyCommandAndGoHome = async () => {
  const command = `/bind ${bindCode.value}`
  try {
    await navigator.clipboard.writeText(command)
    ElMessage.success('绑定命令已复制，正在返回首页')
  } catch (_err) {
    ElMessage.warning('复制失败，正在返回首页')
  } finally {
    await router.replace({
      path: '/accounts',
      query: {
        refresh: '1',
        t: String(Date.now())
      }
    })
  }
}

const handleSubmitPassword = async () => {
  if (!loginId.value) return
  if (!password.value) {
    ElMessage.warning('请输入 Telegram 二步密码')
    return
  }

  submittingPassword.value = true
  try {
    const res = await submitLoginPassword(loginId.value, password.value)
    bindCode.value = res.data.bind_code
    status.value = LoginStatus.CONFIRMED
    error.value = ''
    passwordDialogVisible.value = false
    ElMessage.success('登录成功，请发送绑定命令到 Bot')
  } catch (err: any) {
    error.value = err.message || '二步密码验证失败'
    ElMessage.error(error.value)
  } finally {
    submittingPassword.value = false
  }
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

.scan-tip {
  margin: 1rem 0 0;
  color: #606266;
  line-height: 1.6;
}

.scan-progress {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  margin-top: 1.25rem;
  padding: 0.9rem 1rem;
  border-radius: 12px;
  background: #f5f8ff;
  border: 1px solid #dbe5ff;
  text-align: left;
}

.scan-progress-icon {
  color: #667eea;
  margin-top: 0.15rem;
}

.scan-progress-text strong {
  display: block;
  color: #2c3e50;
  margin-bottom: 0.25rem;
}

.scan-progress-text p {
  margin: 0;
  color: #606266;
  line-height: 1.5;
}

.scan-actions {
  margin-top: 1rem;
}

.awaiting-card {
  width: 100%;
  max-width: 260px;
  text-align: center;
  color: #2c3e50;
}

.awaiting-card strong {
  display: block;
  margin: 0.75rem 0 0.4rem;
}

.awaiting-card p {
  margin: 0 0 0.75rem;
  color: #606266;
  line-height: 1.5;
}

.awaiting-card-icon {
  font-size: 28px;
  color: #667eea;
}

.dialog-tip,
.password-hint {
  margin: 0 0 0.75rem;
  color: #606266;
  line-height: 1.5;
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
