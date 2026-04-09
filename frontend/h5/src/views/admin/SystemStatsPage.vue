<template>
  <div class="page-stack">
    <el-alert
      :title="stats ? `统计日期 ${stats.date}，按服务器时区 ${stats.timezone} 计算。` : '按服务器时区统计今日数据。'"
      type="info"
      :closable="false"
    />

    <div class="stats-grid" v-loading="loading">
      <el-card shadow="hover">
        <div class="stat-label">今日发送消息条数</div>
        <div class="stat-value">{{ stats?.today_sent_messages ?? 0 }}</div>
        <div class="stat-meta">仅统计成功发送的任务日志</div>
      </el-card>
      <el-card shadow="hover">
        <div class="stat-label">今日绑定卡密数量</div>
        <div class="stat-value">{{ stats?.today_bound_cards ?? 0 }}</div>
        <div class="stat-meta">按今日激活/使用的卡密统计</div>
      </el-card>
      <el-card shadow="hover">
        <div class="stat-label">今日新增用户</div>
        <div class="stat-value">{{ stats?.today_new_users ?? 0 }}</div>
        <div class="stat-meta">按今日创建的系统用户统计</div>
      </el-card>
    </div>

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>统计说明</span>
          <el-button @click="loadStats">刷新</el-button>
        </div>
      </template>
      <div class="meta-list">
        <div class="meta-row">
          <span class="meta-label">统计口径</span>
          <span class="meta-value">当前部署数据库</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">时间边界</span>
          <span class="meta-value">{{ stats?.timezone || 'Asia/Shanghai' }}</span>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { adminGetTodaySystemStats, type SystemTodayStats } from '@/api/admin'

const loading = ref(false)
const stats = ref<SystemTodayStats | null>(null)

const loadStats = async () => {
  loading.value = true
  try {
    const response = await adminGetTodaySystemStats()
    stats.value = response.data
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadStats()
})
</script>

<style scoped>
.page-stack {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.stats-grid {
  display: grid;
  gap: 20px;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}

.stat-label {
  color: #64748b;
  font-size: 13px;
}

.stat-value {
  margin-top: 12px;
  font-size: 30px;
  font-weight: 700;
  color: #0f172a;
}

.stat-meta {
  margin-top: 10px;
  color: #64748b;
  font-size: 13px;
}

.card-header,
.meta-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.meta-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.meta-label {
  color: #64748b;
}

.meta-value {
  color: #0f172a;
  font-weight: 600;
}

@media (max-width: 768px) {
  .card-header,
  .meta-row {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
  }
}
</style>
