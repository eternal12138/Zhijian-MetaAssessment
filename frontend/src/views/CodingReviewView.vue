<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import AppPageHeader from '../components/ui/AppPageHeader.vue'
import AudioTranscriptPlayer from '../components/audio/AudioTranscriptPlayer.vue'
import { extractionApi } from '../api/extraction'
import {
  researchApi,
  type CodingBatch,
  type CodingBatchPreview,
  type CodingBatchScopeOptions,
  type CodingReviewer,
  type CodingUnitAssignment,
  type CodingUnitDisagreement,
  type ExpertDatasetStats,
  type ExpertLabel
} from '../api/research'
import { useAuthStore } from '../stores/auth'
import { confirmAction } from '../composables/useUiFeedback'

type CodingDimension = ExpertLabel
type CodingDraft = { dimension: CodingDimension | undefined; note: string }

const authStore = useAuthStore()
const assignments = ref<CodingUnitAssignment[]>([])
const disagreements = ref<CodingUnitDisagreement[]>([])
const batches = ref<CodingBatch[]>([])
const reviewers = ref<CodingReviewer[]>([])
const scopeOptions = ref<CodingBatchScopeOptions | null>(null)
const batchPreview = ref<CodingBatchPreview | null>(null)
const previewLoading = ref(false)
const previewStale = ref(true)
const studentSearch = ref('')
const drafts = reactive<Record<string, CodingDraft>>({})
const isLoading = ref(true)
const savingId = ref('')
const batchSaving = ref(false)
const errorMessage = ref('')
const successMessage = ref('')
const assignmentStatus = ref<'unannotated' | 'annotated'>('unannotated')
const datasetStats = ref<ExpertDatasetStats | null>(null)
const exportTextSource = ref<'clean_text' | 'raw_text'>('clean_text')
const exportLabelMode = ref<'resolved' | 'individual'>('resolved')
const exportBusy = ref(false)
const activeTab = ref<'independent' | 'adjudication' | 'batches'>('independent')
const editingBatchId = ref('')
const audioPlayer = ref<InstanceType<typeof AudioTranscriptPlayer> | null>(null)
const audioUnit = ref<CodingUnitAssignment | CodingUnitDisagreement | null>(null)
const audioUrl = ref('')
const audioPeaks = ref<number[]>([])
const audioDuration = ref(0)
const audioLoading = ref(false)
const audioError = ref('')
const isAdmin = computed(() => authStore.userRole === 'admin')

const batchForm = reactive({
  name: '',
  reviewer_a_id: '',
  reviewer_b_id: '',
  adjudicator_id: ''
})
const batchScope = reactive({
  class_groups: [] as string[],
  user_ids: [] as string[],
  task_ids: [] as string[],
  completed_from: null as string | null,
  completed_to: null as string | null,
  exclude_previously_batched: false
})

const dimensions: Array<{
  value: CodingDimension
  label: string
  description: string
  icon: string
}> = [
  {
    value: 'monitoring',
    label: '监控',
    description: '检查理解、进度、困惑或当前状态',
    icon: 'bi-eye'
  },
  {
    value: 'regulation',
    label: '调控',
    description: '调整方法、纠正错误或切换策略',
    icon: 'bi-sliders'
  },
  {
    value: 'evaluation',
    label: '评估',
    description: '核验结果、反思过程或比较方法',
    icon: 'bi-check2-circle'
  }
]

const currentAssignment = computed(() => assignments.value[0] ?? null)
const visibleScopeStudents = computed(() => {
  const keyword = studentSearch.value.trim().toLowerCase()
  const selectedClass = batchScope.class_groups[0]
  return (scopeOptions.value?.students ?? []).filter(student => {
    if (selectedClass && student.class_group !== selectedClass) return false
    if (!keyword) return true
    return [student.name, student.username, student.class_group ?? '']
      .some(value => value.toLowerCase().includes(keyword))
  })
})
const currentDraft = computed(() => {
  const item = currentAssignment.value
  return item ? drafts[item.unit_id] : undefined
})
const audioSegments = computed(() => audioUnit.value ? [{
  segment_no: audioUnit.value.sequence_no,
  text: audioUnit.value.segment,
  started_at_ms: audioUnit.value.started_at_ms,
  ended_at_ms: audioUnit.value.ended_at_ms
}] : [])
const independentProgress = computed(() => {
  const item = currentAssignment.value
  if (!item) return { completed: 0, total: 0, percent: 0 }
  const completed = item.completed_units
  return {
    completed,
    total: item.total_units,
    percent: item.total_units
      ? Math.round(completed / item.total_units * 100)
      : 0
  }
})

function label(value: string | null) {
  const legacyLabels: Record<string, string> = {
    NON_META: '非元认知（旧编码）',
    non_meta: '非元认知（旧编码）',
    non_metacognitive: '非元认知（旧编码）',
    planning: '计划（旧编码，需迁移）',
    MONITORING: '监控（旧编码）',
    REGULATION: '调节（旧编码）',
    EVALUATION: '评估（旧编码，需重新确认）',
    controlDebugging: '控制/调试（旧编码）',
    legacy_evaluation: '评估（旧编码，需重新确认）'
  }
  if (value && legacyLabels[value]) return legacyLabels[value]
  return dimensions.find(item => item.value === value)?.label ?? '未分类'
}

function formatTime(ms: number) {
  const seconds = Math.max(0, Math.round(ms / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

function resolveAudioUrl(url: string) {
  try { return new URL(url, window.location.origin).toString() } catch { return url }
}

async function prepareAudio(item: CodingUnitAssignment | CodingUnitDisagreement, play = false) {
  audioUnit.value = item
  audioUrl.value = ''
  audioPeaks.value = []
  audioDuration.value = 0
  audioError.value = ''
  audioLoading.value = true
  try {
    const [ticket, waveform] = await Promise.all([
      extractionApi.audioTicket(item.session_id),
      extractionApi.audioWaveform(item.session_id).catch(() => null)
    ])
    if (audioUnit.value?.unit_id !== item.unit_id) return
    audioUrl.value = resolveAudioUrl(ticket.data.url)
    if (waveform) {
      audioPeaks.value = waveform.data.peaks
      audioDuration.value = waveform.data.duration_seconds
    }
    if (play) {
      await new Promise(resolve => window.setTimeout(resolve, 0))
      audioPlayer.value?.playRange(item.started_at_ms, item.ended_at_ms)
    }
  } catch (error) {
    audioError.value = error instanceof Error ? error.message : '原始录音加载失败'
  } finally {
    audioLoading.value = false
  }
}

function ensureDraft(key: string) {
  if (!drafts[key]) drafts[key] = { dimension: undefined, note: '' }
  return drafts[key]
}

function initializeDrafts() {
  for (const item of assignments.value) {
    const existing = item.current_expert_label
    drafts[item.unit_id] = {
      dimension: existing && dimensions.some(dim => dim.value === existing)
        ? existing
        : undefined,
      note: item.current_note
    }
  }
  for (const item of disagreements.value) ensureDraft(`adjudicate-${item.unit_id}`)
}

async function loadPage() {
  isLoading.value = true
  errorMessage.value = ''
  try {
    const [assignmentResponse, disagreementResponse] = await Promise.all([
      researchApi.listCodingUnitAssignments(assignmentStatus.value),
      researchApi.listCodingUnitDisagreements()
    ])
    assignments.value = assignmentResponse.data
    disagreements.value = disagreementResponse.data
    if (isAdmin.value) {
      const [reviewerResponse, batchResponse, scopeResponse] = await Promise.all([
        researchApi.listCodingReviewers(),
        researchApi.listCodingBatches(),
        researchApi.codingBatchScopeOptions()
      ])
      reviewers.value = reviewerResponse.data
      batches.value = batchResponse.data
      scopeOptions.value = scopeResponse.data
      datasetStats.value = (await researchApi.expertDatasetStats()).data
      await refreshPreview()
    }
    initializeDrafts()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载编码工作流失败'
  } finally {
    isLoading.value = false
  }
}

watch(currentAssignment, item => {
  if (item) void prepareAudio(item)
  else { audioUnit.value = null; audioUrl.value = '' }
})

function setClassFilter(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  batchScope.class_groups = value ? [value] : []
  if (value) {
    const allowed = new Set(
      (scopeOptions.value?.students ?? [])
        .filter(student => student.class_group === value)
        .map(student => student.id)
    )
    batchScope.user_ids = batchScope.user_ids.filter(id => allowed.has(id))
  }
}

function setVisibleStudents(selected: boolean) {
  const visibleIds = visibleScopeStudents.value.map(student => student.id)
  if (selected) {
    batchScope.user_ids = [...new Set([
      ...batchScope.user_ids,
      ...visibleIds
    ])]
  } else {
    const visible = new Set(visibleIds)
    batchScope.user_ids = batchScope.user_ids.filter(id => !visible.has(id))
  }
}

async function refreshPreview() {
  if (!isAdmin.value || editingBatchId.value) return
  previewLoading.value = true
  errorMessage.value = ''
  try {
    batchPreview.value = (
      await researchApi.previewCodingBatch({ ...batchScope })
    ).data
    previewStale.value = false
  } catch (error) {
    batchPreview.value = null
    errorMessage.value = error instanceof Error
      ? error.message
      : '无法预览编码范围'
  } finally {
    previewLoading.value = false
  }
}

function selectDimension(key: string, dimension: CodingDimension) {
  ensureDraft(key).dimension = dimension
  successMessage.value = ''
}

async function submitIndependent(item: CodingUnitAssignment) {
  const draft = ensureDraft(item.unit_id)
  if (draft.dimension === undefined) {
    errorMessage.value = '请先选择一个编码结果。'
    return
  }
  savingId.value = item.unit_id
  errorMessage.value = ''
  try {
    await researchApi.saveExpertAnnotation(
      item.unit_id,
      draft.dimension,
      draft.note.trim()
    )
    delete drafts[item.unit_id]
    assignments.value = (await researchApi.listCodingUnitAssignments(assignmentStatus.value)).data
    initializeDrafts()
    successMessage.value = item.annotation_status === 'annotated'
      ? '专家标签修改已保存并写入审计记录。'
      : '独立编码已保存。AI 与另一名编码员的结果仍保持不可见。'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '提交独立编码失败'
  } finally {
    savingId.value = ''
  }
}

async function changeAssignmentStatus(status: 'unannotated' | 'annotated') {
  assignmentStatus.value = status
  isLoading.value = true
  try {
    assignments.value = (await researchApi.listCodingUnitAssignments(status)).data
    initializeDrafts()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '切换标注状态失败'
  } finally {
    isLoading.value = false
  }
}

async function exportTrainingDataset() {
  exportBusy.value = true
  errorMessage.value = ''
  try {
    const response = await researchApi.exportExpertDataset(
      exportTextSource.value, exportLabelMode.value
    )
    const url = URL.createObjectURL(response.data)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `专家训练数据_${exportTextSource.value}_${exportLabelMode.value}.csv`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
    successMessage.value = '专家训练数据已导出。'
    datasetStats.value = (await researchApi.expertDatasetStats()).data
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '训练数据导出失败'
  } finally {
    exportBusy.value = false
  }
}

async function adjudicate(item: CodingUnitDisagreement) {
  const key = `adjudicate-${item.unit_id}`
  const draft = ensureDraft(key)
  if (draft.dimension === undefined) {
    errorMessage.value = '请选择最终裁决维度。'
    return
  }
  if (!draft.note.trim()) {
    errorMessage.value = '第三方仲裁必须填写裁决依据。'
    return
  }
  savingId.value = item.unit_id
  errorMessage.value = ''
  try {
    await researchApi.adjudicateCodingUnit(
      item.unit_id,
      draft.dimension,
      draft.note.trim()
    )
    disagreements.value = disagreements.value.filter(
      current => current.unit_id !== item.unit_id
    )
    delete drafts[key]
    successMessage.value = '分歧已由第三方完成仲裁。'
    if (isAdmin.value) {
      batches.value = (await researchApi.listCodingBatches()).data
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保存仲裁失败'
  } finally {
    savingId.value = ''
  }
}

function resetBatchForm() {
  editingBatchId.value = ''
  batchForm.name = ''
  batchForm.reviewer_a_id = ''
  batchForm.reviewer_b_id = ''
  batchForm.adjudicator_id = ''
}

function resetBatchScope() {
  batchScope.class_groups = []
  batchScope.user_ids = []
  batchScope.task_ids = []
  batchScope.completed_from = null
  batchScope.completed_to = null
  batchScope.exclude_previously_batched = false
  studentSearch.value = ''
}

function editBatch(batch: CodingBatch) {
  editingBatchId.value = batch.id
  batchForm.name = batch.name
  batchForm.reviewer_a_id = batch.reviewer_a_id
  batchForm.reviewer_b_id = batch.reviewer_b_id
  batchForm.adjudicator_id = batch.adjudicator_id
  activeTab.value = 'batches'
}

async function saveBatch() {
  const ids = [
    batchForm.reviewer_a_id,
    batchForm.reviewer_b_id,
    batchForm.adjudicator_id
  ]
  if (!batchForm.name.trim()) {
    errorMessage.value = '请填写编码批次名称。'
    return
  }
  if (ids.some(id => !id) || new Set(ids).size !== 3) {
    errorMessage.value = '编码员 A、编码员 B 和仲裁员必须选择三个不同账号。'
    return
  }
  if (
    !editingBatchId.value
    && (
      previewStale.value
      || !batchPreview.value
      || batchPreview.value.segment_count === 0
    )
  ) {
    errorMessage.value = previewStale.value
      ? '筛选条件已改变，请先重新预览编码范围。'
      : '当前筛选范围没有可用于盲编的 AI 候选片段。'
    return
  }
  if (!editingBatchId.value) {
    const unreviewedCount = batchPreview.value?.unreviewed_candidate_count ?? 0
    const confirmed = await confirmAction({
      title: unreviewedCount ? '包含未人工复核片段' : '创建盲编批次',
      message: unreviewedCount
        ? `所选范围包含 ${unreviewedCount} 条未经过人工复核、仅有 AI 初步筛选的候选片段。继续后，这些片段将与已复核片段一起固定分配给编码员，请专家在盲编阶段独立判断。是否仍要继续？`
        : `将为 ${batchPreview.value?.student_count ?? 0} 名学生、${batchPreview.value?.run_count ?? 0} 次测评的 ${batchPreview.value?.segment_count ?? 0} 个候选片段建立编码单元。创建后筛选范围和人员分配将固定。`,
      confirmText: unreviewedCount ? '仍然创建并分配' : '确认创建',
      tone: unreviewedCount ? 'warning' : 'primary'
    })
    if (!confirmed) return
  }
  batchSaving.value = true
  errorMessage.value = ''
  const wasEditing = Boolean(editingBatchId.value)
  try {
    if (editingBatchId.value) {
      await researchApi.updateCodingBatchAssignments(editingBatchId.value, {
        reviewer_a_id: batchForm.reviewer_a_id,
        reviewer_b_id: batchForm.reviewer_b_id,
        adjudicator_id: batchForm.adjudicator_id
      })
      successMessage.value = '编码批次人员分配已更新。'
    } else {
      await researchApi.createCodingBatch({
        name: batchForm.name.trim(),
        reviewer_a_id: batchForm.reviewer_a_id,
        reviewer_b_id: batchForm.reviewer_b_id,
        adjudicator_id: batchForm.adjudicator_id,
        allow_unreviewed_candidates: Boolean(batchPreview.value?.unreviewed_candidate_count),
        ...batchScope
      })
      const unreviewedCount = batchPreview.value?.unreviewed_candidate_count ?? 0
      successMessage.value = unreviewedCount
        ? `盲编批次已创建并固定分配，其中 ${unreviewedCount} 条为仅经 AI 初筛、尚未人工复核的候选。`
        : '盲编批次已创建，候选片段已经固定分配。'
    }
    batches.value = (await researchApi.listCodingBatches()).data
    resetBatchForm()
    if (!wasEditing) {
      resetBatchScope()
      await refreshPreview()
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保存编码批次失败'
  } finally {
    batchSaving.value = false
  }
}

watch(
  batchScope,
  () => {
    previewStale.value = true
  },
  { deep: true }
)

onMounted(loadPage)
</script>

<template>
  <div class="review-page">
    <AppPageHeader eyebrow="独立盲编与双人复核" title="元认知双人独立编码" icon="bi-person-check" description="固定编码员 A/B 独立盲编；只有两人完成后，分歧才会交给指定第三方仲裁。">
      <template #actions>
        <span class="blind-badge"><i class="bi bi-eye-slash me-1" />独立编码阶段不显示 AI 和对方结果</span>
      </template>
    </AppPageHeader>

    <div v-if="errorMessage" class="alert alert-danger">{{ errorMessage }}</div>
    <div v-if="successMessage" class="alert alert-success">{{ successMessage }}</div>

    <ul class="nav nav-pills review-tabs mb-4">
      <li class="nav-item">
        <button
          class="nav-link"
          :class="{ active: activeTab === 'independent' }"
          @click="activeTab = 'independent'"
        >
          我的独立编码
          <span class="badge text-bg-light ms-1">{{ assignments.length }}</span>
        </button>
      </li>
      <li class="nav-item">
        <button
          class="nav-link"
          :class="{ active: activeTab === 'adjudication' }"
          @click="activeTab = 'adjudication'"
        >
          我的仲裁任务
          <span class="badge text-bg-light ms-1">{{ disagreements.length }}</span>
        </button>
      </li>
      <li v-if="isAdmin" class="nav-item">
        <button
          class="nav-link"
          :class="{ active: activeTab === 'batches' }"
          @click="activeTab = 'batches'"
        >
          批次与人员分配
          <span class="badge text-bg-light ms-1">{{ batches.length }}</span>
        </button>
      </li>
    </ul>

    <div v-if="isLoading" class="card border-0 shadow-sm">
      <div class="card-body py-5 text-center">
        <div class="spinner-border text-primary" />
      </div>
    </div>

    <template v-else-if="activeTab === 'independent'">
      <div class="annotation-status-bar app-surface-card mb-3">
        <div>
          <strong>我的专家标注</strong>
          <small>可在未标注与已标注片段之间切换；已标注记录允许修订并保留审计轨迹。</small>
        </div>
        <div class="btn-group" role="group" aria-label="专家标注状态">
          <button class="btn btn-sm" :class="assignmentStatus === 'unannotated' ? 'btn-primary' : 'btn-outline-secondary'" @click="changeAssignmentStatus('unannotated')">未标注</button>
          <button class="btn btn-sm" :class="assignmentStatus === 'annotated' ? 'btn-primary' : 'btn-outline-secondary'" @click="changeAssignmentStatus('annotated')">已标注</button>
        </div>
      </div>
      <div v-if="!currentAssignment" class="card border-0 shadow-sm">
        <div class="card-body py-5 text-center">
          <i class="bi bi-check2-circle display-5 text-success" />
          <h5 class="mt-3">{{ assignmentStatus === 'annotated' ? '当前没有已标注片段' : '当前没有待编码片段' }}</h5>
          <p class="text-muted mb-0">只有管理员固定分配给你的盲编批次会出现在这里。</p>
        </div>
      </div>

      <div v-else class="coding-workspace">
        <section class="card border-0 shadow-sm">
          <div class="card-header bg-white border-0 p-4 pb-2">
            <div class="d-flex flex-wrap justify-content-between gap-3">
              <div>
                <span class="badge bg-primary-subtle text-primary mb-2">
                  {{ currentAssignment.batch_name }}
                </span>
                <span v-if="currentAssignment.annotation_status === 'annotated'" class="badge bg-success-subtle text-success-emphasis ms-2">已标注，可修改</span>
                <h5 class="mb-1">任务 {{ currentAssignment.sequence_no }} · 编码片段</h5>
                <small class="text-muted">
                  匿名会话 {{ currentAssignment.session_id.slice(0, 8) }} ·
                  {{ formatTime(currentAssignment.started_at_ms) }}–{{ formatTime(currentAssignment.ended_at_ms) }}
                </small>
              </div>
              <div class="progress-summary">
                <strong>{{ independentProgress.completed }}/{{ independentProgress.total }}</strong>
                <span>本批次已完成</span>
              </div>
            </div>
            <div class="progress mt-3" role="progressbar" :aria-valuenow="independentProgress.percent">
              <div class="progress-bar" :style="{ width: `${independentProgress.percent}%` }" />
            </div>
          </div>

          <div class="card-body p-4">
            <div v-if="currentAssignment.context_before" class="context-block">
              <span>前文</span>
              <p>{{ currentAssignment.context_before }}</p>
            </div>
            <div class="text-comparison my-3">
              <div class="text-version raw-version">
                <span>ASR 原文</span>
                <p>{{ currentAssignment.raw_text }}</p>
              </div>
              <div class="text-version clean-version">
                <span>AI 清洗文本</span>
                <p>{{ currentAssignment.clean_text }}</p>
              </div>
            </div>
            <div v-if="currentAssignment.context_after" class="context-block">
              <span>后文</span>
              <p>{{ currentAssignment.context_after }}</p>
            </div>
            <div class="coding-audio mt-4">
              <div v-if="audioLoading" class="d-flex align-items-center gap-2 text-muted small py-3">
                <span class="spinner-border spinner-border-sm" />正在准备原始录音波形…
              </div>
              <AudioTranscriptPlayer
                v-else-if="audioUrl && audioUnit?.unit_id === currentAssignment.unit_id"
                ref="audioPlayer"
                :src="audioUrl"
                :segments="audioSegments"
                :peaks="audioPeaks"
                :duration-seconds="audioDuration"
                title="原始录音盲听复核"
                compact
              />
              <div v-else-if="audioError" class="alert alert-warning mb-0">
                {{ audioError }}
                <button class="btn btn-sm btn-outline-primary ms-2" type="button" @click="prepareAudio(currentAssignment)">重试</button>
              </div>
            </div>
          </div>
        </section>

        <aside class="card border-0 shadow-sm coding-panel">
          <div class="card-body p-4">
            <h5 class="mb-1">选择编码结果</h5>
            <p class="text-muted small">只依据被试原话及上下文判断，不推测未表达的心理过程。</p>

            <div class="dimension-list">
              <button
                v-for="dimension in dimensions"
                :key="dimension.label"
                class="dimension-option"
                :class="{ active: currentDraft?.dimension === dimension.value }"
                @click="selectDimension(currentAssignment.unit_id, dimension.value)"
              >
                <i class="bi" :class="dimension.icon" />
                <span>
                  <strong>{{ dimension.label }}</strong>
                  <small>{{ dimension.description }}</small>
                </span>
              </button>
            </div>

            <label class="form-label mt-4" for="independent-note">编码依据（可选）</label>
            <textarea
              id="independent-note"
              v-model.trim="ensureDraft(currentAssignment.unit_id).note"
              class="form-control"
              rows="4"
              maxlength="2000"
              placeholder="记录可观察的关键词、行为或判断依据"
            />
            <button
              class="btn btn-primary w-100 mt-3"
              :disabled="savingId === currentAssignment.unit_id || currentDraft?.dimension === undefined"
              @click="submitIndependent(currentAssignment)"
            >
              <span v-if="savingId === currentAssignment.unit_id" class="spinner-border spinner-border-sm me-1" />
              <i v-else class="bi bi-arrow-right-circle me-1" />
              {{ currentAssignment.annotation_status === 'annotated' ? '保存标签修改' : '保存并进入下一条' }}
            </button>
          </div>
        </aside>
      </div>
    </template>

    <template v-else-if="activeTab === 'adjudication'">
      <div v-if="!disagreements.length" class="card border-0 shadow-sm">
        <div class="card-body py-5 text-center text-muted">
          <i class="bi bi-shield-check display-5 text-success" />
          <h5 class="mt-3">当前没有分配给你的仲裁任务</h5>
        </div>
      </div>
      <div v-else class="d-grid gap-3">
        <article v-for="item in disagreements" :key="item.unit_id" class="card border-0 shadow-sm">
          <div class="card-body p-4">
            <div class="d-flex flex-wrap justify-content-between gap-2 mb-3">
              <span class="badge bg-danger-subtle text-danger-emphasis">{{ item.batch_name }} · 待仲裁</span>
              <div class="d-flex align-items-center gap-2">
                <small class="text-muted">任务 {{ item.sequence_no }} · {{ formatTime(item.started_at_ms) }}–{{ formatTime(item.ended_at_ms) }}</small>
                <button class="btn btn-sm btn-outline-primary" type="button" :disabled="audioLoading" @click="prepareAudio(item, true)">
                  <i class="bi bi-headphones me-1" />试听原录音
                </button>
              </div>
            </div>
            <div v-if="item.context_before" class="context-block">
              <span>前文</span><p>{{ item.context_before }}</p>
            </div>
            <div class="text-comparison my-3">
              <div class="text-version raw-version"><span>ASR 原文</span><p>{{ item.raw_text }}</p></div>
              <div class="text-version clean-version"><span>AI 清洗文本</span><p>{{ item.clean_text }}</p></div>
            </div>
            <div v-if="item.context_after" class="context-block">
              <span>后文</span><p>{{ item.context_after }}</p>
            </div>
            <AudioTranscriptPlayer
              v-if="audioUrl && audioUnit?.unit_id === item.unit_id"
              ref="audioPlayer"
              class="mt-3"
              :src="audioUrl"
              :segments="audioSegments"
              :peaks="audioPeaks"
              :duration-seconds="audioDuration"
              title="仲裁原始录音范围"
              compact
            />

            <div class="row g-3 my-2">
              <div v-for="annotation in item.annotations" :key="annotation.reviewer_slot" class="col-md-6">
                <div class="annotation">
                  <strong>编码员 {{ annotation.reviewer_slot }}</strong>
                  <div class="annotation-result">{{ label(annotation.expert_label) }}</div>
                  <small>{{ annotation.note || '未填写编码依据' }}</small>
                </div>
              </div>
            </div>

            <div class="adjudication-form">
              <h6>第三方最终裁决</h6>
              <div class="compact-dimensions">
                <button
                  v-for="dimension in dimensions"
                  :key="dimension.label"
                  class="btn btn-sm"
                  :class="ensureDraft(`adjudicate-${item.unit_id}`).dimension === dimension.value ? 'btn-primary' : 'btn-outline-secondary'"
                  @click="selectDimension(`adjudicate-${item.unit_id}`, dimension.value)"
                >
                  {{ dimension.label }}
                </button>
              </div>
              <textarea
                v-model.trim="ensureDraft(`adjudicate-${item.unit_id}`).note"
                class="form-control mt-3"
                rows="3"
                maxlength="2000"
                placeholder="必填：说明采用该裁决的可观察依据"
              />
              <button
                class="btn btn-danger mt-3"
                :disabled="savingId === item.unit_id"
                @click="adjudicate(item)"
              >
                <span v-if="savingId === item.unit_id" class="spinner-border spinner-border-sm me-1" />
                保存最终裁决
              </button>
            </div>
          </div>
        </article>
      </div>
    </template>

    <template v-else>
      <section class="card border-0 shadow-sm dataset-export-card mb-4">
        <div class="card-body p-4">
          <div class="d-flex flex-wrap justify-content-between gap-3">
            <div>
              <span class="badge bg-success-subtle text-success-emphasis mb-2">机器学习数据闭环</span>
              <h5 class="mb-1">导出专家训练数据</h5>
              <p class="text-muted small mb-0">默认只导出双人共识或仲裁完成的片段，文本默认采用 AI 清洗文本；ASR 原文始终保留。</p>
            </div>
            <div v-if="datasetStats" class="dataset-metrics">
              <div><strong>{{ datasetStats.resolved_segment_count }}</strong><span>可训练片段</span></div>
              <div><strong>{{ datasetStats.individual_annotation_count }}</strong><span>专家原始编码</span></div>
            </div>
          </div>
          <div class="export-controls mt-3">
            <label><span>文本来源</span><select v-model="exportTextSource" class="form-select"><option value="clean_text">AI 清洗文本（默认）</option><option value="raw_text">ASR 原文</option></select></label>
            <label><span>标签模式</span><select v-model="exportLabelMode" class="form-select"><option value="resolved">双人共识/仲裁标签（默认）</option><option value="individual">每位专家独立标签</option></select></label>
            <button class="btn btn-success" :disabled="exportBusy" @click="exportTrainingDataset"><span v-if="exportBusy" class="spinner-border spinner-border-sm me-1" /><i v-else class="bi bi-filetype-csv me-1" />导出 CSV</button>
          </div>
        </div>
      </section>
      <div class="batch-layout">
        <section class="card border-0 shadow-sm batch-form-card">
          <div class="card-body p-4">
            <div class="d-flex justify-content-between align-items-start gap-2">
              <div>
                <h5>{{ editingBatchId ? '调整批次人员' : '创建盲编批次' }}</h5>
                <p class="text-muted small">
                  创建时将筛选范围固化并纳入 AI 抽取候选；如包含尚未人工复核的候选，系统会警告并要求再次确认。
                </p>
              </div>
              <button v-if="editingBatchId" class="btn-close" title="取消编辑" @click="resetBatchForm" />
            </div>

            <label class="form-label">批次名称</label>
            <input
              v-model.trim="batchForm.name"
              class="form-control mb-3"
              maxlength="128"
              :disabled="Boolean(editingBatchId)"
              placeholder="例如：第一轮模型校准编码"
            >

            <div v-if="!editingBatchId" class="scope-panel mb-4">
              <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-3">
                <div>
                  <h6 class="mb-1">选择研究数据范围</h6>
                  <small class="text-muted">未选择任何条件时默认显示全部权威转录；修改后需要重新预览。</small>
                </div>
                <span v-if="previewStale" class="badge bg-warning-subtle text-warning-emphasis">
                  预览待更新
                </span>
              </div>

              <div class="scope-data-summary mt-3">
                <i class="bi bi-database-check" />
                <span>
                  当前共检索到
                  <strong>{{ scopeOptions?.transcript_segment_count || 0 }}</strong>
                  条权威转录，其中
                  <strong>{{ scopeOptions?.coding_ready_segment_count || 0 }}</strong>
                  条 AI 候选已完成人工复核。
                </span>
              </div>

              <div class="row g-3">
                <div class="col-md-4">
                  <label class="form-label">班级</label>
                  <select
                    class="form-select"
                    :value="batchScope.class_groups[0] || ''"
                    @change="setClassFilter"
                  >
                    <option value="">全部班级</option>
                    <option
                      v-for="classGroup in scopeOptions?.class_groups || []"
                      :key="classGroup"
                      :value="classGroup"
                    >
                      {{ classGroup }}
                    </option>
                  </select>
                </div>
                <div class="col-md-4">
                  <label class="form-label">完成日期从</label>
                  <input
                    v-model="batchScope.completed_from"
                    type="date"
                    class="form-control"
                  >
                </div>
                <div class="col-md-4">
                  <label class="form-label">完成日期至</label>
                  <input
                    v-model="batchScope.completed_to"
                    type="date"
                    class="form-control"
                  >
                </div>
              </div>

              <div class="row g-3 mt-0">
                <div class="col-lg-7">
                  <div class="d-flex flex-wrap justify-content-between align-items-center gap-2">
                    <label class="form-label mb-0">学生</label>
                    <small class="text-muted">
                      已指定 {{ batchScope.user_ids.length }} 人；不指定表示当前班级全部学生
                    </small>
                  </div>
                  <div class="input-group input-group-sm my-2">
                    <span class="input-group-text"><i class="bi bi-search" /></span>
                    <input
                      v-model.trim="studentSearch"
                      class="form-control"
                      placeholder="按姓名、账号或班级查找"
                    >
                    <button class="btn btn-outline-secondary" type="button" @click="setVisibleStudents(true)">
                      选择当前结果
                    </button>
                    <button class="btn btn-outline-secondary" type="button" @click="setVisibleStudents(false)">
                      清除当前结果
                    </button>
                  </div>
                  <div class="student-picker">
                    <label
                      v-for="student in visibleScopeStudents"
                      :key="student.id"
                      class="student-choice"
                    >
                      <input
                        v-model="batchScope.user_ids"
                        class="form-check-input"
                        type="checkbox"
                        :value="student.id"
                      >
                      <span>
                        <strong>{{ student.name }}</strong>
                        <small>{{ student.username }} · {{ student.class_group || '未分配班级' }}</small>
                      </span>
                    </label>
                    <div v-if="!visibleScopeStudents.length" class="text-center text-muted small py-4">
                      没有符合条件的学生
                    </div>
                  </div>
                </div>

                <div class="col-lg-5">
                  <label class="form-label">任务</label>
                  <div class="task-picker">
                    <label
                      v-for="task in scopeOptions?.tasks || []"
                      :key="task.id"
                      class="task-choice"
                    >
                      <input
                        v-model="batchScope.task_ids"
                        class="form-check-input"
                        type="checkbox"
                        :value="task.id"
                      >
                      <span>
                        <strong>{{ task.title }}</strong>
                        <small>标准协议中的第 {{ task.protocol_order }} 项</small>
                      </span>
                    </label>
                    <small v-if="!(scopeOptions?.tasks.length)" class="text-muted">
                      暂无包含权威转录的已完成任务
                    </small>
                  </div>

                  <label class="duplicate-protection mt-3">
                    <input
                      v-model="batchScope.exclude_previously_batched"
                      class="form-check-input"
                      type="checkbox"
                    >
                    <span>
                      <strong>仅显示未进入其他编码批次的片段</strong>
                      <small>默认关闭以显示全部数据；正式新建不重复批次时再开启。</small>
                    </span>
                  </label>
                </div>
              </div>

              <div class="preview-bar mt-3">
                <button
                  class="btn btn-outline-primary"
                  :disabled="previewLoading"
                  @click="refreshPreview"
                >
                  <span v-if="previewLoading" class="spinner-border spinner-border-sm me-1" />
                  <i v-else class="bi bi-calculator me-1" />
                  预览数据范围
                </button>
                <div v-if="batchPreview && !previewStale" class="preview-metrics">
                  <div><strong>{{ batchPreview.student_count }}</strong><span>学生</span></div>
                  <div><strong>{{ batchPreview.run_count }}</strong><span>测评</span></div>
                  <div><strong>{{ batchPreview.session_count }}</strong><span>会话</span></div>
                  <div><strong>{{ batchPreview.transcript_segment_count }}</strong><span>权威转录</span></div>
                  <div><strong>{{ batchPreview.segment_count }}</strong><span>候选总数</span></div>
                  <div><strong>{{ batchPreview.coding_ready_segment_count }}</strong><span>已人工复核</span></div>
                  <div><strong>{{ batchPreview.unreviewed_candidate_count }}</strong><span>仅 AI 初筛</span></div>
                </div>
              </div>
              <div
                v-if="batchPreview && !previewStale && batchPreview.previously_batched_segment_count"
                class="small text-warning-emphasis mt-2"
              >
                <i class="bi bi-shield-check me-1" />
                <template v-if="batchScope.exclude_previously_batched">
                  已排除 {{ batchPreview.previously_batched_segment_count }} 个曾进入其他批次的片段。
                </template>
                <template v-else>
                  当前范围包含 {{ batchPreview.previously_batched_segment_count }} 个曾进入其他批次的片段，创建后会形成重复编码。
                </template>
              </div>
              <div
                v-if="batchPreview && !previewStale && batchPreview.unreviewed_candidate_count"
                class="alert alert-warning py-2 px-3 mt-3 mb-0"
              >
                <i class="bi bi-exclamation-triangle-fill me-1" />
                所选范围有 {{ batchPreview.unreviewed_candidate_count }} 条候选尚未完成人工复核，仅有 AI 初步筛选。
                点击“创建并固定分配”后，系统将再次要求确认。
              </div>
              <div
                v-if="batchPreview && !previewStale && !batchPreview.segment_count"
                class="alert alert-warning py-2 px-3 mt-3 mb-0"
              >
                <template v-if="batchPreview.transcript_segment_count">
                  已找到 {{ batchPreview.transcript_segment_count }} 条权威转录，但尚未生成可用于盲编的 AI 候选片段。
                </template>
                <template v-else>
                  当前范围没有权威转录，请先确认 ASR 已完成且转录版本已发布为权威版本。
                </template>
              </div>
            </div>

            <div class="row g-3">
              <div class="col-md-4">
                <label class="form-label">编码员 A</label>
                <select v-model="batchForm.reviewer_a_id" class="form-select">
                  <option value="">请选择</option>
                  <option v-for="reviewer in reviewers" :key="reviewer.id" :value="reviewer.id">
                    {{ reviewer.name }}（{{ reviewer.username }}）
                  </option>
                </select>
              </div>
              <div class="col-md-4">
                <label class="form-label">编码员 B</label>
                <select v-model="batchForm.reviewer_b_id" class="form-select">
                  <option value="">请选择</option>
                  <option v-for="reviewer in reviewers" :key="reviewer.id" :value="reviewer.id">
                    {{ reviewer.name }}（{{ reviewer.username }}）
                  </option>
                </select>
              </div>
              <div class="col-md-4">
                <label class="form-label">第三方仲裁员</label>
                <select v-model="batchForm.adjudicator_id" class="form-select">
                  <option value="">请选择</option>
                  <option v-for="reviewer in reviewers" :key="reviewer.id" :value="reviewer.id">
                    {{ reviewer.name }}（{{ reviewer.username }}）
                  </option>
                </select>
              </div>
            </div>
            <button
              class="btn btn-primary mt-4"
              :disabled="
                batchSaving
                || (!editingBatchId && (
                  previewLoading
                  || previewStale
                  || !batchPreview?.segment_count
                ))
              "
              @click="saveBatch"
            >
              <span v-if="batchSaving" class="spinner-border spinner-border-sm me-1" />
              {{ editingBatchId ? '保存人员分配' : '创建并固定分配' }}
            </button>
          </div>
        </section>

        <section class="d-grid gap-3">
          <div v-if="!batches.length" class="card border-0 shadow-sm">
            <div class="card-body py-5 text-center text-muted">尚未创建编码批次。</div>
          </div>
          <article v-for="batch in batches" :key="batch.id" class="card border-0 shadow-sm">
            <div class="card-body p-4">
              <div class="d-flex flex-wrap justify-content-between gap-3">
                <div>
                  <div class="d-flex align-items-center gap-2">
                    <h5 class="mb-0">{{ batch.name }}</h5>
                    <span class="badge" :class="batch.status === 'completed' ? 'bg-success-subtle text-success-emphasis' : 'bg-primary-subtle text-primary'">
                      {{ batch.status === 'completed' ? '已完成' : '进行中' }}
                    </span>
                  </div>
                  <small class="text-muted">规则版本 {{ batch.rubric_version }}</small>
                  <div v-if="batch.scope_summary" class="batch-scope-summary mt-2">
                    <span>{{ batch.scope_summary.student_count }} 名学生</span>
                    <span>{{ batch.scope_summary.run_count }} 次测评</span>
                    <span>{{ batch.scope_summary.session_count }} 个会话</span>
                    <span>{{ batch.scope_summary.segment_count }} 个片段</span>
                    <span v-if="batch.scope_summary.ai_only_unreviewed_count" class="text-warning-emphasis">
                      {{ batch.scope_summary.ai_only_unreviewed_count }} 条仅 AI 初筛
                    </span>
                  </div>
                </div>
                <button
                  v-if="batch.reviewer_a_completed + batch.reviewer_b_completed === 0 && batch.status === 'active'"
                  class="btn btn-sm btn-outline-secondary"
                  @click="editBatch(batch)"
                >
                  调整人员
                </button>
              </div>

              <div class="assignment-grid my-3">
                <div><span>编码员 A</span><strong>{{ batch.reviewer_a_name }}</strong></div>
                <div><span>编码员 B</span><strong>{{ batch.reviewer_b_name }}</strong></div>
                <div><span>仲裁员</span><strong>{{ batch.adjudicator_name }}</strong></div>
              </div>

              <div class="batch-progress">
                <div>
                  <span>最终解决 {{ batch.resolved_count }}/{{ batch.unit_count }}</span>
                  <span v-if="batch.disputed_count" class="text-danger">待仲裁 {{ batch.disputed_count }}</span>
                </div>
                <div class="progress">
                  <div
                    class="progress-bar"
                    :style="{ width: `${batch.unit_count ? Math.round(batch.resolved_count / batch.unit_count * 100) : 0}%` }"
                  />
                </div>
                <small>
                  A 已编码 {{ batch.reviewer_a_completed }} · B 已编码 {{ batch.reviewer_b_completed }}
                </small>
              </div>
            </div>
          </article>
        </section>
      </div>
    </template>
  </div>
</template>

<style scoped>
.review-page { max-width: 1280px; margin: 0 auto; }
.card { border-radius: var(--radius-lg); }
.blind-badge {
  padding: .65rem .85rem;
  border-radius: 10px;
  color: var(--color-primary);
  background: var(--color-primary-soft);
  font-size: .78rem;
}
.review-tabs { gap: .35rem; }
.review-tabs .nav-link { border-radius: 9px; }
.annotation-status-bar { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: .85rem 1rem; }
.annotation-status-bar strong, .annotation-status-bar small { display: block; }
.annotation-status-bar small { margin-top: .15rem; color: var(--color-text-muted); }
.text-comparison { display: grid; grid-template-columns: 1fr 1fr; gap: .75rem; }
.text-version { padding: .9rem 1rem; border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface-subtle); }
.text-version > span { display: block; margin-bottom: .4rem; color: var(--color-text-muted); font-size: .7rem; font-weight: 750; letter-spacing: .04em; }
.text-version p { margin: 0; color: var(--color-text); line-height: 1.75; white-space: pre-wrap; }
.clean-version { border-color: color-mix(in srgb, var(--color-primary) 30%, var(--color-border)); background: color-mix(in srgb, var(--color-primary-soft) 42%, var(--color-surface)); }
.dataset-metrics { display: flex; gap: .65rem; }
.dataset-metrics div { min-width: 108px; padding: .65rem .8rem; border-radius: var(--radius-md); text-align: center; background: var(--color-surface-subtle); }
.dataset-metrics strong, .dataset-metrics span { display: block; }
.dataset-metrics strong { color: var(--color-primary); font-size: 1.1rem; }
.dataset-metrics span { color: var(--color-text-muted); font-size: .68rem; }
.export-controls { display: grid; grid-template-columns: minmax(180px, 1fr) minmax(220px, 1.2fr) auto; gap: .75rem; align-items: end; }
.export-controls label > span { display: block; margin-bottom: .3rem; color: var(--color-text-muted); font-size: .72rem; font-weight: 700; }
.coding-workspace {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(310px, 390px);
  gap: 1.25rem;
  align-items: start;
}
.coding-panel { position: sticky; top: 1rem; }
.progress { height: 7px; border-radius: 999px; }
.progress-summary { display: grid; text-align: right; }
.progress-summary strong { color: var(--color-primary); font-size: 1.1rem; }
.progress-summary span { color: var(--color-text-muted); font-size: .72rem; }
.segment {
  padding: 1.15rem;
  border-left: 4px solid var(--color-primary);
  border-radius: 0 10px 10px 0;
  background: var(--color-surface-subtle);
  font-size: 1.05rem;
  line-height: 1.8;
}
.context-block {
  padding: .75rem .9rem;
  border-radius: 9px;
  color: var(--color-text-secondary);
  background: var(--color-surface-subtle);
}
.context-block span { display: block; margin-bottom: .25rem; color: var(--color-text-muted); font-size: .68rem; }
.context-block p { margin: 0; line-height: 1.65; }
.dimension-list { display: grid; gap: .65rem; }
.dimension-option {
  display: flex;
  gap: .75rem;
  align-items: flex-start;
  padding: .8rem;
  border: 1px solid var(--color-border);
  border-radius: 10px;
  color: var(--color-text);
  background: var(--color-surface);
  text-align: left;
  transition: color var(--motion-popover) ease, background-color var(--motion-popover) ease, border-color var(--motion-popover) ease, box-shadow var(--motion-popover) ease;
}
.dimension-option:hover { border-color: var(--color-primary-hover); background: var(--color-primary-soft); }
.dimension-option.active { border-color: var(--color-primary); background: var(--color-primary-soft); box-shadow: 0 0 0 2px rgba(75, 73, 172, .08); }
.dimension-option i { color: var(--color-primary); font-size: 1.05rem; }
.dimension-option small { display: block; margin-top: .15rem; color: var(--color-text-muted); font-size: .72rem; }
.annotation { height: 100%; padding: 1rem; border: 1px solid var(--color-border); border-radius: 10px; background: var(--color-surface); }
.annotation-result { margin: .45rem 0; color: var(--color-primary); font-weight: 600; }
.annotation small { display: block; color: var(--color-text-muted); }
.adjudication-form { padding: 1rem; border-radius: 10px; background: var(--color-danger-soft, #fff8f8); }
.compact-dimensions { display: flex; flex-wrap: wrap; gap: .5rem; }
.batch-layout { display: grid; gap: 1.25rem; }
.batch-form-card { border-top: 4px solid var(--color-primary) !important; }
.scope-panel {
  padding: 1rem;
  border: 1px solid var(--color-border);
  border-radius: 12px;
  background: var(--color-surface-subtle);
}
.scope-data-summary {
  display: flex;
  align-items: center;
  gap: .65rem;
  padding: .7rem .8rem;
  border: 1px solid color-mix(in srgb, var(--color-primary) 25%, var(--color-border));
  border-radius: 10px;
  color: var(--color-text-secondary);
  background: var(--color-primary-soft);
  font-size: .78rem;
}
.scope-data-summary i { flex: 0 0 auto; color: var(--color-primary); font-size: 1rem; }
.scope-data-summary strong { color: var(--color-text); }
.student-picker {
  max-height: 230px;
  overflow-y: auto;
  padding: .4rem;
  border: 1px solid var(--color-border);
  border-radius: 10px;
  background: var(--color-surface);
}
.student-choice,
.task-choice,
.duplicate-protection {
  display: flex;
  align-items: flex-start;
  gap: .65rem;
  padding: .65rem;
  border-radius: 8px;
  cursor: pointer;
}
.student-choice:hover,
.task-choice:hover { background: var(--color-primary-soft); }
.student-choice input,
.task-choice input,
.duplicate-protection input { flex: 0 0 auto; margin-top: .22rem; }
.student-choice span,
.task-choice span,
.duplicate-protection span { min-width: 0; }
.student-choice strong,
.task-choice strong,
.duplicate-protection strong { display: block; color: var(--color-text); font-size: .82rem; }
.student-choice small,
.task-choice small,
.duplicate-protection small { display: block; color: var(--color-text-muted); font-size: .7rem; overflow-wrap: anywhere; }
.task-picker { display: grid; gap: .3rem; }
.duplicate-protection {
  border: 1px solid var(--color-border);
  background: var(--color-success-soft, #f4fbf7);
}
.preview-bar {
  display: flex;
  align-items: center;
  gap: 1rem;
}
.preview-metrics {
  display: grid;
  flex: 1;
  grid-template-columns: repeat(5, minmax(70px, 1fr));
  gap: .5rem;
}
.preview-metrics div {
  padding: .55rem;
  border-radius: 8px;
  background: var(--color-surface);
  text-align: center;
}
.preview-metrics strong { display: block; color: var(--color-primary); font-size: 1.05rem; }
.preview-metrics span { color: var(--color-text-muted); font-size: .68rem; }
.assignment-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: .75rem; }
.assignment-grid div { padding: .75rem; border-radius: 9px; background: var(--color-surface-subtle); }
.assignment-grid span { display: block; color: var(--color-text-muted); font-size: .7rem; }
.assignment-grid strong { display: block; margin-top: .2rem; color: var(--color-text); }
.batch-progress > div:first-child { display: flex; justify-content: space-between; margin-bottom: .45rem; font-size: .78rem; }
.batch-progress small { display: block; margin-top: .45rem; color: var(--color-text-muted); }
.batch-scope-summary { display: flex; flex-wrap: wrap; gap: .35rem; }
.batch-scope-summary span {
  padding: .2rem .45rem;
  border-radius: 999px;
  color: var(--color-text-secondary);
  background: var(--color-surface-subtle);
  font-size: .68rem;
}
@media (max-width: 991.98px) {
  .coding-workspace { grid-template-columns: 1fr; }
  .coding-panel { position: static; }
}
@media (max-width: 767.98px) {
  .annotation-status-bar { align-items: stretch; flex-direction: column; }
  .annotation-status-bar .btn-group, .annotation-status-bar .btn { width: 100%; }
  .text-comparison, .export-controls { grid-template-columns: 1fr; }
  .dataset-metrics { width: 100%; }
  .dataset-metrics div { flex: 1; min-width: 0; }
  .assignment-grid { grid-template-columns: 1fr; }
  .preview-bar { align-items: stretch; flex-direction: column; }
}
@media (max-width: 575.98px) {
  .blind-badge { width: 100%; text-align: center; }
  .review-tabs { display: grid; grid-template-columns: 1fr; }
  .review-tabs .nav-link { width: 100%; text-align: left; }
  .segment, .context-block, .annotation { padding: .85rem; overflow-wrap: anywhere; }
  .card-body, .card-header { padding: 1rem !important; }
  .progress-summary { width: 100%; grid-template-columns: auto 1fr; gap: .5rem; text-align: left; align-items: baseline; }
  .adjudication-form .btn-danger { width: 100%; }
  .preview-metrics { grid-template-columns: repeat(2, 1fr); }
  .scope-panel { padding: .8rem; }
  .input-group .btn { width: 50%; border-radius: 0; }
}
</style>
