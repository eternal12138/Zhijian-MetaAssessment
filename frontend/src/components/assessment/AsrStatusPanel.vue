<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  asrApi,
  type AsrJobStatus,
  type AsrSessionStatus
} from '../../api/asr'

const props = withDefaults(defineProps<{
  sessionIds: string[]
  title?: string
  allowRetry?: boolean
}>(), {
  title: '服务端权威转录',
  allowRetry: true
})
const emit = defineEmits<{
  readyChange: [ready: boolean]
}>()

const statuses = ref<Record<string, AsrSessionStatus>>({})
const loadingIds = ref(new Set<string>())
const retryingId = ref('')
const errorMessage = ref('')
const missingJobPolls = ref<Record<string, number>>({})
let timer: ReturnType<typeof setInterval> | null = null
let polling = false

const statusPresentation: Record<AsrJobStatus, {
  label: string
  detail: string
  icon: string
  badge: string
}> = {
  queued: {
    label: '等待处理',
    detail: '录音已安全保存，正在等待服务端处理。',
    icon: 'bi-hourglass-split',
    badge: 'bg-secondary-subtle text-secondary-emphasis'
  },
  preparing_audio: {
    label: '正在整理音频',
    detail: '正在校验分片并转换为标准音频。',
    icon: 'bi-soundwave',
    badge: 'bg-info-subtle text-info-emphasis'
  },
  transcribing: {
    label: '正在识别',
    detail: '服务端正在生成权威转录，请稍候。',
    icon: 'bi-mic-fill',
    badge: 'bg-primary-subtle text-primary'
  },
  completed: {
    label: '转录完成',
    detail: '权威转录已经生成，可用于后续分析。',
    icon: 'bi-check-circle-fill',
    badge: 'bg-success-subtle text-success-emphasis'
  },
  manually_transcribed: {
    label: '人工转录完成',
    detail: '研究人员已根据录音完成人工转录，并明确标记为非 ASR 来源。',
    icon: 'bi-person-check-fill',
    badge: 'bg-success-subtle text-success-emphasis'
  },
  retry_wait: {
    label: '等待重试',
    detail: '临时错误已记录，任务将重新尝试。',
    icon: 'bi-arrow-repeat',
    badge: 'bg-warning-subtle text-warning-emphasis'
  },
  failed: {
    label: '识别失败',
    detail: '录音仍然安全保留，可以重新提交识别。',
    icon: 'bi-exclamation-triangle-fill',
    badge: 'bg-danger-subtle text-danger-emphasis'
  },
  waiting_configuration: {
    label: 'ASR 未开启/未配置',
    detail: '当前服务端 ASR 处于关闭或未配置状态。配置开启后可随时手动触发识别；亦可直接进行人工转录。',
    icon: 'bi-gear-fill',
    badge: 'bg-warning-subtle text-warning-emphasis'
  }
}

const allCompleted = computed(() =>
  props.sessionIds.length > 0
  && props.sessionIds.every(id =>
    ['completed', 'manually_transcribed'].includes(statuses.value[id]?.job?.status || '')
  )
)
const hasActiveJob = computed(() =>
  props.sessionIds.some(id => {
    const status = statuses.value[id]?.job?.status
    return !status || ['queued', 'preparing_audio', 'transcribing', 'retry_wait'].includes(status)
  })
)
const hasWaitingConfig = computed(() =>
  props.sessionIds.some(id => statuses.value[id]?.job?.status === 'waiting_configuration')
)
const missingJobIds = computed(() => new Set(
  props.sessionIds.filter(id => (
    Boolean(statuses.value[id])
    && !statuses.value[id]?.job
    && (missingJobPolls.value[id] || 0) >= 3
  ))
))

function presentation(status?: AsrJobStatus, missing = false) {
  if (missing) return {
    label: '任务待恢复',
    detail: '录音已保存，但识别任务尚未建立。系统会自动恢复，也可立即重新提交。',
    icon: 'bi-exclamation-triangle-fill',
    badge: 'bg-warning-subtle text-warning-emphasis'
  }
  return status ? statusPresentation[status] : {
    label: '读取状态',
    detail: '正在确认服务端任务状态。',
    icon: 'bi-cloud-arrow-up',
    badge: 'bg-light text-dark'
  }
}

function taskLabel(index: number) {
  return `任务 ${index + 1}`
}

function duration(ms: number | null | undefined) {
  if (!ms) return ''
  const totalSeconds = Math.round(ms / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = String(totalSeconds % 60).padStart(2, '0')
  return `${minutes}:${seconds}`
}

async function loadStatuses() {
  if (polling || !props.sessionIds.length) return
  polling = true
  errorMessage.value = ''
  const nextLoading = new Set(loadingIds.value)
  props.sessionIds.forEach(id => nextLoading.add(id))
  loadingIds.value = nextLoading
  try {
    const results = await Promise.allSettled(
      props.sessionIds.map(async id => {
        const response = await asrApi.status(id)
        return [id, response.data] as const
      })
    )
    const responses = results
      .filter((result): result is PromiseFulfilledResult<readonly [string, AsrSessionStatus]> => result.status === 'fulfilled')
      .map(result => result.value)
    statuses.value = {
      ...statuses.value,
      ...Object.fromEntries(responses)
    }
    const nextMissingPolls = { ...missingJobPolls.value }
    for (const [id, status] of responses) {
      nextMissingPolls[id] = status.job ? 0 : (nextMissingPolls[id] || 0) + 1
    }
    missingJobPolls.value = nextMissingPolls
    const failedCount = results.length - responses.length
    if (failedCount === results.length) {
      throw new Error('ASR 状态暂时无法读取，请稍后重试')
    }
    if (failedCount > 0) {
      errorMessage.value = `${failedCount} 项状态暂时未更新，其余结果已保留。`
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'ASR 状态读取失败'
  } finally {
    loadingIds.value = new Set()
    polling = false
  }
}

async function retry(sessionId: string) {
  retryingId.value = sessionId
  errorMessage.value = ''
  try {
    const response = await asrApi.retry(sessionId)
    statuses.value = { ...statuses.value, [sessionId]: response.data }
    missingJobPolls.value = { ...missingJobPolls.value, [sessionId]: 0 }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '重新识别失败'
  } finally {
    retryingId.value = ''
  }
}

function restartPolling() {
  if (timer) clearInterval(timer)
  timer = null
  missingJobPolls.value = Object.fromEntries(props.sessionIds.map(id => [id, 0]))
  void loadStatuses()
  timer = setInterval(() => {
    if (
      hasActiveJob.value
      && document.visibilityState === 'visible'
      && navigator.onLine
    ) void loadStatuses()
  }, 5000)
}

watch(() => props.sessionIds.join(','), restartPolling, { immediate: true })
watch(allCompleted, ready => emit('readyChange', ready), { immediate: true })

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})

defineExpose({ refresh: loadStatuses })
</script>

<template>
  <section class="asr-status-panel">
    <div class="d-flex flex-wrap justify-content-between align-items-start gap-2 mb-3">
      <div>
        <h5 class="mb-1">{{ title }}</h5>
        <p class="text-muted small mb-0">
          浏览器字幕仅供现场参考，最终分析以服务端转录为准。
        </p>
      </div>
      <span v-if="allCompleted" class="badge bg-success-subtle text-success-emphasis">
        <i class="bi bi-shield-check me-1" />全部就绪
      </span>
    </div>

    <div v-if="errorMessage" class="alert alert-danger py-2 small" aria-live="polite">
      {{ errorMessage }}
    </div>
    <div v-if="hasWaitingConfig" class="alert alert-warning py-2 px-3 small d-flex align-items-center gap-2 mb-2" role="status">
      <i class="bi bi-info-circle-fill text-warning flex-shrink-0" style="font-size: 1.1rem;"></i>
      <div>
        <strong>服务端 ASR 处于未开启/未配置状态：</strong>
        录音数据已完整保存。若管理员已在后台开启 ASR 服务，可点击每项右侧“手动触发识别”；亦可由教师直接在转录校订页进行人工转录。
      </div>
    </div>
    <div v-if="missingJobIds.size" class="alert alert-warning py-2 small" aria-live="polite">
      {{ missingJobIds.size }} 项识别任务尚未建立。系统正在自动恢复，您也可以点击“重新提交”。
    </div>

    <div class="d-grid gap-2">
      <article
        v-for="(sessionId, index) in sessionIds"
        :key="sessionId"
        class="status-row"
      >
        <div class="status-icon">
          <span
            v-if="loadingIds.has(sessionId) && !statuses[sessionId]"
            class="spinner-border spinner-border-sm text-primary"
          />
          <i
            v-else
            class="bi"
            :class="presentation(statuses[sessionId]?.job?.status, missingJobIds.has(sessionId)).icon"
          />
        </div>
        <div class="flex-grow-1 min-width-0">
          <div class="d-flex flex-wrap align-items-center gap-2">
            <strong>{{ taskLabel(index) }}</strong>
            <span
              class="badge"
              :class="presentation(statuses[sessionId]?.job?.status, missingJobIds.has(sessionId)).badge"
            >
              {{ presentation(statuses[sessionId]?.job?.status, missingJobIds.has(sessionId)).label }}
            </span>
            <small
              v-if="statuses[sessionId]?.job?.audio_duration_ms"
              class="text-muted"
            >
              音频 {{ duration(statuses[sessionId]?.job?.audio_duration_ms) }}
            </small>
          </div>
          <p class="small text-muted mb-0 mt-1">
            {{ presentation(statuses[sessionId]?.job?.status, missingJobIds.has(sessionId)).detail }}
          </p>
          <div
            v-if="statuses[sessionId]?.job?.error_message"
            class="alert alert-danger py-1 px-2 small mb-0 mt-2 text-break"
            role="alert"
          >
            <i class="bi bi-exclamation-triangle-fill me-1"></i>
            <strong>失败原因：</strong>{{ statuses[sessionId]?.job?.error_message }}
          </div>
          <small
            v-if="statuses[sessionId]?.authoritative_version"
            class="text-success d-block mt-1"
          >
            权威版本 v{{ statuses[sessionId].authoritative_version?.version_no }}
            · {{ statuses[sessionId].authoritative_version?.segments.length }} 个片段
          </small>
        </div>
        <button
          v-if="
            allowRetry
            && (
              missingJobIds.has(sessionId)
              || ['failed', 'retry_wait', 'waiting_configuration'].includes(statuses[sessionId]?.job?.status ?? '')
            )
          "
          class="btn btn-sm flex-shrink-0"
          :class="statuses[sessionId]?.job?.status === 'waiting_configuration' ? 'btn-outline-primary' : 'btn-outline-danger'"
          :disabled="retryingId === sessionId"
          @click="retry(sessionId)"
        >
          <span
            v-if="retryingId === sessionId"
            class="spinner-border spinner-border-sm me-1"
          />
          {{ missingJobIds.has(sessionId) ? '重新提交' : statuses[sessionId]?.job?.status === 'waiting_configuration' ? '手动触发识别' : '重新识别' }}
        </button>
      </article>
    </div>
  </section>
</template>

<style scoped>
.asr-status-panel {
  padding: 1.25rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  text-align: left;
}
.status-row {
  display: flex;
  align-items: flex-start;
  gap: .85rem;
  padding: .9rem;
  border: 1px solid var(--color-border);
  border-radius: 11px;
  background: var(--color-surface-subtle);
}
.status-icon {
  display: grid;
  place-items: center;
  width: 2.25rem;
  height: 2.25rem;
  flex: 0 0 2.25rem;
  border-radius: 50%;
  color: var(--color-primary);
  background: var(--color-primary-soft);
  font-size: 1.05rem;
}
.min-width-0 { min-width: 0; }
@media (max-width: 575.98px) {
  .status-row { flex-wrap: wrap; }
  .status-row .btn { margin-left: 3.1rem; }
}
</style>
