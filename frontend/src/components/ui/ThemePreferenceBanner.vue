<script setup lang="ts">
import { useTheme } from '../../composables/useTheme'

const { showDarkPrompt, acceptDarkTheme, dismissDarkPrompt } = useTheme()
</script>

<template>
  <Transition name="theme-banner-slide">
    <div
      v-if="showDarkPrompt"
      class="theme-prompt-banner shadow-lg"
      role="region"
      aria-label="深色模式偏好提示"
    >
      <div class="theme-prompt-content">
        <div class="theme-prompt-icon" aria-hidden="true">
          <i class="bi bi-moon-stars-fill" />
        </div>
        <div class="theme-prompt-text">
          <p class="theme-prompt-title">
            检测到您的系统偏好深色模式
          </p>
          <p class="theme-prompt-desc">
            本系统默认采用浅色显示。是否立即切换为深色显示？（后续可随时在页面右上角 ☀️/🌙 自由切换）
          </p>
        </div>
      </div>
      <div class="theme-prompt-actions">
        <button
          type="button"
          class="btn btn-sm btn-primary"
          @click="acceptDarkTheme"
        >
          <i class="bi bi-moon-fill me-1" />切换为深色
        </button>
        <button
          type="button"
          class="btn btn-sm btn-outline-secondary"
          @click="dismissDarkPrompt"
        >
          保持浅色
        </button>
        <button
          type="button"
          class="btn-close-banner"
          aria-label="关闭提示"
          @click="dismissDarkPrompt"
        >
          <i class="bi bi-x-lg" />
        </button>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.theme-prompt-banner {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 1060;
  max-width: 460px;
  width: calc(100vw - 32px);
  padding: 1rem 1.2rem;
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.18);
}

.theme-prompt-content {
  display: flex;
  align-items: flex-start;
  gap: 0.85rem;
}

.theme-prompt-icon {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  flex: 0 0 38px;
  border-radius: 50%;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-size: 1.15rem;
}

.theme-prompt-text {
  flex: 1;
}

.theme-prompt-title {
  margin: 0 0 0.2rem;
  font-size: 0.92rem;
  font-weight: 700;
  color: var(--color-text);
}

.theme-prompt-desc {
  margin: 0;
  font-size: 0.78rem;
  color: var(--color-text-secondary);
  line-height: 1.5;
}

.theme-prompt-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.5rem;
}

.btn-close-banner {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border: 0;
  background: transparent;
  color: var(--color-text-muted);
  border-radius: 50%;
  cursor: pointer;
  margin-left: 0.25rem;
  transition: color var(--motion-fast) ease, background-color var(--motion-fast) ease;
}

.btn-close-banner:hover {
  color: var(--color-text);
  background: var(--color-surface-subtle);
}

/* 动效 */
.theme-banner-slide-enter-active,
.theme-banner-slide-leave-active {
  transition: opacity 220ms ease, transform 220ms cubic-bezier(0.16, 1, 0.3, 1);
}

.theme-banner-slide-enter-from,
.theme-banner-slide-leave-to {
  opacity: 0;
  transform: translateY(16px) scale(0.96);
}

@media (max-width: 575.98px) {
  .theme-prompt-banner {
    bottom: 16px;
    right: 16px;
    left: 16px;
    width: auto;
  }
}
</style>
