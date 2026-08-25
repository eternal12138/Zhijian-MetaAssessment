import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

export interface UserProfile {
  id: string
  name: string
  role: 'student' | 'teacher' | 'admin'
  avatarText: string
}

export const useUserStore = defineStore('user', () => {
  const profile = ref<UserProfile>({
    id: '',
    name: '未登录',
    role: 'student',
    avatarText: '?'
  })
  const isAuthenticated = ref(false)
  const displayName = computed(() => profile.value.name)

  function setProfile(nextProfile: UserProfile) {
    profile.value = nextProfile
    isAuthenticated.value = true
  }

  function signOut() {
    profile.value = { id: '', name: '未登录', role: 'student', avatarText: '?' }
    isAuthenticated.value = false
    // localStorage 清理由 authStore.logout() 统一负责，此处不重复执行。
  }

  return { profile, isAuthenticated, displayName, setProfile, signOut }
}, {
  persist: {
    key: 'mc-user',
    storage: localStorage,
    pick: ['profile', 'isAuthenticated']
  }
})
