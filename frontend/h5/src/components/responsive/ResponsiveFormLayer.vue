<template>
  <el-drawer
    v-if="isCompact"
    :model-value="modelValue"
    :title="title"
    :size="mobileSize"
    :destroy-on-close="destroyOnClose"
    append-to-body
    @close="emit('update:modelValue', false)"
  >
    <slot />
    <template #footer>
      <slot name="footer" />
    </template>
  </el-drawer>
  <el-dialog
    v-else
    :model-value="modelValue"
    :title="title"
    :width="width"
    :destroy-on-close="destroyOnClose"
    append-to-body
    @close="emit('update:modelValue', false)"
  >
    <slot />
    <template #footer>
      <slot name="footer" />
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { useResponsive } from '@/composables/useResponsive'

withDefaults(
  defineProps<{
    modelValue: boolean
    title: string
    width?: string
    mobileSize?: string
    destroyOnClose?: boolean
  }>(),
  {
    width: '520px',
    mobileSize: '100%',
    destroyOnClose: true,
  },
)

const emit = defineEmits<{
  'update:modelValue': [boolean]
}>()

const { isCompact } = useResponsive()
</script>
