/**
 * Pure utility functions extracted from Tasks.vue.
 * No Vue reactivity dependencies — safe to import anywhere.
 */
import type { TaskDetail } from '@/api/task'

export interface ResourceOption {
  peer_id: number
  peer_type: string
  access_hash: number | null
  title: string
  username?: string | null
}

/* ------------------------------------------------------------------ */
/*  Peer-type metadata                                                */
/* ------------------------------------------------------------------ */

const peerTypeMeta: Record<string, { icon: string; label: string }> = {
  user: { icon: '👤', label: '个人' },
  chat: { icon: '👥', label: '群组' },
  supergroup: { icon: '👥', label: '群组' },
  channel: { icon: '📢', label: '频道' }
}

export const getPeerTypeMeta = (peerType: string) => {
  return peerTypeMeta[peerType] || { icon: '💬', label: peerType || '未知' }
}

/* ------------------------------------------------------------------ */
/*  Resource key helpers                                              */
/* ------------------------------------------------------------------ */

export const resourceKey = (res: ResourceOption) => `${res.peer_type}:${res.peer_id}`

export const displayResourceName = (res: ResourceOption): string => {
  const title = (res.title || '').trim()
  if (title) return title
  if (res.username) return `@${res.username}`
  return `未命名${getPeerTypeMeta(res.peer_type).label}`
}

export const resourceLabel = (res: ResourceOption) => {
  const meta = getPeerTypeMeta(res.peer_type)
  const name = displayResourceName(res)
  const suffix = res.username && !name.includes(`@${res.username}`) ? ` (@${res.username})` : ''
  return `${meta.icon} ${meta.label} · ${name}${suffix}`
}

/* ------------------------------------------------------------------ */
/*  Button helpers                                                    */
/* ------------------------------------------------------------------ */

export const normalizeButtonUrl = (rawUrl: string): string => {
  const candidate = rawUrl.trim()
  if (!candidate) return ''
  const withProtocol = /^https?:\/\//i.test(candidate) ? candidate : `https://${candidate}`
  try {
    const parsed = new URL(withProtocol)
    if (!['http:', 'https:'].includes(parsed.protocol)) return ''
    return parsed.toString()
  } catch (_err) {
    return ''
  }
}

export const parseButtonsText = (text: string): Array<Array<{ text: string; url: string }>> | null => {
  const normalized = (text || '').trim()
  if (!normalized) return null

  const rows = normalized
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  if (rows.length > 3) {
    throw new Error('最多支持 3 行按钮')
  }

  const buttons: Array<Array<{ text: string; url: string }>> = []
  for (const row of rows) {
    const cols = row
      .split('&&')
      .map((col) => col.trim())
      .filter(Boolean)
    if (cols.length > 3) {
      throw new Error('每行最多支持 3 个按钮')
    }

    const rowButtons: Array<{ text: string; url: string }> = []
    for (const col of cols) {
      const delimiterIndex = col.indexOf(' - ')
      if (delimiterIndex <= 0) {
        throw new Error(`按钮格式错误: ${col}（请使用 "文字 - 链接"）`)
      }

      const textPart = col.slice(0, delimiterIndex).trim()
      const urlPart = col.slice(delimiterIndex + 3).trim()
      const url = normalizeButtonUrl(urlPart)
      if (!textPart || !url) {
        throw new Error(`按钮格式错误: ${col}`)
      }
      rowButtons.push({ text: textPart, url })
    }

    if (rowButtons.length > 0) {
      buttons.push(rowButtons)
    }
  }

  return buttons.length > 0 ? buttons : null
}

export const formatButtonsText = (buttons: TaskDetail['buttons']): string => {
  if (!buttons || buttons.length === 0) return ''
  return buttons
    .map((row) => row.map((btn) => `${btn.text} - ${btn.url}`).join(' && '))
    .join('\n')
}

/* ------------------------------------------------------------------ */
/*  Resource key parsing                                              */
/* ------------------------------------------------------------------ */

export const parseResourceKey = (key: string, resources: ResourceOption[]): ResourceOption | null => {
  const [peerType, peerIdStr] = key.split(':')
  const peerId = Number(peerIdStr)
  if (!peerType || Number.isNaN(peerId)) return null
  return resources.find(r => r.peer_type === peerType && r.peer_id === peerId) || null
}

/* ------------------------------------------------------------------ */
/*  Timestamp helpers                                                 */
/* ------------------------------------------------------------------ */

export const toUnix = (localDatetime: string): number | null => {
  if (!localDatetime) return null
  const ts = Math.floor(new Date(localDatetime).getTime() / 1000)
  return Number.isNaN(ts) ? null : ts
}

export const fromUnix = (ts: number | null | undefined): string => {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export const formatUnix = (ts: number | null) => {
  if (!ts) return '-'
  return new Date(ts * 1000).toLocaleString()
}

/* ------------------------------------------------------------------ */
/*  Media helpers                                                     */
/* ------------------------------------------------------------------ */

export const prettyMediaType = (mediaType: string) => {
  const normalized = (mediaType || 'none').toLowerCase()
  const labelMap: Record<string, string> = {
    none: '纯文本',
    photo: '图片',
    video: '视频',
    animation: 'GIF',
    sticker: '贴纸'
  }
  return labelMap[normalized] || normalized
}

export const extractFileName = (uri: string): string => {
  if (!uri) return ''
  if (uri.startsWith('tgmsg://')) {
    const messageId = uri.split('/').pop() || ''
    return messageId ? `Telegram媒体 #${messageId}` : 'Telegram媒体'
  }
  const parts = uri.split(/[\\/]/)
  return parts[parts.length - 1] || uri
}
