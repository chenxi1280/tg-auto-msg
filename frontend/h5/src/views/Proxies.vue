<template>
  <div class="proxies-page">
    <!-- 头部 -->
    <header class="header">
      <div class="container">
        <router-link to="/" class="back-link">← 返回首页</router-link>
        <div class="brand-header">
          <img class="brand-logo" src="/quanqiu.png" alt="全球通" />
          <h1>全球通代理管理</h1>
        </div>
      </div>
    </header>

    <!-- 操作栏 -->
    <div class="toolbar">
      <div class="container">
        <el-button type="primary" @click="showAddDialog = true">
          <el-icon><Plus /></el-icon>
          添加代理
        </el-button>
        <el-button @click="checkAllHealth" :loading="checking">
          <el-icon><CircleCheck /></el-icon>
          检查所有代理
        </el-button>
        <el-button @click="refreshProxies" :loading="loading">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
        <div class="stats">
          <el-tag>总计: {{ proxies.length }}</el-tag>
          <el-tag type="success">健康: {{ healthyProxies.length }}</el-tag>
          <el-tag type="info">已分配: {{ assignedProxies.length }}</el-tag>
        </div>
      </div>
    </div>

    <!-- 代理列表 -->
    <div class="main">
      <div class="container">
        <div class="table-wrap">
          <el-table v-if="!isCompact" :data="proxies" stripe v-loading="loading">
            <el-table-column prop="host" label="主机" min-width="150" />
            <el-table-column prop="port" label="端口" width="80" />
            <el-table-column prop="proxy_type" label="类型" width="100">
              <template #default="{ row }">
                <el-tag size="small">{{ row.proxy_type.toUpperCase() }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="row.is_healthy ? 'success' : 'danger'" size="small">
                  {{ row.is_healthy ? '健康' : '异常' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="response_time_ms" label="响应时间" width="100" align="right">
              <template #default="{ row }">
                <span v-if="row.response_time_ms">{{ row.response_time_ms }}ms</span>
                <span v-else class="text-muted">-</span>
              </template>
            </el-table-column>
            <el-table-column prop="usage_count" label="使用次数" width="90" align="right" />
            <el-table-column label="分配账号" width="150">
              <template #default="{ row }">
                <span v-if="row.assigned_account_id">已分配</span>
                <span v-else class="text-muted">未分配</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="240" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="handleCheckHealth(row)">
                  检查
                </el-button>
                <el-button
                  size="small"
                  :disabled="!row.assigned_account_id"
                  @click="handleUnassign(row)"
                >
                  解绑
                </el-button>
                <el-button
                  size="small"
                  type="danger"
                  @click="handleDelete(row)"
                >
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <div v-else class="mobile-card-list" v-loading="loading">
            <div v-for="row in proxies" :key="row.proxy_id" class="mobile-data-card">
              <div class="mobile-data-card__header">
                <div>
                  <div class="mobile-data-card__title">{{ row.host }}:{{ row.port }}</div>
                  <div class="mobile-data-card__subtitle">{{ row.proxy_type.toUpperCase() }}</div>
                </div>
                <el-tag :type="row.is_healthy ? 'success' : 'danger'">{{ row.is_healthy ? '健康' : '异常' }}</el-tag>
              </div>
              <div class="mobile-data-card__grid">
                <div class="mobile-data-card__row">
                  <span class="mobile-data-card__label">响应时间</span>
                  <span class="mobile-data-card__value">{{ row.response_time_ms ? `${row.response_time_ms}ms` : '-' }}</span>
                </div>
                <div class="mobile-data-card__row">
                  <span class="mobile-data-card__label">使用次数</span>
                  <span class="mobile-data-card__value">{{ row.usage_count }}</span>
                </div>
                <div class="mobile-data-card__row">
                  <span class="mobile-data-card__label">分配账号</span>
                  <span class="mobile-data-card__value">{{ row.assigned_account_id ? '已分配' : '未分配' }}</span>
                </div>
              </div>
              <div class="mobile-action-bar">
                <el-button @click="handleCheckHealth(row)">检查</el-button>
                <el-button :disabled="!row.assigned_account_id" @click="handleUnassign(row)">解绑</el-button>
                <el-button type="danger" plain @click="handleDelete(row)">删除</el-button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 添加代理对话框 -->
    <ResponsiveFormLayer v-model="showAddDialog" title="添加代理" width="500px">
      <el-form :model="proxyForm" label-width="80px">
        <el-form-item label="类型">
          <el-select v-model="proxyForm.proxy_type">
            <el-option label="SOCKS5" value="socks5" />
            <el-option label="HTTP" value="http" />
          </el-select>
        </el-form-item>
        <el-form-item label="主机" required>
          <el-input v-model="proxyForm.host" placeholder="例如: 127.0.0.1" />
        </el-form-item>
        <el-form-item label="端口" required>
          <el-input-number v-model="proxyForm.port" :min="1" :max="65535" />
        </el-form-item>
        <el-form-item label="用户名">
          <el-input v-model="proxyForm.username" placeholder="可选" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="proxyForm.password" type="password" placeholder="可选" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button type="primary" @click="handleAddProxy" :loading="adding">
          确定
        </el-button>
      </template>
    </ResponsiveFormLayer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, CircleCheck } from '@element-plus/icons-vue'
import { useProxyStore } from '@/stores/proxy'
import { useAccountStore } from '@/stores/account'
import type { Proxy } from '@/api/proxy'
import { useResponsive } from '@/composables/useResponsive'
import ResponsiveFormLayer from '@/components/responsive/ResponsiveFormLayer.vue'

const proxyStore = useProxyStore()
const accountStore = useAccountStore()
const { isCompact } = useResponsive()

// 状态
const proxies = computed(() => proxyStore.proxies)
const loading = computed(() => proxyStore.loading)
const healthyProxies = computed(() => proxyStore.healthyProxies)
const assignedProxies = computed(() => proxyStore.assignedProxies)
const checking = ref(false)
const adding = ref(false)
const showAddDialog = ref(false)

// 表单数据
const proxyForm = ref({
  proxy_type: 'socks5',
  host: '',
  port: 1080,
  username: '',
  password: ''
})

// 刷新代理列表
const refreshProxies = async () => {
  await proxyStore.fetchProxies()
}

// 检查所有代理健康状态
const checkAllHealth = async () => {
  checking.value = true
  try {
    for (const proxy of proxies.value) {
      try {
        await proxyStore.checkHealth(proxy.proxy_id)
      } catch (err) {
        console.error(`检查代理 ${proxy.proxy_id} 失败:`, err)
      }
    }
    ElMessage.success('健康检查完成')
  } catch (err: any) {
    ElMessage.error(err.message || '检查失败')
  } finally {
    checking.value = false
  }
}

// 检查单个代理
const handleCheckHealth = async (proxy: Proxy) => {
  try {
    const result = await proxyStore.checkHealth(proxy.proxy_id)
    if (result.is_healthy) {
      ElMessage.success(`代理 ${proxy.host}:${proxy.port} 健康 (${result.response_time_ms}ms)`)
    } else {
      ElMessage.warning(`代理 ${proxy.host}:${proxy.port} 异常`)
    }
  } catch (err: any) {
    ElMessage.error(err.message || '检查失败')
  }
}

// 解绑代理
const handleUnassign = async (proxy: Proxy) => {
  try {
    await proxyStore.unassignProxy(proxy.proxy_id)
    ElMessage.success('代理已解绑')
  } catch (err: any) {
    ElMessage.error(err.message || '操作失败')
  }
}

// 删除代理
const handleDelete = async (proxy: Proxy) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除代理 ${proxy.host}:${proxy.port} 吗？`,
      '确认删除',
      {
        type: 'error',
        confirmButtonText: '确定',
        cancelButtonText: '取消'
      }
    )
    await proxyStore.deleteProxy(proxy.proxy_id)
    ElMessage.success('代理已删除')
  } catch (err: any) {
    if (err !== 'cancel') {
      ElMessage.error(err.message || '删除失败')
    }
  }
}

// 添加代理
const handleAddProxy = async () => {
  if (!proxyForm.value.host || !proxyForm.value.port) {
    ElMessage.warning('请填写主机和端口')
    return
  }

  adding.value = true
  try {
    await proxyStore.addProxy({
      proxy_type: proxyForm.value.proxy_type,
      host: proxyForm.value.host,
      port: proxyForm.value.port,
      username: proxyForm.value.username || undefined,
      password: proxyForm.value.password || undefined
    })
    ElMessage.success('代理添加成功')
    showAddDialog.value = false
    // 重置表单
    proxyForm.value = {
      proxy_type: 'socks5',
      host: '',
      port: 1080,
      username: '',
      password: ''
    }
  } catch (err: any) {
    ElMessage.error(err.message || '添加失败')
  } finally {
    adding.value = false
  }
}

// 组件挂载
onMounted(() => {
  proxyStore.fetchProxies()
})
</script>

<style scoped>
.proxies-page {
  min-height: 100vh;
  background: #f5f7fa;
}

.header {
  background: white;
  padding: 1.5rem 0;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
}

.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 1.5rem;
}

.brand-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-logo {
  width: 72px;
  height: auto;
  display: block;
}

.back-link {
  color: #667eea;
  text-decoration: none;
  display: inline-block;
  margin-bottom: 1rem;
}

.back-link:hover {
  text-decoration: underline;
}

.header h1 {
  margin: 0;
  font-size: 1.5rem;
  color: #2c3e50;
}

.toolbar {
  background: white;
  padding: 1rem 0;
  margin-top: 1rem;
  border-bottom: 1px solid #eee;
}

.toolbar .container {
  display: flex;
  align-items: center;
  gap: 1rem;
  flex-wrap: wrap;
}

.stats {
  margin-left: auto;
  display: flex;
  gap: 0.5rem;
}

.main {
  padding: 2rem 0;
}

.text-muted {
  color: #adb5bd;
}

.table-wrap {
  width: 100%;
  overflow-x: auto;
}

@media (max-width: 900px) {
  .container {
    padding: 0 0.9rem;
  }

  .main {
    padding: 1rem 0;
  }
}

@media (max-width: 640px) {
  .header {
    padding: 1rem 0;
  }

  .header h1 {
    font-size: 1.25rem;
  }

  .toolbar .container {
    gap: 0.6rem;
  }

  .toolbar :deep(.el-button) {
    width: 100%;
  }

  .stats {
    width: 100%;
    margin-left: 0;
    flex-wrap: wrap;
  }

  .table-wrap {
    margin: 0 -0.15rem;
    padding: 0 0.15rem;
  }
}
</style>
