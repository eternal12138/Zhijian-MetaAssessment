<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useNotificationStore } from '../stores/notification'
import type { AppNotification } from '../api/notifications'
import { parseApiDate } from '../utils/datetime'

const store = useNotificationStore()
const router = useRouter()
const icons: Record<string, string> = {
  assessment: 'bi-clipboard-check',
  report: 'bi-bar-chart',
  review: 'bi-check2-square',
  security: 'bi-shield-lock',
  system: 'bi-info-circle'
}
function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit'
  }).format(parseApiDate(value))
}
async function openItem(item: AppNotification) {
  await store.markRead(item.id)
  await router.push(item.target_url)
}
onMounted(() => store.load(100))
</script>

<template>
  <div class="center-page">
    <div class="d-flex justify-content-between align-items-start gap-3 mb-4">
      <div><h3>消息中心</h3><p class="text-muted mb-0">测评、报告、复核和账号安全提醒。</p></div>
      <button v-if="store.unreadCount" class="btn btn-outline-primary btn-sm" @click="store.markAllRead">全部标为已读</button>
    </div>
    <div v-if="store.errorMessage" class="alert alert-danger">{{ store.errorMessage }}</div>
    <div v-if="store.isLoading" class="card border-0 shadow-sm"><div class="card-body py-5 text-center"><div class="spinner-border text-primary" /></div></div>
    <div v-else-if="!store.items.length" class="card border-0 shadow-sm">
      <div class="card-body py-5 text-center"><i class="bi bi-bell-slash display-5 text-muted" /><h5 class="mt-3">暂无消息</h5></div>
    </div>
    <div v-else class="card border-0 shadow-sm overflow-hidden">
      <button
        v-for="item in store.items"
        :key="item.id"
        class="center-item"
        :class="{ unread: !item.is_read }"
        @click="openItem(item)"
      >
        <span class="item-icon"><i class="bi" :class="icons[item.type] ?? icons.system" /></span>
        <span class="item-copy"><strong>{{ item.title }}</strong><span>{{ item.content }}</span><small>{{ formatDate(item.created_at) }}</small></span>
        <i class="bi bi-chevron-right text-muted" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.center-page { max-width: 900px; margin: 0 auto; }
.card { border-radius: var(--radius-lg); }
.center-item { width: 100%; display: flex; align-items: center; gap: 1rem; padding: 1rem 1.25rem; border: 0; border-bottom: 1px solid var(--color-border); background: var(--color-surface); color: var(--color-text); text-align: left; transition: background-color var(--motion-fast) ease; }
.center-item:hover { background: var(--color-surface-subtle); }
.center-item.unread { background: var(--color-primary-soft); }
.item-icon { flex: 0 0 42px; height: 42px; display: grid; place-items: center; border-radius: 50%; background: var(--color-primary-soft); color: var(--color-primary); }
.item-copy { min-width: 0; flex: 1; display: grid; gap: .2rem; }
.item-copy > span { color: var(--color-text-secondary); font-size: .82rem; }
.item-copy small { color: var(--color-text-muted); font-size: .72rem; }
@media (max-width: 575.98px) {
  .center-page > .d-flex { flex-wrap: wrap; }
  .center-item { align-items: flex-start; gap: .75rem; padding: .9rem; }
  .item-icon { flex-basis: 36px; height: 36px; }
  .item-copy strong, .item-copy > span { overflow-wrap: anywhere; }
}
</style>
