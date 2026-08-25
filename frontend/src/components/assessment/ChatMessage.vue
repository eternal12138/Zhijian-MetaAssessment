<script setup lang="ts">
import type { DialogueRole } from '../../types/assessment'

defineProps<{
  role: DialogueRole
  content: string
  timestamp: number
  /** 可选的元认知维度标签 */
  dimensionLabel?: string
  /** 可选的文件名（语音消息） */
  audioName?: string
}>()

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <div class="chat-message" :class="`is-${role}`">
    <div class="msg-avatar">
      <template v-if="role === 'agent'">
        <span class="agent-avatar-mini"><i class="bi bi-stars"></i></span>
      </template>
      <template v-else-if="role === 'user'">
        <span class="user-avatar-mini">羽</span>
      </template>
      <template v-else>
        <span class="sys-avatar-mini"><i class="bi bi-info-circle"></i></span>
      </template>
    </div>
    <div class="msg-body">
      <div class="msg-meta">
        <span class="msg-sender">
          {{ role === 'agent' ? '知见 AI' : role === 'user' ? '你' : '系统' }}
        </span>
        <span class="msg-time">{{ formatTime(timestamp) }}</span>
      </div>
      <div class="msg-bubble">
        <template v-if="audioName">
          <div class="audio-msg">
            <i class="bi bi-soundwave"></i>
            <span>{{ audioName }}</span>
            <small>{{ content }}</small>
          </div>
        </template>
        <template v-else>
          <p>{{ content }}</p>
        </template>
      </div>
      <span v-if="dimensionLabel" class="msg-dimension-tag">
        <i class="bi bi-tag-fill"></i> {{ dimensionLabel }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.chat-message { display: flex; gap: 10px; max-width: 88%; }
.chat-message.is-user { align-self: flex-end; flex-direction: row-reverse; }
.chat-message.is-system { align-self: center; max-width: 70%; opacity: .8; }
.msg-avatar { flex-shrink: 0; width: 34px; }
.agent-avatar-mini, .user-avatar-mini, .sys-avatar-mini { width: 32px; height: 32px; display: grid; place-items: center; border-radius: 50%; font-size: 13px; }
.agent-avatar-mini { background: linear-gradient(135deg, #7573e7, #4b49ac); color: #fff; }
.user-avatar-mini { background: #ffdfce; color: #b25a3e; font-weight: 700; }
.sys-avatar-mini { background: var(--color-surface-subtle); color: var(--color-text-muted); }
.msg-body { display: flex; flex-direction: column; gap: 4px; }
.is-user .msg-body { align-items: flex-end; }
.msg-meta { display: flex; gap: 8px; align-items: center; }
.is-user .msg-meta { flex-direction: row-reverse; }
.msg-sender { font-size: 11px; font-weight: 700; color: var(--ink); }
.msg-time { font-size: 10px; color: var(--color-text-muted); }
.msg-bubble { padding: 11px 16px; border-radius: 15px; font-size: 13px; line-height: 1.7; }
.is-agent .msg-bubble { background: var(--color-surface-subtle); border: 1px solid var(--color-border); color: var(--color-text); border-bottom-left-radius: 5px; }
.is-user .msg-bubble { background: var(--primary); color: #fff; border-bottom-right-radius: 5px; }
.is-system .msg-bubble { background: var(--color-surface-subtle); color: var(--color-text-muted); font-size: 12px; text-align: center; }
.msg-bubble p { margin: 0; }
.msg-bubble strong { color: inherit; }
.msg-dimension-tag { display: inline-flex; align-items: center; gap: 4px; padding: 3px 9px; border-radius: 10px; background: var(--color-warning-soft); color: var(--color-warning); font-size: 10px; font-weight: 700; }
.is-user .msg-dimension-tag { background: #ffffff2b; color: #ffdc81; }
.audio-msg { display: flex; align-items: center; gap: 8px; color: var(--muted); }
.audio-msg i { color: var(--primary); font-size: 16px; }
.audio-msg small { color: var(--color-text-muted); }
</style>
