<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppPageHeader from '../components/ui/AppPageHeader.vue'
import AudioTranscriptPlayer from '../components/audio/AudioTranscriptPlayer.vue'
import {
  extractionApi,
  type CandidateRevision,
  type ExtractionCandidate,
  type ExtractionJob,
  type ExtractionQueueItem,
  type ExtractionReviewDetail
} from '../api/extraction'
import { asrApi } from '../api/asr'
import { confirmAction } from '../composables/useUiFeedback'
import { useUserStore } from '../stores/user'
import { useExtractionTaskStore } from '../stores/extractionTasks'
import { parseApiDate } from '../utils/datetime'

type Draft = { original_text: string; clean_text: string; review_note: string }
type QueueTaskGroup = {
  taskId: string
  taskTitle: string
  sequenceNo: number
  items: ExtractionQueueItem[]
}
type QueueUserGroup = {
  user: ExtractionQueueItem
  itemCount: number
  taskGroups: QueueTaskGroup[]
}

const userStore = useUserStore()
const route = useRoute()
const extractionTaskStore = useExtractionTaskStore()
const queue = ref<ExtractionQueueItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const totalPages = ref(1)
const classGroups = ref<string[]>([])
const taskOptions = ref<Array<{ id: string; title: string }>>([])
const statusOptions = ref<string[]>([])
const filters = reactive({ keyword: '', class_group: '', task_id: '', status: '' })
const selectedSessionId = ref('')
const selectedJobId = ref('')
const detail = ref<ExtractionReviewDetail | null>(null)
const loading = ref(true)
const detailLoading = ref(false)
const busyId = ref('')
const errorMessage = ref('')
const successMessage = ref('')
const audioUrl = ref('')
const reviewPlayer = ref<InstanceType<typeof AudioTranscriptPlayer> | null>(null)
const audioPeaks = ref<number[]>([])
const audioDuration = ref(0)
const audioLoading = ref(false)
const audioError = ref('')
const audioTicketExpires = ref(0)
const audioReady = ref(false)
const drafts = reactive<Record<string, Draft>>({})
const draftSavedAt = ref<Record<string, number>>({})
const focusedCandidateId = ref('')
const candidatePage = ref(1)
const candidatePageSize = ref(10)
const lockRenewing = ref(false)
const candidateHistories = ref<Record<string, CandidateRevision[]>>({})
const historyBusyId = ref('')
const expandedQueueUserIds = ref<string[]>([])
const selectedRerunSessionIds = ref<string[]>([])
const batchRerunBusy = ref(false)
const currentBatchJobIds = ref<string[]>([])
const refreshedTerminalJobIds = new Set<string>()
const addition = reactive({
  source_transcript_segment_id: '', original_text: '', clean_text: '',
  started_at_ms: 0, ended_at_ms: 0,
  review_note: '人工听取原始录音后补充遗漏'
})

let searchTimer: number | null = null
let lockTimer: number | null = null
const MAX_BATCH_RERUN = 50

const pendingCount = computed(() => detail.value?.pending_count ?? 0)
const acceptedCount = computed(() => detail.value?.accepted_count ?? 0)
const lowRiskCount = computed(() => detail.value?.candidates.filter(item => item.is_low_risk).length ?? 0)

// 当前生产模型输出三分类（监控 / 控制调控 / 评估），非元认知项在候选复核阶段已过滤。
// 下方同时保留旧版模型或 TF-IDF 降级可能出现的所有值，确保任何情况下都显示中文。
const classifierDimensionLabels: Record<string, string> = {
  // 生产模型三分类标准输出（DIMENSION_MAP 定义）
  monitoring: '监控',
  controlDebugging: '控制/调控',
  evaluation: '评估',
  // 向下兼容：旧版四分类模型或 TF-IDF 降级时可能残留的标签值
  non_meta: '非元认知（旧版）',
  non_metacognitive: '非元认知（旧版）',
  planning: '计划（旧版）',
  regulation: '调节/控制（旧版）',
}

function classifierLabel(candidate: ExtractionCandidate) {
  return candidate.predicted_dimension
    ? classifierDimensionLabels[candidate.predicted_dimension] ?? candidate.predicted_dimension
    : ''
}

const classificationStatusLabels: Record<ExtractionCandidate['classification_status'], string> = {
  pending_classification: '等待分类',
  classified: '远程嵌入分类完成',
  classified_with_fallback: 'TF-IDF 降级分类完成',
  not_active: '尚未启用生产模型'
}

function classificationStatusLabel(candidate: ExtractionCandidate) {
  return classificationStatusLabels[candidate.classification_status] ?? candidate.classification_status
}

function predictionSourceLabel(candidate: ExtractionCandidate) {
  if (candidate.prediction_source === 'remote_embedding') return '远程 Embedding API'
  if (candidate.prediction_source === 'tfidf_production') return 'TF-IDF 生产模型'
  if (candidate.prediction_source === 'tfidf_fallback') return 'TF-IDF 安全降级'
  return '未产生预测'
}
const candidateTotalPages = computed(() => detail.value?.candidate_total_pages ?? 1)
const visibleCandidates = computed(() => detail.value?.candidates ?? [])
const candidateAudioSegments = computed(() => visibleCandidates.value.map(candidate => ({
  segment_no: candidate.sequence_no,
  text: candidate.clean_text || candidate.original_text,
  started_at_ms: candidate.started_at_ms,
  ended_at_ms: candidate.ended_at_ms
})))
const currentQueueItem = computed(() => queue.value.find(item => item.session_id === selectedSessionId.value) ?? null)
const eligiblePageRerunIds = computed(() => queue.value
  .filter(item => canRerunQueueItem(item))
  .map(item => item.session_id))
const allEligiblePageSelected = computed(() => Boolean(
  eligiblePageRerunIds.value.length
  && eligiblePageRerunIds.value.every(id => selectedRerunSessionIds.value.includes(id))
))
const queueGroups = computed(() => {
  const groups = new Map<string, {
    user: ExtractionQueueItem
    tasks: Map<string, QueueTaskGroup>
  }>()
  for (const item of queue.value) {
    let group = groups.get(item.user_id)
    if (!group) {
      group = { user: item, tasks: new Map<string, QueueTaskGroup>() }
      groups.set(item.user_id, group)
    }
    const logicalTaskKey = item.task_title.trim()
    let taskGroup = group.tasks.get(logicalTaskKey)
    if (!taskGroup) {
      taskGroup = {
        taskId: item.task_id,
        taskTitle: item.task_title,
        sequenceNo: item.sequence_no,
        items: []
      }
      group.tasks.set(logicalTaskKey, taskGroup)
    }
    taskGroup.items.push(item)
  }
  return [...groups.values()].map<QueueUserGroup>(group => {
    const taskGroups = [...group.tasks.values()].map(taskGroup => ({
      ...taskGroup,
      items: [...taskGroup.items].sort((left, right) => queueCompletionTimestamp(right) - queueCompletionTimestamp(left))
    }))
    return {
      user: group.user,
      itemCount: taskGroups.reduce((sum, taskGroup) => sum + taskGroup.items.length, 0),
      taskGroups
    }
  })
})
const latestJob = computed(() => detail.value?.job_history[0] ?? null)
const currentTrackedTask = computed(() => {
  const jobId = detail.value?.job?.id
  return jobId ? extractionTaskStore.tasks[jobId] ?? null : null
})
const currentJobStatus = computed(() => (
  currentTrackedTask.value?.status ?? detail.value?.job?.status ?? ''
))
const currentJobCandidateCount = computed(() => (
  currentTrackedTask.value?.candidate_count ?? detail.value?.candidate_total ?? 0
))
const currentBatchTasks = computed(() => currentBatchJobIds.value
  .map(id => extractionTaskStore.tasks[id])
  .filter((item): item is NonNullable<typeof item> => Boolean(item)))
const currentBatchSummary = computed(() => {
  const summary = { total: currentBatchTasks.value.length, queued: 0, running: 0, completed: 0, failed: 0 }
  currentBatchTasks.value.forEach(task => {
    if (task.status === 'queued' || task.status === 'retry_wait') summary.queued += 1
    else if (task.status === 'running') summary.running += 1
    else if (task.status === 'failed') summary.failed += 1
    else summary.completed += 1
  })
  return summary
})
const canEdit = computed(() => Boolean(
  detail.value?.job?.status === 'reviewing' && detail.value.locked_by_current_user
))
const currentCandidate = computed(() => {
  const candidates = detail.value?.candidates ?? []
  return candidates.find(item => item.id === focusedCandidateId.value)
    ?? candidates.find(item => item.review_status === 'pending')
    ?? candidates[0]
    ?? null
})
const pipelineStatusLabel = computed(() => currentQueueItem.value
  ? statusLabel(currentQueueItem.value)
  : statusText(detail.value?.asr_status ?? 'asr_not_created'))

function statusText(status: string) {
  return {
    asr_not_created: '待识别', asr_processing: '识别处理中', asr_failed: '识别失败',
    asr_waiting_configuration: '识别待配置', ready_for_extraction: '待候选抽取',
    extraction_queued: '抽取排队中', extraction_running: '抽取中',
    extraction_retry_wait: '抽取等待重试', extraction_reviewing: '待复核',
    extraction_reviewed: '已复核', extraction_failed: '抽取失败',
    extraction_superseded: '版本已失效', not_created: '待识别', failed: '识别失败'
  }[status] ?? status
}

function statusLabel(item: ExtractionQueueItem) {
  if (!item.transcript_version_no) {
    if (item.asr_status === 'failed') return statusText('asr_failed')
    if (item.asr_status === 'waiting_configuration') return statusText('asr_waiting_configuration')
    if (item.asr_status === 'not_created') return statusText('asr_not_created')
    return statusText('asr_processing')
  }
  if (!item.job) return statusText('ready_for_extraction')
  const trackedStatus = extractionTaskStore.tasks[item.job.id]?.status
  return statusText(`extraction_${trackedStatus ?? item.job.status}`)
}

function canRerunQueueItem(item: ExtractionQueueItem) {
  const status = item.job
    ? extractionTaskStore.tasks[item.job.id]?.status ?? item.job.status
    : ''
  return Boolean(
    item.transcript_version_no
    && item.job
    && !['queued', 'running', 'retry_wait'].includes(status)
  )
}

function trackJob(job: ExtractionJob, item?: ExtractionQueueItem | null) {
  extractionTaskStore.track(job, {
    user_name: item?.user_name ?? detail.value?.user_name ?? '',
    task_title: item?.task_title ?? detail.value?.task_title ?? ''
  })
}

function displayedJobStatus(job: ExtractionJob) {
  return extractionTaskStore.tasks[job.id]?.status ?? job.status
}

function toggleRerunSelection(sessionId: string, checked: boolean) {
  if (
    checked
    && !selectedRerunSessionIds.value.includes(sessionId)
    && selectedRerunSessionIds.value.length >= MAX_BATCH_RERUN
  ) {
    errorMessage.value = `单次最多选择 ${MAX_BATCH_RERUN} 条记录，请先执行当前批次。`
    return
  }
  selectedRerunSessionIds.value = checked
    ? [...new Set([...selectedRerunSessionIds.value, sessionId])]
    : selectedRerunSessionIds.value.filter(id => id !== sessionId)
}

function toggleEligiblePageSelection() {
  if (allEligiblePageSelected.value) {
    const pageIds = new Set(eligiblePageRerunIds.value)
    selectedRerunSessionIds.value = selectedRerunSessionIds.value.filter(id => !pageIds.has(id))
  } else {
    const remaining = MAX_BATCH_RERUN - selectedRerunSessionIds.value.length
    const available = eligiblePageRerunIds.value
      .filter(id => !selectedRerunSessionIds.value.includes(id))
    const additions = available
      .slice(0, Math.max(0, remaining))
    selectedRerunSessionIds.value = [
      ...new Set([...selectedRerunSessionIds.value, ...additions])
    ]
    if (additions.length < available.length) {
      errorMessage.value = `单次最多选择 ${MAX_BATCH_RERUN} 条记录。`
    }
  }
}

function formatDate(value: string) {
  return parseApiDate(value).toLocaleString('zh-CN', { hour12: false })
}

function queueCompletionTimestamp(item: ExtractionQueueItem) {
  return item.completed_at ? parseApiDate(item.completed_at).getTime() : 0
}

function formatCompletionTime(item: ExtractionQueueItem) {
  if (!item.completed_at) return '完成时间未记录'
  const prefix = item.completed_at_source === 'session_end'
    ? '完成于'
    : item.completed_at_source === 'run_completed'
      ? '整次测评完成于'
      : '记录于'
  return `${prefix} ${formatDate(item.completed_at)}`
}

function completionTimeTitle(item: ExtractionQueueItem) {
  if (item.completed_at_source === 'session_start_fallback') {
    return '该历史记录缺少任务结束时间，当前显示任务开始记录时间'
  }
  if (item.completed_at_source === 'run_completed') {
    return '该历史记录缺少单项任务结束时间，当前显示整次测评完成时间'
  }
  return '该任务的实际完成时间'
}

function isQueueUserExpanded(userId: string) {
  return expandedQueueUserIds.value.includes(userId)
}

function toggleQueueUser(userId: string) {
  expandedQueueUserIds.value = isQueueUserExpanded(userId)
    ? expandedQueueUserIds.value.filter(item => item !== userId)
    : [...expandedQueueUserIds.value, userId]
}

function revisionActionLabel(action: string) {
  return ({
    review_accepted: '接受并保存', review_rejected: '排除并保存',
    bulk_accept_low_risk: '批量接受低风险候选', human_create: '人工补充候选'
  } as Record<string, string>)[action] ?? action
}

function snapshotText(snapshot: Record<string, unknown> | null, key: string) {
  const value = snapshot?.[key]
  return typeof value === 'string' ? value : '—'
}

function draftKey(candidate: ExtractionCandidate) {
  return `candidate-draft:${userStore.profile.id}:${candidate.extraction_job_id}:${candidate.id}:${candidate.updated_at}`
}

function seedDrafts(candidates: ExtractionCandidate[]) {
  for (const item of candidates) {
    let saved: Draft | null = null
    try {
      saved = JSON.parse(localStorage.getItem(draftKey(item)) ?? 'null') as Draft | null
    } catch { saved = null }
    drafts[item.id] = saved ?? {
      original_text: item.original_text,
      clean_text: item.clean_text,
      review_note: item.review_note
    }
  }
}

function saveDraft(candidate: ExtractionCandidate) {
  const draft = drafts[candidate.id]
  if (!draft) return
  localStorage.setItem(draftKey(candidate), JSON.stringify(draft))
  draftSavedAt.value = { ...draftSavedAt.value, [candidate.id]: Date.now() }
}

function clearDraft(candidate: ExtractionCandidate) {
  localStorage.removeItem(draftKey(candidate))
  const next = { ...draftSavedAt.value }
  delete next[candidate.id]
  draftSavedAt.value = next
}

function clearAudio() {
  reviewPlayer.value?.pause()
  audioPeaks.value = []
  audioDuration.value = 0
  audioUrl.value = ''
  audioError.value = ''
  audioTicketExpires.value = 0
  audioReady.value = false
}

function clearLockTimer() {
  if (lockTimer !== null) window.clearInterval(lockTimer)
  lockTimer = null
}

async function releaseCurrentLock() {
  clearLockTimer()
  if (detail.value?.locked_by_current_user && detail.value.session_id) {
    try { await extractionApi.releaseLock(detail.value.session_id) } catch { /* lease expires safely */ }
  }
}

async function loadQueue(selectFirst = false) {
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await extractionApi.listQueue({
      page: page.value, page_size: pageSize.value,
      keyword: filters.keyword || undefined,
      class_group: filters.class_group || undefined,
      task_id: filters.task_id || undefined,
      status: filters.status || undefined
    })
    queue.value = response.data.items
    queue.value.forEach(item => {
      if (item.job && ['queued', 'running', 'retry_wait'].includes(item.job.status)) {
        trackJob(item.job, item)
      }
    })
    total.value = response.data.total
    page.value = response.data.page
    totalPages.value = response.data.total_pages
    classGroups.value = response.data.class_groups
    taskOptions.value = response.data.tasks
    statusOptions.value = response.data.statuses
    expandedQueueUserIds.value = expandedQueueUserIds.value.filter(id => (
      queue.value.some(item => item.user_id === id)
    ))
    if ((selectFirst || !selectedSessionId.value) && queue.value.length) {
      if (!isQueueUserExpanded(queue.value[0].user_id)) {
        expandedQueueUserIds.value = [...expandedQueueUserIds.value, queue.value[0].user_id]
      }
      await selectSession(queue.value[0].session_id, false, '')
    } else if (selectedSessionId.value && !queue.value.some(item => item.session_id === selectedSessionId.value)) {
      await releaseCurrentLock()
      selectedSessionId.value = ''
      detail.value = null
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '候选复核队列加载失败'
  } finally { loading.value = false }
}

async function acquireLock() {
  if (!detail.value || detail.value.job?.status !== 'reviewing') return
  try {
    const lease = (await extractionApi.acquireLock(detail.value.session_id)).data
    detail.value.locked_by_current_user = lease.locked_by_current_user
    detail.value.lock_owner_name = lease.lock_owner_name
    detail.value.lock_expires_at = lease.lock_expires_at
    clearLockTimer()
    if (lease.acquired) {
      lockTimer = window.setInterval(() => void renewLock(), 120_000)
    }
  } catch (error) {
    detail.value.locked_by_current_user = false
    errorMessage.value = error instanceof Error ? error.message : '暂时无法获取复核编辑权，页面已切换为只读'
  }
}

async function renewLock() {
  if (!detail.value?.locked_by_current_user || lockRenewing.value) return
  lockRenewing.value = true
  try {
    const lease = (await extractionApi.renewLock(detail.value.session_id)).data
    detail.value.lock_expires_at = lease.lock_expires_at
  } catch (error) {
    clearLockTimer()
    detail.value.locked_by_current_user = false
    errorMessage.value = error instanceof Error ? error.message : '复核编辑权已失效'
  } finally { lockRenewing.value = false }
}

async function selectSession(
  sessionId: string,
  forceAudioReload = false,
  jobId?: string,
  requestedCandidatePage?: number
) {
  const sessionChanged = selectedSessionId.value !== sessionId
  const requestedJobId = jobId === undefined ? (sessionChanged ? '' : selectedJobId.value) : jobId
  const jobChanged = Boolean(detail.value?.job?.id && requestedJobId !== detail.value.job.id)
  const targetCandidatePage = sessionChanged || jobChanged
    ? 1
    : (requestedCandidatePage ?? candidatePage.value)
  if (selectedSessionId.value && (sessionChanged || jobChanged)) await releaseCurrentLock()
  selectedSessionId.value = sessionId
  const selectedQueueItem = queue.value.find(item => item.session_id === sessionId)
  if (selectedQueueItem && !isQueueUserExpanded(selectedQueueItem.user_id)) {
    expandedQueueUserIds.value = [...expandedQueueUserIds.value, selectedQueueItem.user_id]
  }
  selectedJobId.value = requestedJobId
  detailLoading.value = true
  let shouldLoadAudio = false
  errorMessage.value = ''
  successMessage.value = ''
  if (sessionChanged || forceAudioReload) clearAudio()
  try {
    detail.value = (await extractionApi.detail(
      sessionId,
      requestedJobId || undefined,
      targetCandidatePage,
      candidatePageSize.value
    )).data
    if (detail.value.job && ['queued', 'running', 'retry_wait'].includes(detail.value.job.status)) {
      trackJob(detail.value.job, selectedQueueItem)
    }
    selectedJobId.value = detail.value.job?.id ?? ''
    candidateHistories.value = {}
    seedDrafts(detail.value.candidates)
    focusedCandidateId.value = detail.value.candidates.find(item => item.review_status === 'pending')?.id
      ?? detail.value.candidates[0]?.id ?? ''
    candidatePage.value = detail.value.candidate_page
    shouldLoadAudio = detail.value.audio_available && !audioUrl.value
    if (detail.value.job?.status === 'reviewing') await acquireLock()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '复核详情加载失败'
  } finally { detailLoading.value = false }
  // The detail panel (and its <audio> element) does not exist while the loading
  // placeholder is visible. Load the ticket only after Vue has mounted it.
  if (shouldLoadAudio && detail.value?.session_id === sessionId) {
    await nextTick()
    void loadReviewAudio(sessionId)
  }
}

async function loadCandidatePage(nextPage: number) {
  if (!detail.value || detailLoading.value) return
  await selectSession(
    detail.value.session_id,
    false,
    detail.value.job?.id || undefined,
    Math.max(1, Math.min(candidateTotalPages.value, nextPage))
  )
}

async function changeCandidatePageSize() {
  await loadCandidatePage(1)
}

async function rerunExtraction() {
  if (!detail.value?.transcript_version_id) return
  const confirmed = await confirmAction({
    title: '生成新的候选抽取版本',
    message: '系统会保留当前候选、复核历史及其编码引用，并使用当前启用的提示词创建新的独立抽取版本。是否继续？',
    confirmText: '创建新版本', tone: 'warning'
  })
  if (!confirmed) return
  busyId.value = 'rerun'; errorMessage.value = ''; successMessage.value = ''
  try {
    const sessionId = detail.value.session_id
    const context = currentQueueItem.value
    const job = (await extractionApi.rerun(sessionId)).data
    trackJob(job, context)
    await loadQueue()
    await selectSession(sessionId, false, job.id)
    successMessage.value = `候选抽取版本 V${job.generation_no} 已进入队列；系统会持续显示状态，并在完成后通知您。`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '新版本抽取任务创建失败'
  } finally { busyId.value = '' }
}

async function batchRerunExtraction() {
  if (!selectedRerunSessionIds.value.length || batchRerunBusy.value) return
  const count = selectedRerunSessionIds.value.length
  const confirmed = await confirmAction({
    title: `批量生成 ${count} 个新抽取版本`,
    message: '每条记录都会保留旧候选、人工复核历史和编码引用；正在处理中的任务将自动跳过。是否继续？',
    confirmText: '批量生成',
    tone: 'warning'
  })
  if (!confirmed) return
  batchRerunBusy.value = true
  errorMessage.value = ''
  successMessage.value = ''
  const sessionIds = [...selectedRerunSessionIds.value]
  const contexts = new Map(queue.value.map(item => [item.session_id, item]))
  try {
    await releaseCurrentLock()
    const result = (await extractionApi.batchRerun(sessionIds)).data
    const createdJobs = result.items
      .filter(item => item.status === 'created' && item.job)
      .map(item => item.job as ExtractionJob)
    extractionTaskStore.trackMany(createdJobs.map(job => ({
      job,
      context: {
        user_name: contexts.get(job.session_id)?.user_name ?? '',
        task_title: contexts.get(job.session_id)?.task_title ?? ''
      }
    })))
    currentBatchJobIds.value = createdJobs.map(job => job.id)
    if (result.failed) {
      const failedMessages = result.items
        .filter(item => item.status === 'failed')
        .slice(0, 3)
        .map(item => item.message)
      errorMessage.value = `部分记录处理失败：${failedMessages.join('；')}`
    }
    selectedRerunSessionIds.value = []
    await loadQueue()
    if (selectedSessionId.value) await selectSession(selectedSessionId.value, false, '')
    successMessage.value = `批量任务已提交：创建 ${result.created} 条，跳过 ${result.skipped} 条，失败 ${result.failed} 条。下方会持续更新完成进度。`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量生成新抽取版本失败'
  } finally {
    batchRerunBusy.value = false
  }
}

async function toggleCandidateHistory(candidateId: string) {
  if (candidateHistories.value[candidateId]) {
    const next = { ...candidateHistories.value }
    delete next[candidateId]
    candidateHistories.value = next
    return
  }
  historyBusyId.value = candidateId
  try {
    const history = (await extractionApi.candidateHistory(candidateId)).data
    candidateHistories.value = { ...candidateHistories.value, [candidateId]: history }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '候选操作历史加载失败'
  } finally { historyBusyId.value = '' }
}

function resolveReviewAudioUrl(url: string) {
  try {
    return new URL(url, window.location.origin).toString()
  } catch {
    return url
  }
}

async function loadReviewAudio(
  sessionId = detail.value?.session_id ?? '',
  forceReload = false
) {
  if (!sessionId || audioLoading.value) return
  audioLoading.value = true
  audioError.value = ''
  audioPeaks.value = []
  audioReady.value = false
  if (forceReload) {
    reviewPlayer.value?.pause()
    audioUrl.value = ''
    await nextTick()
  }
  try {
    const ticket = await extractionApi.audioTicket(sessionId)
    if (detail.value?.session_id !== sessionId) return
    audioUrl.value = resolveReviewAudioUrl(ticket.data.url)
    audioTicketExpires.value = ticket.data.expires
    void loadReviewWaveform(sessionId)
  } catch (error) {
    audioUrl.value = ''
    audioError.value = error instanceof Error ? error.message : '完整录音加载失败'
  } finally {
    audioLoading.value = false
  }
}

async function loadReviewWaveform(sessionId: string) {
  try {
    const response = await extractionApi.audioWaveform(sessionId)
    if (detail.value?.session_id !== sessionId) return
    audioDuration.value = response.data.duration_seconds
    audioPeaks.value = response.data.peaks
  } catch {
    // Waveform is an enhancement; native streaming playback remains available.
    if (detail.value?.session_id === sessionId) audioPeaks.value = []
  }
}

function onAudioCanPlay() {
  audioReady.value = true
  audioError.value = ''
}

function onAudioError() {
  if (!audioUrl.value) return
  audioReady.value = false
  const expired = audioTicketExpires.value > 0
    && Math.floor(Date.now() / 1000) >= audioTicketExpires.value
  audioError.value = expired
    ? '录音播放地址已过期，请重新加载录音。'
    : '录音流加载失败，请检查录音文件后重新加载。'
}

async function playRange(start: number, end: number) {
  const now = Math.floor(Date.now() / 1000)
  if (audioError.value || !audioUrl.value || audioTicketExpires.value <= now + 30) {
    await loadReviewAudio(detail.value?.session_id ?? '', true)
  }
  await nextTick()
  if (!audioUrl.value) return
  reviewPlayer.value?.playRange(start * 1000, end * 1000)
}

async function playFullRecording() {
  const now = Math.floor(Date.now() / 1000)
  if (audioError.value || !audioUrl.value || audioTicketExpires.value <= now + 30) {
    await loadReviewAudio(detail.value?.session_id ?? '', true)
  }
  await nextTick()
  reviewPlayer.value?.seekToMs(0, true)
}

async function playCandidate(candidate: ExtractionCandidate) {
  focusedCandidateId.value = candidate.id
  await playRange(
    Math.max(0, candidate.started_at_ms / 1000),
    Math.max(0, candidate.ended_at_ms / 1000)
  )
}

async function retryAsr() {
  if (!detail.value) return
  busyId.value = 'asr'; errorMessage.value = ''; successMessage.value = ''
  try {
    await asrApi.retry(detail.value.session_id)
    successMessage.value = '服务端语音识别任务已提交。'
    await loadQueue(); await selectSession(detail.value.session_id, true)
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : '语音识别任务提交失败' }
  finally { busyId.value = '' }
}

async function enqueue() {
  if (!detail.value) return
  busyId.value = 'enqueue'
  try {
    const sessionId = detail.value.session_id
    const job = (await extractionApi.enqueue(sessionId)).data
    trackJob(job, currentQueueItem.value)
    await loadQueue(); await selectSession(sessionId, false, job.id)
    successMessage.value = '候选抽取任务已进入队列；系统会在完成后通知您。'
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : '抽取任务提交失败' }
  finally { busyId.value = '' }
}

async function classifyCurrentCandidates() {
  if (!detail.value?.job) return
  busyId.value = 'classify'
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const jobId = detail.value.job.id
    await extractionApi.classifyJob(jobId)
    await selectSession(detail.value.session_id, false, jobId)
    successMessage.value = '当前候选已使用生产分类模型完成预测，人工复核状态未改变。'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '候选分类失败'
  } finally {
    busyId.value = ''
  }
}

async function reviewCandidate(candidate: ExtractionCandidate, reviewStatus: 'accepted' | 'rejected') {
  const draft = drafts[candidate.id]
  if (!draft || !canEdit.value) return
  busyId.value = candidate.id; errorMessage.value = ''
  try {
    await extractionApi.review(candidate.id, {
      review_status: reviewStatus, ...draft, expected_updated_at: candidate.updated_at
    })
    clearDraft(candidate)
    await selectSession(selectedSessionId.value)
    focusRelative(0)
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : '候选复核保存失败' }
  finally { busyId.value = '' }
}

async function bulkAccept() {
  if (!detail.value || !canEdit.value || !pendingCount.value) return
  const confirmed = await confirmAction({
    title: '批量接受结构低风险候选',
    message: '系统将检查该版本的全部待复核候选，仅接受满足“原文可追溯、仅保守删除、时间有效”条件的记录。该操作不代表最终元认知编码，是否继续？',
    confirmText: '确认批量接受', tone: 'warning'
  })
  if (!confirmed) return
  busyId.value = 'bulk'
  try {
    const result = (await extractionApi.bulkAcceptLowRisk(detail.value.session_id)).data
    successMessage.value = `已接受 ${result.accepted} 条，保留 ${result.skipped} 条供逐条复核。`
    await selectSession(detail.value.session_id)
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : '批量接受失败' }
  finally { busyId.value = '' }
}

function useSegment(segmentId: string) {
  const segment = detail.value?.segments.find(item => item.id === segmentId)
  if (!segment) return
  Object.assign(addition, {
    source_transcript_segment_id: segment.id, original_text: segment.text,
    clean_text: segment.text, started_at_ms: segment.started_at_ms,
    ended_at_ms: segment.ended_at_ms
  })
  void playRange(segment.started_at_ms / 1000, segment.ended_at_ms / 1000)
}

async function addCandidate() {
  if (!detail.value || !canEdit.value || !addition.original_text.trim() || !addition.clean_text.trim()) return
  busyId.value = 'add'
  try {
    await extractionApi.addCandidate(detail.value.session_id, {
      ...addition, source_transcript_segment_id: addition.source_transcript_segment_id || null
    })
    addition.original_text = ''; addition.clean_text = ''
    await selectSession(detail.value.session_id)
    successMessage.value = '人工候选已补充并标记为已接受。'
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : '人工候选补充失败' }
  finally { busyId.value = '' }
}

async function completeReview() {
  if (!detail.value || !canEdit.value) return
  busyId.value = 'complete'
  try {
    await extractionApi.complete(detail.value.session_id)
    clearLockTimer(); await loadQueue(); await selectSession(detail.value.session_id)
    successMessage.value = '本次候选复核已完成，可以进入双人盲编批次。'
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : '无法完成复核' }
  finally { busyId.value = '' }
}

async function exportReviewResult() {
  if (!detail.value?.job || !detail.value.candidate_total) return
  const reviewComplete = currentJobStatus.value === 'reviewed' && pendingCount.value === 0
  if (!reviewComplete) {
    const confirmed = await confirmAction({
      title: '导出未完成复核快照',
      message: `当前仍有 ${pendingCount.value} 条候选待复核。导出文件会包含 pending 记录并明确标记“非最终结果”，不能作为最终复核数据使用。是否继续？`,
      confirmText: '仍然导出',
      tone: 'warning'
    })
    if (!confirmed) return
  }
  busyId.value = 'export'
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const response = await extractionApi.exportReviewResult(
      detail.value.session_id,
      detail.value.job.id
    )
    const url = URL.createObjectURL(response.data)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `候选复核${reviewComplete ? '最终结果' : '未完成快照'}_${detail.value.username}_${detail.value.task_title}_V${detail.value.job.generation_no}.csv`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
    successMessage.value = reviewComplete
      ? '当前抽取版本的最终候选复核结果已导出。'
      : '未完成复核快照已导出；文件内含待复核记录，不能视为最终结果。'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '候选复核结果导出失败'
  } finally {
    busyId.value = ''
  }
}

function focusRelative(delta: number) {
  const candidates = detail.value?.candidates ?? []
  if (!candidates.length) return
  const index = Math.max(0, candidates.findIndex(item => item.id === currentCandidate.value?.id))
  const target = candidates[Math.max(0, Math.min(candidates.length - 1, index + delta))]
  focusedCandidateId.value = target.id
  candidatePage.value = Math.floor(candidates.indexOf(target) / candidatePageSize.value) + 1
  nextTick(() => document.getElementById(`candidate-${target.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }))
}

function handleShortcut(event: KeyboardEvent) {
  const target = event.target as HTMLElement | null
  if (target?.matches('input, textarea, select, button, a, [contenteditable="true"]') || target?.closest('[role="dialog"]')) return
  if (event.key.toLowerCase() === 'j') { event.preventDefault(); focusRelative(1) }
  if (event.key.toLowerCase() === 'k') { event.preventDefault(); focusRelative(-1) }
  if (event.key.toLowerCase() === 'a' && currentCandidate.value && canEdit.value) {
    event.preventDefault(); void reviewCandidate(currentCandidate.value, 'accepted')
  }
  if (event.key.toLowerCase() === 'r' && currentCandidate.value && canEdit.value) {
    event.preventDefault(); void reviewCandidate(currentCandidate.value, 'rejected')
  }
  if (event.code === 'Space' && currentCandidate.value) {
    event.preventDefault(); void playCandidate(currentCandidate.value)
  }
}

watch(() => filters.keyword, () => {
  if (searchTimer !== null) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    if (page.value !== 1) page.value = 1
    else void loadQueue(true)
  }, 350)
})
watch([() => filters.class_group, () => filters.task_id, () => filters.status, pageSize], () => {
  if (page.value !== 1) page.value = 1
  else void loadQueue(true)
})
watch(page, () => void loadQueue(true))
watch(candidatePageSize, () => { candidatePage.value = 1 })
watch(
  () => currentTrackedTask.value
    ? `${currentTrackedTask.value.id}:${currentTrackedTask.value.status}:${currentTrackedTask.value.candidate_count}`
    : '',
  async value => {
    if (!value || !currentTrackedTask.value) return
    const task = currentTrackedTask.value
    if (!['reviewing', 'reviewed', 'failed'].includes(task.status)) return
    if (refreshedTerminalJobIds.has(task.id)) return
    refreshedTerminalJobIds.add(task.id)
    await loadQueue()
    if (selectedSessionId.value === task.session_id) {
      await selectSession(task.session_id, false, task.id)
    }
  }
)

onMounted(async () => {
  window.addEventListener('keydown', handleShortcut)
  const requestedSessionId = typeof route.query.session_id === 'string'
    ? route.query.session_id
    : ''
  const requestedJobId = typeof route.query.job_id === 'string'
    ? route.query.job_id
    : ''
  await loadQueue(!requestedSessionId)
  if (requestedSessionId) {
    await selectSession(requestedSessionId, false, requestedJobId)
  }
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleShortcut)
  if (searchTimer !== null) window.clearTimeout(searchTimer)
  void releaseCurrentLock()
  clearAudio()
})
</script>

<template>
  <div class="candidate-review-page">
    <AppPageHeader eyebrow="EVIDENCE VALIDATION" title="元认知候选复核" description="AI 高召回抽取后，结合权威转录和原始录音确认、修订、排除或补充证据。" />
    <div v-if="errorMessage" class="alert alert-danger">{{ errorMessage }}</div>
    <div v-if="successMessage" class="alert alert-success">{{ successMessage }}</div>

    <section class="filter-bar app-surface-card mb-3">
      <div><label class="form-label">学生</label><input v-model.trim="filters.keyword" class="form-control" placeholder="姓名或账号"></div>
      <div><label class="form-label">班级</label><select v-model="filters.class_group" class="form-select"><option value="">全部班级</option><option v-for="item in classGroups" :key="item">{{ item }}</option></select></div>
      <div><label class="form-label">任务</label><select v-model="filters.task_id" class="form-select"><option value="">全部任务</option><option v-for="item in taskOptions" :key="item.id" :value="item.id">{{ item.title }}</option></select></div>
      <div><label class="form-label">流程状态</label><select v-model="filters.status" class="form-select"><option value="">全部状态</option><option v-for="item in statusOptions" :key="item" :value="item">{{ statusText(item) }}</option></select></div>
      <div><label class="form-label">每页</label><select v-model.number="pageSize" class="form-select"><option :value="10">10</option><option :value="20">20</option><option :value="50">50</option></select></div>
    </section>

    <section class="batch-rerun-bar app-surface-card mb-3" aria-label="批量生成新抽取版本">
      <div>
        <strong>批量生成新抽取版本</strong>
        <span>已选择 {{ selectedRerunSessionIds.length }}/{{ MAX_BATCH_RERUN }} 条；仅可选择已有历史版本且当前未在处理的记录。</span>
      </div>
      <div class="batch-rerun-actions">
        <button class="btn btn-sm btn-outline-secondary" type="button" :disabled="!eligiblePageRerunIds.length" @click="toggleEligiblePageSelection">
          {{ allEligiblePageSelected ? '取消选择本页' : '选择本页可重跑项' }}
        </button>
        <button class="btn btn-sm btn-outline-secondary" type="button" :disabled="!selectedRerunSessionIds.length" @click="selectedRerunSessionIds = []">清空选择</button>
        <button class="btn btn-sm btn-primary" type="button" :disabled="!selectedRerunSessionIds.length || batchRerunBusy" @click="batchRerunExtraction">
          <span v-if="batchRerunBusy" class="spinner-border spinner-border-sm me-1"></span>
          生成所选新版本
        </button>
      </div>
    </section>

    <section v-if="currentBatchSummary.total" class="batch-progress app-surface-card mb-3" aria-live="polite">
      <div class="batch-progress-heading">
        <div><strong>本次批量抽取进度</strong><span>{{ currentBatchSummary.completed + currentBatchSummary.failed }}/{{ currentBatchSummary.total }} 已结束</span></div>
        <div class="batch-progress-counts">
          <span class="is-completed">完成 {{ currentBatchSummary.completed }}</span>
          <span class="is-running">处理中 {{ currentBatchSummary.running }}</span>
          <span class="is-queued">排队/重试 {{ currentBatchSummary.queued }}</span>
          <span class="is-failed">失败 {{ currentBatchSummary.failed }}</span>
        </div>
      </div>
      <div class="progress" role="progressbar" aria-label="批量抽取完成进度" :aria-valuenow="currentBatchSummary.completed + currentBatchSummary.failed" aria-valuemin="0" :aria-valuemax="currentBatchSummary.total">
        <div class="progress-bar" :style="{ width: `${((currentBatchSummary.completed + currentBatchSummary.failed) / currentBatchSummary.total) * 100}%` }"></div>
      </div>
      <details class="batch-progress-details">
        <summary>查看各任务状态</summary>
        <div class="batch-progress-items">
          <div v-for="task in currentBatchTasks" :key="task.id">
            <span>{{ task.user_name || '未知学生' }} · {{ task.task_title || '未知任务' }} · V{{ task.generation_no }}</span>
            <strong>{{ statusText(`extraction_${task.status}`) }}<template v-if="task.status === 'reviewing'"> · {{ task.candidate_count }} 条候选</template></strong>
          </div>
        </div>
      </details>
    </section>

    <div class="review-layout">
      <aside class="queue-panel app-surface-card">
        <div class="queue-summary">共 {{ total }} 次任务记录 · 按账号和任务归组</div>
        <div v-if="loading" class="p-4 text-center text-muted"><span class="spinner-border spinner-border-sm me-2"></span>加载中</div>
        <section v-for="group in queueGroups" :key="group.user.user_id" class="queue-account">
          <button class="queue-account-header" type="button" :aria-expanded="isQueueUserExpanded(group.user.user_id)" @click="toggleQueueUser(group.user.user_id)">
            <span class="queue-account-avatar">{{ group.user.user_name.slice(0, 1) }}</span>
            <span class="queue-account-copy"><strong>{{ group.user.user_name }}</strong><small>{{ group.user.username }} · {{ group.user.class_group || '未分班' }}</small></span>
            <span class="queue-account-count">{{ group.itemCount }}</span>
            <i class="bi" :class="isQueueUserExpanded(group.user.user_id) ? 'bi-chevron-up' : 'bi-chevron-down'"></i>
          </button>
          <div v-if="isQueueUserExpanded(group.user.user_id)" class="queue-account-items">
            <section v-for="taskGroup in group.taskGroups" :key="taskGroup.taskId" class="queue-task-group">
              <div class="queue-task-heading">
                <span><i class="bi bi-list-task"></i>{{ taskGroup.taskTitle }}</span>
                <small>{{ taskGroup.items.length }} 次</small>
              </div>
              <div v-for="item in taskGroup.items" :key="item.session_id" class="queue-item-shell" :class="{ active: item.session_id === selectedSessionId }">
                <label class="queue-select" :title="canRerunQueueItem(item) ? '选择后批量生成新版本' : '当前记录不可批量重跑'" @click.stop>
                  <input
                    type="checkbox"
                    :checked="selectedRerunSessionIds.includes(item.session_id)"
                    :disabled="!canRerunQueueItem(item)"
                    :aria-label="`选择 ${item.user_name} ${item.task_title} ${formatCompletionTime(item)}`"
                    @change="toggleRerunSelection(item.session_id, ($event.target as HTMLInputElement).checked)"
                  >
                </label>
                <button class="queue-item" type="button" @click="selectSession(item.session_id, false, '')">
                  <span class="queue-item-heading"><strong :title="completionTimeTitle(item)"><i class="bi bi-clock-history"></i>{{ formatCompletionTime(item) }}</strong><small>{{ statusLabel(item) }}</small></span>
                  <span class="queue-item-meta">第 {{ item.sequence_no }} 项任务 · 候选 {{ item.candidate_count }} · 待复核 {{ item.pending_count }}</span>
                </button>
              </div>
            </section>
          </div>
        </section>
        <div v-if="!loading && !queue.length" class="p-4 text-center text-muted">没有符合条件的记录</div>
        <nav class="queue-pagination" aria-label="候选复核分页">
          <button class="btn btn-sm btn-outline-secondary" :disabled="page <= 1" @click="page -= 1">上一页</button>
          <span>{{ page }} / {{ totalPages }}</span>
          <button class="btn btn-sm btn-outline-secondary" :disabled="page >= totalPages" @click="page += 1">下一页</button>
        </nav>
      </aside>

      <main class="detail-panel">
        <div v-if="detailLoading" class="app-surface-card p-5 text-center"><span class="spinner-border text-primary"></span></div>
        <template v-else-if="detail">
          <section class="app-surface-card p-4 mb-3">
            <div class="d-flex flex-wrap justify-content-between gap-3 align-items-start">
              <div class="extraction-heading-copy"><h5 class="mb-1">{{ detail.user_name }} · {{ detail.task_title }}</h5><div class="small text-muted">账号 {{ detail.username }}<template v-if="detail.transcript_version_no"> · 权威转录 v{{ detail.transcript_version_no }} · {{ detail.transcript_source }}</template><template v-else> · 尚未生成权威转录</template></div><div v-if="detail.job" class="small mt-2">抽取版本 V{{ detail.job.generation_no }} · 模型 {{ detail.job.model }} · 抽取器 {{ detail.job.extractor_version }} · 提示词 {{ detail.job.prompt_version }}</div></div>
              <div class="extraction-version-actions">
                <select v-if="detail.job_history.length" v-model="selectedJobId" class="form-select form-select-sm" aria-label="查看候选抽取历史版本" @change="selectSession(detail.session_id, false, selectedJobId)">
                  <option v-for="job in detail.job_history" :key="job.id" :value="job.id">V{{ job.generation_no }} · {{ statusText(`extraction_${displayedJobStatus(job)}`) }} · {{ formatDate(job.created_at) }}</option>
                </select>
                <div v-if="detail.job" class="extraction-status-card" :class="`is-${currentJobStatus}`" role="status" aria-live="polite">
                  <span class="extraction-status-icon">
                    <span v-if="['queued', 'running', 'retry_wait'].includes(currentJobStatus)" class="spinner-border spinner-border-sm"></span>
                    <i v-else-if="currentJobStatus === 'failed'" class="bi bi-exclamation-triangle-fill"></i>
                    <i v-else class="bi bi-check-circle-fill"></i>
                  </span>
                  <div>
                    <strong>抽取版本 V{{ detail.job.generation_no }} · {{ statusText(`extraction_${currentJobStatus}`) }}</strong>
                    <span v-if="currentJobStatus === 'queued'">任务已进入队列，系统会自动开始处理。</span>
                    <span v-else-if="currentJobStatus === 'running'">AI 正在分析权威转录，完成后将自动刷新候选。</span>
                    <span v-else-if="currentJobStatus === 'retry_wait'">模型请求暂时失败，正在等待自动重试（{{ currentTrackedTask?.retry_count ?? detail.job.retry_count }}/{{ currentTrackedTask?.max_retries ?? detail.job.max_retries }}）。</span>
                    <span v-else-if="currentJobStatus === 'reviewing'">已生成 {{ currentJobCandidateCount }} 条候选，等待人工听取录音并复核。</span>
                    <span v-else-if="currentJobStatus === 'reviewed'">该版本的候选已经完成人工复核。</span>
                    <span v-else-if="currentJobStatus === 'failed'" class="text-danger d-block">
                      <strong>失败原因：</strong>{{ currentTrackedTask?.error_message || detail.job.error_message || '抽取未能完成，请检查模型服务后重试。' }}
                    </span>
                    <span v-else>该版本已作为历史记录保留。</span>
                  </div>
                </div>
                <button v-if="detail.transcript_version_id && !detail.job" class="btn btn-primary" :disabled="busyId === 'enqueue'" @click="enqueue">开始候选抽取</button>
                <button v-else-if="detail.transcript_version_id && currentJobStatus === 'failed'" class="btn btn-danger" :disabled="busyId === 'rerun'" @click="rerunExtraction"><i class="bi bi-arrow-clockwise me-1"></i>重新抽取</button>
                <button v-else-if="detail.transcript_version_id" class="btn btn-outline-primary" :disabled="busyId === 'rerun' || ['queued', 'running', 'retry_wait'].includes(latestJob ? displayedJobStatus(latestJob) : '')" @click="rerunExtraction"><i class="bi bi-arrow-repeat me-1"></i>生成新抽取版本</button>
                <button v-if="detail.job && detail.candidate_total" class="btn btn-outline-secondary" :disabled="busyId === 'classify' || ['queued','running','retry_wait'].includes(currentJobStatus)" @click="classifyCurrentCandidates"><span v-if="busyId === 'classify'" class="spinner-border spinner-border-sm me-1"></span><i v-else class="bi bi-cpu me-1"></i>使用当前模型分类</button>
              </div>
            </div>
            <div v-if="detail.job?.status === 'reviewing'" class="lease-banner mt-3" :class="canEdit ? 'is-owned' : 'is-locked'">
              <i class="bi" :class="canEdit ? 'bi-unlock-fill' : 'bi-lock-fill'"></i>
              <span v-if="canEdit">您已取得编辑权，系统每 2 分钟自动续租。</span>
              <span v-else>该任务正由 {{ detail.lock_owner_name || '另一名复核员' }} 编辑；当前页面为只读。</span>
            </div>

            <div class="audio-review mt-3">
              <div class="audio-review-heading w-100">
                <div><strong>完整录音二次复核</strong><div class="small text-muted">候选播放会在片段结束时间自动停止；单击波形可自由定位。</div></div>
                <button v-if="audioUrl" class="btn btn-sm btn-outline-primary" type="button" :disabled="audioLoading" @click="playFullRecording">
                  <i class="bi bi-play-fill me-1"></i>播放完整录音
                </button>
              </div>
              <div v-if="audioLoading" class="audio-loading w-100" aria-live="polite">
                <span class="spinner-border spinner-border-sm text-primary"></span>
                <span>正在准备流式录音与波形……</span>
              </div>
              <div v-if="audioError" class="alert alert-warning d-flex flex-wrap align-items-center justify-content-between gap-2 w-100 mb-0">
                <span><i class="bi bi-exclamation-triangle me-2"></i>{{ audioError }}</span>
                <button class="btn btn-sm btn-outline-primary" type="button" @click="loadReviewAudio(detail.session_id, true)">重新加载录音</button>
              </div>
              <AudioTranscriptPlayer
                v-if="audioUrl"
                ref="reviewPlayer"
                class="w-100"
                :src="audioUrl"
                :segments="candidateAudioSegments"
                :peaks="audioPeaks"
                :duration-seconds="audioDuration"
                title="完整录音与候选片段范围"
                @ready="onAudioCanPlay"
                @error="onAudioError"
              />
              <div v-if="audioUrl && !audioLoading && !audioError" class="audio-readiness" aria-live="polite">
                <i class="bi" :class="audioReady ? 'bi-check-circle-fill' : 'bi-hourglass-split'"></i>
                {{ audioReady ? '录音已就绪' : '正在缓冲录音' }}
              </div>
              <span v-else-if="!audioLoading && !audioError" class="badge text-bg-light">暂无可播放录音</span>
            </div>
          </section>

          <section v-if="!detail.transcript_version_id" class="app-surface-card p-4 mb-3 pipeline-blocked">
            <div class="pipeline-icon"><i class="bi bi-soundwave"></i></div><div><h5>候选抽取尚未开始</h5><p class="text-muted mb-2">必须先由服务端 ASR 生成权威转录。</p><div class="small mb-3"><strong>当前识别状态：</strong>{{ pipelineStatusLabel }}</div><div v-if="detail.asr_error_message" class="alert alert-warning"><strong>{{ detail.asr_error_code || 'ASR 失败' }}</strong><br>{{ detail.asr_error_message }}</div><button class="btn btn-primary" :disabled="busyId === 'asr' || ['queued', 'preparing_audio', 'transcribing'].includes(detail.asr_status)" @click="retryAsr">{{ detail.asr_status === 'not_created' ? '开始服务端识别' : '重新识别' }}</button></div>
          </section>

          <section v-else-if="detail.job && ['queued', 'running', 'retry_wait'].includes(currentJobStatus)" class="app-surface-card p-5 text-center"><span class="spinner-border text-primary mb-3"></span><h5>AI 正在抽取候选证据</h5><p class="text-muted mb-0">可以离开当前页面，完成后系统仍会通过消息中心通知您。</p></section>

          <template v-else-if="detail.transcript_version_id">
            <section class="app-surface-card p-4 mb-3">
              <div class="candidate-toolbar">
                <div><h5 class="mb-1">候选片段</h5><span class="small text-muted">共 {{ detail.candidate_total }} 条 · 已接受 {{ acceptedCount }} · 待复核 {{ pendingCount }} · 本页低风险 {{ lowRiskCount }}</span></div>
                <div class="d-flex flex-wrap gap-2"><span class="shortcut-hint">J/K 切换 · A 接受 · R 排除 · 空格试听</span><button class="btn btn-outline-primary" :disabled="!canEdit || !pendingCount || busyId === 'bulk'" @click="bulkAccept">批量检查并接受低风险候选</button></div>
              </div>
              <div v-if="detail.candidates.length" class="candidate-pagination mb-3">
                <div class="d-flex align-items-center gap-2">
                  <span>每页</span>
                  <select v-model.number="candidatePageSize" class="form-select form-select-sm candidate-page-size" aria-label="每页候选数量" @change="changeCandidatePageSize"><option :value="5">5</option><option :value="10">10</option><option :value="20">20</option></select>
                  <span>条</span>
                </div>
                <div class="d-flex align-items-center gap-2">
                  <button class="btn btn-sm btn-outline-secondary" :disabled="candidatePage <= 1 || detailLoading" @click="loadCandidatePage(candidatePage - 1)">上一页</button>
                  <span>第 {{ candidatePage }} / {{ candidateTotalPages }} 页</span>
                  <button class="btn btn-sm btn-outline-secondary" :disabled="candidatePage >= candidateTotalPages || detailLoading" @click="loadCandidatePage(candidatePage + 1)">下一页</button>
                </div>
              </div>
              <div v-if="!detail.candidates.length" class="text-center text-muted py-4">AI 未返回候选，可在下方听取录音后人工补充。</div>
              <article v-for="candidate in visibleCandidates" :id="`candidate-${candidate.id}`" :key="candidate.id" class="candidate-card" :class="[`is-${candidate.review_status}`, { 'is-focused': focusedCandidateId === candidate.id }]" @click="focusedCandidateId = candidate.id">
                <div class="d-flex flex-wrap justify-content-between gap-2 mb-2"><span><strong>#{{ candidate.sequence_no }}</strong> · {{ candidate.source_type === 'human' ? '人工补充' : 'AI 候选' }} <span v-if="candidate.is_low_risk" class="badge text-bg-info ms-1">低风险候选</span></span><div class="d-flex flex-wrap gap-2"><button class="btn btn-sm btn-outline-secondary" :disabled="historyBusyId === candidate.id" @click.stop="toggleCandidateHistory(candidate.id)"><i class="bi bi-clock-history me-1"></i>{{ candidateHistories[candidate.id] ? '收起历史' : '操作历史' }}</button><button class="btn btn-sm btn-outline-primary" :disabled="!audioUrl" @click.stop="playCandidate(candidate)"><i class="bi bi-play-fill me-1"></i>试听本片段 {{ Math.max(0, Math.round((candidate.ended_at_ms - candidate.started_at_ms) / 100) / 10) }} 秒</button></div></div>
                <div v-if="candidate.classifier_version" class="classifier-result" :class="{ 'is-warning': candidate.predicted_label === 0 || (candidate.prediction_confidence !== null && candidate.prediction_confidence < .75) || candidate.classification_status === 'classified_with_fallback' }">
                  <span><i class="bi bi-cpu me-1"></i>分类模型 {{ candidate.classifier_version }}</span>
                  <strong>{{ classifierLabel(candidate) }}</strong>
                  <span v-if="candidate.prediction_confidence !== null">置信度 {{ (candidate.prediction_confidence * 100).toFixed(1) }}%</span>
                  <span v-else>置信度：该分类器不提供概率</span>
                  <small>{{ classificationStatusLabel(candidate) }} · {{ predictionSourceLabel(candidate) }} · 仅供人机一致性比较，不替代人工结论</small>
                </div>
                <div v-else-if="candidate.classification_error" class="alert alert-warning py-2 px-3 small"><strong>{{ classificationStatusLabel(candidate) }}</strong>：{{ candidate.classification_error }}。候选文本和人工复核流程均已保留，可稍后重试。</div>
                <div v-else-if="candidate.classification_status === 'not_active'" class="alert alert-secondary py-2 px-3 small">尚未启用生产分类模型。候选仍可正常人工复核。</div>
                <label class="form-label small">权威转录原话</label><textarea v-model="drafts[candidate.id].original_text" class="form-control mb-2" rows="2" :disabled="!canEdit" @input="saveDraft(candidate)"></textarea>
                <label class="form-label small">保守清洗文本（不得改写含义）</label><textarea v-model="drafts[candidate.id].clean_text" class="form-control mb-2" rows="2" :disabled="!canEdit" @input="saveDraft(candidate)"></textarea>
                <input v-model="drafts[candidate.id].review_note" class="form-control mb-2" placeholder="复核备注（可选）" :disabled="!canEdit" @input="saveDraft(candidate)">
                <div class="draft-status mb-2"><i class="bi bi-cloud-check"></i>{{ draftSavedAt[candidate.id] ? '草稿已自动保存到本机' : '修改后自动保存草稿' }}</div>
                <div class="d-flex flex-wrap gap-2"><button class="btn btn-success" :disabled="!canEdit || busyId === candidate.id" @click.stop="reviewCandidate(candidate, 'accepted')">接受并保存</button><button class="btn btn-outline-danger" :disabled="!canEdit || busyId === candidate.id" @click.stop="reviewCandidate(candidate, 'rejected')">排除但保留记录</button><span class="badge align-self-center" :class="candidate.review_status === 'accepted' ? 'text-bg-success' : candidate.review_status === 'rejected' ? 'text-bg-secondary' : 'text-bg-warning'">{{ candidate.review_status }}</span></div>
                <div v-if="candidateHistories[candidate.id]" class="candidate-history mt-3" @click.stop>
                  <div v-if="!candidateHistories[candidate.id].length" class="small text-muted">尚无人工修改记录。</div>
                  <article v-for="revision in candidateHistories[candidate.id]" :key="revision.id" class="revision-row">
                    <div class="revision-heading"><strong>{{ revisionActionLabel(revision.action) }}</strong><span>{{ revision.actor_name || '系统' }} · {{ formatDate(revision.created_at) }}</span></div>
                    <div class="revision-diff"><div><small>修改前 · 原始证据</small><p>{{ snapshotText(revision.before_snapshot, 'original_text') }}</p><small>保守清洗文本</small><p>{{ snapshotText(revision.before_snapshot, 'clean_text') }}</p></div><i class="bi bi-arrow-right"></i><div><small>修改后 · 原始证据</small><p>{{ snapshotText(revision.after_snapshot, 'original_text') }}</p><small>保守清洗文本</small><p>{{ snapshotText(revision.after_snapshot, 'clean_text') }}</p></div></div>
                  </article>
                </div>
              </article>
            </section>

            <section class="app-surface-card p-4 mb-3"><h5>人工补充遗漏（新增独立候选）</h5><p class="small text-muted">用于补录 AI 未提取到的元认知片段，不会修改或覆盖上方 AI 候选。点击转录片段会同步播放对应录音范围。</p><div class="segment-strip mb-3"><button v-for="segment in detail.segments" :key="segment.id" class="btn btn-sm btn-outline-secondary" @click="useSegment(segment.id)">片段 {{ (segment.segment_no ?? 0) + 1 }}</button></div><textarea v-model="addition.original_text" class="form-control mb-2" rows="2" placeholder="原始证据文本" :disabled="!canEdit"></textarea><textarea v-model="addition.clean_text" class="form-control mb-2" rows="2" placeholder="保守清洗文本" :disabled="!canEdit"></textarea><input v-model="addition.review_note" class="form-control mb-3" placeholder="补充原因" :disabled="!canEdit"><button class="btn btn-primary" :disabled="!canEdit || busyId === 'add' || !addition.original_text || !addition.clean_text" @click="addCandidate">新增为已接受候选</button></section>

            <section class="app-surface-card p-4"><div class="d-flex flex-wrap justify-content-between align-items-center gap-3"><div><strong>{{ currentJobStatus === 'reviewed' ? '候选复核已完成' : '完成候选复核' }}</strong><div class="small text-muted">{{ currentJobStatus === 'reviewed' ? '可导出当前抽取版本全部已接受、已排除决定及其追溯字段。' : '尚未完成时也可导出当前快照，但文件会警告其不是最终复核结果。' }}</div></div><div class="d-flex flex-wrap gap-2"><button v-if="detail.candidate_total" class="btn btn-outline-primary" :disabled="busyId === 'export'" @click="exportReviewResult"><span v-if="busyId === 'export'" class="spinner-border spinner-border-sm me-1"></span><i v-else class="bi bi-file-earmark-spreadsheet me-1"></i>{{ currentJobStatus === 'reviewed' ? '导出最终复核结果' : '导出当前复核快照' }}</button><button v-if="currentJobStatus !== 'reviewed'" class="btn btn-primary" :disabled="!canEdit || pendingCount > 0 || acceptedCount === 0 || busyId === 'complete'" @click="completeReview">确认完成复核</button></div></div></section>
          </template>
        </template>
        <div v-else class="app-surface-card p-5 text-center text-muted">请从左侧选择一次测评</div>
      </main>
    </div>
  </div>
</template>

<style scoped>
.candidate-review-page { max-width: 1500px; margin: 0 auto; }
.filter-bar { display: grid; grid-template-columns: minmax(190px, 1.3fr) repeat(3, minmax(150px, 1fr)) 100px; gap: .75rem; padding: 1rem; align-items: end; }
.filter-bar .form-label { margin-bottom: .3rem; font-size: .78rem; font-weight: 650; }
.batch-rerun-bar { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: .85rem 1rem; }
.batch-rerun-bar > div:first-child { display: grid; gap: .2rem; }
.batch-rerun-bar span { color: var(--bs-secondary-color); font-size: .76rem; }
.batch-rerun-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: .5rem; }
.batch-progress { display: grid; gap: .75rem; padding: 1rem; }
.batch-progress-heading { display: flex; flex-wrap: wrap; justify-content: space-between; gap: .75rem; }
.batch-progress-heading > div:first-child { display: grid; gap: .15rem; }
.batch-progress-heading > div:first-child span { color: var(--bs-secondary-color); font-size: .78rem; }
.batch-progress-counts { display: flex; flex-wrap: wrap; gap: .45rem; }
.batch-progress-counts span { padding: .25rem .55rem; border-radius: 999px; font-size: .72rem; font-weight: 700; }
.batch-progress-counts .is-completed { color: var(--color-success); background: var(--color-success-soft); }
.batch-progress-counts .is-running { color: var(--color-primary); background: var(--color-primary-soft); }
.batch-progress-counts .is-queued { color: var(--color-warning); background: var(--color-warning-soft); }
.batch-progress-counts .is-failed { color: var(--color-danger); background: var(--color-danger-soft); }
.batch-progress-details summary { cursor: pointer; color: var(--bs-primary); font-size: .78rem; font-weight: 700; }
.batch-progress-items { display: grid; gap: .35rem; margin-top: .65rem; }
.batch-progress-items > div { display: flex; flex-wrap: wrap; justify-content: space-between; gap: .5rem; padding: .55rem .7rem; border-radius: .65rem; background: var(--bs-tertiary-bg); font-size: .76rem; }
.batch-progress-items strong { color: var(--bs-secondary-color); }
.review-layout { display: grid; grid-template-columns: 310px minmax(0, 1fr); gap: 1rem; align-items: start; }
.queue-panel { position: sticky; top: 1rem; max-height: calc(100dvh - 2rem); overflow: auto; }
.queue-summary { position: sticky; top: 0; z-index: 1; padding: .8rem 1rem; border-bottom: 1px solid var(--bs-border-color); background: var(--bs-body-bg); font-size: .82rem; color: var(--bs-secondary-color); }
.queue-account { margin: .65rem; overflow: hidden; border: 1px solid var(--bs-border-color); border-radius: .9rem; background: var(--bs-body-bg); }
.queue-account-header { display: grid; grid-template-columns: 36px minmax(0, 1fr) auto auto; align-items: center; gap: .65rem; width: 100%; padding: .8rem; border: 0; background: transparent; text-align: left; }
.queue-account-header:hover { background: rgba(79, 70, 229, .045); }
.queue-account-avatar { display: grid; place-items: center; width: 36px; height: 36px; border-radius: 50%; color: var(--color-primary); background: var(--color-primary-soft); font-weight: 700; }
.queue-account-copy { display: grid; min-width: 0; }
.queue-account-copy strong, .queue-account-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.queue-account-copy small { color: var(--bs-secondary-color); }
.queue-account-count { min-width: 26px; padding: .15rem .4rem; border-radius: 999px; color: var(--color-primary); background: var(--color-primary-soft); text-align: center; font-size: .75rem; }
.queue-account-items { border-top: 1px solid var(--bs-border-color); }
.queue-task-group + .queue-task-group { border-top: 1px solid var(--bs-border-color); }
.queue-task-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: .5rem; padding: .65rem .8rem; color: var(--color-primary); background: var(--color-primary-soft); font-size: .76rem; font-weight: 700; }
.queue-task-heading span { min-width: 0; }
.queue-task-heading i { margin-right: .35rem; }
.queue-task-heading small { flex: 0 0 auto; color: var(--bs-secondary-color); font-weight: 600; }
.queue-item-shell { display: grid; grid-template-columns: 34px minmax(0, 1fr); align-items: stretch; border-bottom: 1px solid var(--bs-border-color); transition: background-color .18s ease, box-shadow .18s ease; }
.queue-item-shell:last-child { border-bottom: 0; }
.queue-item-shell.active { background: rgba(79, 70, 229, .1); box-shadow: inset 3px 0 var(--bs-primary); }
.queue-select { display: grid; place-items: center; margin: 0; cursor: pointer; }
.queue-select input { width: 1rem; height: 1rem; accent-color: var(--bs-primary); }
.queue-select:has(input:disabled) { cursor: not-allowed; opacity: .45; }
.queue-item { display: grid; gap: .3rem; width: 100%; padding: .8rem 1rem .8rem .25rem; border: 0; background: transparent; text-align: left; transition: background-color .18s ease; }
.queue-item:hover { background: rgba(79, 70, 229, .05); }
.queue-item-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: .5rem; }
.queue-item-heading strong { color: var(--bs-body-color); font-size: .76rem; font-weight: 650; }
.queue-item-heading strong i { margin-right: .35rem; color: var(--bs-secondary-color); }
.queue-item-heading small { flex: 0 0 auto; color: var(--bs-secondary-color); font-size: .7rem; }
.queue-item-meta { color: var(--bs-secondary-color); font-size: .72rem; }
.queue-pagination { position: sticky; bottom: 0; display: flex; justify-content: space-between; align-items: center; gap: .5rem; padding: .75rem; border-top: 1px solid var(--bs-border-color); background: var(--bs-body-bg); font-size: .8rem; }
.audio-review { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: .75rem; padding: 1rem; border-radius: 1rem; background: var(--bs-tertiary-bg); }
.audio-review-heading { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: .75rem; }
.extraction-heading-copy { flex: 1 1 420px; min-width: 0; }
.extraction-version-actions { display: grid; justify-items: stretch; flex: 0 1 360px; gap: .55rem; width: min(100%, 360px); }
.extraction-version-actions .form-select { width: 100%; min-width: 0; }
.extraction-version-actions > .btn { justify-self: end; }
.extraction-status-card {
  --status-color: var(--color-text-secondary);
  --status-border: var(--color-border);
  --status-bg: var(--color-surface-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: .65rem;
  width: 100%;
  min-height: 68px;
  padding: .7rem .75rem;
  border: 1px solid var(--status-border);
  border-radius: .75rem;
  color: var(--status-color);
  background: var(--status-bg);
  text-align: center;
}
.extraction-status-card > div { display: grid; align-content: center; gap: .2rem; min-width: 0; text-align: center; }
.extraction-status-card > div strong { font-size: .82rem; line-height: 1.3; }
.extraction-status-card > div span { color: inherit; font-size: .75rem; line-height: 1.45; opacity: .82; }
.extraction-status-icon { display: grid; place-items: center; flex: 0 0 30px; width: 30px; height: 30px; border-radius: 50%; color: inherit; background: var(--color-surface); }
.extraction-status-card.is-queued { --status-color: var(--color-text-secondary); --status-border: var(--color-border); --status-bg: var(--color-surface-subtle); }
.extraction-status-card.is-running { --status-color: var(--color-primary); --status-border: var(--color-primary); --status-bg: var(--color-primary-soft); }
.extraction-status-card.is-retry_wait { --status-color: var(--color-warning); --status-border: var(--color-warning); --status-bg: var(--color-warning-soft); }
.extraction-status-card.is-reviewing { --status-color: var(--color-success); --status-border: var(--color-success); --status-bg: var(--color-success-soft); }
.extraction-status-card.is-reviewed { --status-color: var(--color-success); --status-border: var(--color-success); --status-bg: var(--color-success-soft); }
.extraction-status-card.is-failed { --status-color: var(--color-danger); --status-border: var(--color-danger); --status-bg: var(--color-danger-soft); }
.extraction-status-card.is-superseded { --status-color: var(--color-text-muted); --status-border: var(--color-border); --status-bg: var(--color-surface-subtle); }
.audio-review audio { width: 100%; height: 38px; }
.audio-loading { display: flex; align-items: center; gap: .65rem; min-height: 44px; color: var(--bs-secondary-color); }
.audio-readiness { display: inline-flex; align-items: center; gap: .35rem; color: var(--bs-secondary-color); font-size: .74rem; }
.audio-readiness .bi-check-circle-fill { color: var(--bs-success); }
.waveform { display: block; width: 100%; height: 82px; border-radius: .65rem; background: var(--color-surface); cursor: crosshair; }
.lease-banner { display: flex; align-items: center; gap: .6rem; padding: .7rem .9rem; border-radius: .7rem; font-size: .85rem; }
.lease-banner.is-owned { color: var(--color-success); background: var(--color-success-soft); }
.lease-banner.is-locked { color: var(--color-warning); background: var(--color-warning-soft); }
.candidate-toolbar { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 1rem; margin-bottom: 1rem; }
.candidate-pagination { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: .75rem; padding: .65rem .75rem; border-radius: .75rem; background: var(--bs-tertiary-bg); color: var(--bs-secondary-color); font-size: .8rem; }
.candidate-page-size { width: 72px; }
.shortcut-hint { align-self: center; font-size: .75rem; color: var(--bs-secondary-color); }
.candidate-card { padding: 1rem; margin-bottom: 1rem; border: 1px solid var(--bs-border-color); border-left-width: 4px; border-radius: 1rem; transition: box-shadow .18s ease, border-color .18s ease; }
.candidate-card.is-focused { box-shadow: 0 0 0 3px rgba(79,70,229,.12); }
.candidate-card.is-accepted { border-left-color: var(--bs-success); }
.candidate-card.is-rejected { border-left-color: var(--bs-secondary); opacity: .8; }
.candidate-card.is-pending { border-left-color: var(--bs-warning); }
.classifier-result { display: flex; flex-wrap: wrap; align-items: center; gap: .45rem .8rem; margin-bottom: .8rem; padding: .65rem .75rem; border: 1px solid var(--color-primary); border-radius: .75rem; color: var(--color-primary); background: var(--color-primary-soft); font-size: .78rem; }
.classifier-result.is-warning { color: var(--color-warning); border-color: var(--color-warning); background: var(--color-warning-soft); }
.classifier-result small { flex-basis: 100%; color: var(--color-text-muted); }
.draft-status { color: var(--bs-secondary-color); font-size: .72rem; }
.draft-status i { margin-right: .35rem; }
.candidate-history { display: grid; gap: .65rem; padding: .8rem; border-radius: .8rem; background: var(--bs-tertiary-bg); }
.revision-row { display: grid; gap: .55rem; padding: .7rem; border: 1px solid var(--bs-border-color); border-radius: .7rem; background: var(--bs-body-bg); }
.revision-heading { display: flex; flex-wrap: wrap; justify-content: space-between; gap: .5rem; font-size: .8rem; }
.revision-heading span { color: var(--bs-secondary-color); }
.revision-diff { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); align-items: center; gap: .7rem; }
.revision-diff small { color: var(--bs-secondary-color); }
.revision-diff p { margin: .2rem 0 0; white-space: pre-wrap; }
.segment-strip { display: flex; gap: .5rem; overflow-x: auto; padding-bottom: .35rem; }
.pipeline-blocked { display: flex; gap: 1rem; align-items: flex-start; }
.pipeline-icon { display: grid; place-items: center; flex: 0 0 48px; width: 48px; height: 48px; border-radius: 14px; color: var(--bs-primary); background: rgba(79,70,229,.1); font-size: 1.3rem; }
@media (max-width: 1199.98px) { .filter-bar { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 991.98px) { .review-layout { grid-template-columns: 1fr; } .queue-panel { position: static; max-height: 390px; } .filter-bar { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 575.98px) { .filter-bar { grid-template-columns: 1fr; } .batch-rerun-bar { align-items: stretch; flex-direction: column; } .batch-rerun-actions, .batch-rerun-actions .btn { width: 100%; } .candidate-toolbar .btn, .audio-review-heading .btn { width: 100%; } .shortcut-hint { display: none; } .extraction-version-actions, .extraction-version-actions .form-select, .extraction-version-actions .btn { width: 100%; min-width: 0; } .revision-diff { grid-template-columns: 1fr; } .revision-diff > i { transform: rotate(90deg); justify-self: center; } }
</style>
