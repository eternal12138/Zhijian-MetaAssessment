<script setup lang="ts">
import { computed, ref } from 'vue'
import { adminApi } from '../api/admin'
import { useUserStore } from '../stores/user'
import AppPageHeader from '../components/ui/AppPageHeader.vue'

const userStore = useUserStore()
const newPassword = ref('')
const confirmPassword = ref('')
const showNewPassword = ref(false)
const showConfirmPassword = ref(false)
const isSaving = ref(false)
const errorMessage = ref('')
const successMessage = ref('')
const roleLabel = computed(() => ({ student: '学生', teacher: '教师', admin: '管理员' }[userStore.profile.role]))

const pwdStrength = computed(() => {
  const p = newPassword.value
  if (!p) return { score: 0, label: '', class: '', textClass: '' }
  let score = 0
  if (p.length >= 6) score++
  if (/[a-zA-Z]/.test(p) && /\d/.test(p)) score++
  if (/[^a-zA-Z0-9]/.test(p) || p.length >= 10) score++
  if (score <= 1) return { score: 1, label: '弱 (建议包含字母与数字)', class: 'strength-weak', textClass: 'text-weak' }
  if (score === 2) return { score: 2, label: '中 (可加入特殊符号提升安全性)', class: 'strength-medium', textClass: 'text-medium' }
  return { score: 3, label: '强', class: 'strength-strong', textClass: 'text-strong' }
})

const passwordMismatch = computed(() => {
  return confirmPassword.value.length > 0 && newPassword.value !== confirmPassword.value
})

async function changePassword() {
  errorMessage.value = ''
  successMessage.value = ''
  if (newPassword.value.length < 6) { errorMessage.value = '密码至少需要6位'; return }
  if (newPassword.value === '123456') { errorMessage.value = '不能继续使用默认密码'; return }
  if (newPassword.value !== confirmPassword.value) { errorMessage.value = '两次输入的密码不一致'; return }
  isSaving.value = true
  try {
    const response = await adminApi.changeOwnPassword(newPassword.value)
    localStorage.setItem('access_token', response.data.access_token)
    localStorage.removeItem('needs_password_change')
    newPassword.value = ''
    confirmPassword.value = ''
    successMessage.value = '密码修改成功。'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '密码修改失败'
  } finally {
    isSaving.value = false
  }
}
</script>

<template>
  <div class="settings-page">
    <AppPageHeader eyebrow="账号设置" title="个人信息与安全" icon="bi-person-gear" description="个人研究字段由管理员维护，当前页面提供只读信息和密码修改。" compact />
    <div class="row g-4">
      <div class="col-lg-5">
        <div class="card border-0 shadow-sm h-100"><div class="card-body p-4">
          <div class="profile-head"><span class="avatar large">{{ userStore.profile.avatarText }}</span><div><h5>{{ userStore.profile.name }}</h5><span class="badge bg-primary-subtle text-primary">{{ roleLabel }}</span></div></div>
          <dl class="profile-list mt-4"><div><dt>用户ID</dt><dd>{{ userStore.profile.id || '—' }}</dd></div><div><dt>账号角色</dt><dd>{{ roleLabel }}</dd></div></dl>
        </div></div>
      </div>
      <div class="col-lg-7">
        <div class="card border-0 shadow-sm"><div class="card-body p-4">
          <h5>修改密码</h5>
          <p class="text-muted small mb-3">建议使用至少8位且包含字母、数字的独立密码。</p>
          <div v-if="errorMessage" class="alert alert-danger py-2">{{ errorMessage }}</div>
          <div v-if="successMessage" class="alert alert-success py-2">{{ successMessage }}</div>

          <div class="mb-3">
            <label class="form-label" for="account-new-password">新密码</label>
            <div class="input-with-action">
              <input
                id="account-new-password"
                v-model="newPassword"
                :type="showNewPassword ? 'text' : 'password'"
                class="form-control"
                placeholder="输入新密码（至少6位）"
                autocomplete="new-password"
              >
              <button
                v-if="newPassword"
                type="button"
                class="input-action-btn"
                :aria-label="showNewPassword ? '隐藏密码' : '显示密码'"
                :title="showNewPassword ? '隐藏密码' : '显示密码'"
                @click="showNewPassword = !showNewPassword"
              >
                <i class="bi" :class="showNewPassword ? 'bi-eye-slash-fill' : 'bi-eye-fill'"></i>
              </button>
            </div>
            <!-- 密码强度指示器 -->
            <div v-if="newPassword" class="password-strength-wrap">
              <div class="password-strength-bar">
                <div class="password-strength-fill" :class="pwdStrength.class"></div>
              </div>
              <div class="password-strength-hint">
                <span>密码强度</span>
                <strong :class="pwdStrength.textClass">{{ pwdStrength.label }}</strong>
              </div>
            </div>
          </div>

          <div class="mb-3">
            <label class="form-label" for="account-confirm-password">确认新密码</label>
            <div class="input-with-action">
              <input
                id="account-confirm-password"
                v-model="confirmPassword"
                :type="showConfirmPassword ? 'text' : 'password'"
                class="form-control"
                :class="{ 'is-invalid': passwordMismatch }"
                placeholder="再次输入新密码"
                autocomplete="new-password"
                @keyup.enter="changePassword"
              >
              <button
                v-if="confirmPassword"
                type="button"
                class="input-action-btn"
                :aria-label="showConfirmPassword ? '隐藏密码' : '显示密码'"
                :title="showConfirmPassword ? '隐藏密码' : '显示密码'"
                @click="showConfirmPassword = !showConfirmPassword"
              >
                <i class="bi" :class="showConfirmPassword ? 'bi-eye-slash-fill' : 'bi-eye-fill'"></i>
              </button>
            </div>
            <p v-if="passwordMismatch" class="text-danger small mt-1 mb-0">
              <i class="bi bi-exclamation-circle me-1"></i>两次输入的密码不一致
            </p>
          </div>

          <button
            class="btn btn-primary mt-2"
            :disabled="isSaving || !newPassword || !confirmPassword || passwordMismatch"
            @click="changePassword"
          >
            <span v-if="isSaving" class="spinner-border spinner-border-sm me-2"></span>
            保存新密码
          </button>
        </div></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-page { max-width: 1000px; margin: 0 auto; }
.card { border-radius: var(--radius-lg); }
.profile-head { display: flex; align-items: center; gap: 1rem; }
.avatar.large { width: 58px; height: 58px; font-size: 1.2rem; }
.profile-head h5 { margin: 0 0 .35rem; }
.profile-list div { display: flex; justify-content: space-between; padding: .75rem 0; border-bottom: 1px solid var(--color-border); }
.profile-list dt { color: var(--color-text-muted); font-weight: 500; }
.profile-list dd { margin: 0; color: var(--color-text); }
@media (max-width: 575.98px) {
  .profile-list div { gap: 1rem; align-items: flex-start; }
  .profile-list dd { min-width: 0; text-align: right; overflow-wrap: anywhere; }
  .settings-page .btn { width: 100%; min-height: 44px; }
}
</style>
