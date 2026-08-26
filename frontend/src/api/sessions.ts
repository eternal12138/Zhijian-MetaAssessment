/**
 * 测评会话 API
 */
import apiClient from './client'

export interface AudioChunkUpload {
  blob: Blob
  chunkIndex: number
  startedAtMs: number
  endedAtMs: number
}

export interface TranscriptSegmentUpload {
  client_segment_id: string
  text: string
  started_at_ms: number
  ended_at_ms: number
  is_final: boolean
  source: 'browser'
}

export type InteractionEventType =
  | 'task_entered'
  | 'recording_started'
  | 'recording_paused'
  | 'recording_resumed'
  | 'recording_stopped'
  | 'speech_started'
  | 'speech_stopped'
  | 'transcript_final'
  | 'silence_threshold_reached'
  | 'neutral_prompt_started'
  | 'neutral_prompt_finished'
  | 'neutral_prompt_interrupted'
  | 'audio_chunk_uploaded'
  | 'session_submitted'
  | 'transfer_failed'
  | 'realtime_transcription_unavailable'
  | 'assessment_tool_used'
  | 'narration_started'
  | 'narration_finished'
  | 'narration_fallback'

export interface InteractionEventUpload {
  client_event_id: string
  sequence_no: number
  event_type: InteractionEventType
  occurred_at_ms: number
  client_timestamp_ms: number
  payload: Record<string, unknown>
}

export interface InteractionEventRecord extends InteractionEventUpload {
  id: string
  session_id: string
  source: string
  created_at: string
}

export interface SessionCompleteRequest {
  elapsed_seconds: number
  expected_audio_chunks: number
  expected_transcript_segments: number
}

export const sessionApi = {
  get(sessionId: string) {
    return apiClient.get<{
      id: string
      status: string
      audio_chunks: Array<{
        chunk_index: number
        started_at_ms: number
        ended_at_ms: number
      }>
      transcript_segments: Array<{
        id: string
        text: string
        is_final: boolean
        started_at_ms: number
        ended_at_ms: number
      }>
      interaction_events: InteractionEventRecord[]
    }>(`/sessions/${sessionId}`)
  },

  /** 上传一个录音分片；后端按 chunkIndex 幂等保存 */
  uploadAudioChunk(sessionId: string, chunk: AudioChunkUpload) {
    const form = new FormData()
    const extension = chunk.blob.type.includes('mp4') ? 'm4a'
      : chunk.blob.type.includes('ogg') ? 'ogg'
        : 'webm'
    form.append('file', chunk.blob, `chunk-${chunk.chunkIndex}.${extension}`)
    form.append('chunk_index', String(chunk.chunkIndex))
    form.append('started_at_ms', String(chunk.startedAtMs))
    form.append('ended_at_ms', String(chunk.endedAtMs))
    return apiClient.post(`/sessions/${sessionId}/audio-chunks`, form)
  },

  /** 保存一个或多个浏览器最终转录片段 */
  saveTranscripts(sessionId: string, segments: TranscriptSegmentUpload[]) {
    return apiClient.post(`/sessions/${sessionId}/transcripts`, { segments })
  },

  /** 幂等保存测评过程事件。 */
  saveEvents(sessionId: string, events: InteractionEventUpload[]) {
    return apiClient.post<InteractionEventRecord[]>(
      `/sessions/${sessionId}/events`,
      { events }
    )
  },

  /** 完成会话并触发生成报告 */
  complete(sessionId: string, data?: SessionCompleteRequest) {
    return apiClient.post(`/sessions/${sessionId}/complete`, data ?? {})
  }
}
