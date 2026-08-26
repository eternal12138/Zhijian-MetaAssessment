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

export const reportApi = {
  get(reportId: string) {
    return apiClient.get<ReportDetail>(`/reports/${reportId}`)
  },

  list() {
    return apiClient.get<ReportBrief[]>('/reports')
  }
}
