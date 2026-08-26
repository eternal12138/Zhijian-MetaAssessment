/**
 * 管理员 API —— 用户管理
 */
import apiClient from './client'
import { authApi } from './auth'

export interface AdminUser {
  id: string
  username: string
  name: string
  role: string
  avatar_text: string
  class_group: string | null
  managed_classes: string | null
  is_active: boolean
  must_change_password: boolean
  can_manage_users: boolean
}

export interface CreateUserRequest {
  username: string
  password?: string
  name: string
  role: string
  class_group?: string | null
  managed_classes?: string | null
}

export interface AdminDataTaskRecord {
  session_id: string
  task_title: string
  sequence_no: number
  status: string
  started_at: string | null
  completed_at: string | null
  audio_chunk_count: number
  transcript_count: number
}

export interface AdminDataRecord {
  run_id: string
  user_id: string
  username: string
  name: string
  class_group: string | null
  questionnaire_participant_name: string | null
  status: string
  current_stage: string
  started_at: string
  completed_at: string | null
  session_count: number
  audio_chunk_count: number
  audio_size_bytes: number
  transcript_count: number
  dialogue_count: number
  coded_segment_count: number
  questionnaire_response_count: number
  questionnaire_enabled: boolean
  tasks: AdminDataTaskRecord[]
}

export interface AdminDataRecordsPage {
  items: AdminDataRecord[]
  total: number
  page: number
  page_size: number
  total_pages: number
  category_counts: Record<'overview' | 'audio' | 'transcripts' | 'questionnaire', number>
}

export interface AdminDeleteDataResult {
  status: 'success'
  message: string
  deleted_records?: number
  deleted_files?: number
  failed_files?: number
}

export interface AdminDeletionImpact {
  session_count: number
  audio_chunk_count: number
  audio_file_count: number
  transcript_version_count: number
  transcript_segment_count: number
  extraction_job_count: number
  candidate_count: number
  candidate_revision_count: number
  coding_record_count: number
  questionnaire_response_count: number
}

export interface AdminBulkDeletionImpact {
  run_count: number
  totals: AdminDeletionImpact
  items: Record<string, AdminDeletionImpact>
}

export interface BatchCreateRequest {
  users: CreateUserRequest[]
}

export interface BatchCreateResult {
  status: 'success'
  message: string
  created: number
  skipped: number
  errors: string[]
}

export interface BulkActionResult {
  status: 'success'
  processed: number
  skipped: number
  errors: string[]
}

export interface ModelConfigHistory {
  id: string
  created_at: string
  created_by: string | null
  created_by_name: string | null
  summary: {
    action?: 'saved' | 'rollback'
    llm_model?: string
    asr_provider?: string
    asr_auth_mode?: string
    rollback_from?: string
  }
}

export interface ProtocolConfig {
  questionnaire_enabled: boolean
  behavior_weight: number
  questionnaire_weight: number
  updated_at: string | null
}

export interface NarrationAsset {
  id: string
  slot_key: string
  label: string
  source_text: string
  original_filename: string
  mime_type: string
  size_bytes: number
  sha256: string
  version: number
  is_active: boolean
  uploaded_by: string
  created_at: string
}

export interface NarrationSlot {
  slot_key: string
  label: string
  source_text: string
  category: 'instruction' | 'practice' | 'questionnaire' | 'task' | 'silence'
  asset: NarrationAsset | null
}

export type DiagnosticStatus =
  | 'ready'
  | 'warning'
  | 'error'
  | 'disabled'
  | 'unconfigured'
  | 'unknown'

export interface ServiceDiagnostic {
  status: DiagnosticStatus
  configured: boolean
  label: string
  provider: string
  endpoint: string | null
  model: string | null
  latency_ms: number | null
  message: string
}

export interface QuotaDiagnostic {
  status: 'console_required' | 'unavailable'
  exact_remaining_available: boolean
  remaining: number | null
  unit: string
  local_usage: number | null
  period: string | null
  console_url: string
  message: string
}

export interface ModelServicesDiagnostics {
  overall_status: 'ready' | 'degraded' | 'unavailable'
  checked_at: string
  llm: ServiceDiagnostic
  embedding: ServiceDiagnostic
  asr: ServiceDiagnostic
  audio_public_url: ServiceDiagnostic
  llm_quota: QuotaDiagnostic
  asr_quota: QuotaDiagnostic
}

export interface ModelServicesConfig {
  report_use_llm: boolean
  llm_base_url: string
  llm_model: string
  llm_api_key_configured: boolean
  llm_temperature: number
  llm_top_p: number
  llm_max_tokens: number
  report_llm_timeout_seconds: number
  qwen_embedding_base_url: string
  qwen_embedding_model: string
  qwen_embedding_api_key_configured: boolean
  qwen_embedding_dimensions: number
  qwen_embedding_batch_size: number
  qwen_embedding_timeout_seconds: number
  asr_provider: 'disabled' | 'volcengine'
  volcengine_asr_auth_mode: 'api_key' | 'legacy'
  volcengine_asr_api_key_configured: boolean
  volcengine_asr_app_id: string
  volcengine_asr_access_key_configured: boolean
  volcengine_asr_resource_id: string
  volcengine_asr_submit_url: string
  volcengine_asr_query_url: string
  asr_model: string
  asr_language: string
  asr_max_retries: number
  asr_config_version: string
  asr_poll_interval_seconds: number
  asr_public_base_url: string
  asr_audio_signing_secret_configured: boolean
  asr_timeout_seconds: number
  volcengine_asr_query_interval_seconds: number
  volcengine_asr_max_wait_seconds: number
  asr_audio_url_ttl_seconds: number
  storage: 'encrypted_database'
}

export interface ModelServicesConfigUpdate {
  report_use_llm: boolean
  llm_base_url: string
  llm_model: string
  llm_api_key?: string | null
  clear_llm_api_key?: boolean
  llm_temperature: number
  llm_top_p: number
  llm_max_tokens: number
  report_llm_timeout_seconds: number
  qwen_embedding_base_url: string
  qwen_embedding_model: string
  qwen_embedding_api_key?: string | null
  clear_qwen_embedding_api_key?: boolean
  qwen_embedding_dimensions: number
  qwen_embedding_batch_size: number
  qwen_embedding_timeout_seconds: number
  asr_provider: 'disabled' | 'volcengine'
  volcengine_asr_auth_mode: 'api_key' | 'legacy'
  volcengine_asr_api_key?: string | null
  clear_volcengine_asr_api_key?: boolean
  volcengine_asr_app_id: string
  volcengine_asr_access_key?: string | null
  clear_volcengine_asr_access_key?: boolean
  volcengine_asr_resource_id: string
  volcengine_asr_submit_url: string
  volcengine_asr_query_url: string
  asr_model: string
  asr_language: string
  asr_max_retries: number
  asr_config_version: string
  asr_poll_interval_seconds: number
  asr_public_base_url: string
  asr_audio_signing_secret?: string | null
  clear_asr_audio_signing_secret?: boolean
  asr_timeout_seconds: number
  volcengine_asr_query_interval_seconds: number
  volcengine_asr_max_wait_seconds: number
  asr_audio_url_ttl_seconds: number
}

export const adminApi = {
  /** 列出所有用户 */
  listUsers(params: {
    page?: number
    page_size?: number
    search?: string
    role?: string
    account_status?: string
    class_group?: string
    sort_by?: string
  } = {}) {
    return apiClient.get<AdminUser[]>('/admin/users', { params })
  },

  listUserClasses() {
    return apiClient.get<string[]>('/admin/users/classes')
  },

  /** 新增单个用户 */
  createUser(data: CreateUserRequest) {
    return apiClient.post('/admin/users', data)
  },

  /** 批量新增用户 */
  batchCreateUsers(data: BatchCreateRequest) {
    return apiClient.post<BatchCreateResult>('/admin/users/batch', data)
  },

  /** 为未分班学生或未设置负责班级的教师补充班级范围 */
  assignUserClass(userId: string, classGroup: string) {
    return apiClient.patch<AdminUser>(
      `/admin/users/${userId}/class-group`,
      { class_group: classGroup }
    )
  },

  /** 冻结/解冻用户 */
  toggleStatus(userId: string) {
    return apiClient.post('/admin/users/toggle-status', { user_id: userId })
  },

  /** 管理员重置用户密码 */
  resetPassword(userId: string, newPassword: string = '123456') {
    return apiClient.post('/admin/users/reset-password', {
      user_id: userId, new_password: newPassword
    })
  },

  /** 删除用户（仅超管） */
  deleteUser(userId: string) {
    return apiClient.delete(`/admin/users/${userId}`)
  },

  /** 获取用户特定任务的对话记录 */
  getUserDialogue(userId: string, taskId: string) {
    return apiClient.get<Array<{ id: string; role: string; content: string; timestamp: number }>>(
      `/admin/users/${userId}/dialogue?task_id=${encodeURIComponent(taskId)}`
    )
  },

  /** 按账号和测评时间列出可治理的研究数据。 */
  listDataRecords(params: {
    page: number
    page_size: number
    keyword?: string
    category: 'overview' | 'audio' | 'transcripts' | 'questionnaire'
  }) {
    return apiClient.get<AdminDataRecordsPage>('/admin/data-records', { params })
  },

  /** 删除前核对录音、转录、候选、编码和问卷依赖。 */
  getDataDeletionImpact(runId: string) {
    return apiClient.get<AdminDeletionImpact>(`/admin/data-records/${runId}/deletion-impact`)
  },

  /** 一次核对多条测评的全部关联数据。 */
  getBulkDataDeletionImpact(runIds: string[]) {
    return apiClient.post<AdminBulkDeletionImpact>('/admin/data-records/bulk-deletion-impact', {
      run_ids: runIds
    })
  },

  /** 删除整次测评及其录音、转录、问卷和衍生研究数据。 */
  deleteDataRun(runId: string) {
    return apiClient.delete<AdminDeleteDataResult>(`/admin/data-records/${runId}`)
  },

  /** 只删除录音文件和音频分片元数据。 */
  deleteDataAudio(runId: string) {
    return apiClient.delete<AdminDeleteDataResult>(`/admin/data-records/${runId}/audio`)
  },

  /** 只删除转录、旧式对话和衍生编码数据。 */
  deleteDataTranscripts(runId: string) {
    return apiClient.delete<AdminDeleteDataResult>(`/admin/data-records/${runId}/transcripts`)
  },

  /** 只删除问卷答案及被试填写的微信名。 */
  deleteDataQuestionnaire(runId: string) {
    return apiClient.delete<AdminDeleteDataResult>(`/admin/data-records/${runId}/questionnaire`)
  },

  bulkUserAction(data: {
    user_ids: string[]
    action: 'freeze' | 'unfreeze' | 'reset_password' | 'assign_class'
    class_group?: string
  }) {
    return apiClient.post<BulkActionResult>('/admin/users/bulk-action', data)
  },

  /** 读取只影响新测评的协议开关 */
  getProtocolConfig() {
    return apiClient.get<ProtocolConfig>('/admin/protocol-config')
  },

  /** 保存协议开关与多模态加权权重；进行中的测评继续使用创建时的快照 */
  updateProtocolConfig(data: {
    questionnaire_enabled: boolean
    behavior_weight?: number
    questionnaire_weight?: number
  }) {
    return apiClient.put<ProtocolConfig>('/admin/protocol-config', data)
  },

  /** 列出标准测评的真人朗读录音槽位 */
  listNarrationSlots() {
    return apiClient.get<NarrationSlot[]>('/admin/narration-assets')
  },

  /** 上传新录音并将其设为该槽位的当前版本 */
  uploadNarration(slotKey: string, file: File) {
    const form = new FormData()
    form.append('file', file)
    return apiClient.post<NarrationAsset>(
      `/admin/narration-assets/${encodeURIComponent(slotKey)}/upload`,
      form
    )
  },

  /** 停用当前录音；历史测评仍可读取原文件 */
  disableNarration(assetId: string) {
    return apiClient.delete(`/admin/narration-assets/${assetId}`)
  },

  /** 通过鉴权请求读取录音，供管理员试听 */
  getNarrationAudio(assetId: string) {
    return apiClient.get<Blob>(`/narrations/${assetId}/audio`, {
      responseType: 'blob'
    })
  },

  /** 运行火山方舟、豆包语音和公网音频链路的真实诊断 */
  diagnoseModelServices() {
    return apiClient.post<ModelServicesDiagnostics>(
      '/admin/model-services/diagnostics',
      {},
      { timeout: 60_000 }
    )
  },

  /** 读取脱敏后的模型服务配置 */
  getModelServicesConfig() {
    return apiClient.get<ModelServicesConfig>('/admin/model-services/config')
  },

  /** 加密保存并立即应用模型服务配置 */
  updateModelServicesConfig(data: ModelServicesConfigUpdate) {
    return apiClient.put<ModelServicesConfig>(
      '/admin/model-services/config',
      data
    )
  },

  listModelServicesConfigHistory() {
    return apiClient.get<ModelConfigHistory[]>('/admin/model-services/config/history')
  },

  rollbackModelServicesConfig(historyId: string) {
    return apiClient.post<ModelServicesConfig>(
      `/admin/model-services/config/history/${historyId}/rollback`
    )
  },

  /** 当前用户修改自己的密码 */
  changeOwnPassword(newPassword: string) {
    return apiClient.post<{ access_token: string }>('/auth/change-password', {
      new_password: newPassword
    })
  }
}
