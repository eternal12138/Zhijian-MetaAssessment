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

export interface PendingCoding {
  id: string
  session_id: string
  transcript_segment_id: string | null
  segment: string
  dimension: string | null
  score: number | null
  confidence: number
  reason: string
  needs_review: boolean
  human_score: number | null
  review_note: string | null
  analysis_method: string
  rubric_version: string
}

export const reportApi = {
  get(reportId: string) {
    return apiClient.get<ReportDetail>(`/reports/${reportId}`)
  },

  getByRun(runId: string) {
    return apiClient.get<ReportDetail>(`/reports/runs/${runId}`)
  },

  generateRun(runId: string, reanalyze = false) {
    return apiClient.post<ReportDetail>(`/reports/runs/${runId}/generate`, { reanalyze })
  },

  list() {
    return apiClient.get<ReportBrief[]>('/reports')
  },

  listPendingCodings(page = 1, pageSize = 20) {
    return apiClient.get<PendingCoding[]>('/reports/review/pending', {
      params: { page, page_size: pageSize }
    })
  },

  reviewCoding(codingId: string, humanScore: number, reviewNote: string) {
    return apiClient.patch<PendingCoding>(`/reports/codings/${codingId}`, {
      human_score: humanScore,
      review_note: reviewNote
    })
  }
}
