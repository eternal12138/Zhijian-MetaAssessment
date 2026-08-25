<script setup lang="ts">
import AppModal from '../../ui/AppModal.vue'

defineProps<{
  open: boolean
  taskIndex: number
  recordingDurationFormatted: string
  generatedAudioChunkCount: number
  failedTransferCount: number
  pendingTransferCount: number
  submissionWarnings: string[]
  isOnline: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'confirm'): void
}>()
</script>

<template>
  <AppModal
    :open="open"
    max-width="480px"
    @close="emit('close')"
  >
    <template #header>
      <div class="d-flex align-items-center gap-2">
        <div class="submit-confirmation-icon"><i class="bi bi-check2-circle" /></div>
        <h5 class="mb-0" id="submit-task-title">确认完成任务 {{ taskIndex + 1 }}</h5>
      </div>
    </template>

    <p class="text-muted small mb-0">
      提交后将结束本任务录音，不能返回修改。系统会先等待当前音频和字幕同步完成。
    </p>
    <dl class="submit-summary">
      <div><dt>录音时长</dt><dd>{{ recordingDurationFormatted }}</dd></div>
      <div><dt>音频分片</dt><dd>{{ generatedAudioChunkCount }} 个</dd></div>
      <div><dt>同步状态</dt><dd>{{ failedTransferCount ? `${failedTransferCount} 项待重试` : pendingTransferCount ? `${pendingTransferCount} 项处理中` : '已同步' }}</dd></div>
    </dl>
    <div v-if="submissionWarnings.length" class="submit-warnings">
      <strong><i class="bi bi-exclamation-triangle-fill me-1" />提交前请确认</strong>
      <ul class="mb-0"><li v-for="warning in submissionWarnings" :key="warning">{{ warning }}</li></ul>
    </div>

    <template #footer>
      <div class="app-dialog-actions mt-3 w-100">
        <button class="btn btn-outline-secondary" type="button" @click="emit('close')">继续作答</button>
        <button class="btn btn-primary" type="button" :disabled="!isOnline" @click="emit('confirm')">确认完成并提交</button>
      </div>
    </template>
  </AppModal>
</template>

<style scoped>
.submit-confirmation-icon {
  display: grid;
  width: 36px;
  height: 36px;
  place-items: center;
  border-radius: 50%;
  color: var(--color-success);
  background: var(--color-success-soft);
  font-size: 1.25rem;
}
.submit-summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: .5rem; margin: 1rem 0; }
.submit-summary div { padding: .65rem; border-radius: var(--radius-sm); background: var(--color-surface-subtle); border: 1px solid var(--color-border); }
.submit-summary dt { color: var(--color-text-muted); font-size: .68rem; font-weight: 600; }
.submit-summary dd { margin: .2rem 0 0; color: var(--color-text); font-size: .84rem; font-weight: 700; }
.submit-warnings { padding: .75rem .85rem; border: 1px solid var(--color-border); border-radius: var(--radius-md); color: var(--color-warning); background: var(--color-warning-soft); }
.submit-warnings strong { font-size: .78rem; }
.submit-warnings ul { margin-top: .35rem; padding-left: 1.15rem; font-size: .74rem; line-height: 1.55; }
@media (max-width: 575.98px) {
  .submit-summary { grid-template-columns: 1fr; }
}
</style>
