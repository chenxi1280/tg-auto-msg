<template>
  <div class="page-stack">
    <div class="stats-grid">
      <el-card v-if="canGenerateBatches && canReadPricing" shadow="hover">
        <div class="stat-label">批次数</div>
        <div class="stat-value">{{ batchTotal }}</div>
        <div class="stat-meta">当前筛选结果总数</div>
      </el-card>
      <el-card v-if="canGenerateBatches && canReadPricing" shadow="hover">
        <div class="stat-label">余额已付批次</div>
        <div class="stat-value">{{ batchStats.page_paid_count }}</div>
        <div class="stat-meta">当前页统计</div>
      </el-card>
      <el-card shadow="hover">
        <div class="stat-label">授信批次</div>
        <div class="stat-value">{{ batchStats.page_credit_count }}</div>
        <div class="stat-meta">当前页统计</div>
      </el-card>
      <el-card shadow="hover">
        <div class="stat-label">待结算批次</div>
        <div class="stat-value">{{ batchStats.page_pending_settlement_count }}</div>
        <div class="stat-meta">当前页金额 ¥{{ centsToYuan(batchStats.page_total_amount_cents) }}</div>
      </el-card>
    </div>

    <el-alert
      v-if="lastActionMessage"
      :title="lastActionMessage"
      type="success"
      :closable="true"
      @close="lastActionMessage = ''"
    />

    <div class="form-grid">
      <el-card shadow="hover">
        <template #header>
          <div class="card-header">
            <span>立即生成卡密</span>
            <span class="card-tip">{{ generationTip }}</span>
          </div>
        </template>
        <el-form label-position="top">
          <el-form-item label="规格">
            <el-select v-model="batchForm.plan_code" filterable>
              <el-option
                v-for="plan in activePlans"
                :key="plan.plan_code"
                :label="`${plan.display_name} / ¥${centsToYuan(plan.price_cents)}`"
                :value="plan.plan_code"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="数量">
            <el-input-number v-model="batchForm.quantity" :min="1" :max="500" />
          </el-form-item>
          <el-form-item label="前缀">
            <el-input v-model.trim="batchForm.prefix" />
          </el-form-item>
          <el-form-item label="有效天数">
            <el-input-number v-model="batchForm.valid_days" :min="1" />
          </el-form-item>
          <el-form-item v-if="!isPlatformOperator" label="资金来源">
            <el-radio-group v-model="batchForm.funding_source">
              <el-radio-button label="balance">余额直接生成</el-radio-button>
              <el-radio-button label="credit" :disabled="!store.profile?.account.is_credit_whitelisted">授信兜底生成</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <div v-if="!isPlatformOperator && balanceWarning" class="warning-tip">{{ balanceWarning }}</div>
          <el-button type="primary" :loading="submittingBatch" @click="submitGenerateBatch">提交生成</el-button>
        </el-form>
      </el-card>
    </div>

    <el-card v-if="canDirectSettle && settlementRows.length" shadow="hover">
      <template #header>
        <div class="card-header">
          <span>待结算授信批次</span>
          <span class="card-tip">当前由你负责结清的授信批次可在这里直接完成结算</span>
        </div>
      </template>
      <el-table v-if="!isCompact" :data="settlementRows" stripe>
        <el-table-column label="规格" width="140">
          <template #default="{ row }">{{ planDisplayName(row.plan_code, row.plan_display_name) }}</template>
        </el-table-column>
        <el-table-column label="已使用 / 总数" width="140">
          <template #default="{ row }">{{ row.used_count || 0 }} / {{ row.total_count || row.quantity }}</template>
        </el-table-column>
        <el-table-column label="金额" width="120">
          <template #default="{ row }">¥{{ centsToYuan(row.total_amount_cents) }}</template>
        </el-table-column>
        <el-table-column label="对手方" width="140">
          <template #default="{ row }">{{ row.current_counterparty_name || '待上级结清' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link :loading="settlingBatchId === row.batch_id" @click="settleBatch(row.batch_id)">直接结清</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-else class="mobile-card-list">
        <div v-for="row in settlementRows" :key="row.batch_id" class="mobile-data-card">
          <div class="mobile-data-card__header">
            <div>
              <div class="mobile-data-card__title">{{ planDisplayName(row.plan_code, row.plan_display_name) }}</div>
              <div class="mobile-data-card__subtitle">{{ formatDateTime(row.created_at) }}</div>
            </div>
            <el-tag type="warning">待结清</el-tag>
          </div>
          <div class="mobile-data-card__grid">
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">金额</span>
              <span class="mobile-data-card__value">¥{{ centsToYuan(row.total_amount_cents) }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">已使用 / 总数</span>
              <span class="mobile-data-card__value">{{ row.used_count || 0 }} / {{ row.total_count || row.quantity }}</span>
            </div>
          </div>
          <div class="mobile-action-bar">
            <el-button type="primary" :loading="settlingBatchId === row.batch_id" @click="settleBatch(row.batch_id)">直接结清</el-button>
          </div>
        </div>
      </div>
    </el-card>

    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>卡密批次</span>
          <div class="header-actions">
            <el-button v-if="isCompact" class="mobile-filter-trigger" @click="batchFiltersVisible = true">筛选条件</el-button>
            <template v-else>
              <el-select v-model="batchFilters.plan_code" clearable placeholder="规格" style="width: 140px">
                <el-option v-for="plan in activePlans" :key="plan.plan_code" :label="plan.display_name" :value="plan.plan_code" />
              </el-select>
              <el-select v-model="batchFilters.payment_status" placeholder="支付状态" style="width: 140px">
                <el-option label="全部支付" value="all" />
                <el-option label="已支付" value="paid" />
                <el-option label="授信" value="credit" />
              </el-select>
              <el-select v-model="batchFilters.settlement_status" placeholder="结算状态" style="width: 140px">
                <el-option label="全部结算" value="all" />
                <el-option label="已结算" value="settled" />
                <el-option label="待结算" value="pending" />
              </el-select>
              <el-input v-model.trim="batchFilters.keyword" clearable placeholder="搜索规格" style="width: 220px" />
              <el-button @click="loadBatchRows(true)">查询</el-button>
              <el-button @click="loadBatchRows()">刷新</el-button>
            </template>
          </div>
        </div>
      </template>
      <el-table v-if="!isCompact" :data="batchRows" stripe @row-click="handleBatchRowClick">
        <el-table-column label="规格" width="140">
          <template #default="{ row }">{{ planDisplayName(row.plan_code, row.plan_display_name) }}</template>
        </el-table-column>
        <el-table-column label="已使用 / 总数" width="140">
          <template #default="{ row }">{{ row.used_count || 0 }} / {{ row.total_count || row.quantity }}</template>
        </el-table-column>
        <el-table-column label="单价" width="120">
          <template #default="{ row }">¥{{ centsToYuan(row.unit_price_cents) }}</template>
        </el-table-column>
        <el-table-column label="总额" width="120">
          <template #default="{ row }">¥{{ centsToYuan(row.total_amount_cents) }}</template>
        </el-table-column>
        <el-table-column label="支付" width="110">
          <template #default="{ row }">
            <el-tag :type="row.payment_status === 'paid' ? 'success' : 'warning'">{{ paymentStatusLabel(row.payment_status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="结算" width="110">
          <template #default="{ row }">
            <el-tag :type="row.settlement_status === 'settled' ? 'success' : 'warning'">{{ settlementStatusLabel(row.settlement_status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="时间" min-width="160">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openBatchDetails(row)">查看明细</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-else class="mobile-card-list">
        <div v-for="row in batchRows" :key="row.batch_id" class="mobile-data-card">
          <div class="mobile-data-card__header">
            <div>
              <div class="mobile-data-card__title">{{ planDisplayName(row.plan_code, row.plan_display_name) }}</div>
              <div class="mobile-data-card__subtitle">{{ formatDateTime(row.created_at) }}</div>
            </div>
            <el-tag :type="row.payment_status === 'paid' ? 'success' : 'warning'">{{ paymentStatusLabel(row.payment_status) }}</el-tag>
          </div>
          <div class="mobile-data-card__grid">
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">已使用 / 总数</span>
              <span class="mobile-data-card__value">{{ row.used_count || 0 }} / {{ row.total_count || row.quantity }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">单价</span>
              <span class="mobile-data-card__value">¥{{ centsToYuan(row.unit_price_cents) }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">总额</span>
              <span class="mobile-data-card__value">¥{{ centsToYuan(row.total_amount_cents) }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">结算</span>
              <span class="mobile-data-card__value">{{ settlementStatusLabel(row.settlement_status) }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">时间</span>
              <span class="mobile-data-card__value">{{ formatDateTime(row.created_at) }}</span>
            </div>
          </div>
          <div class="mobile-action-bar">
            <el-button type="primary" plain @click="openBatchDetails(row)">查看该批次明细</el-button>
          </div>
        </div>
      </div>
      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="batchPagination.currentPage"
          v-model:page-size="batchPagination.pageSize"
          background
          layout="total, sizes, prev, pager, next"
          :page-sizes="[20, 50, 100]"
          :total="batchTotal"
          @current-change="handleBatchPageChange"
          @size-change="handleBatchSizeChange"
        />
      </div>
    </el-card>

    <div ref="cardSectionRef">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <div class="header-title-stack">
            <span>卡密明细</span>
            <span v-if="activeBatchDetail.summary" class="card-tip">{{ activeBatchDetail.summary }}</span>
          </div>
          <div class="header-actions">
            <el-button v-if="isCompact" class="mobile-filter-trigger" @click="cardFiltersVisible = true">筛选条件</el-button>
            <template v-else>
              <el-select v-model="cardFilters.plan_code" clearable placeholder="规格" style="width: 140px">
                <el-option v-for="plan in activePlans" :key="plan.plan_code" :label="plan.display_name" :value="plan.plan_code" />
              </el-select>
              <el-select v-model="cardFilters.status" placeholder="卡密状态" style="width: 140px">
                <el-option label="全部状态" value="all" />
                <el-option label="可用" value="available" />
                <el-option label="已使用" value="used" />
              </el-select>
              <el-select v-model="cardFilters.source_type" placeholder="来源" style="width: 140px">
                <el-option label="全部来源" value="all" />
                <el-option label="余额" value="balance" />
                <el-option label="授信" value="credit" />
                <el-option label="平台直生" value="platform" />
                <el-option label="旧系统" value="legacy" />
              </el-select>
              <el-input v-model.trim="cardFilters.keyword" clearable placeholder="搜索卡密/规格" style="width: 220px" />
              <el-button @click="loadCardRows(true)">查询</el-button>
              <el-button v-if="canExportCards" @click="exportExcel">导出 Excel</el-button>
              <el-button v-if="canCopyCards" type="primary" :disabled="!selectedCards.length" @click="copySelectedCards(false)">复制卡密</el-button>
              <el-button v-if="canCopyCards" type="primary" plain :disabled="!selectedCards.length" @click="copySelectedCards(true)">复制卡密+元数据</el-button>
              <el-button v-if="activeBatchDetail.batchId" @click="clearBatchDetailFilter">清除批次筛选</el-button>
            </template>
          </div>
        </div>
      </template>
      <el-alert
        v-if="activeBatchDetail.batchId"
        title="当前正在查看指定批次的全部卡密"
        type="info"
        :closable="false"
      >
        <template #default>
          <div class="detail-alert-content">
            <span>{{ activeBatchDetail.summary }}</span>
            <el-button link type="primary" @click="clearBatchDetailFilter">返回全部卡密</el-button>
          </div>
        </template>
      </el-alert>
      <div class="selection-bar">已选择 {{ selectedCards.length }} 条卡密，当前总数 {{ cardTotal }}，单次最多复制 {{ copyCardLimit }} 条</div>
      <el-table v-if="!isCompact" :data="cardRows" stripe @selection-change="handleSelectionChange">
        <el-table-column type="selection" width="48" />
        <el-table-column prop="card_code" label="卡密" min-width="180" />
        <el-table-column label="规格" width="140">
          <template #default="{ row }">{{ planDisplayName(row.plan_code, row.plan_display_name) }}</template>
        </el-table-column>
        <el-table-column prop="card_source_type" label="来源" width="120" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_used ? 'warning' : 'success'">{{ row.is_used ? '已使用' : '可用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="使用时间" min-width="160">
          <template #default="{ row }">{{ formatDateTime(row.used_at) || '-' }}</template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="160">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>
      <div v-else class="mobile-card-list">
        <div v-for="row in cardRows" :key="row.id" class="mobile-data-card">
          <div class="mobile-data-card__header">
            <div>
              <div class="mobile-data-card__title">{{ row.card_code }}</div>
              <div class="mobile-data-card__subtitle">{{ planDisplayName(row.plan_code, row.plan_display_name) }} · {{ sourceTypeLabel(row.card_source_type) }}</div>
            </div>
            <el-checkbox :model-value="isSelected(row.id)" @change="toggleCardSelection(row)" />
          </div>
          <div class="mobile-data-card__grid">
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">来源</span>
              <span class="mobile-data-card__value">{{ row.card_source_type }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">状态</span>
              <span class="mobile-data-card__value">{{ row.is_used ? '已使用' : '可用' }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">使用时间</span>
              <span class="mobile-data-card__value">{{ formatDateTime(row.used_at) || '-' }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">创建时间</span>
              <span class="mobile-data-card__value">{{ formatDateTime(row.created_at) }}</span>
            </div>
          </div>
        </div>
      </div>
      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="cardPagination.currentPage"
          v-model:page-size="cardPagination.pageSize"
          background
          layout="total, sizes, prev, pager, next"
          :page-sizes="[20, 50, 100]"
          :total="cardTotal"
          @current-change="handleCardPageChange"
          @size-change="handleCardSizeChange"
        />
      </div>
    </el-card>
    </div>

    <el-drawer v-model="batchFiltersVisible" title="筛选卡密批次" size="100%" append-to-body>
      <div class="mobile-card-list">
        <el-select v-model="batchFilters.plan_code" clearable placeholder="规格">
          <el-option v-for="plan in activePlans" :key="plan.plan_code" :label="plan.display_name" :value="plan.plan_code" />
        </el-select>
        <el-select v-model="batchFilters.payment_status" placeholder="支付状态">
          <el-option label="全部支付" value="all" />
          <el-option label="已支付" value="paid" />
          <el-option label="授信" value="credit" />
        </el-select>
        <el-select v-model="batchFilters.settlement_status" placeholder="结算状态">
          <el-option label="全部结算" value="all" />
          <el-option label="已结算" value="settled" />
          <el-option label="待结算" value="pending" />
        </el-select>
        <el-input v-model.trim="batchFilters.keyword" clearable placeholder="搜索规格" />
        <div class="mobile-action-bar">
          <el-button @click="batchFiltersVisible = false">关闭</el-button>
          <el-button @click="loadBatchRows()">刷新</el-button>
          <el-button type="primary" @click="applyBatchFilters">应用筛选</el-button>
        </div>
      </div>
    </el-drawer>

    <el-drawer v-model="cardFiltersVisible" title="筛选卡密明细" size="100%" append-to-body>
      <div class="mobile-card-list">
        <el-select v-model="cardFilters.plan_code" clearable placeholder="规格">
          <el-option v-for="plan in activePlans" :key="plan.plan_code" :label="plan.display_name" :value="plan.plan_code" />
        </el-select>
        <el-select v-model="cardFilters.status" placeholder="卡密状态">
          <el-option label="全部状态" value="all" />
          <el-option label="可用" value="available" />
          <el-option label="已使用" value="used" />
        </el-select>
        <el-select v-model="cardFilters.source_type" placeholder="来源">
          <el-option label="全部来源" value="all" />
          <el-option label="余额" value="balance" />
          <el-option label="授信" value="credit" />
          <el-option label="平台直生" value="platform" />
          <el-option label="旧系统" value="legacy" />
        </el-select>
        <el-input v-model.trim="cardFilters.keyword" clearable placeholder="搜索卡密/规格" />
        <div class="mobile-action-bar">
          <el-button v-if="canExportCards" @click="exportExcel">导出 Excel</el-button>
          <el-button v-if="canCopyCards" type="primary" plain :disabled="!selectedCards.length" @click="copySelectedCards(false)">复制卡密</el-button>
          <el-button v-if="canCopyCards" type="primary" :disabled="!selectedCards.length" @click="copySelectedCards(true)">复制卡密+元数据</el-button>
          <el-button v-if="activeBatchDetail.batchId" @click="clearBatchDetailFilter">清除批次筛选</el-button>
          <el-button @click="cardFiltersVisible = false">关闭</el-button>
          <el-button type="primary" @click="applyCardFilters">应用筛选</el-button>
        </div>
      </div>
    </el-drawer>

    <el-drawer v-model="resultDrawer.visible" title="卡密生成完成" size="420px" append-to-body>
      <div class="mobile-card-list">
        <div class="mobile-data-card">
          <div class="mobile-data-card__grid">
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">规格</span>
              <span class="mobile-data-card__value">{{ planDisplayName(resultDrawer.planCode, resultDrawer.planDisplayName) }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">生成数量</span>
              <span class="mobile-data-card__value">{{ resultDrawer.quantity || 0 }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">总金额</span>
              <span class="mobile-data-card__value">¥{{ centsToYuan(resultDrawer.totalAmountCents) }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">资金来源</span>
              <span class="mobile-data-card__value">{{ fundingSourceLabel(resultDrawer.fundingSource) }}</span>
            </div>
            <div class="mobile-data-card__row">
              <span class="mobile-data-card__label">创建时间</span>
              <span class="mobile-data-card__value">{{ formatDateTime(resultDrawer.createdAt) }}</span>
            </div>
          </div>
        </div>
        <div v-if="resultDrawer.quantity > copyCardLimit" class="copy-limit-tip">
          本批数量较多，单次最多复制最近创建的 {{ copyCardLimit }} 条，其余卡密可进入明细继续筛选或导出。
        </div>
        <div class="mobile-action-bar">
          <el-button @click="resultDrawer.visible = false">关闭</el-button>
          <el-button v-if="canCopyCards" type="primary" plain @click="copyGeneratedCards">复制本次卡密</el-button>
          <el-button type="primary" @click="jumpToGeneratedBatchDetail">查看该批次明细</el-button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { AgentCard, CardBatch } from '@/api/admin'
import {
  adminExportCardsXlsx,
  adminGenerateCardBatch,
  adminListCardBatches,
  adminListCards,
  adminSettleBatchDirect,
} from '@/api/admin'
import { useAdminConsoleStore } from '@/stores/adminConsole'
import { centsToYuan, formatDateTime } from '@/utils/adminConsole'
import { useResponsive } from '@/composables/useResponsive'

const store = useAdminConsoleStore()
const { isCompact } = useResponsive()
const COPY_CARD_LIMIT = 40
const canGenerateBatches = computed(() => store.hasPermission('batches.generate'))
const canExportCards = computed(() => store.hasPermission('batches.export'))
const canCopyCards = computed(() => store.hasPermission('batches.copy'))
const canReadPricing = computed(() => store.hasPermission('pricing.read'))
const canReadLedgers = computed(() => store.hasPermission('ledgers.read'))
const canDirectSettle = computed(() => store.hasPermission('agents.write'))
const isPlatformOperator = computed(() => store.profile?.account.account_type === 'staff')
const submittingBatch = ref(false)
const settlingBatchId = ref('')
const selectedCards = ref<AgentCard[]>([])
const cardSectionRef = ref<HTMLElement | null>(null)
const lastActionMessage = ref('')
const batchFiltersVisible = ref(false)
const cardFiltersVisible = ref(false)
const batchRows = ref<CardBatch[]>([])
const cardRows = ref<AgentCard[]>([])
const batchTotal = ref(0)
const cardTotal = ref(0)
const batchStats = reactive({
  page_total_amount_cents: 0,
  page_paid_count: 0,
  page_credit_count: 0,
  page_pending_settlement_count: 0,
})

const activePlans = computed(() => store.plans.filter((plan) => plan.is_active))
const selectedPlan = computed(() => activePlans.value.find((plan) => plan.plan_code === batchForm.plan_code))
const estimatedBatchAmountCents = computed(() => (selectedPlan.value?.price_cents || 0) * Number(batchForm.quantity || 0))
const generationTip = computed(() => {
  if (isPlatformOperator.value) {
    return '超管走平台直生，不占用余额、不走授信、不经过审批'
  }
  return '默认先扣余额生成；余额不足时，只有授信白名单代理可走授信兜底'
})
const settlementRows = computed(() =>
  batchRows.value.filter(
    (row) =>
      row.payment_status === 'credit' &&
      row.settlement_status === 'pending' &&
      Number(row.current_liability_account_id || 0) === Number(store.profile?.account.id || 0),
  ),
)
const balanceWarning = computed(() => {
  if (isPlatformOperator.value) return ''
  const amount = estimatedBatchAmountCents.value
  if (!amount) return ''
  const balance = Number(store.profile?.account.balance_cents || 0)
  if (balance >= amount) return ''
  if (store.profile?.account.is_credit_whitelisted) {
    return `当前余额不足 ¥${centsToYuan(amount - balance)}，如需立即出卡可切换到“授信兜底生成”。`
  }
  return `当前余额不足 ¥${centsToYuan(amount - balance)}，且未开通授信白名单，请先发起线下充值入账。`
})
const batchPagination = reactive({
  currentPage: 1,
  pageSize: 20,
})
const cardPagination = reactive({
  currentPage: 1,
  pageSize: 20,
})

const batchForm = reactive({
  plan_code: '',
  quantity: 1,
  prefix: '',
  valid_days: 30,
  funding_source: 'balance' as 'balance' | 'credit',
})

const batchFilters = reactive({
  plan_code: '',
  payment_status: 'all',
  settlement_status: 'all',
  keyword: '',
})

const cardFilters = reactive({
  batch_id: '',
  plan_code: '',
  status: 'all',
  source_type: 'all',
  keyword: '',
})

const activeBatchDetail = reactive({
  batchId: '',
  summary: '',
})

const resultDrawer = reactive({
  visible: false,
  batchId: '',
  planCode: '',
  planDisplayName: '',
  quantity: 0,
  totalAmountCents: 0,
  fundingSource: '',
  createdAt: '' as string | null,
  summary: '',
  generatedCards: [] as AgentCard[],
  copiedText: '',
})

const copyCardLimit = COPY_CARD_LIMIT

const initDefaultPlan = () => {
  const firstPlan = activePlans.value[0]
  if (firstPlan && !batchForm.plan_code) {
    batchForm.plan_code = firstPlan.plan_code
  }
}

const loadBatchRows = async (resetPage = false) => {
  if (resetPage) batchPagination.currentPage = 1
  const response = await adminListCardBatches({
    plan_code: batchFilters.plan_code || undefined,
    payment_status: batchFilters.payment_status === 'all' ? undefined : batchFilters.payment_status,
    settlement_status: batchFilters.settlement_status === 'all' ? undefined : batchFilters.settlement_status,
    keyword: batchFilters.keyword || undefined,
    limit: batchPagination.pageSize,
    offset: (batchPagination.currentPage - 1) * batchPagination.pageSize,
  })
  batchRows.value = response.data.items
  batchTotal.value = response.data.total
  if (!batchRows.value.length && batchTotal.value > 0 && batchPagination.currentPage > 1) {
    batchPagination.currentPage -= 1
    await loadBatchRows()
    return
  }
  Object.assign(batchStats, response.data.stats || {
    page_total_amount_cents: 0,
    page_paid_count: 0,
    page_credit_count: 0,
    page_pending_settlement_count: 0,
  })
}

const loadCardRows = async (resetPage = false) => {
  if (resetPage) cardPagination.currentPage = 1
  const response = await adminListCards({
    batch_id: cardFilters.batch_id || undefined,
    plan_code: cardFilters.plan_code || undefined,
    status: cardFilters.status === 'all' ? undefined : cardFilters.status,
    source_type: cardFilters.source_type === 'all' ? undefined : cardFilters.source_type,
    keyword: cardFilters.keyword || undefined,
    limit: cardPagination.pageSize,
    offset: (cardPagination.currentPage - 1) * cardPagination.pageSize,
  })
  cardRows.value = response.data.items
  cardTotal.value = response.data.total
  selectedCards.value = []
  if (!cardRows.value.length && cardTotal.value > 0 && cardPagination.currentPage > 1) {
    cardPagination.currentPage -= 1
    await loadCardRows()
  }
}

const refreshData = async () => {
  const tasks: Promise<unknown>[] = [
    loadBatchRows(),
    loadCardRows(),
  ]
  if (canReadPricing.value) {
    tasks.push(store.loadPlans())
  }
  await Promise.all(tasks)
  initDefaultPlan()
}

const handleBatchPageChange = async () => {
  await loadBatchRows()
}

const handleBatchSizeChange = async () => {
  batchPagination.currentPage = 1
  await loadBatchRows()
}

const handleCardPageChange = async () => {
  await loadCardRows()
}

const handleCardSizeChange = async () => {
  cardPagination.currentPage = 1
  await loadCardRows()
}

const applyBatchFilters = async () => {
  batchFiltersVisible.value = false
  await loadBatchRows(true)
}

const applyCardFilters = async () => {
  cardFiltersVisible.value = false
  await loadCardRows(true)
}

const paymentStatusLabel = (status: string) => (status === 'paid' ? '已支付' : status === 'credit' ? '授信' : status || '-')
const settlementStatusLabel = (status: string) => (status === 'settled' ? '已结算' : status === 'pending' ? '待结算' : status || '-')
const sourceTypeLabel = (status: string) => {
  if (status === 'balance') return '余额'
  if (status === 'credit') return '授信'
  if (status === 'platform') return '平台直生'
  if (status === 'legacy') return '旧系统'
  return status || '-'
}
const fundingSourceLabel = (status: string) => {
  if (status === 'platform') return '平台直生'
  return sourceTypeLabel(status)
}
const planDisplayName = (planCode?: string | null, planDisplayNameValue?: string | null) =>
  planDisplayNameValue ||
  activePlans.value.find((plan) => plan.plan_code === planCode)?.display_name ||
  '规格已记录'
const buildBatchSummary = (row: Pick<CardBatch, 'plan_code' | 'used_count' | 'total_count' | 'quantity' | 'created_at'>) =>
  `${planDisplayName(row.plan_code, (row as CardBatch).plan_display_name)} · 已使用 ${row.used_count || 0} / ${row.total_count || row.quantity} · ${formatDateTime(row.created_at)}`

const cardCreatedTime = (card: AgentCard) => {
  const timestamp = card.created_at ? new Date(card.created_at).getTime() : 0
  return Number.isFinite(timestamp) ? timestamp : 0
}

const latestCardsForCopy = (cards: AgentCard[]) =>
  [...cards]
    .sort((left, right) => cardCreatedTime(right) - cardCreatedTime(left) || Number(right.id) - Number(left.id))
    .slice(0, COPY_CARD_LIMIT)
    .sort((left, right) => cardCreatedTime(left) - cardCreatedTime(right) || Number(left.id) - Number(right.id))

const copyTextToClipboard = async (text: string) => {
  if (!text) {
    throw new Error('复制内容为空')
  }
  if (window.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return
    } catch {
      // Fall through to the textarea copy path for mobile WebViews and local HTTP admin pages.
    }
  }
  const textArea = document.createElement('textarea')
  textArea.value = text
  textArea.setAttribute('readonly', 'true')
  textArea.style.position = 'fixed'
  textArea.style.top = '0'
  textArea.style.left = '-9999px'
  textArea.style.width = '1px'
  textArea.style.height = '1px'
  textArea.style.opacity = '0'
  document.body.appendChild(textArea)
  const activeElement = document.activeElement instanceof HTMLElement ? document.activeElement : null
  textArea.focus()
  textArea.select()
  textArea.setSelectionRange(0, textArea.value.length)
  let success = false
  try {
    success = document.execCommand('copy')
  } finally {
    document.body.removeChild(textArea)
    activeElement?.focus()
  }
  if (!success) {
    throw new Error('浏览器拒绝复制，请手动长按选择卡密复制')
  }
}

const formatCopiedCards = (cards: AgentCard[], withMeta = false) =>
  cards
    .map((card) => (withMeta ? `${card.card_code} | ${card.plan_code || '-'} | ${card.batch_id || '-'}` : card.card_code))
    .join('\n')

const showCopySuccess = (count: number, total: number, withMeta = false) => {
  const suffix = withMeta ? '（附带元数据）' : ''
  lastActionMessage.value = `已复制 ${count} 条卡密${suffix}`
  if (total > count) {
    ElMessage.warning(`本次共 ${total} 条，已复制最近创建的 ${count} 条`)
    return
  }
  ElMessage.success(`已复制 ${count} 条卡密`)
}

const showCopyFailure = (error: unknown) => {
  const message = error instanceof Error ? error.message : '复制失败，请手动长按选择卡密复制'
  ElMessage.error(message)
}

const scrollToCardSection = () => {
  requestAnimationFrame(() => {
    cardSectionRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
}

const openBatchDetails = async (row: CardBatch) => {
  activeBatchDetail.batchId = row.batch_id
  activeBatchDetail.summary = buildBatchSummary(row)
  cardFilters.batch_id = row.batch_id
  await loadCardRows(true)
  scrollToCardSection()
}

const handleBatchRowClick = async (row: CardBatch) => {
  await openBatchDetails(row)
}

const clearBatchDetailFilter = async () => {
  activeBatchDetail.batchId = ''
  activeBatchDetail.summary = ''
  cardFilters.batch_id = ''
  await loadCardRows(true)
}

const submitGenerateBatch = async () => {
  if (!canGenerateBatches.value) {
    ElMessage.warning('当前账号无权生成卡密批次')
    return
  }
  if (!isPlatformOperator.value && batchForm.funding_source === 'balance') {
    const balance = Number(store.profile?.account.balance_cents || 0)
    if (balance < estimatedBatchAmountCents.value) {
      if (store.profile?.account.is_credit_whitelisted) {
        ElMessage.warning('当前余额不足，请切换到“授信兜底生成”或先充值到账')
      } else {
        ElMessage.warning('当前余额不足且未开通授信白名单，请先充值到账')
      }
      return
    }
  }
  if (!isPlatformOperator.value && batchForm.funding_source === 'credit' && !store.profile?.account.is_credit_whitelisted) {
    ElMessage.warning('当前账号未开通授信白名单，不能使用授信生成')
    return
  }
  submittingBatch.value = true
  try {
    const response = await adminGenerateCardBatch(batchForm)
    const tasks: Promise<unknown>[] = [store.loadProfile(), loadBatchRows(), loadCardRows()]
    if (canReadLedgers.value) {
      tasks.push(store.loadSelfLedgers())
    }
    await Promise.all(tasks)
    resultDrawer.visible = true
    resultDrawer.batchId = response.data.batch.batch_id
    resultDrawer.planCode = response.data.batch.plan_code
    resultDrawer.planDisplayName = response.data.batch.plan_display_name || ''
    resultDrawer.quantity = response.data.batch.quantity
    resultDrawer.totalAmountCents = response.data.batch.total_amount_cents
    resultDrawer.fundingSource = isPlatformOperator.value ? 'platform' : batchForm.funding_source
    resultDrawer.createdAt = response.data.batch.created_at
    resultDrawer.summary = buildBatchSummary(response.data.batch)
    resultDrawer.generatedCards = response.data.cards || []
    resultDrawer.copiedText = response.data.copied_text || ''
    lastActionMessage.value = `新卡密已生成，共 ${response.data.batch.quantity} 张，金额 ¥${centsToYuan(response.data.batch.total_amount_cents)}`
    ElMessage.success('卡密批次已生成')
  } finally {
    submittingBatch.value = false
  }
}

const jumpToGeneratedBatchDetail = async () => {
  if (!resultDrawer.batchId) {
    resultDrawer.visible = false
    return
  }
  const matchingBatch = batchRows.value.find((item) => item.batch_id === resultDrawer.batchId)
  activeBatchDetail.batchId = resultDrawer.batchId
  activeBatchDetail.summary = matchingBatch ? buildBatchSummary(matchingBatch) : resultDrawer.summary
  cardFilters.batch_id = resultDrawer.batchId
  resultDrawer.visible = false
  await loadCardRows(true)
  scrollToCardSection()
}

const handleSelectionChange = (rows: AgentCard[]) => {
  selectedCards.value = rows
}

const isSelected = (cardId: number) => selectedCards.value.some((item) => item.id === cardId)

const toggleCardSelection = (row: AgentCard) => {
  if (isSelected(row.id)) {
    selectedCards.value = selectedCards.value.filter((item) => item.id !== row.id)
    return
  }
  selectedCards.value = [...selectedCards.value, row]
}

const copyGeneratedCards = async () => {
  if (!canCopyCards.value) {
    ElMessage.warning('当前账号无权复制卡密')
    return
  }
  const cards = latestCardsForCopy(resultDrawer.generatedCards)
  const copiedText = cards.length ? formatCopiedCards(cards) : resultDrawer.copiedText
  const copiedCount = cards.length || copiedText.split('\n').filter(Boolean).length
  if (!copiedText) {
    ElMessage.warning('本次生成结果中没有可复制的卡密，请进入明细后再复制')
    return
  }
  try {
    await copyTextToClipboard(copiedText)
    showCopySuccess(copiedCount, resultDrawer.quantity || copiedCount)
  } catch (error) {
    showCopyFailure(error)
  }
}

const copySelectedCards = async (withMeta: boolean) => {
  if (!canCopyCards.value) {
    ElMessage.warning('当前账号无权复制卡密')
    return
  }
  if (!selectedCards.value.length) {
    ElMessage.warning('请先选择卡密')
    return
  }
  const cardsToCopy = latestCardsForCopy(selectedCards.value)
  const copiedText = formatCopiedCards(cardsToCopy, withMeta)
  try {
    await copyTextToClipboard(copiedText)
    showCopySuccess(cardsToCopy.length, selectedCards.value.length, withMeta)
  } catch (error) {
    showCopyFailure(error)
  }
}

const exportExcel = async () => {
  if (!canExportCards.value) {
    ElMessage.warning('当前账号无权导出卡密')
    return
  }
  const file = await adminExportCardsXlsx({
    plan_code: cardFilters.plan_code || undefined,
    batch_id: cardFilters.batch_id || undefined,
    status: cardFilters.status === 'all' ? undefined : cardFilters.status,
    source_type: cardFilters.source_type === 'all' ? undefined : cardFilters.source_type,
    keyword: cardFilters.keyword || undefined,
  })
  const url = window.URL.createObjectURL(file)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `agent-cards-${Date.now()}.xlsx`
  anchor.click()
  window.URL.revokeObjectURL(url)
  lastActionMessage.value = '卡密 Excel 已导出'
}

const settleBatch = async (batchId: string) => {
  if (!canDirectSettle.value) {
    ElMessage.warning('当前账号无权直接结清授信批次')
    return
  }
  settlingBatchId.value = batchId
  try {
    const response = await adminSettleBatchDirect(batchId)
    const tasks: Promise<unknown>[] = [store.loadProfile(), loadBatchRows(), loadCardRows()]
    if (canReadLedgers.value) {
      tasks.push(store.loadSelfLedgers())
    }
    await Promise.all(tasks)
    lastActionMessage.value = '授信批次已直接结清'
    ElMessage.success('授信批次已直接结清')
  } finally {
    settlingBatchId.value = ''
  }
}

onMounted(async () => {
  await refreshData()
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
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 20px;
}

.stat-label {
  color: #64748b;
  font-size: 13px;
}

.stat-value {
  margin-top: 10px;
  font-size: 28px;
  font-weight: 700;
  color: #0f172a;
}

.stat-meta,
.selection-bar {
  margin-top: 10px;
  color: #64748b;
  font-size: 13px;
}

.warning-tip {
  margin: 4px 0 16px;
  color: #b45309;
  font-size: 13px;
  line-height: 1.6;
}

.copy-limit-tip {
  color: #b45309;
  font-size: 13px;
  line-height: 1.6;
}

.form-grid {
  display: block;
}

.card-header,
.header-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.header-title-stack {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.detail-alert-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.card-tip {
  color: #94a3b8;
  font-size: 12px;
}

@media (max-width: 768px) {
  .detail-alert-content {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
