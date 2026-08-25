<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  asrApi,
  type AsrReviewQueueItem,
  type AsrSessionStatus,
  type TranscriptCorrectionSegment,
  type TranscriptVersion
} from '../api/asr'
import { extractionApi } from '../api/extraction'
import { confirmAction, notify } from '../composables/useUiFeedback'
import AppMetricPill from '../components/ui/AppMetricPill.vue'
import AppPageHeader from '../components/ui/AppPageHeader.vue'
import AudioTranscriptPlayer from '../components/audio/AudioTranscriptPlayer.vue'
import { parseApiDate } from '../utils/datetime'

const route = useRoute()
const router = useRouter()
const queue = ref<AsrReviewQueueItem[]>([])
const selectedSessionId = ref('')
const selectedStatus = ref<AsrSessionStatus | null>(null)
const versions = ref<TranscriptVersion[]>([])
const selectedVersionId = ref('')
const editableSegments = ref<TranscriptCorrectionSegment[]>([])
const isLoading = ref(true)
const detailLoading = ref(false)
const saving = ref(false)
const approving = ref(false)
const retrying = ref(false)
const isDirty = ref(false)
const errorMessage = ref('')
const successMessage = ref('')
const studentSearch = ref('')
const FILTER_STORAGE_KEY = 'transcript-review-status-filter'
const allowedQueueFilters = new Set([
  'attention', '', 'completed', 'manually_transcribed', 'queued',
  'preparing_audio', 'transcribing', 'retry_wait', 'failed', 'waiting_configuration'
])
const routeFilter: string | null = typeof route.query.asr_status === 'string'
  ? (route.query.asr_status === 'all' ? '' : route.query.asr_status)
  : null
const storedFilter = sessionStorage.getItem(FILTER_STORAGE_KEY) ?? ''
const queueStatusFilter = ref(
  routeFilter !== null && allowedQueueFilters.has(routeFilter)
    ? routeFilter
    : allowedQueueFilters.has(storedFilter) ? storedFilter : 'attention'
)
const queuePage = ref(1)
const queuePageSize = ref(20)
const queueTotal = ref(0)
const selectedStudentIds = ref<string[]>([])
const batchRetrying = ref(false)
const manualEntryMode = ref(false)
const deletingFailedAudio = ref(false)
const audioPreview = ref<HTMLAudioElement | null>(null)
const audioPreviewUrl = ref('')
const audioPreviewPeaks = ref<number[]>([])
const audioPreviewDuration = ref(0)
const audioPreviewLoading = ref(false)
const audioPreviewError = ref('')
const audioPreviewExpires = ref(0)
const playerRef = ref<InstanceType<typeof AudioTranscriptPlayer> | null>(null)
const activeSegmentIndex = ref(-1)

watch(activeSegmentIndex, (newIdx) => {
  if (newIdx >= 0) {
    const el = document.getElementById('segment-row-' + newIdx)
    if (el && document.activeElement?.tagName !== 'TEXTAREA') {
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }
})
let timer: ReturnType<typeof setInterval> | null = null
let queueRevision = 0
let detailRevision = 0

interface StudentReviewGroup {
  user_id: string
  user_name: string
  class_group: string | null
  items: AsrReviewQueueItem[]
  taskItems: AsrReviewQueueItem[]
}

function uniqueTaskItems(items: AsrReviewQueueItem[]) {
  const bySequence = new Map<number, AsrReviewQueueItem>()
  for (const item of items) {
    if (!bySequence.has(item.sequence_no)) bySequence.set(item.sequence_no, item)
  }
  return [...bySequence.values()].sort((a, b) => a.sequence_no - b.sequence_no)
}

function latestRunItems(items: AsrReviewQueueItem[]) {
  const latestRunId = items.find(item => item.run_id)?.run_id
  return latestRunId
    ? items.filter(item => item.run_id === latestRunId)
    : items
}

const selectedItem = computed(() =>
  queue.value.find(item => item.session_id === selectedSessionId.value) ?? null
)
const studentGroups = computed<StudentReviewGroup[]>(() => {
  const grouped = new Map<string, AsrReviewQueueItem[]>()
  for (const item of queue.value) {
    const items = grouped.get(item.user_id)
    if (items) items.push(item)
    else grouped.set(item.user_id, [item])
  }
  return [...grouped.entries()].map(([userId, items]) => ({
    user_id: userId,
    user_name: items[0]?.user_name ?? '未知学生',
    class_group: items[0]?.class_group ?? null,
    items,
    taskItems: uniqueTaskItems(latestRunItems(items))
  }))
})
const visibleStudentGroups = computed(() => {
  const keyword = studentSearch.value.trim().toLocaleLowerCase('zh-CN')
  return studentGroups.value.filter(group => {
    const status = groupStatus(group)
    const matchesSearch = !keyword
      || group.user_name.toLocaleLowerCase('zh-CN').includes(keyword)
      || (group.class_group || '').toLocaleLowerCase('zh-CN').includes(keyword)
    const matchesStatus = !queueStatusFilter.value
      || (queueStatusFilter.value === 'attention'
        ? ['failed', 'retry_wait', 'waiting_configuration'].includes(status)
        : queueStatusFilter.value === 'completed'
          ? ['completed', 'manually_transcribed'].includes(status)
        : status === queueStatusFilter.value)
    return matchesSearch && matchesStatus
  })
})
const retryableSelectedSessions = computed(() => studentGroups.value
  .filter(group => selectedStudentIds.value.includes(group.user_id))
  .flatMap(group => group.taskItems)
  .filter(item => ['failed', 'retry_wait', 'waiting_configuration'].includes(item.job.status))
  .map(item => item.session_id))
const selectedStudentGroup = computed(() => {
  const userId = selectedItem.value?.user_id
  return userId
    ? studentGroups.value.find(group => group.user_id === userId) ?? null
    : null
})
const selectedTaskItems = computed(() => {
  const group = selectedStudentGroup.value
  const item = selectedItem.value
  if (!group || !item) return []
  const sameRunItems = item.run_id
    ? group.items.filter(candidate => candidate.run_id === item.run_id)
    : group.items
  return uniqueTaskItems(sameRunItems)
})
const taskOptions = computed(() =>
  [1, 2].map(sequenceNo => ({
    sequenceNo,
    item: selectedTaskItems.value.find(item => item.sequence_no === sequenceNo) ?? null
  }))
)
const selectedVersion = computed(() =>
  versions.value.find(item => item.id === selectedVersionId.value) ?? null
)
const completedCount = computed(() =>
  queue.value.filter(item => ['completed', 'manually_transcribed'].includes(item.job.status)).length
)
const attentionCount = computed(() =>
  queue.value.filter(item =>
    ['failed', 'retry_wait', 'waiting_configuration'].includes(item.job.status)
  ).length
)
const queuePageCount = computed(() => Math.max(1, Math.ceil(queueTotal.value / queuePageSize.value)))
const canResolveFailedAudio = computed(() =>
  selectedStatus.value?.job?.status === 'failed' && versions.value.length === 0
)

const statusLabels: Record<string, string> = {
  queued: '等待处理',
  preparing_audio: '整理音频',
  transcribing: '正在识别',
  completed: '识别完成',
  manually_transcribed: '人工转录完成',
  retry_wait: '等待重试',
  failed: '识别失败',
  waiting_configuration: '等待配置'
}

function statusClass(status: string) {
  if (status === 'completed' || status === 'manually_transcribed') return 'bg-success-subtle text-success-emphasis'
  if (status === 'failed') return 'bg-danger-subtle text-danger-emphasis'
  if (status === 'waiting_configuration' || status === 'retry_wait') {
    return 'bg-warning-subtle text-warning-emphasis'
  }
  if (status === 'transcribing' || status === 'preparing_audio') {
    return 'bg-primary-subtle text-primary'
  }
  return 'bg-secondary-subtle text-secondary-emphasis'
}

function sourceLabel(source: string | null | undefined) {
  if (source === 'human_transcribed') return '人工转录（非 ASR）'
  if (source === 'human_corrected') return '人工校订'
  if (source === 'server_asr') return '服务端 ASR'
  return source || '未知来源'
}

function taskLabel(sequenceNo: number) {
  if (sequenceNo === 1) return '任务一'
  if (sequenceNo === 2) return '任务二'
  return `任务 ${sequenceNo}`
}

function groupStatus(group: StudentReviewGroup) {
  const statuses = group.taskItems.map(item => item.job.status)
  const attention = statuses.find(status =>
    ['failed', 'retry_wait', 'waiting_configuration'].includes(status)
  )
  if (attention) return attention
  const processing = statuses.find(status =>
    ['queued', 'preparing_audio', 'transcribing'].includes(status)
  )
  if (processing) return processing
  return statuses.every(status => ['completed', 'manually_transcribed'].includes(status))
    ? (statuses.some(status => status === 'manually_transcribed') ? 'manually_transcribed' : 'completed')
    : statuses[0] || 'queued'
}

function formatTime(ms: number) {
  const seconds = Math.max(0, Math.round(ms / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

function formatDate(value: string) {
  return parseApiDate(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function cloneSegments(version: TranscriptVersion) {
  editableSegments.value = [...version.segments]
    .sort((a, b) => (a.segment_no ?? 0) - (b.segment_no ?? 0))
    .map((segment, index) => ({
      segment_no: segment.segment_no ?? index,
      text: segment.text,
      started_at_ms: segment.started_at_ms,
      ended_at_ms: segment.ended_at_ms,
      confidence: segment.confidence
    }))
  isDirty.value = false
}

function resolveAudioUrl(url: string) {
  try {
    return new URL(url, window.location.origin).toString()
  } catch {
    return url
  }
}

async function loadAudioPreview(sessionId: string) {
  audioPreview.value?.pause()
  audioPreviewUrl.value = ''
  audioPreviewPeaks.value = []
  audioPreviewDuration.value = 0
  audioPreviewError.value = ''
  audioPreviewExpires.value = 0
  audioPreviewLoading.value = true
  try {
    const [ticket, waveform] = await Promise.all([
      extractionApi.audioTicket(sessionId),
      extractionApi.audioWaveform(sessionId).catch(() => null)
    ])
    if (selectedSessionId.value !== sessionId) return
    audioPreviewUrl.value = resolveAudioUrl(ticket.data.url)
    audioPreviewExpires.value = ticket.data.expires
    if (waveform) {
      audioPreviewPeaks.value = waveform.data.peaks
      audioPreviewDuration.value = waveform.data.duration_seconds
    }
  } catch (error) {
    if (selectedSessionId.value === sessionId) {
      audioPreviewError.value = error instanceof Error ? error.message : '录音试听加载失败'
    }
  } finally {
    if (selectedSessionId.value === sessionId) audioPreviewLoading.value = false
  }
}

function onAudioPreviewError() {
  if (!audioPreviewUrl.value) return
  const expired = audioPreviewExpires.value > 0
    && Math.floor(Date.now() / 1000) >= audioPreviewExpires.value
  audioPreviewError.value = expired
    ? '试听地址已过期，请重新载入。'
    : '录音暂时无法播放，请检查录音文件。'
}

function chooseVersion(versionId: string) {
  const version = versions.value.find(item => item.id === versionId)
  if (!version) return
  selectedVersionId.value = version.id
  cloneSegments(version)
}

async function loadQueue(keepSelection = true) {
  const revision = ++queueRevision
  try {
    const response = await asrApi.reviewQueue({
      page: queuePage.value,
      page_size: queuePageSize.value,
      search: studentSearch.value.trim(),
      status_filter: queueStatusFilter.value
    })
    if (revision !== queueRevision) return
    queue.value = response.data
    queueTotal.value = Number(response.headers['x-total-count'] ?? response.data.length)
    const querySession = typeof route.query.session === 'string'
      ? route.query.session
      : ''
    const preferred = keepSelection ? selectedSessionId.value || querySession : querySession
    if (preferred && queue.value.some(item => item.session_id === preferred)) {
      if (preferred !== selectedSessionId.value) await selectSession(preferred)
    } else if (studentGroups.value[0]) {
      selectedSessionId.value = ''
      const firstGroup = studentGroups.value[0]
      const firstSession = firstGroup.taskItems.find(item => item.sequence_no === 1)
        ?? firstGroup.taskItems[0]
      if (firstSession) await selectSession(firstSession.session_id)
    } else {
      selectedSessionId.value = ''
      selectedStatus.value = null
      versions.value = []
      selectedVersionId.value = ''
      editableSegments.value = []
      manualEntryMode.value = false
    }
  } catch (error) {
    if (revision === queueRevision) {
      errorMessage.value = error instanceof Error ? error.message : 'ASR 复核队列加载失败'
    }
  }
}

let filterTimer: ReturnType<typeof setTimeout> | null = null
watch([studentSearch, queueStatusFilter, queuePageSize], () => {
  sessionStorage.setItem(FILTER_STORAGE_KEY, queueStatusFilter.value)
  queuePage.value = 1
  if (filterTimer) clearTimeout(filterTimer)
  filterTimer = setTimeout(() => void loadQueue(false), 300)
})
watch(queuePage, () => void loadQueue(false))

async function loadDetail(sessionId: string, preserveEditor = false) {
  const revision = ++detailRevision
  detailLoading.value = true
  try {
    const [statusResponse, versionResponse] = await Promise.all([
      asrApi.status(sessionId),
      asrApi.versions(sessionId)
    ])
    if (revision !== detailRevision) return
    selectedStatus.value = statusResponse.data
    versions.value = versionResponse.data
    if (!preserveEditor || !isDirty.value) {
      const target = versions.value.find(item => item.is_authoritative)
        ?? versions.value[0]
      if (target) chooseVersion(target.id)
      else {
        selectedVersionId.value = ''
        editableSegments.value = []
        isDirty.value = false
      }
    }
  } catch (error) {
    if (revision === detailRevision) {
      errorMessage.value = error instanceof Error ? error.message : '转录详情加载失败'
    }
  } finally {
    if (revision === detailRevision) detailLoading.value = false
  }
}

async function selectSession(sessionId: string) {
  if (isDirty.value && sessionId !== selectedSessionId.value) {
    const confirmed = await confirmAction({
      title: '放弃未保存的校订',
      message: '当前校订尚未保存。切换会话后，本次修改将丢失。',
      confirmText: '继续切换',
      tone: 'warning'
    })
    if (!confirmed) return
  }
  selectedSessionId.value = sessionId
  manualEntryMode.value = false
  errorMessage.value = ''
  successMessage.value = ''
  await router.replace({
    query: {
      ...route.query,
      session: sessionId,
      asr_status: queueStatusFilter.value || 'all'
    }
  })
  await Promise.all([
    loadDetail(sessionId),
    loadAudioPreview(sessionId)
  ])
}

async function selectStudent(group: StudentReviewGroup) {
  if (selectedItem.value?.user_id === group.user_id) return
  const target = group.taskItems.find(item => item.sequence_no === 1)
    ?? group.taskItems[0]
  if (target) await selectSession(target.session_id)
}

async function retryRecognition() {
  if (!selectedSessionId.value) return
  retrying.value = true
  errorMessage.value = ''
  try {
    selectedStatus.value = (await asrApi.retry(selectedSessionId.value)).data
    successMessage.value = '识别任务已重新进入队列。'
    await loadQueue()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '重新识别失败'
  } finally {
    retrying.value = false
  }
}

async function batchRetryRecognition() {
  const sessionIds = retryableSelectedSessions.value
  if (!sessionIds.length) {
    notify('所选学生没有可重试的失败任务', 'warning')
    return
  }
  const confirmed = await confirmAction({
    title: '批量重新识别',
    message: `将 ${sessionIds.length} 个失败或待配置的识别任务重新加入队列，是否继续？`,
    confirmText: '加入队列',
    tone: 'warning'
  })
  if (!confirmed) return
  batchRetrying.value = true
  try {
    const result = (await asrApi.batchRetry(sessionIds)).data
    notify(`已重新排队 ${result.processed} 项${result.skipped ? `，跳过 ${result.skipped} 项` : ''}`, result.skipped ? 'warning' : 'success')
    if (result.errors.length) errorMessage.value = result.errors.slice(0, 5).join('；')
    selectedStudentIds.value = []
    await loadQueue()
  } catch (error) {
    notify(error instanceof Error ? error.message : '批量重试失败', 'danger')
  } finally {
    batchRetrying.value = false
  }
}

async function approveVersion() {
  const version = selectedVersion.value
  if (!version || !selectedSessionId.value) return
  approving.value = true
  errorMessage.value = ''
  try {
    await asrApi.approve(selectedSessionId.value, version.id)
    successMessage.value = `版本 v${version.version_no} 已确认为权威转录。`
    await loadDetail(selectedSessionId.value)
    await loadQueue()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '版本确认失败'
  } finally {
    approving.value = false
  }
}

async function saveCorrection() {
  if (!selectedSessionId.value || !editableSegments.value.length) return
  if (editableSegments.value.some(item => !item.text.trim())) {
    errorMessage.value = '转录片段不能为空，请填写或删除对应内容。'
    return
  }
  saving.value = true
  errorMessage.value = ''
  try {
    const response = await asrApi.correct(
      selectedSessionId.value,
      editableSegments.value.map(item => ({ ...item, text: item.text.trim() }))
    )
    successMessage.value = `人工校订已保存为权威版本 v${response.data.version_no}。`
    isDirty.value = false
    await loadDetail(selectedSessionId.value)
    chooseVersion(response.data.id)
    await loadQueue()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '人工校订保存失败'
  } finally {
    saving.value = false
  }
}

async function startManualTranscription() {
  if (!selectedSessionId.value || !canResolveFailedAudio.value) return
  const confirmed = await confirmAction({
    title: '改为人工转录',
    message: '该语音的自动识别已经失败。继续后请人工听取完整录音并填写文本；保存结果会明确标记为“人工转录（非 ASR）”，并直接成为权威版本。是否继续？',
    confirmText: '开始人工转录',
    tone: 'warning'
  })
  if (!confirmed) return
  manualEntryMode.value = true
  selectedVersionId.value = ''
  editableSegments.value = [{
    segment_no: 0,
    text: '',
    started_at_ms: 0,
    ended_at_ms: selectedStatus.value?.job?.audio_duration_ms ?? Math.round(audioPreviewDuration.value * 1000),
    confidence: null
  }]
  isDirty.value = true
  successMessage.value = ''
  errorMessage.value = ''
}

async function saveManualTranscription() {
  if (!selectedSessionId.value || !manualEntryMode.value) return
  if (!editableSegments.value.length || editableSegments.value.some(item => !item.text.trim())) {
    errorMessage.value = '请填写完整的人工转录文本。'
    return
  }
  saving.value = true
  errorMessage.value = ''
  try {
    const response = await asrApi.manualTranscript(
      selectedSessionId.value,
      editableSegments.value.map(item => ({ ...item, text: item.text.trim() }))
    )
    manualEntryMode.value = false
    isDirty.value = false
    successMessage.value = `人工转录已保存并标记为非 ASR 来源，权威版本为 v${response.data.version_no}。`
    await loadDetail(selectedSessionId.value)
    chooseVersion(response.data.id)
    await loadQueue()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '人工转录保存失败'
  } finally {
    saving.value = false
  }
}

async function deleteFailedAudio() {
  if (!selectedSessionId.value || !canResolveFailedAudio.value) return
  const targetSessionId = selectedSessionId.value
  const confirmed = await confirmAction({
    title: '永久删除识别失败的语音',
    message: '该操作会删除此任务的原始录音分片、整理后的音频及全部失败识别任务记录，删除后无法恢复，也不能再进行人工转录。是否确认删除？',
    confirmText: '永久删除',
    tone: 'danger'
  })
  if (!confirmed) return
  deletingFailedAudio.value = true
  errorMessage.value = ''
  try {
    const result = (await asrApi.deleteFailedAudio(targetSessionId)).data
    selectedSessionId.value = ''
    selectedStatus.value = null
    versions.value = []
    editableSegments.value = []
    manualEntryMode.value = false
    const message = result.failed_files
      ? `${result.message}；有 ${result.failed_files} 个存储文件未能清理，请查看服务器日志。`
      : result.message
    notify(message, result.failed_files ? 'warning' : 'success')
    await router.replace({
      query: {
        ...route.query,
        session: undefined,
        asr_status: queueStatusFilter.value || 'all'
      }
    })
    await loadQueue(false)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '删除识别失败语音失败'
  } finally {
    deletingFailedAudio.value = false
  }
}

function markDirty() {
  isDirty.value = true
  successMessage.value = ''
}

function removeSegment(index: number) {
  editableSegments.value.splice(index, 1)
  editableSegments.value = editableSegments.value.map((item, segmentNo) => ({
    ...item,
    segment_no: segmentNo
  }))
  markDirty()
}

function refreshPeriodically() {
  if (
    isDirty.value
    || document.visibilityState !== 'visible'
    || !navigator.onLine
  ) return
  void loadQueue().then(() => {
    const status = selectedStatus.value?.job?.status
    if (
      selectedSessionId.value
      && status
      && !['completed', 'failed', 'waiting_configuration'].includes(status)
    ) {
      void loadDetail(selectedSessionId.value, true)
    }
  })
}

onMounted(async () => {
  isLoading.value = true
  await loadQueue(false)
  isLoading.value = false
  timer = setInterval(refreshPeriodically, 5000)
})

onBeforeUnmount(() => {
  audioPreview.value?.pause()
  if (timer) clearInterval(timer)
  if (filterTimer) clearTimeout(filterTimer)
})
</script>

<template>
  <div class="transcript-review-page">
    <AppPageHeader eyebrow="权威转录版本" title="权威转录校订" icon="bi-file-earmark-text" description="检查服务端识别结果，保留原版本并将人工修订发布为新的权威版本。">
      <template #actions>
        <AppMetricPill :value="completedCount" label="已完成" tone="success" />
        <AppMetricPill :value="attentionCount" label="需处理" :tone="attentionCount ? 'warning' : 'neutral'" />
      </template>
    </AppPageHeader>

    <div v-if="errorMessage" class="alert alert-danger">{{ errorMessage }}</div>
    <div v-if="successMessage" class="alert alert-success">{{ successMessage }}</div>

    <div v-if="isLoading" class="card border-0 shadow-sm py-5 text-center">
      <div><span class="spinner-border text-primary" /></div>
    </div>

    <div v-else class="review-layout">
      <aside class="session-list card border-0 shadow-sm">
        <div class="card-body p-3">
          <div class="d-flex justify-content-between align-items-center mb-3">
            <h5 class="mb-0">学生名单</h5>
            <button class="btn btn-sm btn-light" title="刷新" @click="loadQueue()">
              <i class="bi bi-arrow-clockwise" />
            </button>
          </div>
          <div class="queue-filters mb-3">
            <input v-model="studentSearch" class="form-control form-control-sm" type="search" placeholder="查找姓名或班级" />
            <select v-model="queueStatusFilter" class="form-select form-select-sm">
              <option value="attention">仅需处理</option>
              <option value="">全部状态</option>
              <option value="completed">已完成（含人工）</option>
              <option value="manually_transcribed">人工转录完成</option>
              <option value="queued">等待处理</option>
              <option value="preparing_audio">整理音频</option>
              <option value="transcribing">正在识别</option>
              <option value="retry_wait">等待重试</option>
              <option value="failed">识别失败</option>
              <option value="waiting_configuration">等待配置</option>
            </select>
          </div>
          <div v-if="selectedStudentIds.length" class="batch-retry-bar mb-2">
            <span>已选 {{ selectedStudentIds.length }} 人</span>
            <button class="btn btn-sm btn-outline-danger" :disabled="batchRetrying" @click="batchRetryRecognition">
              <span v-if="batchRetrying" class="spinner-border spinner-border-sm me-1" />批量重试
            </button>
          </div>
          <button
            v-for="group in visibleStudentGroups"
            :key="group.user_id"
            class="session-item"
            :class="{ active: selectedItem?.user_id === group.user_id }"
            @click="selectStudent(group)"
          >
            <input
              v-model="selectedStudentIds"
              class="form-check-input session-select"
              type="checkbox"
              :value="group.user_id"
              :aria-label="`选择 ${group.user_name}`"
              @click.stop
            />
            <span class="d-flex justify-content-between gap-2">
              <strong>{{ group.user_name }}</strong>
              <span class="badge" :class="statusClass(groupStatus(group))">
                {{ statusLabels[groupStatus(group)] || groupStatus(group) }}
              </span>
            </span>
            <small>{{ group.class_group || '未分班' }}</small>
            <span class="task-progress mt-2">
              <span
                v-for="sequenceNo in [1, 2]"
                :key="sequenceNo"
                :class="{ ready: group.taskItems.some(item => item.sequence_no === sequenceNo) }"
              >
                {{ taskLabel(sequenceNo) }}
              </span>
            </span>
          </button>
          <p v-if="!visibleStudentGroups.length" class="text-center text-muted small py-4 mb-0">
            {{ studentGroups.length ? '没有符合筛选条件的学生' : '暂无服务端 ASR 会话' }}
          </p>
          <nav v-if="queueTotal > queuePageSize" class="queue-page-nav" aria-label="转录队列分页">
            <button class="btn btn-sm btn-outline-secondary" :disabled="queuePage <= 1" @click="queuePage--">上一页</button>
            <span>{{ queuePage }} / {{ queuePageCount }} · 共 {{ queueTotal }} 条</span>
            <button class="btn btn-sm btn-outline-secondary" :disabled="queuePage >= queuePageCount" @click="queuePage++">下一页</button>
          </nav>
        </div>
      </aside>

      <section class="detail-panel card border-0 shadow-sm" aria-label="转录校订详情">
        <div v-if="!selectedItem" class="card-body py-5 text-center text-muted">
          <i class="bi bi-file-earmark-text display-5" />
          <p class="mt-3 mb-0">请选择一个测评会话</p>
        </div>

        <template v-else>
          <div class="card-header bg-white border-0 p-4 pb-3">
            <div class="d-flex flex-wrap justify-content-between align-items-start gap-3">
              <div>
                <div class="d-flex flex-wrap align-items-center gap-2">
                  <h5 class="mb-0">{{ selectedItem.user_name }}</h5>
                  <span class="badge" :class="statusClass(selectedStatus?.job?.status || selectedItem.job.status)">
                    {{ statusLabels[selectedStatus?.job?.status || selectedItem.job.status] }}
                  </span>
                </div>
                <p class="small text-muted mb-0 mt-2">
                  会话 {{ selectedItem.session_id }} · {{ selectedItem.class_group || '未分班' }}
                </p>
              </div>
              <div class="failed-audio-actions">
                <button
                  v-if="['failed', 'retry_wait'].includes(selectedStatus?.job?.status || '')"
                  class="btn btn-sm btn-outline-danger"
                  :disabled="retrying || deletingFailedAudio"
                  @click="retryRecognition"
                >
                  <span v-if="retrying" class="spinner-border spinner-border-sm me-1" />
                  <i v-else class="bi bi-arrow-repeat me-1" />重新识别
                </button>
                <button
                  v-if="canResolveFailedAudio"
                  class="btn btn-sm btn-outline-primary"
                  :disabled="saving || deletingFailedAudio"
                  @click="startManualTranscription"
                >
                  <i class="bi bi-keyboard me-1" />人工转录
                </button>
                <button
                  v-if="canResolveFailedAudio"
                  class="btn btn-sm btn-outline-danger"
                  :disabled="saving || deletingFailedAudio"
                  @click="deleteFailedAudio"
                >
                  <span v-if="deletingFailedAudio" class="spinner-border spinner-border-sm me-1" />
                  <i v-else class="bi bi-trash3 me-1" />删除失败语音
                </button>
              </div>
            </div>
            <div class="task-switcher mt-3" role="group" aria-label="选择校订任务">
              <button
                v-for="option in taskOptions"
                :key="option.sequenceNo"
                class="task-switch-button"
                :class="{ active: option.item?.session_id === selectedSessionId }"
                :disabled="!option.item"
                @click="option.item && selectSession(option.item.session_id)"
              >
                <span>
                  <strong>{{ taskLabel(option.sequenceNo) }}</strong>
                  <small v-if="option.item">
                    {{ statusLabels[option.item.job.status] || option.item.job.status }}
                  </small>
                  <small v-else>暂无会话</small>
                </span>
                <i
                  v-if="option.item?.authoritative_version_no"
                  class="bi bi-shield-check text-success"
                  :title="`权威版本 v${option.item.authoritative_version_no}`"
                />
              </button>
            </div>
            <div class="audio-preview mt-3" aria-label="当前任务录音试听">
              <div class="audio-preview-label mb-2">
                <i class="bi bi-headphones text-primary" />
                <span><strong>音文对齐精细试听</strong><small>点击片段直接定位播放，支持 0.75x–2.0x 倍速与单句循环</small></span>
              </div>
              <span v-if="audioPreviewLoading" class="audio-preview-loading">
                <span class="spinner-border spinner-border-sm" />载入音频中…
              </span>
              <AudioTranscriptPlayer
                v-else-if="audioPreviewUrl"
                ref="playerRef"
                v-model:active-index="activeSegmentIndex"
                :src="audioPreviewUrl"
                :segments="editableSegments"
                :peaks="audioPreviewPeaks"
                :duration-seconds="audioPreviewDuration"
                :title="selectedItem ? (selectedItem.user_name + ' - ' + taskLabel(selectedItem.sequence_no)) : ''"
                @error="onAudioPreviewError"
              />
              <button
                v-else
                class="btn btn-sm btn-outline-secondary"
                type="button"
                :disabled="audioPreviewLoading"
                @click="loadAudioPreview(selectedSessionId)"
              >
                <i class="bi bi-arrow-clockwise me-1" />重新载入录音试听
              </button>
            </div>
            <p v-if="audioPreviewError" class="audio-preview-error mb-0 mt-2">
              <i class="bi bi-exclamation-circle me-1" />{{ audioPreviewError }}
            </p>
            <div
              v-if="selectedStatus?.job?.error_message"
              class="alert alert-warning py-2 small mt-3 mb-0"
            >
              {{ selectedStatus.job.error_message }}
            </div>
          </div>

          <div class="card-body p-4 pt-2">
            <div v-if="detailLoading" class="text-center py-5">
              <span class="spinner-border text-primary" />
            </div>

            <template v-else-if="versions.length || manualEntryMode">
              <div v-if="versions.length" class="version-strip mb-4">
                <button
                  v-for="version in versions"
                  :key="version.id"
                  class="version-button"
                  :class="{ active: selectedVersionId === version.id }"
                  @click="chooseVersion(version.id)"
                >
                  <span>
                    <strong>v{{ version.version_no }}</strong>
                    <small>{{ sourceLabel(version.source) }}</small>
                  </span>
                  <i v-if="version.is_authoritative" class="bi bi-shield-check text-success" />
                </button>
              </div>

              <div v-if="manualEntryMode" class="alert alert-warning d-flex gap-2 align-items-start mb-4">
                <i class="bi bi-person-lines-fill mt-1" />
                <div>
                  <strong>正在创建人工转录</strong>
                  <div class="small">请完整听取录音并填写文本。保存后将标记为“人工转录（非 ASR）”，且不会伪装成自动识别结果。</div>
                </div>
              </div>

              <div class="d-flex flex-wrap justify-content-between align-items-start gap-3 mb-3">
                <div v-if="selectedVersion && !manualEntryMode">
                  <h6 class="mb-1">
                    版本 v{{ selectedVersion.version_no }}
                    <span
                      v-if="selectedVersion.is_authoritative"
                      class="badge bg-success-subtle text-success-emphasis ms-1"
                    >
                      当前权威版本
                    </span>
                  </h6>
                  <small class="text-muted">
                    {{ sourceLabel(selectedVersion.source) }} ·
                    {{ formatDate(selectedVersion.created_at) }} ·
                    {{ selectedVersion.segments.length }} 个片段
                  </small>
                </div>
                <button
                  v-if="selectedVersion && !selectedVersion.is_authoritative"
                  class="btn btn-sm btn-outline-success"
                  :disabled="approving || isDirty"
                  @click="approveVersion"
                >
                  <span v-if="approving" class="spinner-border spinner-border-sm me-1" />
                  确认为权威版本
                </button>
              </div>

              <div class="segment-editor">
                <article
                  v-for="(segment, index) in editableSegments"
                  :key="`${selectedVersionId}-${segment.segment_no}`"
                  :id="`segment-row-${index}`"
                  class="segment-row"
                  :class="{ 'is-active-speaking': index === activeSegmentIndex }"
                >
                  <div class="segment-meta">
                    <button
                      type="button"
                      class="btn btn-sm segment-play-btn"
                      :class="index === activeSegmentIndex ? 'btn-primary active-play' : 'btn-outline-secondary'"
                      title="从本句开始试听"
                      @click="playerRef?.seekToSegment(index, true)"
                    >
                      <i class="bi" :class="index === activeSegmentIndex ? 'bi-volume-up-fill' : 'bi-play-fill'" />
                      <strong>#{{ index + 1 }}</strong>
                    </button>
                    <span
                      class="segment-time-pill"
                      title="点击定位试听"
                      @click="playerRef?.seekToSegment(index, true)"
                    >
                      <i class="bi bi-clock-history me-1"></i>{{ formatTime(segment.started_at_ms) }}–{{ formatTime(segment.ended_at_ms) }}
                    </span>
                    <span v-if="segment.confidence != null" class="segment-conf-badge">
                      置信度 {{ Math.round(segment.confidence * 100) }}%
                    </span>
                  </div>
                  <textarea
                    v-model="segment.text"
                    class="form-control"
                    rows="3"
                    aria-label="转录片段文本"
                    @input="markDirty"
                  />
                  <button
                    class="btn btn-sm btn-link text-danger remove-button"
                    title="删除此片段"
                    @click="removeSegment(index)"
                  >
                    <i class="bi bi-trash" />
                  </button>
                </article>
              </div>

              <div class="editor-footer">
                <p class="small text-muted mb-0">
                  {{ manualEntryMode
                    ? '保存后将创建带有人工来源标记的权威版本，并保留原识别失败信息。'
                    : '保存校订会创建新版本，原始 ASR 结果不会被覆盖。' }}
                </p>
                <button
                  class="btn btn-primary"
                  :disabled="!isDirty || !editableSegments.length || saving"
                  @click="manualEntryMode ? saveManualTranscription() : saveCorrection()"
                >
                  <span v-if="saving" class="spinner-border spinner-border-sm me-1" />
                  <i v-else class="bi bi-check2-circle me-1" />
                  {{ manualEntryMode ? '保存人工转录为权威版本' : '保存为新权威版本' }}
                </button>
              </div>
            </template>

            <div v-else class="empty-transcript py-5 text-center">
              <i class="bi bi-hourglass-split display-5 text-muted" />
              <h6 class="mt-3">权威转录尚未生成</h6>
              <p class="text-muted small mb-0">
                当前状态：{{ statusLabels[selectedStatus?.job?.status || selectedItem.job.status] }}
              </p>
            </div>
          </div>
        </template>
      </section>
    </div>
  </div>
</template>

<style scoped>
.transcript-review-page { max-width: 1320px; margin: 0 auto; }
.card { border-radius: var(--radius-lg); }
.summary-pill {
  padding: .65rem .85rem;
  border-radius: 10px;
  color: var(--color-text);
  background: var(--color-surface-subtle);
  font-size: .8rem;
}
.summary-pill strong { font-size: 1rem; margin-right: .25rem; }
.summary-pill.attention { color: var(--color-warning); background: var(--color-warning-soft); }
.review-layout {
  display: grid;
  grid-template-columns: minmax(260px, 330px) minmax(0, 1fr);
  gap: 1.25rem;
  align-items: start;
}
.session-list { max-height: calc(100vh - 180px); overflow: auto; position: sticky; top: 1rem; }
.queue-filters { display: grid; grid-template-columns: minmax(0, 1fr) minmax(150px, auto); gap: .45rem; }
.failed-audio-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: .5rem; }
.batch-retry-bar { display: flex; align-items: center; justify-content: space-between; gap: .5rem; padding: .55rem .65rem; border-radius: 9px; background: var(--color-danger-soft); color: var(--color-danger); font-size: .78rem; }
.session-item {
  position: relative;
  display: block;
  width: 100%;
  padding: .9rem;
  margin-bottom: .55rem;
  border: 1px solid var(--color-border);
  border-radius: 11px;
  color: var(--color-text);
  background: var(--color-surface);
  text-align: left;
  transition: color var(--motion-popover) ease, background-color var(--motion-popover) ease, border-color var(--motion-popover) ease, box-shadow var(--motion-popover) ease;
}
.session-select { position: absolute; top: .8rem; left: .7rem; z-index: 1; }
.session-item > span:first-of-type { padding-left: 1.35rem; }
.session-item:hover { border-color: var(--color-primary-hover); background: var(--color-primary-soft); }
.session-item.active { border-color: var(--color-primary); background: var(--color-primary-soft); box-shadow: 0 0 0 2px rgba(75, 73, 172, .1); }
.session-item small { color: var(--color-text-muted); }
.task-progress { display: flex; gap: .4rem; }
.task-progress span {
  padding: .2rem .45rem;
  border-radius: 999px;
  color: var(--color-text-muted);
  background: var(--color-surface-subtle);
  font-size: .68rem;
}
.task-progress span.ready { color: var(--color-primary); background: var(--color-primary-soft); }
.queue-page-nav { position: sticky; bottom: 0; display: flex; align-items: center; justify-content: space-between; gap: .5rem; padding: .75rem 0 .1rem; background: var(--color-surface); color: var(--color-text-muted); font-size: .72rem; }
.task-switcher { display: grid; grid-template-columns: repeat(2, minmax(0, 180px)); gap: .65rem; }
.task-switch-button {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .75rem;
  padding: .7rem .85rem;
  border: 1px solid var(--color-border);
  border-radius: 10px;
  color: var(--color-text);
  background: var(--color-surface);
  text-align: left;
  transition: color var(--motion-popover) ease, background-color var(--motion-popover) ease, border-color var(--motion-popover) ease, box-shadow var(--motion-popover) ease;
}
.task-switch-button:not(:disabled):hover { border-color: var(--color-primary-hover); background: var(--color-primary-soft); }
.task-switch-button.active { border-color: var(--color-primary); background: var(--color-primary-soft); box-shadow: 0 0 0 2px rgba(75, 73, 172, .08); }
.task-switch-button:disabled { color: var(--color-text-muted); background: var(--color-surface-subtle); cursor: not-allowed; }
.task-switch-button small { display: block; margin-top: .1rem; color: var(--color-text-muted); font-size: .7rem; }
.audio-preview {
  display: grid;
  grid-template-columns: minmax(180px, auto) minmax(240px, 1fr);
  align-items: center;
  gap: .85rem;
  padding: .7rem .8rem;
  border: 1px solid var(--color-border);
  border-radius: 11px;
  background: var(--color-surface-subtle);
}
.audio-preview-label { display: flex; align-items: center; gap: .65rem; min-width: 0; }
.audio-preview-label > i { color: var(--color-primary); font-size: 1.1rem; }
.audio-preview-label span, .audio-preview-label strong, .audio-preview-label small { display: block; }
.audio-preview-label strong { color: var(--color-text); font-size: .8rem; }
.audio-preview-label small { margin-top: .12rem; color: var(--color-text-muted); font-size: .68rem; }
.audio-preview-player { width: 100%; min-width: 0; height: 36px; }
.audio-preview-loading { display: inline-flex; align-items: center; gap: .45rem; color: var(--color-text-muted); font-size: .75rem; }
.audio-preview-error { color: var(--color-danger); font-size: .74rem; }
.version-strip { display: flex; gap: .55rem; overflow-x: auto; padding-bottom: .25rem; }
.version-button {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .8rem;
  min-width: 135px;
  padding: .7rem .8rem;
  border: 1px solid var(--color-border);
  border-radius: 10px;
  background: var(--color-surface);
  color: var(--color-text);
  text-align: left;
}
.version-button.active { border-color: var(--color-primary); background: var(--color-primary-soft); color: var(--color-primary); }
.version-button small { display: block; color: var(--color-text-muted); font-size: .7rem; }
.segment-editor { display: grid; gap: .75rem; }
.segment-row {
  position: relative;
  padding: 1rem;
  border: 1px solid var(--color-border);
  border-radius: 11px;
  background: var(--color-surface-subtle);
}
.segment-meta { display: flex; flex-wrap: wrap; gap: .75rem; margin-bottom: .55rem; color: var(--color-text-muted); font-size: .75rem; }
.segment-meta strong { color: var(--color-primary); }
.segment-row textarea { padding-right: 2.5rem; line-height: 1.65; resize: vertical; }
.remove-button { position: absolute; right: 1.15rem; top: 3.15rem; }
.editor-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  padding-top: 1rem;
  margin-top: 1rem;
  border-top: 1px solid var(--color-border);
}
@media (max-width: 991.98px) {
  .review-layout { grid-template-columns: 1fr; }
  .session-list { position: static; max-height: 360px; }
}
@media (max-width: 575.98px) {
  .summary-pill { flex: 1 1 calc(50% - .5rem); text-align: center; }
  .session-list { max-height: 320px; }
  .queue-filters { grid-template-columns: 1fr; }
  .session-item { padding: .75rem; }
  .detail-panel .card-header, .detail-panel .card-body { padding: 1rem !important; }
  .task-switcher { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .task-switch-button { padding: .65rem; }
  .audio-preview { grid-template-columns: 1fr; gap: .6rem; }
  .version-button { min-width: 122px; padding: .6rem .7rem; }
  .segment-row { padding: .8rem; }
  .segment-row textarea { padding-right: 2.25rem; font-size: 16px; }
  .remove-button { right: .85rem; top: 2.95rem; }
  .editor-footer { align-items: stretch; flex-direction: column; }
  .editor-footer .btn { width: 100%; }
}

.segment-row.is-active-speaking {
  border-color: var(--color-primary) !important;
  background: var(--color-primary-soft) !important;
  box-shadow: 0 4px 18px rgba(75, 73, 172, .18);
  transform: scale(1.008);
}
.segment-play-btn {
  padding: .15rem .45rem;
  font-size: .75rem;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  gap: .25rem;
  font-weight: 700;
}
.segment-play-btn.active-play {
  box-shadow: 0 0 10px rgba(75, 73, 172, .4);
}
.segment-time-pill {
  cursor: pointer;
  padding: .2rem .5rem;
  border-radius: 6px;
  background: var(--color-surface-subtle);
  border: 1px solid var(--color-border);
  font-size: .75rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  transition: all var(--motion-fast) ease;
}
.segment-time-pill:hover {
  color: var(--color-primary);
  border-color: var(--color-primary);
  background: var(--color-primary-soft);
}
.segment-conf-badge {
  font-size: .72rem;
  color: var(--color-text-muted);
}

</style>
