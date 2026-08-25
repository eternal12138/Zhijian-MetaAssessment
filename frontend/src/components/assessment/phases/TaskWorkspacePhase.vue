<script setup lang="ts">
import type { ProtocolTask } from '../../../api/protocol'
import LiveRecordingWaveform from '../../audio/LiveRecordingWaveform.vue'
import AssessmentTools from '../AssessmentTools.vue'

defineProps<{
  taskIndex: number
  currentTask: ProtocolTask
  taskImage: { src: string; title: string; alt: string } | null
  taskUnitNote: string | null
  spokenPrompt: string
  spokenPromptKind: 'information' | 'silence'
  isRecording: boolean
  recordingDurationSeconds: number
  recordingDurationFormatted: string
  volumeLevel: number
  mediaStream: MediaStream | null
  waveformStatus: 'idle' | 'recording' | 'quiet' | 'warning'
  audioSignalPresentation: { tone: string; icon: string; text: string }
  recordingStatusClass: string
  recordingStatusIcon: string
  recordingStatusTitle: string
  recordingStatusDetail: string
  recordingNeedsAttention: boolean
  silenceRemainingSeconds: number
  taskTranscript: string
  interimTranscript: string
  isOnline: boolean
  failedTransferCount: number
  pendingTransferCount: number
  generatedAudioChunkCount: number
  uploadedAudioChunkCount: number
  savedTranscriptCount: number
  generatedTranscriptCount: number
  transferProgress: number
  transferRetrying: boolean
  taskRecordingCanStart: boolean
  taskCanSubmit: boolean
  isBusy: boolean
  isSpeaking: boolean
  questionnaireEnabled: boolean
}>()

const emit = defineEmits<{
  (e: 'start-recording'): void
  (e: 'retry-recording'): void
  (e: 'retry-transfers'): void
  (e: 'request-finish'): void
  (e: 'tool-event', event: {
    tool: 'calculator' | 'scratchpad'
    action: 'opened' | 'closed' | 'collapsed' | 'expanded' | 'calculated' | 'undo' | 'cleared'
  }): void
}>()
</script>

<template>
  <div class="row g-4 task-workspace-layout">
    <!-- 左侧任务详情与刺激材料工作区 -->
    <div class="col-lg-8">
      <div class="card border-0 shadow-sm h-100">
        <div class="card-body p-4">
          <div class="task-heading d-flex justify-content-between align-items-start gap-3">
            <div>
              <span class="badge bg-primary-subtle text-primary mb-2">任务 {{ taskIndex + 1 }} / 2</span>
              <h4>{{ currentTask.title }}</h4>
            </div>
            <div class="task-tools-area">
              <span class="text-muted small">建议 {{ currentTask.estimated_minutes }} 分钟</span>
            </div>
          </div>

          <div
            class="mobile-recording-bar"
            :class="recordingStatusClass"
            role="status"
            aria-live="polite"
          >
            <span v-if="isRecording" class="recording-live-dot" aria-hidden="true" />
            <i v-else class="bi" :class="recordingStatusIcon" aria-hidden="true" />
            <span class="mobile-recording-copy">
              <strong>{{ recordingStatusTitle }}</strong>
              <small>{{ recordingStatusDetail }}</small>
            </span>
            <button
              v-if="recordingNeedsAttention"
              class="btn btn-sm btn-outline-danger"
              type="button"
              @click="emit('retry-recording')"
            >
              重试
            </button>
          </div>

          <p class="scenario mt-3">{{ currentTask.scenario }}</p>
          <div v-if="taskUnitNote" class="task-unit-note mt-3" role="note">
            <i class="bi bi-info-circle-fill" aria-hidden="true"></i>
            <span>{{ taskUnitNote }}</span>
          </div>

          <div class="task-workspace mt-4">
            <figure v-if="taskImage" class="task-stimulus">
              <h5 class="task-stimulus-title">{{ taskImage.title }}</h5>
              <img :src="taskImage.src" :alt="taskImage.alt">
              <figcaption>
                <span class="d-block">{{ taskImage.alt }}。可点击图片放大查看。</span>
              </figcaption>
              <a :href="taskImage.src" target="_blank" rel="noopener noreferrer" class="stretched-link">
                <span class="visually-hidden">放大查看题目图片</span>
              </a>
            </figure>
            <AssessmentTools
              class="task-tool-dock"
              :task-key="currentTask.id"
              :task-title="currentTask.title"
              :task-scenario="currentTask.scenario"
              :task-image="taskImage"
              :task-unit-note="taskUnitNote"
              @event="emit('tool-event', $event)"
            />
          </div>
        </div>
      </div>
    </div>

    <!-- 右侧录音与状态控制面板 -->
    <div class="col-lg-4 task-recording-column">
      <div class="card border-0 shadow-sm">
        <div class="card-body p-4">
          <div
            v-if="spokenPrompt && spokenPromptKind === 'silence'"
            class="spoken-prompt silence-prompt mb-3"
            role="alert"
            aria-live="assertive"
          >
            <i class="bi bi-megaphone-fill" />
            <div>
              <strong>请继续说出想法</strong>
              <span>{{ spokenPrompt }}</span>
            </div>
          </div>
          <div class="d-flex justify-content-between">
            <span class="fw-semibold d-flex align-items-center gap-2">
              <span v-if="isRecording" class="recording-live-dot" aria-hidden="true" />
              出声思维录音（正式任务必需）
            </span>
            <span class="font-monospace">{{ recordingDurationFormatted }}</span>
          </div>
          <LiveRecordingWaveform
            class="my-3"
            :stream="mediaStream"
            :active="isRecording"
            :status="waveformStatus"
            :height="66"
          />
          <div
            v-if="isRecording"
            class="audio-signal-status"
            :class="audioSignalPresentation.tone"
          >
            <i class="bi me-1" :class="audioSignalPresentation.icon" />
            {{ audioSignalPresentation.text }}
          </div>
          <div
            class="mandatory-recording-status"
            :class="recordingStatusClass"
            role="status"
            aria-live="polite"
          >
            <i class="bi" :class="recordingStatusIcon" />
            <div class="flex-grow-1">
              <strong>{{ recordingStatusTitle }}</strong>
              <small>
                {{
                  isRecording
                    ? `请持续大声思考，距静默提醒约 ${silenceRemainingSeconds} 秒`
                    : '正式任务必须全程录音，被试不能主动暂停；提交时由系统自动结束。'
                }}
              </small>
            </div>
            <button
              v-if="recordingNeedsAttention"
              class="btn btn-sm btn-outline-danger"
              type="button"
              @click="emit('retry-recording')"
            >
              重试录音
            </button>
          </div>
          <div class="transcript-box mt-3">
            {{ taskTranscript || interimTranscript || '实时字幕将显示在这里。' }}
            <span v-if="interimTranscript" class="text-muted"> {{ interimTranscript }}</span>
          </div>
          <div
            class="transfer-status mt-3"
            :class="{ 'has-error': failedTransferCount > 0, 'is-offline': !isOnline }"
            role="status"
            aria-live="polite"
          >
            <div class="transfer-status-head">
              <span>
                <i class="bi me-1" :class="!isOnline ? 'bi-wifi-off' : failedTransferCount ? 'bi-cloud-slash' : pendingTransferCount ? 'bi-cloud-arrow-up' : 'bi-cloud-check'" />
                {{ !isOnline ? '网络已断开，数据已安全保存在此设备' : failedTransferCount ? '部分数据等待自动补传' : pendingTransferCount ? '正在同步实验数据' : generatedAudioChunkCount ? '实验数据已同步' : '等待录音数据' }}
              </span>
              <strong>{{ transferProgress }}%</strong>
            </div>
            <div class="transfer-progress" aria-hidden="true">
              <div :style="{ transform: `scaleX(${transferProgress / 100})` }" />
            </div>
            <small>
              音频 {{ uploadedAudioChunkCount }}/{{ generatedAudioChunkCount }}，字幕 {{ savedTranscriptCount }}/{{ generatedTranscriptCount }}
              <template v-if="pendingTransferCount">，{{ pendingTransferCount }} 项处理中</template>
            </small>
            <button
              v-if="failedTransferCount"
              class="btn btn-sm btn-outline-danger mt-2 w-100"
              type="button"
              :disabled="transferRetrying || !isOnline"
              @click="emit('retry-transfers')"
            >
              <span v-if="transferRetrying" class="spinner-border spinner-border-sm me-1" />
              {{ transferRetrying ? '正在重新同步' : `重试 ${failedTransferCount} 项失败数据` }}
            </button>
          </div>
        </div>
      </div>

      <div class="card border-0 shadow-sm task-action-card mt-3">
        <div class="card-body p-3">
          <p class="task-action-title mb-3">任务操作</p>
          <div class="task-primary-actions task-sidebar-actions">
            <button
              v-if="taskRecordingCanStart"
              class="btn btn-primary"
              type="button"
              :disabled="isBusy"
              @click="emit('start-recording')"
            >
              <i class="bi bi-mic-fill me-1" />
              {{ isSpeaking ? '结束朗读并开始录音' : '开始录音' }}
            </button>
            <button
              class="btn btn-success task-submit-button"
              :class="{ 'is-full-width': !taskRecordingCanStart }"
              :disabled="isBusy || isSpeaking || !taskCanSubmit || !isOnline"
              @click="emit('request-finish')"
            >
              {{
                isBusy
                  ? '正在保存并提交…'
                  : taskIndex === 0
                  ? '提交任务一并继续'
                  : questionnaireEnabled ? '提交任务二并进入问卷' : '提交任务二并确认'
              }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.scenario {
  border-left: 4px solid var(--color-primary);
  background: var(--color-surface-subtle);
  padding: 1rem;
  line-height: 1.8;
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}
.spoken-prompt {
  position: relative;
  isolation: isolate;
  display: flex;
  align-items: flex-start;
  gap: .75rem;
  border: 2px solid transparent;
  border-radius: var(--radius-md);
  padding: .85rem 1rem;
  box-shadow: var(--shadow-sm);
}
.spoken-prompt > i { flex: 0 0 auto; font-size: 1.2rem; margin-top: .05rem; }
.spoken-prompt strong, .spoken-prompt span { display: block; }
.spoken-prompt strong { margin-bottom: .15rem; font-size: .82rem; }
.spoken-prompt span { font-size: .9rem; line-height: 1.55; }
.silence-prompt {
  color: var(--color-warning);
  border-color: var(--color-warning);
  background: var(--color-warning-soft);
}
.silence-prompt::after {
  content: "";
  position: absolute;
  z-index: -1;
  inset: -2px;
  border: 2px solid rgba(255, 176, 32, .42);
  border-radius: inherit;
  pointer-events: none;
  animation: reminder-pulse 1.2s var(--ease-in-out) 2 alternate;
}
@keyframes reminder-pulse {
  from { opacity: .5; transform: scale(1); }
  to { opacity: 0; transform: scale(1.035); }
}
.task-tools-area {
  display: flex;
  min-width: 120px;
  align-items: flex-end;
  flex-direction: column;
  gap: .55rem;
}
.task-workspace {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: .85rem;
}
.task-tool-dock { min-width: 0; order: -1; }
.task-stimulus {
  position: relative;
  margin-bottom: 0;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}
.task-stimulus-title {
  margin: 0;
  padding: .8rem 1rem;
  border-bottom: 1px solid var(--color-border);
  color: var(--color-text);
  background: var(--color-surface-subtle);
  font-size: 1rem;
  font-weight: 700;
  text-align: center;
}
.task-stimulus img {
  display: block;
  width: 100%;
  height: auto;
  max-height: 620px;
  object-fit: contain;
}
.task-stimulus figcaption {
  padding: .65rem .85rem;
  color: var(--color-text-secondary);
  background: var(--color-surface-subtle);
  font-size: .76rem;
  text-align: center;
}
.task-unit-note {
  display: flex;
  align-items: flex-start;
  gap: .65rem;
  padding: .8rem 1rem;
  border: 1px solid var(--color-warning);
  border-left: 4px solid var(--color-warning);
  border-radius: .65rem;
  color: var(--color-warning);
  background: var(--color-warning-soft);
  font-size: .92rem;
  font-weight: 600;
  line-height: 1.6;
}
.task-unit-note .bi {
  flex: 0 0 auto;
  margin-top: .18rem;
  color: var(--color-warning);
}
.volume-track { height: 8px; border-radius: 8px; background: var(--color-border); overflow: hidden; }
.volume-track > div {
  width: 100%;
  height: 100%;
  background: var(--color-success);
  transform: scaleX(0);
  transform-origin: left center;
  transition: transform 120ms linear;
  will-change: transform;
}
.recording-live-dot {
  position: relative;
  width: 10px;
  height: 10px;
  flex: 0 0 10px;
  border-radius: 50%;
  background: var(--color-danger);
}
.recording-live-dot::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: rgba(220, 53, 69, .32);
  pointer-events: none;
  animation: recording-pulse 1.4s var(--ease-out) infinite;
}
@keyframes recording-pulse {
  from { opacity: .55; transform: scale(1); }
  70%, 100% { opacity: 0; transform: scale(2.6); }
}
@media (prefers-reduced-motion: reduce) {
  .silence-prompt::after,
  .recording-live-dot::after { animation: none; }
  .silence-prompt::after { opacity: .35; }
  .recording-live-dot::after { opacity: 0; }
}
.mandatory-recording-status {
  display: flex;
  align-items: flex-start;
  gap: .7rem;
  padding: .8rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface-subtle);
}
.mandatory-recording-status .btn { flex: 0 0 auto; white-space: nowrap; }
.mobile-recording-bar { display: none; }
.mobile-recording-copy { min-width: 0; flex: 1; }
.mobile-recording-copy strong,
.mobile-recording-copy small { display: block; }
.mobile-recording-copy strong { font-size: .84rem; }
.mobile-recording-copy small {
  margin-top: .12rem;
  overflow: hidden;
  color: currentColor;
  font-size: .72rem;
  line-height: 1.35;
  opacity: .78;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.task-submit-button:disabled {
  color: var(--color-text-muted);
  border-color: var(--color-border);
  background: var(--color-surface-subtle);
  opacity: 1;
}
.task-primary-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: .75rem;
  padding: 1rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  box-shadow: var(--shadow-xs);
}
.task-primary-actions .btn {
  min-height: 46px;
  font-weight: 650;
}
.task-primary-actions .is-full-width { grid-column: 1 / -1; }
.task-sidebar-actions {
  grid-template-columns: 1fr;
  padding: 0;
  border: 0;
  background: transparent;
  box-shadow: none;
}
.task-sidebar-actions .btn { width: 100%; }
.task-action-card { overflow: hidden; }
.task-action-title {
  color: var(--color-text);
  font-size: .82rem;
  font-weight: 700;
  letter-spacing: .02em;
}
.mandatory-recording-status > i { margin-top: .05rem; font-size: 1.05rem; }
.mandatory-recording-status strong,
.mandatory-recording-status small { display: block; }
.mandatory-recording-status strong { font-size: .84rem; }
.mandatory-recording-status small { margin-top: .15rem; line-height: 1.45; }
.recording-active { color: var(--color-success); border-color: var(--color-success); background: var(--color-success-soft); }
.recording-preparing { color: var(--color-warning); border-color: var(--color-warning); background: var(--color-warning-soft); }
.recording-error { color: var(--color-danger); border-color: var(--color-danger); background: var(--color-danger-soft); }
.audio-signal-status {
  margin: -.25rem 0 .85rem;
  padding: .5rem .65rem;
  border-radius: var(--radius-sm);
  font-size: .78rem;
  font-weight: 600;
}
.signal-ok { color: var(--color-success); background: var(--color-success-soft); }
.signal-waiting { color: var(--color-warning); background: var(--color-warning-soft); }
.signal-warning { color: var(--color-danger); background: var(--color-danger-soft); }
.transfer-status {
  padding: .7rem .75rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  color: var(--color-text-secondary);
  background: var(--color-surface-subtle);
}
.transfer-status.has-error,
.transfer-status.is-offline { color: var(--color-danger); border-color: var(--color-danger); background: var(--color-danger-soft); }
.transfer-status-head { display: flex; align-items: center; justify-content: space-between; gap: .75rem; font-size: .76rem; }
.transfer-status-head span { font-weight: 650; }
.transfer-status-head strong { font-size: .72rem; }
.transfer-progress { height: 5px; margin: .5rem 0; overflow: hidden; border-radius: 999px; background: var(--color-border); }
.transfer-progress > div {
  width: 100%;
  height: 100%;
  background: var(--color-primary);
  transform-origin: left center;
  transition: transform 180ms var(--ease-out);
}
.transfer-status.has-error .transfer-progress > div,
.transfer-status.is-offline .transfer-progress > div { background: var(--color-danger); }
.transfer-status small { display: block; font-size: .68rem; line-height: 1.4; }
.transcript-box {
  min-height: 120px;
  max-height: 230px;
  overflow-y: auto;
  line-height: 1.7;
  border: 1px solid var(--color-border);
  background: var(--color-surface-subtle);
  border-radius: var(--radius-md);
  padding: 1rem;
}
@media (min-width: 992px) {
  .task-recording-column { align-self: flex-start; }
  .task-recording-column > .card:first-child { position: sticky; top: 1rem; }
}
@media (max-width: 991.98px) {
  .task-workspace-layout { scroll-padding-top: 5.5rem; }
  .task-heading { flex-wrap: wrap; }
  .task-tools-area { width: 100%; min-width: 0; align-items: stretch; }
  .scenario { padding: .85rem; line-height: 1.7; }
  .task-stimulus img { max-height: none; }
  .mobile-recording-bar {
    position: sticky;
    top: .5rem;
    z-index: 12;
    display: flex;
    align-items: center;
    gap: .65rem;
    margin-top: 1rem;
    padding: .7rem .8rem;
    border: 1px solid;
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-sm);
  }
  .task-workspace,
  .task-stimulus { scroll-margin-top: 5.5rem; }
  .mobile-recording-bar > i { flex: 0 0 auto; }
  .mobile-recording-bar .btn { flex: 0 0 auto; min-height: 36px; }
}
@media (max-width: 575.98px) {
  .transcript-box { min-height: 105px; max-height: 190px; padding: 1rem; }
  .spoken-prompt { padding: .75rem .8rem; }
  .spoken-prompt span { font-size: .84rem; }
  .mandatory-recording-status { flex-wrap: wrap; }
  .mandatory-recording-status .btn { width: 100%; }
  .task-primary-actions { grid-template-columns: 1fr; padding: .75rem; }
  .task-primary-actions .btn { width: 100%; }
}
</style>
