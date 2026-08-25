<script setup lang="ts">
import { computed } from 'vue'
import type { OfflineAssessmentSnapshot } from '../../utils/offlineAssessmentStorage'
import AppModal from '../ui/AppModal.vue'

const props = defineProps<{
  open: boolean
  snapshot: OfflineAssessmentSnapshot | null
  pendingItemCount: number
  isBusy: boolean
}>()

const emit = defineEmits<{
  (e: 'restore'): void
  (e: 'discard'): void
}>()

const phaseLabel = computed(() => ({
  device_check: '设备检查',
  instructions: '操作说明',
  practice: '练习任务',
  task: `正式任务 ${(props.snapshot?.currentTaskIndex ?? 0) + 1}`,
  questionnaire: '任务后问卷',
  review: '提交确认'
}[props.snapshot?.currentPhase ?? ''] ?? '未完成阶段'))

const progress = computed(() => {
  const phase = props.snapshot?.currentPhase
  const values: Record<string, number> = {
    device_check: 15,
    instructions: 25,
    practice: 35,
    task: (props.snapshot?.currentTaskIndex ?? 0) === 0 ? 50 : 68,
    questionnaire: 82,
    review: 95
  }
  return values[phase ?? ''] ?? 5
})

const savedAt = computed(() => props.snapshot
  ? new Intl.DateTimeFormat('zh-CN', {
      month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit'
    }).format(new Date(props.snapshot.updatedAt))
  : '')
</script>

<template>
  <AppModal
    :open="open"
    title="检测到未完成的测评"
    icon="bi-arrow-counterclockwise"
    max-width="520px"
    :close-on-backdrop="false"
    :close-on-esc="false"
  >
    <div class="recovery-hero">
      <span class="recovery-orbit" aria-hidden="true"><i class="bi bi-cloud-check-fill" /></span>
      <div>
        <strong>本地安全副本可用</strong>
        <p>上次停留在{{ phaseLabel }}，已完成约 {{ progress }}%。</p>
      </div>
    </div>

    <div class="recovery-progress" role="progressbar" :aria-valuenow="progress" aria-valuemin="0" aria-valuemax="100">
      <span :style="{ transform: `scaleX(${progress / 100})` }" />
    </div>

    <dl class="recovery-details">
      <div><dt>最近保存</dt><dd>{{ savedAt }}</dd></div>
      <div><dt>待同步数据</dt><dd>{{ pendingItemCount }} 项</dd></div>
      <div><dt>恢复内容</dt><dd>阶段、草稿、问卷和待传数据</dd></div>
    </dl>

    <p class="recovery-note">
      <i class="bi bi-shield-check" aria-hidden="true" />
      恢复操作会与服务器已保存内容合并，不会覆盖已经成功上传的录音分片。
    </p>

    <template #footer>
      <div class="d-flex flex-column-reverse flex-sm-row justify-content-end gap-2">
        <button class="btn btn-outline-secondary" :disabled="isBusy" @click="emit('discard')">
          放弃本地副本
        </button>
        <button class="btn btn-primary" :disabled="isBusy" @click="emit('restore')">
          <span v-if="isBusy" class="spinner-border spinner-border-sm me-2" />
          一键恢复测评
        </button>
      </div>
    </template>
  </AppModal>
</template>

<style scoped>
.recovery-hero {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem;
  border: 1px solid color-mix(in srgb, var(--color-primary) 24%, var(--color-border));
  border-radius: var(--radius-lg);
  background:
    radial-gradient(circle at 8% 15%, rgba(92, 180, 255, .16), transparent 46%),
    color-mix(in srgb, var(--color-primary-soft) 62%, var(--color-surface));
}
.recovery-hero strong { display: block; color: var(--color-text); }
.recovery-hero p { margin: .25rem 0 0; color: var(--color-text-secondary); font-size: .84rem; }
.recovery-orbit {
  display: grid;
  width: 48px;
  height: 48px;
  flex: 0 0 48px;
  place-items: center;
  border-radius: 50%;
  color: #fff;
  background: linear-gradient(135deg, #7573e7, #3ed2c0);
  box-shadow: 0 0 22px rgba(92, 180, 255, .28);
  font-size: 1.2rem;
}
.recovery-progress {
  height: 7px;
  margin: 1rem 0;
  overflow: hidden;
  border-radius: 999px;
  background: var(--color-border);
}
.recovery-progress span {
  display: block;
  width: 100%;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #7573e7, #3ed2c0);
  transform-origin: left center;
  transition: transform var(--motion-panel) var(--ease-out);
}
.recovery-details { display: grid; gap: .55rem; margin: 0; }
.recovery-details div { display: flex; justify-content: space-between; gap: 1rem; padding-bottom: .55rem; border-bottom: 1px solid var(--color-border); }
.recovery-details dt { color: var(--color-text-muted); font-size: .78rem; font-weight: 500; }
.recovery-details dd { margin: 0; color: var(--color-text); font-size: .8rem; font-weight: 650; text-align: right; }
.recovery-note { display: flex; gap: .5rem; margin: 1rem 0 0; color: var(--color-text-muted); font-size: .75rem; line-height: 1.55; }
.recovery-note i { color: var(--color-success); }
@media (prefers-reduced-motion: reduce) {
  .recovery-progress span { transition: none; }
}
</style>
