import apiClient from './client'

export interface ExtractionJob {
  id: string
  session_id: string
  transcript_version_id: string
  status: 'queued' | 'running' | 'retry_wait' | 'reviewing' | 'reviewed' | 'failed' | 'superseded'
  provider: string
  model: string
  extractor_version: string
  prompt_version: string
  generation_no: number
  supersedes_job_id: string | null
  retry_count: number
  max_retries: number
  error_code: string | null
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  review_lock_user_id: string | null
  review_lock_acquired_at: string | null
  review_lock_expires_at: string | null
}

export interface ExtractionCandidate {
  id: string
  extraction_job_id: string
  source_transcript_segment_id: string | null
  sequence_no: number
  source_type: 'llm' | 'human'
  review_status: 'pending' | 'accepted' | 'rejected'
  raw_asr_text: string
  original_text: string
  clean_text: string
  char_start: number | null
  char_end: number | null
  started_at_ms: number
  ended_at_ms: number
  reviewer_id: string | null
  review_note: string
  reviewed_at: string | null
  updated_at: string
  is_low_risk: boolean
  classifier_version: string | null
  predicted_label: number | null
  predicted_dimension: string | null
  prediction_confidence: number | null
  prediction_probabilities: Record<string, number> | null
  classified_at: string | null
  classification_error: string
  classification_status: 'pending_classification' | 'classified' | 'classified_with_fallback' | 'not_active'
  prediction_source: 'remote_embedding' | 'tfidf_production' | 'tfidf_fallback' | null
}

export interface ExtractionQueueItem {
  session_id: string
  run_id: string | null
  user_id: string
  user_name: string
  username: string
  class_group: string | null
  task_id: string
  task_title: string
  sequence_no: number
  completed_at: string | null
  completed_at_source: 'session_end' | 'run_completed' | 'session_start_fallback'
  transcript_version_no: number | null
  transcript_source: string | null
  asr_status: string
  asr_error_code: string | null
  asr_error_message: string | null
  audio_available: boolean
  job: ExtractionJob | null
  candidate_count: number
  pending_count: number
}

export interface ExtractionQueuePage {
  items: ExtractionQueueItem[]
  total: number
  page: number
  page_size: number
  total_pages: number
  class_groups: string[]
  tasks: Array<{ id: string; title: string }>
  statuses: string[]
}

export interface EvidenceSegment {
  id: string
  segment_no: number | null
  text: string
  started_at_ms: number
  ended_at_ms: number
}

export interface ExtractionReviewDetail {
  session_id: string
  run_id: string | null
  user_id: string
  user_name: string
  username: string
  task_id: string
  task_title: string
  sequence_no: number
  transcript_version_id: string | null
  transcript_version_no: number | null
  transcript_source: string | null
  full_text: string
  audio_available: boolean
  asr_status: string
  asr_error_code: string | null
  asr_error_message: string | null
  job: ExtractionJob | null
  job_history: ExtractionJob[]
  segments: EvidenceSegment[]
  candidates: ExtractionCandidate[]
  candidate_total: number
  candidate_page: number
  candidate_page_size: number
  candidate_total_pages: number
  pending_count: number
  accepted_count: number
  rejected_count: number
  locked_by_current_user: boolean
  lock_owner_name: string | null
  lock_expires_at: string | null
}

export interface ReviewLease {
  acquired: boolean
  locked_by_current_user: boolean
  lock_owner_name: string | null
  lock_expires_at: string | null
}

export interface CandidateRevision {
  id: string
  candidate_id: string
  extraction_job_id: string
  action: string
  actor_id: string | null
  actor_name: string | null
  before_snapshot: Record<string, unknown> | null
  after_snapshot: Record<string, unknown> | null
  created_at: string
}

export interface ReviewAudioTicket {
  url: string
  expires: number
}

export interface ReviewAudioWaveform {
  duration_seconds: number
  peaks: number[]
}

export interface ExtractionBatchRerunResult {
  requested: number
  created: number
  skipped: number
  failed: number
  items: Array<{
    session_id: string
    status: 'created' | 'skipped' | 'failed'
    message: string
    job: ExtractionJob | null
  }>
}

export interface ExtractionJobStatus {
  id: string
  session_id: string
  status: ExtractionJob['status']
  generation_no: number
  retry_count: number
  max_retries: number
  candidate_count: number
  error_code: string | null
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export const extractionApi = {
  listQueue(params: {
    page: number
    page_size: number
    keyword?: string
    class_group?: string
    task_id?: string
    status?: string
  }) {
    return apiClient.get<ExtractionQueuePage>('/research/extraction/queue', { params })
  },
  detail(sessionId: string, jobId?: string, candidatePage = 1, candidatePageSize = 10) {
    return apiClient.get<ExtractionReviewDetail>(`/research/extraction/sessions/${sessionId}`, {
      params: {
        job_id: jobId || undefined,
        candidate_page: candidatePage,
        candidate_page_size: candidatePageSize
      }
    })
  },
  enqueue(sessionId: string) {
    return apiClient.post<ExtractionJob>(`/research/extraction/sessions/${sessionId}/enqueue`)
  },
  rerun(sessionId: string) {
    return apiClient.post<ExtractionJob>(`/research/extraction/sessions/${sessionId}/rerun`)
  },
  batchRerun(sessionIds: string[]) {
    return apiClient.post<ExtractionBatchRerunResult>(
      '/research/extraction/sessions/batch-rerun',
      { session_ids: sessionIds },
      { timeout: 120_000 }
    )
  },
  jobStatus(jobId: string) {
    return apiClient.get<ExtractionJobStatus>(
      `/research/extraction/jobs/${jobId}/status`
    )
  },
  classifyJob(jobId: string) {
    return apiClient.post<ExtractionCandidate[]>(`/research/extraction/jobs/${jobId}/classify`)
  },
  jobStatuses(jobIds: string[]) {
    return apiClient.post<{ items: ExtractionJobStatus[] }>(
      '/research/extraction/jobs/status',
      { job_ids: jobIds }
    )
  },
  review(candidateId: string, data: {
    review_status: 'accepted' | 'rejected'
    original_text: string
    clean_text: string
    review_note: string
    expected_updated_at: string
  }) {
    return apiClient.patch<ExtractionCandidate>(`/research/extraction/candidates/${candidateId}`, data)
  },
  addCandidate(sessionId: string, data: {
    source_transcript_segment_id: string | null
    original_text: string
    clean_text: string
    started_at_ms: number
    ended_at_ms: number
    review_note: string
  }) {
    return apiClient.post<ExtractionCandidate>(`/research/extraction/sessions/${sessionId}/candidates`, data)
  },
  complete(sessionId: string) {
    return apiClient.post<ExtractionJob>(`/research/extraction/sessions/${sessionId}/complete`)
  },
  acquireLock(sessionId: string) {
    return apiClient.post<ReviewLease>(`/research/extraction/sessions/${sessionId}/lock`)
  },
  renewLock(sessionId: string) {
    return apiClient.post<ReviewLease>(`/research/extraction/sessions/${sessionId}/lock/renew`)
  },
  releaseLock(sessionId: string) {
    return apiClient.delete<ReviewLease>(`/research/extraction/sessions/${sessionId}/lock`)
  },
  bulkAcceptLowRisk(sessionId: string) {
    return apiClient.post<{ accepted: number; skipped: number; skipped_candidate_ids: string[] }>(
      `/research/extraction/sessions/${sessionId}/candidates/bulk-accept-low-risk`
    )
  },
  candidateHistory(candidateId: string) {
    return apiClient.get<CandidateRevision[]>(`/research/extraction/candidates/${candidateId}/history`)
  },
  audioTicket(sessionId: string) {
    return apiClient.post<ReviewAudioTicket>(
      `/research/extraction/sessions/${sessionId}/audio-ticket`
    )
  },
  audioWaveform(sessionId: string) {
    return apiClient.get<ReviewAudioWaveform>(
      `/research/extraction/sessions/${sessionId}/audio-waveform`,
      { timeout: 120_000 }
    )
  }
}
