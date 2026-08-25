<script setup lang="ts">
import { RouterLink } from 'vue-router'
import AsrStatusPanel from '../AsrStatusPanel.vue'

defineProps<{
  questionnaireEnabled: boolean
  submittedSessionIds: string[]
  runId?: string
  asrReady: boolean
}>()

const emit = defineEmits<{
  (e: 'ready-change', ready: boolean): void
}>()
</script>

<template>
  <div class="card border-0 shadow-sm">
    <div class="card-body py-5 text-center">
      <span class="completion-icon"><i class="bi bi-check-lg" /></span>
      <h3 class="mt-4">测评已完成</h3>
      <p class="text-muted">
        {{ questionnaireEnabled ? '录音、转录文本与问卷已经成功提交' : '录音与转录文本已经成功提交' }}，感谢你的参与。
      </p>
      <AsrStatusPanel
        v-if="submittedSessionIds.length"
        class="my-4 mx-auto completed-status"
        :session-ids="submittedSessionIds"
        @ready-change="emit('ready-change', $event)"
      />
      <div class="completion-actions d-flex justify-content-center gap-2 mt-3">
        <RouterLink
          v-if="runId && asrReady"
          :to="{ path: '/report', query: { run: runId } }"
          class="btn btn-primary"
        >
          生成并查看报告
        </RouterLink>
        <button v-else-if="runId" class="btn btn-primary" disabled>
          等待权威转录后生成报告
        </button>
        <RouterLink to="/" class="btn btn-outline-secondary">返回首页</RouterLink>
      </div>
    </div>
  </div>
</template>

<style scoped>
.completed-status { max-width: 760px; }
.completion-icon {
  display: inline-grid;
  place-items: center;
  width: 82px;
  height: 82px;
  border-radius: 50%;
  background: var(--color-success-soft);
  color: var(--color-success);
  font-size: 2.5rem;
}
@media (max-width: 575.98px) {
  .completion-icon { width: 68px; height: 68px; font-size: 2rem; }
  .completion-actions { flex-direction: column; }
  .completion-actions .btn { width: 100%; }
}
</style>
