<script setup lang="ts">
import { ref, watch } from 'vue'
import apiClient from '../../api/client'
import { parseApiDate } from '../../utils/datetime'
const props = defineProps<{ reportId: string; version: number }>()
type Revision = { version_no: number; content: { summary: string; generated_at: string; template_version: string; generation_metadata?: { model?: string } | null; suggestions?: Array<{ title: string; description: string }> } }
const items = ref<Revision[]>([])
const page = ref(1)
const total = ref(0)
const loading = ref(false)
const error = ref('')
const open = ref(false)
let request = 0
async function load(nextPage = 1) {
  const token = ++request
  loading.value = true
  error.value = ''
  try {
    const response = await apiClient.get<{items: Revision[]; total: number}>(`/research/reports/${props.reportId}/versions`, {params:{page:nextPage}})
    if (token !== request) return
    items.value = response.data.items
    total.value = response.data.total
    page.value = nextPage
  } catch {
    if (token === request) error.value = '历史版本加载失败，请重试。'
  } finally { if (token === request) loading.value = false }
}
watch(() => [props.reportId, props.version], () => {
  request++; items.value = []; page.value = 1; total.value = 0
  if (open.value) void load()
})
function toggle(event: Event) {
  open.value = (event.target as HTMLDetailsElement).open
  if (open.value) void load()
}
</script>
<template>
  <details class="card border-0 shadow-sm mt-4 p-4 report-history" @toggle="toggle">
    <summary>过往报告版本（只读）</summary>
    <p class="text-muted mt-2">重新生成不会删除旧稿；历史版本不作为当前发布依据。更新前未记录的信息不会倒填。</p>
    <p v-if="loading" role="status">正在加载历史版本…</p>
    <p v-if="error" role="alert">{{ error }} <button type="button" class="btn btn-sm btn-outline-primary" @click="load(page)">重试</button></p>
    <article v-for="item in items" :key="item.version_no" class="border rounded p-3 my-2">
      <h6>V{{ item.version_no }} · {{ parseApiDate(item.content.generated_at).toLocaleString('zh-CN') }}</h6>
      <p class="text-muted">提示词 {{ item.content.template_version }} · 模型 {{ item.content.generation_metadata?.model || '历史记录未记录' }}</p>
      <p>{{ item.content.summary }}</p>
      <details><summary>查看历史建议</summary><p v-for="suggestion in item.content.suggestions" :key="suggestion.title">{{ suggestion.title }}：{{ suggestion.description }}</p></details>
    </article>
    <p v-if="!loading && !error && !total">暂无过往版本。</p>
    <div v-if="total > 5" class="d-flex align-items-center gap-2">
      <button type="button" class="btn btn-sm btn-outline-secondary" :disabled="page <= 1 || loading" @click="load(page-1)">上一页</button>
      <span>{{ page }} / {{ Math.ceil(total/5) }}</span>
      <button type="button" class="btn btn-sm btn-outline-secondary" :disabled="page*5 >= total || loading" @click="load(page+1)">下一页</button>
    </div>
  </details>
</template>
<style scoped>
.report-history { overflow-wrap:anywhere; }
summary { cursor:pointer; font-weight:600; }
@media print { .report-history { display:none; } }
</style>
