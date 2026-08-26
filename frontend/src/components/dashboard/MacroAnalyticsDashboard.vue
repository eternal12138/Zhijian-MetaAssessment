<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import RadarChart from '../charts/RadarChart.vue'
import AppErrorBoundary from '../feedback/AppErrorBoundary.vue'
import { researchApi, type MacroAnalytics, type MacroOrderGroup } from '../../api/research'

const props = withDefaults(defineProps<{
  userRole?: 'teacher' | 'admin'
  classGroups?: string[]
}>(), {
  userRole: 'teacher',
  classGroups: () => []
})

type ViewTab = 'macro_radar' | 'order_balance' | 'dimension_distribution' | 'pipeline_status'

const selectedClass = ref('all')
const activeViewTab = ref<ViewTab>('macro_radar')
const isLoading = ref(false)
const errorMessage = ref('')
const analytics = ref<MacroAnalytics | null>(null)
let requestId = 0

const classOptions = computed(() => Array.from(new Set([
  ...props.classGroups,
  ...(analytics.value?.available_class_groups ?? [])
].filter(Boolean))).sort((a, b) => a.localeCompare(b, 'zh-CN')))
const classAverageScores = computed(() => analytics.value?.class_averages ?? [])
const referenceAverageScores = computed(() => analytics.value?.reference_averages ?? [])
const hasProfileData = computed(() => classAverageScores.value.length === 3)
const distributionRows = computed(() => {
  const distribution = analytics.value?.dimension_distribution
  const counts = distribution?.counts
  const total = distribution?.total ?? 0
  return [
    { key: 'monitoring', label: '监控', count: counts?.monitoring ?? 0, tone: 'is-monitoring' },
    { key: 'controlDebugging', label: '调控', count: counts?.controlDebugging ?? 0, tone: 'is-regulation' },
    { key: 'evaluation', label: '评估', count: counts?.evaluation ?? 0, tone: 'is-evaluation' }
  ].map(item => ({ ...item, percentage: total ? item.count / total * 100 : 0 }))
})

function valueOrDash(value: number | null | undefined, suffix = '') {
  return value == null ? '—' : `${value}${suffix}`
}

function groupFacts(group: MacroOrderGroup) {
  return [
    ['完整测评数', `${group.count} 份`],
    ['含画像得分', `${group.scoreCount} 份`],
    ['平均完成用时', valueOrDash(group.avgDurationMin, ' 分钟')],
    ['综合画像均分', valueOrDash(group.avgScore, ' 分')],
    ['已接受候选密度', valueOrDash(group.acceptedCandidateDensity, ' 条/分钟')]
  ]
}

function statusCount(statuses: Record<string, number> | undefined, ...keys: string[]) {
  return keys.reduce((total, key) => total + Number(statuses?.[key] ?? 0), 0)
}

function distributionSourceLabel(source: MacroAnalytics['dimension_distribution']['primary_source']) {
  return ({
    expert_consensus: '双人盲编共识/仲裁结果',
    production_model: '候选文本的当前生产模型分类',
    none: '暂无可用分类结果'
  })[source]
}

async function fetchRealMacroData() {
  const currentRequest = ++requestId
  isLoading.value = true
  errorMessage.value = ''
  try {
    const response = await researchApi.getMacroAnalytics(selectedClass.value)
    if (currentRequest === requestId) analytics.value = response.data
  } catch (error) {
    if (currentRequest !== requestId) return
    analytics.value = null
    errorMessage.value = error instanceof Error ? error.message : '宏观研究数据加载失败'
  } finally {
    if (currentRequest === requestId) isLoading.value = false
  }
}

watch(selectedClass, () => void fetchRealMacroData())
watch(() => props.classGroups, classes => {
  if (selectedClass.value !== 'all' && !classes.includes(selectedClass.value)) selectedClass.value = 'all'
}, { deep: true })
onMounted(() => void fetchRealMacroData())
</script>

<template>
  <AppErrorBoundary component-name="班级研究概览">
    <section class="macro-analytics-dashboard card border-0 shadow-sm mt-4">
      <div class="card-body p-4">
        <div class="macro-header">
          <div>
            <div class="title-line">
              <span class="badge bg-primary-subtle text-primary">真实数据聚合</span>
              <span v-if="analytics && !isLoading" class="live-dot" title="已从数据库完成聚合" />
              <h5 class="mb-0">班级研究概览与处理链路状态</h5>
            </div>
            <p class="text-muted small mb-0 mt-1">基于当前账号有权访问的真实测评、画像、专家编码和处理任务聚合；缺失数据不会使用演示值填充。</p>
          </div>
          <div class="macro-actions">
            <select v-model="selectedClass" class="form-select form-select-sm class-selector">
              <option value="all">全部可访问样本</option>
              <option v-for="className in classOptions" :key="className" :value="className">{{ className }}</option>
            </select>
            <button class="btn btn-sm btn-outline-secondary" title="刷新数据库聚合结果" :disabled="isLoading" @click="fetchRealMacroData">
              <i class="bi" :class="isLoading ? 'bi-arrow-repeat spin' : 'bi-arrow-clockwise'" />
            </button>
            <div class="btn-group btn-group-sm tab-button-group">
              <button class="btn" :class="activeViewTab === 'macro_radar' ? 'btn-primary' : 'btn-outline-secondary'" @click="activeViewTab = 'macro_radar'"><i class="bi bi-pie-chart me-1" />画像参照</button>
              <button class="btn" :class="activeViewTab === 'order_balance' ? 'btn-primary' : 'btn-outline-secondary'" @click="activeViewTab = 'order_balance'"><i class="bi bi-shuffle me-1" />任务顺序</button>
              <button class="btn" :class="activeViewTab === 'dimension_distribution' ? 'btn-primary' : 'btn-outline-secondary'" @click="activeViewTab = 'dimension_distribution'"><i class="bi bi-bar-chart-steps me-1" />三类分布</button>
              <button class="btn" :class="activeViewTab === 'pipeline_status' ? 'btn-primary' : 'btn-outline-secondary'" @click="activeViewTab = 'pipeline_status'"><i class="bi bi-activity me-1" />处理链路</button>
            </div>
          </div>
        </div>

        <div v-if="errorMessage" class="alert alert-danger mb-0"><i class="bi bi-exclamation-triangle me-2" />{{ errorMessage }}</div>
        <div v-else-if="isLoading && !analytics" class="macro-loading" aria-label="正在聚合研究数据">
          <span v-for="index in 4" :key="index" class="skeleton-block" />
        </div>

        <div v-else-if="analytics && activeViewTab === 'macro_radar'" class="macro-view-pane">
          <div v-if="!hasProfileData" class="macro-empty">
            <i class="bi bi-radar" /><strong>当前范围暂无完整元认知画像</strong>
            <p>需要先完成测评质量检查并生成报告，系统才会计算三维均值；这里不会填入预设分数。</p>
          </div>
          <div v-else class="row g-4 align-items-center">
            <div class="col-lg-6 text-center">
              <div class="radar-wrap">
                <RadarChart
                  :scores="classAverageScores"
                  :comparison-scores="referenceAverageScores"
                  :name="selectedClass === 'all' ? '全部可访问样本' : selectedClass"
                  comparison-name="可访问样本参照"
                />
              </div>
              <div class="radar-legend"><span><i class="bi bi-circle-fill text-primary" />当前范围均值</span><span><i class="bi bi-circle-fill text-info" />可访问样本参照</span></div>
            </div>
            <div class="col-lg-6">
              <div class="macro-stats-list">
                <div v-for="(score, index) in classAverageScores" :key="score.dimension" class="stat-row">
                  <span>{{ score.label }}</span>
                  <strong>{{ score.score }} 分 <small>参照 {{ referenceAverageScores[index]?.score ?? '—' }}</small></strong>
                </div>
                <div class="stat-row"><span>有效画像样本</span><strong>{{ analytics.sample_count }} / 参照 {{ analytics.reference_sample_count }}</strong></div>
              </div>
              <div class="alert alert-info py-2 px-3 small mt-3 mb-0"><i class="bi bi-info-circle-fill me-1" />{{ analytics.profile_source }}</div>
            </div>
          </div>
        </div>

        <div v-else-if="analytics && activeViewTab === 'order_balance'" class="macro-view-pane">
          <div class="row g-3">
            <div v-for="group in [analytics.order_balance.groupAB, analytics.order_balance.groupBA]" :key="group.name" class="col-md-6">
              <div class="order-card">
                <h6><i class="bi bi-shuffle me-1" />{{ group.name }}</h6>
                <ul class="list-unstyled mb-0 mt-2 small text-muted">
                  <li v-for="fact in groupFacts(group)" :key="fact[0]">{{ fact[0] }}：<strong>{{ fact[1] }}</strong></li>
                </ul>
              </div>
            </div>
          </div>
          <div class="stat-conclusion-box" :class="analytics.order_balance.test.available ? 'is-ready' : 'is-pending'">
            <h6><i class="bi bi-clipboard-data me-1" />顺序效应分析边界</h6>
            <p v-if="analytics.order_balance.test.available">Welch t 检验（{{ analytics.order_balance.test.metric }}）：<strong>t = {{ analytics.order_balance.test.t_statistic }}，p = {{ analytics.order_balance.test.p_value }}</strong><span v-if="analytics.order_balance.test.levene_p_value !== null">；Levene p = {{ analytics.order_balance.test.levene_p_value }}</span></p>
            <p>{{ analytics.order_balance.test.interpretation }}</p>
          </div>
        </div>

        <div v-else-if="analytics && activeViewTab === 'dimension_distribution'" class="macro-view-pane">
          <div class="distribution-source"><span>当前展示来源</span><strong>{{ distributionSourceLabel(analytics.dimension_distribution.primary_source) }}</strong></div>
          <div v-if="analytics.dimension_distribution.total" class="distribution-bars">
            <div v-for="row in distributionRows" :key="row.key" class="distribution-row">
              <div><span>{{ row.label }}</span><strong>{{ row.count }} 条 · {{ row.percentage.toFixed(1) }}%</strong></div>
              <div class="distribution-track"><span :class="row.tone" :style="{ width: row.percentage + '%' }" /></div>
            </div>
          </div>
          <div v-else class="macro-empty compact"><i class="bi bi-tags" /><strong>暂无已完成的三分类数据</strong><p>完成双人编码共识/仲裁或使用已启用模型完成候选分类后，这里才会出现真实分布。</p></div>
          <p class="text-muted small mt-3 mb-0">专家共识 {{ analytics.dimension_distribution.expert_consensus_total }} 条 · 生产模型分类 {{ analytics.dimension_distribution.production_model_total }} 条。三个类别的总量不代表连续行为转化，因此不再计算“漏斗转化率”。</p>
        </div>

        <div v-else-if="analytics && activeViewTab === 'pipeline_status'" class="macro-view-pane">
          <div class="row g-3">
            <div class="col-sm-6 col-lg-4"><div class="metric-card"><span>本次数据库聚合耗时</span><h4>{{ analytics.pipeline_status.aggregation_latency_ms }} ms</h4><small>仅为当前请求，不冒充历史 P95</small></div></div>
            <div class="col-sm-6 col-lg-4"><div class="metric-card"><span>ASR 终态成功率</span><h4>{{ valueOrDash(analytics.pipeline_status.asr.success_rate, '%') }}</h4><small>成功 {{ statusCount(analytics.pipeline_status.asr.statuses, 'completed') }} / 终态 {{ analytics.pipeline_status.asr.terminal_count }}</small></div></div>
            <div class="col-sm-6 col-lg-4"><div class="metric-card"><span>候选三分类覆盖率</span><h4>{{ valueOrDash(analytics.pipeline_status.classification.coverage_rate, '%') }}</h4><small>已分类 {{ analytics.pipeline_status.classification.classified_candidates }} / 可分类 {{ analytics.pipeline_status.classification.eligible_candidates }}</small></div></div>
          </div>
          <div class="pipeline-facts">
            <span><i class="bi bi-database-check text-success" />数据库查询可用</span>
            <span>ASR：排队/处理中 {{ statusCount(analytics.pipeline_status.asr.statuses, 'queued', 'processing', 'retry_wait') }}，失败 {{ statusCount(analytics.pipeline_status.asr.statuses, 'failed') }}</span>
            <span>AI 清洗：待复核/已复核 {{ statusCount(analytics.pipeline_status.extraction.statuses, 'reviewing', 'reviewed') }}，待处理 {{ statusCount(analytics.pipeline_status.extraction.statuses, 'queued', 'running', 'retry_wait') }}，失败 {{ statusCount(analytics.pipeline_status.extraction.statuses, 'failed') }}</span>
          </div>
          <p class="text-muted small mt-3 mb-0">数据更新时间：{{ new Date(analytics.generated_at).toLocaleString('zh-CN', { hour12: false }) }}。当前系统尚未持久化请求时延序列，因此不展示无法验证的 P95、连接池百分比或自动重试成功率。</p>
        </div>
      </div>
    </section>
  </AppErrorBoundary>
</template>

<style scoped>
.macro-analytics-dashboard { background: var(--color-surface); border: 1px solid var(--color-border) !important; border-radius: var(--radius-lg); }
.macro-header, .macro-actions, .title-line, .radar-legend, .pipeline-facts { display: flex; align-items: center; gap: .75rem; }
.macro-header { justify-content: space-between; flex-wrap: wrap; margin-bottom: 1rem; }
.macro-actions { flex-wrap: wrap; justify-content: flex-end; }
.title-line { gap: .5rem; }
.class-selector { width: 190px; }
.live-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--color-success); box-shadow: 0 0 7px var(--color-success); }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.macro-view-pane { min-height: 290px; padding-top: .75rem; }
.macro-loading { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; min-height: 280px; }
.skeleton-block { border-radius: var(--radius-md); background: linear-gradient(90deg, var(--color-surface-subtle), color-mix(in srgb, var(--color-primary) 10%, var(--color-surface)), var(--color-surface-subtle)); background-size: 220% 100%; animation: shimmer 1.4s infinite; }
@keyframes shimmer { to { background-position: -220% 0; } }
.radar-wrap { min-height: 250px; display: grid; place-items: center; }
.radar-legend { justify-content: center; font-size: .82rem; }
.radar-legend span { display: inline-flex; align-items: center; gap: .35rem; }
.macro-stats-list { display: grid; gap: .55rem; }
.stat-row { display: flex; justify-content: space-between; align-items: center; gap: 1rem; padding: .72rem .85rem; background: var(--color-surface-subtle); border: 1px solid var(--color-border); border-radius: var(--radius-md); font-size: .86rem; }
.stat-row strong { color: var(--color-text); text-align: right; }
.stat-row small { display: block; color: var(--color-text-muted); font-weight: 500; }
.macro-empty { min-height: 250px; display: grid; place-items: center; align-content: center; gap: .55rem; text-align: center; color: var(--color-text-muted); }
.macro-empty i { font-size: 2rem; color: var(--color-primary); }
.macro-empty p { max-width: 560px; margin: 0; }
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
  .macro-header, .macro-actions { align-items: stretch; }
  .macro-actions, .tab-button-group, .class-selector { width: 100%; }
  .tab-button-group { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .tab-button-group .btn { border-radius: var(--radius-sm) !important; }
  .macro-loading { grid-template-columns: 1fr; }
  .stat-row, .distribution-source, .order-card li { align-items: flex-start; flex-direction: column; gap: .25rem; }
  .stat-row strong { text-align: left; }
}
</style>
