<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import RadarChart from '../charts/RadarChart.vue'
import AppErrorBoundary from '../feedback/AppErrorBoundary.vue'
import { researchApi, type MacroAnalytics, type MacroOrderGroup, type MacroRadarProfile } from '../../api/research'

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
let requestId = 0

const isStudent = computed(() => props.userRole === 'student')
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
const hasRadarData = computed(() => Boolean(primaryRadar.value?.total && primaryRadar.value.scores.length === 3))
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
  const total = distribution?.total ?? 0
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
    expert_consensus: '双人盲编共识/仲裁结果', production_model: '候选文本的当前生产模型分类',
    hybrid: '专家共识与生产模型的分测评组合', none: '暂无可用分类结果'
  })[source]
}

async function fetchRealMacroData() {
  const currentRequest = ++requestId
  isLoading.value = true
  errorMessage.value = ''
  try {
    const response = await researchApi.getMacroAnalytics(selectedClass.value, isStudent.value ? undefined : selectedParticipant.value || undefined)
    if (currentRequest === requestId) analytics.value = response.data
  } catch (error) {
    if (currentRequest !== requestId) return
    analytics.value = null
    errorMessage.value = error instanceof Error ? error.message : '宏观研究数据加载失败'
  } finally {
    if (currentRequest === requestId) isLoading.value = false
  }
}

watch(selectedClass, () => {
  if (selectedParticipant.value) selectedParticipant.value = ''
  else void fetchRealMacroData()
})
watch(selectedParticipant, () => void fetchRealMacroData())
watch(() => props.classGroups, classes => {
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
              <span class="badge bg-primary-subtle text-primary">真实数据聚合</span>
              <span v-if="analytics && !isLoading" class="live-dot" title="已从数据库完成聚合" />
              <h5 class="mb-0">{{ isStudent ? '我的元认知三类构成与群体参照' : '班级宏观实证分析与全链路可观测大屏' }}</h5>
            </div>
            <p class="text-muted small mb-0 mt-1">{{ isStudent ? '仅展示本人、所在班级与全体样本的三类汇总占比，不披露其他学生明细。缺失数据不会使用演示值填充。' : '按真实三分类证据聚合学生、班级与全体样本，并同步展示研究处理链路；缺失数据不会使用演示值填充。' }}</p>
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
            <button class="btn btn-sm btn-outline-secondary refresh-button" title="刷新数据库聚合结果" :disabled="isLoading" @click="fetchRealMacroData"><i class="bi" :class="isLoading ? 'bi-arrow-repeat spin' : 'bi-arrow-clockwise'" /></button>
            <div v-if="!isStudent" class="btn-group btn-group-sm tab-button-group">
              <button class="btn" :class="activeViewTab === 'macro_radar' ? 'btn-primary' : 'btn-outline-secondary'" @click="activeViewTab = 'macro_radar'"><i class="bi bi-pie-chart me-1" />三类占比</button>
              <button class="btn" :class="activeViewTab === 'order_balance' ? 'btn-primary' : 'btn-outline-secondary'" @click="activeViewTab = 'order_balance'"><i class="bi bi-shuffle me-1" />任务顺序</button>
              <button class="btn" :class="activeViewTab === 'dimension_distribution' ? 'btn-primary' : 'btn-outline-secondary'" @click="activeViewTab = 'dimension_distribution'"><i class="bi bi-bar-chart-steps me-1" />数量分布</button>
              <button class="btn" :class="activeViewTab === 'pipeline_status' ? 'btn-primary' : 'btn-outline-secondary'" @click="activeViewTab = 'pipeline_status'"><i class="bi bi-activity me-1" />处理链路</button>
            </div>
          </div>
        </div>

        <div v-if="errorMessage" class="alert alert-danger mb-0"><i class="bi bi-exclamation-triangle me-2" />{{ errorMessage }}</div>
        <div v-else-if="isLoading && !analytics" class="macro-loading" aria-label="正在聚合研究数据"><span v-for="index in 4" :key="index" class="skeleton-block" /></div>

        <div v-else-if="analytics && (isStudent || activeViewTab === 'macro_radar')" class="macro-view-pane">
          <div v-if="!hasRadarData" class="macro-empty"><i class="bi bi-radar" /><strong>当前范围暂无三分类证据</strong><p>完成候选复核并形成专家编码，或使用已启用模型完成三分类后，系统才会按真实记录计算占比。</p></div>
          <div v-else class="row g-4 align-items-center">
            <div class="col-xl-6 text-center"><div class="radar-wrap"><RadarChart :scores="primaryRadar?.scores ?? []" :comparison-series="radarComparisons" :name="primaryRadar?.label ?? '当前范围'" value-unit="%" :height="350" /></div></div>
            <div class="col-xl-6">
              <div class="composition-note"><i class="bi bi-info-circle-fill" /><span>三条轴合计约为 100%，表示三类元认知证据的<strong>构成比例</strong>，不是能力高低分数，也不是预设常模。</span></div>
              <div class="macro-stats-list mt-3">
                <div v-for="row in radarRows" :key="row.key" class="stat-row"><span>{{ row.label }}</span><strong>{{ row.percentage.toFixed(1) }}% <small>{{ row.count }} 条<span v-for="comparison in row.comparisons" :key="comparison.label"> · {{ comparison.label }} {{ comparison.percentage.toFixed(1) }}%</span></small></strong></div>
                <div class="stat-row"><span>当前统计范围</span><strong>{{ primaryRadar?.label }}<small>三类证据 {{ primaryRadar?.total }} 条 · 来自 {{ primaryRadar?.sample_count }} 次测评</small></strong></div>
                <div class="stat-row"><span>结果来源</span><strong>{{ distributionSourceLabel(primaryRadar?.primary_source ?? 'none') }}</strong></div>
              </div>
              <div class="alert alert-info py-2 px-3 small mt-3 mb-0"><i class="bi bi-shield-check me-1" />{{ analytics.profile_source }}</div>
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
          <p class="text-muted small mt-3 mb-0">专家共识 {{ analytics.dimension_distribution.expert_consensus_total }} 条 · 生产模型分类 {{ analytics.dimension_distribution.production_model_total }} 条。三个类别的总量不代表连续行为转化，因此不再计算“漏斗转化率”。</p>
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
.macro-analytics-dashboard {
  background: var(--color-surface);
  border: 1px solid var(--color-border) !important;
  border-radius: var(--radius-xl);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.04);
}
.macro-header, .macro-actions, .title-line, .pipeline-facts { display: flex; align-items: center; gap: .75rem; }
.macro-header { justify-content: space-between; flex-wrap: wrap; margin-bottom: 1.25rem; }
.macro-actions { flex-wrap: wrap; justify-content: flex-end; }
.title-line { gap: .65rem; flex-wrap: wrap; align-items: center; }
.title-line h5 { font-size: 1.18rem; font-weight: 700; color: var(--color-text); }
.class-selector { width: 190px; }
.participant-selector { width: 220px; }
.live-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--color-success); box-shadow: 0 0 7px var(--color-success); }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.macro-view-pane { min-height: 270px; padding-top: .5rem; }
.macro-loading { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; min-height: 280px; }
.skeleton-block { border-radius: var(--radius-md); background: linear-gradient(90deg, var(--color-surface-subtle), color-mix(in srgb, var(--color-primary) 10%, var(--color-surface)), var(--color-surface-subtle)); background-size: 220% 100%; animation: shimmer 1.4s infinite; }
@keyframes shimmer { to { background-position: -220% 0; } }
.radar-wrap { min-height: 300px; display: grid; place-items: center; }
.composition-note { display: flex; gap: .65rem; align-items: flex-start; padding: .8rem .9rem; border: 1px solid color-mix(in srgb, var(--color-primary) 28%, var(--color-border)); border-radius: var(--radius-md); background: color-mix(in srgb, var(--color-primary) 8%, var(--color-surface)); color: var(--color-text-muted); font-size: .84rem; }
.composition-note i { color: var(--color-primary); }
.composition-note strong { color: var(--color-text); }
.macro-stats-list { display: grid; gap: .55rem; }
.stat-row { display: flex; justify-content: space-between; align-items: center; gap: 1rem; padding: .72rem .85rem; background: var(--color-surface-subtle); border: 1px solid var(--color-border); border-radius: var(--radius-md); font-size: .86rem; }
.stat-row strong { color: var(--color-text); text-align: right; }
.stat-row small { display: block; max-width: 420px; color: var(--color-text-muted); font-weight: 500; line-height: 1.5; }
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
  .macro-actions, .tab-button-group, .class-selector, .participant-selector { width: 100%; }
  .refresh-button { min-height: 40px; }
  .tab-button-group { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .tab-button-group .btn { border-radius: var(--radius-sm) !important; }
  .macro-loading { grid-template-columns: 1fr; }
  .stat-row, .distribution-source, .order-card li { align-items: flex-start; flex-direction: column; gap: .25rem; }
  .stat-row strong { text-align: left; }
}
</style>
