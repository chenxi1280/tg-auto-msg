<template>
  <div class="login-page">
    <div class="login-container">
      <!-- 头部 -->
      <div class="login-header">
        <router-link to="/" class="back-link">← 返回首页</router-link>
        <h1>添加 Telegram 账号</h1>
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
            <h3>扫码登录</h3>
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
          <el-button @click="handleAddAnother">
            添加另一个账号
          </el-button>
        </div>
      </div>

      <!-- 错误状态 -->
      <div v-if="status === LoginStatus.ERROR" class="login-content">
        <div class="error-section">
          <div class="error-icon">⚠️</div>
          <h3>登录失败</h3>
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
          <p>登录会话已过期，请重新开始</p>
          <el-button type="primary" @click="handleRetry">
            重新登录
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
import { createLoginSession, getLoginStatus, LoginStatus } from '@/api/login'
import QRCode from 'qrcode'

const router = useRouter()

// 状态
const status = ref<LoginStatus>(LoginStatus.PENDING)
const loginId = ref('')
const bindCode = ref('')
const qrUrl = ref('')  // 二维码图片 Data URL
const qrUrlData = ref('')  // 从后端获取的 TG 登录 URL
const loading = ref(false)
const error = ref('')

// 轮询定时器
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
    qrUrlData.value = res.data.qr_url  // 【关键】直接使用返回的 qr_url
    status.value = LoginStatus.SCANNING

    // 立即生成二维码
    await generateQRWithLogo()

    // 开始轮询状态
    startPolling()
  } catch (err: any) {
    error.value = err.message || '创建登录会话失败'
    status.value = LoginStatus.ERROR
  } finally {
    loading.value = false
  }
}

// 轮询登录状态
const pollStatus = async () => {
  if (!loginId.value) return

  try {
    const res = await getLoginStatus(loginId.value)
    const data = res.data

    status.value = data.status

    // 如果已确认，显示绑定码
    if (data.status === LoginStatus.CONFIRMED && data.bind_code) {
      bindCode.value = data.bind_code
      stopPolling()
    } else if (data.status === LoginStatus.ERROR) {
      error.value = data.error || '登录失败'
      stopPolling()
    } else if (data.status === LoginStatus.EXPIRED) {
      stopPolling()
    }
  } catch (err: any) {
    console.error('获取登录状态失败:', err)
  }
}

// 开始轮询
const startPolling = () => {
  // 立即检查一次
  pollStatus()

  // 每 2 秒检查一次
  pollTimer = setInterval(() => {
    pollStatus()
  }, 2000)
}

// 停止轮询
const stopPolling = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

// 生成带 TG Logo 的二维码
const generateQRWithLogo = async () => {
  if (!qrUrlData.value) {
    console.error('❌ qrUrlData 为空，无法生成二维码')
    return
  }

  console.log('🔄 开始生成二维码，qrUrlData:', qrUrlData.value)

  try {
    // 创建 canvas
    const canvas = document.createElement('canvas')
    const ctx = canvas.getContext('2d')
    if (!ctx) {
      console.error('❌ 无法获取 canvas context')
      return
    }

    const size = 300
    canvas.width = size
    canvas.height = size

    // 生成二维码到 canvas
    await QRCode.toCanvas(canvas, qrUrlData.value, {
      width: size,
      margin: 2,
      color: { dark: '#000000', light: '#FFFFFF' }
    })

    console.log('✅ 二维码已生成到 canvas')

    // 等待 Logo 加载并绘制
    await new Promise<void>((resolve, reject) => {
      // Telegram Logo SVG（转换为 Data URL）
      const logoSvg = `
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#0088cc">
          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69a.2.2 0 00-.05-.18c-.06-.05-.14-.03-.21-.02-.09.02-1.49.95-4.22 2.79-.4.27-.76.41-1.08.4-.36-.01-1.04-.2-1.55-.37-.63-.2-1.12-.31-1.08-.66.02-.18.27-.36.74-.55 2.92-1.27 4.86-2.11 5.83-2.51 2.78-1.16 3.35-1.36 3.73-1.36.08 0 .27.02.39.12.1.08.13.19.14.27-.01.06.01.24 0 .38z"/>
        </svg>
      `
      const logoUrl = 'data:image/svg+xml;base64,' + btoa(logoSvg)

      // 加载 Logo
      const logo = new Image()
      logo.onload = () => {
        try {
          const logoSize = 50
          const x = (size - logoSize) / 2
          const y = (size - logoSize) / 2

          // 绘制白色背景（圆角矩形）
          ctx.fillStyle = '#FFFFFF'
          const padding = 5
          const radius = 8
          ctx.beginPath()
          ctx.roundRect(x - padding, y - padding, logoSize + padding * 2, logoSize + padding * 2, radius)
          ctx.fill()

          // 绘制 Logo
          ctx.drawImage(logo, x, y, logoSize, logoSize)

          // 转换为 Data URL
          qrUrl.value = canvas.toDataURL('image/png')
          console.log('✅ 二维码 Data URL 已生成')
          resolve()
        } catch (err) {
          console.error('❌ 绘制 Logo 失败:', err)
          reject(err)
        }
      }
      logo.onerror = () => {
        console.error('❌ Logo 加载失败')
        reject(new Error('Logo 加载失败'))
      }
      logo.src = logoUrl
    })

  } catch (err) {
    console.error('❌ 生成二维码失败:', err)
  }
}

// 复制命令
const copyCommand = () => {
  const command = `/bind ${bindCode.value}`
  navigator.clipboard.writeText(command).then(() => {
    ElMessage.success('命令已复制到剪贴板')
  }).catch(() => {
    ElMessage.error('复制失败，请手动复制')
  })
}

// 重试
const handleRetry = () => {
  createSession()
}

// 添加另一个账号
const handleAddAnother = () => {
  createSession()
}

// 组件挂载
onMounted(() => {
  createSession()
})

// 组件卸载
onUnmounted(() => {
  stopPolling()
})
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
  max-width: 500px;
  width: 100%;
  overflow: hidden;
}

.login-header {
  padding: 1.5rem;
  border-bottom: 1px solid #eee;
  position: relative;
}

.back-link {
  color: #667eea;
  text-decoration: none;
  font-size: 0.9rem;
  display: inline-block;
  margin-bottom: 1rem;
}

.back-link:hover {
  text-decoration: underline;
}

.login-header h1 {
  margin: 0;
  font-size: 1.5rem;
  color: #2c3e50;
}

.login-content {
  padding: 2rem;
}

/* 扫码阶段 */
.qr-section {
  text-align: center;
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

.loading-spinner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
  color: #667eea;
}

.qr-code img {
  max-width: 100%;
  border-radius: 8px;
}

.instructions {
  text-align: left;
}

.instructions h3 {
  margin: 0 0 1rem 0;
  font-size: 1.2rem;
  color: #2c3e50;
}

.steps {
  margin: 0;
  padding-left: 1.5rem;
  color: #6c757d;
  line-height: 1.8;
}

.steps li {
  margin-bottom: 0.5rem;
}

/* 绑定码阶段 */
.bind-code-section {
  text-align: center;
}

.success-icon {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  font-size: 3rem;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 1.5rem;
}

.bind-code-section h3 {
  margin: 0 0 0.5rem 0;
  font-size: 1.5rem;
  color: #2c3e50;
}

.bind-code-label {
  color: #6c757d;
  margin-bottom: 0.5rem;
}

.bind-code {
  font-size: 2.5rem;
  font-weight: 700;
  letter-spacing: 0.3em;
  color: #667eea;
  margin-bottom: 1.5rem;
  font-family: 'Courier New', monospace;
}

.bind-instructions {
  background: #f8f9fa;
  border-radius: 8px;
  padding: 1rem;
  margin-bottom: 1.5rem;
}

.bind-instructions p {
  margin: 0 0 0.5rem 0;
  color: #6c757d;
  font-size: 0.9rem;
}

.command {
  display: block;
  background: white;
  padding: 0.75rem;
  border-radius: 4px;
  font-family: 'Courier New', monospace;
  color: #667eea;
  font-weight: 500;
  font-size: 1rem;
}

/* 错误/过期状态 */
.error-section,
.expired-section {
  text-align: center;
  padding: 2rem 0;
}

.error-icon,
.expired-icon {
  font-size: 4rem;
  margin-bottom: 1rem;
}

.error-section h3,
.expired-section h3 {
  margin: 0 0 1rem 0;
  color: #2c3e50;
}

.error-section p,
.expired-section p {
  color: #6c757d;
  margin-bottom: 1.5rem;
}

/* 按钮组 */
:deep(.el-button) + .el-button {
  margin-left: 1rem;
}
</style>
