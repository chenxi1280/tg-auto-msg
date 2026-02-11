<template>
  <div class="home-page">
    <!-- 头部导航 -->
    <header class="header">
      <div class="container">
        <h1 class="title">Telegram 定时消息推送系统</h1>
        <nav class="nav">
          <router-link to="/login" class="nav-link">登录</router-link>
          <router-link v-if="isAuthenticated" to="/accounts" class="nav-link">账号管理</router-link>
          <router-link v-if="isAuthenticated" to="/resources" class="nav-link">资源列表</router-link>
          <router-link v-if="isAuthenticated" to="/proxies" class="nav-link">代理管理</router-link>
          <router-link v-if="isAuthenticated" to="/tasks" class="nav-link">任务管理</router-link>
        </nav>
      </div>
    </header>

    <!-- 主要内容 -->
    <main class="main">
      <div class="container">
        <!-- 欢迎/未登录区域 -->
        <div class="hero">
          <h2>欢迎使用 Telegram 定时消息推送系统</h2>
          <p class="description">
            支持多 Userbot 账号管理、资源自动同步、智能风控等功能
          </p>
          <div class="actions">
            <router-link v-if="!isAuthenticated" to="/login" class="btn btn-primary">
              立即登录
            </router-link>
            <router-link v-else to="/accounts" class="btn btn-primary">
              管理账号
            </router-link>
          </div>
        </div>

        <!-- 功能特性 -->
        <div class="features">
          <div class="feature-card">
            <div class="feature-icon">🔐</div>
            <h3>扫码登录</h3>
            <p>通过 Telegram 扫码快速登录，安全便捷</p>
          </div>
          <div class="feature-card">
            <div class="feature-icon">👥</div>
            <h3>多账号管理</h3>
            <p>支持绑定多个 Userbot 账号，统一管理</p>
          </div>
          <div class="feature-card">
            <div class="feature-icon">🔄</div>
            <h3>资源同步</h3>
            <p>自动同步 Telegram Dialogs，分类存储</p>
          </div>
          <div class="feature-card">
            <div class="feature-icon">⚡</div>
            <h3>快速调度</h3>
            <p>10秒扫描间隔，Jitter 随机抖动防风控</p>
          </div>
          <div class="feature-card">
            <div class="feature-icon">🛡️</div>
            <h3>智能风控</h3>
            <p>多级速率限制、代理池、零宽字符去重</p>
          </div>
          <div class="feature-card">
            <div class="feature-icon">🔧</div>
            <h3>自动恢复</h3>
            <p>FloodWait 自动检测，熔断器自愈机制</p>
          </div>
        </div>
      </div>
    </main>

    <!-- 页脚 -->
    <footer class="footer">
      <div class="container">
        <p>&copy; 2024 Telegram 定时消息推送系统</p>
      </div>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()
const isAuthenticated = computed(() => userStore.isAuthenticated)
</script>

<style scoped>
.home-page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.header {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 1.5rem 0;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
}

.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 1.5rem;
}

.title {
  color: white;
  font-size: 1.5rem;
  font-weight: 600;
  margin: 0 0 1rem 0;
}

.nav {
  display: flex;
  gap: 1.5rem;
}

.nav-link {
  color: rgba(255, 255, 255, 0.9);
  text-decoration: none;
  font-size: 0.95rem;
  transition: color 0.2s;
}

.nav-link:hover {
  color: white;
}

.main {
  flex: 1;
  padding: 3rem 0;
}

.hero {
  text-align: center;
  padding: 3rem 0;
}

.hero h2 {
  font-size: 2rem;
  color: #2c3e50;
  margin-bottom: 1rem;
}

.description {
  font-size: 1.1rem;
  color: #6c757d;
  margin-bottom: 2rem;
}

.actions {
  display: flex;
  justify-content: center;
  gap: 1rem;
}

.btn {
  padding: 0.75rem 2rem;
  border-radius: 8px;
  text-decoration: none;
  font-weight: 500;
  transition: all 0.2s;
  display: inline-block;
}

.btn-primary {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.btn-primary:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}

.features {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 2rem;
  margin-top: 3rem;
}

.feature-card {
  background: white;
  border-radius: 12px;
  padding: 2rem;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  text-align: center;
  transition: transform 0.2s, box-shadow 0.2s;
}

.feature-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
}

.feature-icon {
  font-size: 3rem;
  margin-bottom: 1rem;
}

.feature-card h3 {
  font-size: 1.2rem;
  color: #2c3e50;
  margin-bottom: 0.5rem;
}

.feature-card p {
  color: #6c757d;
  font-size: 0.95rem;
  line-height: 1.5;
}

.footer {
  background: #f8f9fa;
  padding: 1.5rem 0;
  text-align: center;
  color: #6c757d;
  font-size: 0.9rem;
}
</style>
