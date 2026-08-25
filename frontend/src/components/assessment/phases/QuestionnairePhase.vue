<script setup lang="ts">
import type { AssessmentProtocol } from '../../../api/protocol'

defineProps<{
  acknowledged: boolean
  isSpeaking: boolean
  protocol: AssessmentProtocol | null
  questionnaireTotalCount: number
  answeredCount: number
  questionnaireAnswers: Record<string, number>
  participantName: string
  questionnaireComplete: boolean
  isBusy: boolean
}>()

const emit = defineEmits<{
  (e: 'acknowledge'): void
  (e: 'update:participant-name', value: string): void
  (e: 'submit'): void
}>()
</script>

<template>
  <div class="card border-0 shadow-sm">
    <div class="card-body p-4 p-lg-5">
      <!-- 问卷指导语 -->
      <div v-if="!acknowledged" class="questionnaire-guidance">
        <div class="questionnaire-guidance-icon" aria-hidden="true">
          <i class="bi bi-ui-checks-grid" />
        </div>
        <p class="text-primary fw-semibold small mb-1">任务后问卷</p>
        <h4>问卷填写指导语</h4>
        <div class="instruction-box mt-3">
          <p>下面共有24道量表题，最后还有一道姓名确认题。请回忆你刚刚完成两项问题解决任务时的真实体验与实际行为。</p>
          <p class="mb-0">请如实选择，问卷没有对错之分，请根据你的真实情况，按1（强烈不同意）到7（强烈同意）作答。完成量表后，请填写您的姓名或参加本次实验时使用的微信名等标识。</p>
        </div>
        <div class="d-flex flex-wrap gap-2 mt-4">
          <button class="btn btn-primary" type="button" @click="emit('acknowledge')">
            我已了解，开始填写问卷
          </button>
        </div>
        <p v-if="isSpeaking" class="text-muted small mt-3 mb-0" role="status" aria-live="polite">
          指导语正在播放；也可以直接点击上方按钮终止朗读并开始填写。
        </p>
      </div>

      <!-- 问卷作答区 -->
      <template v-else>
        <div class="questionnaire-heading d-flex justify-content-between align-items-center">
          <div>
            <h4>基于问题解决任务的元认知量表</h4>
            <p class="text-muted mb-0">
              共 {{ questionnaireTotalCount }} 题，其中前 {{ protocol?.questionnaire_items.length || 0 }} 题按 1（强烈不同意）到 7（强烈同意）作答，最后填写姓名或实验参与标识。
            </p>
          </div>
          <span class="badge bg-primary-subtle text-primary fs-6 px-3 py-2">
            已答 {{ answeredCount }} / {{ questionnaireTotalCount }}
          </span>
        </div>

        <div
          v-for="(item, index) in protocol?.questionnaire_items"
          :key="item.id"
          class="questionnaire-item"
        >
          <div class="questionnaire-item-title">
            <span class="item-number">{{ index + 1 }}</span>
            <p class="fw-semibold mb-0">{{ item.text }}</p>
          </div>

          <!-- 桌面端 7 选项网格 -->
          <div class="likert-grid desktop-likert">
            <label
              v-for="value in 7"
              :key="value"
              class="likert-option"
              :class="{ 'is-selected': questionnaireAnswers[item.id] === value }"
            >
              <input v-model="questionnaireAnswers[item.id]" type="radio" :name="item.id" :value="value">
              <span class="likert-num">{{ value }}</span>
              <small class="likert-text">{{ protocol?.likert_labels[String(value)] }}</small>
            </label>
          </div>

          <!-- 移动端纵向卡片式单选条目 -->
          <div class="mobile-likert-list">
            <label
              v-for="value in 7"
              :key="value"
              class="mobile-likert-item"
              :class="{ 'is-active': questionnaireAnswers[item.id] === value }"
            >
              <input v-model="questionnaireAnswers[item.id]" type="radio" :name="`m-${item.id}`" :value="value">
              <span class="mobile-num">{{ value }}</span>
              <span class="mobile-label">{{ protocol?.likert_labels[String(value)] }}</span>
              <i class="bi mobile-check-icon" :class="questionnaireAnswers[item.id] === value ? 'bi-check-circle-fill' : 'bi-circle'" />
            </label>
          </div>
        </div>

        <div class="questionnaire-item questionnaire-identity-item">
          <label class="form-label fw-semibold" for="questionnaire-participant-name">
            {{ questionnaireTotalCount }}. 请填写您的姓名（您参加本次实验的路径，微信名等）
          </label>
          <input
            id="questionnaire-participant-name"
            :value="participantName"
            class="form-control"
            type="text"
            maxlength="255"
            autocomplete="off"
            placeholder="请输入姓名、微信名或参加实验时使用的标识"
            @input="emit('update:participant-name', ($event.target as HTMLInputElement).value)"
          >
          <small class="form-text text-muted">该内容将与本次问卷结果一并保存和导出。</small>
        </div>

        <button
          class="btn btn-primary btn-lg mt-4 px-4"
          :disabled="!questionnaireComplete || isBusy"
          @click="emit('submit')"
        >
          <span v-if="isBusy" class="spinner-border spinner-border-sm me-2"></span>
          提交问卷
        </button>
      </template>
    </div>
  </div>
</template>

<style scoped>
.questionnaire-guidance { max-width: 820px; margin: 0 auto; }
.questionnaire-guidance-icon {
  display: grid;
  width: 52px;
  height: 52px;
  margin-bottom: 1rem;
  place-items: center;
  border-radius: var(--radius-lg);
  color: var(--color-primary);
  background: var(--color-primary-soft);
  font-size: 1.4rem;
}
.instruction-box {
  border: 1px solid var(--color-border);
  background: var(--color-surface-subtle);
  border-radius: var(--radius-lg);
  padding: 1.25rem;
  line-height: 1.9;
}
.questionnaire-item {
  padding: 1.5rem 0;
  border-bottom: 1px solid var(--color-border);
}
.questionnaire-item-title {
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
  margin-bottom: 1rem;
}
.item-number {
  display: inline-grid;
  place-items: center;
  width: 24px;
  height: 24px;
  flex: 0 0 24px;
  border-radius: 50%;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-size: 0.8rem;
  font-weight: 700;
}
.likert-grid { display: grid; grid-template-columns: repeat(7, minmax(72px, 1fr)); gap: .5rem; }
.likert-option { text-align: center; cursor: pointer; position: relative; }
.likert-option input { position: absolute; opacity: 0; }
.likert-num {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  margin: 0 auto .4rem;
  border: 1px solid var(--color-border-strong);
  border-radius: 50%;
  background: var(--color-surface);
  color: var(--color-text);
  font-weight: 600;
  transition: all var(--motion-fast) ease;
}
.likert-option.is-selected .likert-num {
  color: #fff;
  background: var(--color-primary);
  border-color: var(--color-primary);
  box-shadow: 0 4px 12px rgba(75, 73, 172, 0.3);
  transform: scale(1.05);
}
.likert-text { display: block; color: var(--color-text-muted); line-height: 1.25; font-size: .75rem; }
.likert-option.is-selected .likert-text { color: var(--color-primary); font-weight: 600; }

/* 移动端专属单选列表 (默认在桌面端隐藏) */
.mobile-likert-list { display: none; }

@media (max-width: 768px) {
  .desktop-likert { display: none; }
  .mobile-likert-list {
    display: grid;
    gap: 0.45rem;
    margin-top: 0.5rem;
  }
  .mobile-likert-item {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    min-height: 44px;
    padding: 0.6rem 0.85rem;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
    cursor: pointer;
    transition: background-color var(--motion-fast) ease, border-color var(--motion-fast) ease, box-shadow var(--motion-fast) ease;
  }
  .mobile-likert-item input { position: absolute; opacity: 0; }
  .mobile-num {
    display: grid;
    place-items: center;
    width: 28px;
    height: 28px;
    flex: 0 0 28px;
    border-radius: 50%;
    background: var(--color-surface-subtle);
    border: 1px solid var(--color-border);
    color: var(--color-text);
    font-size: 0.82rem;
    font-weight: 700;
  }
  .mobile-label {
    flex: 1;
    font-size: 0.875rem;
    color: var(--color-text);
  }
  .mobile-check-icon {
    font-size: 1.1rem;
    color: var(--color-text-muted);
  }
  .mobile-likert-item.is-active {
    background: var(--color-primary-soft);
    border-color: var(--color-primary);
    box-shadow: 0 2px 8px rgba(75, 73, 172, 0.12);
  }
  .mobile-likert-item.is-active .mobile-num {
    background: var(--color-primary);
    border-color: var(--color-primary);
    color: #fff;
  }
  .mobile-likert-item.is-active .mobile-label {
    color: var(--color-primary);
    font-weight: 600;
  }
  .mobile-likert-item.is-active .mobile-check-icon {
    color: var(--color-primary);
  }
  .questionnaire-heading { flex-wrap: wrap; gap: 0.5rem; }
}

@media (max-width: 575.98px) {
  .questionnaire-item { padding: 1.15rem 0; }
  .mobile-likert-item { padding: 0.55rem 0.75rem; }
}
</style>
