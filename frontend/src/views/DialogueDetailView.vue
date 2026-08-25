<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { adminApi } from '../api/admin'

const route = useRoute()
const router = useRouter()

const userId = route.params.userId as string
const taskId = route.params.taskId as string
const taskTitle = (route.query.title as string) || taskId

const records = ref<Array<{ id: string; role: string; content: string; timestamp: number }>>([])
const loading = ref(false)
const errorMsg = ref('')

async function loadDialogue() {
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await adminApi.getUserDialogue(userId, taskId)
    records.value = res.data || []
  } catch (e: unknown) {
    errorMsg.value = e instanceof Error ? e.message : '加载对话失败'
  } finally {
    loading.value = false
  }
}

function goBack() {
  router.push('/dialogue')
}

onMounted(loadDialogue)
</script>

<template>
  <div class="dialogue-detail-page">
    <!-- 头部 -->
    <div class="detail-header">
      <button class="btn btn-outline-secondary btn-sm" @click="goBack">
        <i class="bi bi-arrow-left me-1"></i>返回
      </button>
      <div class="header-info">
        <h5 class="mb-0">{{ taskTitle }}</h5>
        <small class="text-muted">用户：{{ userId }} · {{ records.length }} 条对话</small>
      </div>
    </div>

    <!-- 错误提示 -->
    <div v-if="errorMsg" class="alert alert-danger py-2">{{ errorMsg }}</div>

    <!-- 加载中 -->
    <div v-if="loading" class="text-center text-muted py-5">
      <div class="spinner-border spinner-border-sm me-2"></div>加载对话记录…
    </div>

    <!-- 空状态 -->
    <div v-else-if="records.length === 0" class="text-center text-muted py-5">
      <i class="bi bi-chat-dots" style="font-size: 2rem;"></i>
      <p class="mt-2">暂无对话记录</p>
    </div>

    <!-- 对话列表 -->
    <div v-else class="chat-list">
      <div
        v-for="d in records"
        :key="d.id"
        class="chat-bubble"
        :class="d.role === 'user' ? 'chat-right' : 'chat-left'"
      >
        <div class="chat-avatar">
          <span v-if="d.role === 'user'">👤</span>
          <span v-else>🤖</span>
        </div>
        <div class="chat-body">
          <div class="chat-meta">
            <span class="chat-role">{{ d.role === 'user' ? '学生' : 'AI 助手' }}</span>
            <small class="text-muted">{{ new Date(d.timestamp).toLocaleString('zh-CN') }}</small>
          </div>
          <div class="chat-content">{{ d.content }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dialogue-detail-page {
  max-width: 780px;
  margin: 0 auto;
}

.detail-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--line, #ebeaf4);
}

.header-info h5 {
  font-size: 1rem;
}

.chat-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.chat-bubble {
  display: flex;
  gap: 10px;
  max-width: 85%;
}

.chat-left {
  align-self: flex-start;
}

.chat-right {
  align-self: flex-end;
  flex-direction: row-reverse;
}

.chat-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}

.chat-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.chat-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.chat-role {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-primary);
}

.chat-right .chat-role {
  color: var(--color-info);
}

.chat-content {
  background: var(--color-surface-subtle);
  border: 1px solid var(--color-border);
  border-radius: 8px 8px 8px 2px;
  padding: 10px 14px;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--color-text);
}

.chat-right .chat-content {
  background: var(--color-primary-soft);
  border-color: var(--color-primary);
  border-radius: 8px 8px 2px 8px;
}
@media (max-width: 575.98px) {
  .detail-header { align-items: flex-start; gap: 10px; margin-bottom: 18px; }
  .chat-bubble { max-width: 96%; }
  .chat-avatar { width: 30px; height: 30px; font-size: 15px; }
  .chat-meta { flex-wrap: wrap; gap: 3px 8px; }
  .chat-content { padding: 9px 11px; font-size: 13px; }
}
</style>
