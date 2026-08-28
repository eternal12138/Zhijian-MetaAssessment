import apiClient from './client'

export interface ReportEvidence {
  segmentId: string
  excerpt: string
  scaleItemId: string
  reason: string
  confidence: number
  needsReview: boolean
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
  published_at: string | null
  generated_at: string
}

export interface ReportBrief {
  id: string
  run_id: string | null
  session_id: string
  overall_score: number
  level: string
  is_provisional: boolean
  workflow_status: string
  generated_at: string
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
