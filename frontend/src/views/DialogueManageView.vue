<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  adminApi,
  type AdminDataRecord,
  type AdminDeleteDataResult,
  type AdminDeletionImpact
} from '../api/admin'
import { confirmAction, notify } from '../composables/useUiFeedback'
import AppPageHeader from '../components/ui/AppPageHeader.vue'
import { apiDateTimestamp, parseApiDate } from '../utils/datetime'

type DataCategory = 'overview' | 'audio' | 'transcripts' | 'questionnaire'

const records = ref<AdminDataRecord[]>([])
const loading = ref(false)
const errorMsg = ref('')
const searchQuery = ref('')
const activeCategory = ref<DataCategory>('overview')
const deletingKey = ref('')
const expandedUserIds = ref<string[]>([])
const expandedRunIds = ref<string[]>([])
const selectedRunIds = ref<string[]>([])
const bulkProgress = ref({ completed: 0, total: 0 })
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const totalPages = ref(1)
const categoryCounts = ref<Record<DataCategory, number>>({
  overview: 0, audio: 0, transcripts: 0, questionnaire: 0
})
let searchTimer: number | null = null

const categories: Array<{
  key: DataCategory
  label: string
  icon: string
  description: string
}> = [
  {
    key: 'overview',
    label: '测评记录',
    icon: 'bi-collection-fill',
    description: '查看整次测评及其任务、录音、转录和问卷汇总。'
  },
  {
    key: 'audio',
    label: '录音数据',
    icon: 'bi-mic-fill',
    description: '单独查看并删除浏览器录音分片和服务端音频文件。'
  },
  {
    key: 'transcripts',
    label: '转录与分析',
    icon: 'bi-file-earmark-text-fill',
    description: '单独查看并删除转录、对话和由其产生的编码数据。'
  },
  {
    key: 'questionnaire',
    label: '问卷数据',
    icon: 'bi-ui-checks-grid',
    description: '单独查看并删除问卷答案及填写问卷时提供的微信名。'
  }
]

const activeCategoryInfo = computed(() => (
  categories.find(item => item.key === activeCategory.value) ?? categories[0]
))

const visibleRecords = computed(() => records.value)

const groupedRecords = computed(() => {
  const groups = new Map<string, { user: AdminDataRecord; records: AdminDataRecord[] }>()
  for (const item of visibleRecords.value) {
    const existing = groups.get(item.user_id)
    if (existing) {
      existing.records.push(item)
    } else {
      groups.set(item.user_id, { user: item, records: [item] })
    }
  }
  return [...groups.values()]
    .map(group => ({
      ...group,
      records: [...group.records].sort((left, right) => (
        apiDateTimestamp(right.started_at) - apiDateTimestamp(left.started_at)
      ))
    }))
    .sort((left, right) => left.user.username.localeCompare(right.user.username, 'zh-CN'))
})
const visibleRunIds = computed(() => visibleRecords.value.map(item => item.run_id))
const selectedVisibleRecords = computed(() => visibleRecords.value.filter(
  item => selectedRunIds.value.includes(item.run_id)
))
const allVisibleSelected = computed(() => (
  visibleRunIds.value.length > 0
  && visibleRunIds.value.every(id => selectedRunIds.value.includes(id))
))

async function loadRecords() {
  loading.value = true
  errorMsg.value = ''
  try {
    const response = await adminApi.listDataRecords({
      page: page.value,
      page_size: pageSize.value,
      keyword: searchQuery.value.trim() || undefined,
      category: activeCategory.value
    })
    records.value = response.data.items
    page.value = response.data.page
    total.value = response.data.total
    totalPages.value = response.data.total_pages
    categoryCounts.value = response.data.category_counts
  } catch (error) {
    errorMsg.value = error instanceof Error ? error.message : '数据记录加载失败'
  } finally {
    loading.value = false
  }
}

function isUserExpanded(userId: string) {
  return expandedUserIds.value.includes(userId)
}

function toggleUser(userId: string) {
  expandedUserIds.value = isUserExpanded(userId)
    ? expandedUserIds.value.filter(item => item !== userId)
    : [...expandedUserIds.value, userId]
}

function isRunExpanded(runId: string) {
  return expandedRunIds.value.includes(runId)
}

function toggleRun(runId: string) {
  expandedRunIds.value = isRunExpanded(runId)
    ? expandedRunIds.value.filter(item => item !== runId)
    : [...expandedRunIds.value, runId]
}

function isRunSelected(runId: string) {
  return selectedRunIds.value.includes(runId)
}

function setRunSelected(runId: string, selected: boolean) {
  selectedRunIds.value = selected
    ? [...new Set([...selectedRunIds.value, runId])]
    : selectedRunIds.value.filter(item => item !== runId)
}

function onRunSelectionChange(runId: string, event: Event) {
  setRunSelected(runId, (event.target as HTMLInputElement).checked)
}

function toggleVisibleSelection() {
  if (allVisibleSelected.value) {
    const visible = new Set(visibleRunIds.value)
    selectedRunIds.value = selectedRunIds.value.filter(id => !visible.has(id))
  } else {
    selectedRunIds.value = [...new Set([...selectedRunIds.value, ...visibleRunIds.value])]
  }
}

function groupSelectionState(runIds: string[]) {
  const selected = runIds.filter(id => selectedRunIds.value.includes(id)).length
  return { checked: selected === runIds.length && runIds.length > 0, indeterminate: selected > 0 && selected < runIds.length }
}

function toggleGroupSelection(runIds: string[]) {
  const state = groupSelectionState(runIds)
  if (state.checked) {
    const groupIds = new Set(runIds)
    selectedRunIds.value = selectedRunIds.value.filter(id => !groupIds.has(id))
  } else {
    selectedRunIds.value = [...new Set([...selectedRunIds.value, ...runIds])]
  }
}

function formatDate(value: string | null) {
  if (!value) return '未完成'
  const date = parseApiDate(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  }).format(date)
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 ** 2).toFixed(1)} MB`
}

function statusLabel(status: string) {
  return ({
    completed: '已完成',
    in_progress: '进行中',
    abandoned: '已中止',
    preparation: '准备中',
    paused: '已暂停'
  } as Record<string, string>)[status] ?? status
}

function statusClass(status: string) {
  if (status === 'completed') return 'status-completed'
  if (status === 'in_progress') return 'status-progress'
  return 'status-muted'
}

function deleteCopy(record: AdminDataRecord, impact: AdminDeletionImpact) {
  const identity = `${record.name}（${record.username}）在 ${formatDate(record.started_at)} 开始的测评`
  if (activeCategory.value === 'audio') {
    return {
      title: '删除录音数据',
      message: `关联检查完成：将删除${identity}的 ${impact.audio_chunk_count} 个录音分片和 ${impact.audio_file_count} 个服务端音频文件；保留 ${impact.transcript_segment_count} 段转录、${impact.candidate_count} 条候选、${impact.coding_record_count} 条编码及问卷。确定继续吗？`,
      confirmText: '删除录音'
    }
  }
  if (activeCategory.value === 'transcripts') {
    return {
      title: '删除转录与分析数据',
      message: `关联检查完成：将删除${identity}的 ${impact.transcript_segment_count} 段转录、${impact.extraction_job_count} 个抽取版本、${impact.candidate_count} 条候选、${impact.candidate_revision_count} 条候选历史和 ${impact.coding_record_count} 条编码记录；录音和问卷保留。`,
      confirmText: '删除转录数据'
    }
  }
  if (activeCategory.value === 'questionnaire') {
    return {
      title: '删除问卷数据',
      message: `关联检查完成：将删除${identity}的 ${impact.questionnaire_response_count} 道问卷答案及填写的微信名；录音、转录、${impact.candidate_count} 条候选和 ${impact.coding_record_count} 条编码记录保留。`,
      confirmText: '删除问卷'
    }
  }
  return {
    title: '删除整次测评',
    message: `关联检查完成：将永久删除${identity}的 ${impact.audio_chunk_count} 个录音分片、${impact.audio_file_count} 个音频文件、${impact.transcript_segment_count} 段转录、${impact.candidate_count} 条候选、${impact.candidate_revision_count} 条候选历史、${impact.coding_record_count} 条编码记录及 ${impact.questionnaire_response_count} 道问卷答案。该操作不可恢复。`,
    confirmText: '删除整次测评'
  }
}

function bulkDeleteCopy(count: number, impact: AdminDeletionImpact) {
  if (activeCategory.value === 'audio') return {
    title: `批量删除 ${count} 次测评的录音`,
    message: `关联检查完成：将删除 ${impact.audio_chunk_count} 个录音分片和 ${impact.audio_file_count} 个音频文件；转录、候选、编码和问卷保留。操作会逐条执行并记录审计日志。`,
    confirmText: `确认删除 ${count} 条录音`
  }
  if (activeCategory.value === 'transcripts') return {
    title: `批量删除 ${count} 次测评的转录与分析`,
    message: `关联检查完成：将删除 ${impact.transcript_segment_count} 段转录、${impact.extraction_job_count} 个抽取版本、${impact.candidate_count} 条候选、${impact.candidate_revision_count} 条候选历史和 ${impact.coding_record_count} 条编码记录；录音和问卷保留。`,
    confirmText: `确认删除 ${count} 条转录`
  }
  if (activeCategory.value === 'questionnaire') return {
    title: `批量删除 ${count} 次测评的问卷`,
    message: `关联检查完成：将删除 ${impact.questionnaire_response_count} 道问卷答案及相应微信名；录音、转录、候选和编码记录保留。`,
    confirmText: `确认删除 ${count} 份问卷`
  }
  return {
    title: `永久删除 ${count} 次完整测评`,
    message: `关联检查完成：将删除 ${impact.audio_chunk_count} 个录音分片、${impact.audio_file_count} 个音频文件、${impact.transcript_segment_count} 段转录、${impact.candidate_count} 条候选、${impact.candidate_revision_count} 条候选历史、${impact.coding_record_count} 条编码记录和 ${impact.questionnaire_response_count} 道问卷答案。操作不可恢复。`,
    confirmText: `永久删除 ${count} 次测评`
  }
}

function deleteByCategory(runId: string) {
  if (activeCategory.value === 'audio') return adminApi.deleteDataAudio(runId)
  if (activeCategory.value === 'transcripts') return adminApi.deleteDataTranscripts(runId)
  if (activeCategory.value === 'questionnaire') return adminApi.deleteDataQuestionnaire(runId)
  return adminApi.deleteDataRun(runId)
}

async function deleteRecord(record: AdminDataRecord) {
  const key = `${activeCategory.value}-${record.run_id}`
  deletingKey.value = key
  try {
    const impact = (await adminApi.getDataDeletionImpact(record.run_id)).data
    const copy = deleteCopy(record, impact)
    const confirmed = await confirmAction({ ...copy, tone: 'danger' })
    if (!confirmed) return
    const response: { data: AdminDeleteDataResult } = await deleteByCategory(record.run_id)
    const fileWarning = response.data.failed_files
      ? `，另有 ${response.data.failed_files} 个文件未能清理，请查看服务器日志`
      : ''
    notify(`${response.data.message}${fileWarning}`, response.data.failed_files ? 'warning' : 'success')
    await loadRecords()
  } catch (error) {
    notify(error instanceof Error ? error.message : '删除失败', 'danger')
  } finally {
    deletingKey.value = ''
  }
}

async function bulkDeleteSelected() {
  const targets = selectedVisibleRecords.value
  if (!targets.length || deletingKey.value) return
  if (targets.length > 100) {
    notify('为避免误操作和服务器压力，每次最多批量删除 100 条，请缩小查找范围后重试。', 'warning', 6000)
    return
  }
  deletingKey.value = 'bulk-preflight'
  try {
    const runIds = targets.map(item => item.run_id)
    const preflight = (await adminApi.getBulkDataDeletionImpact(runIds)).data
    const confirmed = await confirmAction({
      ...bulkDeleteCopy(preflight.run_count, preflight.totals), tone: 'danger'
    })
    if (!confirmed) return

    deletingKey.value = 'bulk'
    bulkProgress.value = { completed: 0, total: targets.length }
    const failed: string[] = []
    let failedFiles = 0
    for (const target of targets) {
      try {
        const response = await deleteByCategory(target.run_id)
        failedFiles += response.data.failed_files ?? 0
        selectedRunIds.value = selectedRunIds.value.filter(id => id !== target.run_id)
      } catch (error) {
        failed.push(`${target.name}（${target.username}）${formatDate(target.started_at)}`)
      } finally {
        bulkProgress.value.completed += 1
      }
    }
    await loadRecords()
    if (failed.length) {
      notify(`批量操作完成：成功 ${targets.length - failed.length} 条，失败 ${failed.length} 条。失败记录仍保持选中，可再次处理。`, 'warning', 6000)
    } else if (failedFiles) {
      notify(`已完成 ${targets.length} 条批量删除，另有 ${failedFiles} 个文件未能清理，请查看服务器日志。`, 'warning', 6000)
    } else {
      notify(`已完成 ${targets.length} 条${activeCategoryInfo.value.label}批量删除。`, 'success')
    }
  } catch (error) {
    notify(error instanceof Error ? error.message : '批量删除预检失败', 'danger')
  } finally {
    deletingKey.value = ''
    bulkProgress.value = { completed: 0, total: 0 }
  }
}

watch(activeCategory, () => {
  selectedRunIds.value = []
  expandedUserIds.value = []
  expandedRunIds.value = []
  page.value = 1
  void loadRecords()
})

watch(searchQuery, () => {
  selectedRunIds.value = []
  page.value = 1
  if (searchTimer !== null) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => void loadRecords(), 350)
})

onMounted(loadRecords)
onBeforeUnmount(() => {
  if (searchTimer !== null) window.clearTimeout(searchTimer)
})
</script>

<template>
  <div class="data-management-page">
    <AppPageHeader
      eyebrow="系统管理"
      title="数据管理"
      icon="bi-database-fill-gear"
      description="按账号和测评时间管理录音、转录、问卷及完整测评记录。删除操作会写入审计日志。"
      compact
    />

    <div class="data-category-grid" role="tablist" aria-label="数据类型">
      <button
        v-for="category in categories"
        :key="category.key"
        class="data-category-card"
        :class="{ active: activeCategory === category.key }"
        type="button"
        role="tab"
        :aria-selected="activeCategory === category.key"
        @click="activeCategory = category.key"
      >
        <span class="category-icon"><i class="bi" :class="category.icon" /></span>
        <span class="category-copy">
          <strong>{{ category.label }}</strong>
          <small>{{ category.description }}</small>
        </span>
        <span class="category-count">{{ categoryCounts[category.key] }}</span>
      </button>
    </div>

    <section class="data-toolbar card border-0 shadow-sm" aria-label="数据筛选">
      <div>
        <h5>{{ activeCategoryInfo.label }}</h5>
        <p>{{ activeCategoryInfo.description }} 共 {{ total }} 条；每页按测评开始时间倒序排列。</p>
      </div>
      <label class="search-box">
        <i class="bi bi-search" aria-hidden="true" />
        <span class="visually-hidden">查找账号、姓名、班级或微信名</span>
        <input
          v-model="searchQuery"
          type="search"
          class="form-control"
          placeholder="查找账号、姓名、班级或微信名"
        >
      </label>
    </section>

    <section v-if="!loading && visibleRecords.length" class="bulk-toolbar card border-0 shadow-sm" aria-label="批量操作">
      <label class="bulk-select-all">
        <input type="checkbox" class="form-check-input" :checked="allVisibleSelected" @change="toggleVisibleSelection">
        <span>{{ allVisibleSelected ? '取消选择当前结果' : '选择当前全部结果' }}</span>
      </label>
      <div class="bulk-actions">
        <span v-if="selectedVisibleRecords.length" class="selected-count">已选择 {{ selectedVisibleRecords.length }} 条</span>
        <button v-if="selectedVisibleRecords.length" class="btn btn-sm btn-link text-secondary" type="button" :disabled="Boolean(deletingKey)" @click="selectedRunIds = []">清除选择</button>
        <button class="btn btn-danger" type="button" :disabled="!selectedVisibleRecords.length || Boolean(deletingKey)" @click="bulkDeleteSelected">
          <span v-if="deletingKey.startsWith('bulk')" class="spinner-border spinner-border-sm me-1" />
          <i v-else class="bi bi-trash3-fill me-1" />
          <template v-if="deletingKey === 'bulk'">正在处理 {{ bulkProgress.completed }}/{{ bulkProgress.total }}</template>
          <template v-else-if="deletingKey === 'bulk-preflight'">正在核对关联数据</template>
          <template v-else>批量删除{{ activeCategory === 'overview' ? '完整测评' : activeCategoryInfo.label }}</template>
        </button>
      </div>
    </section>

    <div v-if="errorMsg" class="alert alert-danger d-flex align-items-center gap-2">
      <i class="bi bi-exclamation-triangle-fill" />
      <span>{{ errorMsg }}</span>
      <button class="btn btn-sm btn-outline-danger ms-auto" type="button" @click="loadRecords">重新加载</button>
    </div>

    <div v-if="loading" class="loading-state card border-0 shadow-sm">
      <span class="spinner-border spinner-border-sm text-primary" aria-hidden="true" />
      正在读取研究数据…
    </div>

    <div v-else-if="groupedRecords.length === 0" class="empty-state card border-0 shadow-sm">
      <i class="bi bi-inbox" />
      <h5>没有符合条件的数据</h5>
      <p>请切换数据类型或调整查找条件。</p>
    </div>

    <div v-else class="account-groups">
      <section v-for="group in groupedRecords" :key="group.user.user_id" class="account-group">
        <div class="account-header-row">
          <label class="selection-control" :title="`选择 ${group.user.name} 的当前记录`">
            <input
              type="checkbox"
              class="form-check-input"
              :checked="groupSelectionState(group.records.map(item => item.run_id)).checked"
              :indeterminate="groupSelectionState(group.records.map(item => item.run_id)).indeterminate"
              @change="toggleGroupSelection(group.records.map(item => item.run_id))"
            >
            <span class="visually-hidden">选择该账号当前分类下的全部记录</span>
          </label>
          <button
            class="account-header"
            type="button"
            :aria-expanded="isUserExpanded(group.user.user_id)"
            :aria-controls="`account-records-${group.user.user_id}`"
            @click="toggleUser(group.user.user_id)"
          >
            <span class="account-identity">
              <strong>{{ group.user.name }}</strong>
              <code>{{ group.user.username }}</code>
            </span>
            <i class="bi account-chevron" :class="isUserExpanded(group.user.user_id) ? 'bi-chevron-up' : 'bi-chevron-down'" aria-hidden="true" />
          </button>
        </div>

        <div
          v-if="isUserExpanded(group.user.user_id)"
          :id="`account-records-${group.user.user_id}`"
          class="account-content"
        >
          <div class="account-meta">
            <span><i class="bi bi-mortarboard me-1" />{{ group.user.class_group || '未分配班级' }}</span>
            <span><i class="bi bi-collection me-1" />{{ group.records.length }} 条当前类型记录</span>
          </div>
          <div class="record-list">
          <article v-for="record in group.records" :key="record.run_id" class="record-card" :class="{ 'is-selected': isRunSelected(record.run_id) }">
            <div class="record-heading-row">
              <label class="selection-control record-selection" title="选择这次测评">
                <input type="checkbox" class="form-check-input" :checked="isRunSelected(record.run_id)" @change="onRunSelectionChange(record.run_id, $event)">
                <span class="visually-hidden">选择这次测评</span>
              </label>
              <button
                class="record-main record-toggle"
                type="button"
                :aria-expanded="isRunExpanded(record.run_id)"
                :aria-controls="`record-details-${record.run_id}`"
                @click="toggleRun(record.run_id)"
              >
              <div class="record-time">
                <span>测评开始时间</span>
                <strong><i class="bi bi-calendar3 me-1" />{{ formatDate(record.started_at) }}</strong>
                <small>完成时间：{{ formatDate(record.completed_at) }}</small>
                <small class="record-summary-meta">
                  录音 {{ record.audio_chunk_count }} · 转录 {{ record.transcript_count }} · 问卷 {{ record.questionnaire_response_count }}
                </small>
              </div>
              <span class="record-toggle-state">
                <span class="record-status" :class="statusClass(record.status)">
                  {{ statusLabel(record.status) }}
                </span>
                <i class="bi" :class="isRunExpanded(record.run_id) ? 'bi-chevron-up' : 'bi-chevron-down'" aria-hidden="true" />
              </span>
              </button>
            </div>

            <div v-if="isRunExpanded(record.run_id)" :id="`record-details-${record.run_id}`" class="record-details-body">
            <dl class="identity-grid">
              <div>
                <dt>账号姓名</dt>
                <dd>{{ record.name }}</dd>
              </div>
              <div class="wechat-field">
                <dt>问卷填写的微信名／实验标识</dt>
                <dd>{{ record.questionnaire_participant_name || '未填写或已删除' }}</dd>
              </div>
              <div>
                <dt>测评批次编号</dt>
                <dd class="run-id">{{ record.run_id }}</dd>
              </div>
            </dl>

            <div class="data-metrics">
              <div><i class="bi bi-mic" /><span>录音</span><strong>{{ record.audio_chunk_count }} 片</strong><small>{{ formatBytes(record.audio_size_bytes) }}</small></div>
              <div><i class="bi bi-file-earmark-text" /><span>转录</span><strong>{{ record.transcript_count }} 段</strong><small>{{ record.dialogue_count }} 条对话</small></div>
              <div><i class="bi bi-tags" /><span>编码</span><strong>{{ record.coded_segment_count }} 段</strong><small>衍生分析</small></div>
              <div><i class="bi bi-ui-checks" /><span>问卷</span><strong>{{ record.questionnaire_response_count }} 题</strong><small>{{ record.questionnaire_enabled ? '协议已启用' : '协议未启用' }}</small></div>
            </div>

            <details v-if="record.tasks.length" class="task-details">
              <summary>查看 {{ record.tasks.length }} 个任务的时间与数据</summary>
              <div class="task-records">
                <div v-for="task in record.tasks" :key="task.session_id" class="task-record">
                  <div>
                    <strong>任务{{ task.sequence_no }} · {{ task.task_title }}</strong>
                    <small>{{ formatDate(task.started_at) }} — {{ formatDate(task.completed_at) }}</small>
                  </div>
                  <span>{{ task.audio_chunk_count }} 个录音分片 · {{ task.transcript_count }} 段转录</span>
                </div>
              </div>
            </details>

            <footer class="record-footer">
              <p><i class="bi bi-shield-check me-1" />删除后不可恢复，操作人和删除类型会记录到审计日志。</p>
              <button
                class="btn btn-outline-danger"
                type="button"
                :disabled="deletingKey === `${activeCategory}-${record.run_id}`"
                @click="deleteRecord(record)"
              >
                <span v-if="deletingKey === `${activeCategory}-${record.run_id}`" class="spinner-border spinner-border-sm me-1" />
                <i v-else class="bi bi-trash3 me-1" />
                {{ activeCategory === 'overview' ? '删除整次测评' : `删除${activeCategoryInfo.label}` }}
              </button>
            </footer>
            </div>
          </article>
          </div>
        </div>
      </section>
      <nav class="data-pagination card border-0 shadow-sm" aria-label="数据记录分页">
        <button class="btn btn-outline-secondary" type="button" :disabled="page <= 1 || loading" @click="page -= 1; loadRecords()">上一页</button>
        <span>第 {{ page }} / {{ totalPages }} 页 · 共 {{ total }} 条</span>
        <label>每页<select v-model.number="pageSize" class="form-select form-select-sm" @change="page = 1; loadRecords()"><option :value="10">10</option><option :value="20">20</option><option :value="50">50</option></select></label>
        <button class="btn btn-outline-secondary" type="button" :disabled="page >= totalPages || loading" @click="page += 1; loadRecords()">下一页</button>
      </nav>
    </div>
  </div>
</template>

<style scoped>
.data-management-page { max-width: 1240px; margin: 0 auto; }
.data-category-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: .85rem;
  margin-bottom: 1rem;
}
.data-category-card {
  position: relative;
  display: flex;
  min-width: 0;
  align-items: center;
  gap: .75rem;
  padding: .9rem;
  border: 1px solid var(--color-border);
  border-radius: 14px;
  color: var(--color-text);
  background: var(--color-surface);
  text-align: left;
  transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
}
.data-category-card:hover { border-color: var(--color-primary-hover); transform: translateY(-1px); }
.data-category-card.active { border-color: var(--color-primary); box-shadow: 0 8px 22px rgba(75,73,172,.13); }
.category-icon {
  display: grid;
  width: 42px;
  height: 42px;
  flex: 0 0 42px;
  place-items: center;
  border-radius: 11px;
  color: var(--color-primary);
  background: var(--color-primary-soft);
  font-size: 1.05rem;
}
.category-copy { min-width: 0; flex: 1; }
.category-copy strong, .category-copy small { display: block; }
.category-copy strong { font-size: .9rem; }
.category-copy small {
  display: -webkit-box;
  margin-top: .18rem;
  overflow: hidden;
  color: var(--color-text-muted);
  font-size: .68rem;
  line-height: 1.4;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
.category-count { color: var(--color-primary); font-size: .78rem; font-weight: 750; }
.data-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
  padding: 1rem 1.1rem;
  border-radius: 14px;
}
.data-toolbar h5 { margin: 0; color: var(--color-text); font-size: 1rem; }
.data-toolbar p { margin: .25rem 0 0; color: var(--color-text-muted); font-size: .76rem; }
.bulk-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 1rem; margin-bottom: 1rem; padding: .8rem 1rem; border: 1px solid var(--color-border) !important; border-radius: 14px; }
.bulk-select-all, .bulk-actions { display: flex; align-items: center; gap: .65rem; }
.bulk-select-all { color: var(--color-text-secondary); font-size: .8rem; font-weight: 650; cursor: pointer; }
.bulk-actions { justify-content: flex-end; }
.selected-count { padding: .28rem .6rem; border-radius: 999px; color: var(--color-primary); background: var(--color-primary-soft); font-size: .72rem; font-weight: 750; }
.bulk-actions .btn-danger { min-height: 38px; }
.search-box { position: relative; width: min(360px, 100%); }
.search-box > i { position: absolute; top: 50%; left: .85rem; z-index: 1; color: var(--color-text-muted); transform: translateY(-50%); }
.search-box .form-control { min-height: 42px; padding-left: 2.45rem; border-radius: 11px; }
.loading-state, .empty-state { display: grid; min-height: 220px; place-items: center; padding: 2rem; border-radius: 16px; color: var(--color-text-muted); text-align: center; }
.loading-state { display: flex; align-items: center; justify-content: center; gap: .65rem; }
.empty-state i { color: var(--color-text-muted); font-size: 2rem; }
.empty-state h5 { margin: .5rem 0 0; color: var(--color-text); }
.empty-state p { margin: .25rem 0 0; font-size: .82rem; }
.account-groups { display: grid; gap: 1.25rem; }
.account-group { overflow: hidden; border: 1px solid var(--color-border); border-radius: 16px; background: var(--color-surface-subtle); }
.account-header-row, .record-heading-row { display: flex; align-items: stretch; background: var(--color-surface); }
.selection-control { display: grid; flex: 0 0 48px; place-items: center; margin: 0; cursor: pointer; }
.selection-control .form-check-input { width: 1.05rem; height: 1.05rem; margin: 0; cursor: pointer; }
.account-header {
  display: flex;
  width: 100%;
  min-height: 62px;
  align-items: center;
  justify-content: space-between;
  gap: .8rem;
  padding: .9rem 1.1rem;
  border: 0;
  color: var(--color-text);
  background: var(--color-surface);
  text-align: left;
}
.account-header:hover { background: var(--color-primary-soft); }
.account-header:focus-visible { position: relative; z-index: 1; outline: 0; box-shadow: inset 0 0 0 3px rgba(75,73,172,.2); }
.account-identity { display: flex; min-width: 0; align-items: center; flex-wrap: wrap; gap: .55rem; }
.account-identity strong { font-size: .95rem; }
.account-identity code { padding: .18rem .45rem; border-radius: 5px; color: var(--color-text-secondary); background: var(--color-surface-subtle); font-size: .72rem; }
.account-chevron { flex: 0 0 auto; color: var(--color-text-muted); font-size: .9rem; }
.account-content { border-top: 1px solid var(--color-border); }
.account-meta { display: flex; align-items: center; flex-wrap: wrap; gap: .65rem 1.1rem; padding: .7rem .95rem 0; color: var(--color-text-muted); font-size: .72rem; }
.record-list { display: grid; gap: .85rem; padding: .85rem; }
.record-card { overflow: hidden; border: 1px solid var(--color-border); border-radius: 13px; background: var(--color-surface); box-shadow: 0 4px 14px rgba(34,43,69,.04); }
.record-card.is-selected { border-color: var(--color-primary); box-shadow: 0 0 0 2px rgba(75,73,172,.11); }
.record-selection { flex-basis: 44px; border-right: 1px solid var(--color-border); }
.record-main { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; padding: 1rem 1rem .75rem; }
.record-toggle {
  width: 100%;
  border: 0;
  color: inherit;
  background: var(--color-surface);
  text-align: left;
  transition: background-color 160ms ease;
}
.record-toggle:hover { background: var(--color-primary-soft); }
.record-toggle:focus-visible { position: relative; z-index: 1; outline: 0; box-shadow: inset 0 0 0 3px rgba(75,73,172,.18); }
.record-toggle:active { background: var(--color-surface-subtle); }
.record-toggle-state { display: flex; align-items: center; gap: .65rem; }
.record-toggle-state > i { color: var(--color-text-muted); font-size: .82rem; }
.record-summary-meta { color: var(--color-primary) !important; font-weight: 650; }
.record-details-body { border-top: 1px solid var(--color-border); padding-top: .85rem; }
.record-time span, .record-time strong, .record-time small { display: block; }
.record-time span { color: var(--color-text-muted); font-size: .68rem; }
.record-time strong { margin-top: .18rem; color: var(--color-text); font-size: .95rem; }
.record-time small { margin-top: .2rem; color: var(--color-text-muted); font-size: .72rem; }
.record-status { padding: .28rem .55rem; border-radius: 999px; font-size: .7rem; font-weight: 700; white-space: nowrap; }
.status-completed { color: var(--color-success); background: var(--color-success-soft); }
.status-progress { color: var(--color-warning); background: var(--color-warning-soft); }
.status-muted { color: var(--color-text-secondary); background: var(--color-surface-subtle); }
.identity-grid { display: grid; grid-template-columns: .65fr 1.35fr 1fr; gap: .65rem; margin: 0; padding: 0 1rem .85rem; }
.identity-grid > div { min-width: 0; padding: .65rem .75rem; border-radius: 9px; background: var(--color-surface-subtle); }
.identity-grid dt { color: var(--color-text-muted); font-size: .64rem; font-weight: 650; }
.identity-grid dd { margin: .2rem 0 0; overflow-wrap: anywhere; color: var(--color-text); font-size: .76rem; font-weight: 650; }
.identity-grid .wechat-field { border-left: 3px solid var(--color-primary); background: var(--color-primary-soft); }
.run-id { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-weight: 500 !important; }
.data-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; border-block: 1px solid var(--color-border); background: var(--color-border); }
.data-metrics > div { display: grid; grid-template-columns: auto 1fr; align-items: center; column-gap: .5rem; padding: .72rem .85rem; background: var(--color-surface); }
.data-metrics i { grid-row: 1 / 3; color: var(--color-primary); }
.data-metrics span { color: var(--color-text-muted); font-size: .65rem; }
.data-metrics strong { color: var(--color-text); font-size: .78rem; }
.data-metrics small { grid-column: 2; color: var(--color-text-muted); font-size: .62rem; }
.task-details { margin: .75rem 1rem 0; border: 1px solid var(--color-border); border-radius: 9px; background: var(--color-surface-subtle); }
.task-details summary { padding: .65rem .75rem; color: var(--color-text-secondary); font-size: .74rem; font-weight: 650; cursor: pointer; }
.task-records { display: grid; gap: .45rem; padding: 0 .65rem .65rem; }
.task-record { display: flex; align-items: center; justify-content: space-between; gap: .75rem; padding: .6rem; border-radius: 8px; background: var(--color-surface); }
.task-record strong, .task-record small { display: block; }
.task-record strong { color: var(--color-text); font-size: .73rem; }
.task-record small, .task-record > span { margin-top: .15rem; color: var(--color-text-muted); font-size: .66rem; }
.record-footer { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: .85rem 1rem; }
.record-footer p { margin: 0; color: var(--color-text-muted); font-size: .67rem; }
.record-footer .btn { min-height: 38px; flex: 0 0 auto; font-size: .75rem; }
.data-pagination { display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: .75rem; padding: .8rem 1rem; color: var(--color-text-muted); font-size: .76rem; }
.data-pagination label { display: flex; align-items: center; gap: .4rem; }
.data-pagination .form-select { width: 72px; }
@media (max-width: 991.98px) {
  .data-category-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .identity-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .identity-grid > div:last-child { grid-column: 1 / -1; }
  .data-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 575.98px) {
  .data-category-grid { grid-template-columns: 1fr; gap: .55rem; }
  .category-copy small { -webkit-line-clamp: 1; }
  .data-toolbar { align-items: stretch; flex-direction: column; }
  .bulk-toolbar, .bulk-actions { align-items: stretch; flex-direction: column; }
  .bulk-actions { width: 100%; }
  .bulk-actions .btn-danger { width: 100%; }
  .search-box { width: 100%; }
  .account-header { padding: .8rem; }
  .record-list { padding: .55rem; }
  .record-main { padding: .85rem .8rem .65rem; }
  .identity-grid { grid-template-columns: 1fr; padding-inline: .8rem; }
  .identity-grid > div:last-child { grid-column: auto; }
  .data-metrics { grid-template-columns: 1fr 1fr; }
  .data-metrics > div { padding: .65rem; }
  .task-details { margin-inline: .8rem; }
  .task-record { align-items: flex-start; flex-direction: column; }
  .record-footer { align-items: stretch; flex-direction: column; padding: .8rem; }
  .record-footer .btn { width: 100%; }
  .data-pagination .btn { flex: 1 1 120px; }
}
</style>
