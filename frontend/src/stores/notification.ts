import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { notificationApi, type AppNotification } from '../api/notifications'

export const useNotificationStore = defineStore('notification', () => {
  const items = ref<AppNotification[]>([])
  const unreadCount = ref(0)
  const isLoading = ref(false)
  const errorMessage = ref('')
  let pollingTimer: ReturnType<typeof setInterval> | null = null
  let countRequest: { revision: number; promise: Promise<void> } | null = null
  let stateRevision = 0

  const badgeText = computed(() =>
    unreadCount.value > 99 ? '99+' : String(unreadCount.value)
  )

  async function refreshCount() {
    const revision = stateRevision
    if (countRequest?.revision === revision) return countRequest.promise
    const request = (async () => {
      try {
        const response = await notificationApi.unreadCount()
        if (revision === stateRevision) {
          unreadCount.value = response.data.count
        }
      } catch {
        // 后台刷新失败不打断用户当前页面。
      }
    })()
    countRequest = { revision, promise: request }
    try {
      await request
    } finally {
      if (countRequest?.promise === request) {
        countRequest = null
      }
    }
  }

  async function load(limit = 10) {
    const revision = stateRevision
    isLoading.value = true
    errorMessage.value = ''
    try {
      const response = await notificationApi.list(limit)
      if (revision !== stateRevision) return
      items.value = response.data
      unreadCount.value = items.value.filter(item => !item.is_read).length
      await refreshCount()
    } catch (error) {
      if (revision === stateRevision) {
        errorMessage.value = error instanceof Error ? error.message : '消息加载失败'
      }
    } finally {
      if (revision === stateRevision) {
        isLoading.value = false
      }
    }
  }

  async function markRead(id: string) {
    const item = items.value.find(current => current.id === id)
    if (!item || item.is_read) return
    await notificationApi.markRead(id)
    item.is_read = true
    unreadCount.value = Math.max(0, unreadCount.value - 1)
  }

  async function markAllRead() {
    await notificationApi.markAllRead()
    items.value.forEach(item => { item.is_read = true })
    unreadCount.value = 0
  }

  function startPolling() {
    if (pollingTimer) return
    void refreshCount()
    pollingTimer = setInterval(() => {
      if (document.visibilityState === 'visible' && navigator.onLine) {
        void refreshCount()
      }
    }, 30_000)
  }

  function stopPolling() {
    if (pollingTimer) clearInterval(pollingTimer)
    pollingTimer = null
  }

  function clear() {
    stateRevision += 1
    stopPolling()
    items.value = []
    unreadCount.value = 0
    errorMessage.value = ''
  }

  return {
    items,
    unreadCount,
    badgeText,
    isLoading,
    errorMessage,
    refreshCount,
    load,
    markRead,
    markAllRead,
    startPolling,
    stopPolling,
    clear
  }
})
