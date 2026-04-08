<template>
  <div class="page-stack">
    <el-alert v-if="lastActionMessage" :title="lastActionMessage" type="success" :closable="true" @close="lastActionMessage = ''" />

    <el-tabs v-model="activeTab" type="border-card">
      <el-tab-pane label="卡密规格" name="plans">
        <div class="page-stack">
          <el-card shadow="hover">
            <template #header>
              <div class="card-header">
                <span>新增卡密规格</span>
                <el-button @click="loadData">刷新</el-button>
              </div>
            </template>
            <el-form class="toolbar-form" inline>
              <el-form-item label="编码">
                <el-input v-model.trim="planForm.plan_code" style="width: 140px" />
              </el-form-item>
              <el-form-item label="名称">
                <el-input v-model.trim="planForm.display_name" style="width: 160px" />
              </el-form-item>
              <el-form-item label="周期">
                <el-input v-model.trim="planForm.billing_cycle" style="width: 120px" />
              </el-form-item>
              <el-form-item label="价格(元)">
                <el-input-number v-model="planForm.price_yuan" :min="0" :precision="2" />
              </el-form-item>
              <el-form-item label="时长(天)">
                <el-input-number v-model="planForm.duration_days" :min="1" />
              </el-form-item>
              <el-form-item label="排序">
                <el-input-number v-model="planForm.sort_order" :min="0" />
              </el-form-item>
              <el-form-item v-if="canWrite">
                <el-button type="primary" :loading="creatingPlan" @click="createPlan">新增规格</el-button>
              </el-form-item>
            </el-form>
          </el-card>

          <el-card shadow="hover">
            <el-table :data="plans" stripe>
              <el-table-column prop="plan_code" label="编码" width="140" />
              <el-table-column prop="display_name" label="名称" min-width="180" />
              <el-table-column prop="billing_cycle" label="周期" width="120" />
              <el-table-column label="价格" width="120">
                <template #default="{ row }">¥{{ centsToYuan(row.price_cents) }}</template>
              </el-table-column>
              <el-table-column prop="duration_days" label="时长" width="100" />
              <el-table-column prop="sort_order" label="排序" width="100" />
              <el-table-column label="状态" width="100">
                <template #default="{ row }">
                  <el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '停用' }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" min-width="220" fixed="right">
                <template #default="{ row }">
                  <el-button v-if="canWrite" link type="primary" @click="openPlanEditor(row)">编辑</el-button>
                  <el-button v-if="canWrite" link type="danger" @click="deletePlan(row.plan_code)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </div>
      </el-tab-pane>

      <el-tab-pane label="卡密总览" name="cards">
        <div class="page-stack">
          <el-card shadow="hover">
            <template #header>
              <div class="card-header">
                <span>生成旧卡密</span>
                <div class="header-actions">
                  <el-select v-model="cardFilters.plan_code" clearable placeholder="规格" style="width: 140px">
                    <el-option v-for="plan in plans" :key="plan.plan_code" :label="plan.display_name" :value="plan.plan_code" />
                  </el-select>
                  <el-select v-model="cardFilters.status" style="width: 140px">
                    <el-option label="全部状态" value="all" />
                    <el-option label="可用" value="available" />
                    <el-option label="已使用" value="used" />
                  </el-select>
                  <el-input v-model.trim="cardFilters.keyword" clearable placeholder="搜索卡密/批次/规格" style="width: 220px" />
                  <el-button @click="loadCards(true)">查询</el-button>
                </div>
              </div>
            </template>
            <el-form class="toolbar-form" inline>
              <el-form-item label="规格">
                <el-select v-model="generateForm.plan_code" filterable style="width: 200px">
                  <el-option v-for="plan in plans" :key="plan.plan_code" :label="plan.display_name" :value="plan.plan_code" />
                </el-select>
              </el-form-item>
              <el-form-item label="数量">
                <el-input-number v-model="generateForm.quantity" :min="1" :max="500" />
              </el-form-item>
              <el-form-item label="有效天数">
                <el-input-number v-model="generateForm.valid_days" :min="1" />
              </el-form-item>
              <el-form-item label="前缀">
                <el-input v-model.trim="generateForm.prefix" style="width: 140px" />
              </el-form-item>
              <el-form-item>
                <el-button v-if="canWrite" type="primary" :loading="generatingCards" @click="generateCards">生成卡密</el-button>
                <el-button v-if="canExport" @click="exportCards">导出 XLSX</el-button>
              </el-form-item>
            </el-form>
          </el-card>

          <el-card shadow="hover">
            <el-table :data="cards.items" stripe>
              <el-table-column prop="card_code" label="卡密" min-width="220" />
              <el-table-column prop="plan_code" label="规格" width="120" />
              <el-table-column label="状态" width="120">
                <template #default="{ row }">
                  <el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? (row.is_used ? '已使用' : '可用') : '停用' }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="绑定账号" min-width="180">
                <template #default="{ row }">{{ row.bound_account_name || '-' }}</template>
              </el-table-column>
              <el-table-column label="创建时间" min-width="160">
                <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="160" fixed="right">
                <template #default="{ row }">
                  <el-button v-if="canWrite && row.is_active" link type="warning" @click="toggleCard(row.card_code, false)">停用</el-button>
                  <el-button v-else-if="canWrite" link type="success" @click="toggleCard(row.card_code, true)">启用</el-button>
                </template>
              </el-table-column>
            </el-table>
            <div class="pagination-wrap">
              <el-pagination
                v-model:current-page="cardPagination.currentPage"
                v-model:page-size="cardPagination.pageSize"
                background
                layout="total, sizes, prev, pager, next"
                :page-sizes="[20, 50, 100]"
                :total="cards.total"
                @current-change="handleCardPageChange"
                @size-change="handleCardSizeChange"
              />
            </div>
          </el-card>
        </div>
      </el-tab-pane>

      <el-tab-pane label="历史授权" name="slots">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>历史授权</span>
              <div class="header-actions">
                <el-select v-model="slotFilters.status" style="width: 160px">
                  <el-option label="全部状态" value="" />
                  <el-option label="active" value="active" />
                  <el-option label="expired" value="expired" />
                  <el-option label="terminated" value="terminated" />
                </el-select>
                <el-button @click="loadSlots(true)">查询</el-button>
              </div>
            </div>
          </template>
          <el-table :data="licenseSlots" stripe>
            <el-table-column prop="authorization_id" label="授权单号" min-width="180" />
            <el-table-column prop="owner_username" label="所属用户" width="140" />
            <el-table-column prop="status" label="状态" width="120" />
            <el-table-column prop="current_account_username" label="当前账号" width="140" />
            <el-table-column prop="total_duration_days" label="总天数" width="100" />
            <el-table-column label="到期时间" min-width="160">
              <template #default="{ row }">{{ formatDateTime(row.end_at) }}</template>
            </el-table-column>
          </el-table>
          <div class="pagination-wrap">
            <el-pagination
              v-model:current-page="slotPagination.currentPage"
              v-model:page-size="slotPagination.pageSize"
              background
              layout="total, sizes, prev, pager, next"
              :page-sizes="[20, 50, 100]"
              :total="slotTotal"
              @current-change="handleSlotPageChange"
              @size-change="handleSlotSizeChange"
            />
          </div>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="planEditor.visible" title="编辑卡密规格" width="520px">
      <el-form label-position="top">
        <el-form-item label="名称">
          <el-input v-model.trim="planEditor.display_name" :disabled="!canWrite" />
        </el-form-item>
        <el-form-item label="周期">
          <el-input v-model.trim="planEditor.billing_cycle" :disabled="!canWrite" />
        </el-form-item>
        <el-form-item label="价格(元)">
          <el-input-number v-model="planEditor.price_yuan" :min="0" :precision="2" :disabled="!canWrite" />
        </el-form-item>
        <el-form-item label="时长(天)">
          <el-input-number v-model="planEditor.duration_days" :min="1" :disabled="!canWrite" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="planEditor.sort_order" :min="0" :disabled="!canWrite" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="planEditor.is_active" :disabled="!canWrite" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="planEditor.visible = false">取消</el-button>
        <el-button v-if="canWrite" type="primary" :loading="savingPlan" @click="savePlan">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { AgentPlan, LicenseAuthorization, LicenseCardsPageData } from '@/api/admin'
import {
  adminCreateLicensePlan,
  adminDeleteLicensePlan,
  adminDisableLicenseCard,
  adminEnableLicenseCard,
  adminExportLicenseCards,
  adminGenerateLegacyCards,
  adminListLicenseCards,
  adminListLicensePlans,
  adminListLicenseSlots,
  adminUpdateLicensePlan,
} from '@/api/admin'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { centsToYuan, formatDateTime, yuanToCents } from '@/utils/adminConsole'

const store = useAdminConsoleStore()
const canWrite = computed(() => store.hasPermission('legacy_cards.write'))
const canExport = computed(() => store.hasPermission('legacy_cards.export'))
const activeTab = ref('plans')
const plans = ref<AgentPlan[]>([])
const licenseSlots = ref<LicenseAuthorization[]>([])
const cards = ref<LicenseCardsPageData>({ items: [], total: 0, limit: 50, offset: 0 })
const slotTotal = ref(0)
const lastActionMessage = ref('')

const creatingPlan = ref(false)
const savingPlan = ref(false)
const generatingCards = ref(false)

const cardPagination = reactive({
  currentPage: 1,
  pageSize: 20,
})

const slotPagination = reactive({
  currentPage: 1,
  pageSize: 20,
})

const planForm = reactive({
  plan_code: '',
  display_name: '',
  billing_cycle: 'custom',
  price_yuan: 0,
  duration_days: 30,
  sort_order: 0,
})

const generateForm = reactive({
  plan_code: '',
  quantity: 10,
  valid_days: 30,
  prefix: '',
})

const cardFilters = reactive({
  plan_code: '',
  status: 'all',
  keyword: '',
})

const slotFilters = reactive({
  status: '',
})

const planEditor = reactive({
  visible: false,
  plan_code: '',
  display_name: '',
  billing_cycle: 'custom',
  price_yuan: 0,
  duration_days: 30,
  sort_order: 0,
  is_active: true,
})

const loadPlans = async () => {
  const plansResponse = await adminListLicensePlans()
  plans.value = plansResponse.data
  const firstPlan = plans.value[0]
  if (!generateForm.plan_code && firstPlan) {
    generateForm.plan_code = firstPlan.plan_code
  }
}

const loadCards = async (resetPage = false) => {
  if (resetPage) cardPagination.currentPage = 1
  const cardsResponse = await adminListLicenseCards({
    plan_code: cardFilters.plan_code || undefined,
    is_used: cardFilters.status === 'used' ? true : cardFilters.status === 'available' ? false : undefined,
    is_active: cardFilters.status === 'available' ? true : undefined,
    keyword: cardFilters.keyword || undefined,
    limit: cardPagination.pageSize,
    offset: (cardPagination.currentPage - 1) * cardPagination.pageSize,
  })
  cards.value = cardsResponse.data
  if (!cards.value.items.length && cards.value.total > 0 && cardPagination.currentPage > 1) {
    cardPagination.currentPage -= 1
    await loadCards()
  }
}

const loadSlots = async (resetPage = false) => {
  if (resetPage) slotPagination.currentPage = 1
  const slotsResponse = await adminListLicenseSlots({
    status: slotFilters.status || undefined,
    limit: slotPagination.pageSize,
    offset: (slotPagination.currentPage - 1) * slotPagination.pageSize,
  })
  licenseSlots.value = slotsResponse.data.items
  slotTotal.value = slotsResponse.data.total
  if (!licenseSlots.value.length && slotTotal.value > 0 && slotPagination.currentPage > 1) {
    slotPagination.currentPage -= 1
    await loadSlots()
  }
}

const loadData = async () => {
  await Promise.all([loadPlans(), loadCards(), loadSlots()])
}

const handleCardPageChange = async () => {
  await loadCards()
}

const handleCardSizeChange = async () => {
  cardPagination.currentPage = 1
  await loadCards()
}

const handleSlotPageChange = async () => {
  await loadSlots()
}

const handleSlotSizeChange = async () => {
  slotPagination.currentPage = 1
  await loadSlots()
}

const createPlan = async () => {
  creatingPlan.value = true
  try {
    await adminCreateLicensePlan({
      plan_code: planForm.plan_code,
      display_name: planForm.display_name,
      billing_cycle: planForm.billing_cycle,
      price_cents: yuanToCents(planForm.price_yuan),
      duration_days: planForm.duration_days,
      sort_order: planForm.sort_order,
    })
    Object.assign(planForm, {
      plan_code: '',
      display_name: '',
      billing_cycle: 'custom',
      price_yuan: 0,
      duration_days: 30,
      sort_order: 0,
    })
    await loadData()
    lastActionMessage.value = '卡密规格已创建'
    ElMessage.success(lastActionMessage.value)
  } finally {
    creatingPlan.value = false
  }
}

const openPlanEditor = (plan: AgentPlan) => {
  Object.assign(planEditor, {
    visible: true,
    plan_code: plan.plan_code,
    display_name: plan.display_name,
    billing_cycle: plan.billing_cycle,
    price_yuan: plan.price_cents / 100,
    duration_days: plan.duration_days,
    sort_order: plan.sort_order,
    is_active: plan.is_active,
  })
}

const savePlan = async () => {
  savingPlan.value = true
  try {
    await adminUpdateLicensePlan(planEditor.plan_code, {
      display_name: planEditor.display_name,
      billing_cycle: planEditor.billing_cycle,
      price_cents: yuanToCents(planEditor.price_yuan),
      duration_days: planEditor.duration_days,
      sort_order: planEditor.sort_order,
      is_active: planEditor.is_active,
    })
    planEditor.visible = false
    await loadData()
    lastActionMessage.value = '卡密规格已更新'
    ElMessage.success(lastActionMessage.value)
  } finally {
    savingPlan.value = false
  }
}

const deletePlan = async (planCode: string) => {
  await ElMessageBox.confirm('删除规格会停用该规格下所有未使用卡密，确定继续吗？', '删除规格', { type: 'warning' })
  await adminDeleteLicensePlan(planCode)
  await loadData()
  lastActionMessage.value = '卡密规格已删除'
  ElMessage.success(lastActionMessage.value)
}

const generateCards = async () => {
  generatingCards.value = true
  try {
    await adminGenerateLegacyCards({ ...generateForm })
    await loadCards(true)
    lastActionMessage.value = '卡密已生成'
    ElMessage.success(lastActionMessage.value)
  } finally {
    generatingCards.value = false
  }
}

const exportCards = async () => {
  const blob = await adminExportLicenseCards()
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `legacy-license-cards-${Date.now()}.xlsx`
  link.click()
  window.URL.revokeObjectURL(url)
  lastActionMessage.value = '旧卡密 Excel 已导出'
}

const toggleCard = async (cardCode: string, enabled: boolean) => {
  if (enabled) {
    await adminEnableLicenseCard(cardCode)
  } else {
    await adminDisableLicenseCard(cardCode)
  }
  await loadCards()
  lastActionMessage.value = enabled ? '卡密已启用' : '卡密已停用'
  ElMessage.success(lastActionMessage.value)
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

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.toolbar-form {
  gap: 8px 0;
}

.header-actions,
.pagination-wrap {
  display: flex;
  align-items: center;
  gap: 12px;
}

.pagination-wrap {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
