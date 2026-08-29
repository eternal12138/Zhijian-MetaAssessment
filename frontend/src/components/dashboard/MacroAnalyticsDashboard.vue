<script setup lang="ts">
import { computed, onMounted, onScopeDispose, ref, watch } from 'vue'
import { confirmAction, notify } from '../../composables/useUiFeedback'
import RadarChart from '../charts/RadarChart.vue'
import AppErrorBoundary from '../feedback/AppErrorBoundary.vue'
import { researchApi, type MacroAnalytics, type MacroOrderGroup, type MacroRadarProfile } from '../../api/research'
import { reportApi, type MetacognitionMeasurement } from '../../api/reports'
import type { DimensionScore } from '../../types/assessment'

const props = withDefaults(defineProps<{
  userRole?: 'student' | 'teacher' | 'admin'
  classGroups?: string[]
}>(), { userRole: 'teacher', classGroups: () => [] })

type ViewTab = 'macro_radar' | 'order_balance' | 'dimension_distribution' | 'pipeline_status'
type RadarDimension = 'monitoring' | 'controlDebugging' | 'evaluation'

const selectedClass = ref('all')
const selectedParticipant = ref('')
const activeViewTab = ref<ViewTab>('macro_radar')
const isLoading = ref(false)
const errorMessage = ref('')
const analytics = ref<MacroAnalytics | null>(null)
const measurementHistory = ref<MetacognitionMeasurement[]>([])
const selectedMeasurementRunId = ref('')
const selectedTaskId = ref('all')
const taskMeasurement = ref<MetacognitionMeasurement | null>(null)
const taskMeasurementLoading = ref(false)
// A failed task must not poison the cached whole-run result or history list.
const taskErrorMessage = ref('')
const uploadingCorrection = ref(false)
const correctionFile = ref<File | null>(null)
let requestId = 0
let taskRequestId = 0
let runRequestId = 0
let resettingRun = false
const runRefreshing = ref(false)
const runErrorMessage = ref('')
onScopeDispose(() => { requestId++; taskRequestId++; runRequestId++ })

const isStudent = computed(() => props.userRole === 'student')
const selectedRunMeasurement = computed(() => (
  measurementHistory.value.find(item => item.run_id === selectedMeasurementRunId.value)
  ?? measurementHistory.value[0]
  ?? null
))
const selectedMeasurement = computed(() => (
  selectedTaskId.value === 'all' ? selectedRunMeasurement.value : taskMeasurement.value
))
const taskOptions = computed(() => {
  const measurement = selectedRunMeasurement.value
  if (!measurement) return []
  return measurement.task_ids.map((id, index) => ({
    id,
    name: measurement.task_names[index] ?? `任务 ${index + 1}`
  }))
})
const studentRadarScores = computed<DimensionScore[]>(() => {
  const scores = selectedMeasurement.value?.dimension_scores
  if (!selectedMeasurement.value?.score_available || !scores) return []
  const rows: Array<{ dimension: DimensionScore['dimension']; label: string; score: number | null }> = [
    { dimension: 'monitoring', label: '监控', score: scores.monitoring },
    { dimension: 'controlDebugging', label: '控制/调试', score: scores.control_debugging },
    { dimension: 'evaluation', label: '评估', score: scores.evaluation }
  ]
  return rows
    .flatMap(row => row.score === null ? [] : [{ ...row, score: row.score, max: 1 }])
})
const studentMeasurementRows = computed(() => {
  const measurement = selectedMeasurement.value
  if (!measurement) return []
  return [
    { key: 'monitoring', label: '监控', score: measurement.dimension_scores.monitoring, count: measurement.dimension_counts.monitoring },
    { key: 'control_debugging', label: '控制/调试', score: measurement.dimension_scores.control_debugging, count: measurement.dimension_counts.control_debugging },
    { key: 'evaluation', label: '评估', score: measurement.dimension_scores.evaluation, count: measurement.dimension_counts.evaluation }
  ]
})
const classOptions = computed(() => Array.from(new Set([
  ...props.classGroups,
  ...(analytics.value?.available_class_groups ?? [])
].filter(Boolean))).sort((a, b) => a.localeCompare(b, 'zh-CN')))
const participantOptions = computed(() => analytics.value?.available_participants ?? [])
const primaryRadar = computed<MacroRadarProfile | null>(() => {
  const profiles = analytics.value?.radar_profiles
  return profiles ? profiles.participant ?? profiles.selected : null
})
const radarComparisons = computed(() => {
  const profiles = analytics.value?.radar_profiles
  const primary = primaryRadar.value
  if (!profiles || !primary) return []
  const candidates: MacroRadarProfile[] = []
  if (primary.scope === 'participant' && profiles.class_group?.total) candidates.push(profiles.class_group)
  if (profiles.overall.total && (primary.scope !== 'accessible' || props.userRole === 'teacher')) candidates.push(profiles.overall)
  return candidates
    .filter((profile, index, rows) => (
      profile.label !== primary.label
      && rows.findIndex(item => item.label === profile.label) === index
    ))
    .map((profile, index) => ({
      name: profile.label,
      scores: profile.scores,
      color: index === 0 ? '#22b88b' : '#12b6d4',
      dashed: true
    }))
})
const hasRadarData = computed(() => Boolean(primaryRadar.value?.score_available && primaryRadar.value.scores.length === 3))
const radarRows = computed(() => {
  const primary = primaryRadar.value
  if (!primary) return []
  const dimensions: Array<{ key: RadarDimension; label: string }> = [
    { key: 'monitoring', label: '监控（Monitoring）' },
    { key: 'controlDebugging', label: '调控（Regulation）' },
    { key: 'evaluation', label: '评估（Evaluation）' }
  ]
  const profiles = analytics.value?.radar_profiles
  const comparisons = [profiles?.class_group, profiles?.overall]
    .filter((item): item is MacroRadarProfile => Boolean(item?.total && item.label !== primary.label))
  return dimensions.map(item => ({
    ...item,
    percentage: primary.percentages[item.key],
    count: primary.counts[item.key],
    comparisons: comparisons.map(profile => ({ label: profile.label, percentage: profile.percentages[item.key] }))
  }))
})
const distributionRows = computed(() => {
  const distribution = analytics.value?.dimension_distribution
  const counts = distribution?.counts
  const total = primaryRadar.value?.effective_dialogue_count ?? 0
  return [
    { key: 'monitoring', label: '监控', count: counts?.monitoring ?? 0, tone: 'is-monitoring' },
    { key: 'controlDebugging', label: '调控', count: counts?.controlDebugging ?? 0, tone: 'is-regulation' },
    { key: 'evaluation', label: '评估', count: counts?.evaluation ?? 0, tone: 'is-evaluation' }
  ].map(item => ({ ...item, percentage: total ? item.count / total * 100 : 0 }))
})

function valueOrDash(value: number | null | undefined, suffix = '') { return value == null ? '—' : `${value}${suffix}` }
function groupFacts(group: MacroOrderGroup) {
  return [
    ['完整测评数', `${group.count} 份`], ['含画像得分', `${group.scoreCount} 份`],
    ['平均完成用时', valueOrDash(group.avgDurationMin, ' 分钟')], ['综合画像均分', valueOrDash(group.avgScore, ' 分')],
    ['已接受候选密度', valueOrDash(group.acceptedCandidateDensity, ' 条/分钟')]
  ]
}
function statusCount(statuses: Record<string, number> | undefined, ...keys: string[]) {
  return keys.reduce((total, key) => total + Number(statuses?.[key] ?? 0), 0)
}
function distributionSourceLabel(source: MacroAnalytics['dimension_distribution']['primary_source']) {
  return ({
expert_consensus: '双人盲编共识/仲裁结果', production_model: '候选文本的已完成模型分类',
    admin_upload: '管理员上传的完整校对集', hybrid: '按会话合并的专家/模型/上传结果', none: '暂无可用分类结果'
  })[source]
}

function measurementSourceLabel(source: MetacognitionMeasurement['source']) {
  return ({
    expert_consensus: '双人盲编共识/仲裁结果',
    uploaded_review: '人工校订后的权威结果',
    admin_upload: '管理员上传的完整校对集',
    production_model: '候选文本的已完成模型分类',
    hybrid: '按会话合并的专家/模型/上传结果',
    human_review: '人工确认后的候选结果',
    none: '暂无最终有效结果'
  } as Record<string, string>)[source] ?? source
}

function denominatorDescription(breakdown: Record<string, number> = {}) {
  const names: Record<string, string> = {
    human_review: '筛选并完成复核的有效对话', admin_upload: '管理员上传校对的有效对话',
    expert_consensus: '已完成专家复核的对话', label_total_fallback: '三类标签总数回退（暂定）'
  }
  return Object.entries(breakdown).filter(([, count]) => count > 0)
    .map(([source, count]) => `${names[source] ?? source} ${count} 条`).join('；') || '暂无有效分母'
}

const evidenceStatusLabels: Record<string, string> = {
  ready: '已有可用结果', classification_partial: '部分候选待分类',
  no_transcript: '暂无权威转录', awaiting_extraction: '当前转录尚未抽取',
  extraction_queued: '抽取排队中', extraction_running: '抽取中', extraction_processing: '抽取中',
  extraction_retry_wait: '抽取等待重试', extraction_retrying: '抽取等待重试', extraction_failed: '抽取失败',
  classification_pending: '当前版本待分类', classification_failed: '分类失败，等待处理',
  no_candidates: '抽取已完成，无候选', all_rejected: '候选均已排除', no_three_class_labels: '暂无有效三类标签'
}
function evidenceStatusLabel(status: string) { return evidenceStatusLabels[status] ?? '当前结果待处理' }
function evidenceStatusSummary(counts: Record<string, number> = {}) {
  return Object.entries(counts).map(([status, count]) => `${evidenceStatusLabel(status)}：${count} 个任务会话`).join('；')
}
function sessionEvidenceDescription(item: NonNullable<MetacognitionMeasurement['session_states']>[number]) {
  const name = taskOptions.value.find(task => task.id === item.task_id)?.name ?? '任务'
  const version = item.extraction_generation == null ? '' : ` · 抽取 V${item.extraction_generation}`
  const model = item.model_versions.length ? ` · 分类模型 ${item.model_versions.join('、')}` : ''
  const pending = item.using_previous_extraction ? `；新抽取 V${item.latest_generation} ${evidenceStatusLabel(`extraction_${item.latest_extraction_status}`)}，暂显示同一转录的上一成功版本` : ''
  return `${name}${version}：${evidenceStatusLabel(item.status)}${model}${pending}`
}

const comparisonProfiles = computed(() => [analytics.value?.radar_profiles.class_group, analytics.value?.radar_profiles.overall]
  .filter((item): item is MacroRadarProfile => Boolean(item && item.label !== primaryRadar.value?.label)))

function onCorrectionFile(event: Event) {
  correctionFile.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

async function downloadCorrectionTemplate() {
  try {
    const { data } = await reportApi.getCorrectionTemplate()
    const url = URL.createObjectURL(data)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = '有效对话校对模板.csv'
    anchor.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (error) {
    notify(error instanceof Error ? error.message : '模板下载失败', 'danger')
  }
}

async function uploadCorrection() {
  const file = correctionFile.value
  if (!file || uploadingCorrection.value || props.userRole !== 'admin') return
  if (!await confirmAction({
    title: '确认上传完整校对集', tone: 'warning', confirmText: '确认并保存新版本',
    message: '文件中的每个会话必须包含完整的有效对话和最终标签，不是增量片段。本次上传将作为这些会话的优先统计依据，三端同时生效；旧校对版本和 ASR 原文保留，文件未涉及的会话不变。'
  })) return
  uploadingCorrection.value = true
  try {
    const { data } = await reportApi.uploadMeasurementCorrections(file)
    notify(`已保存 ${data.session_count} 个会话、${data.dialogue_count} 条有效对话，统计已更新`)
    await fetchRealMacroData()
  } catch (error) {
    notify(error instanceof Error ? error.message : '校对上传失败', 'danger')
  } finally { uploadingCorrection.value = false }
}

function formatMeasurementOption(measurement: MetacognitionMeasurement) {
  const date = new Date(measurement.completed_at).toLocaleString('zh-CN', { hour12: false })
  const tasks = measurement.task_names.join(' / ') || '问题解决任务'
  const states = Object.keys(measurement.evidence_status_counts ?? {})
  const status = !measurement.score_available ? (states.length === 1 ? evidenceStatusLabel(states[0]!) : '待分类')
    : measurement.fallback_dialogue_count || measurement.unclassified_count ? '暂定结果' : '已有画像'
  return `${date} · ${status} · ${tasks}`
}

async function fetchRealMacroData() {
  const currentRequest = ++requestId
  ++runRequestId
  runRefreshing.value = false
  runErrorMessage.value = ''
  isLoading.value = true
  errorMessage.value = ''
  try {
    if (isStudent.value) {
      const items: MetacognitionMeasurement[] = []
      let page = 1
      let total = 0
      do {
        const response = await reportApi.listMetacognitionMeasurements(page++, 100)
        if (currentRequest !== requestId) return
        items.push(...response.data.items)
        total = response.data.total
        if (!response.data.items.length) break
      } while (items.length < total)
      measurementHistory.value = items
      if (!items.some(item => item.run_id === selectedMeasurementRunId.value)) {
        // The API orders all completed runs newest first, including unclassified runs.
        selectedMeasurementRunId.value = items[0]?.run_id ?? ''
      }
      await fetchSelectedTaskMeasurement()
      return
    }
    const response = await researchApi.getMacroAnalytics(selectedClass.value, isStudent.value ? undefined : selectedParticipant.value || undefined)
    if (currentRequest === requestId) analytics.value = response.data
  } catch (error) {
    if (currentRequest !== requestId) return
    if (isStudent.value) measurementHistory.value = []
    else analytics.value = null
    errorMessage.value = error instanceof Error ? error.message : '宏观研究数据加载失败'
  } finally {
    if (currentRequest === requestId) isLoading.value = false
  }
}

async function fetchSelectedRunMeasurement() {
  const currentRequest = ++runRequestId
  const runId = selectedMeasurementRunId.value
  runErrorMessage.value = ''
  if (!isStudent.value || !runId) return
  runRefreshing.value = true
  try {
    const response = await reportApi.getMetacognitionMeasurement(runId)
    if (currentRequest !== runRequestId || selectedMeasurementRunId.value !== runId) return
    if (response.data.run_id !== runId) throw new Error('返回结果与所选轮次不一致，请重试')
    measurementHistory.value = measurementHistory.value.map(item => item.run_id === runId ? response.data : item)
  } catch (error) {
    if (currentRequest === runRequestId) runErrorMessage.value = error instanceof Error ? error.message : '整轮结果刷新失败'
  } finally {
    if (currentRequest === runRequestId) runRefreshing.value = false
  }
}

async function fetchSelectedTaskMeasurement() {
  const currentRequest = ++taskRequestId
  taskMeasurement.value = null
  taskMeasurementLoading.value = false
  taskErrorMessage.value = ''
  if (!isStudent.value || selectedTaskId.value === 'all' || !selectedMeasurementRunId.value) return
  taskMeasurementLoading.value = true
  try {
    const response = await reportApi.getMetacognitionMeasurement(
      selectedMeasurementRunId.value,
      selectedTaskId.value
    )
    if (currentRequest === taskRequestId) taskMeasurement.value = response.data
  } catch (error) {
    if (currentRequest === taskRequestId) {
      taskErrorMessage.value = error instanceof Error ? error.message : '任务测量结果加载失败'
    }
  } finally {
    if (currentRequest === taskRequestId) taskMeasurementLoading.value = false
  }
}

watch(selectedClass, () => {
  if (selectedParticipant.value) selectedParticipant.value = ''
  else void fetchRealMacroData()
})
watch(selectedParticipant, () => void fetchRealMacroData())
watch(selectedMeasurementRunId, () => {
  resettingRun = true
  selectedTaskId.value = 'all'
  resettingRun = false
  taskMeasurement.value = null
  ++taskRequestId
  taskMeasurementLoading.value = false
  taskErrorMessage.value = ''
  if (!isLoading.value) void fetchSelectedRunMeasurement()
}, { flush: 'sync' })
watch(selectedTaskId, () => {
  void fetchSelectedTaskMeasurement()
  if (selectedTaskId.value === 'all' && !isLoading.value && !resettingRun) void fetchSelectedRunMeasurement()
}, { flush: 'sync' })
// Task-order students are paginated; a page change must not reset this filter.
watch(classOptions, classes => {
  if (selectedClass.value !== 'all' && !classes.includes(selectedClass.value)) selectedClass.value = 'all'
}, { deep: true })
onMounted(() => void fetchRealMacroData())
</script>

<template>
  <AppErrorBoundary component-name="元认知三类构成概览">
    <section class="macro-analytics-dashboard card border-0 shadow-sm mt-4">
      <div class="card-body p-4">
        <div class="macro-header">
          <div>
            <div class="title-line">
              <span class="badge bg-primary-subtle text-primary">{{ isStudent ? '真实测量数据' : '真实数据聚合' }}</span>
              <span v-if="(isStudent ? selectedMeasurement : analytics) && !isLoading" class="live-dot" title="已从数据库读取真实结果" />
              <h5 class="mb-0">{{ isStudent ? '元认知三维画像' : '班级宏观实证分析与全链路可观测大屏' }}</h5>
            </div>
            <p class="text-muted small mb-0 mt-1">{{ isStudent ? '每个维度均按本轮最终标签命中数 ÷ 最终有效对话总数计算；原始分数保持在 0–1，页面仅转换为百分比显示。' : '按真实三分类证据聚合学生、班级与全体样本，并同步展示研究处理链路；缺失数据不会使用演示值填充。' }}</p>
          </div>
          <div class="macro-actions">
            <template v-if="!isStudent">
              <select v-model="selectedClass" class="form-select form-select-sm class-selector" aria-label="选择班级">
                <option value="all">全部可访问样本</option>
                <option v-for="className in classOptions" :key="className" :value="className">{{ className }}</option>
              </select>
              <select v-model="selectedParticipant" class="form-select form-select-sm participant-selector" aria-label="选择学生">
                <option value="">{{ selectedClass === 'all' ? '按当前范围汇总' : '查看全班汇总' }}</option>
                <option v-for="participant in participantOptions" :key="participant.id" :value="participant.id">{{ participant.name }}（{{ participant.username }}）</option>
              </select>
            </template>
            <template v-else-if="measurementHistory.length">
              <span class="small text-muted">已完成 {{ measurementHistory.length }} 轮</span>
              <select v-model="selectedMeasurementRunId" class="form-select form-select-sm measurement-selector" aria-label="选择历史测量轮次">
                <option v-for="measurement in measurementHistory" :key="measurement.run_id" :value="measurement.run_id">{{ formatMeasurementOption(measurement) }}</option>
              </select>
              <select v-model="selectedTaskId" class="form-select form-select-sm task-selector" aria-label="选择测量任务">
                <option value="all">整轮汇总</option>
                <option v-for="task in taskOptions" :key="task.id" :value="task.id">{{ task.name }}</option>
              </select>
            </template>
            <button class="btn btn-sm btn-outline-secondary refresh-button" title="刷新数据库聚合结果" :disabled="isLoading" @click="fetchRealMacroData"><i class="bi" :class="isLoading ? 'bi-arrow-repeat spin' : 'bi-arrow-clockwise'" /></button>
            <div v-if="!isStudent" class="btn-group btn-group-sm tab-button-group">
              <button class="btn" :class="activeViewTab === 'macro_radar' ? 'btn-primary' : 'btn-outline-secondary'" @click="activeViewTab = 'macro_radar'"><i class="bi bi-pie-chart me-1" />三类占比</button>
              <button class="btn" :class="activeViewTab === 'order_balance' ? 'btn-primary' : 'btn-outline-secondary'" @click="activeViewTab = 'order_balance'"><i class="bi bi-shuffle me-1" />任务顺序</button>
              <button class="btn" :class="activeViewTab === 'dimension_distribution' ? 'btn-primary' : 'btn-outline-secondary'" @click="activeViewTab = 'dimension_distribution'"><i class="bi bi-bar-chart-steps me-1" />数量分布</button>
              <button class="btn" :class="activeViewTab === 'pipeline_status' ? 'btn-primary' : 'btn-outline-secondary'" @click="activeViewTab = 'pipeline_status'"><i class="bi bi-activity me-1" />处理链路</button>
            </div>
          </div>
        </div>

        <details v-if="props.userRole === 'admin'" class="correction-upload mb-3">
          <summary>管理员 · 上传有效对话校对</summary>
          <p class="small text-muted mt-3">CSV 三列：会话ID、校对文本、最终标签。会话ID可在转录校订页或导出数据中查看；每行是一条有效对话。请填写完整会话数据，不要只上传三类命中的句子。</p>
          <p class="small text-muted">标签：0=非元认知、1=监控、2=调控、3=评估，也可填写对应中文/英文类别。0 类保留在分母中，不进入三类分子。上传会同时校正分子和分母，不覆盖录音、ASR 原文或专家原始编码。限 UTF-8 CSV、5 MB、10000 条、100 个会话；仅支持已结束的测评。</p>
          <div class="d-flex flex-wrap gap-2 align-items-center">
            <button class="btn btn-outline-secondary btn-sm" @click="downloadCorrectionTemplate">下载校对模板</button>
            <input type="file" accept=".csv" class="form-control form-control-sm correction-file" aria-label="选择有效对话校对 CSV" :disabled="uploadingCorrection" @change="onCorrectionFile" />
            <button class="btn btn-primary btn-sm" :disabled="!correctionFile || uploadingCorrection" @click="uploadCorrection">{{ uploadingCorrection ? '正在校验并保存…' : '上传校对新版本' }}</button>
          </div>
        </details>

        <div v-if="errorMessage" class="alert alert-danger mb-0"><i class="bi bi-exclamation-triangle me-2" />{{ errorMessage }}</div>
        <div v-else-if="(isLoading || taskMeasurementLoading) && !(isStudent ? selectedMeasurement : analytics)" class="macro-loading" aria-label="正在读取三维测量数据"><span v-for="index in 4" :key="index" class="skeleton-block" /></div>

        <div v-else-if="isStudent" class="macro-view-pane">
          <p v-if="runRefreshing && selectedTaskId === 'all'" class="text-muted small" role="status">正在核对本轮最新结果，以下为已加载的数据…</p>
          <div v-if="runErrorMessage && selectedTaskId === 'all'" class="alert alert-warning" role="alert">{{ runErrorMessage }}。以下仍为上次读取的数据。<button class="btn btn-sm btn-outline-secondary ms-2" @click="fetchSelectedRunMeasurement">重试刷新</button></div>
          <div v-if="selectedMeasurement?.session_states?.length" class="composition-note mb-3" role="status"><i class="bi bi-info-circle-fill" /><div><p v-for="item in selectedMeasurement.session_states" :key="item.session_id" class="mb-1">{{ sessionEvidenceDescription(item) }}</p></div></div>
          <div v-if="taskErrorMessage" class="alert alert-danger mb-0" role="alert">
            <p class="mb-2">当前任务结果加载失败：{{ taskErrorMessage }}。可重试，或切回整轮汇总查看已加载的结果。</p>
            <button class="btn btn-sm btn-outline-danger" @click="fetchSelectedTaskMeasurement">重试当前任务</button>
          </div>
          <div v-else-if="!selectedMeasurement" class="macro-empty"><i class="bi bi-radar" /><strong>暂无已完成轮次</strong><p>完成一轮问题解决测评后，该轮次会显示在这里；分类结果生成后再展示三维画像。</p></div>
          <div v-else-if="!selectedMeasurement.score_available" class="macro-empty"><i class="bi bi-radar" /><strong>{{ selectedTaskId === 'all' ? '本轮' : '当前任务' }}暂无可用分类结果</strong><p>{{ evidenceStatusSummary(selectedMeasurement.evidence_status_counts) || '当前版本尚无可用分类，请联系教师核查。' }}。新转录或新抽取版本不沿用旧文本标签；没有分类结果时不生成虚假的零分画像。</p></div>
          <div v-else class="radar-detail-layout">
            <div class="radar-panel">
              <h6>三维占比</h6>
              <p class="radar-caption">{{ selectedMeasurement.task_name || '整轮汇总' }} · 各轴范围 0–100%</p>
              <div class="measurement-radar-stage"><RadarChart :scores="studentRadarScores" :name="selectedMeasurement.task_name || '整轮汇总'" :global-max="1" :display-as-percentage="true" :height="360" /></div>
            </div>
            <div class="radar-details">
              <div class="composition-note"><i class="bi bi-info-circle-fill" /><span>当前分母 <strong>{{ selectedMeasurement.effective_dialogue_count }} 条</strong>：{{ denominatorDescription(selectedMeasurement.denominator_breakdown) }}。三维不强制合计为 100%，不是能力分数或常模。</span></div>
              <div class="macro-stats-list mt-3">
                <div v-for="row in studentMeasurementRows" :key="row.key" class="stat-row"><span>{{ row.label }}</span><strong>{{ row.score === null ? '暂无' : `${(row.score * 100).toFixed(1)}%` }}<small>{{ row.count }} / {{ selectedMeasurement.effective_dialogue_count }} 条</small></strong></div>
              </div>
            </div>
            <div class="radar-context">
              <div v-if="selectedMeasurement.fallback_dialogue_count || selectedMeasurement.unclassified_count" class="alert alert-warning mb-0 small" role="status">此结果含暂定或未分类数据。回退分母 {{ selectedMeasurement.fallback_dialogue_count ?? 0 }} 条，已复核但待分类 {{ selectedMeasurement.unclassified_count ?? 0 }} 条；不能视为全部完成复核的正式结果。</div>
              <div class="radar-context-grid">
                <div class="stat-row"><span>当前范围</span><strong>{{ selectedMeasurement.task_name || '整轮汇总' }}<small>{{ selectedMeasurement.task_names.join(' / ') || '问题解决任务' }} · 完成于 {{ new Date(selectedMeasurement.completed_at).toLocaleString('zh-CN', { hour12: false }) }}</small></strong></div>
                <div class="stat-row"><span>结果来源</span><strong>{{ measurementSourceLabel(selectedMeasurement.source) }}<small>数据版本 {{ selectedMeasurement.data_version || '暂无' }}</small></strong></div>
              </div>
            </div>
          </div>
        </div>

        <div v-else-if="analytics && activeViewTab === 'macro_radar'" class="macro-view-pane">
          <div v-if="primaryRadar?.evidence_status_counts" class="composition-note mb-3" role="status"><i class="bi bi-info-circle-fill" /><span>{{ evidenceStatusSummary(primaryRadar.evidence_status_counts) }}。<template v-if="primaryRadar.retained_previous_count">其中 {{ primaryRadar.retained_previous_count }} 个会话的新抽取尚未成功，暂使用同一转录的上一成功版本。</template></span></div>
          <div v-if="!hasRadarData" class="macro-empty"><i class="bi bi-radar" /><strong>当前范围暂无三分类证据</strong><p>完成候选复核并形成专家编码，或使用已启用模型完成三分类后，系统才会按真实记录计算占比。</p></div>
          <div v-else class="radar-detail-layout">
            <div class="radar-panel">
              <h6>三维占比与范围对比</h6>
              <p class="radar-caption">{{ primaryRadar?.label ?? '当前范围' }} · 各轴范围 0–100%</p>
              <div class="measurement-radar-stage"><RadarChart :scores="primaryRadar?.scores ?? []" :comparison-series="radarComparisons" :name="primaryRadar?.label ?? '当前范围'" value-unit="%" :height="360" /></div>
            </div>
            <div class="radar-details">
              <div class="composition-note"><i class="bi bi-info-circle-fill" /><span>各维度按<strong>标签命中数 ÷ 最终有效对话数</strong>计算，三个百分比不强制合计为 100%。既无复核也无上传校对数据的会话，才回退三类标签总数；不是能力分数或常模。</span></div>
              <div class="macro-stats-list mt-3">
                <div v-for="row in radarRows" :key="row.key" class="stat-row"><span>{{ row.label }}</span><strong>{{ row.percentage.toFixed(1) }}% <small>{{ row.count }} / {{ primaryRadar?.effective_dialogue_count }} 条<span v-for="comparison in row.comparisons" :key="comparison.label"> · {{ comparison.label }} {{ comparison.percentage.toFixed(1) }}%</span></small></strong></div>
              </div>
            </div>
            <div class="radar-context">
              <div v-if="primaryRadar?.fallback_dialogue_count || primaryRadar?.unclassified_count" class="alert alert-warning mb-0 small" role="status">包含三类标签总数回退 {{ primaryRadar?.fallback_dialogue_count ?? 0 }} 条；已复核待分类 {{ primaryRadar?.unclassified_count ?? 0 }} 条。当前汇总不是全部完成复核的正式结果。</div>
              <div class="radar-context-grid">
                <div class="stat-row"><span>当前统计范围</span><strong>{{ primaryRadar?.label }}<small>三类标签 {{ primaryRadar?.total }} 条 / 分母 {{ primaryRadar?.effective_dialogue_count }} 条 · 来自 {{ primaryRadar?.sample_count }} 次测评</small></strong></div>
                <div class="stat-row"><span>分母来源</span><strong>{{ denominatorDescription(primaryRadar?.denominator_breakdown) }}</strong></div>
                <div class="stat-row"><span>结果来源</span><strong>{{ distributionSourceLabel(primaryRadar?.primary_source ?? 'none') }}</strong></div>
                <div v-for="profile in comparisonProfiles" :key="profile.scope" class="stat-row"><span>{{ profile.label }} · 对比分母</span><strong>{{ profile.effective_dialogue_count }} 条<small>{{ denominatorDescription(profile.denominator_breakdown) }}</small></strong></div>
              </div>
              <div class="alert alert-info py-2 px-3 small mb-0"><i class="bi bi-shield-check me-1" />{{ analytics.profile_source }}</div>
            </div>
          </div>
        </div>

        <div v-else-if="analytics && activeViewTab === 'order_balance'" class="macro-view-pane">
          <div class="row g-3"><div v-for="group in [analytics.order_balance.groupAB, analytics.order_balance.groupBA]" :key="group.name" class="col-md-6"><div class="order-card"><h6><i class="bi bi-shuffle me-1" />{{ group.name }}</h6><ul class="list-unstyled mb-0 mt-2 small text-muted"><li v-for="fact in groupFacts(group)" :key="fact[0]">{{ fact[0] }}：<strong>{{ fact[1] }}</strong></li></ul></div></div></div>
          <div class="stat-conclusion-box" :class="analytics.order_balance.test.available ? 'is-ready' : 'is-pending'"><h6><i class="bi bi-clipboard-data me-1" />顺序效应分析边界</h6><p v-if="analytics.order_balance.test.available">Welch t 检验（{{ analytics.order_balance.test.metric }}）：<strong>t = {{ analytics.order_balance.test.t_statistic }}，p = {{ analytics.order_balance.test.p_value }}</strong><span v-if="analytics.order_balance.test.levene_p_value !== null">；Levene p = {{ analytics.order_balance.test.levene_p_value }}</span></p><p>{{ analytics.order_balance.test.interpretation }}</p></div>
        </div>

        <div v-else-if="analytics && activeViewTab === 'dimension_distribution'" class="macro-view-pane">
          <div class="distribution-source"><span>当前展示来源</span><strong>{{ distributionSourceLabel(analytics.dimension_distribution.primary_source) }}</strong></div>
          <div v-if="analytics.dimension_distribution.total" class="distribution-bars"><div v-for="row in distributionRows" :key="row.key" class="distribution-row"><div><span>{{ row.label }}</span><strong>{{ row.count }} 条 · {{ row.percentage.toFixed(1) }}%</strong></div><div class="distribution-track"><span :class="row.tone" :style="{ width: row.percentage + '%' }" /></div></div></div>
          <div v-else class="macro-empty compact"><i class="bi bi-tags" /><strong>暂无已完成的三分类数据</strong><p>完成双人编码共识/仲裁或使用已启用模型完成候选分类后，这里才会出现真实分布。</p></div>
          <p class="text-muted small mt-3 mb-0">三类标签共 {{ analytics.dimension_distribution.total }} 条，分母 {{ primaryRadar?.effective_dialogue_count ?? 0 }} 条。{{ denominatorDescription(primaryRadar?.denominator_breakdown) }}。百分比与雷达图一致；不是行为转化率或能力等级。</p>
        </div>

        <div v-else-if="analytics && activeViewTab === 'pipeline_status'" class="macro-view-pane">
          <div class="row g-3"><div class="col-sm-6 col-lg-4"><div class="metric-card"><span>本次数据库聚合耗时</span><h4>{{ analytics.pipeline_status.aggregation_latency_ms }} ms</h4><small>仅为当前请求，不冒充历史 P95</small></div></div><div class="col-sm-6 col-lg-4"><div class="metric-card"><span>ASR 终态成功率</span><h4>{{ valueOrDash(analytics.pipeline_status.asr.success_rate, '%') }}</h4><small>成功 {{ statusCount(analytics.pipeline_status.asr.statuses, 'completed') }} / 终态 {{ analytics.pipeline_status.asr.terminal_count }}</small></div></div><div class="col-sm-6 col-lg-4"><div class="metric-card"><span>候选三分类覆盖率</span><h4>{{ valueOrDash(analytics.pipeline_status.classification.coverage_rate, '%') }}</h4><small>已分类 {{ analytics.pipeline_status.classification.classified_candidates }} / 可分类 {{ analytics.pipeline_status.classification.eligible_candidates }}</small></div></div></div>
          <div class="pipeline-facts"><span><i class="bi bi-database-check text-success" />数据库查询可用</span><span>ASR：排队/处理中 {{ statusCount(analytics.pipeline_status.asr.statuses, 'queued', 'processing', 'retry_wait') }}，失败 {{ statusCount(analytics.pipeline_status.asr.statuses, 'failed') }}</span><span>AI 清洗：待复核/已复核 {{ statusCount(analytics.pipeline_status.extraction.statuses, 'reviewing', 'reviewed') }}，待处理 {{ statusCount(analytics.pipeline_status.extraction.statuses, 'queued', 'running', 'retry_wait') }}，失败 {{ statusCount(analytics.pipeline_status.extraction.statuses, 'failed') }}</span></div>
          <p class="text-muted small mt-3 mb-0">数据更新时间：{{ new Date(analytics.generated_at).toLocaleString('zh-CN', { hour12: false }) }}。当前系统尚未持久化请求时延序列，因此不展示无法验证的 P95、连接池百分比或自动重试成功率。</p>
        </div>
      </div>
    </section>
  </AppErrorBoundary>
</template>

<style scoped>
.correction-upload { padding: .85rem 1rem; border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface-subtle); }
.correction-upload summary { cursor: pointer; font-weight: 600; }
.correction-file { width: min(100%, 340px); }
.macro-analytics-dashboard {
  container-type: inline-size;
  min-width: 0;
  max-width: 100%;
  background: var(--color-surface);
  border: 1px solid var(--color-border) !important;
  border-radius: var(--radius-xl);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.04);
}
.macro-header, .macro-actions, .title-line, .pipeline-facts { display: flex; align-items: center; gap: .75rem; }
.macro-header { flex-direction: column; align-items: stretch; margin-bottom: 1.5rem; }
.macro-header > div { min-width: 0; }
.macro-actions { flex-wrap: wrap; justify-content: flex-start; padding-top: .75rem; border-top: 1px solid var(--color-border); }
.macro-actions > * { min-width: 0; max-width: 100%; }
.tab-button-group { display: flex; flex-wrap: wrap; gap: .25rem; }
.tab-button-group .btn { border-radius: var(--radius-sm) !important; margin: 0 !important; flex: 1 1 auto; white-space: normal; }
.title-line { gap: .65rem; flex-wrap: wrap; align-items: center; }
.title-line h5 { font-size: 1.18rem; font-weight: 700; color: var(--color-text); }
.class-selector { width: 190px; }
.participant-selector { width: 220px; }
.measurement-selector { width: min(480px, 100%); }
.task-selector { width: 180px; }
.live-dot { flex: 0 0 7px; width: 7px; height: 7px; border-radius: 50%; background: var(--color-success); box-shadow: 0 0 7px var(--color-success); }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.macro-view-pane { min-height: 270px; padding-top: .5rem; }
.macro-loading { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; min-height: 280px; }
.skeleton-block { border-radius: var(--radius-md); background: linear-gradient(90deg, var(--color-surface-subtle), color-mix(in srgb, var(--color-primary) 10%, var(--color-surface)), var(--color-surface-subtle)); background-size: 220% 100%; animation: shimmer 1.4s infinite; }
@keyframes shimmer { to { background-position: -220% 0; } }
.radar-detail-layout { display: grid; grid-template-columns: minmax(0, 1fr); align-items: stretch; gap: 1rem 1.5rem; }
.radar-panel { display: flex; flex-direction: column; min-width: 0; padding: 1rem; border: 1px solid var(--color-border); border-radius: var(--radius-lg); background: var(--color-surface-subtle); }
.radar-panel h6 { margin: 0; color: var(--color-text); font-size: 1rem; font-weight: 700; }
.radar-caption { margin: .4rem 0 .5rem; color: var(--color-text-muted); font-size: .85rem; line-height: 1.6; overflow-wrap: anywhere; }
/* Do not reuse legacy .radar-wrap: layout.css reserves an empty 180px column there. */
.measurement-radar-stage { display: grid; place-items: center; flex: 1; width: 100%; min-width: 0; }
.measurement-radar-stage :deep(.radar-chart-wrapper) { width: 100%; max-width: 600px; min-width: 0; }
.radar-details { display: flex; flex-direction: column; justify-content: center; min-width: 0; }
.radar-context { grid-column: 1 / -1; display: grid; gap: 1rem; min-width: 0; padding-top: 1rem; border-top: 1px solid var(--color-border); }
.radar-context-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: .75rem; }
.radar-context-grid .stat-row { grid-template-columns: minmax(0, 1fr); gap: .25rem; }
.radar-context-grid .stat-row > span { color: var(--color-text-muted); font-size: .85rem; }
.radar-context-grid .stat-row strong { text-align: left; }
.radar-details .alert, .radar-context .alert, .composition-note, .stat-row, .title-line h5, .pipeline-facts, .distribution-source { overflow-wrap: anywhere; }
@container (min-width: 680px) {
  .radar-context-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@container (min-width: 940px) {
  .radar-detail-layout { grid-template-columns: minmax(0, .95fr) minmax(0, 1.05fr); }
}
@container (max-width: 560px) {
  .stat-row { grid-template-columns: minmax(0, 1fr) !important; gap: .35rem !important; }
  .stat-row strong { text-align: left !important; }
  .macro-actions select { width: 100%; }
  .radar-panel { padding: .75rem .5rem; }
}
.composition-note { display: flex; gap: .65rem; align-items: flex-start; padding: .8rem .9rem; border: 1px solid color-mix(in srgb, var(--color-primary) 28%, var(--color-border)); border-radius: var(--radius-md); background: color-mix(in srgb, var(--color-primary) 8%, var(--color-surface)); color: var(--color-text-muted); font-size: .84rem; }
.composition-note { font-size: .9rem; line-height: 1.65; }
.composition-note > span { min-width: 0; }
.composition-note i { color: var(--color-primary); flex-shrink: 0; }
.composition-note strong { color: var(--color-text); }
.macro-stats-list { display: grid; gap: .55rem; }
.stat-row { display: grid; grid-template-columns: minmax(0, .85fr) minmax(0, 1.15fr); align-items: start; gap: .75rem; padding: .85rem 1rem; background: var(--color-surface-subtle); border: 1px solid var(--color-border); border-radius: var(--radius-md); font-size: .94rem; line-height: 1.6; }
.stat-row > * { min-width: 0; }
.stat-row strong { color: var(--color-text); text-align: right; }
.stat-row small { display: block; color: var(--color-text-muted); font-weight: 500; font-size: .82rem; line-height: 1.65; margin-top: .25rem; }
.macro-empty {
  min-height: 230px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: .75rem;
  text-align: center;
  color: var(--color-text-muted);
  padding: 2.2rem 1.5rem;
}
.macro-empty i { font-size: 2.4rem; color: var(--color-primary); opacity: .9; margin-bottom: .2rem; }
.macro-empty strong { font-size: 1.05rem; color: var(--color-text); font-weight: 700; }
.macro-empty p { max-width: 580px; margin: 0; font-size: .88rem; line-height: 1.65; color: var(--color-text-muted); }
.macro-empty.compact { min-height: 190px; }
.order-card, .metric-card { height: 100%; padding: 1rem; border-radius: var(--radius-md); border: 1px solid var(--color-border); background: var(--color-surface-subtle); }
.order-card h6 { color: var(--color-primary); }
.order-card ul { display: grid; gap: .4rem; }
.order-card li { display: flex; justify-content: space-between; gap: 1rem; }
.order-card strong { color: var(--color-text); }
.stat-conclusion-box { padding: 1rem; margin-top: 1rem; border: 1px solid var(--color-border); border-radius: var(--radius-md); }
.stat-conclusion-box.is-ready { background: color-mix(in srgb, var(--color-success) 10%, var(--color-surface)); }
.stat-conclusion-box.is-pending { background: color-mix(in srgb, var(--color-warning) 11%, var(--color-surface)); }
.stat-conclusion-box h6 { margin-bottom: .35rem; }
.stat-conclusion-box p { margin: 0; font-size: .84rem; }
.distribution-source { display: flex; justify-content: space-between; gap: 1rem; padding: .75rem 1rem; border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface-subtle); }
.distribution-bars { display: grid; gap: 1rem; padding: 1rem 0; }
.distribution-row > div:first-child { display: flex; justify-content: space-between; margin-bottom: .4rem; font-size: .86rem; }
.distribution-track { height: 15px; overflow: hidden; border-radius: 999px; background: var(--color-surface-subtle); border: 1px solid var(--color-border); }
.distribution-track span { display: block; height: 100%; border-radius: inherit; transition: width .35s ease; }
.is-monitoring { background: linear-gradient(90deg, #6762e8, #8b7cf6); }
.is-regulation { background: linear-gradient(90deg, #17a2b8, #37c8d9); }
.is-evaluation { background: linear-gradient(90deg, #2e9b70, #53c997); }
.metric-card { text-align: center; }
.metric-card > span, .metric-card small { color: var(--color-text-muted); font-size: .78rem; }
.metric-card h4 { margin: .35rem 0; color: var(--color-primary); }
.pipeline-facts { justify-content: space-between; flex-wrap: wrap; margin-top: 1rem; padding: .85rem 1rem; border-top: 1px solid var(--color-border); border-bottom: 1px solid var(--color-border); color: var(--color-text-muted); font-size: .82rem; }
.pipeline-facts span { display: inline-flex; align-items: center; gap: .35rem; }
@media (max-width: 767.98px) {
  .card-body { padding: 1rem !important; }
  .macro-header, .macro-actions { align-items: stretch; }
  .macro-actions, .tab-button-group, .class-selector, .participant-selector, .measurement-selector, .task-selector { width: 100%; }
  .refresh-button { min-height: 40px; }
  .tab-button-group { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .tab-button-group .btn { border-radius: var(--radius-sm) !important; }
  .macro-loading { grid-template-columns: 1fr; }
  .stat-row, .distribution-source, .order-card li { align-items: flex-start; flex-direction: column; gap: .25rem; }
  .stat-row strong { text-align: left; }
}
@media (prefers-reduced-motion: reduce) {
  .skeleton-block, .spin { animation: none; }
  .distribution-track span { transition: none; }
}
</style>
