import apiClient from './client'

export interface ReportEvidence {
  segmentId: string
  excerpt: string
  scaleItemId: string
  reason: string
  confidence?: number | null
  needsReview?: boolean
}

export interface ReportDimension {
  dimension: 'monitoring' | 'controlDebugging' | 'evaluation'
  label: string
  score: number
  percentile: number | null
  interpretation: string
  behavioral_score: number | null
  questionnaire_score: number | null
  evidence: ReportEvidence[]
}

export interface ReportRecommendation {
  id: string
  dimension: string
  title: string
  description: string
  practices: string[]
  difficulty: string
}

export interface MetacognitionPattern {
  title: string
  key: string
  label: string
  status: 'available' | 'provisional' | 'insufficient' | string
  description: string
  practice_focus: string
  rule_version: string
  comparison_basis: 'within_person' | string
  effective_dialogue_count: number
  is_provisional: boolean
  relative_high_dimensions: string[]
  relative_low_dimensions: string[]
  scores: Record<string, number | null>
  personal_mean: number | null
  span: number | null
  group_norm: {
    status: 'not_connected' | 'available' | string
    reference_id: string | null
    reference_label: string | null
    percentiles: Record<string, number> | null
  }
}

export interface ReportDetail {
  id: string
  user_id: string
  run_id: string | null
  session_id: string
  overall_score: number
  level: string
  summary: string
  dimension_details: ReportDimension[]
  strengths: string[]
  weaknesses: string[]
  recommendations: ReportRecommendation[]
  analysis_method: string
  rubric_version: string
  requires_review_count: number
  is_provisional: boolean
  workflow_status: string
  version_no: number
  template_version: string
  measurement_snapshot?: MetacognitionMeasurement | null
  metacognition_pattern?: MetacognitionPattern | null
  generation_metadata?: { status: string; model?: string; prompt_version?: string; data_version?: string; duration_seconds?: number } | null
  overall_score_available?: boolean
  evidence_is_provisional?: boolean | null
  published_at: string | null
  generated_at: string
}

export interface ReportBrief {
  id: string
  run_id: string | null
  session_id: string
  overall_score: number
  overall_score_available?: boolean
  level: string
  is_provisional: boolean
  workflow_status: string
  generated_at: string
}

export interface ReportReview {
  report: ReportDetail
  owner: { name: string; username: string; class_group: string | null }
  checks: Array<{ key: string; passed: boolean; message: string; route: string; overridable?: boolean }>
  can_publish: boolean
  risks: string[]
  measurement: MetacognitionMeasurement | null
  measurement_error: string
}

export interface MetacognitionMeasurement {
  id: string
  user_id: string
  run_id: string
  scope_type: 'run' | 'task' | string
  scope_key: string
  task_id: string | null
  task_name: string | null
  task_ids: string[]
  task_names: string[]
  effective_dialogue_count: number
  denominator_breakdown?: Record<string, number>
  fallback_dialogue_count?: number
  unclassified_count?: number
  evidence_status_counts?: Record<string, number>
  retained_previous_count?: number
  session_states?: Array<{
    session_id: string; task_id: string; status: string
    extraction_generation: number | null; latest_generation: number | null
    latest_extraction_status: string | null; using_previous_extraction: boolean
    model_versions: string[]
  }>
  dimension_counts: {
    monitoring: number
    control_debugging: number
    evaluation: number
  }
  dimension_scores: {
    monitoring: number | null
    control_debugging: number | null
    evaluation: number | null
  }
  score_available: boolean
  source: 'expert_consensus' | 'uploaded_review' | 'human_review' | 'none' | string
  data_version: string
  calculated_at: string
  completed_at: string
}

export interface MetacognitionMeasurementPage {
  items: MetacognitionMeasurement[]
  page: number
  page_size: number
  total: number
}

export const reportApi = {
  getCorrectionTemplate() {
    return apiClient.get<Blob>('/reports/measurement-corrections/template', { responseType: 'blob' })
  },

  uploadMeasurementCorrections(file: File) {
    const form = new FormData()
    form.append('file', file)
    form.append('confirmed', 'true')
    return apiClient.post<{ session_count: number; dialogue_count: number }>(
      '/reports/measurement-corrections', form
    )
  },

  get(reportId: string) {
    return apiClient.get<ReportDetail>(`/reports/${reportId}`)
  },

  getByRun(runId: string) {
    return apiClient.get<ReportDetail>(`/reports/runs/${runId}`)
  },

  review(reportId: string) {
    return apiClient.get<ReportReview>(`/research/reports/${reportId}/review`)
  },

  list() {
    return apiClient.get<ReportBrief[]>('/reports')
  },

  listMetacognitionMeasurements(page = 1, pageSize = 20) {
    return apiClient.get<MetacognitionMeasurementPage>('/reports/metacognition-measurements', {
      params: { page, page_size: pageSize }
    })
  },

  getMetacognitionMeasurement(runId: string, taskId?: string) {
    return apiClient.get<MetacognitionMeasurement>(`/reports/metacognition-measurements/${runId}`, {
      params: taskId ? { task_id: taskId } : undefined
    })
  }
}
