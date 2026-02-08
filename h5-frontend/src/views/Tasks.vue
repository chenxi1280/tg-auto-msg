<template>
  <div class="tasks-page">
    <!-- 头部 -->
    <header class="header">
      <div class="container">
        <router-link to="/" class="back-link">← 返回首页</router-link>
        <h1>任务管理</h1>
      </div>
    </header>

    <!-- 内容区域 -->
    <div class="main">
      <div class="container">
        <el-empty description="任务管理功能开发中...">
          <p class="hint">提示：您可以使用原有的 H5 任务管理页面</p>
        </el-empty>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// 任务管理页面 - 占位符
// 实际功能可以复用现有的 H5 任务页面
</script>

<style scoped>
.tasks-page {
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

.main {
  padding: 4rem 0;
}

.hint {
  color: #6c757d;
  margin-top: 1rem;
}
</style>
