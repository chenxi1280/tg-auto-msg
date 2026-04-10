<template>
  <div class="page-stack">
    <el-alert
      :title="canUpdate ? '当前账号可维护系统配置。' : '当前账号仅可查看系统配置，修改权限未授予。'"
      :type="canUpdate ? 'success' : 'info'"
      :closable="false"
    />

    <div class="page-grid">
      <el-card shadow="hover">
        <template #header>
          <div class="card-header">
            <span>购买入口配置</span>
            <el-button @click="loadData">刷新</el-button>
          </div>
        </template>
        <el-form label-position="top">
          <el-form-item label="购买链接">
            <el-input v-model.trim="purchaseForm.purchase_url" :disabled="!canUpdate" placeholder="https://t.me/your_contact" />
          </el-form-item>
          <el-form-item label="按钮文案">
            <el-input v-model.trim="purchaseForm.purchase_button_text" :disabled="!canUpdate" maxlength="50" show-word-limit />
          </el-form-item>
          <el-button v-if="canUpdate" type="primary" :loading="savingPurchase" @click="savePurchase">
            保存购买入口
          </el-button>
        </el-form>
      </el-card>

      <el-card shadow="hover">
        <template #header>
          <div class="card-header">
            <span>Bot 公告栏</span>
            <el-tag :type="noticeForm.enabled ? 'success' : 'info'">{{ noticeForm.enabled ? '已启用' : '未启用' }}</el-tag>
          </div>
        </template>
        <el-form label-position="top">
          <el-alert
            title="保存后会自动刷新已关联用户的公告，并尝试置顶。"
            type="info"
            :closable="false"
            class="notice-tip"
          />
          <el-form-item label="启用公告">
            <el-switch v-model="noticeForm.enabled" :disabled="!canUpdate" />
          </el-form-item>
          <el-form-item label="入口按钮文案">
            <el-input v-model.trim="noticeForm.entry_button_text" :disabled="!canUpdate" maxlength="20" show-word-limit />
          </el-form-item>
          <el-form-item label="公告正文">
            <el-input v-model="noticeForm.message_text" :disabled="!canUpdate" type="textarea" :rows="6" maxlength="3000" show-word-limit />
          </el-form-item>
          <el-form-item label="跳转链接（可选）">
            <el-input v-model.trim="noticeForm.target_url" :disabled="!canUpdate" placeholder="https://...（可留空）" />
          </el-form-item>
          <el-button v-if="canUpdate" type="primary" :loading="savingNotice" @click="saveNotice">
            保存公告配置
          </el-button>
        </el-form>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  adminGetBotNoticeSettings,
  adminGetPurchaseSettings,
  adminUpdateBotNoticeSettings,
  adminUpdatePurchaseSettings,
} from '@/api/admin'
import { useAdminConsoleStore } from '@/stores/adminConsole'

const store = useAdminConsoleStore()
const canUpdate = computed(() => store.hasPermission('system.settings.update'))

const savingPurchase = ref(false)
const savingNotice = ref(false)

const purchaseForm = reactive({
  purchase_url: '',
  purchase_button_text: '联系 Telegram 购买',
})

const noticeForm = reactive({
  enabled: false,
  entry_button_text: '📢 公告栏',
  message_text: '',
  target_url: '',
})

const loadData = async () => {
  const [purchaseResponse, noticeResponse] = await Promise.all([
    adminGetPurchaseSettings(),
    adminGetBotNoticeSettings(),
  ])
  purchaseForm.purchase_url = purchaseResponse.data.purchase_url
  purchaseForm.purchase_button_text = purchaseResponse.data.purchase_button_text
  noticeForm.enabled = noticeResponse.data.enabled
  noticeForm.entry_button_text = noticeResponse.data.entry_button_text
  noticeForm.message_text = noticeResponse.data.message_text
  noticeForm.target_url = noticeResponse.data.target_url
}

const savePurchase = async () => {
  savingPurchase.value = true
  try {
    await adminUpdatePurchaseSettings({ ...purchaseForm })
    ElMessage.success('购买入口已保存')
  } finally {
    savingPurchase.value = false
  }
}

const saveNotice = async () => {
  savingNotice.value = true
  try {
    const response = await adminUpdateBotNoticeSettings({ ...noticeForm })
    const summary = response.data.refresh_summary
    if (summary) {
      ElMessage.success(
        `公告栏配置已保存，已刷新 ${summary.updated ?? 0} 个用户，置顶失败 ${summary.pin_failed_users ?? 0} 个`,
      )
    } else {
      ElMessage.success('公告栏配置已保存')
    }
  } finally {
    savingNotice.value = false
  }
}

onMounted(async () => {
  await loadData()
})
</script>

<style scoped>
.page-stack {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.page-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 20px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.notice-tip {
  margin-bottom: 16px;
}

@media (max-width: 768px) {
  .page-grid {
    grid-template-columns: 1fr;
  }

  .card-header {
    align-items: flex-start;
    flex-direction: column;
    gap: 10px;
  }
}
</style>
