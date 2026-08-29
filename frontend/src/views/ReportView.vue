<script setup lang="ts">
import { computed, nextTick, onScopeDispose, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '../stores/user'
import { researchApi } from '../api/research'
import { confirmAction, notify } from '../composables/useUiFeedback'
import RadarChart from '../components/charts/RadarChart.vue'
import ReportVersionHistory from '../components/dashboard/ReportVersionHistory.vue'
import {
  reportApi,
  type MetacognitionMeasurement,
  type ReportBrief,
  type ReportDetail,
  type ReportReview
} from '../api/reports'
import type { DimensionScore } from '../types/assessment'
import AppEmptyState from '../components/ui/AppEmptyState.vue'
import AppPageHeader from '../components/ui/AppPageHeader.vue'
import { parseApiDate } from '../utils/datetime'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const isReviewer = computed(() => ['teacher', 'admin'].includes(userStore.profile.role))
const review = ref<ReportReview | null>(null)
const reviewConfirmed = ref(false)
const reviewNote = ref('')
const publishing = ref(false)
const regenerating = ref(false)
const publishError = ref('')
let loadVersion = 0
onScopeDispose(() => { loadVersion++ })
const report = ref<ReportDetail | null>(null)
const reports = ref<ReportBrief[]>([])
const isLoading = ref(true)
const waitingForPublication = ref(false)
const errorMessage = ref('')
const highlightedDimension = ref('')
const selectedMeasurement = ref<MetacognitionMeasurement | null>(null)
const measurementError = ref('')

function measurementRadarScores(measurement: MetacognitionMeasurement | null): DimensionScore[] {
  if (!measurement?.score_available) return []
  const rows: Array<{ dimension: DimensionScore['dimension']; label: string; score: number | null }> = [
    { dimension: 'monitoring', label: '监控', score: measurement.dimension_scores.monitoring },
    { dimension: 'controlDebugging', label: '控制/调试', score: measurement.dimension_scores.control_debugging },
    { dimension: 'evaluation', label: '评估', score: measurement.dimension_scores.evaluation }
  ]
  return rows.flatMap(item => item.score === null ? [] : [{ ...item, score: item.score, max: 1 }])
}

const radarScores = computed<DimensionScore[]>(() => measurementRadarScores(selectedMeasurement.value))

const methodLabel = computed(() => {
  const labels: Record<string, string> = {
    hybrid: '规则基线 + LLM 辅助',
    llm: 'LLM 辅助编码',
    rule: '规则基线编码',
    rule_fallback: '规则降级编码',
    existing: '已有编码重新聚合',
    human_reviewed: '含人工复核'
    , unified_evidence: '三端统一分类证据', double_coder_consensus: '专家共识或仲裁'
  }
  return labels[report.value?.analysis_method ?? ''] ?? report.value?.analysis_method
})

const workflowLabel = computed(() => {
  const labels: Record<string, string> = {
    draft: '报告草稿',
    review_pending: '等待人工复核',
    reviewed: '已复核，待发布',
    published: '已审核发布',
    withdrawn: '已撤回'
    , archived: '已归档'
  }
  return labels[report.value?.workflow_status ?? ''] ?? report.value?.workflow_status
})

function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).format(parseApiDate(value))
}

function scoreTone(score: number) {
  if (score >= 85) return 'success'
  if (score >= 70) return 'primary'
  if (score >= 50) return 'warning'
  return 'danger'
}

function evidenceStrength(confidence: number) {
  if (confidence >= .8) return '较强'
  if (confidence >= .6) return '中等'
  return '有限'
}

function formatMeasurementScore(score: number | null) {
  return score === null ? '暂无' : `${(score * 100).toFixed(1)}%`
}

async function loadReportById(reportId: string, requestId: number) {
  const response = await reportApi.get(reportId)
  if (requestId !== loadVersion) return
  report.value = response.data
  selectedMeasurement.value = response.data.measurement_snapshot ?? null
  measurementError.value = selectedMeasurement.value
    ? ''
    : '该历史报告未保存生成时的三维画像快照，无法可靠还原。'
}

async function loadPage() {
  const requestId = ++loadVersion
  isLoading.value = true
  errorMessage.value = ''
  report.value = null
  reports.value = []
  review.value = null
  reviewConfirmed.value = false
  reviewNote.value = ''
  selectedMeasurement.value = null
  waitingForPublication.value = false
  measurementError.value = ''
  highlightedDimension.value = ''
  const runId = typeof route.query.run === 'string' ? route.query.run : ''
  const reportId = typeof route.query.id === 'string' ? route.query.id : ''
  try {
    if (isReviewer.value) {
      if (!reportId && !runId) throw new Error('请从最近报告列表选择需要审阅的草稿')
      const id = reportId || (await reportApi.getByRun(runId)).data.id
      if (requestId !== loadVersion) return
      const result = (await reportApi.review(id)).data
      if (requestId !== loadVersion) return
      review.value = result
      report.value = result.report
      selectedMeasurement.value = result.measurement
      measurementError.value = result.measurement_error
      return
    }
    const reportResult = await reportApi.list()
    if (requestId !== loadVersion) return
    reports.value = reportResult.data
    if (reportId) {
      await loadReportById(reportId, requestId)
    } else if (runId) {
      const requestedReport = reports.value.find(item => item.run_id === runId)
      if (requestedReport) {
        await loadReportById(requestedReport.id, requestId)
      } else {
        waitingForPublication.value = true
      }
    } else if (reports.value[0]) {
      await loadReportById(reports.value[0].id, requestId)
    }
  } catch (error) {
    if (requestId === loadVersion) errorMessage.value = error instanceof Error ? error.message : '报告加载失败'
  } finally {
    if (requestId === loadVersion) isLoading.value = false
  }
}

async function selectReport(reportId: string) {
  await router.replace({ path: route.path, query: { id: reportId } })
}

async function publishReviewedReport() {
  if (!isReviewer.value || !report.value || !review.value?.can_publish || !reviewConfirmed.value || publishing.value || regenerating.value) return
  const snapshot = report.value
  const note = reviewNote.value.trim()
  const confirmed = await confirmAction({ title: '确认发布报告', message: `将 ${review.value.owner.name}（${review.value.owner.username}）的报告发布给学生并发送通知。请确认已审阅正文、证据与学习建议。`, confirmText: '确认发布', tone: 'success' })
  if (!confirmed || report.value !== snapshot || publishing.value || regenerating.value) return
  const risks = review.value.risks || []
  if (risks.length) {
    const riskConfirmed = await confirmAction({
      title: '发布风险警告',
      message: `以下检查未通过，但你仍可发布。请确认已了解风险并继续：\n${risks.join('\n')}\n\n发布后将固定当前正文与画像快照，学生会立即看到该报告。`,
      confirmText: '确认风险并仍要发布',
      tone: 'danger'
    })
    if (!riskConfirmed || report.value !== snapshot || publishing.value || regenerating.value) return
  }
  publishing.value = true
  publishError.value = ''
  try {
    await researchApi.publishReport(snapshot.id, note, {
      review_confirmed: true,
      expected_generated_at: snapshot.generated_at,
      acknowledge_risks: risks.length > 0
    })
    notify('报告已发布，学生现在可以查看并收到通知。', 'success')
    if (report.value === snapshot) await loadPage()
  } catch (error) {
    if (report.value === snapshot) {
      publishError.value = error instanceof Error ? error.message : '发布失败'
      await loadPage()
    }
  } finally {
    publishing.value = false
  }
}

async function updateDraft() {
  const snapshot = report.value
  if (!isReviewer.value || !snapshot?.run_id || !['draft', 'review_pending', 'reviewed'].includes(snapshot.workflow_status) || publishing.value || regenerating.value) return
  const confirmed = await confirmAction({ title: '重新 AI 分析草稿', message: '将按当前报告提示词及已有证据重新生成画像与建议，不改动人工编码。成功后替换原草稿，需重新审阅；AI 调用失败则保留原稿，不会自动发布。', confirmText: '重新 AI 分析', tone: 'primary' })
  if (!confirmed || report.value !== snapshot || publishing.value || regenerating.value) return
  regenerating.value = true
  reviewConfirmed.value = false
  publishError.value = ''
  try {
    const result = (await researchApi.startAnalysis(snapshot.run_id, false, { report_only: true, expected_generated_at: snapshot.generated_at })).data
    if (result.status !== 'completed') throw new Error(result.error_message || '草稿更新失败')
    notify('草稿已更新，请重新审阅后发布。', 'success')
    if (report.value === snapshot) await loadPage()
  } catch (error) {
    if (report.value === snapshot) publishError.value = error instanceof Error ? error.message : '草稿更新失败'
  } finally { regenerating.value = false }
}

function onSelectDimension(dim: { dimension: string; label: string; score: number }) {
  if (!isReviewer.value) return
  highlightedDimension.value = dim.dimension
  nextTick(() => {
    const el = document.getElementById(`dim-${dim.dimension}`)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  })
}

function exportPdf() {
  if (!report.value) return
  const previousTitle = document.title
  const dateLabel = formatDate(report.value.generated_at).replace(/[\s/:]/g, '-')
  document.title = `元认知测评报告_${dateLabel}`
  window.print()
  window.setTimeout(() => { document.title = previousTitle }, 500)
}

watch(() => [route.path, route.query.run, route.query.id], () => { publishError.value = ''; void loadPage() }, { immediate: true })
</script>

<template>
  <div class="report-page">
    <AppPageHeader eyebrow="元认知画像" :title="isReviewer ? '报告草稿与审阅' : '我的元认知测评报告'" icon="bi-file-earmark-bar-graph" description="依据本次协议采集的出声思维行为证据与可选问卷形成阶段性学习反馈。">
      <template #actions>
        <div class="d-flex align-items-center gap-2 flex-wrap">
          <RouterLink v-if="isReviewer" to="/teacher" class="btn btn-outline-secondary">返回报告列表</RouterLink>
          <select
            v-if="reports.length > 1"
            class="form-select report-select"
            aria-label="选择测评报告"
            :value="report?.id"
            @change="selectReport(($event.target as HTMLSelectElement).value)"
          >
            <option v-for="item in reports" :key="item.id" :value="item.id">
              {{ formatDate(item.generated_at) }} · {{ item.level }}
            </option>
          </select>
          <button
            v-if="report"
            class="btn btn-outline-primary pdf-export-button"
            type="button"
            title="在打印窗口中选择“另存为 PDF”"
            @click="exportPdf"
          >
            <i class="bi bi-file-earmark-pdf me-1" />导出 PDF
          </button>
        </div>
      </template>
    </AppPageHeader>

    <div v-if="errorMessage" class="alert alert-danger">
      <i class="bi bi-exclamation-triangle-fill me-2" />{{ errorMessage }}
    </div>

    <div v-if="isLoading" class="card border-0 shadow-sm">
      <div class="card-body py-5 text-center">
        <div class="spinner-border text-primary mb-3" />
        <p class="mb-1">{{ isReviewer ? '正在加载报告草稿与发布检查……' : '正在加载已发布报告……' }}</p>
      </div>
    </div>

    <div v-else-if="!report" class="card border-0 shadow-sm">
      <AppEmptyState
        icon="bi-hourglass-split"
        :title="isReviewer ? '草稿暂不可查看' : waitingForPublication ? '报告正在处理中' : '还没有可查看的报告'"
        :description="isReviewer ? '请确认草稿已生成且属于您的管理范围；可返回列表或重试。' : waitingForPublication
          ? '测评数据正在依次进行权威转录、候选复核、双人编码与研究审核；正式发布后系统会通过消息通知你。'
          : '个人报告需经研究复核并正式发布后才可查看。'"
      >
        <button v-if="isReviewer || errorMessage" type="button" class="btn btn-primary" @click="loadPage">重新加载</button>
        <RouterLink v-else-if="waitingForPublication" to="/" class="btn btn-primary">返回学习概览</RouterLink>
        <RouterLink v-else to="/assessment" class="btn btn-primary">开始测评</RouterLink>
        <RouterLink
          v-if="waitingForPublication && reports.length"
          to="/report"
          class="btn btn-outline-primary ms-2"
        >
          查看其他已发布报告
        </RouterLink>
      </AppEmptyState>
    </div>

    <template v-else>
      <header class="report-print-header">
        <div>
          <span>知见 · AI 元认知测评</span>
          <h1>元认知测评报告{{ report.workflow_status !== 'published' ? '（草稿·未发布）' : '' }}</h1>
        </div>
        <dl v-if="isReviewer">
          <div v-if="review"><dt>学生</dt><dd>{{ review.owner.name }} · {{ review.owner.username }}</dd></div>
          <div><dt>报告等级</dt><dd>{{ report.level }}</dd></div>
          <div v-if="report.overall_score_available !== false"><dt>历史综合得分</dt><dd>{{ report.overall_score.toFixed(1) }} / 100</dd></div>
          <div><dt>生成时间</dt><dd>{{ formatDate(report.generated_at) }}</dd></div>
        </dl>
      </header>
      <div
        v-if="isReviewer"
        class="alert d-flex gap-2"
        :class="report.workflow_status === 'published' ? 'alert-success' : 'alert-warning'"
      >
        <i class="bi bi-info-circle-fill mt-1" />
        <div>
          <strong>{{ workflowLabel }}</strong>
          <div class="small">
            本报告尚未建立正式常模，不能解释为人群百分位，也不用于临床诊断或高风险决策。
            <span v-if="report.requires_review_count">
              其中 {{ report.requires_review_count }} 条有效对话等待分类。
            </span>
          </div>
        </div>
      </div>

      <div v-if="isReviewer && !report.generation_metadata" class="alert alert-warning">
        历史报告：生成来源信息不完整。下方画像如可用，反映当前数据，不代表历史报告生成时的快照。
      </div>
      <div v-if="isReviewer && report.generation_metadata" class="alert alert-info report-provenance">
        AI 生成成功 · 模型 {{ report.generation_metadata.model || '未记录' }} · 提示词 {{ report.template_version }} · 报告 V{{ report.version_no }}。
        图表与正文绑定生成时的数据快照，不随后续校对而自动改变。
        <details><summary>查看数据版本</summary>{{ report.generation_metadata.data_version }}</details>
      </div>
      <div v-if="isReviewer && report.evidence_is_provisional" class="alert alert-warning">
        暂定学习反馈：包含未复核、回退、未分类或缺失任务数据，不能作为正式测量结论。
      </div>

      <section v-if="isReviewer && review" class="card border-0 shadow-sm mb-4 review-controls">
        <div class="card-body p-4">
          <h5>{{ review.owner.name }} · {{ review.owner.username }} <small class="text-muted">{{ review.owner.class_group || '未分班' }}</small></h5>
          <p class="text-muted mb-2">下方为报告正文；草稿仅对有权限的管理员、教师可见。审阅确认不会跳过必须处理的检查；存在未通过检查时，可确认风险后发布。</p>
          <ul class="review-checks">
            <li v-for="check in review.checks" :key="check.key" :class="check.passed ? 'text-success' : 'text-warning-emphasis'">
              <i :class="check.passed ? 'bi bi-check-circle' : 'bi bi-exclamation-circle'" /> {{ check.message }}
              <RouterLink v-if="!check.passed && check.route" :to="check.route" class="ms-2">前往处理</RouterLink>
            </li>
          </ul>
          <p v-if="report.workflow_status === 'published'" class="text-success mb-0">已发布给学生，无需再次发布。</p>
          <p v-else class="text-muted small mb-0">请阅读下方完整报告，页面底部可填写审阅意见并确认发布。</p>
        </div>
      </section>

      <div class="row g-4 report-summary-grid" :class="{ 'student-final-report': !isReviewer }">
        <!-- 综合分与报告元数据 -->
        <div v-if="isReviewer" class="col-lg-4">
          <div class="card border-0 shadow-sm h-100 score-card">
            <div class="card-body p-4 text-center">
              <div v-if="report.overall_score_available !== false" class="score-ring mx-auto" :class="`tone-${scoreTone(report.overall_score)}`">
                <strong>{{ report.overall_score.toFixed(1) }}</strong>
                <span>/ 100</span>
              </div>
              <p v-else class="text-muted">本报告展示三维言语证据占比，不计算能力综合分。</p>
              <h4 class="mt-3">{{ report.level }}</h4>
              <p class="text-muted small">{{ report.summary }}</p>
              <hr>
              <div class="text-start small text-muted">
                <div>编码方式：{{ methodLabel }}</div>
                <div>量表版本：{{ report.rubric_version }}</div>
                <div>方法模板：{{ report.template_version }}</div>
                <div>生成时间：{{ formatDate(report.generated_at) }}</div>
              </div>
            </div>
          </div>
        </div>

        <!-- 交互雷达图 -->
        <div :class="isReviewer ? 'col-lg-8' : 'col-12'">
          <div class="card border-0 shadow-sm h-100">
            <div class="card-body p-4">
              <div class="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-2">
                <div>
                  <h5 class="mb-0">元认知三维测量画像</h5>
                  <p class="text-muted small mb-0">
                    各维度为最终标签命中数 ÷ 本轮最终有效对话数；悬浮查看百分比。
                  </p>
                </div>
              </div>
              <div v-if="report.evidence_is_provisional" class="alert alert-warning py-2 small">
                本轮包含未复核、回退、未分类或缺失任务数据，雷达图仅作暂定学习反馈。
              </div>
              <div v-if="measurementError" class="alert alert-danger mb-0">{{ measurementError }}</div>
              <div v-else-if="!selectedMeasurement?.score_available" class="measurement-empty">
                <i class="bi bi-radar" />
                <strong>本轮暂无足够的有效对话数据</strong>
                <p>暂不能生成元认知三维画像，系统不会显示三个 0 分或演示数据。</p>
              </div>
              <template v-else>
                <RadarChart
                  :scores="radarScores"
                  name="本次测量"
                  :height="320"
                  :show-norm="false"
                  :global-max="1"
                  :display-as-percentage="true"
                  @select-dimension="onSelectDimension"
                />
                <div class="measurement-score-grid">
                  <div><span>监控</span><strong>{{ formatMeasurementScore(selectedMeasurement.dimension_scores.monitoring) }}</strong><small>{{ selectedMeasurement.dimension_counts.monitoring }} 条</small></div>
                  <div><span>控制/调试</span><strong>{{ formatMeasurementScore(selectedMeasurement.dimension_scores.control_debugging) }}</strong><small>{{ selectedMeasurement.dimension_counts.control_debugging }} 条</small></div>
                  <div><span>评估</span><strong>{{ formatMeasurementScore(selectedMeasurement.dimension_scores.evaluation) }}</strong><small>{{ selectedMeasurement.dimension_counts.evaluation }} 条</small></div>
                  <div><span>有效对话</span><strong>{{ selectedMeasurement.effective_dialogue_count }}</strong><small>条</small></div>
                </div>
                <section v-if="report.metacognition_pattern" class="metacognition-pattern mt-3">
                  <div class="pattern-heading">
                    <h6>本轮元认知模式</h6>
                    <span
                      class="badge"
                      :class="report.metacognition_pattern.status === 'available' ? 'text-bg-primary' : 'text-bg-warning'"
                    >
                      {{ report.metacognition_pattern.status === 'available' ? '本轮相对画像' : report.metacognition_pattern.status === 'insufficient' ? '证据不足' : '暂定' }}
                    </span>
                  </div>
                  <strong class="pattern-label">{{ report.metacognition_pattern.label }}</strong>
                  <p>{{ report.metacognition_pattern.description }}</p>
                  <p class="pattern-focus"><span>练习重点</span>{{ report.metacognition_pattern.practice_focus }}</p>
                  <details v-if="isReviewer" class="pattern-method">
                    <summary>查看判定方法</summary>
                    个体内相对比较 · {{ report.metacognition_pattern.rule_version }} · 群体常模{{ report.metacognition_pattern.group_norm.status === 'available' ? '已接入' : '待接入' }}
                  </details>
                </section>
              </template>
            </div>
          </div>
        </div>
      </div>

      <!-- 维度卡片与证据 -->
      <div v-if="isReviewer" class="row g-4 mt-1 dimension-grid">
        <div
          v-for="dimension in report.dimension_details"
          :id="`dim-${dimension.dimension}`"
          :key="dimension.dimension"
          class="col-lg-4"
        >
          <div
            class="card border-0 shadow-sm h-100 dimension-card"
            :class="{ 'is-highlighted': highlightedDimension === dimension.dimension }"
            @click="highlightedDimension = dimension.dimension"
          >
            <div class="card-body p-4">
              <div class="d-flex justify-content-between align-items-center">
                <h5 class="mb-0">{{ dimension.label }}</h5>
                <span class="badge text-bg-primary">
                  {{ dimension.score.toFixed(1) }}{{ report.overall_score_available === false ? '%' : '' }}
                </span>
              </div>
              <p class="text-muted small mt-3">{{ dimension.interpretation }}</p>
              <div class="source-score">
                <span>行为证据占比</span>
                <strong>{{ dimension.behavioral_score == null ? '证据不足' : dimension.behavioral_score.toFixed(1) + '%' }}</strong>
              </div>
              <div class="mt-3">
                <div class="small fw-semibold mb-2">支持证据</div>
                <div v-if="!dimension.evidence.length" class="text-muted small">
                  本次字幕中未提取到足够明确的该维度行为证据。
                </div>
                <blockquote
                  v-for="evidence in dimension.evidence"
                  :key="evidence.segmentId"
                  class="evidence-item"
                >
                  “{{ evidence.excerpt }}”
                  <small>
                    {{ evidence.reason }}
                    <span v-if="typeof evidence.confidence === 'number' && Number.isFinite(evidence.confidence)">
                      · 模型置信度 {{ Math.round(evidence.confidence * 100) }}%（{{ evidenceStrength(evidence.confidence) }}）
                    </span>
                  </small>
                </blockquote>
              </div>
            </div>
          </div>
        </div>
      </div>

      <section v-if="isReviewer" class="card border-0 shadow-sm mt-4">
        <div class="card-body p-4 row g-3">
          <div class="col-md-6"><h5>已观察到的表现</h5><ul><li v-for="item in report.strengths" :key="item">{{ item }}</li></ul><p v-if="!report.strengths.length" class="text-muted">暂无足够证据。</p></div>
          <div class="col-md-6"><h5>可进一步练习的方向</h5><ul><li v-for="item in report.weaknesses" :key="item">{{ item }}</li></ul><p v-if="!report.weaknesses.length" class="text-muted">暂无明确的练习方向。</p></div>
        </div>
      </section>
      <!-- 提升策略 -->
      <div class="card border-0 shadow-sm mt-4">
        <div class="card-body p-4">
          <h5>个性化提升策略</h5>
          <p class="text-muted small mb-0">依据本轮元认知模式及有效对话证据生成。</p>
          <p v-if="!report.recommendations.length" class="text-muted mb-0 mt-3">本轮暂未生成可用的个性化提升策略。</p>
          <div class="row g-3 mt-1">
            <div
              v-for="item in report.recommendations"
              :key="item.id"
              :class="report.recommendations.length === 1 ? 'col-12' : 'col-md-6'"
            >
              <div class="recommendation h-100">
                <h6>{{ item.title }}</h6>
                <p class="small text-muted">{{ item.description }}</p>
                <ul class="small mb-0">
                  <li v-for="practice in item.practices" :key="practice">{{ practice }}</li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      </div>
      <ReportVersionHistory v-if="isReviewer" :report-id="report.id" :version="report.version_no" />
      <section v-if="isReviewer && review && ['draft', 'review_pending', 'reviewed'].includes(report.workflow_status)" class="card border-0 shadow-sm mt-4 review-controls">
        <div class="card-body p-4">
          <h5>审阅确认与发布</h5>
          <div v-if="publishError" class="alert alert-danger" role="alert">{{ publishError }}</div>
          <div v-if="!review.can_publish" class="alert alert-warning">当前暂不能发布，请先处理上方未通过的检查；完成后刷新检查。如已调整编码，请重新生成草稿并再次审阅。</div>
          <div v-else-if="review.risks?.length" class="alert alert-warning">
            存在以下未通过检查，可点击“确认风险并仍要发布”继续：{{ review.risks.join('；') }}。发布后将按当前正文与画像快照固定，学生立即查看。
          </div>
          <label for="report-review-note" class="form-label">审阅意见（可选，将保存到发布审计记录）</label>
          <textarea id="report-review-note" v-model="reviewNote" class="form-control mb-3" rows="3" maxlength="1000" :disabled="publishing || regenerating" placeholder="记录报告结论、证据及建议的核查情况" />
          <div class="form-check mb-3">
            <input id="report-review-confirmed" v-model="reviewConfirmed" class="form-check-input" type="checkbox" :disabled="publishing || regenerating || !review.can_publish">
            <label for="report-review-confirmed" class="form-check-label">我已审阅本版草稿的报告正文、证据与建议，确认可以发布给该学生。</label>
          </div>
          <div class="d-flex flex-wrap gap-2">
            <button type="button" class="btn btn-success" :disabled="publishing || regenerating || !reviewConfirmed || !review.can_publish" @click="publishReviewedReport"><span v-if="publishing" class="spinner-border spinner-border-sm me-1" />审阅确认并发布</button>
            <button type="button" class="btn btn-outline-secondary" :disabled="publishing || regenerating" @click="loadPage">刷新发布检查</button>
            <button v-if="report.run_id && ['draft', 'review_pending', 'reviewed'].includes(report.workflow_status)" type="button" class="btn btn-outline-primary" :disabled="publishing || regenerating" @click="updateDraft"><span v-if="regenerating" class="spinner-border spinner-border-sm me-1" />重新 AI 分析草稿</button>
            <RouterLink to="/teacher" class="btn btn-outline-primary">返回报告列表</RouterLink>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.report-page { max-width: 1240px; margin: 0 auto; }
.report-provenance { overflow-wrap: anywhere; }
.report-select { width: min(320px, 100%); }
.report-print-header { display: none; }
.review-checks { list-style:none; padding:0; margin:1rem 0; display:grid; gap:.6rem; }
.review-controls { overflow-wrap:anywhere; }
.measurement-empty { min-height: 260px; display: grid; place-items: center; align-content: center; gap: .65rem; text-align: center; color: var(--color-text-muted); }
.measurement-empty i { font-size: 2.3rem; color: var(--color-primary); }
.measurement-empty strong { color: var(--color-text); }
.measurement-empty p { margin: 0; max-width: 480px; }
.measurement-score-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .6rem; }
.measurement-score-grid > div { display: grid; gap: .1rem; padding: .65rem; border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface-subtle); text-align: center; }
.measurement-score-grid span, .measurement-score-grid small { color: var(--color-text-muted); font-size: .75rem; }
.measurement-score-grid strong { color: var(--color-text); }
.metacognition-pattern { padding: 1rem 1.1rem; border: 1px solid color-mix(in srgb, var(--color-primary) 24%, var(--color-border)); border-radius: var(--radius-lg); background: color-mix(in srgb, var(--color-primary) 5%, var(--color-surface)); }
.pattern-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; }
.pattern-heading h6 { margin: 0; color: var(--color-text); font-weight: 700; line-height: 1.5; }
.pattern-heading .badge { flex: 0 0 auto; }
.pattern-label { display: block; margin-top: .75rem; color: var(--color-primary); font-size: 1.05rem; }
.metacognition-pattern p { margin: .45rem 0 0; color: var(--color-text-secondary); line-height: 1.65; }
.pattern-focus { display: flex; align-items: flex-start; gap: .55rem; }
.pattern-focus span { flex: 0 0 auto; color: var(--color-text); font-weight: 700; }
.pattern-method { margin-top: .65rem; color: var(--color-text-muted); font-size: .78rem; }
.pattern-method summary { cursor: pointer; }
.card { border-radius: var(--radius-xl); transition: border-color var(--motion-fast) ease, box-shadow var(--motion-fast) ease, transform var(--motion-fast) ease; }
.score-ring {
  width: 150px;
  height: 150px;
  border-radius: 50%;
  display: grid;
  place-content: center;
  border: 12px solid var(--color-border);
  background: var(--color-surface);
}
.score-ring strong { display: block; font-size: 2.2rem; line-height: 1; color: var(--color-text); }
.score-ring span { color: var(--color-text-muted); font-size: .8rem; }
.score-ring.tone-success { border-color: var(--color-success); }
.score-ring.tone-primary { border-color: var(--color-primary); }
.score-ring.tone-warning { border-color: var(--color-warning); }
.score-ring.tone-danger { border-color: var(--color-danger); }
.source-score {
  display: flex;
  justify-content: space-between;
  padding: .65rem 0;
  border-bottom: 1px solid var(--color-border);
  font-size: .85rem;
}
.evidence-item {
  margin: 0 0 .85rem;
  padding: .85rem 1rem;
  border-left: 3.5px solid var(--color-primary);
  border-radius: 0 var(--radius-md) var(--radius-md) 0;
  background: var(--color-surface-subtle);
  font-size: .84rem;
  line-height: 1.6;
}
.evidence-item small { display: block; color: var(--color-text-secondary); margin-top: .4rem; line-height: 1.45; }
.recommendation {
  padding: 1.25rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface-subtle);
}
.recommendation h6 { font-weight: 700; margin-bottom: .5rem; }
.recommendation li { margin-bottom: .4rem; line-height: 1.5; }
.dimension-card {
  cursor: pointer;
  transition: transform var(--motion-fast) ease, box-shadow var(--motion-fast) ease, border-color var(--motion-fast) ease;
}
.dimension-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06) !important;
}
.dimension-card.is-highlighted {
  border-color: var(--color-primary) !important;
  box-shadow: 0 0 0 3px var(--focus-ring), var(--shadow-md) !important;
  transform: translateY(-2px);
}
@media (max-width: 575.98px) {
  .report-select { width: 100%; }
  .score-ring { width: 128px; height: 128px; border-width: 10px; }
  .score-ring strong { font-size: 1.85rem; }
  .source-score { gap: 1rem; align-items: flex-start; }
  .source-score strong { text-align: right; }
  .evidence-item { padding: .75rem; word-break: break-word; }
  .recommendation { padding: 1rem; }
  .measurement-score-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .pattern-heading { display: grid; gap: .5rem; }
  .pattern-heading .badge { justify-self: start; }
}

@media print {
  .review-controls { display:none !important; }
  @page { size: A4 portrait; margin: 12mm; }
  :global(html), :global(body) {
    color: #1f2430 !important;
    background: #fff !important;
    print-color-adjust: exact;
    -webkit-print-color-adjust: exact;
  }
  :global(.sidebar),
  :global(.sidebar-backdrop),
  :global(.topbar),
  :global(.ds-page-header),
  :global(.app-feedback-host) { display: none !important; }
  :global(.app-shell), :global(.content-shell) {
    display: block !important;
    width: 100% !important;
    min-height: 0 !important;
    margin: 0 !important;
  }
  :global(.page-content) { padding: 0 !important; }
  .report-page { max-width: none; color: #1f2430; }
  .report-print-header {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 20mm;
    margin-bottom: 8mm;
    padding-bottom: 5mm;
    border-bottom: 2px solid #4b49ac;
  }
  .report-print-header span { color: #5d5f73; font-size: 9pt; letter-spacing: .08em; }
  .report-print-header h1 { margin: 1.5mm 0 0; color: #25253d; font-size: 22pt; }
  .report-print-header dl { display: grid; gap: 1.2mm; min-width: 62mm; margin: 0; font-size: 8.5pt; }
  .report-print-header dl div { display: flex; justify-content: space-between; gap: 8mm; }
  .report-print-header dt { color: #66687d; font-weight: 500; }
  .report-print-header dd { margin: 0; color: #25253d; font-weight: 700; }
  .alert { break-inside: avoid; border: 1px solid #d7d9e4 !important; color: #25253d !important; background: #f8f8fc !important; }
  .report-summary-grid { display: grid; grid-template-columns: 34% 66%; margin: 0 0 5mm !important; }
  .report-summary-grid.student-final-report { grid-template-columns: 100%; }
  .report-summary-grid > * { width: auto; padding: 0 2.5mm; }
  .dimension-grid { display: block; margin: 0 !important; }
  .dimension-grid > * { width: 100%; padding: 0; margin-bottom: 4mm; }
  .card, .recommendation, .evidence-item {
    color: #25253d !important;
    background: #fff !important;
    border: 1px solid #d7d9e4 !important;
    box-shadow: none !important;
    transform: none !important;
    break-inside: avoid;
  }
  .card-body { padding: 5mm !important; }
  .score-ring { width: 36mm; height: 36mm; background: #fff !important; }
  .score-ring strong, h4, h5, h6, strong { color: #25253d !important; }
  .text-muted, .evidence-item small { color: #5d5f73 !important; }
  .dimension-card { cursor: default; }
  .recommendation { min-height: 0; }
  .pdf-export-button, .report-select { display: none !important; }
  canvas { max-width: 100% !important; }
}
</style>
