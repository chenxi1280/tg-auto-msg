import * as accountApi from '@/api/account'
import type { AccountSyncStatusResponse } from '@/api/account'

const SYNC_POLL_INTERVAL_MS = 1_000
const SYNC_POLL_TIMEOUT_MS = 5 * 60 * 1_000

export class AccountSyncPollingError extends Error {}

const sleep = (milliseconds: number) => (
  new Promise<void>(resolve => window.setTimeout(resolve, milliseconds))
)

export async function waitForAccountSync(accountId: string): Promise<AccountSyncStatusResponse> {
  const deadline = Date.now() + SYNC_POLL_TIMEOUT_MS

  while (Date.now() < deadline) {
    const response = await accountApi.getAccountSyncStatus(accountId)
    if (response.status === 'completed') return response
    if (response.status === 'failed') {
      throw new AccountSyncPollingError(response.data?.error || response.message || '账号资源同步失败')
    }
    if (response.status === 'idle') {
      throw new AccountSyncPollingError('同步状态已丢失，服务可能已重启，请重新点击同步')
    }
    await sleep(SYNC_POLL_INTERVAL_MS)
  }

  throw new AccountSyncPollingError('等待账号资源同步完成超时，后台任务可能仍在执行')
}
