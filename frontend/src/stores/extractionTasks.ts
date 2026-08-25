import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import {
  extractionApi,
  type ExtractionJob,
  type ExtractionJobStatus
} from '../api/extraction'
import { notify } from '../composables/useUiFeedback'
import { useNotificationStore } from './notification'

const ACTIVE_STATUSES: ExtractionJob['status'][] = ['queued', 'running', 'retry_wait']
const TERMINAL_STATUSES: ExtractionJob['status'][] = ['reviewing', 'reviewed', 'failed', 'superseded']

export interface TrackedExtractionTask extends ExtractionJobStatus {
  user_name: string
  task_title: string
  notified_terminal: boolean
  last_checked_at: number
}

type TaskContext = {
  user_name?: string
  task_title?: string
}

export const useExtractionTaskStore = defineStore('extractionTasks', () => {
  const tasks = ref<Record<string, TrackedExtractionTask>>({})
  const polling = ref(false)
  const consecutiveFailures = ref(0)
  let pollTimer: ReturnType<typeof setTimeout> | null = null

  const activeTasks = computed(() => Object.values(tasks.value).filter(task => (
    ACTIVE_STATUSES.includes(task.status)
  )))

  function fromJob(job: ExtractionJob, context: TaskContext): TrackedExtractionTask {
    return {
      id: job.id,
      session_id: job.session_id,
      status: job.status,
      generation_no: job.generation_no,
      retry_count: job.retry_count,
      max_retries: job.max_retries,
      candidate_count: 0,
      error_code: job.error_code,
      error_message: job.error_message,
      created_at: job.created_at,
      started_at: job.started_at,
      completed_at: job.completed_at,
      user_name: context.user_name ?? '',
      task_title: context.task_title ?? '',
      notified_terminal: TERMINAL_STATUSES.includes(job.status),
      last_checked_at: Date.now()
    }
  }

  function track(job: ExtractionJob, context: TaskContext = {}) {
    const existing = tasks.value[job.id]
    tasks.value = {
      ...tasks.value,
      [job.id]: existing
        ? {
            ...existing,
            user_name: context.user_name || existing.user_name,
            task_title: context.task_title || existing.task_title
          }
        : fromJob(job, context)
    }
    if (ACTIVE_STATUSES.includes(job.status)) schedulePoll(0)
  }

  function trackMany(items: Array<{ job: ExtractionJob; context?: TaskContext }>) {
    items.forEach(item => track(item.job, item.context))
  }

  function displaySubject(task: TrackedExtractionTask) {
    const parts = [task.user_name, task.task_title].filter(Boolean)
    return parts.length ? `${parts.join('·')}的` : ''
  }

  function applyStatus(status: ExtractionJobStatus) {
    const existing = tasks.value[status.id]
    if (!existing) return
    const wasActive = ACTIVE_STATUSES.includes(existing.status)
    const becameTerminal = wasActive && TERMINAL_STATUSES.includes(status.status)
    const next: TrackedExtractionTask = {
      ...existing,
      ...status,
      last_checked_at: Date.now()
    }
    if (becameTerminal && !existing.notified_terminal) {
      next.notified_terminal = true
      if (status.status === 'reviewing' || status.status === 'reviewed') {
        notify(
          `${displaySubject(next)}抽取版本 V${status.generation_no} 已生成，共 ${status.candidate_count} 条候选。`,
          'success',
          6500
        )
      } else if (status.status === 'failed') {
        notify(
          `${displaySubject(next)}抽取版本 V${status.generation_no} 生成失败：${status.error_message || '请检查模型服务后重试'}`,
          'danger',
          8000
        )
      }
      void useNotificationStore().refreshCount()
    }
    tasks.value = { ...tasks.value, [status.id]: next }
  }

  async function pollNow() {
    if (polling.value || !navigator.onLine) {
      schedulePoll(document.visibilityState === 'visible' ? 5_000 : 15_000)
      return
    }
    const ids = activeTasks.value.map(task => task.id)
    if (!ids.length) {
      stopTimer()
      return
    }
    polling.value = true
    try {
      for (let offset = 0; offset < ids.length; offset += 50) {
        const response = await extractionApi.jobStatuses(ids.slice(offset, offset + 50))
        response.data.items.forEach(applyStatus)
      }
      consecutiveFailures.value = 0
    } catch {
      consecutiveFailures.value += 1
    } finally {
      polling.value = false
    }
    if (activeTasks.value.length) {
      const base = document.visibilityState === 'visible' ? 3_000 : 12_000
      const backoff = Math.min(30_000, base * Math.max(1, consecutiveFailures.value))
      schedulePoll(backoff)
    } else {
      stopTimer()
    }
  }

  function schedulePoll(delay = 3_000) {
    if (pollTimer) clearTimeout(pollTimer)
    pollTimer = setTimeout(() => void pollNow(), delay)
  }

  function stopTimer() {
    if (pollTimer) clearTimeout(pollTimer)
    pollTimer = null
  }

  function clear() {
    stopTimer()
    tasks.value = {}
    polling.value = false
    consecutiveFailures.value = 0
  }

  function resume() {
    if (activeTasks.value.length) schedulePoll(0)
  }

  return {
    tasks,
    activeTasks,
    polling,
    track,
    trackMany,
    pollNow,
    resume,
    clear
  }
}, {
  persist: {
    key: 'metacognition_extraction_tasks',
    storage: sessionStorage,
    pick: ['tasks']
  }
})
