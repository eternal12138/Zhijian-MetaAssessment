<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { researchApi, type AnalysisJob } from '../../api/research'
import { parseApiDate } from '../../utils/datetime'
const emit = defineEmits<{ completed: [] }>()
const jobs = ref<AnalysisJob[]>([])
const error = ref('')
let disposed = false
let timer: ReturnType<typeof setTimeout> | undefined
let previous: Map<string, string> | null = null
const labels: Record<string, string> = { queued: '排队中', running: 'AI 生成中', completed: '已生成 · 待审阅', failed: '生成失败 · 原稿保留' }
function time(value?: string | null) {
  return value ? parseApiDate(value).toLocaleString('zh-CN') : '—'
}
async function refresh() {
  try {
    const rows = (await researchApi.listAnalysisJobs()).data
    if (disposed) return
    if (previous && rows.some(j => j.status === 'completed' && previous!.get(j.id) !== 'completed')) emit('completed')
    previous = new Map(rows.map(j => [j.id, j.status]))
    jobs.value = rows
    error.value = ''
  } catch {
    if (!disposed) error.value = '生成任务状态暂时加载失败；不代表任务失败。'
  }
}
async function poll() {
  await refresh()
  if (!disposed) timer = setTimeout(poll, 5000)
}
onMounted(poll)
onUnmounted(() => { disposed = true; clearTimeout(timer) })
</script>

<template>
  <details class="report-jobs mb-3">
    <summary>报告生成任务 · {{ jobs.filter(j => ['queued', 'running'].includes(j.status)).length }} 份处理中</summary>
    <p class="text-muted small mt-2">已提交任务在后台处理，关闭页面不会中断；批量操作尚未提交的部分需保持页面打开。失败可从对应测评或草稿重新提交。</p>
    <p v-if="error" role="alert" class="text-warning">{{ error }}</p>
    <p v-if="!jobs.length && !error" class="text-muted">暂无生成任务。</p>
    <ol class="job-list">
      <li v-for="job in jobs" :key="job.id">
        <div class="d-flex justify-content-between gap-2 flex-wrap">
          <strong>{{ labels[job.status] || job.status }}</strong>
          <span>{{ time(job.created_at) }}</span>
        </div>
        <small>测评轮次：{{ job.run_id }}</small>
        <progress v-if="['queued', 'running'].includes(job.status)" :value="job.progress" max="100" :aria-label="'报告处理阶段进度 ' + job.progress + '%'" />
        <small v-if="job.status === 'running'">{{ job.progress }}%（阶段进度）· 最近心跳 {{ time(job.heartbeat_at) }}</small>
        <p v-if="job.error_message" class="text-danger mb-0">{{ job.error_message }}</p>
        <RouterLink v-if="job.result_profile_id" :to="{path:'/report-review',query:{id:job.result_profile_id}}">查看并审阅草稿</RouterLink>
      </li>
    </ol>
  </details>
</template>

<style scoped>
.report-jobs { padding: 1rem; border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface-subtle); }
.report-jobs summary { cursor: pointer; font-weight: 600; }
.job-list { display: grid; gap: .8rem; padding: 0; list-style: none; max-height: 360px; overflow-y: auto; }
.job-list li { display: grid; gap: .4rem; padding: .75rem; border: 1px solid var(--color-border); border-radius: var(--radius-md); overflow-wrap: anywhere; }
.job-list small { color: var(--color-text-muted); }
progress { width: 100%; accent-color: var(--color-primary); }
</style>
