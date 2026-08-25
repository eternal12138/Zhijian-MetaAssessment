<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { protocolApi, type AssessmentProtocol, type AssessmentRun, type ProtocolTask } from '../api/protocol'
import {
  sessionApi,
  type InteractionEventRecord,
  type InteractionEventType,
  type InteractionEventUpload
} from '../api/sessions'
import {
  useVoiceAssessment,
  type AudioChunkPayload,
  type TranscriptSegment
} from '../composables/useVoiceAssessment'
import { confirmAction } from '../composables/useUiFeedback'
import {
  audioChunkRecordId,
  checkOfflineStorage,
  clearAssessmentSnapshot,
  clearOfflineRunData,
  createSnapshot,
  getAssessmentSnapshot,
  getPendingAudioChunks,
  getPendingEvents,
  getPendingTranscripts,
  removeOfflineAudioChunk,
  removeOfflineEvent,
  removeOfflineTranscript,
  saveAssessmentSnapshot,
  saveOfflineAudioChunk,
  saveOfflineEvent,
  saveOfflineTranscript,
  type OfflineAssessmentSnapshot
} from '../utils/offlineAssessmentStorage'

// 子阶段组件导入
import ConsentPhase from '../components/assessment/phases/ConsentPhase.vue'
import DeviceCheckPhase from '../components/assessment/phases/DeviceCheckPhase.vue'
import InstructionsPhase from '../components/assessment/phases/InstructionsPhase.vue'
import PracticePhase from '../components/assessment/phases/PracticePhase.vue'
import TaskWorkspacePhase from '../components/assessment/phases/TaskWorkspacePhase.vue'
import QuestionnairePhase from '../components/assessment/phases/QuestionnairePhase.vue'
import ReviewPhase from '../components/assessment/phases/ReviewPhase.vue'
import CompletedPhase from '../components/assessment/phases/CompletedPhase.vue'
import TaskSubmitModal from '../components/assessment/phases/TaskSubmitModal.vue'
import AssessmentRecoveryModal from '../components/assessment/AssessmentRecoveryModal.vue'

type Phase =
  | 'loading'
  | 'consent'
  | 'device_check'
  | 'instructions'
  | 'practice'
  | 'task'
  | 'questionnaire'
  | 'review'
  | 'completed'
  | 'error'

const phase = ref<Phase>('loading')
const protocol = ref<AssessmentProtocol | null>(null)
const run = ref<AssessmentRun | null>(null)
const isBusy = ref(false)
const errorMessage = ref('')
const practiceAnswer = ref('')
const practiceCompleted = ref(false)
const questionnaireInstructionsAcknowledged = ref(false)
const taskIndex = ref(0)
const taskTranscript = ref('')
const questionnaireAnswers = ref<Record<string, number>>({})
const questionnaireParticipantName = ref('')
const uploadedAudioChunkCount = ref(0)
const savedTranscriptCount = ref(0)
const generatedAudioChunkCount = ref(0)
const generatedTranscriptCount = ref(0)
const pendingAudioUploads = ref(0)
const pendingTranscriptUploads = ref(0)
const failedTransferCount = ref(0)
const transferRetrying = ref(false)
const isOnline = ref(typeof navigator === 'undefined' ? true : navigator.onLine)
const offlineStorageWarning = ref('')
const offlinePendingItemCount = ref(0)
const recoverySnapshot = ref<OfflineAssessmentSnapshot | null>(null)
const recoveryOpen = ref(false)
const recoveryBusy = ref(false)
const submitConfirmationOpen = ref(false)
const nextAudioChunkIndex = ref(0)
const nextAudioTimelineMs = ref(0)
const asrReady = ref(false)
const spokenPrompt = ref('')
const spokenPromptKind = ref<'information' | 'silence'>('information')
const isSpeaking = ref(false)
const speechSynthesisAvailable = ref(
  typeof window !== 'undefined'
  && 'speechSynthesis' in window
  && typeof SpeechSynthesisUtterance !== 'undefined'
)
const narrationAssetMap = computed(() => new Map(
  (protocol.value?.narration_assets ?? []).map(asset => [asset.slot_key, asset])
))

let activeSessionId: string | null = null
let audioUploadQueue: Promise<void> = Promise.resolve()
let transcriptUploadQueue: Promise<void> = Promise.resolve()
let eventUploadQueue: Promise<void> = Promise.resolve()
let failedAudioChunks: AudioChunkPayload[] = []
let failedTranscriptSegments: TranscriptSegment[] = []
let failedInteractionEvents: InteractionEventUpload[] = []
let silenceReminderIndex = 0
let interactionEventSequence = 0
let eventTimelineStartedAt = Date.now()
let eventTimelineOffsetMs = 0
let spokenPromptTimer: ReturnType<typeof setTimeout> | null = null
let speechRequestId = 0
let activeNarrationAudio: HTMLAudioElement | null = null
let snapshotTimer: ReturnType<typeof setTimeout> | null = null
let restoringInitialState = true
let offlineReplayPromise: Promise<void> | null = null
const narrationObjectUrls = new Map<string, string>()
const offlineRecordIds = new Set<string>()

const INSTRUCTION_NARRATION = [
  '任务进行时，请专注于任务本身，把你脑海中正在发生的想法直接说出来。',
  '如果沉默超过十五秒，系统会提醒你继续说出想法。',
  '全程自动录音仅用于记录你的想法，结束后自动保存。',
  '出声思维操作规范。',
  '第一，任务进行时，请同步口述你看到的页面内容、脑中浮现的所有念头、计算推演步骤与每一次选择判断。',
  '第二，请直接说出脑海原生想法，使用日常口语自然表达，完整呈现当下实时思绪。',
  '第三，全程保持连贯口述思维内容。',
  '第四，若出现连续十五秒未出声的情况，系统将通过文字、语音双重提示，引导您继续分享思考。',
  '第五，任务启动同步开启录音，任务结束后系统自动停止并保存本次口述记录。'
].join('')

const PRACTICE_NARRATION = [
  '为了考察甲、乙两地小麦的长势，分别从中抽出 10 株苗，测得苗高如表 1 所示，单位厘米。',
  '表 1 为甲乙两地小麦苗高。',
  '试问哪个地的小麦长得比较整齐。',
  '请持续口头说出你脑海中实时产生的所有想法，包括你的思考过程与答案。'
].join('')

const QUESTIONNAIRE_NARRATION = [
  '下面共有24道量表题，最后还有一道姓名确认题。请回忆你刚刚完成两项问题解决任务时的真实体验与实际行为。',
  '请如实选择，问卷没有对错之分，请根据你的真实情况，按1（强烈不同意）到7（强烈同意）作答。完成量表后，请填写您的姓名或参加本次实验时使用的微信名等标识。'
].join('')

const SILENCE_REMINDERS = [
  '继续大声思考。',
  '你可以大声思考吗？',
  '请继续说。',
  '你现在在做什么？'
]

const stageLabels: Record<string, string> = {
  consent: '知情说明',
  device_check: '设备检查',
  instructions: '出声思维说明',
  practice: '练习',
  task_1: '任务一',
  task_2: '任务二',
  questionnaire: '任务后问卷',
  review: '提交确认',
  completed: '完成'
}

const currentTask = computed(() => protocol.value?.tasks[taskIndex.value] ?? null)
const questionnaireEnabled = computed(() =>
  run.value?.questionnaire_enabled ?? protocol.value?.questionnaire_enabled ?? false
)
const currentSession = computed(() => {
  const task = currentTask.value
  return run.value?.sessions.find(item => item.task_id === task?.id) ?? null
})
const submittedSessionIds = computed(() =>
  [...(run.value?.sessions ?? [])]
    .filter(item => item.status === 'completed')
    .sort((a, b) => a.sequence_no - b.sequence_no)
    .map(item => item.id)
)
const questionnaireComplete = computed(() => {
  const items = protocol.value?.questionnaire_items ?? []
  return items.length > 0
    && items.every(item => questionnaireAnswers.value[item.id] !== undefined)
    && Boolean(questionnaireParticipantName.value.trim())
})
const questionnaireTotalCount = computed(() => (protocol.value?.questionnaire_items.length ?? 0) + 1)
const answeredCount = computed(() => (
  Object.keys(questionnaireAnswers.value).length
  + (questionnaireParticipantName.value.trim() ? 1 : 0)
))
const pendingTransferCount = computed(() => Math.max(
  pendingAudioUploads.value + pendingTranscriptUploads.value,
  offlinePendingItemCount.value
))
const transferProgress = computed(() => {
  const generated = generatedAudioChunkCount.value + generatedTranscriptCount.value
  const saved = uploadedAudioChunkCount.value + savedTranscriptCount.value
  return generated === 0 ? 100 : Math.min(100, Math.round((saved / generated) * 100))
})
const progressPercent = computed(() => {
  const map: Record<Phase, number> = {
    loading: 0,
    consent: 5,
    device_check: 15,
    instructions: 25,
    practice: 35,
    task: taskIndex.value === 0 ? 50 : 68,
    questionnaire: 82,
    review: 95,
    completed: 100,
    error: 0
  }
  return map[phase.value]
})

const taskImage = computed(() => {
  const type = currentTask.value?.stimulus_data?.type
  const configuredPath = currentTask.value?.stimulus_data?.image_path
  const safeConfiguredPath = configuredPath?.startsWith('/assessment/')
    ? configuredPath
    : null
  if (type === 'scatter') {
    return {
      src: safeConfiguredPath ?? '/assessment/pitching-machines-zh.png',
      title: currentTask.value?.stimulus_data?.image_title ?? '四台投球机落点与距离分布图',
      alt: '四台投球机相对于红色目标点的多次投球结果图'
    }
  }
  if (type === 'athletes') {
    return {
      src: safeConfiguredPath ?? '/assessment/jump-performance-table-zh.png',
      title: currentTask.value?.stimulus_data?.image_title ?? '2000年跳高与跳远最佳成绩频数表',
      alt: '表2，2000年跳高和跳远最佳成绩及对应跳跃次数表'
    }
  }
  return null
})

const taskUnitNote = computed(() => (
  currentTask.value?.stimulus_data?.type === 'athletes'
    ? "注：表中成绩采用英尺（'）和英寸（''）表示，1 英尺 = 12 英寸（1' = 12''）"
    : null
))

function getError(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback
}

async function loadProtocol() {
  phase.value = 'loading'
  errorMessage.value = ''
  restoringInitialState = true
  try {
    const [protocolResponse, runResponse] = await Promise.all([
      protocolApi.getProtocol(),
      protocolApi.getCurrentRun()
    ])
    protocol.value = protocolResponse.data
    if (runResponse.data) {
      const snapshot = await getAssessmentSnapshot(
        runResponse.data.user_id,
        runResponse.data.id
      )
      const canRecover = Boolean(
        snapshot
        && snapshot.status === 'active'
        && runResponse.data.status !== 'completed'
      )
      recoverySnapshot.value = canRecover ? snapshot : null
      await restoreRun(runResponse.data, canRecover)
      await refreshOfflinePendingCount(runResponse.data)
      if (navigator.onLine) void replayArchivedOfflineTransfers(runResponse.data)
      if (canRecover) recoveryOpen.value = true
    } else {
      phase.value = 'consent'
    }
  } catch (error) {
    errorMessage.value = getError(error, '无法加载标准测评内容')
    phase.value = 'error'
  } finally {
    restoringInitialState = false
  }
}

async function restoreRun(savedRun: AssessmentRun, suppressNarration = false) {
  run.value = savedRun
  if (protocol.value) {
    const taskMap = new Map(protocol.value.tasks.map(task => [task.id, task]))
    const orderedTasks = [...savedRun.sessions]
      .sort((left, right) => left.sequence_no - right.sequence_no)
      .map(session => taskMap.get(session.task_id))
      .filter((task): task is ProtocolTask => Boolean(task))
    if (orderedTasks.length === protocol.value.tasks.length) {
      protocol.value.tasks = orderedTasks
      protocol.value.task_order_code = savedRun.task_order_code
      protocol.value.order_source = 'active_run'
    }
    protocol.value.questionnaire_enabled = savedRun.questionnaire_enabled
  }
  questionnaireAnswers.value = Object.fromEntries(
    savedRun.questionnaire_answers.map(answer => [answer.item_id, answer.value])
  )
  questionnaireParticipantName.value = savedRun.questionnaire_participant_name ?? ''
  const stage = savedRun.current_stage
  if (stage === 'device_check' || stage === 'instructions' || stage === 'practice') {
    phase.value = stage
    await nextTick()
    if (!suppressNarration && stage === 'instructions') speakInstructions()
    if (!suppressNarration && stage === 'practice') speakPracticeQuestion()
    return
  }
  if (stage === 'task_1' || stage === 'task_2') {
    const index = stage === 'task_1' ? 0 : 1
    const session = savedRun.sessions.find(item => item.sequence_no === index + 1)
    if (session?.status === 'completed') {
      await advanceServerStage(
        index === 0
          ? 'task_2'
          : savedRun.questionnaire_enabled ? 'questionnaire' : 'review'
      )
      await restoreRun(run.value!, suppressNarration)
      return
    }
    taskIndex.value = index
    activeSessionId = session?.id ?? null
    resetTaskTransferState()
    if (activeSessionId) {
      const response = await sessionApi.get(activeSessionId)
      const chunks = response.data.audio_chunks ?? []
      const transcripts = (response.data.transcript_segments ?? []).filter(item => item.is_final)
      const events = response.data.interaction_events ?? []
      nextAudioChunkIndex.value = chunks.length
        ? Math.max(...chunks.map(item => item.chunk_index)) + 1
        : 0
      nextAudioTimelineMs.value = Math.max(
        0,
        ...chunks.map(item => item.ended_at_ms),
        ...transcripts.map(item => item.ended_at_ms)
      )
      uploadedAudioChunkCount.value = chunks.length
      savedTranscriptCount.value = transcripts.length
      taskTranscript.value = transcripts.map(item => item.text).join(' ')
      restoreInteractionTimeline(events)
      await hydrateOfflineTransfers(savedRun, activeSessionId, new Set(
        chunks.map(item => item.chunk_index)
      ))
      if (events.length === 0) {
        recordInteractionEvent('task_entered', {
          task_index: index,
          restored: true
        })
      }
    }
    phase.value = 'task'
    await nextTick()
    if (!suppressNarration) speakTaskContent()
    return
  }
  if (stage === 'questionnaire' || stage === 'review' || stage === 'completed') {
    phase.value = stage
    if (stage === 'questionnaire') {
      questionnaireInstructionsAcknowledged.value = false
      await nextTick()
      if (!suppressNarration) speakQuestionnaireInstructions()
    }
    return
  }
  phase.value = 'consent'
}

async function beginAssessment() {
  isBusy.value = true
  errorMessage.value = ''
  try {
    const response = await protocolApi.createRun(true)
    const protocolResponse = await protocolApi.getProtocol()
    protocol.value = protocolResponse.data
    await restoreRun(response.data)
  } catch (error) {
    errorMessage.value = getError(error, '创建测评失败')
  } finally {
    isBusy.value = false
  }
}

async function advanceServerStage(stage: string) {
  if (!run.value) throw new Error('测评运行记录不存在')
  const response = await protocolApi.advanceStage(run.value.id, stage)
  run.value = response.data
}

async function checkMicrophone() {
  errorMessage.value = ''
  const passed = await voice.testMicrophone()
  if (voice.permission.value !== 'granted') {
    errorMessage.value = voice.errorMessage.value || '麦克风检查失败'
  } else if (!passed) {
    errorMessage.value = '没有检测到清晰声音。请靠近麦克风，用正常音量说话后重新测试。'
  }
}

async function enterInstructions() {
  isBusy.value = true
  try {
    await advanceServerStage('instructions')
    phase.value = 'instructions'
    await nextTick()
    speakInstructions()
  } catch (error) {
    errorMessage.value = getError(error, '无法进入说明阶段')
  } finally {
    isBusy.value = false
  }
}

async function enterPractice() {
  isBusy.value = true
  try {
    await advanceServerStage('practice')
    phase.value = 'practice'
    voice.clearTranscript()
    practiceAnswer.value = ''
    practiceCompleted.value = false
    await nextTick()
    speakPracticeQuestion()
  } catch (error) {
    errorMessage.value = getError(error, '无法进入练习阶段')
  } finally {
    isBusy.value = false
  }
}

async function togglePracticeRecording() {
  if (voice.isRecording.value) {
    await voice.stopRecording()
    practiceAnswer.value = voice.finalTranscript.value
    practiceCompleted.value = true
    return
  }
  interruptNarrationForRecording()
  voice.clearTranscript()
  practiceCompleted.value = false
  await voice.startRecording()
}

function resetTaskTransferState() {
  generatedAudioChunkCount.value = 0
  generatedTranscriptCount.value = 0
  uploadedAudioChunkCount.value = 0
  savedTranscriptCount.value = 0
  pendingAudioUploads.value = 0
  pendingTranscriptUploads.value = 0
  failedTransferCount.value = 0
  nextAudioChunkIndex.value = 0
  nextAudioTimelineMs.value = 0
  failedAudioChunks = []
  failedTranscriptSegments = []
  failedInteractionEvents = []
  audioUploadQueue = Promise.resolve()
  transcriptUploadQueue = Promise.resolve()
  eventUploadQueue = Promise.resolve()
  silenceReminderIndex = 0
  interactionEventSequence = 0
  eventTimelineOffsetMs = 0
  eventTimelineStartedAt = Date.now()
  taskTranscript.value = ''
  submitConfirmationOpen.value = false
  voice.clearTranscript()
}

function syncFailedTransferCount() {
  failedTransferCount.value = failedAudioChunks.length
    + failedTranscriptSegments.length
    + failedInteractionEvents.length
}

function transcriptRecordId(sessionId: string, segmentId: string) {
  if (!run.value) return ''
  return `${run.value.user_id}:${run.value.id}:${sessionId}:transcript:${segmentId}`
}

function eventRecordId(sessionId: string, eventId: string) {
  if (!run.value) return ''
  return `${run.value.user_id}:${run.value.id}:${sessionId}:event:${eventId}`
}

function markOfflineQueued(id: string) {
  if (!id || offlineRecordIds.has(id)) return
  offlineRecordIds.add(id)
  offlinePendingItemCount.value = offlineRecordIds.size
}

function markOfflineSynced(id: string) {
  if (!id) return
  offlineRecordIds.delete(id)
  offlinePendingItemCount.value = offlineRecordIds.size
}

async function refreshOfflinePendingCount(savedRun = run.value) {
  if (!savedRun) return
  const [audio, transcripts, events] = await Promise.all([
    getPendingAudioChunks(savedRun.user_id, savedRun.id),
    getPendingTranscripts(savedRun.user_id, savedRun.id),
    getPendingEvents(savedRun.user_id, savedRun.id)
  ])
  offlineRecordIds.clear()
  for (const record of [...audio, ...transcripts, ...events]) offlineRecordIds.add(record.id)
  offlinePendingItemCount.value = offlineRecordIds.size
}

async function hydrateOfflineTransfers(
  savedRun: AssessmentRun,
  sessionId: string,
  uploadedChunkIndexes: Set<number>
) {
  const [audioRecords, transcriptRecords, eventRecords] = await Promise.all([
    getPendingAudioChunks(savedRun.user_id, savedRun.id),
    getPendingTranscripts(savedRun.user_id, savedRun.id),
    getPendingEvents(savedRun.user_id, savedRun.id)
  ])
  for (const record of audioRecords.filter(item => item.sessionId === sessionId)) {
    if (uploadedChunkIndexes.has(record.chunkIndex)) {
      await removeOfflineAudioChunk(record.id)
      continue
    }
    if (!failedAudioChunks.some(item => item.chunkIndex === record.chunkIndex)) {
      failedAudioChunks.push({
        blob: record.blob,
        chunkIndex: record.chunkIndex,
        startedAtMs: record.startedAtMs,
        endedAtMs: record.endedAtMs,
        mimeType: record.mimeType
      })
    }
    markOfflineQueued(record.id)
    nextAudioChunkIndex.value = Math.max(nextAudioChunkIndex.value, record.chunkIndex + 1)
    nextAudioTimelineMs.value = Math.max(nextAudioTimelineMs.value, record.endedAtMs)
  }
  for (const record of transcriptRecords.filter(item => item.sessionId === sessionId)) {
    if (!failedTranscriptSegments.some(item => item.id === record.segmentId)) {
      failedTranscriptSegments.push({
        id: record.segmentId,
        text: record.text,
        createdAt: record.updatedAt,
        startedAtMs: record.startedAtMs,
        endedAtMs: record.endedAtMs
      })
    }
    markOfflineQueued(record.id)
    nextAudioTimelineMs.value = Math.max(nextAudioTimelineMs.value, record.endedAtMs)
  }
  for (const record of eventRecords.filter(item => item.sessionId === sessionId)) {
    const event = record.event as unknown as InteractionEventUpload
    if (!failedInteractionEvents.some(item => item.client_event_id === event.client_event_id)) {
      failedInteractionEvents.push(event)
    }
    markOfflineQueued(record.id)
  }
  generatedAudioChunkCount.value = uploadedAudioChunkCount.value + failedAudioChunks.length
  generatedTranscriptCount.value = savedTranscriptCount.value + failedTranscriptSegments.length
  syncFailedTransferCount()
  await refreshOfflinePendingCount(savedRun)
}

async function replayArchivedOfflineTransfers(savedRun = run.value) {
  if (!savedRun || !navigator.onLine) return
  if (offlineReplayPromise) return offlineReplayPromise
  offlineReplayPromise = (async () => {
    const [audioRecords, transcriptRecords, eventRecords] = await Promise.all([
      getPendingAudioChunks(savedRun.user_id, savedRun.id),
      getPendingTranscripts(savedRun.user_id, savedRun.id),
      getPendingEvents(savedRun.user_id, savedRun.id)
    ])
    for (const record of audioRecords.filter(item => item.sessionId !== activeSessionId)) {
      try {
        await sessionApi.uploadAudioChunk(record.sessionId, {
          blob: record.blob,
          chunkIndex: record.chunkIndex,
          startedAtMs: record.startedAtMs,
          endedAtMs: record.endedAtMs
        })
        await removeOfflineAudioChunk(record.id)
        markOfflineSynced(record.id)
      } catch { /* 保留在队列中，下一次联网继续补传。 */ }
    }
    for (const record of transcriptRecords.filter(item => item.sessionId !== activeSessionId)) {
      try {
        await sessionApi.saveTranscripts(record.sessionId, [{
          client_segment_id: record.segmentId,
          text: record.text,
          started_at_ms: record.startedAtMs,
          ended_at_ms: record.endedAtMs,
          is_final: true,
          source: 'browser'
        }])
        await removeOfflineTranscript(record.id)
        markOfflineSynced(record.id)
      } catch { /* 保留在队列中，下一次联网继续补传。 */ }
    }
    for (const record of eventRecords.filter(item => item.sessionId !== activeSessionId)) {
      try {
        await sessionApi.saveEvents(
          record.sessionId,
          [record.event as unknown as InteractionEventUpload]
        )
        await removeOfflineEvent(record.id)
        markOfflineSynced(record.id)
      } catch { /* 保留在队列中，下一次联网继续补传。 */ }
    }
    await refreshOfflinePendingCount(savedRun)
  })().finally(() => {
    offlineReplayPromise = null
  })
  return offlineReplayPromise
}

async function persistCurrentSnapshot() {
  if (
    restoringInitialState
    || !run.value
    || !protocol.value
    || ['loading', 'consent', 'completed', 'error'].includes(phase.value)
  ) return
  const persisted = await saveAssessmentSnapshot(createSnapshot({
    userId: run.value.user_id,
    runId: run.value.id,
    protocolId: protocol.value.version,
    currentPhase: phase.value,
    currentTaskIndex: taskIndex.value,
    practiceAnswer: practiceAnswer.value,
    practiceCompleted: practiceCompleted.value,
    questionnaireAnswers: { ...questionnaireAnswers.value },
    participantName: questionnaireParticipantName.value,
    activeSessionId,
    status: 'active'
  }))
  if (!persisted && !offlineStorageWarning.value) {
    offlineStorageWarning.value = '当前浏览器无法持久保存录音分片；文字草稿仍会尽力保留，请勿在断网时关闭页面。'
  }
}

function scheduleSnapshotSave() {
  if (restoringInitialState) return
  if (snapshotTimer) clearTimeout(snapshotTimer)
  snapshotTimer = setTimeout(() => {
    snapshotTimer = null
    void persistCurrentSnapshot()
  }, 300)
}

function resumeCurrentNarration() {
  if (phase.value === 'instructions') speakInstructions()
  else if (phase.value === 'practice') speakPracticeQuestion()
  else if (phase.value === 'task') speakTaskContent()
  else if (phase.value === 'questionnaire' && !questionnaireInstructionsAcknowledged.value) {
    speakQuestionnaireInstructions()
  }
}

async function restoreLocalSnapshot() {
  const snapshot = recoverySnapshot.value
  if (!snapshot) return
  recoveryBusy.value = true
  try {
    practiceAnswer.value = snapshot.practiceAnswer
    practiceCompleted.value = snapshot.practiceCompleted
    questionnaireAnswers.value = {
      ...questionnaireAnswers.value,
      ...snapshot.questionnaireAnswers
    }
    questionnaireParticipantName.value = snapshot.participantName
      || questionnaireParticipantName.value
    recoveryOpen.value = false
    await nextTick()
    resumeCurrentNarration()
    await persistCurrentSnapshot()
  } finally {
    recoveryBusy.value = false
  }
}

async function discardLocalSnapshot() {
  if (!run.value) return
  recoveryBusy.value = true
  try {
    await clearAssessmentSnapshot(run.value.user_id, run.value.id)
    recoverySnapshot.value = null
    recoveryOpen.value = false
    await nextTick()
    resumeCurrentNarration()
  } finally {
    recoveryBusy.value = false
  }
}

async function enterTask(index: number) {
  isBusy.value = true
  errorMessage.value = ''
  try {
    if (voice.isRecording.value) await voice.stopRecording()
    taskIndex.value = index
    await advanceServerStage(index === 0 ? 'task_1' : 'task_2')
    activeSessionId = currentSession.value?.id ?? null
    if (!activeSessionId) throw new Error('任务会话创建失败')
    resetTaskTransferState()
    phase.value = 'task'
    recordInteractionEvent('task_entered', {
      task_index: index,
      task_id: currentTask.value?.id ?? ''
    })
    await nextTick()
    speakTaskContent()
  } catch (error) {
    activeSessionId = null
    errorMessage.value = getError(error, '无法进入任务')
  } finally {
    isBusy.value = false
  }
}

function restoreInteractionTimeline(events: InteractionEventRecord[]) {
  interactionEventSequence = events.length
    ? Math.max(...events.map(item => item.sequence_no)) + 1
    : 0
  eventTimelineOffsetMs = events.length
    ? Math.max(...events.map(item => item.occurred_at_ms))
    : 0
  eventTimelineStartedAt = Date.now()
}

function recordInteractionEvent(
  eventType: InteractionEventType,
  payload: Record<string, unknown> = {}
) {
  if (!activeSessionId) return
  const sessionId = activeSessionId
  const sequence = interactionEventSequence
  interactionEventSequence += 1
  const now = Date.now()
  const event: InteractionEventUpload = {
    client_event_id: `event-${now}-${sequence}-${Math.random().toString(36).slice(2, 10)}`,
    sequence_no: sequence,
    event_type: eventType,
    occurred_at_ms: Math.min(
      24 * 60 * 60 * 1_000,
      eventTimelineOffsetMs + Math.max(0, now - eventTimelineStartedAt)
    ),
    client_timestamp_ms: now,
    payload
  }
  const offlineId = eventRecordId(sessionId, event.client_event_id)
  const persistence = run.value
    ? saveOfflineEvent({
        id: offlineId,
        userId: run.value.user_id,
        runId: run.value.id,
        sessionId,
        eventId: event.client_event_id,
        event: event as unknown as Record<string, unknown>,
        uploadStatus: 'pending',
        retryCount: 0,
        lastError: '',
        updatedAt: now
      }).then(persisted => {
        markOfflineQueued(offlineId)
        if (!persisted && !offlineStorageWarning.value) {
          offlineStorageWarning.value = '离线存储不可用；请保持页面打开，待网络恢复后系统会继续同步。'
        }
      })
    : Promise.resolve()
  eventUploadQueue = eventUploadQueue
    .then(async () => {
      await persistence
      if (!navigator.onLine) throw new Error('网络已断开')
      await sessionApi.saveEvents(sessionId, [event])
      await removeOfflineEvent(offlineId)
      markOfflineSynced(offlineId)
    })
    .catch(() => {
      failedInteractionEvents.push(event)
      syncFailedTransferCount()
    })
}

function recordToolEvent(event: {
  tool: 'calculator' | 'scratchpad'
  action: 'opened' | 'closed' | 'collapsed' | 'expanded' | 'calculated' | 'undo' | 'cleared'
}) {
  recordInteractionEvent('assessment_tool_used', {
    tool: event.tool,
    action: event.action,
    task_id: currentTask.value?.id ?? '',
    task_index: taskIndex.value
  })
}

function enqueueAudioChunk(chunk: AudioChunkPayload) {
  if (!activeSessionId) return
  const sessionId = activeSessionId
  generatedAudioChunkCount.value += 1
  pendingAudioUploads.value += 1
  nextAudioChunkIndex.value = Math.max(
    nextAudioChunkIndex.value,
    chunk.chunkIndex + 1
  )
  nextAudioTimelineMs.value = Math.max(
    nextAudioTimelineMs.value,
    chunk.endedAtMs
  )
  const offlineId = run.value
    ? audioChunkRecordId(run.value.user_id, run.value.id, sessionId, chunk.chunkIndex)
    : ''
  const persistence = run.value
    ? saveOfflineAudioChunk({
        id: offlineId,
        userId: run.value.user_id,
        runId: run.value.id,
        sessionId,
        chunkIndex: chunk.chunkIndex,
        blob: chunk.blob,
        mimeType: chunk.mimeType,
        startedAtMs: chunk.startedAtMs,
        endedAtMs: chunk.endedAtMs,
        uploadStatus: 'pending',
        retryCount: 0,
        lastError: '',
        updatedAt: Date.now()
      }).then(persisted => {
        markOfflineQueued(offlineId)
        if (!persisted && !offlineStorageWarning.value) {
          offlineStorageWarning.value = '录音分片只能暂存在当前页面内存中；请勿关闭页面。'
        }
      })
    : Promise.resolve()
  audioUploadQueue = audioUploadQueue
    .then(async () => {
      await persistence
      if (!navigator.onLine) throw new Error('网络已断开')
      await sessionApi.uploadAudioChunk(sessionId, chunk)
      uploadedAudioChunkCount.value += 1
      await removeOfflineAudioChunk(offlineId)
      markOfflineSynced(offlineId)
      recordInteractionEvent('audio_chunk_uploaded', {
        chunk_index: chunk.chunkIndex,
        size_bytes: chunk.blob.size,
        mime_type: chunk.mimeType,
        started_at_ms: chunk.startedAtMs,
        ended_at_ms: chunk.endedAtMs
      })
    })
    .catch(error => {
      failedAudioChunks.push(chunk)
      syncFailedTransferCount()
      errorMessage.value = getError(error, '音频分片上传失败')
      recordInteractionEvent('transfer_failed', {
        channel: 'audio',
        chunk_index: chunk.chunkIndex
      })
    })
    .finally(() => {
      pendingAudioUploads.value = Math.max(0, pendingAudioUploads.value - 1)
    })
}

function enqueueTranscript(segment: TranscriptSegment) {
  if (!activeSessionId) return
  const sessionId = activeSessionId
  generatedTranscriptCount.value += 1
  pendingTranscriptUploads.value += 1
  taskTranscript.value = [taskTranscript.value, segment.text].filter(Boolean).join(' ')
  recordInteractionEvent('transcript_final', {
    client_segment_id: segment.id,
    char_count: segment.text.length,
    started_at_ms: segment.startedAtMs,
    ended_at_ms: segment.endedAtMs
  })
  const offlineId = transcriptRecordId(sessionId, segment.id)
  const persistence = run.value
    ? saveOfflineTranscript({
        id: offlineId,
        userId: run.value.user_id,
        runId: run.value.id,
        sessionId,
        segmentId: segment.id,
        text: segment.text,
        startedAtMs: segment.startedAtMs,
        endedAtMs: segment.endedAtMs,
        uploadStatus: 'pending',
        retryCount: 0,
        lastError: '',
        updatedAt: Date.now()
      }).then(persisted => {
        markOfflineQueued(offlineId)
        if (!persisted && !offlineStorageWarning.value) {
          offlineStorageWarning.value = '实时字幕草稿只能暂存在当前页面内存中；请勿关闭页面。'
        }
      })
    : Promise.resolve()
  transcriptUploadQueue = transcriptUploadQueue
    .then(async () => {
      await persistence
      if (!navigator.onLine) throw new Error('网络已断开')
      await sessionApi.saveTranscripts(sessionId, [{
        client_segment_id: segment.id,
        text: segment.text,
        started_at_ms: segment.startedAtMs,
        ended_at_ms: segment.endedAtMs,
        is_final: true,
        source: 'browser'
      }])
      savedTranscriptCount.value += 1
      await removeOfflineTranscript(offlineId)
      markOfflineSynced(offlineId)
    })
    .catch(error => {
      failedTranscriptSegments.push(segment)
      syncFailedTransferCount()
      errorMessage.value = getError(error, '转录片段保存失败')
      recordInteractionEvent('transfer_failed', {
        channel: 'transcript',
        client_segment_id: segment.id
      })
    })
    .finally(() => {
      pendingTranscriptUploads.value = Math.max(0, pendingTranscriptUploads.value - 1)
    })
}

function clearSpokenPrompt(delayMs = 0) {
  if (spokenPromptTimer) clearTimeout(spokenPromptTimer)
  spokenPromptTimer = setTimeout(() => {
    spokenPrompt.value = ''
    spokenPromptTimer = null
  }, delayMs)
}

function stopCurrentNarration() {
  if (activeNarrationAudio) {
    activeNarrationAudio.pause()
    activeNarrationAudio.src = ''
    activeNarrationAudio = null
  }
  if (speechSynthesisAvailable.value) window.speechSynthesis.cancel()
}

function interruptNarrationForRecording() {
  if (!isSpeaking.value) return
  const task = phase.value === 'task' ? currentTask.value : null
  const slotKey = task ? `task:${task.id}` : null
  const asset = slotKey ? narrationAssetMap.value.get(slotKey) : undefined
  const source = activeNarrationAudio ? 'recording' : speechSynthesisAvailable.value ? 'browser' : 'none'
  speechRequestId += 1
  stopCurrentNarration()
  isSpeaking.value = false
  if (spokenPromptTimer) {
    clearTimeout(spokenPromptTimer)
    spokenPromptTimer = null
  }
  spokenPrompt.value = ''
  if (slotKey) {
    recordInteractionEvent('narration_finished', {
      slot_key: slotKey,
      source,
      completed: false,
      interrupted_by: 'participant_started_recording',
      asset_id: asset?.id ?? null,
      asset_version: asset?.version ?? null
    })
  }
}

async function narrationObjectUrl(assetId: string) {
  const cached = narrationObjectUrls.get(assetId)
  if (cached) return cached
  const response = await protocolApi.getNarrationAudio(assetId)
  const url = URL.createObjectURL(response.data)
  narrationObjectUrls.set(assetId, url)
  return url
}

async function playNarration(
  slotKey: string,
  text: string,
  kind: 'information' | 'silence',
  onSettled?: (completed: boolean) => void
) {
  if (spokenPromptTimer) {
    clearTimeout(spokenPromptTimer)
    spokenPromptTimer = null
  }
  spokenPrompt.value = text
  spokenPromptKind.value = kind
  const requestId = ++speechRequestId
  stopCurrentNarration()
  const asset = narrationAssetMap.value.get(slotKey)
  let settled = false
  let fallbackStarted = false
  const settle = (completed: boolean, source: 'recording' | 'browser' | 'none') => {
    if (settled || requestId !== speechRequestId) return
    settled = true
    isSpeaking.value = false
    activeNarrationAudio = null
    recordInteractionEvent('narration_finished', {
      slot_key: slotKey,
      source,
      completed,
      asset_id: asset?.id ?? null,
      asset_version: asset?.version ?? null
    })
    onSettled?.(completed)
    clearSpokenPrompt(kind === 'silence' ? 6_000 : 1_200)
  }

  const startBrowserFallback = () => {
    if (fallbackStarted || settled || requestId !== speechRequestId) return
    fallbackStarted = true
    if (activeNarrationAudio) {
      activeNarrationAudio.pause()
      activeNarrationAudio.src = ''
      activeNarrationAudio = null
    }
    recordInteractionEvent('narration_fallback', {
      slot_key: slotKey,
      asset_id: asset?.id ?? null,
      reason: asset ? 'recording_unavailable' : 'recording_not_configured'
    })
    if (!speechSynthesisAvailable.value) {
      settle(false, 'none')
      return
    }
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.lang = 'zh-CN'
    utterance.rate = 0.95
    utterance.pitch = 1
    const chineseVoice = window.speechSynthesis
      .getVoices()
      .find(voice => voice.lang.toLowerCase().startsWith('zh'))
    if (chineseVoice) utterance.voice = chineseVoice
    utterance.onend = () => settle(true, 'browser')
    utterance.onerror = () => settle(false, 'browser')
    window.speechSynthesis.speak(utterance)
  }

  isSpeaking.value = true
  recordInteractionEvent('narration_started', {
    slot_key: slotKey,
    source: asset ? 'recording' : 'browser',
    asset_id: asset?.id ?? null,
    asset_version: asset?.version ?? null
  })
  if (!asset) {
    startBrowserFallback()
    return
  }
  try {
    const url = await narrationObjectUrl(asset.id)
    if (requestId !== speechRequestId || settled) return
    const audio = new Audio(url)
    activeNarrationAudio = audio
    audio.onended = () => settle(true, 'recording')
    audio.onerror = startBrowserFallback
    await audio.play()
  } catch {
    startBrowserFallback()
  }
}

function speakInstructions() {
  void playNarration('instructions', INSTRUCTION_NARRATION, 'information')
}

function speakPracticeQuestion() {
  void playNarration('practice', PRACTICE_NARRATION, 'information')
}

function speakQuestionnaireInstructions() {
  void playNarration('questionnaire', QUESTIONNAIRE_NARRATION, 'information')
}

function acknowledgeQuestionnaireInstructions() {
  if (isSpeaking.value) {
    speechRequestId += 1
    stopCurrentNarration()
    isSpeaking.value = false
    if (spokenPromptTimer) {
      clearTimeout(spokenPromptTimer)
      spokenPromptTimer = null
    }
    spokenPrompt.value = ''
  }
  questionnaireInstructionsAcknowledged.value = true
}

function speakTaskContent() {
  const task = currentTask.value
  if (!task) return
  const text = `现在开始正式任务。题目：${task.title}。${task.scenario}`
  void playNarration(`task:${task.id}`, text, 'information', () => {
    if (phase.value !== 'task' || !activeSessionId) return
    if (!voice.isRecording.value && voice.recordingStatus.value !== 'starting') {
      void startMandatoryTaskRecording('task_started')
    }
  })
}

function speakNeutralReminder() {
  if (phase.value !== 'task' || !voice.isRecording.value) return
  const promptIndex = silenceReminderIndex % SILENCE_REMINDERS.length
  const text = SILENCE_REMINDERS[promptIndex]
  silenceReminderIndex += 1
  recordInteractionEvent('silence_threshold_reached', {
    threshold_seconds: 15,
    prompt_index: promptIndex
  })
  voice.pauseRecording()
  recordInteractionEvent('recording_paused', { reason: 'neutral_prompt' })
  recordInteractionEvent('neutral_prompt_started', { prompt_index: promptIndex })
  void playNarration(`silence:${promptIndex}`, text, 'silence', completed => {
    recordInteractionEvent(
      completed ? 'neutral_prompt_finished' : 'neutral_prompt_interrupted',
      { prompt_index: promptIndex }
    )
    if (phase.value === 'task') {
      voice.resumeRecording()
      recordInteractionEvent('recording_resumed', { reason: 'neutral_prompt' })
    }
  })
}

const voice = useVoiceAssessment({
  silenceThresholdMs: 15_000,
  audioChunkTimesliceMs: 5_000,
  onAudioChunk: enqueueAudioChunk,
  onFinalTranscript: enqueueTranscript,
  onSilence: speakNeutralReminder,
  onSpeechStart: payload => recordInteractionEvent('speech_started', {
    recording_at_ms: payload.occurredAtMs
  }),
  onSpeechEnd: payload => recordInteractionEvent('speech_stopped', {
    recording_at_ms: payload.occurredAtMs
  }),
  onRecognitionUnavailable: reason => recordInteractionEvent(
    'realtime_transcription_unavailable',
    { reason }
  )
})

const waveformStatus = computed<'idle' | 'recording' | 'quiet' | 'warning'>(() => {
  if (!voice.isRecording.value) return 'idle'
  if (voice.silentForMs.value >= 10_000) return 'warning'
  if (voice.silentForMs.value >= 3_000 || voice.volumeLevel.value < .05) return 'quiet'
  return 'recording'
})

const recordingNeedsAttention = computed(() => (
  !isSpeaking.value
  && !voice.isRecording.value
  && voice.recordingStatus.value !== 'paused'
  && !(voice.recordingStatus.value === 'stopped' && generatedAudioChunkCount.value > 0)
))

const taskRecordingCanStart = computed(() => (
  phase.value === 'task'
  && Boolean(activeSessionId)
  && !voice.isRecording.value
  && voice.recordingStatus.value !== 'paused'
  && generatedAudioChunkCount.value === 0
))

const recordingStatusClass = computed(() => {
  if (voice.isRecording.value) return 'recording-active'
  if (voice.recordingStatus.value === 'error') return 'recording-error'
  return 'recording-preparing'
})

const recordingStatusIcon = computed(() => {
  if (voice.isRecording.value) return 'bi-record-circle-fill'
  if (voice.recordingStatus.value === 'error') return 'bi-exclamation-triangle-fill'
  return 'bi-hourglass-split'
})

const recordingStatusTitle = computed(() => {
  if (voice.isRecording.value) return '正在录音 · 无需操作'
  if (isSpeaking.value) return '正在朗读，可立即开始录音'
  if (voice.recordingStatus.value === 'paused') return '系统提示播放中，录音将自动继续'
  if (voice.recordingStatus.value === 'stopped' && generatedAudioChunkCount.value > 0) return '录音已结束，等待重新提交'
  if (voice.recordingStatus.value === 'error') return '录音异常，任务暂不能提交'
  return '录音尚未启动，任务暂不能提交'
})

const recordingStatusDetail = computed(() => {
  if (voice.isRecording.value) {
    const signal = voice.hasDetectedAudio.value ? '已检测到声音' : '等待检测声音'
    return `${formatSeconds(voice.recordingDurationSeconds.value)} · ${signal} · 静默提醒约 ${voice.silenceRemainingSeconds.value} 秒`
  }
  if (voice.recordingStatus.value === 'stopped' && generatedAudioChunkCount.value > 0) {
    return failedTransferCount.value > 0
      ? '录音数据仍在本页中，请重试同步后再次提交。'
      : '录音数据已保留，可以再次提交，无需重新作答。'
  }
  return voice.errorMessage.value || '正式任务必须全程录音，请允许麦克风访问后重试。'
})

const taskCanSubmit = computed(() => (
  voice.isRecording.value
  || (voice.recordingStatus.value === 'stopped' && generatedAudioChunkCount.value > 0)
))

const audioSignalPresentation = computed(() => {
  if (!voice.isRecording.value) return { tone: 'signal-waiting', icon: 'bi-mic-mute', text: '录音尚未开始' }
  if (!voice.hasDetectedAudio.value) {
    return { tone: 'signal-warning', icon: 'bi-mic-mute', text: '尚未检测到清晰人声，请靠近麦克风说话' }
  }
  if (voice.silentForMs.value >= 8_000) {
    return {
      tone: 'signal-warning',
      icon: 'bi-exclamation-circle',
      text: `已连续 ${Math.floor(voice.silentForMs.value / 1_000)} 秒未检测到清晰人声`
    }
  }
  if (voice.silentForMs.value >= 3_000) {
    return { tone: 'signal-waiting', icon: 'bi-volume-down', text: '当前音量偏低，请继续大声说出想法' }
  }
  return { tone: 'signal-ok', icon: 'bi-soundwave', text: '声音采集正常' }
})

const submissionWarnings = computed(() => {
  const warnings: string[] = []
  if (voice.recordingDurationSeconds.value < 30) warnings.push('本任务录音不足 30 秒，请确认已完整说出思考过程。')
  if (!voice.hasDetectedAudio.value) warnings.push('系统尚未检测到清晰人声。')
  if (!isOnline.value) warnings.push('当前网络已断开，恢复连接前无法完成提交。')
  if (failedTransferCount.value > 0) warnings.push(`有 ${failedTransferCount.value} 项数据等待重新同步。`)
  if (pendingTransferCount.value > 0) warnings.push(`仍有 ${pendingTransferCount.value} 项数据正在同步，提交时会自动等待。`)
  return warnings
})

const hasActiveTaskData = computed(() => (
  phase.value === 'task'
  && Boolean(activeSessionId)
  && (
    voice.isRecording.value
    || isBusy.value
    || pendingTransferCount.value > 0
    || failedTransferCount.value > 0
    || generatedAudioChunkCount.value > uploadedAudioChunkCount.value
  )
))

function requestFinishTask() {
  if (!taskCanSubmit.value || isBusy.value || isSpeaking.value) return
  submitConfirmationOpen.value = true
}

function confirmFinishTask() {
  if (!isOnline.value) return
  submitConfirmationOpen.value = false
  void finishTask()
}

async function startMandatoryTaskRecording(reason: 'task_started' | 'participant_started' | 'retry') {
  errorMessage.value = ''
  if (voice.isRecording.value || voice.recordingStatus.value === 'starting') return
  const started = await voice.startRecording(
    nextAudioChunkIndex.value,
    nextAudioTimelineMs.value
  )
  if (started) {
    recordInteractionEvent('recording_started', {
      initial_chunk_index: nextAudioChunkIndex.value,
      mode: 'mandatory',
      reason
    })
    return
  }
  errorMessage.value = voice.errorMessage.value || '正式任务必须录音。请允许麦克风访问后重试。'
}

async function startTaskRecordingFromButton() {
  if (phase.value !== 'task' || !activeSessionId) return
  interruptNarrationForRecording()
  await startMandatoryTaskRecording('participant_started')
}

async function retryFailedTransfers(sessionId: string) {
  const audio = [...failedAudioChunks]
  const transcripts = [...failedTranscriptSegments]
  failedAudioChunks = []
  failedTranscriptSegments = []
  syncFailedTransferCount()
  let firstError: unknown = null
  for (const chunk of audio) {
    try {
      await sessionApi.uploadAudioChunk(sessionId, chunk)
      uploadedAudioChunkCount.value += 1
      if (run.value) {
        const offlineId = audioChunkRecordId(
          run.value.user_id,
          run.value.id,
          sessionId,
          chunk.chunkIndex
        )
        await removeOfflineAudioChunk(offlineId)
        markOfflineSynced(offlineId)
      }
      recordInteractionEvent('audio_chunk_uploaded', {
        chunk_index: chunk.chunkIndex,
        size_bytes: chunk.blob.size,
        mime_type: chunk.mimeType,
        retry: true
      })
    } catch (error) {
      failedAudioChunks.push(chunk)
      syncFailedTransferCount()
      firstError ??= error
    }
  }
  for (const segment of transcripts) {
    try {
      await sessionApi.saveTranscripts(sessionId, [{
        client_segment_id: segment.id,
        text: segment.text,
        started_at_ms: segment.startedAtMs,
        ended_at_ms: segment.endedAtMs,
        is_final: true,
        source: 'browser'
      }])
      savedTranscriptCount.value += 1
      const offlineId = transcriptRecordId(sessionId, segment.id)
      await removeOfflineTranscript(offlineId)
      markOfflineSynced(offlineId)
    } catch (error) {
      failedTranscriptSegments.push(segment)
      syncFailedTransferCount()
      firstError ??= error
    }
  }
  await eventUploadQueue
  await retryFailedInteractionEvents(sessionId)
  syncFailedTransferCount()
  if (firstError) throw firstError
}

async function retryFailedInteractionEvents(sessionId: string) {
  const events = [...failedInteractionEvents]
  failedInteractionEvents = []
  syncFailedTransferCount()
  if (events.length === 0) return
  try {
    for (let index = 0; index < events.length; index += 100) {
      const batch = events.slice(index, index + 100)
      await sessionApi.saveEvents(sessionId, batch)
      for (const event of batch) {
        const offlineId = eventRecordId(sessionId, event.client_event_id)
        await removeOfflineEvent(offlineId)
        markOfflineSynced(offlineId)
      }
    }
  } catch (error) {
    failedInteractionEvents.push(...events)
    syncFailedTransferCount()
    throw error
  }
}

async function retryCurrentTransfers() {
  if (!activeSessionId || transferRetrying.value || failedTransferCount.value === 0 || !isOnline.value) return
  transferRetrying.value = true
  errorMessage.value = ''
  try {
    await Promise.all([audioUploadQueue, transcriptUploadQueue, eventUploadQueue])
    await retryFailedTransfers(activeSessionId)
  } catch (error) {
    errorMessage.value = getError(error, '数据重试仍未成功，请保持页面打开并检查网络。')
  } finally {
    syncFailedTransferCount()
    transferRetrying.value = false
  }
}

async function finishTask() {
  if (!activeSessionId) return
  if (!isOnline.value) {
    errorMessage.value = '当前网络已断开。录音数据仍保留在本页，请联网后重试提交。'
    return
  }
  isBusy.value = true
  errorMessage.value = ''
  const sessionId = activeSessionId
  const elapsed = voice.recordingDurationSeconds.value
  try {
    await voice.stopRecording()
    recordInteractionEvent('recording_stopped', { elapsed_seconds: elapsed })
    await Promise.all([audioUploadQueue, transcriptUploadQueue])
    await eventUploadQueue
    if (
      failedAudioChunks.length
      || failedTranscriptSegments.length
      || failedInteractionEvents.length
    ) {
      await retryFailedTransfers(sessionId)
    }
    recordInteractionEvent('session_submitted', {
      elapsed_seconds: elapsed,
      expected_audio_chunks: generatedAudioChunkCount.value,
      expected_transcript_segments: generatedTranscriptCount.value
    })
    await eventUploadQueue
    await retryFailedInteractionEvents(sessionId)
    await refreshOfflinePendingCount()
    if (offlinePendingItemCount.value > 0) {
      throw new Error(`仍有 ${offlinePendingItemCount.value} 项实验数据等待同步，请保持联网后重试。`)
    }
    await sessionApi.complete(sessionId, {
      elapsed_seconds: elapsed,
      expected_audio_chunks: generatedAudioChunkCount.value,
      expected_transcript_segments: generatedTranscriptCount.value
    })
    activeSessionId = null
    if (taskIndex.value === 0) {
      await enterTask(1)
    } else {
      const nextPhase = questionnaireEnabled.value ? 'questionnaire' : 'review'
      await advanceServerStage(nextPhase)
      phase.value = nextPhase
      if (nextPhase === 'questionnaire') {
        questionnaireInstructionsAcknowledged.value = false
        await nextTick()
        speakQuestionnaireInstructions()
      }
    }
  } catch (error) {
    errorMessage.value = getError(error, '任务提交失败，请勿关闭页面并重试')
  } finally {
    isBusy.value = false
  }
}

async function submitQuestionnaire() {
  if (!run.value || !protocol.value || !questionnaireComplete.value) return
  isBusy.value = true
  errorMessage.value = ''
  try {
    const answers = protocol.value.questionnaire_items.map(item => ({
      item_id: item.id,
      value: questionnaireAnswers.value[item.id]
    }))
    const response = await protocolApi.submitQuestionnaire(
      run.value.id,
      answers,
      questionnaireParticipantName.value.trim()
    )
    run.value = response.data
    phase.value = 'review'
  } catch (error) {
    errorMessage.value = getError(error, '问卷提交失败')
  } finally {
    isBusy.value = false
  }
}

async function completeAssessment() {
  if (!run.value) return
  isBusy.value = true
  errorMessage.value = ''
  try {
    const response = await protocolApi.completeRun(run.value.id)
    run.value = response.data
    phase.value = 'completed'
    await clearOfflineRunData(response.data.user_id, response.data.id)
    offlineRecordIds.clear()
    offlinePendingItemCount.value = 0
  } catch (error) {
    errorMessage.value = getError(error, '测评提交失败')
  } finally {
    isBusy.value = false
  }
}

function formatSeconds(seconds: number) {
  const minutes = Math.floor(seconds / 60).toString().padStart(2, '0')
  const rest = (seconds % 60).toString().padStart(2, '0')
  return `${minutes}:${rest}`
}

function handleOnline() {
  isOnline.value = true
  void replayArchivedOfflineTransfers()
  if (failedTransferCount.value > 0) void retryCurrentTransfers()
}

function handleOffline() {
  isOnline.value = false
}

function handleBeforeUnload(event: BeforeUnloadEvent) {
  if (!hasActiveTaskData.value) return
  event.preventDefault()
  event.returnValue = ''
}

onBeforeRouteLeave(async () => {
  if (!hasActiveTaskData.value) return true
  return confirmAction({
    title: '确认离开当前测评？',
    message: '当前任务仍在录音或同步数据。现在离开可能造成实验数据丢失，建议完成提交后再离开。',
    confirmText: '仍要离开',
    cancelText: '继续测评',
    tone: 'danger'
  })
})

watch(
  [
    phase,
    taskIndex,
    practiceAnswer,
    practiceCompleted,
    questionnaireAnswers,
    questionnaireParticipantName
  ],
  scheduleSnapshotSave,
  { deep: true }
)

onMounted(() => {
  window.addEventListener('online', handleOnline)
  window.addEventListener('offline', handleOffline)
  window.addEventListener('beforeunload', handleBeforeUnload)
  void (async () => {
    const storage = await checkOfflineStorage()
    offlineStorageWarning.value = storage.message
    await loadProtocol()
  })()
})
onBeforeUnmount(() => {
  window.removeEventListener('online', handleOnline)
  window.removeEventListener('offline', handleOffline)
  window.removeEventListener('beforeunload', handleBeforeUnload)
  speechRequestId += 1
  if (snapshotTimer) clearTimeout(snapshotTimer)
  if (spokenPromptTimer) clearTimeout(spokenPromptTimer)
  stopCurrentNarration()
  for (const url of narrationObjectUrls.values()) URL.revokeObjectURL(url)
  narrationObjectUrls.clear()
})
</script>

<template>
  <div class="assessment-page">
    <div class="d-flex flex-wrap justify-content-between align-items-center gap-3 mb-4">
      <div>
        <p class="text-primary fw-semibold small mb-1">AI 元认知测评</p>
        <h3 class="mb-1">标准化出声思维测评</h3>
        <p class="text-muted mb-0">请按照页面顺序完成全部环节，中途不要刷新或关闭页面。</p>
      </div>
      <span class="badge rounded-pill bg-primary-subtle text-primary px-3 py-2">
        {{ stageLabels[run?.current_stage ?? phase] ?? '准备中' }}
      </span>
    </div>

    <div class="progress protocol-progress mb-4" role="progressbar" :aria-valuenow="progressPercent">
      <div class="progress-bar" :style="{ width: `${progressPercent}%` }" />
    </div>

    <div v-if="errorMessage" class="alert alert-danger d-flex align-items-center gap-2">
      <i class="bi bi-exclamation-triangle-fill" />
      <span>{{ errorMessage }}</span>
    </div>
    <div v-if="offlineStorageWarning" class="alert alert-warning d-flex align-items-center gap-2" role="status">
      <i class="bi bi-device-ssd" aria-hidden="true" />
      <span>{{ offlineStorageWarning }}</span>
    </div>

    <div v-if="phase === 'loading'" class="card border-0 shadow-sm">
      <div class="card-body py-5 text-center">
        <div class="spinner-border text-primary mb-3" />
        <p class="text-muted mb-0">正在加载标准测评协议……</p>
      </div>
    </div>

    <div v-else-if="phase === 'error'" class="card border-0 shadow-sm">
      <div class="card-body py-5 text-center">
        <i class="bi bi-cloud-slash display-5 text-danger" />
        <h5 class="mt-3">测评内容加载失败</h5>
        <button class="btn btn-primary mt-2" @click="loadProtocol">重新加载</button>
      </div>
    </div>

    <!-- 阶段 1: 知情同意 -->
    <ConsentPhase
      v-else-if="phase === 'consent'"
      :is-busy="isBusy"
      @agree="beginAssessment"
    />

    <!-- 阶段 2: 设备检查 -->
    <DeviceCheckPhase
      v-else-if="phase === 'device_check'"
      :permission="voice.permission.value"
      :microphone-test-status="voice.microphoneTestStatus.value"
      :microphone-test-seconds-remaining="voice.microphoneTestSecondsRemaining.value"
      :microphone-test-level="voice.microphoneTestLevel.value"
      :media-stream="voice.mediaStream.value"
      :recognition-available="voice.recognitionAvailable.value"
      :speech-synthesis-available="speechSynthesisAvailable"
      :narration-assets-count="protocol?.narration_assets.length ?? 0"
      :is-busy="isBusy"
      @test-microphone="checkMicrophone"
      @next="enterInstructions"
    />

    <!-- 阶段 3: 出声思维说明 -->
    <InstructionsPhase
      v-else-if="phase === 'instructions'"
      :is-busy="isBusy"
      @next="enterPractice"
    />

    <!-- 阶段 4: 练习任务 -->
    <PracticePhase
      v-else-if="phase === 'practice'"
      :is-recording="voice.isRecording.value"
      :audio-level="voice.volumeLevel.value"
      :media-stream="voice.mediaStream.value"
      :transcript="voice.finalTranscript.value || voice.interimTranscript.value"
      :practice-completed="practiceCompleted"
      :is-busy="isBusy"
      @toggle-recording="togglePracticeRecording"
      @next="enterTask(0)"
    />

    <!-- 阶段 5: 正式任务 (任务1 & 任务2) -->
    <TaskWorkspacePhase
      v-else-if="phase === 'task' && currentTask"
      :task-index="taskIndex"
      :current-task="currentTask"
      :task-image="taskImage"
      :task-unit-note="taskUnitNote"
      :spoken-prompt="spokenPrompt"
      :spoken-prompt-kind="spokenPromptKind"
      :is-recording="voice.isRecording.value"
      :recording-duration-seconds="voice.recordingDurationSeconds.value"
      :recording-duration-formatted="formatSeconds(voice.recordingDurationSeconds.value)"
      :volume-level="voice.volumeLevel.value"
      :media-stream="voice.mediaStream.value"
      :waveform-status="waveformStatus"
      :audio-signal-presentation="audioSignalPresentation"
      :recording-status-class="recordingStatusClass"
      :recording-status-icon="recordingStatusIcon"
      :recording-status-title="recordingStatusTitle"
      :recording-status-detail="recordingStatusDetail"
      :recording-needs-attention="recordingNeedsAttention"
      :silence-remaining-seconds="voice.silenceRemainingSeconds.value"
      :task-transcript="taskTranscript"
      :interim-transcript="voice.interimTranscript.value"
      :is-online="isOnline"
      :failed-transfer-count="failedTransferCount"
      :pending-transfer-count="pendingTransferCount"
      :generated-audio-chunk-count="generatedAudioChunkCount"
      :uploaded-audio-chunk-count="uploadedAudioChunkCount"
      :saved-transcript-count="savedTranscriptCount"
      :generated-transcript-count="generatedTranscriptCount"
      :transfer-progress="transferProgress"
      :transfer-retrying="transferRetrying"
      :task-recording-can-start="taskRecordingCanStart"
      :task-can-submit="taskCanSubmit"
      :is-busy="isBusy"
      :is-speaking="isSpeaking"
      :questionnaire-enabled="questionnaireEnabled"
      @start-recording="startTaskRecordingFromButton"
      @retry-recording="startMandatoryTaskRecording('retry')"
      @retry-transfers="retryCurrentTransfers"
      @request-finish="requestFinishTask"
      @tool-event="recordToolEvent"
    />

    <!-- 阶段 6: 任务后问卷 -->
    <QuestionnairePhase
      v-else-if="phase === 'questionnaire'"
      :acknowledged="questionnaireInstructionsAcknowledged"
      :is-speaking="isSpeaking"
      :protocol="protocol"
      :questionnaire-total-count="questionnaireTotalCount"
      :answered-count="answeredCount"
      :questionnaire-answers="questionnaireAnswers"
      :participant-name="questionnaireParticipantName"
      :questionnaire-complete="questionnaireComplete"
      :is-busy="isBusy"
      @acknowledge="acknowledgeQuestionnaireInstructions"
      @update:participant-name="questionnaireParticipantName = $event"
      @submit="submitQuestionnaire"
    />

    <!-- 阶段 7: 提交前审查 -->
    <ReviewPhase
      v-else-if="phase === 'review'"
      :questionnaire-enabled="questionnaireEnabled"
      :questionnaire-items-count="protocol?.questionnaire_items.length ?? 0"
      :submitted-session-ids="submittedSessionIds"
      :is-busy="isBusy"
      @complete="completeAssessment"
      @ready-change="asrReady = $event"
    />

    <!-- 阶段 8: 完成 -->
    <CompletedPhase
      v-else-if="phase === 'completed'"
      :questionnaire-enabled="questionnaireEnabled"
      :submitted-session-ids="submittedSessionIds"
      :run-id="run?.id"
      :asr-ready="asrReady"
      @ready-change="asrReady = $event"
    />

    <!-- 任务提交确认弹窗 -->
    <TaskSubmitModal
      :open="submitConfirmationOpen"
      :task-index="taskIndex"
      :recording-duration-formatted="formatSeconds(voice.recordingDurationSeconds.value)"
      :generated-audio-chunk-count="generatedAudioChunkCount"
      :failed-transfer-count="failedTransferCount"
      :pending-transfer-count="pendingTransferCount"
      :submission-warnings="submissionWarnings"
      :is-online="isOnline"
      @close="submitConfirmationOpen = false"
      @confirm="confirmFinishTask"
    />

    <AssessmentRecoveryModal
      :open="recoveryOpen"
      :snapshot="recoverySnapshot"
      :pending-item-count="offlinePendingItemCount"
      :is-busy="recoveryBusy"
      @restore="restoreLocalSnapshot"
      @discard="discardLocalSnapshot"
    />
  </div>
</template>

<style scoped>
.assessment-page { max-width: 1240px; margin: 0 auto; }
.protocol-progress { height: 6px; background: var(--color-border); }
.card { border-radius: var(--radius-lg); }
</style>
