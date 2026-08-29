<script setup lang="ts">
import { computed } from 'vue'
const props = withDefaults(defineProps<{ page: number; pageSize: number; total: number; label: string; disabled?: boolean }>(), { disabled: false })
const emit = defineEmits<{ 'update:page': [number]; 'update:pageSize': [number] }>()
const pages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))
const start = computed(() => props.total ? (props.page - 1) * props.pageSize + 1 : 0)
const end = computed(() => Math.min(props.page * props.pageSize, props.total))
function jump(event: Event) {
  const input = event.target as HTMLInputElement
  const value = Number(input.value)
  const page = Number.isFinite(value) ? Math.max(1, Math.min(pages.value, Math.trunc(value))) : props.page
  // Also restore invalid input when the clamped page equals the current page.
  input.value = String(page)
  emit('update:page', page)
}
</script>

<template>
  <nav class="section-pager" :aria-label="`${label}分页`">
    <span class="pager-count" aria-live="polite">共 {{ total }} 条 · 当前 {{ start }}–{{ end }} 条</span>
    <label class="pager-size">每页
      <select class="form-select form-select-sm" :value="pageSize" :disabled="disabled" :aria-label="`${label}每页数量`" @change="emit('update:pageSize', Number(($event.target as HTMLSelectElement).value))">
        <option v-for="size in [10, 20, 50]" :key="size" :value="size">{{ size }} 条</option>
      </select>
    </label>
    <div class="pager-navigation">
      <button type="button" class="btn btn-sm btn-outline-secondary" :disabled="disabled || page <= 1" @click="emit('update:page', page - 1)">上一页</button>
      <label class="pager-jump">第 <input class="form-control form-control-sm" type="number" :value="page" min="1" :max="pages" :disabled="disabled" :aria-label="`${label}跳转页码`" @change="jump"> / {{ pages }} 页</label>
      <button type="button" class="btn btn-sm btn-outline-secondary" :disabled="disabled || page >= pages" @click="emit('update:page', page + 1)">下一页</button>
    </div>
  </nav>
</template>

<style scoped>
.section-pager { display:flex; flex-wrap:wrap; align-items:center; gap:.75rem 1rem; border-top:1px solid var(--color-border, #ddd); margin-top:1rem; padding-top:1rem; color:var(--color-text-muted); font-size:.875rem; }
.pager-count { margin-right:auto; font-variant-numeric:tabular-nums; }
.pager-size, .pager-navigation, .pager-jump { display:flex; align-items:center; gap:.5rem; white-space:nowrap; }
.pager-size select { width:5.5rem; min-height:36px; }
.pager-jump input { width:4rem; min-height:36px; text-align:center; }
.pager-navigation .btn { min-height:36px; }
@media (max-width:575px) { .pager-navigation { width:100%; justify-content:space-between; gap:.25rem; } .pager-jump { gap:.25rem; } }
</style>
