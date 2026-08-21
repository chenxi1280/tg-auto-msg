/**
 * 任务相关 API
 */
import request from './request'
import type { ApiResponse } from './request'

export interface TaskItem {
  task_id: string
  account_id: string | null
  chat_id: number | null
  target_peer_id: number | null
  target_peer_type: string | null
  target_peers: Array<{ peer_id: number; peer_type: string; access_hash?: number | null }>
  title: string
  enabled: boolean
  trigger_mode: string
  shortcut_slot: number | null
  shortcut_label: string | null
  priority: number
  repeat_interval_min: number
  jitter_seconds: number
  delay_min_seconds: number
  delay_max_seconds: number
  day_start_hour: number | null
  day_end_hour: number | null
  start_at: number | null
  end_at: number | null
  text: string | null
  media_type: string
  media_source_state: string
  content_contract_version: number
  revision: number
  delete_previous: boolean
  pin_message: boolean
  next_run_at: number | null
  created_at: string | null
}

export interface TaskDetail extends TaskItem {
  user_id: number
  target_access_hash: number | null
  media_source_meta: Record<string, unknown> | null
  media_source_error_code: string | null
  media_source_verified_at: string | null
  last_sent_message_id: number | null
  failure_count: number
  updated_at: string | null
}

export interface CreateTaskPayload {
  account_id?: string | null
  chat_id?: number | null
  target_peer_id?: number | null
  target_peer_type?: string | null
  target_access_hash?: number | null
  target_peers?: Array<{ peer_id: number; peer_type: string; access_hash?: number | null }>
  title: string
  enabled: boolean
  trigger_mode?: string
  shortcut_slot?: number | null
  shortcut_label?: string | null
  priority?: number
  repeat_interval_min: number
  jitter_seconds?: number
  delay_min_seconds?: number
  delay_max_seconds?: number
  day_start_hour?: number | null
  day_end_hour?: number | null
  start_at?: number | null
  end_at?: number | null
  text?: string | null
  expected_revision?: number
  delete_previous?: boolean
  pin_message?: boolean
}

export interface TaskMediaCapture {
  capture_id: string
  state: string
  expires_at: string
  bot_deep_link: string
  error_code?: string | null
  completed_revision?: number | null
}

export interface TaskLogItem {
  id: number
  send_at: string | null
  result: string
  trigger_source: string
  error_code: string | null
  error_message: string | null
  message_id: number | null
}

export interface TaskTriggerSummary {
  task_id: string
  title: string
  account_id: string | null
  trigger_source: string
  status: string
  total_targets: number
  success_count: number
  failed_count: number
  error_summary: string | null
  executed_at: string
}

export const getTasks = (): Promise<ApiResponse<TaskItem[]>> => {
  return request.get('/tasks')
}

export const getTask = (taskId: string): Promise<ApiResponse<TaskDetail>> => {
  return request.get(`/tasks/${taskId}`)
}

export const createTask = (payload: CreateTaskPayload): Promise<ApiResponse<{ task_id: string; revision: number }>> => {
  return request.post('/tasks', payload)
}

export const updateTask = (taskId: string, payload: Partial<CreateTaskPayload>): Promise<ApiResponse<{ revision: number }>> => {
  return request.put(`/tasks/${taskId}`, payload)
}

export const createTaskMediaCapture = (
  taskId: string,
  expectedRevision: number
): Promise<ApiResponse<TaskMediaCapture>> => {
  return request.post(`/tasks/${taskId}/media-captures`, { expected_revision: expectedRevision })
}

export const getTaskMediaCapture = (
  taskId: string,
  captureId: string
): Promise<ApiResponse<TaskMediaCapture>> => {
  return request.get(`/tasks/${taskId}/media-captures/${captureId}`)
}

export const clearTaskMedia = (
  taskId: string,
  expectedRevision: number
): Promise<ApiResponse<{ revision: number }>> => {
  return request.delete(`/tasks/${taskId}/media`, { data: { expected_revision: expectedRevision } })
}

export const deleteTask = (taskId: string): Promise<ApiResponse<any>> => {
  return request.delete(`/tasks/${taskId}`)
}

export const getTaskLogs = (taskId: string, limit = 100): Promise<ApiResponse<TaskLogItem[]>> => {
  return request.get(`/tasks/${taskId}/logs`, { params: { limit } })
}

export const triggerTask = (taskId: string): Promise<ApiResponse<TaskTriggerSummary>> => {
  return request.post(`/tasks/${taskId}/trigger`)
}
