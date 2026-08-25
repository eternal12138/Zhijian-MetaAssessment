<script setup lang="ts">
import { onErrorCaptured, ref } from 'vue'

const props = withDefaults(
  defineProps<{
    componentName?: string
    fallbackMessage?: string
    showRetry?: boolean
  }>(),
  {
    componentName: '该组件',
    fallbackMessage: '组件渲染遇到未预期异常，主系统仍在平稳运行。',
    showRetry: true
  }
)

const hasError = ref(false)
const errorDetail = ref('')

onErrorCaptured((err, instance, info) => {
  hasError.value = true
  errorDetail.value = err instanceof Error ? err.message : String(err)
  console.error(`[ErrorBoundary] Captured error in <${props.componentName}>:`, err, info)
  // 阻止错误继续向上传播导致整页白屏
  return false
})

function resetError() {
  hasError.value = false
  errorDetail.value = ''
}
</script>

<template>
  <div v-if="hasError" class="app-error-boundary-card">
    <div class="error-boundary-icon">
      <i class="bi bi-shield-exclamation"></i>
    </div>
    <div class="error-boundary-content">
      <h6 class="error-boundary-title">{{ componentName }} 发生局部渲染异常</h6>
      <p class="error-boundary-desc">{{ fallbackMessage }}</p>
      <div v-if="errorDetail" class="error-boundary-trace">
        <code>{{ errorDetail }}</code>
      </div>
      <button
        v-if="showRetry"
        type="button"
        class="btn btn-sm btn-outline-primary mt-2"
        @click="resetError"
      >
        <i class="bi bi-arrow-clockwise me-1"></i>重新加载组件
      </button>
    </div>
  </div>
  <slot v-else />
</template>

<style scoped>
.app-error-boundary-card {
  padding: 1.25rem 1.5rem;
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  border: 1px dashed var(--color-border-strong);
  display: flex;
  align-items: flex-start;
  gap: 1rem;
  box-shadow: var(--shadow-sm);
  margin: .75rem 0;
}

.error-boundary-icon {
  font-size: 1.75rem;
  color: var(--color-warning);
  flex-shrink: 0;
}

.error-boundary-content {
  flex: 1;
}

.error-boundary-title {
  margin: 0 0 .35rem;
  color: var(--color-text);
  font-weight: 700;
}

.error-boundary-desc {
  margin: 0 0 .5rem;
  font-size: .84rem;
  color: var(--color-text-secondary);
}

.error-boundary-trace {
  font-size: .78rem;
  background: var(--color-surface-subtle);
  padding: .35rem .6rem;
  border-radius: var(--radius-sm);
  color: var(--color-danger);
  word-break: break-all;
  display: inline-block;
  max-width: 100%;
}
</style>
