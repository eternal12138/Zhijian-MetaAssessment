import apiClient from './client'

export type AsrJobStatus =
  | 'queued'
  | 'preparing_audio'
  | 'transcribing'
  | 'completed'
  | 'manually_transcribed'
  | 'retry_wait'
  | 'failed'
  | 'waiting_configuration'

export interface AsrJob {
  id: string
  session_id: string
  provider: string
  model: string
  config_version: string
  status: AsrJobStatus
  expected_chunk_count: number
  audio_duration_ms: number | null
  language: string
  retry_count: number
  max_retries: number
  error_code: string | null
  error_message: string | null
  created_at: string
  updated_at: string
  started_at: string | null
  finished_at: string | null
}

export interface TranscriptVersionSegment {
  id: string
  segment_no: number | null
  text: string
  started_at_ms: number
  ended_at_ms: number
  confidence: number | null
}

export interface TranscriptVersion {
  id: string
  session_id: string
  asr_job_id: string | null
  version_no: number
  source: 'server_asr' | 'human_corrected' | 'human_transcribed' | string
  status: string
  is_authoritative: boolean
  language: string
  provider: string | null
  model: string | null
  full_text: string
  created_by: string
  created_at: string
  approved_by: string | null
  approved_at: string | null
  segments: TranscriptVersionSegment[]
}

export interface AsrSessionStatus {
  job: AsrJob | null
  authoritative_version: TranscriptVersion | null
}

export interface AsrReviewQueueItem {
  session_id: string
  run_id: string | null
  task_id: string
  sequence_no: number
  user_id: string
  user_name: string
  class_group: string | null
  job: AsrJob
  authoritative_version_no: number | null
  authoritative_source: string | null
}

export interface AsrBatchRetryResult {
  processed: number
  skipped: number
  errors: string[]
}

export interface FailedAudioDeleteResult {
  status: string
  message: string
  deleted_files: number
  failed_files: number
}

export interface TranscriptCorrectionSegment {
  segment_no: number
  text: string
  started_at_ms: number
  ended_at_ms: number
  confidence: number | null
}

export const asrApi = {
  status(sessionId: string) {
    return apiClient.get<AsrSessionStatus>(`/sessions/${sessionId}/asr`)
  },

  retry(sessionId: string) {
    return apiClient.post<AsrSessionStatus>(`/sessions/${sessionId}/asr/retry`)
  },

  reviewQueue(params: {
    page?: number
    page_size?: number
    search?: string
    status_filter?: string
  } = {}) {
    return apiClient.get<AsrReviewQueueItem[]>('/sessions/asr/review-queue', { params })
  },

  batchRetry(sessionIds: string[]) {
    return apiClient.post<AsrBatchRetryResult>('/sessions/asr/batch-retry', {
      session_ids: sessionIds
    })
  },

  versions(sessionId: string) {
    return apiClient.get<TranscriptVersion[]>(
      `/sessions/${sessionId}/transcript-versions`
    )
  },

  approve(sessionId: string, versionId: string) {
    return apiClient.post<TranscriptVersion>(
      `/sessions/${sessionId}/transcript-versions/${versionId}/approve`
    )
  },

  correct(sessionId: string, segments: TranscriptCorrectionSegment[]) {
    return apiClient.post<TranscriptVersion>(
      `/sessions/${sessionId}/transcript-versions/corrections`,
      { segments }
    )
  },

  manualTranscript(sessionId: string, segments: TranscriptCorrectionSegment[]) {
    return apiClient.post<TranscriptVersion>(
      `/sessions/${sessionId}/transcript-versions/manual`,
      { segments }
    )
  },

  deleteFailedAudio(sessionId: string) {
    return apiClient.delete<FailedAudioDeleteResult>(
      `/sessions/${sessionId}/asr/failed-audio`
    )
  }
}
