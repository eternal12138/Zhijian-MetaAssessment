<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import RadarChart from '../components/charts/RadarChart.vue'
import {
  reportApi,
  type MetacognitionMeasurement,
  type ReportBrief,
  type ReportDetail
} from '../api/reports'
import type { DimensionScore } from '../types/assessment'
import AppEmptyState from '../components/ui/AppEmptyState.vue'
import AppPageHeader from '../components/ui/AppPageHeader.vue'
import { parseApiDate } from '../utils/datetime'

const route = useRoute()
const report = ref<ReportDetail | null>(null)
const reports = ref<ReportBrief[]>([])
const isLoading = ref(true)
const waitingForPublication = ref(false)
const errorMessage = ref('')
const highlightedDimension = ref('')
const enableComparison = ref(false)
const measurementHistory = ref<MetacognitionMeasurement[]>([])
const selectedMeasurement = ref<MetacognitionMeasurement | null>(null)
const comparisonMeasurement = ref<MetacognitionMeasurement | null>(null)
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

const comparisonScores = computed<DimensionScore[]>(() => {
  if (!enableComparison.value) return []
  return measurementRadarScores(comparisonMeasurement.value)
})

const comparisonLabel = computed(() => {
  if (!comparisonMeasurement.value) return '上次测量'
  return formatDate(comparisonMeasurement.value.completed_at)
})

const methodLabel = computed(() => {
  const labels: Record<string, string> = {
    hybrid: '规则基线 + LLM 辅助',
    llm: 'LLM 辅助编码',
    rule: '规则基线编码',
    rule_fallback: '规则降级编码',
    existing: '已有编码重新聚合',
    human_reviewed: '含人工复核'
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

async function loadReportById(reportId: string) {
  const response = await reportApi.get(reportId)
  report.value = response.data
  selectedMeasurement.value = measurementHistory.value.find(item => item.run_id === report.value?.run_id) ?? null
  comparisonMeasurement.value = measurementHistory.value.find(item => (
    item.run_id !== report.value?.run_id && item.score_available
  )) ?? null
  if (!comparisonMeasurement.value) {
    enableComparison.value = false
  }
}

async function loadPage() {
  isLoading.value = true
  errorMessage.value = ''
  report.value = null
  waitingForPublication.value = false
  measurementError.value = ''
  highlightedDimension.value = ''
  const runId = typeof route.query.run === 'string' ? route.query.run : ''
  try {
    const [reportResult, measurementResult] = await Promise.allSettled([
      reportApi.list(),
      reportApi.listMetacognitionMeasurements()
    ])
    if (reportResult.status === 'rejected') throw reportResult.reason
    reports.value = reportResult.value.data
    if (measurementResult.status === 'fulfilled') {
      measurementHistory.value = measurementResult.value.data.items
    } else {
      measurementHistory.value = []
      measurementError.value = measurementResult.reason instanceof Error
        ? measurementResult.reason.message
        : '三维测量结果加载失败'
    }
    if (runId) {
      const requestedReport = reports.value.find(item => item.run_id === runId)
      if (requestedReport) {
        await loadReportById(requestedReport.id)
      } else {
        waitingForPublication.value = true
      }
    } else if (reports.value[0]) {
      await loadReportById(reports.value[0].id)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '报告加载失败'
  } finally {
    isLoading.value = false
  }
}

async function selectReport(reportId: string) {
  isLoading.value = true
  errorMessage.value = ''
  try {
    await loadReportById(reportId)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '报告加载失败'
  } finally {
    isLoading.value = false
  }
}

function onSelectDimension(dim: { dimension: string; label: string; score: number }) {
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

watch(() => route.query.run, loadPage, { immediate: true })
</script>

<template>
  <div class="report-page">
    <AppPageHeader eyebrow="元认知画像" title="我的元认知测评报告" icon="bi-file-earmark-bar-graph" description="依据本次协议采集的出声思维行为证据与可选问卷形成阶段性学习反馈。">
      <template #actions>
        <div class="d-flex align-items-center gap-2 flex-wrap">
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
        <p class="mb-1">正在加载已发布报告……</p>
      </div>
    </div>

    <div v-else-if="!report" class="card border-0 shadow-sm">
      <AppEmptyState
        icon="bi-hourglass-split"
        :title="waitingForPublication ? '报告正在处理中' : '还没有可查看的报告'"
        :description="waitingForPublication
          ? '测评数据正在依次进行权威转录、候选复核、双人编码与研究审核；正式发布后系统会通过消息通知你。'
          : '个人报告需经研究复核并正式发布后才可查看。'"
      >
        <RouterLink v-if="waitingForPublication" to="/" class="btn btn-primary">返回学习概览</RouterLink>
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
          <h1>元认知测评报告</h1>
        </div>
        <dl>
          <div><dt>报告等级</dt><dd>{{ report.level }}</dd></div>
          <div><dt>综合得分</dt><dd>{{ report.overall_score.toFixed(1) }} / 100</dd></div>
          <div><dt>生成时间</dt><dd>{{ formatDate(report.generated_at) }}</dd></div>
        </dl>
      </header>
      <div
        class="alert d-flex gap-2"
        :class="report.workflow_status === 'published' ? 'alert-success' : 'alert-warning'"
      >
        <i class="bi bi-info-circle-fill mt-1" />
        <div>
          <strong>{{ workflowLabel }}</strong>
          <div class="small">
            本报告尚未建立正式常模，不能解释为人群百分位，也不用于临床诊断或高风险决策。
            <span v-if="report.requires_review_count">
              其中 {{ report.requires_review_count }} 条低置信度编码等待教师复核。
            </span>
          </div>
        </div>
      </div>

      <div class="row g-4 report-summary-grid">
        <!-- 综合分与报告元数据 -->
        <div class="col-lg-4">
          <div class="card border-0 shadow-sm h-100 score-card">
            <div class="card-body p-4 text-center">
              <div class="score-ring mx-auto" :class="`tone-${scoreTone(report.overall_score)}`">
                <strong>{{ report.overall_score.toFixed(1) }}</strong>
                <span>/ 100</span>
              </div>
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
        <div class="col-lg-8">
          <div class="card border-0 shadow-sm h-100">
            <div class="card-body p-4">
              <div class="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-2">
                <div>
                  <h5 class="mb-0">元认知三维测量画像</h5>
                  <p class="text-muted small mb-0">
                    各维度为最终标签命中数 ÷ 本轮最终有效对话数；悬浮查看百分比。
                  </p>
                </div>
                <div v-if="comparisonMeasurement" class="form-check form-switch mb-0">
                  <input
                    id="compare-switch"
                    v-model="enableComparison"
                    class="form-check-input"
                    type="checkbox"
                    role="switch"
                  >
                  <label class="form-check-label small text-muted" for="compare-switch">
                    与历史记录对比
                  </label>
                </div>
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
                  :comparison-scores="comparisonScores"
                  :comparison-name="comparisonLabel"
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
              </template>
            </div>
          </div>
        </div>
      </div>

      <!-- 维度卡片与证据 -->
      <div class="row g-4 mt-1 dimension-grid">
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
                <span class="badge" :class="`text-bg-${scoreTone(dimension.score)}`">
                  {{ dimension.score.toFixed(1) }}
                </span>
              </div>
              <p class="text-muted small mt-3">{{ dimension.interpretation }}</p>
              <div class="source-score">
                <span>行为证据</span>
                <strong>{{ dimension.behavioral_score?.toFixed(1) ?? '证据不足' }}</strong>
              </div>
              <div class="source-score">
                <span>任务后问卷</span>
                <strong>{{ dimension.questionnaire_score?.toFixed(1) ?? '未纳入' }}</strong>
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
                    {{ evidence.reason }} · 证据强度 {{ evidenceStrength(evidence.confidence) }}
                    （置信度 {{ Math.round(evidence.confidence * 100) }}%）
                  </small>
                </blockquote>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 练习建议 -->
      <div class="card border-0 shadow-sm mt-4">
        <div class="card-body p-4">
          <h5>个性化练习建议</h5>
          <div class="row g-3 mt-1">
            <div v-for="item in report.recommendations" :key="item.id" class="col-md-6">
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
    </template>
  </div>
</template>

<style scoped>
.report-page { max-width: 1240px; margin: 0 auto; }
.report-select { width: min(320px, 100%); }
.report-print-header { display: none; }
.measurement-empty { min-height: 260px; display: grid; place-items: center; align-content: center; gap: .65rem; text-align: center; color: var(--color-text-muted); }
.measurement-empty i { font-size: 2.3rem; color: var(--color-primary); }
.measurement-empty strong { color: var(--color-text); }
.measurement-empty p { margin: 0; max-width: 480px; }
.measurement-score-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .6rem; }
.measurement-score-grid > div { display: grid; gap: .1rem; padding: .65rem; border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface-subtle); text-align: center; }
.measurement-score-grid span, .measurement-score-grid small { color: var(--color-text-muted); font-size: .75rem; }
.measurement-score-grid strong { color: var(--color-text); }
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
}

@media print {
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
