<script setup lang="ts">
defineProps<{
  isBusy: boolean
}>()

const emit = defineEmits<{
  (e: 'next'): void
}>()
</script>

<template>
  <div class="card border-0 shadow-sm">
    <div class="card-body p-4 p-lg-5">
      <h4 class="mb-0">出声思维说明</h4>
      <div class="instruction-box mt-4">
        <p>任务进行时，请专注于任务本身，把你脑海中正在发生的想法直接说出来。如果沉默超过十五秒，系统会提醒你继续说出想法。全程自动录音仅用于记录你的想法，结束后自动保存。</p>
        <h5 class="instruction-title">出声思维操作规范</h5>
        <ol class="mb-0">
          <li>任务进行时，请同步口述你看到的页面内容、脑中浮现的所有念头、计算推演步骤与每一次选择判断；</li>
          <li>请直接说出脑海原生想法，使用日常口语自然表达，完整呈现当下实时思绪；</li>
          <li>全程保持连贯口述思维内容；</li>
          <li>若出现连续15秒未出声的情况，系统将通过文字、语音双重提示，引导您继续分享思考；</li>
          <li>任务启动同步开启录音，任务结束后系统自动停止并保存本次口述记录。</li>
        </ol>
      </div>
      <button
        class="btn btn-primary instruction-confirm-button mt-4"
        :disabled="isBusy"
        @click="emit('next')"
      >
        <span v-if="isBusy" class="spinner-border spinner-border-sm me-2"></span>
        我已完整了解上述操作规范，开始练习
      </button>
    </div>
  </div>
</template>

<style scoped>
.instruction-box {
  border: 1px solid var(--color-border);
  background: var(--color-surface-subtle);
  border-radius: var(--radius-lg);
  padding: 1.25rem;
  line-height: 1.9;
}
.instruction-box > p { margin-bottom: 1rem; }
.instruction-title { margin-bottom: .7rem; font-size: 1rem; font-weight: 700; color: var(--color-text); }
.instruction-confirm-button { white-space: normal; }
@media (max-width: 575.98px) {
  .instruction-box { padding: 1rem; line-height: 1.7; }
  .instruction-box ol { padding-left: 1.35rem; }
}
</style>
