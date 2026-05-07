/**
 * usePaginatedList — reusable composable for paginated data tables.
 *
 * Encapsulates: pagination state, page/size change handlers, empty-page fallback.
 */
import { reactive, ref, type Ref } from 'vue'

export interface PaginatedResponse<T> {
  items: T[]
  total: number
}

export interface UsePaginatedListOptions {
  /** Initial page size (default: 20) */
  defaultPageSize?: number
}

export function usePaginatedList<T>(
  fetchFn: (params: { limit: number; offset: number }) => Promise<{ data: PaginatedResponse<T> }>,
  options: UsePaginatedListOptions = {},
) {
  const { defaultPageSize = 20 } = options

  const rows = ref<T[]>([]) as Ref<T[]>
  const total = ref(0)
  const loading = ref(false)

  const pagination = reactive({
    currentPage: 1,
    pageSize: defaultPageSize,
  })

  const loadData = async (extraParams?: Record<string, unknown>) => {
    loading.value = true
    try {
      const response = await fetchFn({
        limit: pagination.pageSize,
        offset: (pagination.currentPage - 1) * pagination.pageSize,
        ...extraParams,
      })
      rows.value = response.data.items
      total.value = response.data.total

      // Empty-page fallback: if current page is empty but total > 0, go back one page
      if (!rows.value.length && total.value > 0 && pagination.currentPage > 1) {
        pagination.currentPage -= 1
        const retry = await fetchFn({
          limit: pagination.pageSize,
          offset: (pagination.currentPage - 1) * pagination.pageSize,
          ...extraParams,
        })
        rows.value = retry.data.items
        total.value = retry.data.total
      }
    } finally {
      loading.value = false
    }
  }

  const handlePageChange = (_page: number) => {
    loadData()
  }

  const handleSizeChange = (_size: number) => {
    pagination.currentPage = 1
    loadData()
  }

  const resetPage = () => {
    pagination.currentPage = 1
  }

  return {
    rows,
    total,
    loading,
    pagination,
    loadData,
    handlePageChange,
    handleSizeChange,
    resetPage,
  }
}
