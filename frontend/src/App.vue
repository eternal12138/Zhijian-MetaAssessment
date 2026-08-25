<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'
import { useUserStore } from './stores/user'
import { adminApi } from './api/admin'
import { authApi } from './api/auth'
import NotificationButton from './components/topbar/NotificationButton.vue'
import UserMenu from './components/topbar/UserMenu.vue'
import { useNotificationStore } from './stores/notification'
import { useExtractionTaskStore } from './stores/extractionTasks'
import { roleHome } from './utils/roleNavigation'
import AppModal from './components/ui/AppModal.vue'
import AppFeedbackHost from './components/feedback/AppFeedbackHost.vue'
import { useTheme } from './composables/useTheme'
import ThemePreferenceBanner from './components/ui/ThemePreferenceBanner.vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const userStore = useUserStore()
const notificationStore = useNotificationStore()
const extractionTaskStore = useExtractionTaskStore()
const { theme, toggleTheme, initTheme } = useTheme()

const sidebarOpen = ref(false)
const homePath = computed(() => roleHome(authStore.userRole))
const isShelllessPage = computed(() => route.name === 'Login' || route.name === 'Cosmos')
const isStaffWorkspace = computed(() => ['teacher', 'admin'].includes(authStore.userRole || ''))
const activeTopbarMenu = ref<'notifications' | 'user' | null>(null)

// ---- 默认密码修改提醒（登录后弹一次，刷新不重复）----
const showPwdModal = ref(false)
const newPwd = ref('')
const showNewPwd = ref(false)
const pwdError = ref('')
const pwdLoading = ref(false)
const contentRevision = ref(0)

const pwdStrength = computed(() => {
  const p = newPwd.value
  if (!p) return { score: 0, label: '', class: '' }
  let score = 0
  if (p.length >= 6) score++
  if (/[a-zA-Z]/.test(p) && /\d/.test(p)) score++
  if (/[^a-zA-Z0-9]/.test(p) || p.length >= 10) score++
  if (score <= 1) return { score: 1, label: '弱 (建议包含字母与数字)', class: 'strength-weak', textClass: 'text-weak' }
  if (score === 2) return { score: 2, label: '中 (可加入特殊字符提升安全性)', class: 'strength-medium', textClass: 'text-medium' }
  return { score: 3, label: '强', class: 'strength-strong', textClass: 'text-strong' }
})

function passwordChangeDeferredForCurrentToken() {
  const token = localStorage.getItem('access_token')
  if (!token) return false
  try {
    const payloadPart = token.split('.')[1]
    if (!payloadPart) return false
    const normalized = payloadPart.replace(/-/g, '+').replace(/_/g, '/')
    const padded = normalized.padEnd(
      normalized.length + (4 - normalized.length % 4) % 4,
      '='
    )
    const payload = JSON.parse(atob(padded)) as {
      password_change_deferred?: boolean
    }
    return payload.password_change_deferred === true
  } catch {
    return false
  }
}

if (
  authStore.isLoggedIn
  && localStorage.getItem('needs_password_change') === 'true'
  && !passwordChangeDeferredForCurrentToken()
) {
  showPwdModal.value = true
}

watch(
  () => [authStore.isLoggedIn, authStore.sessionRevision] as const,
  ([loggedIn]) => {
  if (
    loggedIn
    && localStorage.getItem('needs_password_change') === 'true'
    && !passwordChangeDeferredForCurrentToken()
  ) {
    showPwdModal.value = true
  }
  }
)

function refreshNotificationsWhenActive() {
  if (
    authStore.isLoggedIn
    && localStorage.getItem('offline_mode') !== 'true'
    && document.visibilityState === 'visible'
  ) {
    void notificationStore.refreshCount()
  }
}

watch(() => [authStore.isLoggedIn, authStore.sessionRevision] as const, ([loggedIn]) => {
  if (loggedIn && localStorage.getItem('offline_mode') !== 'true') {
    // 清掉前一登录会话的缓存，防止同一浏览器切换账号时短暂显示旧消息。
    notificationStore.clear()
    // 登录成功后立即读取消息，不再等待用户点击通知按钮。
    void notificationStore.load(10)
    notificationStore.startPolling()
    extractionTaskStore.resume()
  } else {
    notificationStore.clear()
    extractionTaskStore.clear()
  }
}, { immediate: true })

// ---- 页面初始化与刷新验证 ----
onMounted(async () => {
  initTheme()
  window.addEventListener('focus', refreshNotificationsWhenActive)
  document.addEventListener('visibilitychange', refreshNotificationsWhenActive)
  if (!authStore.isLoggedIn) return
  if (localStorage.getItem('offline_mode') === 'true') return
  if (
    localStorage.getItem('needs_password_change') === 'true'
    && !passwordChangeDeferredForCurrentToken()
  ) {
    showPwdModal.value = true
    return
  }
  try {
    const response = await authApi.me()
    const user = response.data as { must_change_password?: boolean }
    if (
      user.must_change_password
      && !passwordChangeDeferredForCurrentToken()
    ) {
      localStorage.setItem('needs_password_change', 'true')
      showPwdModal.value = true
    } else {
      localStorage.removeItem('needs_password_change')
    }
  } catch {
    authStore.logout()  // 内部已统一清理 token 和模式标记
    router.push('/login')
  }
})

onBeforeUnmount(() => {
  notificationStore.stopPolling()
  extractionTaskStore.clear()
  window.removeEventListener('focus', refreshNotificationsWhenActive)
  document.removeEventListener('visibilitychange', refreshNotificationsWhenActive)
})

async function handleChangePwd() {
  if (newPwd.value.length < 6) { pwdError.value = '密码至少6位'; return }
  if (newPwd.value === '123456') { pwdError.value = '不能使用默认密码'; return }
  pwdLoading.value = true
  try {
    const response = await adminApi.changeOwnPassword(newPwd.value)
    localStorage.setItem('access_token', response.data.access_token)
    localStorage.removeItem('needs_password_change')
    showPwdModal.value = false
    contentRevision.value += 1
    void notificationStore.load(10)
    newPwd.value = ''
    pwdError.value = ''
  } catch (e: unknown) {
    pwdError.value = e instanceof Error ? e.message : '修改失败'
  } finally {
    pwdLoading.value = false
  }
}

async function handleSkipPwd() {
  pwdLoading.value = true
  pwdError.value = ''
  try {
    if (localStorage.getItem('offline_mode') !== 'true') {
      const response = await authApi.skipPasswordChange()
      localStorage.setItem('access_token', response.data.access_token)
    }
    localStorage.removeItem('needs_password_change')
    showPwdModal.value = false
    contentRevision.value += 1
    void notificationStore.load(10)
    newPwd.value = ''
  } catch (e: unknown) {
    pwdError.value = e instanceof Error ? e.message : '操作失败'
  } finally {
    pwdLoading.value = false
  }
}

// ---- 角色感知菜单 ----
interface MenuItem { to: string; label: string; icon: string; roles: string[] }

const allMenuItems: MenuItem[] = [
  { to: '/', label: '学习概览', icon: 'bi-grid-1x2-fill', roles: ['student'] },
  { to: '/assessment', label: '开始测评', icon: 'bi-chat-square-text-fill', roles: ['student'] },
  { to: '/report', label: '我的报告', icon: 'bi-bar-chart-fill', roles: ['student'] },
  { to: '/teacher', label: '教师中心', icon: 'bi-mortarboard-fill', roles: ['teacher'] },
  { to: roleHome('admin'), label: '系统与研究概览', icon: 'bi-speedometer2', roles: ['admin'] },
  { to: '/candidate-review', label: '候选片段复核', icon: 'bi-soundwave', roles: ['teacher', 'admin'] },
  { to: '/ai-evaluation', label: 'AI 评估', icon: 'bi-stars', roles: ['teacher', 'admin'] },
  { to: '/review', label: '双人盲编与仲裁', icon: 'bi-check2-square', roles: ['teacher', 'admin'] },
  { to: '/transcripts', label: '转录校订', icon: 'bi-file-earmark-text-fill', roles: ['teacher', 'admin'] },
  { to: '/users', label: '用户管理', icon: 'bi-people-fill', roles: ['admin'] },
  { to: '/data-management', label: '数据管理', icon: 'bi-database-fill-gear', roles: ['admin'] },
  { to: '/model-services', label: '模型服务状态', icon: 'bi-activity', roles: ['admin'] },
  { to: '/admin', label: '研究管理', icon: 'bi-sliders2-vertical', roles: ['admin'] }
]

const visibleMenu = computed(() =>
  allMenuItems.filter(item =>
    authStore.userRole && item.roles.includes(authStore.userRole)
  )
)

const sidebarIdentity = computed(() => {
  if (authStore.userRole === 'admin') {
    return {
      label: '系统管理工作台',
      supportTitle: '管理员模式',
      supportText: '管理研究流程、用户与系统配置',
      icon: 'bi-shield-lock'
    }
  }
  if (authStore.userRole === 'teacher') {
    return {
      label: '教师研究工作台',
      supportTitle: '教师模式',
      supportText: '仅显示有权管理的班级与测评',
      icon: 'bi-person-video3'
    }
  }
  return {
    label: '学生测评空间',
    supportTitle: '隐私保护声明',
    supportText: '语音与报告等数据仅用于测评研究',
    icon: 'bi-shield-check'
  }
})

watch(() => route.fullPath, () => {
  sidebarOpen.value = false
  activeTopbarMenu.value = null
  refreshNotificationsWhenActive()
})

function handleLogout() {
  activeTopbarMenu.value = null
  notificationStore.clear()
  extractionTaskStore.clear()
  showPwdModal.value = false
  authStore.logout()  // 统一清理 token、模式标记及所有 Pinia 持久化 key
  userStore.signOut()
  router.push('/login')
}
</script>

<template>
  <!-- 登录页：纯页面，无侧边栏/顶栏 -->
  <RouterView v-if="isShelllessPage" />

  <!-- 其他页面：完整布局 -->
  <div v-else class="app-shell">
    <Transition name="sidebar-backdrop">
      <button
        v-if="sidebarOpen"
        class="sidebar-backdrop"
        aria-label="关闭导航菜单"
        @click="sidebarOpen = false"
      />
    </Transition>
    <aside class="sidebar" :class="{ 'is-open': sidebarOpen }">
      <div class="brand">
        <button
          class="brand-cosmos-trigger"
          type="button"
          title="探索星空"
          aria-label="进入太阳系模拟彩蛋"
          @click="router.push('/cosmos')"
        >
          <img class="brand-logo-img" src="/logo.png" alt="知见 Logo" />
        </button>
        <RouterLink class="brand-home-link" :to="homePath" @click="sidebarOpen = false">
          <span><strong>知见</strong><small>AI 元认知测评</small></span>
        </RouterLink>
      </div>
      <div class="sidebar-menu-scroll">
        <div class="sidebar-label">{{ sidebarIdentity.label }}</div>
        <nav class="nav flex-column gap-1">
          <RouterLink
            v-for="item in visibleMenu"
            :key="`${item.to}-${item.label}`"
            :to="item.to"
            class="nav-link"
            @click="sidebarOpen = false"
          >
            <i class="bi" :class="item.icon"></i>{{ item.label }}
          </RouterLink>
        </nav>
      </div>
      <div class="sidebar-support">
        <i class="bi" :class="sidebarIdentity.icon"></i>
        <div>
          <strong>{{ sidebarIdentity.supportTitle }}</strong>
          <span>{{ sidebarIdentity.supportText }}</span>
        </div>
      </div>
      <button class="btn btn-sm btn-outline-secondary mt-2 mx-2" @click="handleLogout">
        <i class="bi bi-box-arrow-right me-1"></i>退出登录
      </button>
    </aside>
    <div class="content-shell">
      <header class="topbar">
        <button
          class="btn sidebar-toggle"
          aria-label="打开导航菜单"
          :aria-expanded="sidebarOpen"
          @click="sidebarOpen = !sidebarOpen"
        ><i class="bi bi-list"></i></button>
        <div class="topbar-actions">
          <button
            class="btn icon-button theme-toggle-btn"
            type="button"
            :aria-label="theme === 'dark' ? '切换为浅色模式' : '切换为深色模式'"
            :title="theme === 'dark' ? '切换为浅色模式' : '切换为深色模式'"
            @click="toggleTheme"
          >
            <i class="bi" :class="theme === 'dark' ? 'bi-sun-fill text-warning' : 'bi-moon-stars-fill'" />
          </button>
          <NotificationButton
            :open="activeTopbarMenu === 'notifications'"
            @toggle="activeTopbarMenu = activeTopbarMenu === 'notifications' ? null : 'notifications'"
            @close="activeTopbarMenu = null"
          />
          <UserMenu
            :open="activeTopbarMenu === 'user'"
            @toggle="activeTopbarMenu = activeTopbarMenu === 'user' ? null : 'user'"
            @close="activeTopbarMenu = null"
            @logout="handleLogout"
          />
        </div>
      </header>
      <main v-if="!showPwdModal" class="page-content">
        <aside v-if="isStaffWorkspace" class="mobile-workbench-note" role="note">
          <i class="bi bi-display" aria-hidden="true" />
          <div>
            <strong>当前为移动端简化视图</strong>
            <span>表格可左右滑动查看，部分操作列可能需要继续向右滑动。批量编辑、模型训练和数据导出等复杂操作，推荐使用电脑端浏览器以获得最佳体验。</span>
          </div>
        </aside>
        <RouterView v-slot="{ Component }">
          <Transition name="page-fade">
            <component :is="Component" :key="`${route.fullPath}:${contentRevision}`" />
          </Transition>
        </RouterView>
      </main>
    </div>
  </div>

  <!-- 默认密码修改提醒 -->
  <AppModal
    :open="showPwdModal"
    title="安全提醒"
    icon="bi-shield-exclamation"
    :close-on-backdrop="false"
    :close-on-esc="false"
  >
    <p class="text-muted small mb-3">
      您当前使用的是初始或重置密码。建议修改为独立密码；暂不修改仅对本次登录有效，
      下次登录仍会提醒，直到您完成密码修改。
    </p>
    <div class="mb-3">
      <label class="form-label-sm" for="initial-password-change">新密码</label>
      <div class="input-with-action">
        <input
          id="initial-password-change"
          v-model="newPwd"
          :type="showNewPwd ? 'text' : 'password'"
          class="form-control form-control-sm"
          placeholder="至少6位，不能为默认密码"
          :aria-describedby="pwdError ? 'initial-password-error' : undefined"
          autocomplete="new-password"
          @keyup.enter="handleChangePwd"
        />
        <button
          v-if="newPwd"
          type="button"
          class="input-action-btn"
          :aria-label="showNewPwd ? '隐藏密码' : '显示密码'"
          :title="showNewPwd ? '隐藏密码' : '显示密码'"
          @click="showNewPwd = !showNewPwd"
        >
          <i class="bi" :class="showNewPwd ? 'bi-eye-slash-fill' : 'bi-eye-fill'"></i>
        </button>
      </div>
      <div v-if="newPwd" class="password-strength-wrap">
        <div class="password-strength-bar">
          <div class="password-strength-fill" :class="pwdStrength.class"></div>
        </div>
        <div class="password-strength-hint">
          <span>密码强度</span>
          <strong :class="pwdStrength.textClass">{{ pwdStrength.label }}</strong>
        </div>
      </div>
    </div>
    <p v-if="pwdError" id="initial-password-error" class="text-danger small mb-2" role="alert">{{ pwdError }}</p>
    <template #footer>
      <div class="d-flex gap-2 justify-content-end w-100">
        <button class="btn btn-sm btn-outline-secondary" :disabled="pwdLoading" @click="handleSkipPwd">
          暂不修改
        </button>
        <button class="btn btn-sm btn-primary" :disabled="pwdLoading" @click="handleChangePwd">
          <span v-if="pwdLoading" class="spinner-border spinner-border-sm me-1"></span>
          确认修改
        </button>
      </div>
    </template>
  </AppModal>
  <ThemePreferenceBanner v-if="route.name !== 'Cosmos'" />
  <AppFeedbackHost />
</template>
