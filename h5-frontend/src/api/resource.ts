/**
 * 资源相关 API
 */
import request from './request'
import type { ApiResponse } from './request'

/**
 * 资源接口
 */
export interface Resource {
  resource_id: number
  peer_id: number
  peer_type: 'user' | 'chat' | 'supergroup' | 'channel'
  access_hash: number | null
  title: string
  username: string | null
  description: string | null
  is_muted: boolean
  is_verified: boolean
  participants_count: number | null
  is_active: boolean
  last_sync_at: string | null
}

/**
 * Peer 类型枚举
 */
export enum PeerType {
  USER = 'user',
  CHAT = 'chat',
  SUPERGROUP = 'supergroup',
  CHANNEL = 'channel'
}
