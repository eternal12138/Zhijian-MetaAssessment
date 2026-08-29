<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useLatestRequest } from '../composables/useLatestRequest'
import SectionPagination from '../components/ui/SectionPagination.vue'
import ReportGenerationJobs from '../components/dashboard/ReportGenerationJobs.vue'
import { useUserStore } from '../stores/user'
import {
  researchApi,
  type AudioTranscriptExportPreview,
  type ResearchAnalytics,
  type ResearchDashboard,
  type RunQuality,
  type TaskOrderOverview,
  type TaskOrderStudent
} from '../api/research'
import { asrApi } from '../api/asr'
import { confirmAction, notify } from '../composables/useUiFeedback'
import AppModal from '../components/ui/AppModal.vue'
import ExportGuideOrb from '../components/export/ExportGuideOrb.vue'
import MacroAnalyticsDashboard from '../components/dashboard/MacroAnalyticsDashboard.vue'

const dashboard = ref<ResearchDashboard | null>(null)
const analytics = ref<ResearchAnalytics | null>(null)
const taskOrders = ref<TaskOrderOverview | null>(null)
const selectedStudents = ref<string[]>([])
const assigningId = ref('')
const balancing = ref(false)
const isLoading = ref(true)
const exporting = ref<'csv' | 'bundle' | ''>('')
const exportStatusMessage = ref('')
const exportProgress = ref(0)
const exportCancelRequested = ref(false)
const exportMode = ref<'all' | 'incremental' | 'accepted_only'>('all')
const exportIncludeAudio = ref(true)
const exportDialogOpen = ref(false)
const exportPreview = ref<AudioTranscriptExportPreview | null>(null)
const exportPreviewLoading = ref(false)
let exportPreviewRequestId = 0
const generatedDraftRunId = ref('')
const analyzingId = ref('')
const analysisErrorMsg = ref('')
const batchAnalyzing = ref(false)
const batchAnalyzeProgress = ref({ current: 0, total: 0 })
const analysisProgress = ref<Record<string, number>>({})
const errorMessage = ref('')
const sectionErrors = ref<string[]>([])
const successMessage = ref('')
const exportExpanded = ref(false)
const transcriptAttention = ref(0)
const codingAssignments = ref(0)
const codingDisagreements = ref(0)
const qualityRuns = ref<RunQuality[]>([])
const qualitySearch = ref('')
const qualityFilter = ref('attention')
const qualityPage = ref(1)
const qualityPageSize = ref(10)
const qualityTotal = ref(0)
const taskOrderSearch = ref('')
const taskOrderPage = ref(1)
const taskOrderPageSize = ref(10)
const reportsPage = ref(1)
const reportsPageSize = ref(10)
type RecentReport = ResearchDashboard['recent_reports'][number]
type PendingRun = ResearchDashboard['unanalyzed_runs'][number]
const selectedReports = ref<string[]>([])
const refreshingReportId = ref('')
const refreshingReports = ref(false)
const stopReportRefresh = ref(false)
const reportRefreshProgress = ref({ completed: 0, total: 0 })
const reportRefreshResults = ref<Array<{ id: string; name: string; success: boolean; message: string }>>([])
const reportActionsBusy = computed(() => refreshingReports.value || batchAnalyzing.value || !!analyzingId.value)
const selectableReports = computed(() => (dashboard.value?.recent_reports ?? []).filter(canReanalyzeReport))
const allReportsSelected = computed(() => selectableReports.value.length > 0 && selectableReports.value.every(item => selectedReports.value.includes(item.id)))
const pendingPage = ref(1)
const pendingPageSize = ref(10)
const { run: requestQuality, invalidate: invalidateQuality, loading: qualityLoading, error: qualityError } = useLatestRequest()
const { run: requestOrders, invalidate: invalidateOrders, loading: ordersLoading, error: ordersError } = useLatestRequest()
const { run: requestDashboard, invalidate: invalidateDashboard, loading: dashboardLoading, error: dashboardError } = useLatestRequest()
let syncingDashboardPages = false
const qualityDecisionTarget = ref<RunQuality | null>(null)
const qualityDecision = ref<'automatic' | 'included' | 'excluded'>('included')
const qualityReason = ref('')
const qualitySaving = ref(false)
const userStore = useUserStore()
const macroClassGroups = computed(() => Array.from(new Set(
  (taskOrders.value?.students ?? [])
    .map(student => student.class_group?.trim())
    .filter((classGroup): classGroup is string => Boolean(classGroup))
)).sort((a, b) => a.localeCompare(b, 'zh-CN')))

const pageTitle = computed(() => (
  userStore.profile.role === 'admin' ? '系统与研究概览' : '教师与研究中心'
))
// Search/status filtering belongs to the server, before pagination.

const agreementText = computed(() => {
  const value = analytics.value?.agreement.dimension_percent_agreement
  return value == null ? '--' : `${Math.round(value * 100)}%`
})

function metric(value: number | null | undefined, digits = 3) {
  return value == null ? '--' : value.toFixed(digits)
}

function exportTime(value: string | null | undefined) {
  if (!value) return ''
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

const reliabilityPresentation = computed(() => {
  const sampleSize = analytics.value?.questionnaire.complete_sample_size ?? 0
  const alpha = analytics.value?.questionnaire.cronbach_alpha
  if (sampleSize < 30) {
    return {
      value: '样本不足',
      detail: `完整样本 ${sampleSize}/30，暂不报告信度系数`,
      tone: 'is-pending'
    }
  }
  if (alpha == null || alpha < 0 || alpha > 1) {
    return {
      value: '暂不可报告',
      detail: '当前计算结果不在有效区间，请检查题目计分与数据质量',
      tone: 'is-warning'
    }
  }
  return {
    value: alpha.toFixed(3),
    detail: '达到当前研究展示所需的最低完整样本量',
    tone: 'is-ready'
  }
})

function reportStatusLabel(status: string) {
  return ({ draft: '草稿 · 待审阅', review_pending: '草稿 · 待审阅', reviewed: '草稿 · 待发布确认', published: '已发布', archived: '已归档' } as Record<string, string>)[status] || '状态待确认'
}

function reportStatusClass(status: string) {
  if (status === 'published') return 'bg-success-subtle text-success-emphasis'
  if (status === 'review_pending') return 'bg-warning-subtle text-warning-emphasis'
  if (status === 'reviewed') return 'bg-primary-subtle text-primary-emphasis'
  return 'bg-secondary-subtle text-secondary-emphasis'
}

function canReanalyzeReport(item: RecentReport) {
  return item.can_reanalyze === true && !!item.run_id && ['draft', 'review_pending', 'reviewed'].includes(item.status)
}

function activeJobFor(item: PendingRun) {
  return item.active_job ?? null
}

function isGenerating(item: PendingRun) {
  return !!activeJobFor(item) || analyzingId.value === item.run_id
}

function generationProgressFor(item: PendingRun): number {
  const active = activeJobFor(item)
  if (active) return active.progress
  if (analyzingId.value === item.run_id) return analysisProgress.value[item.run_id] ?? 0
  return 0
}

function reportChecksText(item: RecentReport) {
  if (item.status === 'published') return '发布时已通过审核'
  if (item.status === 'archived') return '已归档，不再处理'
  const issues: string[] = []
  if (!['eligible', 'included', 'included_override'].includes(item.quality_status)) issues.push('数据质量待处理')
  if (item.requires_review_count) issues.push(`有效对话待分类 ${item.requires_review_count} 条`)
  if (item.double_review_pending == null) issues.push('尚未建立双人盲编批次')
  else if (item.double_review_pending > 0) issues.push(`盲编待完成 ${item.double_review_pending} 条`)
  return issues.join('；') || '进入草稿核对 AI 来源、数据版本与发布条件'
}

function toggleReportSelection() {
  selectedReports.value = allReportsSelected.value ? [] : selectableReports.value.map(item => item.id)
}

async function reanalyzeReports(single?: RecentReport) {
  if (reportActionsBusy.value || dashboardLoading.value || dashboardError.value) return
  const items = single ? [single].filter(canReanalyzeReport) : selectableReports.value.filter(item => selectedReports.value.includes(item.id))
  if (!items.length) return
  const confirmed = await confirmAction({
    title: single ? '重新 AI 分析草稿' : `批量重新 AI 分析 ${items.length} 份草稿`,
    message: `将按当前报告提示词，依据已有转录、编码及复核结果重新生成${single ? '这份' : '本页所选'}草稿的画像和建议。不会修改原始数据或人工编码；成功后替换原草稿并更新生成时间，需重新审阅，不会自动发布。失败时保留原稿。批量任务逐份执行，请保持页面打开。`,
    confirmText: '确认重新分析', tone: 'primary'
  })
  if (!confirmed || reportActionsBusy.value) return
  refreshingReports.value = true
  stopReportRefresh.value = false
  reportRefreshProgress.value = { completed: 0, total: items.length }
  reportRefreshResults.value = []
  try {
    for (const item of items) {
      if (stopReportRefresh.value) break
      refreshingReportId.value = item.id
      try {
        const result = (await researchApi.startAnalysis(item.run_id, false, {
          report_only: true, expected_generated_at: item.generated_at
        })).data
        if (result.status !== 'completed') throw new Error(result.error_message || 'AI 分析未完成，原草稿已保留')
        reportRefreshResults.value.push({ id: item.id, name: `${item.user_name}（${item.username}）`, success: true, message: '已更新草稿，请重新审阅' })
        selectedReports.value = selectedReports.value.filter(id => id !== item.id)
      } catch (error) {
        reportRefreshResults.value.push({ id: item.id, name: `${item.user_name}（${item.username}）`, success: false, message: error instanceof Error ? error.message : '请求失败，请刷新核对报告状态后重试' })
      } finally {
        reportRefreshProgress.value.completed++
      }
    }
    const success = reportRefreshResults.value.filter(item => item.success).length
    const failed = reportRefreshResults.value.length - success
    const skipped = items.length - reportRefreshResults.value.length
    notify(`重新 AI 分析结束：成功 ${success} 份，失败 ${failed} 份${skipped ? `，未执行 ${skipped} 份` : ''}。`, failed || skipped ? 'warning' : 'success')
    // Regenerated reports move to the top; fetch only this dashboard, not all analytics.
    await loadDashboardPage()
  } finally {
    refreshingReportId.value = ''
    refreshingReports.value = false
  }
}

const dimensionLabels: Record<string, string> = {
  monitoring: '监控',
  controlDebugging: '控制/调试',
  evaluation: '评估'
}

function ratio(value: number | null | undefined) {
  return value == null ? '--' : `${(value * 100).toFixed(1)}%`
}

async function loadPage() {
  isLoading.value = true
  errorMessage.value = ''
  sectionErrors.value = []
  const analyticsController = new AbortController()
  // 2C4G 云端首次聚合可能需要数秒；3 秒会把正常慢查询误判为失败。
  const analyticsTimeout = window.setTimeout(() => analyticsController.abort(), 15000)
  const requests = await Promise.allSettled([
      loadDashboardPage(),
      researchApi.analytics({ signal: analyticsController.signal }),
      loadTaskOrderPage(),
      asrApi.reviewQueue(),
      researchApi.listCodingUnitAssignments(),
      researchApi.listCodingUnitDisagreements(),
      loadQualityPage()
    ])
  window.clearTimeout(analyticsTimeout)
  const labels = ['研究概览', '统计指标', '任务顺序', '转录队列', '盲编待办', '仲裁待办', '数据质量']
  requests.forEach((result, index) => {
    if (result.status === 'rejected') sectionErrors.value.push(labels[index] ?? `分区 ${index + 1}`)
  })
  try {
    if (requests[1]?.status === 'fulfilled') analytics.value = requests[1].value.data
    if (requests[3]?.status === 'fulfilled') {
      transcriptAttention.value = requests[3].value.data.filter(item =>
        ['failed', 'retry_wait', 'waiting_configuration'].includes(item.job.status)
      ).length
    }
    if (requests[4]?.status === 'fulfilled') codingAssignments.value = requests[4].value.data.length
    if (requests[5]?.status === 'fulfilled') codingDisagreements.value = requests[5].value.data.length
  } finally {
    isLoading.value = false
  }
}

async function loadQualityPage() {
  await requestQuality(() => researchApi.listRunQuality({
      page: qualityPage.value,
      page_size: qualityPageSize.value,
      search: qualitySearch.value.trim(),
      status_filter: qualityFilter.value
    }), response => {
    qualityRuns.value = response.data
    qualityTotal.value = Number(response.headers['x-total-count'] ?? response.data.length)
    const last = Math.max(1, Math.ceil(qualityTotal.value / qualityPageSize.value))
    if (qualityPage.value > last) qualityPage.value = last
  })
}

async function loadTaskOrderPage() {
  await requestOrders(() => researchApi.taskOrderAssignments({
      page: taskOrderPage.value,
      page_size: taskOrderPageSize.value,
      search: taskOrderSearch.value.trim()
    }), response => {
    taskOrders.value = response.data
    selectedStudents.value = selectedStudents.value.filter(id => response.data.students.some(student => student.user_id === id))
    const last = Math.max(1, Math.ceil(response.data.total / taskOrderPageSize.value))
    if (taskOrderPage.value > last) taskOrderPage.value = last
  })
}

async function loadDashboardPage() {
  await requestDashboard(() => researchApi.dashboard({
    reports_page: reportsPage.value, reports_page_size: reportsPageSize.value,
    pending_page: pendingPage.value, pending_page_size: pendingPageSize.value
  }), response => {
    dashboard.value = response.data
    selectedReports.value = selectedReports.value.filter(id => response.data.recent_reports.some(item => item.id === id && canReanalyzeReport(item)))
    syncingDashboardPages = true
    reportsPage.value = response.data.reports_page
    pendingPage.value = response.data.pending_page
    syncingDashboardPages = false
  })
}

let qualityFilterTimer: ReturnType<typeof setTimeout> | null = null
let taskOrderFilterTimer: ReturnType<typeof setTimeout> | null = null
watch([qualitySearch, qualityFilter, qualityPageSize], () => {
  qualityPage.value = 1
}, { flush: 'sync' })
watch([qualitySearch, qualityFilter, qualityPageSize, qualityPage], () => {
  invalidateQuality()
  if (qualityFilterTimer) clearTimeout(qualityFilterTimer)
  qualityFilterTimer = setTimeout(() => void loadQualityPage(), 300)
})
watch([taskOrderSearch, taskOrderPageSize], () => {
  taskOrderPage.value = 1
}, { flush: 'sync' })
watch([taskOrderSearch, taskOrderPageSize, taskOrderPage], () => {
  invalidateOrders()
  selectedStudents.value = []
  if (taskOrderFilterTimer) clearTimeout(taskOrderFilterTimer)
  taskOrderFilterTimer = setTimeout(() => void loadTaskOrderPage(), 300)
})
watch(reportsPageSize, () => { reportsPage.value = 1 }, { flush: 'sync' })
watch(pendingPageSize, () => { pendingPage.value = 1 }, { flush: 'sync' })
watch([reportsPage, reportsPageSize], () => { selectedReports.value = [] }, { flush: 'sync' })
let dashboardPageTimer: ReturnType<typeof setTimeout> | null = null
watch([reportsPage, reportsPageSize, pendingPage, pendingPageSize], () => {
  if (syncingDashboardPages) return
  invalidateDashboard()
  if (dashboardPageTimer) clearTimeout(dashboardPageTimer)
  dashboardPageTimer = setTimeout(() => void loadDashboardPage(), 0)
}, { flush: 'sync' })
onUnmounted(() => {
  stopReportRefresh.value = true
  if (qualityFilterTimer) clearTimeout(qualityFilterTimer)
  if (taskOrderFilterTimer) clearTimeout(taskOrderFilterTimer)
  if (dashboardPageTimer) clearTimeout(dashboardPageTimer)
})

function qualityStatusLabel(status: string) {
  return ({
    eligible: '自动通过', review_required: '需要复核', ineligible: '暂不可纳入',
    included: '人工纳入', included_override: '人工覆盖纳入', excluded: '已排除'
  } as Record<string, string>)[status] || status
}

function qualityStatusClass(status: string) {
  if (['eligible', 'included'].includes(status)) return 'bg-success-subtle text-success-emphasis'
  if (status === 'included_override' || status === 'review_required') return 'bg-warning-subtle text-warning-emphasis'
  return 'bg-danger-subtle text-danger-emphasis'
}

function openQualityDecision(item: RunQuality, decision: 'automatic' | 'included' | 'excluded') {
  qualityDecisionTarget.value = item
  qualityDecision.value = decision
  qualityReason.value = decision === 'automatic' ? '' : item.decision_reason
}

async function saveQualityDecision() {
  const target = qualityDecisionTarget.value
  if (!target) return
  if (qualityDecision.value !== 'automatic' && qualityReason.value.trim().length < 5) {
    notify('请填写至少 5 个字的纳入或排除依据', 'warning')
    return
  }
  qualitySaving.value = true
  try {
    const updated = (await researchApi.decideRunQuality(
      target.run_id,
      qualityDecision.value,
      qualityReason.value.trim()
    )).data
    const index = qualityRuns.value.findIndex(item => item.run_id === updated.run_id)
    if (index >= 0) qualityRuns.value[index] = updated
    qualityDecisionTarget.value = null
    notify('研究纳入决策已保存并记录审计日志', 'success')
    await loadPage()
  } catch (error) {
    notify(error instanceof Error ? error.message : '质量决策保存失败', 'danger')
  } finally {
    qualitySaving.value = false
  }
}

function orderedIds(code: 'AB' | 'BA') {
  const ids = taskOrders.value?.tasks.map(task => task.id) ?? []
  return code === 'AB' ? ids : [...ids].reverse()
}

function orderLabel(code: string) {
  const tasks = taskOrders.value?.tasks ?? []
  if (tasks.length !== 2) return code
  return code === 'BA'
    ? `BA：${tasks[1].title} → ${tasks[0].title}`
    : `AB：${tasks[0].title} → ${tasks[1].title}`
}

async function setOrder(student: TaskOrderStudent, code: 'AB' | 'BA') {
  assigningId.value = student.user_id
  errorMessage.value = ''
  try {
    const response = await researchApi.setTaskOrder(student.user_id, orderedIds(code))
    const index = taskOrders.value?.students.findIndex(item => item.user_id === student.user_id) ?? -1
    if (taskOrders.value && index >= 0) taskOrders.value.students[index] = response.data
    successMessage.value = student.has_in_progress_run
      ? `${student.name} 已分配 ${code}；其进行中测评保持原顺序，下次测评生效。`
      : `${student.name} 已分配 ${code} 顺序。`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '任务顺序分配失败'
  } finally {
    assigningId.value = ''
  }
}

function onOrderChange(student: TaskOrderStudent, event: Event) {
  const code = (event.target as HTMLSelectElement).value
  if (code === 'AB' || code === 'BA') void setOrder(student, code)
}

async function balanceSelected() {
  if (!selectedStudents.value.length) return
  const studentIds = [...selectedStudents.value]
  balancing.value = true
  errorMessage.value = ''
  try {
    await researchApi.balanceTaskOrders(studentIds)
    await loadTaskOrderPage()
    successMessage.value = `已为 ${studentIds.length} 名学生完成 AB/BA 平衡分配。`
    selectedStudents.value = []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '平衡分配失败'
  } finally {
    balancing.value = false
  }
}

async function analyze(runId: string) {
  if (reportActionsBusy.value) return
  generatedDraftRunId.value = ''
  analyzingId.value = runId
  analysisErrorMsg.value = ''
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const response = await researchApi.startAnalysis(runId, false, undefined, (job) => {
      analysisProgress.value = { ...analysisProgress.value, [runId]: job.progress }
    })
    if (response.data.status !== 'completed') {
      const err = response.data.error_message || '报告生成未完成，请检查模型服务与转录数据'
      analysisErrorMsg.value = err
      notify(`测评分析失败：${err}`, 'danger')
      throw new Error(err)
    }
    notify('测评分析完成，已生成元认知画像报告草稿！', 'success')
    successMessage.value = '测评分析完成，报告草稿已生成。'
    generatedDraftRunId.value = runId
    await loadPage()
  } catch (error) {
    const msg = error instanceof Error ? error.message : '分析任务失败'
    analysisErrorMsg.value = msg
    errorMessage.value = msg
    notify(msg, 'danger')
  } finally {
    analyzingId.value = ''
    delete analysisProgress.value[runId]
  }
}

async function batchAnalyzeAll() {
  const pendingList = [...(dashboard.value?.unanalyzed_runs ?? [])]
  if (!pendingList.length || reportActionsBusy.value || dashboardLoading.value || dashboardError.value) return
  const confirmed = await confirmAction({
    title: `批量生成 ${pendingList.length} 份报告`,
    message: `仅处理当前第 ${pendingPage.value} 页的 ${pendingList.length} 份完整测评，其他页不会生成。将依据转录、编码及问卷数据逐份生成报告草稿，是否继续？`,
    confirmText: '开始批量生成',
    tone: 'primary'
  })
  if (!confirmed || reportActionsBusy.value) return
  batchAnalyzing.value = true
  stopReportRefresh.value = false
  batchAnalyzeProgress.value = { current: 0, total: pendingList.length }
  analysisErrorMsg.value = ''
  let successCount = 0
  let failCount = 0
  for (const item of pendingList) {
    if (stopReportRefresh.value) break
    batchAnalyzeProgress.value.current++
    analyzingId.value = item.run_id
    try {
      const response = await researchApi.startAnalysis(item.run_id, false, undefined, (job) => {
        analysisProgress.value = { ...analysisProgress.value, [item.run_id]: job.progress }
      })
      if (response.data.status === 'completed') {
        successCount++
      } else {
        failCount++
      }
    } catch {
      failCount++
    } finally {
      delete analysisProgress.value[item.run_id]
    }
  }
  analyzingId.value = ''
  batchAnalyzing.value = false
  notify(`批量分析完成：成功 ${successCount} 份${failCount ? `，失败 ${failCount} 份` : ''}`, failCount ? 'warning' : 'success')
  await loadPage()
}

async function exportData(kind: 'csv' | 'bundle') {
  exporting.value = kind
  exportCancelRequested.value = false
  exportStatusMessage.value = kind === 'bundle' ? '正在创建导出任务…' : '正在生成问卷答题矩阵…'
  exportProgress.value = 0
  errorMessage.value = ''
  try {
    let response = kind === 'bundle'
      ? await researchApi.createAudioTranscriptExport(
          exportMode.value,
          true,
          exportMode.value !== 'accepted_only' && exportIncludeAudio.value
        )
      : await researchApi.createExport()
    if (exportCancelRequested.value) return
    if (kind === 'bundle') {
      exportStatusMessage.value = '导出任务已进入队列，可以继续使用其他功能。'
      exportProgress.value = response.data.progress || 0
      while (['queued', 'preparing', 'running'].includes(response.data.status)) {
        if (exportCancelRequested.value) break
        await new Promise(resolve => window.setTimeout(resolve, 2_000))
        if (exportCancelRequested.value) break
        response = await researchApi.getExportStatus(response.data.id)
        exportProgress.value = response.data.progress || 0
        exportStatusMessage.value = response.data.status === 'queued'
          ? '正在排队等待导出…'
          : response.data.status === 'preparing'
            ? exportMode.value === 'accepted_only'
              ? '正在准备已接受候选和用户信息…'
              : exportIncludeAudio.value
                ? '正在准备用户、转录和录音清单…'
                : '正在准备用户、转录和候选文本…'
            : exportMode.value === 'accepted_only'
              ? '正在生成已接受候选轻量数据包…'
            : exportProgress.value >= 70
              ? exportIncludeAudio.value
                ? '正在写入录音压缩包…'
                : '正在写入转录与候选文本包…'
              : '正在整理研究数据…'
      }
    }
    if (exportCancelRequested.value) return
    if (response.data.status !== 'completed') {
      throw new Error(response.data.error_message || '导出任务失败')
    }
    exportStatusMessage.value = '文件已生成，正在启动流式下载…'
    exportProgress.value = 100
    const ticket = await researchApi.downloadExport(response.data.id)
    const link = document.createElement('a')
    link.href = ticket.data.url
    link.download = ticket.data.filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    if (kind === 'bundle') {
      successMessage.value = exportMode.value === 'accepted_only'
        ? `已接受候选数据包已生成，共包含 ${response.data.row_count} 条人工接受内容。`
        : `${exportIncludeAudio.value ? '录音与转录' : '转录与候选文本'}实名数据包已生成，共包含 ${response.data.row_count} 个任务会话。`
    } else {
      successMessage.value = `问卷答题矩阵已导出，共 ${response.data.row_count} 次完整测评；每行对应一次测评，每道题各占一列。`
    }
  } catch (error) {
    if (!exportCancelRequested.value) {
      errorMessage.value = error instanceof Error ? error.message : '研究数据导出失败'
    }
  } finally {
    exporting.value = ''
    exportStatusMessage.value = ''
    exportProgress.value = 0
    exportCancelRequested.value = false
  }
}

function cancelExport() {
  exportCancelRequested.value = true
}

async function openBundleExportDialog() {
  exportDialogOpen.value = true
  await loadBundleExportPreview()
}

async function loadBundleExportPreview() {
  const requestId = ++exportPreviewRequestId
  exportPreviewLoading.value = true
  exportPreview.value = null
  try {
    const includeAudio = exportMode.value !== 'accepted_only' && exportIncludeAudio.value
    const preview = (await researchApi.previewAudioTranscriptExport(includeAudio)).data
    if (requestId === exportPreviewRequestId) exportPreview.value = preview
  } catch (error) {
    if (requestId === exportPreviewRequestId) {
      errorMessage.value = error instanceof Error ? error.message : '导出范围预检失败'
      exportDialogOpen.value = false
    }
  } finally {
    if (requestId === exportPreviewRequestId) exportPreviewLoading.value = false
  }
}

function startBundleExport() {
  exportDialogOpen.value = false
  void exportData('bundle')
}

watch(exportIncludeAudio, () => {
  if (exportDialogOpen.value && exportMode.value !== 'accepted_only') {
    void loadBundleExportPreview()
  }
})

onMounted(loadPage)
</script>

<template>
  <div class="teacher-page">
    <div class="teacher-page-header ds-page-header">
      <div class="teacher-page-heading ds-page-heading">
        <p class="ds-eyebrow">研究运营</p>
        <h3 class="mb-1">{{ pageTitle }}</h3>
        <p class="text-muted mb-0">跟进测评、双人编码、报告发布和受控研究数据导出。</p>
      </div>
      <button
        class="btn btn-sm btn-outline-primary export-toggle"
        type="button"
        :aria-expanded="exportExpanded"
        aria-controls="research-export-actions"
        @click="exportExpanded = !exportExpanded"
      >
        <i class="bi bi-download me-1" />
        研究数据导出
        <i class="bi ms-auto" :class="exportExpanded ? 'bi-chevron-up' : 'bi-chevron-down'" />
      </button>
      <div
        id="research-export-actions"
        class="export-actions"
        :class="{ 'is-expanded': exportExpanded }"
        aria-label="研究数据导出"
      >
        <button
          class="btn btn-outline-primary export-button"
          title="导出问卷答题矩阵：每行对应一名参与者的一次完整测评，每道题各占一列，并包含问卷填写姓名、实验路径或微信名"
          :disabled="Boolean(exporting)"
          :aria-busy="exporting === 'csv'"
          @click="exportData('csv')"
        >
          <span v-if="exporting === 'csv'" class="spinner-border spinner-border-sm" />
          <i v-else class="bi bi-filetype-csv export-button-icon" />
          <span>
            <strong>{{ exporting === 'csv' ? '正在生成问卷矩阵' : '导出问卷答题矩阵' }}</strong>
            <small>CSV · 每行一次完整测评，每题一列</small>
          </span>
        </button>
        <button
          class="btn btn-primary export-button"
          title="导出中文目录数据包：用户信息、原转录、AI筛选和人工校对文本；可选择是否包含 WAV 原始录音"
          :disabled="Boolean(exporting)"
          :aria-busy="exporting === 'bundle'"
          @click="openBundleExportDialog"
        >
          <span v-if="exporting === 'bundle'" class="spinner-border spinner-border-sm" />
          <i v-else class="bi bi-file-earmark-zip export-button-icon" />
          <span>
            <strong>{{ exporting === 'bundle' ? '正在生成研究数据包' : '导出转录与可选录音' }}</strong>
            <small>ZIP · 选择范围，并决定是否包含录音</small>
          </span>
        </button>
        <div
          v-if="exporting"
          class="export-progress"
          role="status"
          aria-live="polite"
        >
          <span class="spinner-border spinner-border-sm" aria-hidden="true" />
          <div class="flex-grow-1">
            <span>{{ exportStatusMessage }}</span>
            <div v-if="exporting === 'bundle'" class="progress mt-2" role="progressbar" :aria-valuenow="exportProgress" aria-valuemin="0" aria-valuemax="100">
              <div class="progress-bar" :style="{ width: `${exportProgress}%` }">{{ exportProgress }}%</div>
            </div>
          </div>
          <button
            class="btn btn-sm btn-outline-secondary flex-shrink-0"
            type="button"
            @click="cancelExport"
          >取消</button>
        </div>
        <p class="export-privacy-note mb-0">
          <i class="bi bi-shield-lock me-1" />
          导出包含姓名与账号，仅限获授权研究人员使用。
        </p>
      </div>
    </div>

    <div v-if="errorMessage" class="alert alert-danger">{{ errorMessage }}</div>
    <div v-if="sectionErrors.length" class="alert alert-warning d-flex justify-content-between align-items-center gap-3">
      <span><i class="bi bi-exclamation-triangle me-2" />{{ sectionErrors.join('、') }}暂时加载失败，其他分区仍可正常使用。</span>
      <button class="btn btn-sm btn-outline-warning flex-shrink-0" type="button" @click="loadPage">重试</button>
    </div>
    <div v-if="successMessage" class="alert alert-success d-flex flex-wrap align-items-center gap-2">{{ successMessage }}<RouterLink v-if="generatedDraftRunId" :to="{ path: '/report-review', query: { run: generatedDraftRunId } }" class="btn btn-sm btn-outline-success">查看新生成草稿</RouterLink></div>
    <div v-if="dashboardError" class="alert alert-danger" role="alert">报告列表加载失败：{{ dashboardError }} <button type="button" class="btn btn-sm btn-outline-danger" @click="loadDashboardPage">重试</button></div>
    <div v-if="ordersError && !taskOrders" class="alert alert-danger" role="alert">任务顺序加载失败：{{ ordersError }} <button type="button" class="btn btn-sm btn-outline-danger" @click="loadTaskOrderPage">重试</button></div>

    <div v-if="isLoading" class="card border-0 shadow-sm">
      <div class="card-body py-5 text-center"><div class="spinner-border text-primary" /></div>
    </div>

    <template v-else>
      <div v-if="dashboard" class="row g-3">
        <div class="col-6 col-xl-3">
          <div class="metric-card"><span>完整测评</span><strong>{{ dashboard.completed_runs }}</strong></div>
        </div>
        <div class="col-6 col-xl-3">
          <div class="metric-card"><span>待复核编码</span><strong>{{ dashboard.review_pending }}</strong></div>
        </div>
        <div class="col-6 col-xl-3">
          <div class="metric-card"><span>待审阅草稿</span><strong>{{ dashboard.publishable }}</strong></div>
        </div>
        <div class="col-6 col-xl-3">
          <div class="metric-card"><span>已发布报告</span><strong>{{ dashboard.published }}</strong></div>
        </div>
      </div>

      <div v-if="dashboard" class="work-queue mt-3">
        <RouterLink to="/transcripts" class="work-item" :class="{ urgent: transcriptAttention }">
          <i class="bi bi-soundwave" /><span><strong>{{ transcriptAttention }}</strong><small>转录异常</small></span><i class="bi bi-chevron-right" />
        </RouterLink>
        <RouterLink to="/review" class="work-item" :class="{ urgent: codingAssignments }">
          <i class="bi bi-person-check" /><span><strong>{{ codingAssignments }}</strong><small>我的盲编待办</small></span><i class="bi bi-chevron-right" />
        </RouterLink>
        <RouterLink to="/review" class="work-item" :class="{ urgent: codingDisagreements }">
          <i class="bi bi-intersect" /><span><strong>{{ codingDisagreements }}</strong><small>待仲裁分歧</small></span><i class="bi bi-chevron-right" />
        </RouterLink>
        <a href="#pending-analysis" class="work-item" :class="{ urgent: dashboard.unanalyzed_total }">
          <i class="bi bi-file-earmark-bar-graph" /><span><strong>{{ dashboard.unanalyzed_total }}</strong><small>待生成报告</small></span><i class="bi bi-chevron-right" />
        </a>
      </div>

      <MacroAnalyticsDashboard v-if="dashboard" :user-role="userStore.profile.role === 'admin' ? 'admin' : 'teacher'" :class-groups="macroClassGroups" />

      <section v-if="dashboard" class="card border-0 shadow-sm mt-4 quality-workbench">
        <div class="card-body p-4">
          <div class="quality-header">
            <div>
              <h5 class="mb-1">研究数据质量工作台</h5>
              <p class="text-muted small mb-0">正式分析前自动检查双任务、录音、权威转录和问卷完整性；人工覆盖必须填写依据。</p>
            </div>
            <div class="quality-summary">
              <span class="is-ready">{{ dashboard.quality.eligible }} 可纳入</span>
              <span class="is-warning">{{ dashboard.quality.review_required }} 待复核</span>
              <span class="is-danger">{{ dashboard.quality.ineligible + dashboard.quality.excluded }} 不纳入</span>
            </div>
          </div>
          <div class="quality-toolbar mt-3">
            <input v-model="qualitySearch" class="form-control form-control-sm" type="search" placeholder="查找姓名、账号或班级" />
            <select v-model="qualityFilter" class="form-select form-select-sm">
              <option value="attention">仅待处理</option><option value="">全部状态</option>
              <option value="eligible">自动通过</option><option value="review_required">需要复核</option>
              <option value="ineligible">暂不可纳入</option><option value="included_override">人工覆盖纳入</option><option value="excluded">已排除</option>
            </select>
          </div>
          <div class="table-responsive quality-table-wrap mt-3">
            <p v-if="qualityLoading" role="status" class="text-muted py-3">正在加载数据质量记录…</p>
            <div v-else-if="qualityError" class="alert alert-danger" role="alert">{{ qualityError }} <button class="btn btn-sm btn-outline-danger" @click="loadQualityPage">重试</button></div>
            <table v-else class="table align-middle mb-0 mobile-card-table quality-mobile-table">
              <thead><tr><th>学生</th><th>自动检查</th><th>研究状态</th><th>问题定位</th><th class="text-end">决策</th></tr></thead>
              <tbody>
                <tr v-for="item in qualityRuns" :key="item.run_id">
                  <td data-label="学生"><strong>{{ item.name }}</strong><small class="d-block text-muted">{{ item.username }} · {{ item.class_group || '未分班' }}</small></td>
                  <td data-label="自动检查"><span class="badge" :class="item.automatic_status === 'passed' ? 'bg-success-subtle text-success-emphasis' : item.automatic_status === 'warning' ? 'bg-warning-subtle text-warning-emphasis' : 'bg-danger-subtle text-danger-emphasis'">{{ item.automatic_status === 'passed' ? '通过' : item.automatic_status === 'warning' ? '有警告' : '未通过' }}</span></td>
                  <td data-label="研究状态"><span class="badge" :class="qualityStatusClass(item.effective_status)">{{ qualityStatusLabel(item.effective_status) }}</span><small v-if="item.reviewed_by_name" class="d-block text-muted mt-1">{{ item.reviewed_by_name }}</small></td>
                  <td class="quality-issues" data-label="问题定位">
                    <span v-for="check in item.checks.filter(check => check.status !== 'pass')" :key="check.key" :class="check.status">{{ check.label }}：{{ check.message }}</span>
                    <span v-if="item.checks.every(check => check.status === 'pass')" class="pass">全部自动检查通过</span>
                  </td>
                  <td class="text-end" data-label="决策">
                    <div class="quality-actions">
                      <button class="btn btn-sm btn-outline-success" @click="openQualityDecision(item, 'included')">纳入</button>
                      <button class="btn btn-sm btn-outline-danger" @click="openQualityDecision(item, 'excluded')">排除</button>
                      <button v-if="item.decision !== 'automatic'" class="btn btn-sm btn-light" @click="openQualityDecision(item, 'automatic')">恢复自动</button>
                    </div>
                  </td>
                </tr>
                <tr v-if="!qualityRuns.length"><td colspan="5" class="text-center text-muted py-4">没有符合当前条件的测评</td></tr>
              </tbody>
            </table>
          </div>
          <SectionPagination v-model:page="qualityPage" v-model:page-size="qualityPageSize" :total="qualityTotal" :disabled="qualityLoading || qualitySaving" label="数据质量" />
        </div>
      </section>

      <div v-if="taskOrders" class="card border-0 shadow-sm mt-4">
        <div class="card-body p-4">
          <div class="d-flex flex-wrap justify-content-between align-items-start gap-3 mb-3">
            <div>
              <h5 class="mb-1">任务顺序分配</h5>
              <p class="text-muted small mb-0">
                标准协议只定义任务 A/B；可手动指定，也可将所选学生自动平衡到 AB、BA 两组。
              </p>
            </div>
            <button
              class="btn btn-primary btn-sm"
              :disabled="!selectedStudents.length || balancing || ordersLoading || !!ordersError"
              @click="balanceSelected"
            >
              <span v-if="balancing" class="spinner-border spinner-border-sm me-1" />
              平衡分配本页所选（{{ selectedStudents.length }}）
            </button>
          </div>
          <div class="order-legend mb-3">
            <span><strong>AB</strong> {{ orderLabel('AB').replace('AB：', '') }}</span>
            <span><strong>BA</strong> {{ orderLabel('BA').replace('BA：', '') }}</span>
          </div>
          <div class="order-search mb-3">
            <input v-model="taskOrderSearch" class="form-control form-control-sm" type="search" placeholder="查找姓名、账号或班级" />
            <span class="text-muted small">翻页或筛选后清空本页勾选</span>
          </div>
          <div class="table-responsive">
            <p v-if="ordersLoading" role="status" class="text-muted py-3">正在加载任务顺序…</p>
            <div v-else-if="ordersError" class="alert alert-danger" role="alert">{{ ordersError }} <button class="btn btn-sm btn-outline-danger" @click="loadTaskOrderPage">重试</button></div>
            <table v-else class="table align-middle mb-0 mobile-card-table order-mobile-table">
              <thead>
                <tr><th class="selection-cell"></th><th>学生</th><th>班级</th><th>当前分配</th><th>生效说明</th></tr>
              </thead>
              <tbody>
                <tr v-for="student in taskOrders.students" :key="student.user_id">
                  <td data-label="选择">
                    <input
                      v-model="selectedStudents"
                      class="form-check-input"
                      type="checkbox"
                      :value="student.user_id"
                    >
                  </td>
                  <td data-label="学生">
                    <strong>{{ student.name }}</strong>
                    <small class="d-block text-muted">{{ student.username }}</small>
                  </td>
                  <td data-label="班级">{{ student.class_group || '未分班' }}</td>
                  <td data-label="当前分配">
                    <select
                      class="form-select form-select-sm order-select"
                      :value="student.order_code"
                      :disabled="assigningId === student.user_id"
                      @change="onOrderChange(student, $event)"
                    >
                      <option value="AB">{{ orderLabel('AB') }}</option>
                      <option value="BA">{{ orderLabel('BA') }}</option>
                    </select>
                  </td>
                  <td data-label="生效说明">
                    <span v-if="student.has_in_progress_run" class="badge bg-warning-subtle text-warning-emphasis">
                      下次测评生效
                    </span>
                    <span v-else class="badge bg-success-subtle text-success-emphasis">新测评立即生效</span>
                  </td>
                </tr>
                <tr v-if="!taskOrders.students.length">
                  <td colspan="5" class="text-center text-muted py-4">当前没有可管理的学生</td>
                </tr>
              </tbody>
            </table>
          </div>
          <SectionPagination v-model:page="taskOrderPage" v-model:page-size="taskOrderPageSize" :total="taskOrders.total" :disabled="ordersLoading || balancing || !!assigningId" label="任务顺序" />
        </div>
      </div>

      <div class="row g-4 mt-1">
        <div v-if="dashboard" class="col-12">
          <div class="card border-0 shadow-sm h-100">
            <div class="card-body p-4">
              <div class="d-flex flex-wrap gap-3 justify-content-between align-items-center mb-3">
                <div>
                  <h5 class="mb-1">最近报告</h5>
                  <small class="text-muted">按报告最近生成时间倒序排列。未发布草稿可重新 AI 分析；成功后更新生成时间，并需重新审阅。</small>
                </div>
                <div class="d-flex flex-wrap gap-2">
                  <button type="button" class="btn btn-sm btn-outline-secondary" :disabled="reportActionsBusy || dashboardLoading" @click="loadDashboardPage">刷新列表</button>
                  <button type="button" class="btn btn-sm btn-primary" :disabled="reportActionsBusy || dashboardLoading || !!dashboardError || !selectedReports.length" @click="reanalyzeReports()">重新 AI 分析所选（{{ selectedReports.length }}）</button>
                </div>
              </div>
              <p class="small text-muted">勾选仅作用于当前页，翻页后清空选择。报告审阅与发布请进入“查看草稿”；已发布和已归档报告不参与重新分析。</p>
              <ReportGenerationJobs @completed="loadDashboardPage" />
              <div v-if="refreshingReports" class="alert alert-info" role="status" aria-live="polite">
                <span class="spinner-border spinner-border-sm me-2" />已处理 {{ reportRefreshProgress.completed }} / {{ reportRefreshProgress.total }} 份，当前报告正在 AI 分析，请保持页面打开。
                <button type="button" class="btn btn-sm btn-outline-secondary ms-2" :disabled="stopReportRefresh" @click="stopReportRefresh = true">{{ stopReportRefresh ? '当前报告完成后停止' : '停止后续任务' }}</button>
              </div>
              <details v-if="reportRefreshResults.length" class="mb-3" open>
                <summary>本次处理结果：成功 {{ reportRefreshResults.filter(item => item.success).length }} 份，失败 {{ reportRefreshResults.filter(item => !item.success).length }} 份</summary>
                <ul class="small mt-2 mb-0 report-refresh-results"><li v-for="result in reportRefreshResults" :key="result.id" :class="result.success ? 'text-success' : 'text-danger'">{{ result.name }}：{{ result.message }}</li></ul>
              </details>
              <div v-if="dashboardError" class="alert alert-danger" role="alert">{{ dashboardError }} <button type="button" class="btn btn-sm btn-outline-danger" :disabled="reportActionsBusy || dashboardLoading" @click="loadDashboardPage">重试加载</button></div>
              <div class="table-responsive">
                <p v-if="dashboardLoading" role="status" class="text-muted py-3">正在加载报告…</p>
                <table v-else-if="!dashboardError" class="table align-middle mobile-card-table report-mobile-table">
                  <thead><tr>
                    <th><input type="checkbox" class="form-check-input" aria-label="选择本页全部可重新分析的草稿" :checked="allReportsSelected" :indeterminate="selectedReports.length > 0 && !allReportsSelected" :disabled="reportActionsBusy || !selectableReports.length" @change="toggleReportSelection"></th>
                    <th>学生信息</th><th>生成时间 ↓</th><th>报告状态</th><th>发布检查</th><th class="text-end">操作</th>
                  </tr></thead>
                  <tbody>
                    <tr v-for="item in dashboard.recent_reports" :key="item.id">
                      <td data-label="选择"><input v-if="canReanalyzeReport(item)" v-model="selectedReports" type="checkbox" class="form-check-input" :value="item.id" :aria-label="`选择 ${item.user_name} 的报告草稿`" :disabled="reportActionsBusy"><span v-else class="text-muted">—</span></td>
                      <td data-label="学生信息"><strong>{{ item.user_name }}</strong><small class="d-block text-muted font-monospace">{{ item.username || '账号未提供' }}</small></td>
                      <td data-label="生成时间"><span>{{ exportTime(item.generated_at) }}</span><small class="d-block text-muted">报告版本 V{{ item.version_no }}</small></td>
                      <td data-label="报告状态"><span class="badge" :class="refreshingReportId === item.id ? 'bg-info-subtle text-info-emphasis' : reportStatusClass(item.status)">{{ refreshingReportId === item.id ? '正在重新 AI 分析' : reportStatusLabel(item.status) }}</span></td>
                      <td data-label="发布检查" class="report-checks-cell"><small>{{ reportChecksText(item) }}</small></td>
                      <td class="text-end" data-label="操作">
                        <div class="d-flex flex-wrap justify-content-end gap-2">
                          <RouterLink v-if="!refreshingReports" :to="{ path: '/report-review', query: { id: item.id } }" class="btn btn-sm btn-outline-primary">{{ ['published', 'archived'].includes(item.status) ? '查看报告' : '查看草稿' }}</RouterLink>
                          <button v-else type="button" class="btn btn-sm btn-outline-secondary" disabled>等待本次处理完成</button>
                          <button v-if="canReanalyzeReport(item)" type="button" class="btn btn-sm btn-outline-primary" :disabled="reportActionsBusy" @click="reanalyzeReports(item)"><span v-if="refreshingReportId === item.id" class="spinner-border spinner-border-sm me-1" />重新 AI 分析</button>
                        </div>
                      </td>
                    </tr>
                    <tr v-if="!dashboard.recent_reports.length">
                      <td colspan="6" class="text-center text-muted py-4">暂无报告</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <SectionPagination v-model:page="reportsPage" v-model:page-size="reportsPageSize" :total="dashboard.reports" :disabled="dashboardLoading || reportActionsBusy" label="最近报告" />
            </div>
          </div>
        </div>

        <div v-if="analytics" class="col-12">
          <div class="card border-0 shadow-sm h-100">
            <div class="card-body p-4">
              <h5>基础研究指标</h5>
              <p class="text-muted small">仅使用通过质量门槛或经人工确认纳入的 {{ analytics.quality.included_run_count }} / {{ analytics.quality.completed_run_count }} 份完整测评。</p>
              <div class="research-metric"><span>双人编码片段</span><strong>{{ analytics.agreement.double_coded_segments }}</strong></div>
              <div class="research-metric"><span>人际维度一致率</span><strong>{{ agreementText }}</strong></div>
              <div class="research-metric"><span>人际 Cohen κ</span><strong>{{ metric(analytics.agreement.cohen_kappa) }}</strong></div>
              <div class="research-metric"><span>人机比较片段</span><strong>{{ analytics.agreement.human_ai_segments }}</strong></div>
              <div class="research-metric"><span>人机 Cohen κ</span><strong>{{ metric(analytics.agreement.human_ai_cohen_kappa) }}</strong></div>
              <div class="research-metric"><span>人机频次 Pearson r</span><strong>{{ metric(analytics.agreement.human_ai_frequency_pearson_r) }}</strong></div>
              <div class="research-metric"><span>人机频次 MAE</span><strong>{{ metric(analytics.agreement.human_ai_frequency_mae) }}</strong></div>
              <div class="table-responsive mt-3">
                <table class="table table-sm align-middle metric-table mb-0">
                  <thead>
                    <tr>
                      <th>人机分维度</th>
                      <th class="text-end">样本</th>
                      <th class="text-end">精确率</th>
                      <th class="text-end">召回率</th>
                      <th class="text-end">F1</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="(item, dimension) in analytics.agreement.human_ai_by_dimension"
                      :key="dimension"
                    >
                      <td>{{ dimensionLabels[dimension] || dimension }}</td>
                      <td class="text-end">{{ item.support }}</td>
                      <td class="text-end">{{ ratio(item.precision) }}</td>
                      <td class="text-end">{{ ratio(item.recall) }}</td>
                      <td class="text-end">{{ metric(item.f1) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <hr>
              <div class="research-metric"><span>完整问卷样本</span><strong>{{ analytics.questionnaire.complete_sample_size }}</strong></div>
              <div class="research-metric"><span>题目数量</span><strong>{{ analytics.questionnaire.item_count }}</strong></div>
              <div class="reliability-result" :class="reliabilityPresentation.tone">
                <div class="research-metric border-0 pb-1">
                  <span>Cronbach α</span><strong>{{ reliabilityPresentation.value }}</strong>
                </div>
                <small>{{ reliabilityPresentation.detail }}</small>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div id="pending-analysis" v-if="dashboard" class="card border-0 shadow-sm mt-4 pending-analysis-card">
        <div class="card-body p-4">
          <div class="d-flex flex-wrap justify-content-between align-items-center gap-3 mb-3">
            <div>
              <div class="d-flex align-items-center gap-2">
                <span class="badge bg-warning-subtle text-warning-emphasis">待处理</span>
                <h5 class="mb-0">待生成报告的完整测评（共 {{ dashboard.unanalyzed_total }} 份）</h5>
              </div>
              <p class="text-muted small mb-0 mt-1">学生已完成作答并通过质量核验；点击“生成报告草稿”将依据转录、编码及问卷数据生成报告，不会自动发布。</p>
            </div>
            <button
              class="btn btn-sm btn-primary"
              :disabled="reportActionsBusy || dashboardLoading || !!dashboardError || !dashboard.unanalyzed_runs.length"
              @click="batchAnalyzeAll"
            >
              <span v-if="batchAnalyzing" class="spinner-border spinner-border-sm me-1" />
              <i v-else class="bi bi-play-circle me-1" />
              {{ batchAnalyzing ? `正在批量分析 (${batchAnalyzeProgress.current}/${batchAnalyzeProgress.total})…` : `生成本页 ${dashboard.unanalyzed_runs.length} 份报告` }}
            </button>
          </div>

          <div v-if="analysisErrorMsg" class="alert alert-danger d-flex align-items-center justify-content-between gap-3 mb-3">
            <div>
              <i class="bi bi-exclamation-triangle-fill me-2" />
              <strong>分析失败：</strong>{{ analysisErrorMsg }}
            </div>
            <button class="btn btn-sm btn-outline-danger" @click="analysisErrorMsg = ''">关闭提示</button>
          </div>

          <div class="table-responsive">
            <p v-if="dashboardLoading" role="status" class="text-muted py-3">正在加载待生成记录…</p>
            <table v-else-if="!dashboardError" class="table align-middle mb-0 mobile-card-table">
              <thead>
                <tr>
                  <th>学生信息</th>
                  <th>测评任务</th>
                  <th>完成时间</th>
                  <th class="text-end">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="!dashboard.unanalyzed_runs.length"><td colspan="4" class="text-center text-muted py-4">暂无待生成报告的完整测评</td></tr>
                <tr v-for="item in dashboard.unanalyzed_runs" :key="item.run_id">
                  <td data-label="学生信息">
                    <div class="d-flex align-items-center gap-2">
                      <span class="user-avatar-badge">{{ (item.user_name || '学')[0] }}</span>
                      <div>
                        <strong>{{ item.user_name || '未知学生' }}</strong>
                        <small class="d-block text-muted">{{ item.username }} · {{ item.class_group || '未分班' }}</small>
                      </div>
                    </div>
                  </td>
                  <td data-label="测评任务">
                    <div v-if="item.tasks?.length" class="task-flow-tags">
                      <span v-for="(t, idx) in item.tasks" :key="t.task_id" class="task-tag">
                        <small class="text-muted me-1">任务{{ t.sequence_no || idx + 1 }}:</small>{{ t.title }}
                      </span>
                    </div>
                    <span v-else class="text-muted small">标准出声思维双任务</span>
                  </td>
                  <td data-label="完成时间">
                    <span class="small text-muted"><i class="bi bi-clock-history me-1" />{{ exportTime(item.completed_at) || '刚刚' }}</span>
                  </td>
                  <td class="text-end" data-label="操作">
                    <button
                      class="btn btn-sm btn-outline-primary"
                      :disabled="reportActionsBusy || isGenerating(item)"
                      @click="analyze(item.run_id)"
                    >
                      <span v-if="isGenerating(item)" class="spinner-border spinner-border-sm me-1" />
                      <i v-else class="bi bi-cpu me-1" />
                      {{ isGenerating(item) ? `生成中 ${generationProgressFor(item)}%` : '生成报告草稿' }}
                    </button>
                    <div v-if="isGenerating(item)" class="mt-2 text-start">
                      <progress
                        :value="generationProgressFor(item)"
                        max="100"
                        class="w-100"
                        :aria-label="`报告生成进度 ${generationProgressFor(item)}%`"
                      />
                      <small class="text-muted d-block mt-1">
                        {{ activeJobFor(item)?.status === 'queued' ? '排队中' : 'AI 生成中' }}
                        <span v-if="activeJobFor(item)?.error_message"> · {{ activeJobFor(item)?.error_message }}</span>
                      </small>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <SectionPagination v-model:page="pendingPage" v-model:page-size="pendingPageSize" :total="dashboard.unanalyzed_total" :disabled="dashboardLoading || batchAnalyzing || !!analyzingId" label="待生成报告" />
        </div>
      </div>
    </template>

    <!-- 导出数据范围弹窗 -->
    <AppModal
      :open="exportDialogOpen"
      max-width="520px"
      @close="exportDialogOpen = false"
    >
      <template #header>
        <div>
          <p class="ds-eyebrow mb-1">转录、候选与可选录音</p>
          <h5 class="mb-1" id="export-dialog-title">选择导出范围</h5>
          <p class="text-muted small mb-0">系统会先核对候选片段的人工复核进度，再生成压缩包。</p>
        </div>
      </template>

      <div v-if="exportPreviewLoading" class="export-review-check is-loading" aria-live="polite">
        <span class="spinner-border spinner-border-sm" />正在核对人工复核进度…
      </div>
      <div v-else-if="exportPreview" class="export-review-check" :class="exportPreview.review_complete ? 'is-complete' : 'is-warning'">
        <i class="bi" :class="exportPreview.review_complete ? 'bi-check-circle-fill' : 'bi-exclamation-triangle-fill'" />
        <div>
          <strong>{{ exportPreview.review_complete ? '人工复核已全部完成' : (exportPreview.candidate_total ? '人工复核尚未完全完成' : '目前尚无可复核候选') }}</strong>
          <p v-if="exportPreview.candidate_total" class="mb-0">当前最新抽取版本共 {{ exportPreview.candidate_total }} 条：累计已接受 {{ exportPreview.accepted_count }}、累计已排除 {{ exportPreview.rejected_count }}、待复核 {{ exportPreview.pending_count }}。</p>
          <p v-if="exportPreview.sessions_without_candidates" class="mb-0">另有 {{ exportPreview.sessions_without_candidates }} 个已完成任务尚未生成候选内容。</p>
          <small v-if="!exportPreview.review_complete">仍可导出，但当前包不能视为最终人工复核版本；点击下方按钮即表示确认继续。</small>
        </div>
      </div>
      <div v-if="exportMode !== 'accepted_only' && exportPreview?.previous_export_at" class="previous-export-note" :class="{ 'is-incomplete': exportPreview.previous_review_complete === false }">
        <i class="bi bi-clock-history" />
        <span v-if="exportPreview.previous_review_complete === false">检测到 {{ exportTime(exportPreview.previous_export_at) }} 的上次{{ exportIncludeAudio ? '含录音' : '文本' }}导出发生在人工复核未完成时；可选择“仅新增”补导之后新复核的内容，也可重新导出全部。</span>
        <span v-else-if="exportPreview.previous_review_complete === true">上次符合当前{{ exportIncludeAudio ? '含录音' : '不含录音' }}条件的导出时间：{{ exportTime(exportPreview.previous_export_at) }}。系统已记录当时的完整复核快照。</span>
        <span v-else>检测到 {{ exportTime(exportPreview.previous_export_at) }} 的同条件历史导出。该旧版本未记录完整复核状态，增量范围将按其导出时间水位安全计算。</span>
      </div>

      <div class="export-scope-options" role="radiogroup" aria-label="导出范围">
        <label class="export-scope-option" :class="{ 'is-selected': exportMode === 'all' }">
          <input v-model="exportMode" type="radio" value="all">
          <span class="export-scope-icon"><i class="bi bi-database" /></span>
          <span>
            <strong>全部已完成测评</strong>
            <small>重新生成当前全部用户信息、转录、AI 候选及所有已接受的人工复核文本；是否包含录音由下方选项决定。</small>
          </span>
        </label>
        <label class="export-scope-option" :class="{ 'is-selected': exportMode === 'incremental' }">
          <input v-model="exportMode" type="radio" value="incremental">
          <span class="export-scope-icon"><i class="bi bi-plus-circle" /></span>
          <span>
            <strong>仅导出上次之后新增内容</strong>
            <small v-if="exportPreview?.previous_export_at">相对上次完整/增量导出，新增复核 {{ exportPreview.newly_reviewed_count }} 条：新接受 {{ exportPreview.newly_accepted_count }} 条、新排除 {{ Math.max(0, exportPreview.newly_reviewed_count - exportPreview.newly_accepted_count) }} 条；另含新完成测评，共涉及 {{ exportPreview.incremental_session_count }} 个任务。</small>
            <small v-else>尚无历史导出，首次使用时自动按全部数据生成。</small>
          </span>
        </label>
        <label class="export-scope-option" :class="{ 'is-selected': exportMode === 'accepted_only' }">
          <input v-model="exportMode" type="radio" value="accepted_only">
          <span class="export-scope-icon"><i class="bi bi-check2-circle" /></span>
          <span>
            <strong>仅导出当前已接受内容</strong>
            <small>导出当前最新抽取版本中累计已接受的 {{ exportPreview?.accepted_count ?? 0 }} 条候选；不处理录音、原始转录、待复核和已排除内容，生成速度最快。</small>
          </span>
        </label>
      </div>
      <label class="export-audio-option" :class="{ 'is-disabled': exportMode === 'accepted_only' }">
        <input
          v-model="exportIncludeAudio"
          class="form-check-input"
          type="checkbox"
          :disabled="exportMode === 'accepted_only'"
        >
        <span class="export-audio-option-icon"><i class="bi bi-file-earmark-music" /></span>
        <span>
          <strong>同时导出原始录音</strong>
          <small v-if="exportMode === 'accepted_only'">“仅导出当前已接受内容”固定为轻量文本包，不包含录音。</small>
          <small v-else-if="exportIncludeAudio">包含每项任务的 WAV 录音；文件更大，服务器生成和浏览器下载所需时间更长。</small>
          <small v-else>跳过录音合并、转码和打包，只导出用户信息、转录与候选文本，生成更快。</small>
        </span>
      </label>
      <div class="export-dialog-note">
        <i class="bi bi-info-circle" />
        下载完成后服务器仅保留最近一次派生研究数据 ZIP；原始录音和数据库记录不会被删除。
      </div>

      <ExportGuideOrb
        :has-previous-export="Boolean(exportPreview?.previous_export_at)"
        :include-audio="exportMode !== 'accepted_only' && exportIncludeAudio"
        :newly-reviewed-count="exportPreview?.newly_reviewed_count ?? 0"
        :newly-accepted-count="exportPreview?.newly_accepted_count ?? 0"
        :incremental-session-count="exportPreview?.incremental_session_count ?? 0"
      />

      <template #footer>
        <div class="d-flex justify-content-end gap-2 w-100">
          <button class="btn btn-secondary" type="button" @click="exportDialogOpen = false">取消</button>
          <button class="btn btn-primary" type="button" :disabled="exportPreviewLoading || !exportPreview" @click="startBundleExport">
            <i class="bi bi-download me-1" />{{ exportPreview && !exportPreview.review_complete ? '确认现状并导出' : '开始生成' }}
          </button>
        </div>
      </template>
    </AppModal>

    <!-- 质量决策弹窗 -->
    <AppModal
      :open="Boolean(qualityDecisionTarget)"
      max-width="520px"
      @close="qualityDecisionTarget = null"
    >
      <template #header>
        <h5 class="mb-0">研究数据{{ qualityDecision === 'included' ? '纳入' : qualityDecision === 'excluded' ? '排除' : '恢复自动判断' }}</h5>
      </template>

      <p v-if="qualityDecisionTarget" class="text-muted small">
        {{ qualityDecisionTarget.name }}（{{ qualityDecisionTarget.username }}）· 测评 {{ qualityDecisionTarget.run_id.slice(0, 8) }}
      </p>
      <label v-if="qualityDecision !== 'automatic'" class="form-label">决策依据</label>
      <textarea
        v-if="qualityDecision !== 'automatic'"
        v-model="qualityReason"
        class="form-control"
        rows="4"
        placeholder="填写可审计的纳入或排除依据，至少 5 个字"
      />

      <template #footer>
        <div class="d-flex justify-content-end gap-2 w-100">
          <button class="btn btn-secondary" :disabled="qualitySaving" @click="qualityDecisionTarget = null">取消</button>
          <button
            class="btn"
            :class="qualityDecision === 'excluded' ? 'btn-danger' : 'btn-primary'"
            :disabled="qualitySaving"
            @click="saveQualityDecision"
          >
            <span v-if="qualitySaving" class="spinner-border spinner-border-sm me-1" />确认保存
          </button>
        </div>
      </template>
    </AppModal>
  </div>
</template>

<style scoped>
.report-checks-cell { max-width: 25rem; white-space: normal; overflow-wrap: anywhere; }
.report-mobile-table .badge { white-space: normal; line-height: 1.5; text-align: center; }
.report-mobile-table td { overflow-wrap: anywhere; }
.report-refresh-results { max-height: 12rem; overflow-y: auto; overflow-wrap: anywhere; }
.teacher-page { max-width: 1240px; margin: 0 auto; }
.metric-table { font-size: .78rem; }
.metric-table th { color: var(--color-text-muted); font-weight: 600; white-space: nowrap; }
.teacher-page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-5);
}
.teacher-page-heading {
  min-width: 0;
}
.export-toggle { display: none; }
.export-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(245px, 1fr));
  gap: .75rem;
  flex: 0 1 590px;
}
.export-button {
  display: flex;
  align-items: center;
  gap: .7rem;
  min-height: 58px;
  padding: .65rem .85rem;
  text-align: left;
  border-radius: var(--radius-md);
}
.export-dialog { width: min(580px, calc(100vw - 2rem)); }
.export-dialog-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}
.export-review-check {
  display: grid;
  grid-template-columns: 1.2rem minmax(0, 1fr);
  gap: .65rem;
  margin-top: .35rem;
  padding: .8rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text-secondary);
  background: var(--color-surface-subtle);
}
.export-review-check > i { margin-top: .12rem; }
.export-review-check strong,.export-review-check small { display: block; }
.export-review-check p { margin-top: .25rem; font-size: .76rem; line-height: 1.5; }
.export-review-check small { margin-top: .35rem; color: var(--color-text-muted); line-height: 1.45; }
.export-review-check.is-complete { border-color: color-mix(in srgb,var(--color-success) 40%,var(--color-border)); background: var(--color-success-soft); }
.export-review-check.is-complete > i { color: var(--color-success); }
.export-review-check.is-warning { border-color: color-mix(in srgb,var(--color-warning) 52%,var(--color-border)); background: var(--color-warning-soft); }
.export-review-check.is-warning > i { color: var(--color-warning); }
.export-review-check.is-loading { display: flex; align-items: center; color: var(--color-text-muted); font-size: .78rem; }
.previous-export-note { display: flex; gap: .5rem; margin-top: .65rem; padding: .65rem .75rem; border-radius: .65rem; color: var(--color-text-muted); background: var(--color-surface-subtle); font-size: .72rem; line-height: 1.5; }
.previous-export-note.is-incomplete { color: var(--color-warning); background: var(--color-warning-soft); }
.export-scope-options { display: grid; gap: .75rem; margin-top: 1.25rem; }
.export-scope-option {
  display: grid;
  grid-template-columns: auto 2.25rem minmax(0, 1fr);
  align-items: center;
  gap: .75rem;
  padding: .9rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  cursor: pointer;
  transition: border-color .16s ease, background-color .16s ease, box-shadow .16s ease;
}
.export-scope-option:hover { border-color: var(--color-primary); background: var(--color-primary-soft); }
.export-scope-option.is-selected {
  border-color: var(--color-primary);
  background: var(--color-primary-soft);
  box-shadow: 0 0 0 2px rgba(79, 70, 229, .08);
}
.export-scope-option input { margin: 0; accent-color: var(--color-primary); }
.export-scope-icon {
  display: grid;
  place-items: center;
  width: 2.25rem;
  height: 2.25rem;
  border-radius: .65rem;
  color: var(--color-primary);
  background: var(--color-surface);
}
.export-scope-option strong,
.export-scope-option small { display: block; }
.export-scope-option small { margin-top: .2rem; color: var(--color-text-muted); line-height: 1.45; }
.export-audio-option {
  display: grid;
  grid-template-columns: auto 2.25rem minmax(0, 1fr);
  align-items: center;
  gap: .75rem;
  margin-top: .85rem;
  padding: .85rem .9rem;
  border: 1px solid color-mix(in srgb,var(--color-primary) 32%,var(--color-border));
  border-radius: var(--radius-md);
  background: color-mix(in srgb,var(--color-primary-soft) 58%,var(--color-surface));
  cursor: pointer;
}
.export-audio-option.is-disabled { opacity: .68; cursor: not-allowed; }
.export-audio-option-icon { display: grid; place-items: center; width: 2.25rem; height: 2.25rem; border-radius: .65rem; color: var(--color-primary); background: var(--color-surface); }
.export-audio-option strong,.export-audio-option small { display: block; }
.export-audio-option small { margin-top: .2rem; color: var(--color-text-muted); line-height: 1.45; }
.export-dialog-note {
  display: flex;
  gap: .5rem;
  margin-top: 1rem;
  padding: .7rem .8rem;
  border-radius: .65rem;
  color: var(--color-warning);
  background: var(--color-warning-soft);
  font-size: .75rem;
}
.export-button-icon {
  flex: 0 0 auto;
  font-size: 1.25rem;
}
.export-button strong,
.export-button small {
  display: block;
}
.export-button strong {
  line-height: 1.2;
  font-size: .88rem;
}
.export-button small {
  margin-top: .22rem;
  line-height: 1.25;
  font-size: .68rem;
  opacity: .78;
}
.export-privacy-note {
  grid-column: 1 / -1;
  color: var(--color-warning);
  font-size: .72rem;
  text-align: right;
}

.export-progress {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 0.625rem;
  padding: 0.75rem 0.875rem;
  border: 1px solid var(--color-border);
  border-radius: 0.75rem;
  color: var(--color-primary);
  background: var(--color-primary-soft);
  font-size: 0.875rem;
}
.card, .metric-card { border-radius: var(--radius-lg); }
.metric-card {
  position: relative;
  overflow: hidden;
  padding: 1.25rem;
  border: 1px solid var(--color-border);
  background: linear-gradient(145deg, rgba(75, 73, 172, .055), transparent 55%), var(--color-surface);
  box-shadow: var(--shadow-xs), inset 0 1px rgba(255, 255, 255, .45);
}
.metric-card::after {
  content: '';
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 3px;
  background: linear-gradient(to bottom, var(--color-primary), var(--color-info));
  opacity: .55;
}
.metric-card span { display: block; color: var(--color-text-muted); font-size: .82rem; }
.metric-card strong { display: block; margin-top: .3rem; color: var(--color-text); font-size: 1.8rem; }
.research-metric {
  display: flex;
  justify-content: space-between;
  padding: .65rem 0;
  border-bottom: 1px solid var(--color-border);
}
.priority-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: .9rem 1rem;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  background: var(--color-primary-soft);
}
.work-queue {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: .75rem;
}
.work-item {
  display: flex;
  align-items: center;
  gap: .7rem;
  min-width: 0;
  padding: .85rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text-secondary);
  background: linear-gradient(135deg, rgba(75, 73, 172, .045), transparent 58%), var(--color-surface);
  text-decoration: none;
  box-shadow: inset 0 1px rgba(255, 255, 255, .38);
  transition: color var(--motion-fast) ease, border-color var(--motion-fast) ease, background-color var(--motion-fast) ease, box-shadow var(--motion-fast) ease;
}
.work-item:hover { border-color: var(--color-primary); color: var(--color-primary); background: var(--color-primary-soft); box-shadow: 0 6px 18px rgba(75, 73, 172, .08); }
.work-item > i:first-child { font-size: 1.15rem; color: var(--color-primary); }
.work-item > i:last-child { margin-left: auto; font-size: .75rem; }
.work-item span { min-width: 0; }
.work-item strong,
.work-item small { display: block; }
.work-item strong { font-size: 1.15rem; line-height: 1; }
.work-item small { margin-top: .2rem; color: var(--color-text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.work-item.urgent { border-color: var(--color-warning); background: var(--color-warning-soft); }
.quality-workbench,
.teacher-page > .card,
.teacher-page > .row .card {
  box-shadow: var(--shadow-sm), inset 0 0 0 1px var(--color-border) !important;
  background: linear-gradient(145deg, rgba(75, 73, 172, .025), transparent 48%), var(--color-surface);
}
.quality-workbench { position: relative; overflow: hidden; }
.quality-workbench::before {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  width: 3px;
  background: linear-gradient(to bottom, var(--color-primary), var(--color-info), var(--color-success));
  opacity: .68;
}
.quality-header,
.quality-summary,
.quality-toolbar,
.quality-actions { display: flex; align-items: center; gap: .65rem; }
.quality-header { justify-content: space-between; align-items: flex-start; }
.quality-summary { flex-wrap: wrap; justify-content: flex-end; }
.quality-summary span { padding: .35rem .55rem; border-radius: 999px; font-size: .72rem; font-weight: 700; }
.quality-summary .is-ready { color: var(--color-success); background: var(--color-success-soft); }
.quality-summary .is-warning { color: var(--color-warning); background: var(--color-warning-soft); }
.quality-summary .is-danger { color: var(--color-danger); background: var(--color-danger-soft); }
.quality-toolbar .form-control { max-width: 300px; }
.quality-toolbar .form-select { max-width: 190px; }
.quality-table-wrap { max-height: 430px; }
.quality-table-wrap thead th { position: sticky; top: 0; z-index: 2; background: var(--color-surface-subtle); }
.quality-issues { min-width: 260px; max-width: 430px; }
.quality-issues span { display: block; font-size: .72rem; line-height: 1.45; }
.quality-issues .warning { color: var(--color-warning); }
.quality-issues .fail { color: var(--color-danger); }
.quality-issues .pass { color: var(--color-success); }
.quality-decision-modal { width: min(520px, calc(100vw - 2rem)); }
.priority-actions strong,
.priority-actions span { display: block; }
.priority-actions span { margin-top: .15rem; color: var(--color-text-muted); font-size: .8rem; }
.reliability-result {
  margin-top: .55rem;
  padding: .65rem .75rem;
  border: 1px solid;
  border-radius: 10px;
}
.reliability-result small { display: block; line-height: 1.4; }
.reliability-result.is-pending { color: var(--color-warning); border-color: var(--color-border); background: var(--color-warning-soft); }
.reliability-result.is-warning { color: var(--color-danger); border-color: var(--color-border); background: var(--color-danger-soft); }
.reliability-result.is-ready { color: var(--color-success); border-color: var(--color-border); background: var(--color-success-soft); }
.selection-cell { width: 2.5rem; }
.order-select { min-width: 310px; }
.order-legend {
  display: flex;
  flex-wrap: wrap;
  gap: .75rem;
}
.order-legend span {
  padding: .45rem .7rem;
  border-radius: 8px;
  background: var(--color-surface-subtle);
  color: var(--color-text-secondary);
  font-size: .8rem;
}
.order-search { display: grid; grid-template-columns: minmax(220px, 1fr) 110px; gap: .75rem; }
@media (max-width: 991.98px) {
  .work-queue { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .quality-header { flex-direction: column; }
  .quality-summary { justify-content: flex-start; }
  .teacher-page-header {
    flex-direction: column;
    gap: 1rem;
  }
  .export-actions {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    flex-basis: auto;
    width: 100%;
  }
}
@media (max-width: 575.98px) {
  .work-queue { grid-template-columns: 1fr; }
  .quality-toolbar,
  .quality-actions { align-items: stretch; flex-direction: column; }
  .quality-toolbar .form-control,
  .quality-toolbar .form-select,
  .quality-actions .btn { width: 100%; max-width: none; min-height: 42px; }
  .teacher-page-header { gap: .75rem; }
  .export-toggle {
    display: flex;
    align-items: center;
    width: 100%;
    min-height: 44px;
  }
  .export-actions {
    display: none;
    grid-template-columns: 1fr;
    gap: .625rem;
  }
  .export-actions.is-expanded { display: grid; }
  .export-button {
    width: 100%;
  }
  .export-privacy-note { text-align: left; }
  .metric-card { min-height: 88px; padding: .85rem; }
  .metric-card strong { margin-top: .15rem; font-size: 1.35rem; }
  .priority-actions { align-items: stretch; flex-direction: column; }
  .priority-actions .btn { flex: 1 1 auto; }
  .order-legend { display: grid; gap: .5rem; }
  .order-search { grid-template-columns: 1fr; }
  .order-select { min-width: 260px; }
  .research-metric { gap: 1rem; }
  .research-metric span { min-width: 0; }
  .mobile-card-table { min-width: 0; margin: 0 !important; }
  .mobile-card-table thead { display: none; }
  .mobile-card-table tbody {
    display: grid;
    gap: .75rem;
  }
  .mobile-card-table tbody tr {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: .75rem 1rem;
    padding: .9rem;
    border: 1px solid var(--color-border);
    border-radius: 12px;
    background: var(--color-surface);
    box-shadow: 0 4px 14px rgba(34,43,69,.04);
  }
  .mobile-card-table tbody td {
    display: block;
    min-width: 0;
    padding: 0;
    border: 0;
    text-align: left !important;
  }
  .mobile-card-table tbody td[data-label]::before {
    content: attr(data-label);
    display: block;
    margin-bottom: .28rem;
    color: var(--color-text-muted);
    font-size: .67rem;
    font-weight: 700;
  }
  .mobile-card-table tbody td[colspan] { grid-column: 1 / -1; padding: 1.25rem 0; }
  .quality-mobile-table td:first-child,
  .quality-mobile-table .quality-issues,
  .quality-mobile-table td:last-child,
  .order-mobile-table td:nth-child(2),
  .order-mobile-table td:nth-child(4),
  .order-mobile-table td:nth-child(5),
  .report-mobile-table td:nth-child(2),
  .report-mobile-table td:last-child { grid-column: 1 / -1; }
  .quality-mobile-table .quality-issues { max-width: none; }
  .quality-mobile-table .quality-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .quality-mobile-table .quality-actions .btn { width: 100%; }
  .order-mobile-table .order-select { width: 100%; min-width: 0; }
  .report-mobile-table td:last-child .btn { width: 100%; min-height: 42px; }
}

.pending-analysis-card {
  border-radius: var(--radius-xl);
  overflow: hidden;
}
.user-avatar-badge {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  display: grid;
  place-items: center;
  font-weight: 700;
  font-size: .88rem;
  flex-shrink: 0;
}
.task-flow-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.task-tag {
  display: inline-flex;
  align-items: center;
  padding: 3px 8px;
  border-radius: var(--radius-sm);
  background: var(--color-surface-subtle);
  border: 1px solid var(--color-border);
  font-size: .78rem;
}
</style>
