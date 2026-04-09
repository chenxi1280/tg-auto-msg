<template>
  <div class="page-stack">
    <el-tabs v-model="activeTab" type="border-card">
      <el-tab-pane v-if="canReadBatches" label="卡密批次与明细" name="cards">
        <BatchesPage />
      </el-tab-pane>
      <el-tab-pane v-if="canReadLegacy" label="历史授权" name="slots">
        <LegacyCardsPage mode="slots" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import BatchesPage from '@/views/admin/BatchesPage.vue'
import LegacyCardsPage from '@/views/admin/LegacyCardsPage.vue'
import { useAdminConsoleStore } from '@/stores/adminConsole'

const route = useRoute()
const router = useRouter()
const store = useAdminConsoleStore()
const canReadBatches = computed(() => store.hasPermission('batches.read'))
const canReadLegacy = computed(() => store.hasPermission('legacy_cards.read'))

const resolveTab = () => {
  const requested = String(route.query.tab || '')
  if (requested === 'cards' && canReadBatches.value) return 'cards'
  if (requested === 'slots' && canReadLegacy.value) return 'slots'
  if (canReadBatches.value) return 'cards'
  if (canReadLegacy.value) return 'slots'
  return 'cards'
}

const activeTab = ref(resolveTab())

watch(
  () => [route.query.tab, canReadBatches.value, canReadLegacy.value],
  () => {
    const nextTab = resolveTab()
    if (activeTab.value !== nextTab) {
      activeTab.value = nextTab
    }
  },
  { immediate: true },
)

watch(activeTab, async (value) => {
  if (String(route.query.tab || '') !== value) {
    await router.replace({ query: { ...route.query, tab: value } })
  }
})
</script>

<style scoped>
.page-stack {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

:deep(.el-tabs) {
  border-radius: 24px;
  overflow: hidden;
}

:deep(.el-tabs__header) {
  padding: 8px 12px 0;
  margin: 0;
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(14px);
}

:deep(.el-tabs__nav-wrap::after) {
  display: none;
}

:deep(.el-tabs__content) {
  padding: 16px;
  background: rgba(255, 255, 255, 0.78);
  backdrop-filter: blur(14px);
}

@media (max-width: 960px) {
  :deep(.el-tabs__header) {
    padding: 8px 8px 0;
  }

  :deep(.el-tabs__nav) {
    display: flex;
    gap: 8px;
  }

  :deep(.el-tabs__item) {
    height: auto;
    padding: 10px 14px;
    border-radius: 999px 999px 0 0;
    font-size: 13px;
    line-height: 1.3;
    white-space: nowrap;
  }

  :deep(.el-tabs__content) {
    padding: 12px;
  }
}

@media (max-width: 768px) {
  .page-stack {
    gap: 12px;
  }

  :deep(.el-tabs__header) {
    padding: 8px 0 0;
    background: transparent;
  }

  :deep(.el-tabs__nav-wrap) {
    overflow-x: auto;
    scrollbar-width: none;
  }

  :deep(.el-tabs__nav-wrap::-webkit-scrollbar) {
    display: none;
  }

  :deep(.el-tabs__nav-scroll) {
    padding: 0 4px;
  }

  :deep(.el-tabs__nav) {
    flex-wrap: nowrap;
    min-width: max-content;
  }

  :deep(.el-tabs__item) {
    padding: 10px 12px;
    font-size: 12px;
  }

  :deep(.el-tabs__content) {
    padding: 10px;
    background: transparent;
    backdrop-filter: none;
  }
}
</style>
