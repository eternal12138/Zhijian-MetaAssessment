import { ref, computed } from 'vue'
import { defineStore } from 'pinia'

export type AppRole = 'student' | 'teacher' | 'admin'

export interface AuthState {
  userRole: AppRole | null
  isLoggedIn: boolean
}

export const useAuthStore = defineStore('auth', () => {
  const userRole = ref<AppRole | null>(null)
  const isLoggedIn = ref(false)
  const sessionRevision = ref(0)

  const isStudent = computed(() => userRole.value === 'student')
  const isTeacher = computed(() => userRole.value === 'teacher')
  const isAdmin = computed(() => userRole.value === 'admin')

  function login(role: AppRole) {
    userRole.value = role
    isLoggedIn.value = true
    sessionRevision.value += 1
  }

  function logout() {
    userRole.value = null
    isLoggedIn.value = false
    sessionRevision.value += 1
    // 统一清除所有持久化数据：JWT token、模式标记以及所有 Pinia 持久化 key。
    // 调用方（App.vue、client.ts 401 拦截器等）无需再各自手动 removeItem。
    try {
      [
        'access_token', 'offline_mode', 'needs_password_change',
        'mc-auth', 'mc-assessment', 'mc-report', 'mc-user',
      ].forEach(k => localStorage.removeItem(k))
    } catch { /* noop */ }
  }

  return {
    userRole,
    isLoggedIn,
    sessionRevision,
    isStudent,
    isTeacher,
    isAdmin,
    login,
    logout
  }
}, {
  persist: {
    key: 'mc-auth',
    storage: localStorage,
    pick: ['userRole', 'isLoggedIn']
  }
})
