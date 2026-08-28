import apiClient from './client'

export interface ProtocolTask {
  id: string
  title: string
  description: string
  scenario: string
  estimated_minutes: number
  protocol_order: number
  stimulus_data: {
    type?: 'scatter' | 'athletes'
    target?: { x: number; y: number }
    points?: Array<{ x: number; y: number }>
    athletes?: Array<Record<string, string | number>>
    columns?: Array<{ key: string; label: string }>
    question?: string
    stimulus_version?: string
    image_path?: string
    image_title?: string
    image_sha256?: string
  } | null
}

export interface ProtocolQuestionnaireItem {
  id: string
  dimension: string
  text: string
  scale_min: number
  scale_max: number
  display_order: number
}

export interface ProtocolNarrationAsset {
  id: string
  slot_key: string
  version: number
  original_filename: string
  mime_type: string
  size_bytes: number
  created_at: string
}

export interface AssessmentProtocol {
  version: string
  questionnaire_enabled: boolean
  questionnaire_source: string
  task_order_code: string
  order_source: 'default' | 'assignment' | 'active_run'
  tasks: ProtocolTask[]
  questionnaire_items: ProtocolQuestionnaireItem[]
  likert_labels: Record<string, string>
  narration_assets: ProtocolNarrationAsset[]
}

export interface RunSession {
  id: string
  task_id: string
  sequence_no: number
  status: string
}

export interface AssessmentRun {
  id: string
  user_id: string
  status: string
  current_stage: string
  protocol_version: string
  questionnaire_enabled: boolean
  questionnaire_source: string
  task_order_code: string
  order_assignment_id: string | null
  consented_at: string
  started_at: string
  completed_at: string | null
  sessions: RunSession[]
  questionnaire_answers: Array<{ item_id: string; value: number }>
  questionnaire_participant_name: string | null
}

export const protocolApi = {
  getProtocol() {
    return apiClient.get<AssessmentProtocol>('/assessment/protocol')
  },

  createRun(consent: boolean) {
    return apiClient.post<AssessmentRun>('/assessment/runs', { consent })
  },

  getCurrentRun() {
    return apiClient.get<AssessmentRun | null>('/assessment/runs/current')
  },

  advanceStage(runId: string, stage: string) {
    return apiClient.patch<AssessmentRun>(`/assessment/runs/${runId}/stage`, { stage })
  },

  submitQuestionnaire(
    runId: string,
    answers: Array<{ item_id: string; value: number }>,
    participantName: string
  ) {
    return apiClient.post<AssessmentRun>(
      `/assessment/runs/${runId}/questionnaire`,
      { answers, participant_name: participantName }
    )
  },

  completeRun(runId: string) {
    return apiClient.post<AssessmentRun>(`/assessment/runs/${runId}/complete`)
  },

  getNarrationAudio(assetId: string) {
    return apiClient.get<Blob>(`/narrations/${assetId}/audio`, {
      responseType: 'blob'
    })
  }
}
