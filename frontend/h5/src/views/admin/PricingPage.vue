<template>
  <div class="page-stack">
    <el-alert
      :title="store.isSuperAdmin ? '卡密价格统一由超管维护，修改后新批次立即按新价格扣费。' : '当前页面为只读视图，卡密统一价格仅允许超管修改。'"
      type="info"
      :closable="false"
    />

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>全局卡密价格</span>
          <el-button @click="store.loadPlans()">刷新</el-button>
        </div>
      </template>
      <el-table :data="store.plans" stripe>
        <el-table-column prop="display_name" label="规格名称" min-width="180" />
        <el-table-column prop="plan_code" label="规格编码" width="140" />
        <el-table-column prop="duration_days" label="时长（天）" width="120" />
        <el-table-column label="统一价格" width="140">
          <template #default="{ row }">¥{{ centsToYuan(row.price_cents) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button v-if="store.isSuperAdmin" link type="primary" @click="openEditor(row)">修改价格</el-button>
            <span v-else class="readonly-text">只读</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="editor.visible" title="修改统一价格" width="420px">
      <el-form label-position="top">
        <el-form-item label="规格">
          <el-input :model-value="editor.plan?.display_name || ''" disabled />
        </el-form-item>
        <el-form-item label="价格（元）">
          <el-input-number v-model="editor.price_yuan" :min="0" :step="10" :precision="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editor.visible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitEditor">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { AgentPlan } from '@/api/admin'
import { adminUpdatePricingPlan } from '@/api/admin'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { centsToYuan, yuanToCents } from '@/utils/adminConsole'

const store = useAdminConsoleStore()
const submitting = ref(false)
const editor = reactive<{
  visible: boolean
  plan: AgentPlan | null
  price_yuan: number
}>({
  visible: false,
  plan: null,
  price_yuan: 0,
})

const openEditor = (plan: AgentPlan) => {
  editor.visible = true
  editor.plan = plan
  editor.price_yuan = plan.price_cents / 100
}

const submitEditor = async () => {
  if (!editor.plan) return
  submitting.value = true
  try {
    await adminUpdatePricingPlan(editor.plan.plan_code, yuanToCents(editor.price_yuan))
    editor.visible = false
    await store.loadPlans()
    ElMessage.success('统一价格已更新')
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  await store.loadPlans()
})
</script>

<style scoped>
.page-stack {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.readonly-text {
  color: #94a3b8;
  font-size: 13px;
}
</style>
