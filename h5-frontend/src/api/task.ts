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
  title: string
  enabled: boolean
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
  delete_previous: boolean
  pin_message: boolean
  next_run_at: number | null
  created_at: string | null
}

export interface TaskDetail extends TaskItem {
  user_id: number
  target_access_hash: number | null
  media_file_id: string | null
  buttons: Array<Array<{ text: string; url: string }>> | null
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
  title: string
  enabled: boolean
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
  media_type?: string
  media_file_id?: string | null
  buttons?: Array<Array<{ text: string; url: string }>> | null
  delete_previous?: boolean
  pin_message?: boolean
}

export const getTasks = (): Promise<ApiResponse<TaskItem[]>> => {
  return request.get('/tasks')
}

export const getTask = (taskId: string): Promise<ApiResponse<TaskDetail>> => {
  return request.get(`/tasks/${taskId}`)
}

export const createTask = (payload: CreateTaskPayload): Promise<ApiResponse<{ task_id: string }>> => {
  return request.post('/tasks', payload)
}

export const updateTask = (taskId: string, payload: Partial<CreateTaskPayload>): Promise<ApiResponse<any>> => {
  return request.put(`/tasks/${taskId}`, payload)
}

export const deleteTask = (taskId: string): Promise<ApiResponse<any>> => {
  return request.delete(`/tasks/${taskId}`)
}
