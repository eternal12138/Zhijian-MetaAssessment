import apiClient from './client'

export type NotificationType = 'assessment' | 'report' | 'review' | 'security' | 'system'

export interface AppNotification {
  id: string
  type: NotificationType
  title: string
  content: string
  target_url: string
  priority: 'normal' | 'important'
  is_read: boolean
  metadata: Record<string, unknown> | null
  created_at: string
  read_at: string | null
}

export const notificationApi = {
  list(limit = 20, unreadOnly = false) {
    return apiClient.get<AppNotification[]>('/notifications', {
      params: { limit, unread_only: unreadOnly }
    })
  },

  unreadCount() {
    return apiClient.get<{ count: number }>('/notifications/unread-count')
  },

  markRead(id: string) {
    return apiClient.patch<AppNotification>(`/notifications/${id}/read`)
  },

  markAllRead() {
    return apiClient.post<{ updated: number }>('/notifications/read-all')
  }
}
