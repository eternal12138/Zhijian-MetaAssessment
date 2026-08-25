<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useNotificationStore } from '../../stores/notification'
import type { AppNotification } from '../../api/notifications'
import { parseApiDate } from '../../utils/datetime'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ toggle: []; close: [] }>()
const router = useRouter()
const store = useNotificationStore()
const rootRef = ref<HTMLElement | null>(null)

const icons: Record<string, string> = {
  assessment: 'bi-clipboard-check',
  report: 'bi-bar-chart',
  review: 'bi-check2-square',
  security: 'bi-shield-lock',
  system: 'bi-info-circle'
}

watch(() => props.open, open => {
  if (open) void store.load(10)
})

function formatTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).format(parseApiDate(value))
}

async function openNotification(item: AppNotification) {
  try {
    await store.markRead(item.id)
  } finally {
    emit('close')
    await router.push(item.target_url)
  }
}

async function openCenter() {
  emit('close')
  await router.push('/notifications')
}

function handleDocumentPointer(event: MouseEvent) {
  if (props.open && !rootRef.value?.contains(event.target as Node)) emit('close')
}

function handleKeydown(event: KeyboardEvent) {
  if (props.open && event.key === 'Escape') emit('close')
}

onMounted(() => {
  document.addEventListener('mousedown', handleDocumentPointer)
  document.addEventListener('keydown', handleKeydown)
})
onBeforeUnmount(() => {
  document.removeEventListener('mousedown', handleDocumentPointer)
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <div ref="rootRef" class="notification-root">
    <button
      class="icon-button"
      aria-label="消息通知"
      aria-controls="notification-panel"
      :aria-expanded="open"
      @click="emit('toggle')"
    >
      <i class="bi bi-bell" />
      <span v-if="store.unreadCount" class="notification-badge">{{ store.badgeText }}</span>
    </button>

    <Transition name="topbar-popover">
      <section
        v-if="open"
        id="notification-panel"
        class="notification-panel"
        aria-label="最近消息"
      >
      <header>
        <strong>消息通知</strong>
        <button
          v-if="store.unreadCount"
          class="btn btn-link btn-sm p-0"
          @click="store.markAllRead"
        >
          全部已读
        </button>
      </header>
      <div v-if="store.isLoading" class="panel-state">
        <span class="spinner-border spinner-border-sm text-primary" /> 正在加载
      </div>
      <div v-else-if="store.errorMessage" class="panel-state text-danger">
        {{ store.errorMessage }}
        <button class="btn btn-link btn-sm" @click="store.load(10)">重试</button>
      </div>
      <div v-else-if="!store.items.length" class="panel-state text-muted">
        <i class="bi bi-bell-slash d-block fs-4 mb-2" />暂无消息
      </div>
      <div v-else class="notification-list">
        <button
          v-for="item in store.items"
          :key="item.id"
          class="notification-item"
          :class="{ unread: !item.is_read, important: item.priority === 'important' }"
          @click="openNotification(item)"
        >
          <span class="notification-icon"><i class="bi" :class="icons[item.type] ?? icons.system" /></span>
          <span class="notification-copy">
            <strong>{{ item.title }}</strong>
            <span>{{ item.content }}</span>
            <small>{{ formatTime(item.created_at) }}</small>
          </span>
        </button>
      </div>
      <footer><button class="btn btn-link btn-sm" @click="openCenter">查看全部消息</button></footer>
      </section>
    </Transition>
  </div>
</template>

<style scoped>
.notification-root { position: relative; }
.notification-badge {
  position: absolute;
  top: -5px;
  right: -7px;
  min-width: 18px;
  height: 18px;
  padding: 0 4px;
  display: grid;
  place-items: center;
  border: 2px solid var(--color-surface);
  border-radius: 10px;
  background: #ff4747;
  color: #fff;
  font-size: 9px;
  font-weight: 700;
}
.notification-panel {
  position: absolute;
  z-index: 1050;
  top: calc(100% + 12px);
  right: 0;
  width: min(390px, calc(100vw - 24px));
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: var(--shadow-md);
  transform-origin: top right;
}
.topbar-popover-enter-active,
.topbar-popover-leave-active {
  transition: opacity var(--motion-popover) var(--ease-out), transform var(--motion-popover) var(--ease-out);
}
.topbar-popover-enter-from,
.topbar-popover-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(.97);
}
.notification-panel header, .notification-panel footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: .85rem 1rem;
  border-bottom: 1px solid var(--color-border);
}
.notification-panel footer { justify-content: center; border-top: 1px solid var(--color-border); border-bottom: 0; }
.notification-list { max-height: 390px; overflow-y: auto; }
.notification-item {
  width: 100%;
  display: flex;
  gap: .75rem;
  padding: .9rem 1rem;
  border: 0;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-text);
  text-align: left;
  transition: background-color var(--motion-fast) ease;
}
.notification-item:hover, .notification-item:focus-visible { background: var(--color-surface-subtle); }
.notification-item.unread { background: var(--color-primary-soft); }
.notification-item.unread .notification-copy strong::after {
  content: "";
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-left: 6px;
  border-radius: 50%;
  background: var(--color-primary);
}
.notification-icon {
  flex: 0 0 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--color-primary-soft);
  color: var(--color-primary);
}
.notification-item.important .notification-icon { background: var(--color-warning-soft); color: var(--color-warning); }
.notification-copy { min-width: 0; display: grid; gap: .2rem; }
.notification-copy strong { font-size: .84rem; color: var(--color-text); }
.notification-copy > span { color: var(--color-text-secondary); font-size: .76rem; line-height: 1.45; }
.notification-copy small { color: var(--color-text-muted); font-size: .68rem; }
.panel-state { padding: 2rem 1rem; text-align: center; font-size: .82rem; color: var(--color-text-muted); }
@media (max-width: 575.98px) {
  .notification-panel {
    position: fixed;
    top: 64px;
    right: 8px;
    left: 8px;
    width: auto;
    max-height: calc(100dvh - 76px);
  }
  .notification-list { max-height: calc(100dvh - 190px); }
}
@media (prefers-reduced-motion: reduce) {
  .topbar-popover-enter-active,
  .topbar-popover-leave-active { transition: opacity 150ms ease; }
  .topbar-popover-enter-from,
  .topbar-popover-leave-to { transform: none; }
}
</style>
