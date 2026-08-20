import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { AccountSyncPollingError } from '@/stores/accountSync'
import { displayResourceName, getPeerTypeMeta, resourceKey, type ResourceOption } from '@/utils/taskHelpers'

interface ResourceFormState {
  accountId: string
  targetKeys: string[]
}

interface ResourceStore {
  getAccountResources: (accountId: string, query: { is_active: boolean }) => Promise<unknown[]>
  syncAccount: (accountId: string, force: boolean) => Promise<{ message?: string }>
}

export const useTaskResources = (
  store: ResourceStore,
  form: ResourceFormState,
  emitResources: (resources: ResourceOption[]) => void
) => {
  const keyword = ref('')
  const resources = ref<ResourceOption[]>([])
  const loading = ref(false)
  const filtered = computed(() => {
    const normalized = keyword.value.trim().toLowerCase()
    if (!normalized) return resources.value
    return resources.value.filter((resource) => {
      const meta = getPeerTypeMeta(resource.peer_type)
      const searchable = [
        displayResourceName(resource),
        resource.username || '',
        String(resource.peer_id),
        meta.label,
        resource.peer_type
      ].join(' ').toLowerCase()
      return searchable.includes(normalized)
    })
  })

  const load = async (autoSyncIfEmpty = false, preserveTargets = true) => {
    if (!form.accountId) {
      resources.value = []
      form.targetKeys = []
      emitResources([])
      return
    }
    const previousTargets = preserveTargets ? [...form.targetKeys] : []
    resources.value = []
    if (!preserveTargets) form.targetKeys = []
    loading.value = true
    try {
      const query = { is_active: true }
      resources.value = await readResources(store, form.accountId, query)
      if (autoSyncIfEmpty && resources.value.length === 0) {
        ElMessage.info('正在同步聊天资源，请稍候...')
        const syncResult = await store.syncAccount(form.accountId, true)
        resources.value = await readResources(store, form.accountId, query)
        ElMessage.success(syncResult.message || '聊天资源同步完成')
      }
      const validKeys = new Set(resources.value.map(resourceKey))
      if (preserveTargets) form.targetKeys = previousTargets.filter((key) => validKeys.has(key))
      emitResources([...resources.value])
    } catch (error) {
      if (error instanceof AccountSyncPollingError) ElMessage.error(error.message)
    } finally {
      loading.value = false
    }
  }

  return { keyword, resources, loading, filtered, load }
}

async function readResources(
  store: ResourceStore,
  accountId: string,
  query: { is_active: boolean }
): Promise<ResourceOption[]> {
  return (await store.getAccountResources(accountId, query)) as ResourceOption[]
}
