<script setup lang="ts">
import AsrStatusPanel from '../AsrStatusPanel.vue'

defineProps<{
  questionnaireEnabled: boolean
  questionnaireItemsCount: number
  submittedSessionIds: string[]
  isBusy: boolean
}>()

const emit = defineEmits<{
  (e: 'complete'): void
  (e: 'ready-change', ready: boolean): void
}>()
</script>

<template>
  <div class="card border-0 shadow-sm">
    <div class="card-body p-4 p-lg-5 text-center">
      <i class="bi bi-clipboard2-check display-4 text-success" />
      <h4 class="mt-3">所有测评内容已保存</h4>
      <p class="text-muted">
        <template v-if="questionnaireEnabled">
          已完成 2 项出声思维任务和 {{ questionnaireItemsCount }} 道任务后问卷。
        </template>
        <template v-else>已完成 2 项出声思维任务，本次协议未启用任务后问卷。</template>
        确认后将结束本次测评。
      </p>
      <AsrStatusPanel
        v-if="submittedSessionIds.length"
        class="my-4"
        :session-ids="submittedSessionIds"
        @ready-change="emit('ready-change', $event)"
      />
      <button class="btn btn-success" :disabled="isBusy" @click="emit('complete')">
        <span v-if="isBusy" class="spinner-border spinner-border-sm me-2"></span>
        确认提交并结束测评
      </button>
    </div>
  </div>
</template>
