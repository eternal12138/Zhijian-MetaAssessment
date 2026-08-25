import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { AssessmentProgress } from '../types/assessment'

const STORAGE_KEY = 'mc-assessment'

const initialProgress: AssessmentProgress = {
  sessionId: null,
  taskTitle: '最优投球机判断',
  status: 'not_started',
  currentStep: 1,
  totalSteps: 4,
  elapsedMinutes: 0
}

export const useAssessmentStore = defineStore('assessment', () => {
  const progress = ref<AssessmentProgress>({ ...initialProgress })
  const completionRate = computed(() => Math.round((progress.value.currentStep / progress.value.totalSteps) * 100))

  function startSession(sessionId: string, taskTitle: string) {
    progress.value = { ...initialProgress, sessionId, taskTitle, status: 'in_progress' }
  }

  function updateStep(step: number) { progress.value.currentStep = Math.min(Math.max(step, 1), progress.value.totalSteps) }
  function addElapsedMinute() { progress.value.elapsedMinutes += 1 }
  function completeSession() { progress.value.status = 'completed'; progress.value.currentStep = progress.value.totalSteps }
  function reset() {
    progress.value = { ...initialProgress, sessionId: null, status: 'not_started', currentStep: 0 }
    // 清除持久化缓存，避免刷新后恢复已放弃的会话
    try { localStorage.removeItem(STORAGE_KEY) } catch { /* noop */ }
  }

  return { progress, completionRate, startSession, updateStep, addElapsedMinute, completeSession, reset }
}, {
  persist: {
    key: STORAGE_KEY,
    storage: localStorage,
    pick: ['progress']   // 仅持久化 progress，其他 computed 不缓存
  }
})
