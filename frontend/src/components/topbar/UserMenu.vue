<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useUserStore } from '../../stores/user'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ toggle: []; close: []; logout: [] }>()
const userStore = useUserStore()
const rootRef = ref<HTMLElement | null>(null)
const roleLabel = computed(() => ({
  student: '学生账号',
  teacher: '教师账号',
  admin: '系统管理员'
}[userStore.profile.role]))

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
  <div ref="rootRef" class="user-menu-root">
    <button
      class="profile-button"
      aria-label="打开用户菜单"
      aria-controls="user-menu-panel"
      :aria-expanded="open"
      @click="emit('toggle')"
    >
      <span class="avatar">{{ userStore.profile.avatarText }}</span>
      <span class="d-none d-sm-inline">{{ userStore.profile.name }}</span>
      <i class="bi bi-chevron-down small" :class="{ rotated: open }" />
    </button>
    <Transition name="topbar-popover">
      <div v-if="open" id="user-menu-panel" class="user-menu-panel" role="menu">
        <div class="user-summary">
          <span class="avatar large">{{ userStore.profile.avatarText }}</span>
          <div><strong>{{ userStore.profile.name }}</strong><small>{{ roleLabel }}</small></div>
        </div>
        <nav>
          <RouterLink to="/account" role="menuitem" @click="emit('close')"><i class="bi bi-person" />个人信息与安全</RouterLink>
          <RouterLink to="/privacy" role="menuitem" @click="emit('close')"><i class="bi bi-shield-check" />隐私与数据说明</RouterLink>
          <RouterLink to="/help" role="menuitem" @click="emit('close')"><i class="bi bi-question-circle" />帮助与使用指南</RouterLink>
        </nav>
        <button class="logout-item" role="menuitem" @click="emit('logout')">
          <i class="bi bi-box-arrow-right" />退出登录
        </button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.user-menu-root { position: relative; }
.profile-button .bi-chevron-down { transition: transform var(--motion-popover) var(--ease-out); }
.profile-button .rotated { transform: rotate(180deg); }
.user-menu-panel {
  position: absolute;
  z-index: 1050;
  top: calc(100% + 12px);
  right: 0;
  width: 250px;
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
.user-summary { display: flex; align-items: center; gap: .75rem; padding: 1rem; background: var(--color-surface-subtle); }
.avatar.large { width: 42px; height: 42px; }
.user-summary div { display: grid; }
.user-summary strong { color: var(--color-text); }
.user-summary small { color: var(--color-text-muted); font-size: .72rem; }
.user-menu-panel nav { padding: .45rem; }
.user-menu-panel a, .logout-item {
  min-height: 42px;
  width: 100%;
  display: flex;
  align-items: center;
  gap: .7rem;
  padding: .7rem .75rem;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--color-text-secondary);
  font-size: .82rem;
  text-decoration: none;
  text-align: left;
  transition: color var(--motion-fast) ease, background-color var(--motion-fast) ease;
}
.user-menu-panel a:hover, .user-menu-panel a:focus-visible { background: var(--color-primary-soft); color: var(--color-primary); }
.logout-item { border-radius: 0; border-top: 1px solid var(--color-border); color: var(--color-danger); padding: .85rem 1.2rem; }
.logout-item:hover, .logout-item:focus-visible { background: var(--color-danger-soft); color: var(--color-danger); }
@media (max-width: 575.98px) {
  .user-menu-panel {
    position: fixed;
    top: 64px;
    right: 8px;
    left: 8px;
    width: auto;
    max-height: calc(100dvh - 76px);
    overflow-y: auto;
  }
  .user-menu-panel a, .logout-item { min-height: 44px; }
}
@media (prefers-reduced-motion: reduce) {
  .profile-button .bi-chevron-down { transition: none; }
  .topbar-popover-enter-active,
  .topbar-popover-leave-active { transition: opacity 150ms ease; }
  .topbar-popover-enter-from,
  .topbar-popover-leave-to { transform: none; }
}
</style>
