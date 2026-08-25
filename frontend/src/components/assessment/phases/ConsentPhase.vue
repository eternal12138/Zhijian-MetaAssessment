<script setup lang="ts">
import { ref } from 'vue'

defineProps<{
  isBusy: boolean
}>()

const emit = defineEmits<{
  (e: 'agree'): void
}>()

const consentChecked = ref(false)
</script>

<template>
  <div class="card border-0 shadow-sm">
    <div class="card-body p-4 p-lg-5">
      <h4 class="mb-3">参与说明与知情同意</h4>
      <div class="consent-copy text-secondary">
        <p class="mb-0">
          本次测评过程中，系统将采集麦克风录音、实时转写文本、作答时长及任务后问卷作答等数据。所有数据仅用于本项目的学术研究与测评分析，均以匿名化形式存储与处理，严格保密，不会关联您的个人身份，也不会用于本研究以外的任何用途。请您在安静环境中独立完成全部测评，作答过程中请避免提及姓名、联系方式等个人敏感信息。
        </p>
      </div>
      <div class="form-check rounded-3 bg-light p-3 ps-5 mt-4">
        <input id="consent" v-model="consentChecked" class="form-check-input" type="checkbox">
        <label class="form-check-label" for="consent">
          我已阅读并理解上述说明，自愿参加本次测评。
        </label>
      </div>
      <button
        class="btn btn-primary mt-4"
        :disabled="!consentChecked || isBusy"
        @click="emit('agree')"
      >
        <span v-if="isBusy" class="spinner-border spinner-border-sm me-2"></span>
        同意并开始
      </button>
    </div>
  </div>
</template>

<style scoped>
.consent-copy { line-height: 1.8; }
</style>
