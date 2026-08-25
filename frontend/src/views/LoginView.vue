<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useUserStore } from '../stores/user'
import { authApi } from '../api/auth'
import type { AppRole } from '../stores/auth'
import { roleHome } from '../utils/roleNavigation'
import { useTheme } from '../composables/useTheme'
import FluidAuroraBackground from '../components/ui/FluidAuroraBackground.vue'

const router = useRouter()
const authStore = useAuthStore()
const userStore = useUserStore()
const { theme, toggleTheme } = useTheme()

const username = ref('')
const password = ref('')
const isLoading = ref(false)
const errorMsg = ref('')
const isOfflineMode = ref(false)
const demoExpanded = ref(false)
const showPassword = ref(false)
const offlineDemoEnabled =
  import.meta.env.DEV && import.meta.env.VITE_ENABLE_OFFLINE_DEMO === 'true'

// ---- 演示账号（完全保留原本定义）----
const demos: Array<{ role: AppRole; user: string; pwd: string; name: string; icon: string }> = [
  { role: 'student', user: 'student', pwd: '123456', name: '闫羽馨（学生）', icon: 'bi-mortarboard' },
  { role: 'teacher', user: 'teacher', pwd: '123456', name: '王老师（教师）', icon: 'bi-person-workspace' },
  { role: 'admin',  user: 'admin',  pwd: '123456', name: '管理员',         icon: 'bi-shield-lock' }
]

function fillDemo(role: AppRole) {
  const d = demos.find(x => x.role === role)!
  username.value = d.user
  password.value = d.pwd
  errorMsg.value = ''
}

function tryOfflineLogin() {
  const u = username.value.trim()
  const p = password.value
  const match = demos.find(d => d.user === u && d.pwd === p)
  if (!match) throw new Error('账号或密码错误')
  return { role: match.role, displayName: match.name.replace(/（.*）$/, ''), id: 0 }
}

// ---- 登录：后端优先，不可用时自动离线（完全保留原本逻辑）----
async function handleLogin() {
  errorMsg.value = ''
  isOfflineMode.value = false

  if (!username.value.trim() || !password.value.trim()) {
    errorMsg.value = '请输入账号和密码'
    return
  }

  isLoading.value = true
  try {
    const res = await authApi.login({
      username: username.value.trim(),
      password: password.value
    })
    const role = res.data.user.role as AppRole
    if (res.data.user.must_change_password) {
      localStorage.setItem('needs_password_change', 'true')
    } else {
      localStorage.removeItem('needs_password_change')
    }
    localStorage.removeItem('offline_mode')
    localStorage.setItem('access_token', res.data.access_token)
    authStore.login(role)
    userStore.setProfile({
      id: String(res.data.user.id),
      name: res.data.user.name,
      role,
      avatarText: res.data.user.name.charAt(0)
    })
  } catch (err: unknown) {
    // 网络不可达 → 离线兜底
    const msg = err instanceof Error ? err.message : ''
    const isOffline = msg.includes('无法连接') || msg.includes('Network Error') || msg.includes('connect')

    if (isOffline && offlineDemoEnabled) {
      try {
        const demo = tryOfflineLogin()
        isOfflineMode.value = true
        localStorage.setItem('offline_mode', 'true')
        localStorage.removeItem('access_token')
        localStorage.setItem('needs_password_change', 'true')
        authStore.login(demo.role)
        userStore.setProfile({
          id: String(demo.id),
          name: demo.displayName,
          role: demo.role,
          avatarText: demo.displayName.charAt(0)
        })
      } catch (demoErr: unknown) {
        errorMsg.value = demoErr instanceof Error ? demoErr.message : '账号或密码错误'
        isLoading.value = false
        return
      }
    } else {
      errorMsg.value = err instanceof Error ? err.message : '登录失败，请检查网络连接'
      isLoading.value = false
      return
    }
  }
  isLoading.value = false
  const redirect = typeof router.currentRoute.value.query.redirect === 'string'
    ? router.currentRoute.value.query.redirect
    : roleHome(authStore.userRole)
  router.replace(redirect)
}
</script>

<template>
  <div class="login-page">
    <!-- 真实物理流光与流动极光画布背景 -->
    <FluidAuroraBackground />

    <!-- 右上角磨砂玻璃主题切换按钮 -->
    <button
      class="btn icon-button login-theme-btn"
      type="button"
      :aria-label="theme === 'dark' ? '切换为浅色模式' : '切换为深色模式'"
      :title="theme === 'dark' ? '切换为浅色模式' : '切换为深色模式'"
      @click="toggleTheme"
    >
      <i class="bi" :class="theme === 'dark' ? 'bi-sun-fill text-warning' : 'bi-moon-stars-fill'" />
    </button>

    <!-- 苹果风格类 VisionOS / macOS 悬浮毛玻璃登录卡片 -->
    <div class="login-card">
      <!-- 品牌标志 -->
      <div class="login-brand">
        <button
          class="login-cosmos-trigger"
          type="button"
          title="探索星空"
          aria-label="进入太阳系模拟彩蛋"
          @click="router.push('/cosmos')"
        >
          <img class="brand-logo-img" src="/logo.png" alt="知见 Logo" />
        </button>
        <div>
          <strong>知见</strong>
          <small>AI 元认知测评</small>
        </div>
      </div>

      <h2 class="login-title">欢迎回来</h2>
      <p class="login-subtitle">系统将根据账号自动识别你的身份</p>

      <!-- 离线模式提示 -->
      <p v-if="isOfflineMode" class="offline-badge">
        <i class="bi bi-wifi-off" /> 离线模式 · 使用演示账号
      </p>

      <!-- 登录表单 -->
      <form class="login-form" @submit.prevent="handleLogin">
        <div class="mb-3">
          <label class="form-label-sm" for="login-username">
            <i class="bi bi-person" /> 账号
          </label>
          <div class="input-with-action">
            <input
              id="login-username"
              v-model="username"
              type="text"
              class="form-control"
              placeholder="学号或教工号"
              :disabled="isLoading"
              autocomplete="username"
            />
            <span v-if="username.trim()" class="input-feedback-icon text-success">
              <i class="bi bi-check-circle-fill" />
            </span>
          </div>
        </div>

        <div class="mb-3">
          <label class="form-label-sm" for="login-password">
            <i class="bi bi-lock" /> 密码
          </label>
          <div class="input-with-action">
            <input
              id="login-password"
              v-model="password"
              :type="showPassword ? 'text' : 'password'"
              class="form-control"
              placeholder="输入密码"
              :disabled="isLoading"
              autocomplete="current-password"
            />
            <button
              v-if="password"
              type="button"
              class="input-action-btn"
              :aria-label="showPassword ? '隐藏密码' : '显示密码'"
              :title="showPassword ? '隐藏密码' : '显示密码'"
              @click="showPassword = !showPassword"
            >
              <i class="bi" :class="showPassword ? 'bi-eye-slash-fill' : 'bi-eye-fill'" />
            </button>
          </div>
        </div>

        <!-- 错误提示 -->
        <p v-if="errorMsg" class="login-error">
          <i class="bi bi-exclamation-triangle" /> {{ errorMsg }}
        </p>

        <!-- 提交按钮 -->
        <button type="submit" class="btn btn-primary login-btn" :disabled="isLoading">
          <span v-if="isLoading" class="spinner-border spinner-border-sm me-2" />
          {{ isLoading ? '登录中…' : '登录' }}
        </button>
      </form>

      <!-- 演示账号快捷入口（完全保留原本展示结构与内容） -->
      <div v-if="offlineDemoEnabled" class="demo-section">
        <button
          class="demo-toggle"
          type="button"
          :aria-expanded="demoExpanded"
          aria-controls="demo-account-buttons"
          @click="demoExpanded = !demoExpanded"
        >
          <span><i class="bi bi-lightning-charge"></i> 演示账号</span>
          <i class="bi" :class="demoExpanded ? 'bi-chevron-up' : 'bi-chevron-down'" />
        </button>
        <div id="demo-account-buttons" class="demo-buttons" :class="{ 'is-expanded': demoExpanded }">
          <button
            v-for="d in demos"
            :key="d.role"
            class="demo-btn"
            type="button"
            @click="fillDemo(d.role)"
          >
            <i class="bi" :class="d.icon"></i> {{ d.name }}
          </button>
        </div>
      </div>
    </div>

    <!-- 苹果风格悬浮毛玻璃胶囊底部提示 -->
    <footer class="login-footer">
      <span>本系统为教育教学研究设计 · 数据仅用于实验研究 · 按角色授权访问与导出</span>
    </footer>

  </div>
</template>

<style scoped>
/* ---- 登录页整体容器 ---- */
.login-page {
  position: relative;
  min-height: 100vh;
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  background: #f0f2fb;
  overflow: hidden;
  user-select: none;
}

html[data-theme="dark"] .login-page {
  background: #0d0e15;
}

/* ---- 苹果风格磨砂玻璃主题切换按钮 ---- */
.login-theme-btn {
  position: absolute;
  top: 24px;
  right: 24px;
  z-index: 10;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.65);
  backdrop-filter: blur(24px) saturate(180%);
  -webkit-backdrop-filter: blur(24px) saturate(180%);
  border: 1px solid rgba(255, 255, 255, 0.7);
  box-shadow: 0 8px 24px rgba(35, 30, 70, 0.08), 0 1px 2px rgba(255, 255, 255, 0.8) inset;
  color: var(--color-text);
  font-size: 1.15rem;
  transition: transform 0.2s ease, background-color 0.2s ease, box-shadow 0.2s ease;
}

.login-theme-btn:hover {
  transform: scale(1.06);
  background: rgba(255, 255, 255, 0.85);
  box-shadow: 0 12px 30px rgba(35, 30, 70, 0.14);
}

html[data-theme="dark"] .login-theme-btn {
  background: rgba(26, 28, 42, 0.65);
  border: 1px solid rgba(255, 255, 255, 0.12);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
}
html[data-theme="dark"] .login-theme-btn:hover {
  background: rgba(36, 38, 56, 0.85);
}

/* ---- 苹果风格毛玻璃悬浮主卡片 (VisionOS Glass Card) ---- */
.login-card {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 430px;
  border-radius: 28px;
  padding: 44px 36px 34px;
  background: rgba(255, 255, 255, 0.68);
  backdrop-filter: blur(36px) saturate(190%);
  -webkit-backdrop-filter: blur(36px) saturate(190%);
  border: 1px solid rgba(255, 255, 255, 0.75);
  box-shadow:
    0 24px 70px rgba(30, 25, 65, 0.11),
    0 1px 3px rgba(255, 255, 255, 0.85) inset;
  transition: transform 0.25s ease, box-shadow 0.25s ease;
}

html[data-theme="dark"] .login-card {
  background: rgba(24, 25, 38, 0.72);
  border: 1px solid rgba(255, 255, 255, 0.12);
  box-shadow:
    0 28px 80px rgba(0, 0, 0, 0.55),
    0 1px 1px rgba(255, 255, 255, 0.1) inset;
}

/* ---- 品牌区域 ---- */
.login-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  justify-content: center;
  margin-bottom: 24px;
}

.login-brand .brand-logo-img {
  width: 56px;
  height: 56px;
  object-fit: cover;
  border-radius: 15px;
  box-shadow: 0 8px 24px rgba(75, 73, 172, 0.28);
  display: block;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.login-cosmos-trigger { padding: 0; border: 0; border-radius: 15px; background: transparent; }
.login-cosmos-trigger:focus-visible { outline: 3px solid var(--focus-ring); outline-offset: 4px; }

.login-brand .brand-logo-img:hover {
  transform: scale(1.05);
  box-shadow: 0 12px 28px rgba(75, 73, 172, 0.38);
}

.login-brand strong {
  display: block;
  font-size: 25px;
  letter-spacing: 2px;
  line-height: 1.1;
  color: var(--color-text);
  font-weight: 800;
}

.login-brand small {
  display: block;
  color: var(--color-text-muted);
  font-size: 11.5px;
  margin-top: 3px;
  letter-spacing: 0.5px;
}

.login-title {
  text-align: center;
  font-size: 20px;
  font-weight: 700;
  margin: 0 0 4px;
  color: var(--color-text);
}

.login-subtitle {
  text-align: center;
  color: var(--color-text-muted);
  font-size: 13px;
  margin: 0 0 16px;
}

.offline-badge {
  text-align: center;
  margin: 0 0 18px;
  padding: 8px 14px;
  border-radius: var(--radius-sm);
  background: var(--color-warning-soft);
  color: var(--color-warning);
  font-size: 12px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

/* ---- 表单控件 (Apple Frosted Form Controls) ---- */
.login-form {
  display: flex;
  flex-direction: column;
}

.form-label-sm {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  gap: 5px;
}

.form-label-sm i {
  color: var(--color-text-muted);
  font-size: 13px;
}

.form-control {
  padding: 12px 14px;
  background: rgba(255, 255, 255, 0.65);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid rgba(215, 218, 235, 0.7);
  border-radius: var(--control-radius);
  font-size: 14.5px;
  color: var(--color-text);
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s, background-color 0.2s;
}

.form-control:focus {
  background: rgba(255, 255, 255, 0.9);
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3.5px var(--focus-ring);
}

html[data-theme="dark"] .form-control {
  background: rgba(36, 38, 54, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: var(--color-text);
}

html[data-theme="dark"] .form-control:focus {
  background: rgba(42, 44, 62, 0.85);
  border-color: var(--color-primary);
}

.login-error {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0 0 14px;
  padding: 10px 14px;
  border-radius: var(--radius-sm);
  background: var(--color-danger-soft);
  color: var(--color-danger);
  font-size: 12.5px;
  font-weight: 500;
}

.login-btn {
  width: 100%;
  padding: 13px;
  font-size: 15px;
  font-weight: 700;
  border-radius: var(--control-radius);
  background: var(--color-primary);
  border-color: var(--color-primary);
  box-shadow: 0 6px 20px rgba(75, 73, 172, 0.35);
  transition: transform 0.18s ease, box-shadow 0.18s ease, background-color 0.18s ease;
}

.login-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 10px 26px rgba(75, 73, 172, 0.42);
}

.login-btn:active:not(:disabled) {
  transform: translateY(0);
}

/* ---- 演示账号（完全保持原貌） ---- */
.demo-section {
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid rgba(0, 0, 0, 0.06);
}

html[data-theme="dark"] .demo-section {
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.demo-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.35rem;
  width: 100%;
  margin-bottom: 12px;
  padding: 0;
  border: 0;
  color: var(--color-text-muted);
  background: transparent;
  font-size: 11px;
}

.demo-toggle > span {
  display: flex;
  align-items: center;
  gap: 5px;
}

.demo-toggle > span i {
  color: #f0a854;
}

.demo-toggle > i {
  display: none;
}

.demo-buttons {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: center;
}

.demo-btn {
  min-height: 36px;
  padding: 7px 14px;
  border: 1px solid rgba(255, 255, 255, 0.6);
  border-radius: var(--radius-sm);
  background: rgba(255, 255, 255, 0.55);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  color: var(--color-text-secondary);
  font-size: 12px;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  transition: color var(--motion-fast) ease, background-color var(--motion-fast) ease, border-color var(--motion-fast) ease;
  display: flex;
  align-items: center;
  gap: 5px;
}

.demo-btn:hover {
  background: var(--color-primary-soft);
  color: var(--color-primary);
  border-color: #c8c7ed;
}

.demo-btn i {
  font-size: 13px;
}

html[data-theme="dark"] .demo-btn {
  background: rgba(36, 38, 54, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: var(--color-text-secondary);
}
html[data-theme="dark"] .demo-btn:hover {
  background: rgba(50, 52, 74, 0.85);
  color: var(--color-primary);
}

/* ---- 苹果风格悬浮毛玻璃胶囊底部提示 ---- */
.login-footer {
  position: relative;
  z-index: 1;
  margin-top: 28px;
  max-width: 640px;
  padding: 10px 22px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.52);
  backdrop-filter: blur(24px) saturate(180%);
  -webkit-backdrop-filter: blur(24px) saturate(180%);
  border: 1px solid rgba(255, 255, 255, 0.65);
  box-shadow: 0 8px 30px rgba(35, 30, 70, 0.07);
  color: var(--color-text-secondary);
  font-size: 12px;
  text-align: center;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  line-height: 1.5;
}

html[data-theme="dark"] .login-footer {
  background: rgba(24, 25, 38, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.1);
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.4);
}

/* ---- 移动端适配 ---- */
@media (max-width: 575.98px) {
  .login-page {
    padding: max(20px, env(safe-area-inset-top)) 16px max(20px, env(safe-area-inset-bottom));
  }
  .login-card {
    padding: 32px 22px 26px;
    border-radius: 22px;
  }
  .demo-toggle {
    justify-content: space-between;
    min-height: 42px;
    margin-bottom: 0;
    padding: 0 0.25rem;
    font-size: 12px;
  }
  .demo-toggle > i {
    display: inline-block;
  }
  .demo-buttons {
    display: none;
    padding-top: 10px;
  }
  .demo-buttons.is-expanded {
    display: flex;
  }
  .demo-btn {
    flex: 1 1 100%;
    justify-content: center;
    min-height: 44px;
  }
  .login-footer {
    border-radius: 16px;
    padding: 10px 16px;
    font-size: 11px;
  }
}
</style>
