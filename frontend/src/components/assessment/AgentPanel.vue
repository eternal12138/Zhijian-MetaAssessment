<script setup lang="ts">
import type { MetacognitionDimension } from '../../types/assessment'
import { DIMENSION_LABELS } from '../../types/assessment'

defineProps<{
  /** AI Agent 当前状态 */
  status: 'idle' | 'speaking' | 'listening' | 'thinking'
  /** 当前检测到的元认知维度事件 */
  activeDimensions: MetacognitionDimension[]
  /** 已收集到的特征片段数 */
  codedCount: number
  /** 量表总条目数 */
  totalItems: number
}>()

const statusLabels: Record<string, string> = {
  idle: '等待中',
  speaking: '正在提问...',
  listening: '正在倾听...',
  thinking: '分析中...'
}
</script>

<template>
  <div class="agent-panel">
    <div class="agent-visual">
      <div class="agent-avatar-ring" :class="`status-${status}`">
        <div class="agent-avatar-core">
          <i class="bi bi-robot"></i>
        </div>
        <svg class="agent-wave-ring" viewBox="0 0 100 100">
          <circle cx="50" cy="50" r="46" fill="none" stroke="currentColor" stroke-width="2"
            :class="{ 'is-pulsing': status === 'speaking' }" />
        </svg>
      </div>
      <div class="agent-status-badge" :class="`status-${status}`">
        <span class="status-dot"></span>
        {{ statusLabels[status] }}
      </div>
    </div>

    <div class="agent-info">
      <h4>知见 AI 测评助手</h4>
      <p>基于生成式 AI 的启发式对话测评智能体，引导你出声思维，实时捕捉元认知策略。</p>
    </div>

    <div class="agent-progress">
      <div class="progress-header">
        <span>量表覆盖进度</span>
        <strong>{{ codedCount }} / {{ totalItems }}</strong>
      </div>
      <div class="progress custom-progress">
        <div class="progress-bar" :style="{ width: `${Math.round((codedCount / totalItems) * 100)}%` }"></div>
      </div>
    </div>

    <div class="agent-dimensions">
      <h5>元认知维度感知</h5>
      <div class="dimension-list">
        <div
          v-for="dim in (['monitoring', 'controlDebugging', 'evaluation'] as MetacognitionDimension[])"
          :key="dim"
          class="dimension-indicator"
          :class="{ 'is-active': activeDimensions.includes(dim) }"
        >
          <span class="dim-dot"></span>
          <span class="dim-label">{{ DIMENSION_LABELS[dim] }}</span>
          <span v-if="activeDimensions.includes(dim)" class="dim-pulse"></span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.agent-panel { background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-lg); box-shadow: var(--shadow-xs); padding: 24px; }
.agent-visual { display: flex; flex-direction: column; align-items: center; margin-bottom: 20px; }
.agent-avatar-ring { width: 88px; height: 88px; position: relative; display: grid; place-items: center; }
.agent-avatar-core { width: 64px; height: 64px; display: grid; place-items: center; border-radius: 50%; background: linear-gradient(135deg, #7573e7, #4b49ac); color: #fff; font-size: 28px; z-index: 2; box-shadow: 0 6px 18px #4b49ac30; }
.agent-wave-ring { position: absolute; inset: 0; color: #4b49ac22; }
.agent-wave-ring :deep(.is-pulsing) { animation: ringPulse 2s infinite var(--ease-out); }
.agent-status-badge { display: flex; align-items: center; gap: 6px; margin-top: 12px; padding: 5px 12px; border-radius: 20px; font-size: 11px; font-weight: 700; color: var(--muted); background: var(--color-surface-subtle); }
.status-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--color-text-muted); }
.status-speaking .status-dot { background: #4b49ac; animation: dotBlink .8s infinite; }
.status-listening .status-dot { background: #37b789; animation: dotBlink 1.5s infinite; }
.status-thinking .status-dot { background: #f0a854; animation: dotBlink .5s infinite; }
.agent-status-badge.status-speaking { color: var(--color-primary); background: var(--color-primary-soft); }
.agent-status-badge.status-listening { color: var(--color-success); background: var(--color-success-soft); }
.agent-status-badge.status-thinking { color: var(--color-warning); background: var(--color-warning-soft); }
.agent-info h4 { font-size: 15px; font-weight: 700; margin: 0 0 6px; }
.agent-info p { color: var(--muted); font-size: 11px; line-height: 1.7; margin: 0; }
.agent-progress { margin: 18px 0; padding: 12px; border-radius: 8px; background: var(--color-surface-subtle); border: 1px solid var(--color-border); }
.progress-header { display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 8px; }
.progress-header span { color: var(--muted); }
.progress-header strong { color: var(--primary); }
.agent-dimensions h5 { font-size: 12px; font-weight: 700; color: var(--muted); margin: 0 0 10px; text-transform: uppercase; letter-spacing: .5px; }
.dimension-list { display: flex; flex-direction: column; gap: 8px; }
.dimension-indicator { display: flex; align-items: center; gap: 9px; padding: 8px 11px; border-radius: 8px; background: var(--color-surface-subtle); color: var(--color-text); font-size: 12px; transition: background .2s; }
.dimension-indicator.is-active { background: var(--color-primary-soft); }
.dim-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--color-border-strong); }
.dimension-indicator.is-active .dim-dot { background: var(--primary); }
.dim-label { color: var(--color-text-muted); }
.dimension-indicator.is-active .dim-label { color: var(--primary); font-weight: 700; }
.dim-pulse { width: 6px; height: 6px; border-radius: 50%; background: #37b789; margin-left: auto; animation: dotBlink 1s infinite; }
@keyframes ringPulse { 0% { opacity: .6; } 100% { opacity: .05; } }
@keyframes dotBlink { 0%, 100% { opacity: 1; } 50% { opacity: .35; } }
@media (prefers-reduced-motion: reduce) {
  .agent-wave-ring :deep(.is-pulsing),
  .status-dot,
  .dim-pulse { animation: none; }
}
</style>
