<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { researchApi, type MethodTemplate, type TemplateAudit, type ModelDatasetSource, type ModelEvaluation, type ModelEvaluationIndex, type ModelEvaluationVersion, type ModelExperimentType, type ModelHyperparameterCatalog, type ModelHyperparameterValue, type ModelTrainingAudit, type ModelTrainingDataset, type ModelTrainingJob } from '../api/research'
import { adminApi, type NarrationSlot } from '../api/admin'
import { parseApiDate } from '../utils/datetime'
import { confirmAction, notify } from '../composables/useUiFeedback'
import AppModal from '../components/ui/AppModal.vue'
import ModelPerformanceGuideOrb from '../components/training/ModelPerformanceGuideOrb.vue'

const templates = ref<MethodTemplate[]>([])
const selectedKey = ref<MethodTemplate['template_key']>('report_prompt')
const content = ref('')
const version = ref('draft-2')
const isLoading = ref(true)
const isSaving = ref(false)
const templateErrorMessage = ref('')
const templateSuccessMessage = ref('')
const viewedTemplateId = ref<string | null>(null)
const activatingTemplateId = ref<string | null>(null)
const templateAudits = ref<TemplateAudit[]>([])
const auditLoading = ref(true)
const questionnaireEnabled = ref(false)
const savedQuestionnaireEnabled = ref(false)
const behaviorWeightPercent = ref(60)
const savedBehaviorWeightPercent = ref(60)
const questionnaireWeightPercent = computed(() => 100 - behaviorWeightPercent.value)
const hasProtocolChanges = computed(() =>
  questionnaireEnabled.value !== savedQuestionnaireEnabled.value ||
  behaviorWeightPercent.value !== savedBehaviorWeightPercent.value
)
const protocolConfigLoading = ref(true)
const protocolConfigSaving = ref(false)
const protocolConfigUpdatedAt = ref<string | null>(null)
const protocolErrorMessage = ref('')
const protocolSuccessMessage = ref('')
const narrationSlots = ref<NarrationSlot[]>([])
const narrationLoading = ref(true)
const narrationBusyKey = ref('')
const narrationErrorMessage = ref('')
const narrationAudioUrls = ref<Record<string, string>>({})
const trainingJobs = ref<ModelTrainingJob[]>([])
const modelEvaluationIndex = ref<ModelEvaluationIndex | null>(null)
const modelEvaluationLoading = ref(true)
const modelEvaluationError = ref('')
const trainingVersion = ref(`gold_${new Date().toISOString().slice(0, 10).replace(/-/g, '')}`)
const selectedExperiment = ref<ModelExperimentType>('tfidf_linear_svc')
const trainingLoading = ref(true)
const trainingCreating = ref(false)
const trainingBusyId = ref('')
const expandedTrainingJobId = ref('')
const expandedTrainingGroupKey = ref('')
const trainingAudits = ref<ModelTrainingAudit[]>([])
const trainingAuditLoading = ref(true)
const trainingCreateOpen = ref(false)
const trainingCreateMode = ref<'single' | 'custom' | 'suite'>('single')
const selectedCustomExperiments = ref<ModelExperimentType[]>([
  'tfidf_linear_svc',
  'embedding_linear_svc'
])
const trainingDatasetSource = ref<ModelDatasetSource>('system_gold')
const uploadedTrainingDatasets = ref<ModelTrainingDataset[]>([])
const selectedTrainingDatasetId = ref('')
const trainingDatasetName = ref('')
const trainingDatasetFile = ref<File | null>(null)
const trainingDatasetLoading = ref(false)
const trainingTemplateDownloading = ref(false)
const selectedComparisonGroupKey = ref('')
const historicalComparisonModelIds = ref<string[]>([])
const historicalComparisonSearch = ref('')
const enlargedRocJob = ref<ModelEvaluation | null>(null)
const hyperparameterCatalog = ref<ModelHyperparameterCatalog | null>(null)
const tuningEnabled = ref<Partial<Record<ModelExperimentType, boolean>>>({})
const trainingParameters = ref<Partial<Record<ModelExperimentType, Record<string, ModelHyperparameterValue>>>>({})
let trainingPoll: number | null = null
let trainingGroupsInitialized = false
let historicalComparisonInitialized = false

const experimentDefinitions: Array<{
  value: ModelExperimentType
  title: string
  feature: string
  classifier: string
  hint: string
}> = [
  { value: 'tfidf_linear_svc', title: '轻量生产基线', feature: 'TF-IDF', classifier: 'LinearSVC', hint: '不调用外部接口，适合 2C4G' },
  { value: 'embedding_linear_svc', title: '向量线性分类', feature: '远程 Embedding', classifier: 'LinearSVC', hint: '比较语义向量与轻量分类器' },
  { value: 'embedding_logistic', title: '向量概率分类', feature: '远程 Embedding', classifier: 'LogisticRegression', hint: '提供可解释的分类概率' },
  { value: 'embedding_random_forest', title: '向量非线性对照', feature: '远程 Embedding', classifier: 'RandomForest', hint: '作为非线性模型对照' },
  { value: 'embedding_xgboost', title: '梯度提升对照', feature: '远程 Embedding', classifier: 'XGBoost', hint: '正则化梯度提升树' },
  { value: 'embedding_lightgbm', title: '叶子优先提升', feature: '远程 Embedding', classifier: 'LightGBM', hint: '高效叶子优先生长模型' },
  { value: 'embedding_catboost', title: '对称提升树', feature: '远程 Embedding', classifier: 'CatBoost', hint: '对称树梯度提升对照' }
]

function jobExperiment(job: ModelTrainingJob): ModelExperimentType {
  const value = job.config_snapshot?.experiment_type
  if (typeof value === 'string' && experimentDefinitions.some(item => item.value === value)) {
    return value as ModelExperimentType
  }
  const feature = job.config_snapshot?.feature
  const classifier = job.config_snapshot?.classifier
  if (feature === 'tfidf') return 'tfidf_linear_svc'
  if (classifier === 'logistic') return 'embedding_logistic'
  if (classifier === 'random_forest') return 'embedding_random_forest'
  if (classifier === 'xgboost') return 'embedding_xgboost'
  if (classifier === 'lightgbm') return 'embedding_lightgbm'
  if (classifier === 'catboost') return 'embedding_catboost'
  return 'embedding_linear_svc'
}

function experimentDefinition(job: ModelTrainingJob) {
  return experimentDefinitions.find(item => item.value === jobExperiment(job)) ?? experimentDefinitions[1]
}

function comparisonIdentity(job: ModelTrainingJob) {
  const configuredId = job.config_snapshot?.comparison_group_id
  const configuredLabel = job.config_snapshot?.comparison_group_label
  if (typeof configuredId === 'string' && configuredId) {
    return {
      key: `suite:${configuredId}`,
      label: typeof configuredLabel === 'string' && configuredLabel ? configuredLabel : job.version
    }
  }
  const match = job.version.match(/^(.*)-(tfidf-svc|emb-svc|emb-logistic|emb-rf|emb-xgb|emb-lgbm|emb-cat)(?:-retry\d+)*$/)
  if (!match || !job.dataset_fingerprint) return null
  return { key: `legacy:${job.dataset_fingerprint}:${match[1]}`, label: match[1] }
}

function trainingVersionIdentity(job: ModelTrainingJob) {
  const comparison = comparisonIdentity(job)
  if (comparison) return comparison
  const rootVersion = job.version.replace(/(?:-retry\d+)+$/, '')
  return { key: `version:${rootVersion}`, label: rootVersion }
}

const trainingVersionGroups = computed(() => {
  const groups = new Map<string, {
    key: string
    label: string
    jobs: ModelTrainingJob[]
    latestAt: number
  }>()
  trainingJobs.value.forEach(job => {
    const identity = trainingVersionIdentity(job)
    const timestamp = parseApiDate(job.created_at).getTime() || 0
    const existing = groups.get(identity.key)
    if (existing) {
      existing.jobs.push(job)
      existing.latestAt = Math.max(existing.latestAt, timestamp)
      return
    }
    groups.set(identity.key, { ...identity, jobs: [job], latestAt: timestamp })
  })
  return [...groups.values()]
    .map(group => ({
      ...group,
      jobs: group.jobs.sort((left, right) => {
        const timeDifference = parseApiDate(right.created_at).getTime() - parseApiDate(left.created_at).getTime()
        return timeDifference || right.id.localeCompare(left.id)
      })
    }))
    .sort((left, right) => right.latestAt - left.latestAt)
})

function trainingGroupSummary(jobs: ModelTrainingJob[]) {
  const completed = jobs.filter(job => job.status === 'completed').length
  const running = jobs.filter(job => ['queued', 'running'].includes(job.status)).length
  const failed = jobs.filter(job => ['failed', 'cancelled'].includes(job.status)).length
  const parts = [`完成 ${completed}/${jobs.length}`]
  if (running) parts.push(`进行中 ${running}`)
  if (failed) parts.push(`异常 ${failed}`)
  return parts.join(' · ')
}

function toggleTrainingGroup(key: string) {
  expandedTrainingGroupKey.value = expandedTrainingGroupKey.value === key ? '' : key
  expandedTrainingJobId.value = ''
}

const comparisonGroups = computed(() => {
  const groups = new Map<string, {
    key: string
    label: string
    jobs: ModelTrainingJob[]
    datasetFingerprint: string
    latestAt: number
  }>()
  trainingJobs.value.forEach(job => {
    const identity = comparisonIdentity(job)
    if (!identity) return
    const timestamp = parseApiDate(job.created_at).getTime() || 0
    const existing = groups.get(identity.key)
    if (existing) {
      existing.jobs.push(job)
      existing.latestAt = Math.max(existing.latestAt, timestamp)
      return
    }
    groups.set(identity.key, {
      ...identity,
      jobs: [job],
      datasetFingerprint: job.dataset_fingerprint || '',
      latestAt: timestamp
    })
  })
  return [...groups.values()]
    .filter(group => new Set(group.jobs.map(jobExperiment)).size >= 2)
    .sort((a, b) => b.latestAt - a.latestAt)
})

const activeComparisonGroup = computed(() =>
  comparisonGroups.value.find(group => group.key === selectedComparisonGroupKey.value)
  ?? comparisonGroups.value[0]
  ?? null
)

const allExperimentTypes = experimentDefinitions.map(item => item.value)

function expectedComparisonExperiments(jobs: ModelTrainingJob[]): ModelExperimentType[] {
  for (const job of jobs) {
    const configured = job.config_snapshot?.comparison_expected_experiments
    if (!Array.isArray(configured)) continue
    const valid = allExperimentTypes.filter(type => configured.includes(type))
    if (valid.length >= 2) return valid
  }
  const existing = allExperimentTypes.filter(type => jobs.some(job => jobExperiment(job) === type))
  return existing.length >= 2 ? existing : allExperimentTypes
}

const activeComparisonExperimentTypes = computed(() =>
  expectedComparisonExperiments(activeComparisonGroup.value?.jobs ?? []))

const comparisonJobs = computed(() => experimentDefinitions
  .filter(definition => activeComparisonExperimentTypes.value.includes(definition.value))
  .map(definition => {
  const candidates = (activeComparisonGroup.value?.jobs.filter(
    item => jobExperiment(item) === definition.value
  ) ?? []).sort((left, right) => {
    const timeDifference = parseApiDate(right.created_at).getTime() - parseApiDate(left.created_at).getTime()
    return timeDifference || right.id.localeCompare(left.id)
  })
  return {
    ...definition,
    job: candidates[0]
  }
}))

const completedComparisonJobs = computed(() => comparisonJobs.value
  .filter((item): item is typeof item & { job: ModelTrainingJob } => item.job?.status === 'completed' && Boolean(item.job.metrics)))

const comparisonIsComplete = computed(() => {
  const jobs = comparisonJobs.value.map(item => item.job)
  return jobs.length === activeComparisonExperimentTypes.value.length
    && jobs.every(job => job?.status === 'completed' && Boolean(job.metrics))
    && jobs.every(job => Boolean(job?.dataset_fingerprint))
    && new Set(jobs.map(job => job?.dataset_fingerprint)).size === 1
})

const bestComparisonJobId = computed(() => {
  if (!comparisonIsComplete.value) return ''
  return [...completedComparisonJobs.value]
    .sort((left, right) => {
      const macroDifference = (right.job.metrics?.macro_f1 ?? -1) - (left.job.metrics?.macro_f1 ?? -1)
      if (macroDifference !== 0) return macroDifference
      const weightedDifference = (right.job.metrics?.weighted_f1 ?? -1) - (left.job.metrics?.weighted_f1 ?? -1)
      if (weightedDifference !== 0) return weightedDifference
      return left.job.version.localeCompare(right.job.version, 'zh-CN')
    })[0]?.job.id ?? ''
})

const metricDefinitions = [
  {
    key: 'macro_f1' as const,
    title: 'Macro-F1',
    summary: '监控、调控、评估三个类别的 F1 先分别计算，再等权平均。',
    use: '三类元认知样本不平衡、且三个维度同样重要时，作为首要选择指标。',
    caution: '仍需查看各类别 F1；平均值可能掩盖“评估”类完全失效。'
  },
  {
    key: 'weighted_f1' as const,
    title: 'Weighted-F1',
    summary: '按每个类别的样本数量加权汇总 F1。',
    use: '希望了解模型在当前真实样本构成下的总体表现时，用作 Macro-F1 的补充。',
    caution: '多数类权重较大，数值较高不代表少数类表现可靠，不能单独决定启用。'
  },
  {
    key: 'macro_auc_ovr' as const,
    title: 'Macro-AUC',
    summary: '将三个元认知类别逐一视为“该类/其他类”，衡量模型对类别的整体区分排序能力。',
    use: '需要概率、低置信度复核或阈值策略时，在具备可比概率输出的模型之间比较。',
    caution: 'AUC 不等于分类正确率，也不代表概率已经校准；LinearSVC 无概率输出时显示为空。'
  }
]

const classF1Definitions = [
  { key: '1', code: 'monitoring', label: '监控', colorClass: 'is-monitoring' },
  { key: '2', code: 'regulation', label: '调控', colorClass: 'is-regulation' },
  { key: '3', code: 'evaluation', label: '评估', colorClass: 'is-evaluation' }
] as const

const rocCurveDefinitions = [
  { key: 'macro', label: 'Macro', color: '#ec4899', width: 3 },
  { key: '1', label: '监控', color: '#6366f1', width: 1.8 },
  { key: '2', label: '调控', color: '#06b6d4', width: 1.8 },
  { key: '3', label: '评估', color: '#f59e0b', width: 1.8 }
] as const

const trainingLabelNames: Record<number, string> = {
  0: '非元认知（历史）', 1: '监控', 2: '控制/调控', 3: '评估'
}

function trainingLabels(job: ModelTrainingJob) {
  const metricLabels = Object.keys(job.metrics?.per_class || {}).map(Number).filter(Number.isInteger)
  if (metricLabels.length) return metricLabels.sort((left, right) => left - right)
  const distributionLabels = Object.keys(job.label_distribution || {}).map(Number).filter(Number.isInteger)
  return distributionLabels.length ? distributionLabels.sort((left, right) => left - right) : [1, 2, 3]
}

function trainingLabelName(label: number) {
  return trainingLabelNames[label] || `标签${label}`
}

function metricPercent(value?: number | null) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 0
  return Math.max(0, Math.min(100, value * 100))
}

type OverfitRiskLevel = 'low' | 'medium' | 'high' | 'unknown'

function trainingGeneralizationGap(job: ModelTrainingJob) {
  const folds = job.metrics?.folds ?? []
  const validFolds = folds.filter(
    fold => typeof fold.train_macro_f1 === 'number' && typeof fold.macro_f1 === 'number'
  )
  if (!validFolds.length) return null
  const trainMean = validFolds.reduce((sum, fold) => sum + (fold.train_macro_f1 ?? 0), 0) / validFolds.length
  const testMean = validFolds.reduce((sum, fold) => sum + fold.macro_f1, 0) / validFolds.length
  return Math.max(0, trainMean - testMean)
}

function overfitRisk(job: ModelTrainingJob | ModelEvaluation | null) {
  const gap = !job
    ? null
    : 'model_id' in job
      ? job.cross_validation.train_test_macro_f1_gap
      : trainingGeneralizationGap(job)
  let level: OverfitRiskLevel = 'unknown'
  if (typeof gap === 'number' && Number.isFinite(gap)) {
    level = gap <= 0.08 ? 'low' : gap <= 0.15 ? 'medium' : 'high'
  }
  const definitions: Record<OverfitRiskLevel, { label: string; tone: string; message: string }> = {
    low: {
      label: '过拟合风险低',
      tone: 'is-low',
      message: '训练集与折外预测差距不超过 0.080，当前未见明显过拟合信号。'
    },
    medium: {
      label: '过拟合风险中等',
      tone: 'is-medium',
      message: '训练集指标明显高于折外预测，启用前应检查五折波动、类别 F1，并优先补充样本或加强正则化。'
    },
    high: {
      label: '过拟合风险高',
      tone: 'is-high',
      message: '训练集与未见数据的性能差距较大。即使 Macro-F1 当前最高，也不建议未经外部验证直接启用。'
    },
    unknown: {
      label: '过拟合风险待计算',
      tone: 'is-unknown',
      message: '该历史训练产物缺少训练折 Macro-F1，无法计算训练—折外差距。'
    }
  }
  return { gap, level, ...definitions[level] }
}

function crossEntropyPercent(value?: number) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 0
  return Math.max(2, Math.min(100, value / latestCrossEntropyMax.value * 100))
}

function rocPath(curve?: { fpr: number[]; tpr: number[] }) {
  if (!curve || !curve.fpr.length || curve.fpr.length !== curve.tpr.length) return ''
  return curve.fpr.map((fpr, index) => {
    const x = 38 + Math.max(0, Math.min(1, fpr)) * 244
    const y = 12 + (1 - Math.max(0, Math.min(1, curve.tpr[index] ?? 0))) * 164
    return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
}

function openRoc(job: ModelTrainingJob | ModelEvaluation) {
  if ('model_id' in job) {
    if (job.roc_curves) enlargedRocJob.value = job
    return
  }
  const evaluation = latestPerformanceModels.value.find(item => item.model_id === job.id)
  if (evaluation?.roc_curves) {
    enlargedRocJob.value = evaluation
  }
}

function performanceClassF1(job: ModelEvaluation, labelId: string) {
  return job.per_class.find(item => String(item.label_id) === labelId)?.f1
}

async function openTrainingJobDetails(job: ModelTrainingJob) {
  const group = trainingVersionGroups.value.find(item => item.jobs.some(candidate => candidate.id === job.id))
  if (group) expandedTrainingGroupKey.value = group.key
  expandedTrainingJobId.value = job.id
  await nextTick()
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  document.getElementById(`training-job-${job.id}`)?.scrollIntoView({
    behavior: reduceMotion ? 'auto' : 'smooth',
    block: 'center'
  })
}

function labelDistributionText(distribution?: Record<string, number>) {
  if (!distribution) return '历史版本未记录'
  return Object.entries(distribution)
    .sort(([left], [right]) => Number(left) - Number(right))
    .map(([label, count]) => `${trainingLabelName(Number(label))} ${count}`)
    .join(' · ')
}

function splitStrategyLabel(job: ModelTrainingJob) {
  return job.metrics?.split_strategy === 'subject_grouped_stratified_5fold'
    ? '被试级分组五折'
    : '句子级分层五折'
}

const performanceVersionGroups = computed(() => modelEvaluationIndex.value?.versions ?? [])
const latestPerformanceGroup = computed(() => {
  const versions = performanceVersionGroups.value
  const latestId = modelEvaluationIndex.value?.latest_version_id
  return versions.find(item => item.version_id === latestId) ?? versions[0] ?? null
})
const latestPerformanceModels = computed(() => latestPerformanceGroup.value?.models ?? [])
const latestCrossEntropyModels = computed(() => latestPerformanceModels.value.filter(
  item => typeof item.summary.cross_entropy === 'number'
))
const latestCrossEntropyMax = computed(() => Math.max(
  ...latestCrossEntropyModels.value.map(item => item.summary.cross_entropy ?? 0),
  0.001
))
const historicalPerformanceGroups = computed(() => performanceVersionGroups.value.filter(
  item => item.version_id !== latestPerformanceGroup.value?.version_id
))

function bestPerformanceModel(group: ModelEvaluationVersion | null): ModelEvaluation | null {
  if (!group?.best_model_id) return null
  return group.models.find(item => item.model_id === group.best_model_id) ?? null
}

const latestBestPerformanceJob = computed(() => bestPerformanceModel(latestPerformanceGroup.value))

const historicalComparisonMetricDefinitions: Array<{
  key: keyof ModelEvaluation['summary']
  title: string
  note: string
}> = [
  { key: 'accuracy', title: 'Accuracy', note: '折外样本预测正确比例' },
  { key: 'macro_precision', title: 'Macro-Precision', note: '三类 Precision 等权平均' },
  { key: 'weighted_precision', title: 'Weighted-Precision', note: '按真实类别样本数加权的 Precision' },
  { key: 'macro_recall', title: 'Macro-Recall', note: '三类 Recall 等权平均' },
  { key: 'weighted_recall', title: 'Weighted-Recall', note: '按真实类别样本数加权的 Recall' },
  { key: 'macro_specificity', title: 'Macro-Specificity', note: '三类 Specificity 等权平均' },
  { key: 'macro_f1', title: 'Macro-F1', note: '首要比较指标' },
  { key: 'weighted_f1', title: 'Weighted-F1', note: '按真实类别样本数加权' },
  { key: 'macro_auc_ovr', title: 'Macro-AUC', note: '一对其余折外区分能力' }
]

const historicalComparisonGroups = computed(() => performanceVersionGroups.value.map(group => ({
  ...group,
  models: group.models.filter(model => {
    const search = historicalComparisonSearch.value.trim().toLocaleLowerCase('zh-CN')
    if (!search) return true
    return [group.display_version, group.dataset_version, model.model_version, evaluationModelName(model)]
      .some(value => String(value || '').toLocaleLowerCase('zh-CN').includes(search))
  })
})).filter(group => group.models.length))

const historicalComparisonOptions = computed(() => performanceVersionGroups.value.flatMap(group =>
  group.models.map(model => ({ group, model }))))

const selectedHistoricalComparisonModels = computed(() => {
  const selected = new Set(historicalComparisonModelIds.value)
  return historicalComparisonOptions.value
    .filter(item => selected.has(item.model.model_id))
})

const selectedHistoricalBestModelId = computed(() => [...selectedHistoricalComparisonModels.value]
  .sort((left, right) => {
    const macroF1 = (right.model.summary.macro_f1 ?? -1) - (left.model.summary.macro_f1 ?? -1)
    if (macroF1 !== 0) return macroF1
    const macroRecall = (right.model.summary.macro_recall ?? -1) - (left.model.summary.macro_recall ?? -1)
    if (macroRecall !== 0) return macroRecall
    const weightedF1 = (right.model.summary.weighted_f1 ?? -1) - (left.model.summary.weighted_f1 ?? -1)
    if (weightedF1 !== 0) return weightedF1
    return left.model.model_version.localeCompare(right.model.model_version, 'zh-CN')
  })[0]?.model.model_id ?? '')

const selectedHistoricalBestEntry = computed(() => selectedHistoricalComparisonModels.value
  .find(item => item.model.model_id === selectedHistoricalBestModelId.value) ?? null)

function isSelectedHistoricalBestModel(model: ModelEvaluation) {
  return model.model_id === selectedHistoricalBestModelId.value
}

function isBestComparableValue(value: number | null | undefined, values: Array<number | null | undefined>, lowerIsBetter = false) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return false
  const valid = values.filter((item): item is number => typeof item === 'number' && Number.isFinite(item))
  if (!valid.length) return false
  const best = lowerIsBetter ? Math.min(...valid) : Math.max(...valid)
  return Math.abs(value - best) < 1e-12
}

function isHistoricalSummaryMetricBest(model: ModelEvaluation, key: keyof ModelEvaluation['summary']) {
  return isBestComparableValue(
    model.summary[key],
    selectedHistoricalComparisonModels.value.map(item => item.model.summary[key]),
    key === 'cross_entropy'
  )
}

function isHistoricalClassF1Best(model: ModelEvaluation, labelId: string) {
  return isBestComparableValue(
    performanceClassF1(model, labelId),
    selectedHistoricalComparisonModels.value.map(item => performanceClassF1(item.model, labelId))
  )
}

function isHistoricalCvMetricBest(
  model: ModelEvaluation,
  key: 'macro_f1_range' | 'train_test_macro_f1_gap'
) {
  return isBestComparableValue(
    model.cross_validation[key],
    selectedHistoricalComparisonModels.value.map(item => item.model.cross_validation[key]),
    true
  )
}

const historicalComparisonCompatibility = computed(() => {
  const selected = selectedHistoricalComparisonModels.value
  if (selected.length < 2) {
    return { comparable: false, tone: 'is-empty', message: '请至少选择两项历史模型结果开始比较。' }
  }
  const fingerprints = new Set(selected.map(item => item.model.dataset.fingerprint).filter(Boolean))
  const hasMissingFingerprint = selected.some(item => !item.model.dataset.fingerprint)
  const labelOrders = new Set(selected.map(item => item.model.labels.map(label => label.id).join(',')))
  if (!hasMissingFingerprint && fingerprints.size === 1 && labelOrders.size === 1) {
    return {
      comparable: true,
      tone: 'is-comparable',
      message: '所选结果使用同一数据指纹和标签顺序，可进行严格横向比较。'
    }
  }
  return {
    comparable: false,
    tone: 'is-reference',
    message: '所选结果来自不同数据快照或标签顺序，仅适合观察迭代趋势，不应据此直接判定算法优劣。'
  }
})

function toggleHistoricalComparisonModel(modelId: string) {
  historicalComparisonModelIds.value = historicalComparisonModelIds.value.includes(modelId)
    ? historicalComparisonModelIds.value.filter(id => id !== modelId)
    : [...historicalComparisonModelIds.value, modelId]
}

function selectHistoricalVersionBestModels() {
  historicalComparisonModelIds.value = performanceVersionGroups.value
    .map(group => bestPerformanceModel(group)?.model_id)
    .filter((id): id is string => Boolean(id))
}

function clearHistoricalComparison() {
  historicalComparisonModelIds.value = []
}

function initializeHistoricalComparisonSelection() {
  const validIds = new Set(historicalComparisonOptions.value.map(item => item.model.model_id))
  historicalComparisonModelIds.value = historicalComparisonModelIds.value.filter(id => validIds.has(id))
  if (historicalComparisonInitialized && historicalComparisonModelIds.value.length) return
  const defaults = performanceVersionGroups.value
    .slice(0, 2)
    .map(group => bestPerformanceModel(group)?.model_id)
    .filter((id): id is string => Boolean(id))
  if (defaults.length < 2) {
    historicalComparisonOptions.value.forEach(item => {
      if (defaults.length < 2 && !defaults.includes(item.model.model_id)) defaults.push(item.model.model_id)
    })
  }
  historicalComparisonModelIds.value = defaults
  historicalComparisonInitialized = true
}

function historicalComparisonCsvCell(value: unknown) {
  const text = value == null ? '' : String(value)
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

function exportHistoricalModelComparison() {
  if (selectedHistoricalComparisonModels.value.length < 2) {
    notify('请至少选择两项模型结果后再导出', 'warning')
    return
  }
  const headers = [
    '训练版本', '模型版本', '特征与分类器', '数据版本', '训练时间', '样本数',
    'Accuracy', 'Macro-Precision', 'Weighted-Precision', 'Macro-Recall', 'Weighted-Recall', 'Macro-Specificity', 'Macro-F1',
    'Weighted-F1', 'Macro-AUC(Pooled OOF)', '交叉熵', '监控F1', '调控F1', '评估F1',
    '五折Macro-F1均值', '五折Macro-F1标准差',
    '五折Macro-AUC均值', '五折Macro-AUC标准差', '折间极差', '训练-折外差距', '过拟合风险',
    '数据指纹', '验证方式'
  ]
  const rows = selectedHistoricalComparisonModels.value.map(({ group, model }) => [
    group.display_version, model.model_version, evaluationModelName(model), model.dataset.version,
    model.trained_at, model.dataset.sample_count, model.summary.accuracy,
    model.summary.macro_precision, model.summary.weighted_precision,
    model.summary.macro_recall, model.summary.weighted_recall, model.summary.macro_specificity,
    model.summary.macro_f1, model.summary.weighted_f1, model.summary.macro_auc_ovr,
    model.summary.cross_entropy, performanceClassF1(model, '1'), performanceClassF1(model, '2'),
    performanceClassF1(model, '3'), model.cross_validation.macro_f1_mean,
    model.cross_validation.macro_f1_std,
    model.cross_validation.macro_auc_mean,
    model.cross_validation.macro_auc_std,
    model.cross_validation.macro_f1_range,
    model.cross_validation.train_test_macro_f1_gap, overfitRisk(model).label,
    model.dataset.fingerprint, evaluationSplitLabel(model)
  ])
  const content = [headers, ...rows]
    .map(row => row.map(historicalComparisonCsvCell).join(','))
    .join('\r\n')
  const url = URL.createObjectURL(new Blob([`\uFEFF${content}`], { type: 'text/csv;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `历史模型效果对比-${new Date().toISOString().slice(0, 10)}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
  notify(`已导出 ${rows.length} 项历史模型效果对比`, 'success')
}

function performanceVerdict(job: ModelEvaluation | null) {
  const macroF1 = job?.summary.macro_f1 ?? 0
  const auc = job?.summary.macro_auc_ovr
  const accuracy = job?.summary.accuracy ?? 0
  const classF1 = job?.per_class.map(item => item.f1).filter((value): value is number => typeof value === 'number') ?? []
  const minimumClassF1 = classF1.length ? Math.min(...classF1) : 0
  const range = job?.cross_validation.macro_f1_range
  const trainF1 = job?.cross_validation.train_macro_f1_mean
  const generalizationGap = job?.cross_validation.train_test_macro_f1_gap
  const risk = overfitRisk(job)
  let level = '仍需优化'
  let tone = 'is-caution'
  if (macroF1 >= .7 && (typeof auc !== 'number' || auc >= .85) && minimumClassF1 >= .6) {
    level = '内部验证表现较强'
    tone = 'is-strong'
  } else if (macroF1 >= .6 && (typeof auc !== 'number' || auc >= .75) && minimumClassF1 >= .45) {
    level = '具备初步区分能力'
    tone = 'is-developing'
  }
  if (risk.level === 'high') {
    level = '指标领先，但过拟合风险高'
    tone = 'is-caution'
  } else if (risk.level === 'medium' && tone === 'is-strong') {
    level = '内部表现较强，需警惕过拟合'
    tone = 'is-developing'
  }
  const findings = [
    `五折折外 Accuracy ${metric(accuracy)}、Macro-F1 ${metric(macroF1)}${typeof auc === 'number' ? `、Macro-AUC ${metric(auc)}` : ''}；结论来自真实测试折预测，不是训练集自测。`,
    `最低类别 F1 为 ${metric(minimumClassF1)}，${minimumClassF1 >= .6 ? '三类识别相对均衡' : '仍有类别识别薄弱，需结合各类 Recall 和混淆矩阵定位'}。`,
    typeof range === 'number'
      ? `五折 Macro-F1 极差为 ${metric(range)}，${range <= .05 ? '跨折表现较稳定' : range <= .1 ? '存在一定划分敏感性' : '跨折波动较大，当前稳定性不足'}。`
      : '历史版本未保存完整五折明细，无法评价跨折稳定性。',
    typeof generalizationGap === 'number'
      ? `平均训练 Macro-F1 与折外 Macro-F1 相差 ${metric(generalizationGap)}，判定为${risk.label}。${risk.message}`
      : risk.message,
    job?.subject_leakage_risk
      ? '数据缺少可靠被试 ID，句子级五折可能高估泛化性能；不建议据此直接发布。'
      : '训练折与测试折已按被试隔离，内部验证可信度较高；仍需独立外部样本验证。'
  ]
  return { level, tone, findings, minimumClassF1, range, trainF1, generalizationGap, risk }
}

function performanceMetricRows(job: ModelEvaluation | null) {
  return [
    { label: 'Accuracy', value: job?.summary.accuracy, note: '全部折外样本中预测正确的比例' },
    { label: 'Macro-Precision', value: job?.summary.macro_precision, note: '各实际训练类别精准率等权平均' },
    { label: 'Weighted-Precision', value: job?.summary.weighted_precision, note: '按各类别真实样本数加权的精准率，多数类影响更大' },
    { label: 'Macro-Recall', value: job?.summary.macro_recall, note: '各实际训练类别召回率等权平均' },
    { label: 'Weighted-Recall', value: job?.summary.weighted_recall, note: '按各类别真实样本数加权的召回率；单标签多分类中通常与 Accuracy 数值相同' },
    { label: 'Macro-Specificity', value: job?.summary.macro_specificity, note: '各实际训练类别特异性等权平均' },
    { label: 'Macro-F1', value: job?.summary.macro_f1, note: '首要比较指标：各类别 F1 等权平均' },
    { label: 'Weighted-F1', value: job?.summary.weighted_f1, note: '按各类别真实样本数加权的 F1，当前系统已计算并在模型比较中展示' },
    { label: 'Macro-AUC', value: job?.summary.macro_auc_ovr, note: '基于全部折外预测汇总计算的 One-vs-Rest Macro-AUC (Pooled OOF)' }
  ]
}

function evaluationModelName(job: ModelEvaluation | null) {
  if (!job) return '—'
  const feature = job.model_info.feature_type === 'tfidf' ? 'TF-IDF' : '远程 Embedding'
  const classifiers: Record<string, string> = {
    linear_svc: 'LinearSVC',
    logistic: 'LogisticRegression',
    random_forest: 'RandomForest',
    xgboost: 'XGBoost',
    lightgbm: 'LightGBM',
    catboost: 'CatBoost'
  }
  return `${feature} + ${classifiers[job.model_info.classifier || ''] || job.model_info.classifier || '未知分类器'}`
}

function evaluationSplitLabel(job: ModelEvaluation | null) {
  return job?.dataset.split_strategy === 'subject_grouped_stratified_5fold'
    ? '被试级分组五折'
    : job?.dataset.split_strategy === 'sentence_stratified_5fold' ? '句子级分层五折' : job?.dataset.split_strategy || '未记录划分策略'
}

function sampleCountRange(values: number[]) {
  if (!values.length) return '未记录'
  const minimum = Math.min(...values)
  const maximum = Math.max(...values)
  return minimum === maximum ? `${minimum}` : `${minimum}–${maximum}`
}

const definitions = {
  report_prompt: {
    label: 'AI 报告与元认知画像提示词',
    kind: 'prompt',
    help: '必须保留 {overall_score} 与 {dimension_results} 占位符；指导火山方舟大模型依据监控、调控、评估三分类评估结果与证据，端到端生成综合画像诊断、等级评定与个性化学习干预策略。'
  },
  metacognitive_extractor: {
    label: '元认知候选抽取提示词',
    kind: 'prompt',
    help: '必须保留 {segments} 占位符；仅从权威 ASR 转录中做高召回候选证据抽取，不得输出最终维度、评分或诊断。'
  }
} as const

const activeTemplate = computed(() =>
  templates.value.find(item => item.template_key === selectedKey.value && item.is_active)
)
const history = computed(() =>
  templates.value.filter(item => item.template_key === selectedKey.value)
)
const visibleAudits = computed(() =>
  templateAudits.value.filter(item => item.template_key === selectedKey.value)
)

function auditActionLabel(action: TemplateAudit['action']) {
  return ({
    'template.create_activate': '创建并启用',
    'template.activate': '启用版本',
    'template.rollback': '回滚版本',
    'template.replace': '创建并启用'
  } as Record<string, string>)[action] ?? action
}

function selectTemplate(key: MethodTemplate['template_key'], clearMessages = true) {
  selectedKey.value = key
  const active = templates.value.find(item => item.template_key === key && item.is_active)
  content.value = active?.content ?? ''
  viewedTemplateId.value = active?.id ?? null
  if (clearMessages) {
    templateSuccessMessage.value = ''
    templateErrorMessage.value = ''
  }
}

function viewHistory(item: MethodTemplate) {
  viewedTemplateId.value = item.id
  content.value = item.content
  templateSuccessMessage.value = `正在查看历史版本 ${item.version}${item.is_active ? '（当前启用）' : ''}。`
  templateErrorMessage.value = ''
}

async function activateHistory(item: MethodTemplate) {
  activatingTemplateId.value = item.id
  templateErrorMessage.value = ''
  try {
    await researchApi.activateTemplate(item.template_key, item.id)
    await Promise.all([loadTemplates(), loadTemplateAudits()])
    templateSuccessMessage.value = `已重新启用版本 ${item.version}，其他版本仍保留。`
  } catch (error) {
    templateErrorMessage.value = error instanceof Error ? error.message : '历史版本启用失败'
  } finally {
    activatingTemplateId.value = null
  }
}

async function loadTemplates() {
  isLoading.value = true
  try {
    const response = await researchApi.listTemplates()
    templates.value = response.data
    selectTemplate(selectedKey.value, false)
  } catch (error) {
    templateErrorMessage.value = error instanceof Error ? error.message : '模板加载失败'
  } finally {
    isLoading.value = false
  }
}

async function loadTemplateAudits() {
  auditLoading.value = true
  try {
    templateAudits.value = (await researchApi.listTemplateAudit()).data
  } catch (error) {
    templateErrorMessage.value = error instanceof Error ? error.message : '提示词审计记录加载失败'
  } finally {
    auditLoading.value = false
  }
}

async function saveTemplate() {
  isSaving.value = true
  templateErrorMessage.value = ''
  templateSuccessMessage.value = ''
  try {
    await researchApi.replaceTemplate(selectedKey.value, {
      version: version.value,
      kind: definitions[selectedKey.value].kind,
      content: content.value
    })
    await Promise.all([loadTemplates(), loadTemplateAudits()])
    templateSuccessMessage.value = `已创建并启用版本 ${version.value}，旧版本仍保留用于追溯。`
  } catch (error) {
    templateErrorMessage.value = error instanceof Error ? error.message : '模板保存失败'
  } finally {
    isSaving.value = false
  }
}

async function loadProtocolConfig() {
  protocolConfigLoading.value = true
  protocolErrorMessage.value = ''
  try {
    const response = await adminApi.getProtocolConfig()
    questionnaireEnabled.value = response.data.questionnaire_enabled
    savedQuestionnaireEnabled.value = response.data.questionnaire_enabled
    const bPct = Math.round((response.data.behavior_weight ?? 0.6) * 100)
    behaviorWeightPercent.value = bPct
    savedBehaviorWeightPercent.value = bPct
    protocolConfigUpdatedAt.value = response.data.updated_at
  } catch (error) {
    protocolErrorMessage.value = error instanceof Error ? error.message : '协议配置加载失败'
  } finally {
    protocolConfigLoading.value = false
  }
}

async function saveProtocolConfig() {
  protocolConfigSaving.value = true
  protocolErrorMessage.value = ''
  protocolSuccessMessage.value = ''
  try {
    const bWeight = behaviorWeightPercent.value / 100
    const qWeight = questionnaireWeightPercent.value / 100
    const response = await adminApi.updateProtocolConfig({
      questionnaire_enabled: questionnaireEnabled.value,
      behavior_weight: bWeight,
      questionnaire_weight: qWeight,
    })
    savedQuestionnaireEnabled.value = response.data.questionnaire_enabled
    const bPct = Math.round((response.data.behavior_weight ?? 0.6) * 100)
    behaviorWeightPercent.value = bPct
    savedBehaviorWeightPercent.value = bPct
    protocolConfigUpdatedAt.value = response.data.updated_at
    protocolSuccessMessage.value = questionnaireEnabled.value
      ? `测评协议与加权配置已更新（行为证据 ${bPct}% + 问卷量表 ${100 - bPct}%），将在新测评与报告中生效。`
      : `测评协议与加权配置已更新（任务后问卷已关闭，行为证据按 100% 独立计算），将在新测评与报告中生效。`
  } catch (error) {
    protocolErrorMessage.value = error instanceof Error ? error.message : '协议配置保存失败'
  } finally {
    protocolConfigSaving.value = false
  }
}

function formatUpdatedAt(value: string | null) {
  if (!value) return '尚未保存'
  return parseApiDate(value).toLocaleString('zh-CN', { hour12: false })
}

function formatBytes(value: number) {
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`
  return `${(value / 1024 / 1024).toFixed(2)} MB`
}

function narrationCategoryLabel(category: NarrationSlot['category']) {
  return ({
    instruction: '测评说明',
    practice: '练习阶段',
    questionnaire: '问卷阶段',
    task: '正式任务',
    silence: '静默提醒'
  } as const)[category]
}

function clearNarrationAudioUrls() {
  Object.values(narrationAudioUrls.value).forEach(url => URL.revokeObjectURL(url))
  narrationAudioUrls.value = {}
}

async function loadNarrationSlots() {
  narrationLoading.value = true
  narrationErrorMessage.value = ''
  try {
    narrationSlots.value = (await adminApi.listNarrationSlots()).data
  } catch (error) {
    narrationErrorMessage.value = error instanceof Error ? error.message : '朗读资源加载失败'
  } finally {
    narrationLoading.value = false
  }
}

async function uploadNarration(slot: NarrationSlot, event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  narrationBusyKey.value = slot.slot_key
  narrationErrorMessage.value = ''
  try {
    await adminApi.uploadNarration(slot.slot_key, file)
    clearNarrationAudioUrls()
    await loadNarrationSlots()
    notify(`已更新“${slot.label}”朗读录音`, 'success')
  } catch (error) {
    narrationErrorMessage.value = error instanceof Error ? error.message : '朗读录音上传失败'
  } finally {
    narrationBusyKey.value = ''
  }
}

async function previewNarration(slot: NarrationSlot) {
  if (!slot.asset) return
  narrationBusyKey.value = slot.slot_key
  narrationErrorMessage.value = ''
  try {
    const existing = narrationAudioUrls.value[slot.asset.id]
    if (existing) {
      URL.revokeObjectURL(existing)
      delete narrationAudioUrls.value[slot.asset.id]
    } else {
      const response = await adminApi.getNarrationAudio(slot.asset.id)
      narrationAudioUrls.value[slot.asset.id] = URL.createObjectURL(response.data)
    }
  } catch (error) {
    narrationErrorMessage.value = error instanceof Error ? error.message : '朗读录音读取失败'
  } finally {
    narrationBusyKey.value = ''
  }
}

async function disableNarration(slot: NarrationSlot) {
  if (!slot.asset) return
  const confirmed = await confirmAction({
    title: '停用当前朗读录音',
    message: `确定停用“${slot.label}”的当前版本吗？历史测评仍会保留原版本，新测评将使用浏览器语音回退。`,
    confirmText: '确认停用',
    tone: 'warning'
  })
  if (!confirmed) return
  narrationBusyKey.value = slot.slot_key
  narrationErrorMessage.value = ''
  try {
    await adminApi.disableNarration(slot.asset.id)
    clearNarrationAudioUrls()
    await loadNarrationSlots()
    notify(`已停用“${slot.label}”当前录音`, 'success')
  } catch (error) {
    narrationErrorMessage.value = error instanceof Error ? error.message : '朗读录音停用失败'
  } finally {
    narrationBusyKey.value = ''
  }
}



function trainingStatus(job: ModelTrainingJob) {
  const status = ({ queued: '排队中', running: '处理中', completed: '已完成', failed: '失败', cancelled: '已取消' } as const)[job.status]
  if (job.stage.startsWith('training_fold_')) {
    const fold = job.current_fold ?? Number(job.stage.replace('training_fold_', ''))
    return `${status} · 第 ${fold}/${job.total_folds || 5} 折`
  }
  const stage = ({
    preparing_dataset: '准备训练数据', preparing_features: '生成 TF-IDF 特征', embedding: '生成文本向量', training: '执行五折训练',
    refitting: '五折完成，拟合最终模型',
    waiting_worker_upgrade: '等待训练 Worker 更新',
    evaluating: '计算评估指标', saving: '保存模型产物', completed: '等待人工验收',
    failed: '处理失败', cancelled: '任务已取消', queued: '等待 Worker'
  } as Record<string, string>)[job.stage]
  return stage ? `${status} · ${stage}` : status
}

function trainingEta(job: ModelTrainingJob) {
  const seconds = job.estimated_remaining_seconds
  if (seconds == null) return '正在估算剩余时间'
  if (seconds <= 10) return '预计即将完成'
  if (seconds < 60) return `预计剩余约 ${seconds} 秒`
  const minutes = Math.ceil(seconds / 60)
  return `预计剩余约 ${minutes} 分钟`
}

function trainingHeartbeat(job: ModelTrainingJob) {
  if (!job.heartbeat_at) return '等待训练心跳'
  const heartbeat = parseApiDate(job.heartbeat_at)
  if (Number.isNaN(heartbeat.getTime())) return '训练心跳已记录'
  const age = Math.max(0, Math.round((Date.now() - heartbeat.getTime()) / 1000))
  if (age <= 15) return '训练心跳正常'
  return `训练心跳延迟 ${age} 秒`
}

function trainingProgressTitle(job: ModelTrainingJob) {
  return `${trainingStatus(job)} · ${job.progress}% · ${trainingHeartbeat(job)} · ${trainingEta(job)}`
}

function metric(value?: number | null) {
  return typeof value === 'number' ? value.toFixed(3) : '—'
}

function trainingAuditLabel(action: string) {
  return ({
    'model_training.create': '创建训练任务', 'model_training.retry': '创建重试版本',
    'model_training.cancel': '请求取消', 'model_training.cancelled': '训练已取消',
    'model_training.completed': '训练完成', 'model_training.failed': '训练失败',
    'model_training.recovered_failed': '中断恢复', 'model_training.activate': '启用/回滚模型',
    'model_training.deactivate': '取消启用模型',
    'model_training.dataset_upload': '上传训练数据版本'
  } as Record<string, string>)[action] ?? action
}

async function loadTrainingJobs(silent = false) {
  if (!silent) trainingLoading.value = true
  try {
    const previous = new Map(trainingJobs.value.map(item => [item.id, item.status]))
    const next = (await researchApi.listModelTrainingJobs()).data
    let completedSinceLastRead = false
    trainingJobs.value = next
    if (!comparisonGroups.value.some(group => group.key === selectedComparisonGroupKey.value)) {
      selectedComparisonGroupKey.value = comparisonGroups.value[0]?.key ?? ''
    }
    if (!trainingGroupsInitialized) {
      expandedTrainingGroupKey.value = trainingVersionGroups.value[0]?.key ?? ''
      trainingGroupsInitialized = true
    } else if (expandedTrainingGroupKey.value && !trainingVersionGroups.value.some(group => group.key === expandedTrainingGroupKey.value)) {
      expandedTrainingGroupKey.value = trainingVersionGroups.value[0]?.key ?? ''
      expandedTrainingJobId.value = ''
    }
    if (silent) {
      next.forEach(item => {
        const oldStatus = previous.get(item.id)
        if (oldStatus && oldStatus !== item.status && ['completed', 'failed', 'cancelled'].includes(item.status)) {
          if (item.status === 'completed') completedSinceLastRead = true
          notify(`训练任务 ${item.version}${item.status === 'completed' ? '已完成，等待人工验收' : item.status === 'failed' ? '执行失败' : '已取消'}`, item.status === 'completed' ? 'success' : item.status === 'failed' ? 'danger' : 'warning')
        }
      })
    }
    // 先确认数据库中的训练任务已经完成，再读取绑定到该任务的评估 manifest，
    // 避免并行轮询时评估接口先返回旧版本、随后轮询停止造成页面滞后。
    if (completedSinceLastRead) await loadModelEvaluations(true)
  } catch (error) {
    if (!silent) notify(error instanceof Error ? error.message : '训练任务读取失败', 'danger')
  } finally {
    trainingLoading.value = false
  }
}

async function loadModelEvaluations(silent = false) {
  if (!silent) modelEvaluationLoading.value = true
  try {
    modelEvaluationIndex.value = (await researchApi.listModelEvaluations()).data
    initializeHistoricalComparisonSelection()
    modelEvaluationError.value = ''
  } catch (error) {
    modelEvaluationError.value = error instanceof Error ? error.message : '模型评估结果读取失败'
  } finally {
    modelEvaluationLoading.value = false
  }
}

async function loadTrainingAudits() {
  trainingAuditLoading.value = true
  try {
    trainingAudits.value = (await researchApi.listModelTrainingAudit()).data
  } catch (error) {
    notify(error instanceof Error ? error.message : '训练审计读取失败', 'danger')
  } finally {
    trainingAuditLoading.value = false
  }
}

async function loadTrainingDatasets() {
  trainingDatasetLoading.value = true
  try {
    uploadedTrainingDatasets.value = (await researchApi.listModelTrainingDatasets()).data
    if (!selectedTrainingDatasetId.value && uploadedTrainingDatasets.value.length) {
      selectedTrainingDatasetId.value = uploadedTrainingDatasets.value[0].id
    }
  } catch (error) {
    notify(error instanceof Error ? error.message : '训练数据版本读取失败', 'danger')
  } finally {
    trainingDatasetLoading.value = false
  }
}

async function loadHyperparameterCatalog() {
  try {
    const catalog = (await researchApi.getModelHyperparameters()).data
    hyperparameterCatalog.value = catalog
    experimentDefinitions.forEach(({ value }) => {
      trainingParameters.value[value] = { ...(catalog[value]?.defaults ?? {}) }
      tuningEnabled.value[value] = false
    })
  } catch (error) {
    notify(error instanceof Error ? error.message : '训练参数说明读取失败', 'danger')
  }
}

const selectedTrainingExperiments = computed<ModelExperimentType[]>(() => {
  if (trainingCreateMode.value === 'single') return [selectedExperiment.value]
  if (trainingCreateMode.value === 'suite') return allExperimentTypes
  return allExperimentTypes.filter(type => selectedCustomExperiments.value.includes(type))
})

const configurableExperiments = computed(() => experimentDefinitions
  .filter(item => selectedTrainingExperiments.value.includes(item.value)))

const isTrainingComparison = computed(() => trainingCreateMode.value !== 'single')
const trainingSelectionValid = computed(() =>
  trainingCreateMode.value !== 'custom' || selectedTrainingExperiments.value.length >= 2)
const comparisonExpectedCount = computed(() => activeComparisonExperimentTypes.value.length)

const selectedExperimentNames = computed(() => configurableExperiments.value
  .map(item => `${item.feature} + ${item.classifier}`)
  .join('、'))

function toggleCustomExperiment(experiment: ModelExperimentType) {
  selectedCustomExperiments.value = selectedCustomExperiments.value.includes(experiment)
    ? selectedCustomExperiments.value.filter(item => item !== experiment)
    : [...selectedCustomExperiments.value, experiment]
}

function resetTrainingParameters(experiment: ModelExperimentType) {
  trainingParameters.value[experiment] = {
    ...(hyperparameterCatalog.value?.[experiment]?.defaults ?? {})
  }
}

function parameterSummary(job: ModelTrainingJob | ModelEvaluation) {
  const parameters = 'model_info' in job
    ? job.model_info.classifier_parameters
    : (job.config_snapshot?.classifier_parameters as Record<string, ModelHyperparameterValue> | undefined)
  if (!parameters || !Object.keys(parameters).length) return '历史版本未记录参数'
  return Object.entries(parameters).map(([name, value]) => `${name}=${value}`).join(' · ')
}

function isManuallyTuned(job: ModelTrainingJob | ModelEvaluation) {
  return 'model_info' in job
    ? Boolean(job.model_info.hyperparameters_tuned)
    : Boolean(job.config_snapshot?.hyperparameters_tuned)
}

function selectTrainingDatasetFile(event: Event) {
  trainingDatasetFile.value = (event.target as HTMLInputElement).files?.[0] ?? null
  if (trainingDatasetFile.value && !trainingDatasetName.value) {
    trainingDatasetName.value = trainingDatasetFile.value.name.replace(/\.(csv|xlsx)$/i, '')
  }
}

async function downloadTrainingDatasetTemplate() {
  trainingTemplateDownloading.value = true
  try {
    const response = await researchApi.downloadModelTrainingDatasetTemplate()
    const url = URL.createObjectURL(response.data)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = '元认知模型训练数据示例模板.xlsx'
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
    notify('训练数据示例模板已下载', 'success')
  } catch (error) {
    notify(error instanceof Error ? error.message : '示例模板下载失败', 'danger')
  } finally {
    trainingTemplateDownloading.value = false
  }
}

async function createTrainingExperiment() {
  if (!trainingVersion.value.trim()) return
  if (trainingDatasetSource.value === 'uploaded' && !trainingDatasetFile.value && !selectedTrainingDatasetId.value) {
    notify('请选择已上传的数据版本，或上传新的 CSV/XLSX 文件', 'warning')
    return
  }
  const isSuite = isTrainingComparison.value
  const selectedCount = selectedTrainingExperiments.value.length
  if (trainingCreateMode.value === 'custom' && selectedCount < 2) {
    notify('自选横向对比至少需要选择两个模型', 'warning')
    return
  }
  const comparisonLabel = trainingCreateMode.value === 'suite'
    ? '七组模型对比实验'
    : `${selectedCount} 组自选模型对比实验`
  const confirmed = await confirmAction({
    title: isSuite ? `创建${comparisonLabel}` : '创建模型训练任务',
    message: `${trainingDatasetSource.value === 'system_gold' ? '系统会冻结当前已完成人工共识/仲裁的专家金标准' : '系统会使用所选的上传数据版本'}。${isSuite ? `所选 ${selectedCount} 项实验共享同一数据快照，分别保存且互不覆盖。` : '任务创建后由后台 Worker 处理。'}本次实际参数也会冻结并显示在结果中。是否继续？`,
    confirmText: isSuite ? `创建 ${selectedCount} 组任务` : '创建任务'
  })
  if (!confirmed) return
  trainingCreating.value = true
  try {
    let datasetId = trainingDatasetSource.value === 'uploaded' ? selectedTrainingDatasetId.value || null : null
    if (trainingDatasetSource.value === 'uploaded' && trainingDatasetFile.value) {
      if (!trainingDatasetName.value.trim()) throw new Error('请填写上传数据版本名称')
      const uploaded = (await researchApi.uploadModelTrainingDataset(
        trainingDatasetName.value.trim(), trainingDatasetFile.value
      )).data
      uploadedTrainingDatasets.value = [uploaded, ...uploadedTrainingDatasets.value]
      selectedTrainingDatasetId.value = uploaded.id
      datasetId = uploaded.id
      trainingDatasetFile.value = null
    }
    const jobs = isSuite
      ? (await researchApi.createModelTrainingSuite(
          trainingVersion.value.trim(), trainingDatasetSource.value, datasetId,
          Object.fromEntries(configurableExperiments.value
            .filter(item => tuningEnabled.value[item.value])
            .map(item => [item.value, trainingParameters.value[item.value] ?? {}])),
          selectedTrainingExperiments.value
        )).data
      : [(await researchApi.createModelTrainingJob(
          trainingVersion.value.trim(), selectedExperiment.value,
          trainingDatasetSource.value, datasetId,
          tuningEnabled.value[selectedExperiment.value]
            ? trainingParameters.value[selectedExperiment.value] ?? {}
            : {}
        )).data]
    await Promise.all([loadTrainingJobs(true), loadModelEvaluations(true), loadTrainingAudits()])
    trainingCreateOpen.value = false
    notify(isSuite ? `已创建 ${jobs.length} 组横向对比实验，后台将依次处理` : '训练任务已创建，将由后台 Worker 处理', 'success')
  } catch (error) {
    notify(error instanceof Error ? error.message : '训练任务创建失败', 'danger')
  } finally {
    trainingCreating.value = false
  }
}

async function exportTrainingJob(job: ModelTrainingJob) {
  trainingBusyId.value = job.id
  try {
    const response = await researchApi.exportModelTrainingReport(job.id)
    const url = URL.createObjectURL(response.data)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `模型训练结果-${job.version}.zip`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
    notify(`已导出 ${job.version} 的完整训练报告`, 'success')
  } catch (error) {
    notify(error instanceof Error ? error.message : '训练报告导出失败', 'danger')
  } finally {
    trainingBusyId.value = ''
  }
}

async function exportTrainingComparison() {
  trainingBusyId.value = 'comparison-export'
  try {
    const jobIds = comparisonJobs.value.flatMap(item => item.job ? [item.job.id] : [])
    const response = await researchApi.exportModelTrainingComparison(jobIds)
    const url = URL.createObjectURL(response.data)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${comparisonExpectedCount.value}模型训练结果对比.csv`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
    notify(`已导出 ${comparisonExpectedCount.value} 模型横向对比表`, 'success')
  } catch (error) {
    notify(error instanceof Error ? error.message : '模型对比表导出失败', 'danger')
  } finally {
    trainingBusyId.value = ''
  }
}

const isExportingErrorCases = ref(false)

async function exportOofErrorCases(job: ModelEvaluation | null | undefined) {
  if (!job) return
  isExportingErrorCases.value = true
  try {
    const response = await researchApi.exportModelErrorCases(job.model_id)
    const url = URL.createObjectURL(response.data)
    const anchor = document.createElement('a')
    anchor.href = url
    const safeVer = (job.model_version || 'v1').replace(/[^\w.-]/g, '_')
    anchor.download = `模型-${safeVer}-折外错误案例.csv`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
    notify(`已成功导出 ${job.model_version} 的全部 ${job.error_analysis?.total_error_count ?? ''} 条折外错误案例 CSV`, 'success')
  } catch (error) {
    notify(error instanceof Error ? error.message : '折外错误案例导出失败', 'danger')
  } finally {
    isExportingErrorCases.value = false
  }
}

async function cancelTrainingJob(job: ModelTrainingJob) {
  const confirmed = await confirmAction({ title: '取消训练任务', message: `确定取消 ${job.version} 吗？运行中的任务会在当前安全检查点停止。`, confirmText: '确认取消', tone: 'warning' })
  if (!confirmed) return
  trainingBusyId.value = job.id
  try {
    await researchApi.cancelModelTrainingJob(job.id)
    await Promise.all([loadTrainingJobs(true), loadModelEvaluations(true), loadTrainingAudits()])
    notify(job.status === 'queued' ? '训练任务已取消' : '已提交取消请求', 'success')
  } catch (error) {
    notify(error instanceof Error ? error.message : '取消训练失败', 'danger')
  } finally {
    trainingBusyId.value = ''
  }
}

async function retryTrainingJob(job: ModelTrainingJob) {
  trainingBusyId.value = job.id
  try {
    const created = (await researchApi.retryModelTrainingJob(job.id)).data
    await Promise.all([loadTrainingJobs(true), loadModelEvaluations(true), loadTrainingAudits()])
    notify(`已创建重试版本 ${created.version}`, 'success')
  } catch (error) {
    notify(error instanceof Error ? error.message : '重新运行失败', 'danger')
  } finally {
    trainingBusyId.value = ''
  }
}

async function activateTrainingJob(job: ModelTrainingJob) {
  if (job.is_active) return
  const risk = overfitRisk(job)
  const riskMessage = risk.level === 'unknown'
    ? `无法计算该模型的过拟合风险。${risk.message}`
    : `${risk.label}（训练—折外差距 ${metric(risk.gap)}）。${risk.message}`
  const confirmed = await confirmAction({
    title: risk.level === 'high' ? '高过拟合风险：仍要启用吗？' : '切换生产分类模型',
    message: `将启用 ${job.version}。${riskMessage} 当前模型会保留，可随时重新启用完成回滚。`,
    confirmText: '确认启用', tone: 'warning'
  })
  if (!confirmed) return
  trainingBusyId.value = job.id
  try {
    await researchApi.activateModelTrainingJob(job.id)
    await Promise.all([loadTrainingJobs(true), loadModelEvaluations(true), loadTrainingAudits()])
    notify(`已启用模型 ${job.version}`, 'success')
  } catch (error) {
    notify(error instanceof Error ? error.message : '模型启用失败', 'danger')
  } finally {
    trainingBusyId.value = ''
  }
}

async function deactivateTrainingJob(job: ModelTrainingJob) {
  if (!job.is_active) return
  const confirmed = await confirmAction({
    title: '取消启用生产模型',
    message: `取消启用 ${job.version} 后，教师将暂时无法执行 AI 评估。模型产物和历史结果不会删除。`,
    confirmText: '确认取消启用', tone: 'danger'
  })
  if (!confirmed) return
  trainingBusyId.value = job.id
  try {
    await researchApi.deactivateModelTrainingJob(job.id)
    await Promise.all([loadTrainingJobs(true), loadModelEvaluations(true), loadTrainingAudits()])
    notify(`已取消启用模型 ${job.version}`, 'success')
  } catch (error) {
    notify(error instanceof Error ? error.message : '取消启用失败', 'danger')
  } finally {
    trainingBusyId.value = ''
  }
}

onMounted(() => {
  void Promise.all([loadTemplates(), loadTemplateAudits(), loadProtocolConfig(), loadNarrationSlots(), loadTrainingJobs(), loadModelEvaluations(), loadTrainingAudits(), loadTrainingDatasets(), loadHyperparameterCatalog()])
  trainingPoll = window.setInterval(() => {
    if (trainingJobs.value.some(item => ['queued', 'running'].includes(item.status))) {
      void loadTrainingJobs(true)
    }
  }, 4000)
})
onBeforeUnmount(() => {
  if (trainingPoll !== null) window.clearInterval(trainingPoll)
  clearNarrationAudioUrls()
})
</script>

<template>
  <div class="template-page">
    <div class="d-flex flex-wrap justify-content-between align-items-start gap-3 mb-4">
      <div>
        <p class="text-primary fw-semibold small mb-1">版本化研究方法</p>
        <h3 class="mb-1">研究配置</h3>
        <p class="text-muted mb-0">测评流程和 AI 分析模板独立配置、独立保存。</p>
      </div>
    </div>

    <details class="research-fold-card mb-4" open>
      <summary><span><i class="bi bi-diagram-3-fill"></i><strong>分类模型持续训练</strong><small>创建版本、查看进度、比较五折指标、启用或回滚模型</small></span><i class="bi bi-chevron-down fold-chevron"></i></summary>
      <div class="fold-content">
        <div v-if="trainingJobs.find(item => item.is_active)" class="active-model-banner mb-3">
          <span class="active-model-icon"><i class="bi bi-cpu-fill"></i></span>
          <div><small>当前生产分类模型</small><strong>{{ trainingJobs.find(item => item.is_active)?.version }}</strong><span>新生成的候选会自动记录该模型的分类与置信度，人工盲编结论不受影响。</span></div>
        </div>
        <div class="training-create-entry mb-3">
          <div><strong>创建训练实验</strong><small>可训练单个模型、自选若干模型横向对比，或一次运行全部七组方案。</small></div>
          <button class="btn btn-primary" @click="trainingCreateOpen = !trainingCreateOpen"><i class="bi bi-plus-circle me-1"></i>{{ trainingCreateOpen ? '收起创建面板' : '新建训练实验' }}</button>
        </div>
        <div v-if="trainingCreateOpen" class="training-builder mb-3">
          <div class="training-builder-section">
            <span class="training-builder-step">1</span>
            <div class="flex-grow-1"><strong>选择实验方式</strong><div class="training-choice-grid mt-2"><label class="training-choice" :class="{ active: trainingCreateMode === 'single' }"><input v-model="trainingCreateMode" type="radio" value="single"><span><b>单个实验</b><small>只训练一种特征与分类器组合</small></span></label><label class="training-choice" :class="{ active: trainingCreateMode === 'custom' }"><input v-model="trainingCreateMode" type="radio" value="custom"><span><b>自选组别横向对比</b><small>任选 2–7 个模型，共用同一数据快照</small></span></label><label class="training-choice" :class="{ active: trainingCreateMode === 'suite' }"><input v-model="trainingCreateMode" type="radio" value="suite"><span><b>全部七组横向对比</b><small>TF-IDF 基线 + 六组 Embedding 分类器</small></span></label></div><label v-if="trainingCreateMode === 'single'" class="mt-3"><span class="form-label">实验方案</span><select v-model="selectedExperiment" class="form-select"><option v-for="item in experimentDefinitions" :key="item.value" :value="item.value">{{ item.feature }} + {{ item.classifier }}</option></select></label><div v-else-if="trainingCreateMode === 'custom'" class="custom-experiment-panel mt-3"><div class="custom-experiment-heading"><span><b>选择参与对比的模型</b><small>已选择 {{ selectedTrainingExperiments.length }} / {{ experimentDefinitions.length }} 项；至少选择两项</small></span><span class="selection-count" :class="{ 'is-invalid': !trainingSelectionValid }">{{ selectedTrainingExperiments.length }} 项</span></div><div class="custom-experiment-grid"><label v-for="item in experimentDefinitions" :key="`custom-${item.value}`" class="custom-experiment-option" :class="{ active: selectedCustomExperiments.includes(item.value) }"><input type="checkbox" :checked="selectedCustomExperiments.includes(item.value)" @change="toggleCustomExperiment(item.value)"><span><b>{{ item.feature }} + {{ item.classifier }}</b><small>{{ item.title }} · {{ item.hint }}</small></span><i class="bi" :class="selectedCustomExperiments.includes(item.value) ? 'bi-check-circle-fill' : 'bi-circle'"></i></label></div><p v-if="!trainingSelectionValid" class="custom-selection-warning"><i class="bi bi-exclamation-triangle-fill"></i>请再选择至少一个模型，横向对比不能只包含单个模型。</p></div><div v-else class="all-experiment-summary mt-3"><i class="bi bi-check2-all"></i><span><b>已选择全部七组模型</b><small>{{ selectedExperimentNames }}</small></span></div></div>
          </div>
          <div class="training-builder-section">
            <span class="training-builder-step">2</span>
            <div class="flex-grow-1"><strong>选择训练数据来源</strong><div class="training-choice-grid mt-2"><label class="training-choice" :class="{ active: trainingDatasetSource === 'system_gold' }"><input v-model="trainingDatasetSource" type="radio" value="system_gold"><span><b>系统专家金标准</b><small>已完成人工排除、双人共识或仲裁的数据</small></span></label><label class="training-choice" :class="{ active: trainingDatasetSource === 'uploaded' }"><input v-model="trainingDatasetSource" type="radio" value="uploaded"><span><b>上传训练数据</b><small>使用独立 CSV / XLSX 数据版本</small></span></label></div>
              <div v-if="trainingDatasetSource === 'system_gold'" class="dataset-source-note mt-3"><i class="bi bi-snow2"></i><span>创建时自动冻结当前系统金标准。后续新增或修改专家编码不会改变本次训练数据。</span></div>
              <div v-else class="uploaded-dataset-panel mt-3">
                <div class="dataset-template-entry"><div><b>第一次上传？</b><small>模板仅需填写“清洗后文本”和“标签”两列，训练标签使用 1、2、3。</small></div><button class="btn btn-sm btn-outline-primary" :disabled="trainingTemplateDownloading" @click="downloadTrainingDatasetTemplate"><span v-if="trainingTemplateDownloading" class="spinner-border spinner-border-sm me-1"></span><i v-else class="bi bi-file-earmark-arrow-down me-1"></i>下载三分类示例模板</button></div>
                <label><span class="form-label">选择已有上传版本</span><select v-model="selectedTrainingDatasetId" class="form-select" :disabled="trainingDatasetLoading"><option value="">不选择，上传新文件</option><option v-for="item in uploadedTrainingDatasets" :key="item.id" :value="item.id">{{ item.name }} · 可训练 {{ item.training_sample_count }} 条 · {{ item.has_participant_ids ? `${item.participant_count} 名被试 / 被试级五折` : '句子级分层五折' }} · {{ formatUpdatedAt(item.created_at) }}</option></select></label>
                <div class="dataset-divider"><span>或上传新版本</span></div>
                <div class="uploaded-dataset-fields"><label><span class="form-label">数据版本名称</span><input v-model.trim="trainingDatasetName" class="form-control" maxlength="100" placeholder="例如 外部专家金标准_v1"></label><label><span class="form-label">CSV / XLSX 文件</span><input class="form-control" type="file" accept=".csv,.xlsx" @change="selectTrainingDatasetFile"></label></div>
                <small class="text-muted">必需列仅为 clean_text（清洗后文本）和 label（标签）。新模型只训练 1监控、2调控、3评估；标签0即使存在也会被排除。至少30条元认知样本、三类完整且每类不少于5条。旧版含 participant_id 的文件仍兼容，并会自动采用更严格的被试级五折。</small>
              </div>
            </div>
          </div>
          <div class="training-builder-section">
            <span class="training-builder-step">3</span>
            <div class="flex-grow-1"><div class="parameter-section-heading"><div><strong>分类器参数（可选）</strong><small>默认参数可直接训练；启用人工调参后，本次取值会冻结到任务、指标和导出报告中。</small></div></div><div v-if="!hyperparameterCatalog" class="text-muted small py-2">正在读取参数范围…</div><details v-for="item in configurableExperiments" v-else :key="`params-${item.value}`" class="parameter-model-card"><summary><span><b>{{ item.feature }} + {{ item.classifier }}</b><small>{{ tuningEnabled[item.value] ? '人工调参' : '系统默认参数' }}</small></span><i class="bi bi-chevron-down"></i></summary><div class="parameter-model-body"><label class="parameter-toggle"><input v-model="tuningEnabled[item.value]" type="checkbox"><span><b>启用本模型人工调参</b><small>关闭时采用下列系统默认值；开启后才标记为“人工调参”。</small></span></label><div class="parameter-grid" :class="{ 'is-disabled': !tuningEnabled[item.value] }"><label v-for="(definition, parameterName) in hyperparameterCatalog[item.value].parameters" :key="parameterName"><span class="form-label">{{ definition.label }} <code>{{ parameterName }}</code></span><select v-if="definition.type === 'choice'" v-model="trainingParameters[item.value]![parameterName]" class="form-select" :disabled="!tuningEnabled[item.value]"><option v-for="choice in definition.choices" :key="choice" :value="choice">{{ choice }}</option></select><input v-else v-model.number="trainingParameters[item.value]![parameterName]" class="form-control" type="number" :min="definition.min" :max="definition.max" :step="definition.step" :disabled="!tuningEnabled[item.value]"><small>{{ definition.description }}</small></label></div><button type="button" class="btn btn-sm btn-outline-secondary" :disabled="!tuningEnabled[item.value]" @click="resetTrainingParameters(item.value)"><i class="bi bi-arrow-counterclockwise me-1"></i>恢复默认值</button></div></details></div>
          </div>
          <div class="training-builder-section">
            <span class="training-builder-step">4</span>
            <div class="flex-grow-1"><strong>设置版本并创建</strong><label class="d-block mt-2"><span class="form-label">{{ isTrainingComparison ? '版本前缀' : '训练版本' }}</span><input v-model.trim="trainingVersion" class="form-control" :maxlength="isTrainingComparison ? 42 : 64" placeholder="例如 元认知模型_v2"></label><small class="text-muted">支持中文、英文、数字、英文句点、下划线和连字符，必须以中文、英文字母或数字开头。</small><small v-if="isTrainingComparison" class="text-muted d-block">系统会为所选模型自动添加对应后缀；各任务共享同一冻结数据快照，便于公平比较。</small><div class="d-flex justify-content-end mt-3"><button class="btn btn-primary" :disabled="trainingCreating || !trainingVersion || !trainingSelectionValid" @click="createTrainingExperiment"><span v-if="trainingCreating" class="spinner-border spinner-border-sm me-1"></span><i v-else class="bi bi-play-circle me-1"></i>{{ isTrainingComparison ? `创建 ${selectedTrainingExperiments.length} 组对比任务` : '创建训练任务' }}</button></div></div>
          </div>
        </div>
        <p class="small text-muted">所有任务都记录数据来源、数据指纹、标签分布和实际分类器参数；同一对比批次严格共用一个冻结快照。Embedding 模型会复用同批文本向量，避免因更换分类器重复生成。任务完成后仍须人工比较并启用。</p>
        <div class="comparison-toolbar mb-2">
          <div class="comparison-toolbar-copy">
            <strong>同组训练结果横向对比</strong>
            <small v-if="comparisonIsComplete"><i class="bi bi-check-circle-fill me-1"></i>本批次 {{ comparisonExpectedCount }} 项实验均已完成；绿色边框表示本组 Macro-F1 最佳模型，同分时优先比较 Weighted-F1，并同步显示训练—折外差距与过拟合风险。</small>
            <small v-else><i class="bi bi-hourglass-split me-1"></i>等待同一批次所选 {{ comparisonExpectedCount }} 项实验全部完成后，系统才会标记最佳模型。</small>
          </div>
          <label v-if="comparisonGroups.length > 1" class="comparison-group-select">
            <span>对比批次</span>
            <select v-model="selectedComparisonGroupKey" class="form-select form-select-sm">
              <option v-for="group in comparisonGroups" :key="group.key" :value="group.key">{{ group.label }} · {{ group.jobs.length }} 项任务</option>
            </select>
          </label>
          <span v-else-if="activeComparisonGroup" class="comparison-group-label">{{ activeComparisonGroup.label }}</span>
          <button class="btn btn-sm btn-outline-secondary" :disabled="trainingBusyId === 'comparison-export' || !comparisonIsComplete" :title="`导出本批次 ${comparisonExpectedCount} 项同数据版本实验的指标、实际参数和调参来源`" @click="exportTrainingComparison"><i class="bi bi-file-earmark-spreadsheet me-1"></i>导出 {{ comparisonExpectedCount }} 模型指标与参数 CSV</button>
        </div>
        <div class="model-comparison-grid mb-3">
          <article v-for="item in comparisonJobs" :key="item.value" class="model-comparison-card" :class="{ 'is-best': item.job?.id === bestComparisonJobId }">
            <div class="model-comparison-heading"><span><i class="bi" :class="item.value === 'tfidf_linear_svc' ? 'bi-lightning-charge-fill' : 'bi-diagram-3-fill'"></i></span><div><small>{{ item.title }}</small><strong>{{ item.feature }} + {{ item.classifier }}</strong></div><span v-if="item.job?.id === bestComparisonJobId" class="best-model-badge"><i class="bi bi-trophy-fill"></i>最佳</span><span v-if="item.job?.is_active" class="badge bg-success">生产启用</span></div>
            <template v-if="item.job"><div class="model-comparison-metrics"><span><small>Macro-F1</small><strong>{{ metric(item.job.metrics?.macro_f1) }}</strong></span><span><small>Accuracy</small><strong>{{ metric(item.job.metrics?.accuracy) }}</strong></span><span><small>Weighted-F1</small><strong>{{ metric(item.job.metrics?.weighted_f1) }}</strong></span></div><div v-if="item.job.id === bestComparisonJobId" class="best-risk-summary" :class="overfitRisk(item.job).tone"><i class="bi" :class="overfitRisk(item.job).level === 'high' ? 'bi-exclamation-triangle-fill' : 'bi-shield-check'"></i><span><b>{{ overfitRisk(item.job).label }}</b><small>训练—折外差距 {{ metric(overfitRisk(item.job).gap) }}</small></span></div><div class="model-parameter-line"><span :class="isManuallyTuned(item.job) ? 'is-manual' : ''">{{ isManuallyTuned(item.job) ? '人工调参' : '默认参数' }}</span><small>{{ parameterSummary(item.job) }}</small></div><div class="model-comparison-footer"><span class="training-status" :class="`is-${item.job.status}`">{{ trainingStatus(item.job) }}</span><button type="button" class="btn btn-sm btn-link" @click="openTrainingJobDetails(item.job)">查看详情</button></div></template>
            <div v-else class="model-comparison-empty">尚未创建 · {{ item.hint }}</div>
          </article>
        </div>
        <div v-if="trainingLoading" class="py-4 text-center"><span class="spinner-border text-primary"></span></div>
        <div v-else-if="trainingJobs.length" class="table-responsive training-table-wrap">
          <table class="table align-middle mb-0">
            <thead><tr><th>模型方案</th><th>状态/进度</th><th>样本</th><th>Macro-F1</th><th>Weighted-F1</th><th>Macro-AUC</th><th>创建时间</th><th class="text-end">操作</th></tr></thead>
            <tbody v-for="group in trainingVersionGroups" :key="group.key" class="training-version-group">
              <tr class="training-group-row">
                <td colspan="8">
                  <button class="training-group-toggle" :aria-expanded="expandedTrainingGroupKey === group.key" @click="toggleTrainingGroup(group.key)">
                    <span class="training-group-chevron"><i class="bi" :class="expandedTrainingGroupKey === group.key ? 'bi-chevron-down' : 'bi-chevron-right'"></i></span>
                    <span class="training-group-copy"><small>训练版本</small><strong>{{ group.label }}</strong><span>{{ group.jobs.length }} 个任务 · 数据：{{ group.jobs[0]?.config_snapshot?.dataset_name || '历史系统金标准' }}</span></span>
                    <span v-if="group.jobs.some(job => job.is_active)" class="training-group-active"><i class="bi bi-check-circle-fill"></i>含当前启用模型</span>
                    <span class="training-group-progress">{{ trainingGroupSummary(group.jobs) }}</span>
                    <time>{{ formatUpdatedAt(group.jobs[0]?.created_at || null) }}</time>
                  </button>
                </td>
              </tr>
              <template v-if="expandedTrainingGroupKey === group.key">
                <template v-for="job in group.jobs" :key="job.id">
                  <tr :id="`training-job-${job.id}`" class="training-job-row" :class="{ 'is-expanded': expandedTrainingJobId === job.id }">
                    <td><button class="training-version-button" @click="expandedTrainingJobId = expandedTrainingJobId === job.id ? '' : job.id"><i class="bi" :class="expandedTrainingJobId === job.id ? 'bi-chevron-down' : 'bi-chevron-right'"></i><strong>{{ experimentDefinition(job).feature }} + {{ experimentDefinition(job).classifier }}</strong></button><span v-if="job.is_active" class="badge bg-success ms-2">当前启用</span><small class="d-block text-muted">{{ job.version }}<template v-if="job.parent_job_id"> · 重试版本</template></small></td>
                    <td><span class="training-status" :class="`is-${job.status}`">{{ trainingStatus(job) }}</span><div v-if="job.status === 'running'" class="training-live-progress mt-2" :title="trainingProgressTitle(job)"><div class="training-progress-heading"><span>{{ trainingHeartbeat(job) }}</span><strong>{{ job.progress }}%</strong></div><div class="training-stream-progress" role="progressbar" :aria-label="`${job.version}训练进度`" :aria-valuenow="job.progress" aria-valuemin="0" aria-valuemax="100" :aria-valuetext="trainingProgressTitle(job)"><span :style="{ transform: `scaleX(${job.progress / 100})` }"></span></div><small>{{ trainingEta(job) }}</small></div><small v-if="job.cancel_requested" class="text-warning d-block mt-1">正在等待安全停止点</small><small v-if="job.error_message" class="text-danger d-block mt-1">{{ job.error_message }}</small></td>
                    <td>{{ job.sample_count || '—' }}<small v-if="job.label_distribution" class="d-block text-muted">{{ trainingLabels(job).join('/') }}：{{ trainingLabels(job).map(key => job.label_distribution?.[String(key)] ?? 0).join('/') }}</small></td>
                    <td>{{ metric(job.metrics?.macro_f1) }}</td><td>{{ metric(job.metrics?.weighted_f1) }}</td><td>{{ metric(job.metrics?.macro_auc_ovr) }}</td>
                    <td>{{ formatUpdatedAt(job.created_at) }}</td>
                    <td class="text-end"><div class="training-actions"><button v-if="job.status === 'completed'" class="btn btn-sm btn-outline-secondary" :disabled="trainingBusyId === job.id" title="导出训练摘要、各类别指标、五折结果、混淆矩阵、完整指标 JSON 与冻结配置" @click="exportTrainingJob(job)"><i class="bi bi-download me-1"></i>导出完整指标 ZIP</button><button v-if="['queued','running'].includes(job.status)" class="btn btn-sm btn-outline-danger" :disabled="trainingBusyId === job.id || job.cancel_requested" @click="cancelTrainingJob(job)">取消</button><button v-if="['failed','cancelled'].includes(job.status)" class="btn btn-sm btn-outline-secondary" :disabled="trainingBusyId === job.id" @click="retryTrainingJob(job)">重新运行</button><button v-if="job.status === 'completed' && !job.is_active" class="btn btn-sm btn-outline-primary" :disabled="trainingBusyId === job.id" @click="activateTrainingJob(job)">{{ trainingJobs.some(item => item.is_active) ? '启用/回滚到此版' : '启用模型' }}</button><template v-else-if="job.is_active"><span class="text-success small fw-semibold">正在使用</span><button class="btn btn-sm btn-outline-danger" :disabled="trainingBusyId === job.id" @click="deactivateTrainingJob(job)">取消启用</button></template></div></td>
                  </tr>
                  <tr v-if="expandedTrainingJobId === job.id" class="training-detail-row"><td colspan="8">
                    <div class="training-detail-grid">
                      <section><h6>冻结配置</h6><dl><div><dt>特征</dt><dd>{{ experimentDefinition(job).feature }}</dd></div><div><dt>分类器</dt><dd>{{ experimentDefinition(job).classifier }}</dd></div><div><dt>数据来源</dt><dd>{{ job.config_snapshot?.dataset_source === 'uploaded' ? '管理员上传' : '系统专家金标准' }}</dd></div><div><dt>数据版本</dt><dd>{{ job.config_snapshot?.dataset_name || '历史实时数据' }}</dd></div><div><dt>评估划分</dt><dd>{{ job.metrics?.split_strategy === 'sentence_stratified_5fold' || job.config_snapshot?.dataset_split_strategy === 'sentence_stratified_5fold' ? '句子级分层五折' : '被试级分组五折' }}</dd></div><div><dt>嵌入模型</dt><dd>{{ job.config_snapshot?.embedding_model || '不使用远程嵌入' }}</dd></div><div><dt>向量维度</dt><dd>{{ job.config_snapshot?.dimensions || '—' }}</dd></div><div><dt>数据指纹</dt><dd class="fingerprint">{{ job.dataset_fingerprint || '训练开始后生成' }}</dd></div><div><dt>产物校验</dt><dd class="fingerprint">{{ job.artifact_sha256 || '尚未生成' }}</dd></div></dl><div v-if="job.metrics?.subject_leakage_risk" class="alert alert-warning py-2 px-3 mt-3 mb-0 small"><i class="bi bi-exclamation-triangle me-1"></i>{{ job.metrics?.evaluation_warning }}</div></section>
                      <section v-if="job.metrics"><h6>整体指标</h6><div class="training-summary-metrics"><span><small>Accuracy</small><strong>{{ metric(job.metrics.accuracy) }}</strong></span><span><small>Macro-F1</small><strong>{{ metric(job.metrics.macro_f1) }}</strong></span><span><small>Weighted-F1</small><strong>{{ metric(job.metrics.weighted_f1) }}</strong></span><span><small>Macro-AUC</small><strong>{{ metric(job.metrics.macro_auc_ovr) }}</strong></span><span><small>交叉熵</small><strong>{{ metric(job.metrics.cross_entropy) }}</strong></span></div></section>
                      <section v-if="job.metrics?.per_class"><h6>各类别指标</h6><div class="class-performance-chart mb-3"><article v-for="label in trainingLabels(job)" :key="`class-chart-${label}`"><div><strong>{{ trainingLabelName(label) }}</strong><small>n={{ job.metrics?.per_class?.[String(label)]?.support }}</small></div><div class="class-performance-bars"><span><i :style="{ width: `${metricPercent(job.metrics?.per_class?.[String(label)]?.precision)}%` }"></i><small>精准率 {{ metric(job.metrics?.per_class?.[String(label)]?.precision) }}</small></span><span><i :style="{ width: `${metricPercent(job.metrics?.per_class?.[String(label)]?.recall)}%` }"></i><small>召回率 {{ metric(job.metrics?.per_class?.[String(label)]?.recall) }}</small></span><span class="is-f1"><i :style="{ width: `${metricPercent(job.metrics?.per_class?.[String(label)]?.f1)}%` }"></i><small>F1 {{ metric(job.metrics?.per_class?.[String(label)]?.f1) }}</small></span></div></article></div><div class="table-responsive"><table class="table table-sm"><thead><tr><th>标签</th><th>样本</th><th>Precision</th><th>Recall</th><th>F1</th></tr></thead><tbody><tr v-for="label in trainingLabels(job)" :key="label"><td>{{ trainingLabelName(label) }}</td><td>{{ job.metrics?.per_class?.[String(label)]?.support }}</td><td>{{ metric(job.metrics?.per_class?.[String(label)]?.precision) }}</td><td>{{ metric(job.metrics?.per_class?.[String(label)]?.recall) }}</td><td>{{ metric(job.metrics?.per_class?.[String(label)]?.f1) }}</td></tr></tbody></table></div></section>
                      <section v-if="job.metrics?.evaluation_summary || job.metrics?.folds" class="evaluation-data-section">
                        <h6>模型评估数据</h6>
                        <div class="evaluation-facts">
                          <span><small>评估方法</small><strong>{{ splitStrategyLabel(job) }}</strong></span>
                          <span><small>可用样本</small><strong>{{ job.metrics?.evaluation_summary?.sample_count ?? job.sample_count }}</strong></span>
                          <span><small>被试数量</small><strong>{{ job.metrics?.evaluation_summary?.participant_count ?? '未提供' }}</strong></span>
                          <span><small>折外测试次数</small><strong>{{ job.metrics?.evaluation_summary?.out_of_fold_sample_count ?? job.sample_count }}</strong></span>
                        </div>
                        <p class="evaluation-distribution"><b>完整数据类别：</b>{{ labelDistributionText(job.metrics?.evaluation_summary?.label_distribution || job.label_distribution || undefined) }}</p>
                        <div class="evaluation-integrity" :class="job.metrics?.subject_leakage_risk ? 'is-warning' : 'is-valid'">
                          <i class="bi" :class="job.metrics?.subject_leakage_risk ? 'bi-exclamation-triangle' : 'bi-check-circle'"></i>
                          <span v-if="job.metrics?.subject_leakage_risk">缺少可靠被试 ID，当前是句子级分层五折；同一被试文本可能跨折，指标存在偏高风险。</span>
                          <span v-else>按被试分组划分，每一折的训练被试与测试被试互斥；代码同时执行交集为空断言。</span>
                        </div>
                        <p class="evaluation-boundary"><b>注意：</b>每条样本恰好作为测试数据一次，页面整体指标、混淆矩阵和 ROC 均来自这些折外结果。评估结束后会再用全部数据拟合生产模型，因此“最终模型”本身没有在本页面重复报告训练集自测成绩，也尚未经过独立外部数据集验证。</p>
                      </section>
                      <section v-if="job.metrics?.folds"><h6>五折训练集 / 测试集实测</h6><div class="fold-visual mb-3"><span v-for="fold in job.metrics.folds" :key="`fold-bar-${fold.fold}`"><i :style="{ height: `${metricPercent(fold.macro_f1)}%` }"></i><b>{{ metric(fold.macro_f1) }}</b><small>Fold {{ fold.fold }}</small></span></div><div class="table-responsive"><table class="table table-sm fold-data-table"><thead><tr><th>折</th><th>训练集</th><th>测试集</th><th>训练 Macro-F1</th><th>测试 Macro-F1</th><th>测试 Accuracy</th><th>测试集类别分布</th></tr></thead><tbody><tr v-for="fold in job.metrics.folds" :key="fold.fold"><td>Fold {{ fold.fold }}</td><td>{{ fold.train_sample_count ?? '历史未记录' }}</td><td>{{ fold.sample_count }}</td><td>{{ metric(fold.train_macro_f1) }}</td><td>{{ metric(fold.macro_f1) }}</td><td>{{ metric(fold.accuracy) }}</td><td>{{ labelDistributionText(fold.test_label_distribution) }}</td></tr></tbody></table></div><p class="small text-muted mt-2 mb-0">训练 Macro-F1 明显高于测试 Macro-F1 时提示过拟合；五折测试结果波动较大时，说明模型对数据划分或不同被试较敏感。</p></section>
                      <section v-if="job.metrics?.confusion_matrix"><h6>混淆矩阵</h6><div class="confusion-matrix" :style="{ gridTemplateColumns: `repeat(${trainingLabels(job).length + 1}, minmax(44px, 1fr))` }"><span class="matrix-corner">真值 \ 预测</span><strong v-for="label in trainingLabels(job)" :key="`h${label}`">{{ label }}</strong><template v-for="(row,rowIndex) in job.metrics.confusion_matrix" :key="rowIndex"><strong>{{ trainingLabels(job)[rowIndex] }}</strong><span v-for="(value,columnIndex) in row" :key="columnIndex" :class="{ 'is-diagonal': rowIndex === columnIndex }">{{ value }}</span></template></div></section>
                    </div>
                  </td></tr>
                </template>
              </template>
            </tbody>
          </table>
        </div>
        <div v-else class="text-muted text-center py-4">尚未创建训练任务</div>
        <details class="training-audit mt-3"><summary>模型训练与发布审计（{{ trainingAudits.length }}）</summary><div v-if="trainingAuditLoading" class="py-3 text-center"><span class="spinner-border spinner-border-sm"></span></div><div v-else class="audit-list mt-3"><article v-for="item in trainingAudits" :key="item.id" class="audit-row"><span class="audit-icon"><i class="bi bi-clock-history"></i></span><div><strong>{{ trainingAuditLabel(item.action) }}</strong><small class="d-block text-muted">{{ item.version || item.job_id || '系统任务' }}</small></div><div class="audit-meta"><span>{{ item.actor_name || '系统 Worker' }}</span><time>{{ formatUpdatedAt(item.created_at) }}</time></div></article><p v-if="!trainingAudits.length" class="text-muted small mb-0">暂无模型训练操作记录。</p></div></details>
      </div>
    </details>

    <details class="research-fold-card model-performance-card mb-4" open>
      <summary><span><i class="bi bi-clipboard2-data-fill"></i><strong>模型性能评估</strong><small>依据真实折外数据自动生成结论，仅展开最新训练版本</small></span><i class="bi bi-chevron-down fold-chevron"></i></summary>
      <div class="fold-content">
        <div v-if="modelEvaluationLoading" class="performance-loading"><span class="spinner-border spinner-border-sm text-primary"></span><span>正在校验训练产物与最新评估版本…</span></div>
        <div v-else-if="modelEvaluationError" class="alert alert-danger mb-0"><i class="bi bi-exclamation-triangle-fill me-2"></i>{{ modelEvaluationError }}。为避免显示混合版本，当前不使用任务表中的旧指标兜底。</div>
        <div v-else-if="latestPerformanceGroup && latestBestPerformanceJob" class="latest-performance">
          <div class="performance-version-heading">
            <div><span class="performance-latest-badge"><i class="bi bi-stars"></i>最新结果 · 已绑定训练产物</span><h5>{{ latestPerformanceGroup.display_version }}</h5><p>{{ latestPerformanceGroup.models.length }} 个已完成模型 · 数据版本：{{ latestPerformanceGroup.dataset_version || '未记录' }} · {{ formatUpdatedAt(latestPerformanceGroup.trained_at) }}</p></div>
            <div class="performance-method-badge"><i class="bi bi-diagram-3"></i><span>{{ evaluationSplitLabel(latestBestPerformanceJob) }}<small>{{ latestBestPerformanceJob.cross_validation.fold_count }} 折折外评估</small></span></div>
          </div>

          <div v-if="!latestPerformanceGroup.comparable" class="alert alert-warning"><i class="bi bi-shield-exclamation me-2"></i>{{ latestPerformanceGroup.comparison_warning || '该版本模型的数据快照或标签顺序不一致，已停止自动比较。' }}</div>

          <div class="performance-summary-grid">
            <article v-for="job in latestPerformanceGroup.models" :key="`summary-${job.model_id}`" :class="{ 'is-best': job.model_id === latestPerformanceGroup.best_model_id }">
              <div><strong>{{ evaluationModelName(job) }}</strong><small class="performance-scheme-name">{{ job.model_version }} · {{ isManuallyTuned(job) ? '人工调参' : '默认参数' }}</small><small class="parameter-result-summary">{{ parameterSummary(job) }}</small></div>
              <div class="performance-summary-badges"><span v-if="job.model_id === latestPerformanceGroup.best_model_id" class="best-model-result">最佳（Macro-F1）</span><span class="overfit-risk-badge" :class="overfitRisk(job).tone">{{ overfitRisk(job).label }}<template v-if="overfitRisk(job).gap !== null"> · 差距 {{ metric(overfitRisk(job).gap) }}</template></span></div>
              <dl><div><dt>Macro-F1</dt><dd>{{ metric(job.summary.macro_f1) }}</dd></div><div><dt>Accuracy</dt><dd>{{ metric(job.summary.accuracy) }}</dd></div><div><dt>Weighted-F1</dt><dd>{{ metric(job.summary.weighted_f1) }}</dd></div><div><dt>Macro-AUC</dt><dd>{{ metric(job.summary.macro_auc_ovr) }}</dd></div></dl>
            </article>
          </div>

          <section class="model-evaluation-panel performance-visualizations">
            <div class="model-evaluation-heading">
              <div>
                <strong>模型指标图形化比较</strong>
                <small>仅使用上方已绑定的最新训练版本；条形长度统一按 0–1 指标范围显示。</small>
              </div>
              <span class="metric-primary-badge"><i class="bi bi-stars me-1"></i>主要排序：Macro-F1</span>
            </div>
            <div class="metric-chart" role="img" aria-label="最新训练版本的 Macro-F1、Weighted-F1 和 Macro-AUC 对比图">
              <article v-for="job in latestPerformanceModels" :key="`performance-chart-${job.model_id}`" class="metric-chart-row">
                <div class="metric-chart-label">
                  <strong>{{ evaluationModelName(job) }}</strong>
                  <small>{{ job.model_version }}</small>
                </div>
                <div class="metric-chart-bars">
                  <div v-for="definition in metricDefinitions" :key="`${job.model_id}-${definition.key}`" class="metric-bar-row">
                    <span>{{ definition.title }}</span>
                    <div class="metric-bar-track">
                      <i v-if="typeof job.summary[definition.key] === 'number'" class="metric-bar-fill" :class="`is-${definition.key}`" :style="{ width: `${metricPercent(job.summary[definition.key])}%` }"></i>
                      <small v-else>该模型无可比指标</small>
                    </div>
                    <b>{{ metric(job.summary[definition.key]) }}</b>
                  </div>
                </div>
              </article>
            </div>

            <div class="class-f1-comparison">
              <div class="class-f1-heading">
                <div><strong>三类 F1 横向比较</strong><small>逐类检查监控、调控和评估，避免平均指标掩盖单一类别失效。</small></div>
                <div class="class-f1-legend"><span v-for="definition in classF1Definitions" :key="`performance-legend-${definition.key}`" :class="definition.colorClass"><i></i>{{ definition.code }}</span></div>
              </div>
              <div class="class-f1-chart" role="img" aria-label="最新训练版本的监控、调控和评估类别 F1 对比图">
                <article v-for="job in latestPerformanceModels" :key="`performance-class-f1-${job.model_id}`" class="class-f1-model-row">
                  <div class="metric-chart-label"><strong>{{ evaluationModelName(job) }}</strong><small>{{ job.model_version }}</small></div>
                  <div class="class-f1-model-bars">
                    <div v-for="definition in classF1Definitions" :key="`${job.model_id}-${definition.key}`" class="class-f1-bar-row">
                      <span><b>{{ definition.label }}</b><small>{{ definition.code }}</small></span>
                      <div class="metric-bar-track"><i class="metric-bar-fill" :class="definition.colorClass" :style="{ width: `${metricPercent(performanceClassF1(job, definition.key))}%` }"></i></div>
                      <strong>{{ metric(performanceClassF1(job, definition.key)) }}</strong>
                    </div>
                  </div>
                </article>
              </div>
              <p class="class-f1-note"><i class="bi bi-info-circle me-1"></i>即使 Macro-F1 较高，只要任一类别 F1 接近 0，也不应直接用于正式画像。</p>
            </div>

            <section class="probability-evaluation-section">
              <div class="visual-section-heading">
                <div><strong>区分能力与概率损失</strong><small>ROC 越靠近左上角越好；交叉熵越低越好，两者不能相互替代。</small></div>
                <span><i class="bi bi-activity me-1"></i>{{ evaluationSplitLabel(latestBestPerformanceJob) }} · 折外预测</span>
              </div>
              <div class="roc-method-note"><i class="bi bi-shield-check"></i><div><strong>数据来源与可信边界</strong><p>ROC 与交叉熵均来自该训练版本保存的五折折外预测，每条样本只作为测试数据一次。当前属于内部交叉验证，不等同于独立外部测试；LinearSVC 的 decision score 可用于 ROC 排序，但不是概率，因此不计算交叉熵。</p></div></div>
              <div class="probability-visual-layout">
                <div class="roc-comparison-grid">
                  <article v-for="job in latestPerformanceModels" :key="`performance-roc-${job.model_id}`" class="roc-model-card">
                    <div class="roc-card-heading"><div><strong>{{ evaluationModelName(job) }}</strong><small>{{ job.model_version }}</small></div><b>Macro-AUC {{ metric(job.summary.macro_auc_ovr) }}</b></div>
                    <template v-if="job.roc_curves">
                      <button class="roc-chart-button" type="button" :aria-label="`放大查看 ${evaluationModelName(job)} ROC 曲线`" @click="openRoc(job)">
                        <svg class="roc-chart" viewBox="0 0 300 205" role="img" :aria-label="`${evaluationModelName(job)} ROC 曲线`">
                          <line v-for="tick in [0,0.25,0.5,0.75,1]" :key="`eval-gx-${job.model_id}-${tick}`" :x1="38 + tick * 244" y1="12" :x2="38 + tick * 244" y2="176" class="roc-grid-line" />
                          <line v-for="tick in [0,0.25,0.5,0.75,1]" :key="`eval-gy-${job.model_id}-${tick}`" x1="38" :y1="12 + tick * 164" x2="282" :y2="12 + tick * 164" class="roc-grid-line" />
                          <line x1="38" y1="176" x2="282" y2="12" class="roc-chance-line" />
                          <path v-for="definition in rocCurveDefinitions" :key="`${job.model_id}-curve-${definition.key}`" :d="rocPath(job.roc_curves?.[definition.key])" fill="none" :stroke="definition.color" :stroke-width="definition.width" stroke-linecap="round" stroke-linejoin="round" />
                          <line x1="38" y1="176" x2="282" y2="176" class="roc-axis-line" /><line x1="38" y1="12" x2="38" y2="176" class="roc-axis-line" />
                          <text x="160" y="199" class="roc-axis-label">假阳性率 FPR</text><text x="11" y="98" class="roc-axis-label" transform="rotate(-90 11 98)">真阳性率 TPR</text>
                          <text x="34" y="190" class="roc-tick-label">0</text><text x="278" y="190" class="roc-tick-label">1</text><text x="24" y="179" class="roc-tick-label">0</text><text x="24" y="16" class="roc-tick-label">1</text>
                        </svg>
                        <span class="roc-expand-hint"><i class="bi bi-arrows-fullscreen"></i>点击放大查看</span>
                      </button>
                      <div class="roc-legend"><span v-for="definition in rocCurveDefinitions" :key="`${job.model_id}-legend-${definition.key}`"><i :style="{ background: definition.color }"></i>{{ definition.label }} <b>{{ metric(job.roc_curves?.[definition.key]?.auc) }}</b></span></div>
                    </template>
                    <div v-else class="roc-empty-state"><i class="bi bi-graph-up"></i><span>该训练产物未保存 ROC 曲线点。</span></div>
                  </article>
                </div>
                <aside class="cross-entropy-panel">
                  <div class="cross-entropy-heading"><span><i class="bi bi-bullseye"></i></span><div><strong>交叉熵对比</strong><small>越低表示对正确类别分配的概率越充分。</small></div></div>
                  <div v-if="latestCrossEntropyModels.length" class="cross-entropy-bars">
                    <article v-for="job in latestCrossEntropyModels" :key="`performance-loss-${job.model_id}`"><div><strong>{{ evaluationModelName(job) }}</strong><b>{{ metric(job.summary.cross_entropy) }}</b></div><div class="loss-bar-track"><i :style="{ width: `${crossEntropyPercent(job.summary.cross_entropy ?? undefined)}%` }"></i></div></article>
                  </div>
                  <p v-else class="cross-entropy-empty">本版本没有可比较的概率损失数据。</p>
                  <div class="loss-model-note"><strong>为什么部分模型不参与？</strong><p>LinearSVC 没有 predict_proba；LogisticRegression、RandomForest 与提升树等概率模型才计算交叉熵。</p></div>
                </aside>
              </div>
            </section>
          </section>

          <template v-if="latestBestPerformanceJob">
            <div class="performance-verdict" :class="performanceVerdict(latestBestPerformanceJob).tone">
              <span class="performance-verdict-icon"><i class="bi bi-clipboard2-check"></i></span>
              <div><small>当前版本综合结论</small><h4>{{ performanceVerdict(latestBestPerformanceJob).level }}</h4><p><b>最佳（Macro-F1）：{{ evaluationModelName(latestBestPerformanceJob) }}</b>。并列时依次比较 Macro-Recall、Weighted-F1；选优后同步使用训练集与折外预测差距检查过拟合。</p></div>
            </div>
            <div class="overfit-risk-callout" :class="overfitRisk(latestBestPerformanceJob).tone">
              <span><i class="bi" :class="overfitRisk(latestBestPerformanceJob).level === 'high' ? 'bi-exclamation-octagon-fill' : overfitRisk(latestBestPerformanceJob).level === 'medium' ? 'bi-exclamation-triangle-fill' : 'bi-shield-check'"></i></span>
              <div><small>最优模型同步风险检查</small><strong>{{ overfitRisk(latestBestPerformanceJob).label }}<template v-if="overfitRisk(latestBestPerformanceJob).gap !== null"> · 训练—折外差距 {{ metric(overfitRisk(latestBestPerformanceJob).gap) }}</template></strong><p>{{ overfitRisk(latestBestPerformanceJob).message }}</p><small class="risk-rule-note">辅助判定：差距 ≤ 0.080 为低风险，0.081–0.150 为中等风险，＞0.150 为高风险；最终仍需结合折间波动与独立外部验证。</small></div>
            </div>

            <div class="performance-main-grid">
              <section class="performance-metric-panel">
                <div class="performance-section-title"><div><strong>核心性能指标</strong><small>全部来自训练时保存的折外预测结果</small></div><span>n={{ latestBestPerformanceJob.dataset.sample_count }}</span></div>
                <div class="performance-metric-chart">
                  <article v-for="item in performanceMetricRows(latestBestPerformanceJob)" :key="item.label">
                    <div><strong :title="item.note">{{ item.label }} <i class="bi bi-info-circle"></i></strong><small>{{ item.note }}</small></div>
                    <div class="performance-bar-track"><i :style="{ width: `${metricPercent(item.value)}%` }"></i></div>
                    <b>{{ metric(item.value) }}</b>
                  </article>
                </div>
              </section>

              <section class="performance-conclusion-panel">
                <div class="performance-section-title"><div><strong>自动评估结论</strong><small>随最新训练真实指标自动更新</small></div></div>
                <ol><li v-for="finding in performanceVerdict(latestBestPerformanceJob).findings" :key="finding">{{ finding }}</li></ol>
                <div class="performance-boundary"><i class="bi bi-info-circle"></i><p>参照项目书的多指标评价思路：同时查看 AUC、Accuracy、Precision、Recall、Specificity、F1、混淆矩阵、交叉验证稳定性和外部验证。项目书中的 PHQ-9 数值仅作为展示范式，不作为本元认知三分类任务的硬性合格线。</p></div>
              </section>
            </div>

            <section class="performance-evidence-panel">
              <div class="performance-section-title"><div><strong>交叉验证证据与可信边界</strong><small>由最新最佳模型的真实五折折外结果生成</small></div><span>{{ latestBestPerformanceJob.cross_validation.fold_count }} 折</span></div>
              <div class="performance-evidence-grid">
                <article>
                  <small>5-fold Macro-F1 稳定性</small>
                  <strong>{{ metric(latestBestPerformanceJob.cross_validation.macro_f1_mean) }} ± {{ metric(latestBestPerformanceJob.cross_validation.macro_f1_std) }}</strong>
                  <p>五折测试折 Macro-F1 均值 ± 样本标准差；极差 {{ metric(latestBestPerformanceJob.cross_validation.macro_f1_range) }}。</p>
                </article>
                <article>
                  <small>5-fold Macro-AUC 稳定性</small>
                  <strong>{{ metric(latestBestPerformanceJob.cross_validation.macro_auc_mean) }} ± {{ metric(latestBestPerformanceJob.cross_validation.macro_auc_std) }}</strong>
                  <p>分别计算 5 个测试折的 Macro-AUC 并统计均值 ± 样本标准差，用于观察不同划分下的性能稳定性；极差 {{ metric(latestBestPerformanceJob.cross_validation.macro_auc_range) }}。</p>
                </article>
                <article :class="{ 'is-verified': latestBestPerformanceJob.cross_validation.subject_disjoint_audit?.all_folds_verified }"><small>被试泄漏检查</small><strong>{{ latestBestPerformanceJob.cross_validation.subject_disjoint_audit?.all_folds_verified ? '五折交集均为 0' : '证据不完整' }}</strong><p>{{ latestBestPerformanceJob.cross_validation.subject_disjoint_audit?.note }}</p></article>
                <article><small>外部验证</small><strong>{{ latestBestPerformanceJob.dataset.external_holdout ? '已完成' : '尚未完成' }}</strong><p>内部交叉验证不能替代独立学校、任务或新被试数据验证。</p></article>
              </div>
              <div class="weighted-metric-note"><i class="bi bi-info-circle-fill"></i><p><b>加权指标说明：</b>Weighted-Precision、Weighted-Recall 与 Weighted-F1 均按各类别真实样本数加权，多数类影响更大。当前系统原有 Weighted-F1 已保留；Weighted-Recall 在单标签多分类任务中通常与 Accuracy 相同，但仍单独展示以保持报告口径完整。</p></div>
              <details v-if="latestBestPerformanceJob.error_analysis" class="performance-error-cases">
                <summary class="d-flex align-items-center justify-content-between flex-wrap gap-2">
                  <span>查看折外错误案例（{{ latestBestPerformanceJob.error_analysis.total_error_count }} 条）</span>
                  <button
                    v-if="latestBestPerformanceJob.error_analysis.total_error_count > 0"
                    type="button"
                    class="btn btn-sm btn-outline-primary py-0 px-2 ms-auto"
                    :disabled="isExportingErrorCases"
                    @click.stop="exportOofErrorCases(latestBestPerformanceJob)"
                  >
                    <span v-if="isExportingErrorCases" class="spinner-border spinner-border-sm me-1"></span>
                    <i v-else class="bi bi-download me-1"></i>导出全部错误案例 (CSV)
                  </button>
                </summary>
                <p>{{ latestBestPerformanceJob.error_analysis.note }}</p>
                <div class="table-responsive"><table class="table table-sm"><thead><tr><th>被试</th><th>清洗后文本</th><th>真实标签</th><th>预测标签</th></tr></thead><tbody><tr v-for="(row, index) in latestBestPerformanceJob.error_analysis.cases.slice(0, 20)" :key="`error-${index}`"><td>{{ row.participant_id || '未提供' }}</td><td>{{ row.text }}</td><td>{{ latestBestPerformanceJob.labels.find(label => label.id === row.true_label)?.name || row.true_label }}</td><td>{{ latestBestPerformanceJob.labels.find(label => label.id === row.predicted_label)?.name || row.predicted_label }}</td></tr></tbody></table></div>
                <small>页面展示前 20 条预览；点击上方“导出全部错误案例”按钮可完整下载全部 {{ latestBestPerformanceJob.error_analysis.total_error_count }} 条折外错误样本 CSV 文件。</small>
              </details>
              <details class="performance-error-cases evidence-gap-list">
                <summary>查看仍缺少的研究证据</summary>
                <ul>
                  <li><b>模型间统计显著性：</b>{{ latestBestPerformanceJob.evidence_coverage.pairwise_statistical_test ? '已生成' : latestBestPerformanceJob.evidence_coverage.notes.pairwise_statistical_test }}</li>
                  <li><b>跨任务/跨情境迁移：</b>{{ latestBestPerformanceJob.evidence_coverage.cross_task_transfer ? '已生成' : latestBestPerformanceJob.evidence_coverage.notes.cross_task_transfer }}</li>
                  <li><b>专家标签质量：</b>{{ latestBestPerformanceJob.evidence_coverage.expert_reliability_bound_to_dataset ? '已与训练版本绑定' : latestBestPerformanceJob.evidence_coverage.notes.expert_reliability_bound_to_dataset }}</li>
                  <li><b>ASR 与文本清洗质量：</b>{{ latestBestPerformanceJob.evidence_coverage.asr_quality_bound_to_dataset ? '已与训练版本绑定' : latestBestPerformanceJob.evidence_coverage.notes.asr_quality_bound_to_dataset }}</li>
                </ul>
              </details>
            </section>

            <section class="performance-model-comparison">
              <div class="performance-section-title"><div><strong>同版本模型比较</strong><small>绿色标记只在数据指纹、标签顺序一致且本批次所选模型结果齐全时出现；参数可在详情和导出报告中追溯</small></div></div>
              <div class="table-responsive"><table class="table align-middle mb-0"><thead><tr><th>模型</th><th title="全部折外样本预测正确比例">Accuracy</th><th title="各类别 Precision 等权平均">Macro-P</th><th title="各类别 Recall 等权平均">Macro-R</th><th title="首要模型比较指标">Macro-F1</th><th title="按各类别真实样本数加权的 F1">Weighted-F1</th><th title="一对其余的折外 ROC-AUC 平均">Macro-AUC</th><th title="各折 Macro-F1 最大值减最小值">折间极差</th><th title="平均训练 Macro-F1 与折外 Macro-F1 的差距">过拟合风险</th></tr></thead><tbody><template v-for="job in latestPerformanceGroup.models" :key="`performance-${job.model_id}`"><tr :class="{ 'is-best-performance': job.model_id === latestPerformanceGroup.best_model_id }"><td><strong>{{ evaluationModelName(job) }}</strong><small>{{ job.model_version }}</small></td><td>{{ metric(job.summary.accuracy) }}</td><td>{{ metric(job.summary.macro_precision) }}</td><td>{{ metric(job.summary.macro_recall) }}</td><td><b>{{ metric(job.summary.macro_f1) }}</b></td><td>{{ metric(job.summary.weighted_f1) }}</td><td>{{ metric(job.summary.macro_auc_ovr) }}</td><td>{{ metric(job.cross_validation.macro_f1_range) }}</td><td><span class="overfit-risk-badge" :class="overfitRisk(job).tone">{{ overfitRisk(job).label }}<template v-if="overfitRisk(job).gap !== null"> {{ metric(overfitRisk(job).gap) }}</template></span></td></tr><tr><td colspan="9" class="p-0"><details class="performance-model-details"><summary>查看类别、混淆矩阵与训练信息</summary><div class="performance-detail-grid"><section><strong>各类别表现（Support 为折外真实样本数）</strong><div class="table-responsive"><table class="table table-sm"><thead><tr><th>类别</th><th>Precision</th><th>Recall</th><th>F1</th><th>Support</th></tr></thead><tbody><tr v-for="row in job.per_class" :key="`${job.model_id}-${row.label_id}`"><td>{{ row.label_name }}</td><td>{{ metric(row.precision) }}</td><td>{{ metric(row.recall) }}</td><td>{{ metric(row.f1) }}</td><td>{{ row.support ?? '—' }}</td></tr></tbody></table></div></section><section><strong>混淆矩阵（行=真实，列=预测）</strong><div class="table-responsive"><table class="table table-sm"><thead><tr><th>真实＼预测</th><th v-for="label in job.labels" :key="`head-${label.id}`">{{ label.name }}</th></tr></thead><tbody><tr v-for="(row, rowIndex) in job.confusion_matrix" :key="`matrix-${rowIndex}`"><th>{{ job.labels[rowIndex]?.name }}</th><td v-for="(value, columnIndex) in row" :key="`matrix-${rowIndex}-${columnIndex}`">{{ value }}</td></tr></tbody></table></div><small v-if="job.confusion_pairs.length" class="text-muted">主要混淆：{{ job.confusion_pairs.slice(0, 3).map(pair => `${pair.actual_label}→${pair.predicted_label} ${pair.count}次`).join('；') }}</small><small v-else class="text-muted">本次折外结果未产生非零混淆对。</small></section><section><strong>交叉验证与稳定性</strong><dl class="performance-compact-facts"><dt>CV Macro-F1</dt><dd><b>{{ metric(job.cross_validation.macro_f1_mean) }} ± {{ metric(job.cross_validation.macro_f1_std) }}</b><small class="validation-level-note">五折测试折 Macro-F1 均值 ± 样本标准差；极差 {{ metric(job.cross_validation.macro_f1_range) }}</small></dd><dt>CV Macro-AUC</dt><dd><b>{{ metric(job.cross_validation.macro_auc_mean) }} ± {{ metric(job.cross_validation.macro_auc_std) }}</b><small class="validation-level-note">五折测试折 Macro-AUC 均值 ± 样本标准差；极差 {{ metric(job.cross_validation.macro_auc_range) }}</small></dd><dt>训练—折外差距</dt><dd class="generalization-gap"><b>{{ metric(job.cross_validation.train_test_macro_f1_gap) }}</b><small><i class="bi bi-info-circle" />训练集指标与折外预测指标之差，用于辅助观察模型过拟合程度；差距越大通常意味着模型在训练数据上的性能明显高于未见数据。</small></dd><dt>过拟合风险</dt><dd><span class="overfit-risk-badge" :class="overfitRisk(job).tone">{{ overfitRisk(job).label }}</span><small class="validation-level-note">{{ overfitRisk(job).message }}</small></dd><dt>验证等级</dt><dd><span class="validation-level" :class="{ 'is-external': job.dataset.external_holdout }"><i class="bi" :class="job.dataset.external_holdout ? 'bi-patch-check-fill' : 'bi-shield-check'" />{{ job.dataset.external_holdout ? '独立留出测试' : '内部交叉验证' }}</span><small v-if="!job.dataset.external_holdout" class="validation-level-note">内部五折折外预测，尚无独立外部测试集</small></dd><dt>AUC 分数来源</dt><dd>{{ job.roc_evaluation?.score_type === 'decision_function' ? 'decision score（不是概率）' : job.roc_evaluation?.score_type === 'predict_proba' ? 'predict_proba' : '未记录' }}</dd></dl></section><section><strong>数据分布</strong><p class="small text-muted mb-0">{{ job.labels.map(label => `${label.name} ${job.dataset.class_distribution?.[String(label.id)] ?? '—'}`).join(' · ') }}</p></section><section class="performance-data-facts"><strong>评估、模型与数据来源</strong><dl><dt>训练版本</dt><dd>{{ job.model_version }}</dd><dt>训练时间</dt><dd>{{ formatUpdatedAt(job.trained_at) }}</dd><dt>数据版本</dt><dd>{{ job.dataset.version || '未记录' }}</dd><dt>数据指纹</dt><dd>{{ job.dataset.fingerprint?.slice(0, 16) || '未记录' }}</dd><dt>特征/分类器</dt><dd>{{ evaluationModelName(job) }}</dd><dt>Embedding</dt><dd>{{ job.model_info.embedding_provider || '不适用' }} / {{ job.model_info.embedding_model || '不适用' }}</dd><dt>样本/被试/类别</dt><dd>{{ job.dataset.sample_count }} / {{ job.dataset.participant_count ?? '未记录' }} / {{ job.dataset.class_count }}</dd><dt>每折训练/测试数</dt><dd>{{ sampleCountRange(job.cross_validation.train_sample_counts) }} / {{ sampleCountRange(job.cross_validation.test_sample_counts) }}</dd><dt>划分/随机种子</dt><dd>{{ evaluationSplitLabel(job) }} / {{ job.dataset.random_seed ?? '未记录' }}</dd><dt>外部独立验证</dt><dd>{{ job.dataset.external_holdout ? '是' : '否，仅内部折外评估' }}</dd><dt>数据来源</dt><dd>Training Evaluation Result</dd><dt>产物校验</dt><dd>{{ job.source.metrics_sha256.slice(0, 12) }}</dd></dl></section></div></details></td></tr></template></tbody></table></div>
            </section>
          </template>

          <details v-if="historicalPerformanceGroups.length" class="performance-history">
            <summary><span><i class="bi bi-clock-history"></i><strong>过往历史结果</strong><small>{{ historicalPerformanceGroups.length }} 个训练版本，点击展开</small></span><i class="bi bi-chevron-down"></i></summary>
            <div class="performance-history-list">
              <details v-for="group in historicalPerformanceGroups" :key="`history-${group.version_id}`" class="performance-history-version">
                <summary><span><strong>{{ group.display_version }}</strong><small>{{ group.models.length }} 个已完成模型 · 数据 {{ group.dataset_version || '未记录' }} · {{ formatUpdatedAt(group.trained_at) }}</small></span><span v-if="bestPerformanceModel(group)" class="history-score">最佳 Macro-F1 {{ metric(bestPerformanceModel(group)?.summary.macro_f1) }}</span><i class="bi bi-chevron-down"></i></summary>
                <div class="history-performance-body">
                  <div v-if="bestPerformanceModel(group)" class="history-verdict" :class="performanceVerdict(bestPerformanceModel(group)).tone"><strong>{{ performanceVerdict(bestPerformanceModel(group)).level }}</strong><span>{{ evaluationModelName(bestPerformanceModel(group)) }}</span></div>
                  <div v-if="bestPerformanceModel(group)" class="history-metrics"><span v-for="item in performanceMetricRows(bestPerformanceModel(group))" :key="`${group.version_id}-${item.label}`"><small>{{ item.label }}</small><strong>{{ metric(item.value) }}</strong></span></div>
                  <p v-else class="alert alert-warning mb-0">{{ group.comparison_warning || '该历史版本不满足同版本比较条件。' }}</p>
                </div>
              </details>
            </div>
          </details>
        </div>
        <div v-else class="performance-empty"><i class="bi bi-bar-chart-line"></i><strong>暂无可安全展示的完整训练版本</strong><p>同一批次所选模型全部训练完成，并通过数据指纹、标签顺序和产物哈希校验后，这里会自动更新；过往版本仍可折叠查看。</p><small v-if="modelEvaluationIndex?.errors.length" class="text-danger">{{ modelEvaluationIndex.errors.length }} 个历史版本校验失败，请查看后端日志。</small></div>
      </div>
    </details>

    <ModelPerformanceGuideOrb />

    <details class="research-fold-card history-comparison-card mb-4" open>
      <summary><span><i class="bi bi-intersect"></i><strong>模型效果对比</strong><small>自由选择历史训练结果，使用与模型性能评估一致的真实折外指标进行比较</small></span><i class="bi bi-chevron-down fold-chevron"></i></summary>
      <div class="fold-content">
        <div v-if="modelEvaluationLoading" class="performance-loading"><span class="spinner-border spinner-border-sm text-primary"></span><span>正在读取可比较的历史评估结果…</span></div>
        <div v-else-if="modelEvaluationError" class="alert alert-danger mb-0"><i class="bi bi-exclamation-triangle-fill me-2"></i>{{ modelEvaluationError }}</div>
        <div v-else-if="performanceVersionGroups.length" class="history-comparison-content">
          <div class="history-comparison-toolbar">
            <div><span class="comparison-kicker">CROSS-VERSION COMPARISON</span><h5>选择需要对照的训练结果</h5><p>同一训练版本中的不同模型、不同历史版本的最佳模型均可组合。跨数据版本时系统会提示可信边界。</p></div>
            <div class="history-comparison-actions"><button type="button" class="btn btn-sm btn-outline-primary" @click="selectHistoricalVersionBestModels"><i class="bi bi-trophy me-1"></i>选择各版本最佳</button><button type="button" class="btn btn-sm btn-outline-secondary" :disabled="!historicalComparisonModelIds.length" @click="clearHistoricalComparison"><i class="bi bi-x-circle me-1"></i>清空</button><button type="button" class="btn btn-sm btn-primary" :disabled="selectedHistoricalComparisonModels.length < 2" @click="exportHistoricalModelComparison"><i class="bi bi-file-earmark-spreadsheet me-1"></i>导出当前对比</button></div>
          </div>

          <details class="history-model-picker">
            <summary><span><i class="bi bi-ui-checks"></i><b>选择历史模型结果</b><small>已选择 {{ selectedHistoricalComparisonModels.length }} 项，共 {{ historicalComparisonOptions.length }} 项可用</small></span><i class="bi bi-chevron-down"></i></summary>
            <div class="history-model-picker-body">
              <label class="history-model-search"><i class="bi bi-search"></i><input v-model.trim="historicalComparisonSearch" class="form-control" type="search" placeholder="搜索训练版本、模型名称或数据版本"></label>
              <div class="history-model-version-list">
                <section v-for="group in historicalComparisonGroups" :key="`picker-${group.version_id}`" class="history-model-version-group">
                  <header><div><strong>{{ group.display_version }}</strong><small>{{ group.dataset_version || '数据版本未记录' }} · {{ formatUpdatedAt(group.trained_at) }}</small></div><span>{{ group.models.length }} 项</span></header>
                  <div class="history-model-options">
                    <label v-for="model in group.models" :key="`picker-model-${model.model_id}`" class="history-model-option" :class="{ active: historicalComparisonModelIds.includes(model.model_id) }"><input type="checkbox" :checked="historicalComparisonModelIds.includes(model.model_id)" @change="toggleHistoricalComparisonModel(model.model_id)"><span><b>{{ evaluationModelName(model) }}</b><small>{{ model.model_version }} · Macro-F1 {{ metric(model.summary.macro_f1) }}</small></span><i class="bi" :class="historicalComparisonModelIds.includes(model.model_id) ? 'bi-check-circle-fill' : 'bi-circle'"></i></label>
                  </div>
                </section>
                <p v-if="!historicalComparisonGroups.length" class="history-model-no-result">没有找到匹配的历史模型结果。</p>
              </div>
            </div>
          </details>

          <div class="comparison-validity" :class="historicalComparisonCompatibility.tone"><i class="bi" :class="historicalComparisonCompatibility.comparable ? 'bi-shield-check' : selectedHistoricalComparisonModels.length >= 2 ? 'bi-exclamation-triangle' : 'bi-info-circle'"></i><div><strong>{{ historicalComparisonCompatibility.comparable ? '严格可比' : selectedHistoricalComparisonModels.length >= 2 ? '趋势参考' : '等待选择' }}</strong><p>{{ historicalComparisonCompatibility.message }}</p></div></div>

          <template v-if="selectedHistoricalComparisonModels.length >= 2">
            <div class="history-selected-models">
              <article v-for="({ group, model }, index) in selectedHistoricalComparisonModels" :key="`selected-history-${model.model_id}`" :class="[`is-series-${index % 6}`, { 'is-overall-best': isSelectedHistoricalBestModel(model) }]"><span class="history-series-mark"></span><div><small>{{ group.display_version }}</small><strong>{{ evaluationModelName(model) }}</strong><p>{{ model.model_version }}</p><span v-if="isSelectedHistoricalBestModel(model)" class="history-overall-best-badge"><i class="bi bi-trophy-fill"></i>综合最优 · Macro-F1</span></div><button type="button" :aria-label="`移除 ${model.model_version}`" @click="toggleHistoricalComparisonModel(model.model_id)"><i class="bi bi-x-lg"></i></button></article>
            </div>

            <section v-if="selectedHistoricalBestEntry" class="history-overall-winner">
              <header><span><i class="bi bi-trophy-fill"></i></span><div><small>所选模型综合最优</small><h5>{{ evaluationModelName(selectedHistoricalBestEntry.model) }}</h5><p>{{ selectedHistoricalBestEntry.group.display_version }} · {{ selectedHistoricalBestEntry.model.model_version }}</p></div><div class="history-winner-rule"><b>选优依据</b><small>Macro-F1 优先；并列时依次比较 Macro-Recall、Weighted-F1</small></div></header>
              <div class="history-winner-metrics">
                <article v-for="definition in historicalComparisonMetricDefinitions" :key="`winner-${definition.key}`" :class="{ 'is-single-best': isHistoricalSummaryMetricBest(selectedHistoricalBestEntry.model, definition.key) }"><span>{{ definition.title }}</span><strong>{{ metric(selectedHistoricalBestEntry.model.summary[definition.key]) }}</strong><small v-if="isHistoricalSummaryMetricBest(selectedHistoricalBestEntry.model, definition.key)"><i class="bi bi-award-fill"></i>该项最优</small><small v-else><i class="bi bi-stars"></i>综合最优模型指标</small></article>
                <article :class="{ 'is-single-best': isHistoricalSummaryMetricBest(selectedHistoricalBestEntry.model, 'cross_entropy') }"><span>交叉熵</span><strong>{{ metric(selectedHistoricalBestEntry.model.summary.cross_entropy) }}</strong><small v-if="isHistoricalSummaryMetricBest(selectedHistoricalBestEntry.model, 'cross_entropy')"><i class="bi bi-award-fill"></i>该项最低（最优）</small><small v-else><i class="bi bi-stars"></i>综合最优模型指标</small></article>
                <article><span>五折 AUC 稳定性</span><strong>{{ metric(selectedHistoricalBestEntry.model.cross_validation.macro_auc_mean) }} ± {{ metric(selectedHistoricalBestEntry.model.cross_validation.macro_auc_std) }}</strong><small><i class="bi bi-stars"></i>极差 {{ metric(selectedHistoricalBestEntry.model.cross_validation.macro_auc_range) }}</small></article>
                <article><span>五折 F1 稳定性</span><strong>{{ metric(selectedHistoricalBestEntry.model.cross_validation.macro_f1_mean) }} ± {{ metric(selectedHistoricalBestEntry.model.cross_validation.macro_f1_std) }}</strong><small><i class="bi bi-stars"></i>极差 {{ metric(selectedHistoricalBestEntry.model.cross_validation.macro_f1_range) }}</small></article>
                <article :class="{ 'is-single-best': isHistoricalCvMetricBest(selectedHistoricalBestEntry.model, 'macro_f1_range') }"><span>折间极差</span><strong>{{ metric(selectedHistoricalBestEntry.model.cross_validation.macro_f1_range) }}</strong><small v-if="isHistoricalCvMetricBest(selectedHistoricalBestEntry.model, 'macro_f1_range')"><i class="bi bi-award-fill"></i>该项最低（最优）</small><small v-else><i class="bi bi-stars"></i>综合最优模型指标</small></article>
                <article :class="{ 'is-single-best': isHistoricalCvMetricBest(selectedHistoricalBestEntry.model, 'train_test_macro_f1_gap') }"><span>训练—折外差距</span><strong>{{ metric(selectedHistoricalBestEntry.model.cross_validation.train_test_macro_f1_gap) }}</strong><small v-if="isHistoricalCvMetricBest(selectedHistoricalBestEntry.model, 'train_test_macro_f1_gap')"><i class="bi bi-award-fill"></i>该项最低（最优）</small><small v-else><i class="bi bi-stars"></i>{{ overfitRisk(selectedHistoricalBestEntry.model).label }}</small></article>
              </div>
            </section>

            <section class="history-metric-comparison">
              <div class="performance-section-title"><div><strong>核心指标横向对比</strong><small>指标口径与上方“模型性能评估”一致，全部来自训练时保存的折外预测</small></div><span>首要指标：Macro-F1</span></div>
              <div class="history-metric-grid">
                <article v-for="definition in historicalComparisonMetricDefinitions" :key="`history-metric-${definition.key}`" class="history-metric-panel">
                  <header><strong>{{ definition.title }}</strong><small>{{ definition.note }}</small></header>
                  <div class="history-metric-series">
                    <div v-for="({ group, model }, index) in selectedHistoricalComparisonModels" :key="`${definition.key}-${model.model_id}`" :class="[`is-series-${index % 6}`, { 'is-overall-best': isSelectedHistoricalBestModel(model), 'is-single-best': isHistoricalSummaryMetricBest(model, definition.key) }]"><span :title="model.model_version">{{ index + 1 }}</span><div class="history-score-hover-target" tabindex="0" :aria-describedby="`history-score-tip-${definition.key}-${model.model_id}`" :aria-label="`${evaluationModelName(model)}，${definition.title} ${metric(model.summary[definition.key])}，悬浮或聚焦查看模型方案`"><div class="history-score-track"><i :style="{ width: `${metricPercent(model.summary[definition.key])}%` }"></i></div><aside :id="`history-score-tip-${definition.key}-${model.model_id}`" class="history-score-tooltip" role="tooltip"><header><span :class="`history-tooltip-index is-series-${index % 6}`">{{ index + 1 }}</span><div><small>{{ group.display_version }}</small><strong>{{ evaluationModelName(model) }}</strong></div></header><dl><dt>训练方案</dt><dd>{{ model.model_version }}</dd><dt>当前指标</dt><dd><b>{{ definition.title }} {{ metric(model.summary[definition.key]) }}</b></dd><dt>数据版本</dt><dd>{{ model.dataset.version || group.dataset_version || '未记录' }}</dd><dt>参数来源</dt><dd>{{ isManuallyTuned(model) ? '人工调参' : '默认参数' }}</dd><dt>分类器参数</dt><dd>{{ parameterSummary(model) }}</dd></dl><footer><span v-if="isSelectedHistoricalBestModel(model)" class="is-overall"><i class="bi bi-trophy-fill"></i>所选综合最优</span><span v-if="isHistoricalSummaryMetricBest(model, definition.key)" class="is-single"><i class="bi bi-award-fill"></i>该指标单项最优</span></footer></aside></div><b>{{ metric(model.summary[definition.key]) }}<i v-if="isSelectedHistoricalBestModel(model)" class="bi bi-stars" title="综合最优模型的该项指标"></i></b><small v-if="isHistoricalSummaryMetricBest(model, definition.key)" class="history-single-best-label"><i class="bi bi-award-fill"></i>单项最优</small></div>
                  </div>
                </article>
              </div>
            </section>

            <section class="history-class-comparison">
              <div class="performance-section-title"><div><strong>三类 F1 与泛化风险</strong><small>逐类识别能力与训练—折外差距同时查看，避免只按总体分数选型</small></div></div>
              <div class="history-class-grid">
                <article v-for="({ group, model }, index) in selectedHistoricalComparisonModels" :key="`history-class-${model.model_id}`" :class="[`is-series-${index % 6}`, { 'is-overall-best': isSelectedHistoricalBestModel(model) }]">
                  <header><span class="history-series-mark"></span><div><strong>{{ evaluationModelName(model) }}</strong><small>{{ group.display_version }}</small><span v-if="isSelectedHistoricalBestModel(model)" class="history-overall-best-badge"><i class="bi bi-trophy-fill"></i>综合最优</span></div><span class="overfit-risk-badge" :class="overfitRisk(model).tone">{{ overfitRisk(model).label }}</span></header>
                  <div v-for="definition in classF1Definitions" :key="`${model.model_id}-${definition.key}`" class="history-class-row" :class="{ 'is-single-best': isHistoricalClassF1Best(model, definition.key), 'is-overall-best': isSelectedHistoricalBestModel(model) }"><span>{{ definition.label }}</span><div><i :class="definition.colorClass" :style="{ width: `${metricPercent(performanceClassF1(model, definition.key))}%` }"></i></div><b>{{ metric(performanceClassF1(model, definition.key)) }}<i v-if="isSelectedHistoricalBestModel(model)" class="bi bi-stars" title="综合最优模型的类别指标"></i></b><small v-if="isHistoricalClassF1Best(model, definition.key)" class="history-single-best-label"><i class="bi bi-award-fill"></i>单项最优</small></div>
                  <footer :class="{ 'is-single-best': isHistoricalCvMetricBest(model, 'train_test_macro_f1_gap') }"><span>训练—折外差距<small v-if="isHistoricalCvMetricBest(model, 'train_test_macro_f1_gap')"><i class="bi bi-award-fill"></i>单项最优</small></span><b>{{ metric(model.cross_validation.train_test_macro_f1_gap) }}<i v-if="isSelectedHistoricalBestModel(model)" class="bi bi-stars" title="综合最优模型的泛化指标"></i></b></footer>
                </article>
              </div>
            </section>

            <section class="history-comparison-table">
              <div class="performance-section-title"><div><strong>完整指标明细</strong><small>交叉熵、折间极差与训练—折外差距越低越好；其余指标通常越高越好</small></div><span class="history-scroll-hint"><i class="bi bi-arrows-expand"></i>左右滑动查看完整指标</span></div>
              <div class="table-responsive" tabindex="0" aria-label="历史模型完整指标横向滚动表格"><table class="table align-middle mb-0"><thead><tr><th>训练结果</th><th>Accuracy</th><th>Macro-P</th><th>Macro-R</th><th>Macro-Specificity</th><th>Macro-F1</th><th>Weighted-F1</th><th>Macro-AUC</th><th>交叉熵</th><th>折间极差</th><th>训练—折外差距</th><th>验证等级</th></tr></thead><tbody>
                <tr v-for="({ group, model }, index) in selectedHistoricalComparisonModels" :key="`history-table-${model.model_id}`" :class="{ 'is-overall-best': isSelectedHistoricalBestModel(model) }">
                  <td><span :class="`history-table-series is-series-${index % 6}`"><i></i>{{ index + 1 }}</span><strong>{{ evaluationModelName(model) }}</strong><small>{{ group.display_version }} · {{ model.model_version }}</small><span v-if="isSelectedHistoricalBestModel(model)" class="history-overall-best-badge"><i class="bi bi-trophy-fill"></i>综合最优</span></td>
                  <td class="history-value-cell" :class="{ 'is-overall-model-metric': isSelectedHistoricalBestModel(model), 'is-single-best-metric': isHistoricalSummaryMetricBest(model, 'accuracy') }"><span>{{ metric(model.summary.accuracy) }}<i v-if="isSelectedHistoricalBestModel(model)" class="bi bi-stars"></i></span><small v-if="isHistoricalSummaryMetricBest(model, 'accuracy')">单项最优</small></td>
                  <td class="history-value-cell" :class="{ 'is-overall-model-metric': isSelectedHistoricalBestModel(model), 'is-single-best-metric': isHistoricalSummaryMetricBest(model, 'macro_precision') }"><span>{{ metric(model.summary.macro_precision) }}<i v-if="isSelectedHistoricalBestModel(model)" class="bi bi-stars"></i></span><small v-if="isHistoricalSummaryMetricBest(model, 'macro_precision')">单项最优</small></td>
                  <td class="history-value-cell" :class="{ 'is-overall-model-metric': isSelectedHistoricalBestModel(model), 'is-single-best-metric': isHistoricalSummaryMetricBest(model, 'macro_recall') }"><span>{{ metric(model.summary.macro_recall) }}<i v-if="isSelectedHistoricalBestModel(model)" class="bi bi-stars"></i></span><small v-if="isHistoricalSummaryMetricBest(model, 'macro_recall')">单项最优</small></td>
                  <td class="history-value-cell" :class="{ 'is-overall-model-metric': isSelectedHistoricalBestModel(model), 'is-single-best-metric': isHistoricalSummaryMetricBest(model, 'macro_specificity') }"><span>{{ metric(model.summary.macro_specificity) }}<i v-if="isSelectedHistoricalBestModel(model)" class="bi bi-stars"></i></span><small v-if="isHistoricalSummaryMetricBest(model, 'macro_specificity')">单项最优</small></td>
                  <td class="history-value-cell is-primary-metric" :class="{ 'is-overall-model-metric': isSelectedHistoricalBestModel(model), 'is-single-best-metric': isHistoricalSummaryMetricBest(model, 'macro_f1') }"><span>{{ metric(model.summary.macro_f1) }}<i v-if="isSelectedHistoricalBestModel(model)" class="bi bi-stars"></i></span><small v-if="isHistoricalSummaryMetricBest(model, 'macro_f1')">单项最优</small></td>
                  <td class="history-value-cell" :class="{ 'is-overall-model-metric': isSelectedHistoricalBestModel(model), 'is-single-best-metric': isHistoricalSummaryMetricBest(model, 'weighted_f1') }"><span>{{ metric(model.summary.weighted_f1) }}<i v-if="isSelectedHistoricalBestModel(model)" class="bi bi-stars"></i></span><small v-if="isHistoricalSummaryMetricBest(model, 'weighted_f1')">单项最优</small></td>
                  <td class="history-value-cell" :class="{ 'is-overall-model-metric': isSelectedHistoricalBestModel(model), 'is-single-best-metric': isHistoricalSummaryMetricBest(model, 'macro_auc_ovr') }"><span>{{ metric(model.summary.macro_auc_ovr) }}<i v-if="isSelectedHistoricalBestModel(model)" class="bi bi-stars"></i></span><small v-if="isHistoricalSummaryMetricBest(model, 'macro_auc_ovr')">单项最优</small></td>
                  <td class="history-value-cell" :class="{ 'is-overall-model-metric': isSelectedHistoricalBestModel(model), 'is-single-best-metric': isHistoricalSummaryMetricBest(model, 'cross_entropy') }"><span>{{ metric(model.summary.cross_entropy) }}<i v-if="isSelectedHistoricalBestModel(model)" class="bi bi-stars"></i></span><small v-if="isHistoricalSummaryMetricBest(model, 'cross_entropy')">最低（最优）</small></td>
                  <td class="history-value-cell" :class="{ 'is-overall-model-metric': isSelectedHistoricalBestModel(model), 'is-single-best-metric': isHistoricalCvMetricBest(model, 'macro_f1_range') }"><span>{{ metric(model.cross_validation.macro_f1_range) }}<i v-if="isSelectedHistoricalBestModel(model)" class="bi bi-stars"></i></span><small v-if="isHistoricalCvMetricBest(model, 'macro_f1_range')">最低（最优）</small></td>
                  <td class="history-value-cell history-risk-cell" :class="{ 'is-overall-model-metric': isSelectedHistoricalBestModel(model), 'is-single-best-metric': isHistoricalCvMetricBest(model, 'train_test_macro_f1_gap') }"><span class="overfit-risk-badge" :class="overfitRisk(model).tone">{{ metric(model.cross_validation.train_test_macro_f1_gap) }} · {{ overfitRisk(model).label }}</span><i v-if="isSelectedHistoricalBestModel(model)" class="bi bi-stars"></i><small v-if="isHistoricalCvMetricBest(model, 'train_test_macro_f1_gap')">最低（最优）</small></td>
                  <td><span class="validation-level" :class="{ 'is-external': model.dataset.external_holdout }">{{ model.dataset.external_holdout ? '独立留出测试' : `${model.cross_validation.fold_count}折内部交叉验证` }}</span></td>
                </tr>
              </tbody></table></div>
            </section>
          </template>
          <div v-else class="history-comparison-empty"><i class="bi bi-intersect"></i><strong>至少选择两项结果</strong><p>展开上方选择器，可从任意训练版本中组合需要比较的模型。</p></div>
        </div>
        <div v-else class="performance-empty"><i class="bi bi-clock-history"></i><strong>暂无历史评估结果</strong><p>模型训练完成并生成可校验评估产物后，这里会自动出现可选结果。</p></div>
      </div>
    </details>

    <details class="research-fold-card mb-4" open>
      <summary><span><i class="bi bi-sliders2"></i><strong>测评协议与多模态评分加权</strong><small>配置任务后问卷与过程行为证据的自定义融合权重</small></span><i class="bi bi-chevron-down fold-chevron"></i></summary>
    <section class="card border-0 shadow-sm protocol-config-card">
      <div class="card-body p-4">
        <div v-if="protocolErrorMessage" class="alert alert-danger py-2">
          <i class="bi bi-exclamation-triangle-fill me-2"></i>{{ protocolErrorMessage }}
        </div>
        <div v-if="protocolSuccessMessage" class="alert alert-success py-2">
          <i class="bi bi-check-circle-fill me-2"></i>{{ protocolSuccessMessage }}
        </div>
        <div class="row g-4 align-items-center">
          <div class="col-lg-5">
            <div class="d-flex align-items-center gap-2 mb-2">
              <span class="protocol-icon"><i class="bi bi-ui-checks-grid"></i></span>
              <div>
                <h5 class="mb-0">标准测评协议流程</h5>
                <small class="text-muted">控制新建测评是否包含任务后 7 点元认知问卷</small>
              </div>
            </div>
            <p class="text-muted small mb-3">
              配置会在学生开始测评时保存为运行快照。进行中的测评不会受修改影响。
            </p>
            <label class="questionnaire-switch">
              <input v-model="questionnaireEnabled" type="checkbox">
              <span class="questionnaire-switch-track">
                <span class="questionnaire-switch-thumb"></span>
              </span>
              <span>
                <strong>{{ questionnaireEnabled ? '已启用任务后问卷' : '已关闭任务后问卷' }}</strong>
                <small>
                  {{ questionnaireEnabled ? '测评链路：任务一 → 任务二 → 问卷 → 提交' : '测评链路：任务一 → 任务二 → 提交' }}
                </small>
              </span>
            </label>
          </div>

          <div class="col-lg-7 border-start-lg ps-lg-4">
            <div class="d-flex align-items-center justify-content-between mb-2">
              <h6 class="mb-0"><i class="bi bi-pie-chart-fill me-2 text-primary"></i>多模态综合得分自定义加权</h6>
              <span class="badge bg-primary-subtle text-primary">
                {{ questionnaireEnabled ? `行为 ${behaviorWeightPercent}% : 问卷 ${questionnaireWeightPercent}%` : '行为 100% (问卷已关闭)' }}
              </span>
            </div>
            <p class="text-muted small mb-3">
              设置出声思维言语行为频次与任务后问卷得分在综合维度报告中的数学融合比例：
            </p>

            <div class="weight-slider-container mb-3" :class="{ 'opacity-50 pointer-events-none': !questionnaireEnabled }">
              <div class="d-flex justify-content-between align-items-center mb-1">
                <label class="form-label small mb-0 fw-semibold">
                  <i class="bi bi-mic-fill me-1 text-primary"></i>过程性行为证据权重
                </label>
                <div class="input-group input-group-sm" style="width: 100px;">
                  <input
                    v-model.number="behaviorWeightPercent"
                    type="number"
                    min="0"
                    max="100"
                    class="form-control form-control-sm text-end"
                    :disabled="!questionnaireEnabled"
                  >
                  <span class="input-group-text">%</span>
                </div>
              </div>
              <input
                v-model.number="behaviorWeightPercent"
                type="range"
                min="0"
                max="100"
                step="5"
                class="form-range"
                :disabled="!questionnaireEnabled"
              >
              <div class="d-flex justify-content-between small text-muted">
                <span>出声思维行为: {{ behaviorWeightPercent }}%</span>
                <span>量表问卷: {{ questionnaireWeightPercent }}%</span>
              </div>
            </div>

            <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 pt-2 border-top">
              <small class="text-muted">上次保存：{{ formatUpdatedAt(protocolConfigUpdatedAt) }}</small>
              <button
                class="btn btn-primary btn-sm px-3"
                :disabled="protocolConfigSaving || !hasProtocolChanges"
                @click="saveProtocolConfig"
              >
                <span v-if="protocolConfigSaving" class="spinner-border spinner-border-sm me-1"></span>
                保存协议与加权配置
              </button>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="card border-0 shadow-sm mt-4">
      <div class="card-body p-4">
        <div class="d-flex flex-wrap justify-content-between align-items-start gap-2 mb-3">
          <div>
            <h5 class="mb-1"><i class="bi bi-volume-up-fill me-2 text-primary"></i>固定协议真人朗读</h5>
            <p class="text-muted small mb-0">新上传版本只影响之后创建的测评；进行中的测评继续使用创建时保存的资源快照。</p>
          </div>
          <button class="btn btn-outline-secondary btn-sm" :disabled="narrationLoading" @click="loadNarrationSlots">
            <span v-if="narrationLoading" class="spinner-border spinner-border-sm me-1" />
            <i v-else class="bi bi-arrow-clockwise me-1" />刷新
          </button>
        </div>

        <div v-if="narrationErrorMessage" class="alert alert-danger py-2">
          <i class="bi bi-exclamation-triangle-fill me-2" />{{ narrationErrorMessage }}
        </div>
        <div v-if="narrationLoading" class="py-4 text-center"><div class="spinner-border text-primary" /></div>
        <div v-else-if="!narrationSlots.length" class="alert alert-warning mb-0">固定协议尚未生成任何朗读槽位。</div>
        <div v-else class="d-grid gap-3">
          <article v-for="slot in narrationSlots" :key="slot.slot_key" class="border rounded-3 p-3">
            <div class="d-flex flex-wrap justify-content-between gap-3">
              <div class="flex-grow-1" style="min-width: 240px">
                <div class="d-flex flex-wrap align-items-center gap-2 mb-1">
                  <strong>{{ slot.label }}</strong>
                  <span class="badge bg-light text-secondary border">{{ narrationCategoryLabel(slot.category) }}</span>
                  <span v-if="slot.asset" class="badge bg-success-subtle text-success">版本 {{ slot.asset.version }}</span>
                  <span v-else class="badge bg-warning-subtle text-warning">未上传，将使用语音回退</span>
                </div>
                <p class="small text-muted mb-2">{{ slot.source_text }}</p>
                <div v-if="slot.asset" class="small text-muted">
                  {{ slot.asset.original_filename }} · {{ formatBytes(slot.asset.size_bytes) }} ·
                  {{ formatUpdatedAt(slot.asset.created_at) }}
                </div>
                <audio
                  v-if="slot.asset && narrationAudioUrls[slot.asset.id]"
                  class="w-100 mt-2"
                  controls
                  autoplay
                  :src="narrationAudioUrls[slot.asset.id]"
                />
              </div>
              <div class="d-flex flex-wrap align-content-start gap-2">
                <button
                  v-if="slot.asset"
                  class="btn btn-outline-primary btn-sm"
                  :disabled="narrationBusyKey === slot.slot_key"
                  @click="previewNarration(slot)"
                >
                  <i class="bi" :class="narrationAudioUrls[slot.asset.id] ? 'bi-stop-circle' : 'bi-play-circle'" />
                  {{ narrationAudioUrls[slot.asset.id] ? '关闭试听' : '试听' }}
                </button>
                <label class="btn btn-primary btn-sm mb-0" :class="{ disabled: narrationBusyKey === slot.slot_key }">
                  <span v-if="narrationBusyKey === slot.slot_key" class="spinner-border spinner-border-sm me-1" />
                  <i v-else class="bi bi-upload me-1" />{{ slot.asset ? '上传新版本' : '上传录音' }}
                  <input
                    class="visually-hidden"
                    type="file"
                    accept="audio/wav,audio/mpeg,audio/mp4,audio/webm,audio/ogg"
                    :disabled="narrationBusyKey === slot.slot_key"
                    @change="uploadNarration(slot, $event)"
                  >
                </label>
                <button
                  v-if="slot.asset"
                  class="btn btn-outline-danger btn-sm"
                  :disabled="narrationBusyKey === slot.slot_key"
                  @click="disableNarration(slot)"
                ><i class="bi bi-slash-circle me-1" />停用</button>
              </div>
            </div>
          </article>
        </div>
      </div>
    </section>
    </details>



    <details class="research-fold-card mb-4">
      <summary><span><i class="bi bi-stars"></i><strong>AI 提示词管理与审计</strong><small>版本化保存并追踪启用和回滚记录</small></span><i class="bi bi-chevron-down fold-chevron"></i></summary>
      <div class="fold-content">
    <div class="section-heading mb-3">
      <div>
        <h5 class="mb-1"><i class="bi bi-stars me-2 text-primary"></i>AI 提示词管理</h5>
        <p class="text-muted small mb-0">每次保存会创建独立版本，不会修改上方的标准测评协议。</p>
      </div>
    </div>
    <div v-if="templateErrorMessage" class="alert alert-danger">
      <i class="bi bi-exclamation-triangle-fill me-2"></i>{{ templateErrorMessage }}
    </div>
    <div v-if="templateSuccessMessage" class="alert alert-success">
      <i class="bi bi-check-circle-fill me-2"></i>{{ templateSuccessMessage }}
    </div>

    <div v-if="isLoading" class="card border-0 shadow-sm">
      <div class="card-body py-5 text-center"><div class="spinner-border text-primary" /></div>
    </div>

    <div v-else class="row g-4">
      <div class="col-lg-3">
        <div class="list-group shadow-sm">
          <button
            v-for="(definition, key) in definitions"
            :key="key"
            class="list-group-item list-group-item-action template-tab-item"
            :class="{ active: selectedKey === key }"
            @click="selectTemplate(key)"
          >
            <div class="d-flex align-items-center justify-content-between w-100">
              <span>{{ definition.label }}</span>
              <i v-if="selectedKey === key" class="bi bi-check2-circle text-white ms-2 fs-6"></i>
            </div>
          </button>
        </div>
        <div class="card border-0 shadow-sm mt-3">
          <div class="card-body">
            <div class="small fw-semibold mb-2">历史版本</div>
            <div v-for="item in history" :key="item.id" class="version-row" :class="{ 'is-viewed': viewedTemplateId === item.id }">
              <button class="version-view" @click="viewHistory(item)">{{ item.version }}</button>
              <span v-if="item.is_active" class="badge bg-success">启用中</span>
              <button v-else class="btn btn-sm btn-outline-primary" :disabled="activatingTemplateId === item.id" @click="activateHistory(item)">启用</button>
            </div>
          </div>
        </div>
      </div>

      <div class="col-lg-9">
        <div class="card border-0 shadow-sm">
          <div class="card-body p-4">
            <div class="template-card-heading d-flex flex-wrap justify-content-between align-items-end gap-3 mb-3">
              <div>
                <h5>{{ definitions[selectedKey].label }}</h5>
                <p class="text-muted small mb-0">{{ definitions[selectedKey].help }}</p>
              </div>
              <div class="template-save-area">
                <div>
                  <label class="form-label small">新版本号</label>
                  <input v-model.trim="version" class="form-control form-control-sm" maxlength="32">
                </div>
                <button
                  class="btn btn-primary"
                  :disabled="isSaving || !content || !version"
                  @click="saveTemplate"
                >
                  <span v-if="isSaving" class="spinner-border spinner-border-sm me-1"></span>
                  保存 AI 模板版本
                </button>
              </div>
            </div>
            <textarea v-model="content" class="form-control template-editor" rows="24" spellcheck="false" />
            <div class="small text-muted mt-2">
              当前启用：{{ activeTemplate?.version ?? '无' }}。JSON 模板会在保存时进行格式校验。
              点击左侧历史版本可查看完整内容；重新启用不会删除后续版本。
            </div>
          </div>
        </div>
      </div>
    </div>

    <section class="card border-0 shadow-sm mt-4 template-audit-card">
      <div class="card-body p-4">
        <div class="d-flex flex-wrap justify-content-between align-items-start gap-2 mb-3">
          <div><h5 class="mb-1"><i class="bi bi-shield-check me-2 text-primary"></i>提示词操作审计</h5><p class="text-muted small mb-0">记录当前模板的创建启用、历史版本启用和回滚操作。</p></div>
          <span class="badge bg-light text-dark">{{ definitions[selectedKey].label }}</span>
        </div>
        <div v-if="auditLoading" class="py-4 text-center"><span class="spinner-border spinner-border-sm text-primary"></span></div>
        <div v-else-if="visibleAudits.length" class="audit-list">
          <article v-for="item in visibleAudits" :key="item.id" class="audit-row">
            <span class="audit-icon"><i class="bi" :class="item.action === 'template.rollback' ? 'bi-arrow-counterclockwise' : 'bi-check2-circle'"></i></span>
            <div><strong>{{ auditActionLabel(item.action) }}</strong><div class="small text-muted">{{ item.from_version || '无启用版本' }} → {{ item.to_version || '未知版本' }}</div></div>
            <div class="audit-meta"><span>{{ item.actor_name || '系统' }}</span><time>{{ formatUpdatedAt(item.created_at) }}</time></div>
          </article>
        </div>
        <p v-else class="text-muted small mb-0 py-3">该模板尚无启用或回滚审计记录。</p>
      </div>
    </section>
      </div>
    </details>
  </div>

  <AppModal
    :open="Boolean(enlargedRocJob)"
    title="ROC 曲线详细视图"
    icon="bi-graph-up-arrow"
    max-width="980px"
    @close="enlargedRocJob = null"
  >
    <div v-if="enlargedRocJob" class="roc-detail-modal">
      <div class="roc-detail-heading">
        <div><strong>{{ evaluationModelName(enlargedRocJob) }}</strong><small>{{ enlargedRocJob.model_version }}</small></div>
        <span>Macro-AUC {{ metric(enlargedRocJob.summary.macro_auc_ovr) }}</span>
      </div>
      <svg class="roc-chart is-enlarged" viewBox="0 0 300 205" role="img" aria-label="放大的 ROC 曲线；横轴是假阳性率，纵轴是真阳性率">
        <line v-for="tick in [0,0.25,0.5,0.75,1]" :key="`modal-gx-${tick}`" :x1="38 + tick * 244" y1="12" :x2="38 + tick * 244" y2="176" class="roc-grid-line" />
        <line v-for="tick in [0,0.25,0.5,0.75,1]" :key="`modal-gy-${tick}`" x1="38" :y1="12 + tick * 164" x2="282" :y2="12 + tick * 164" class="roc-grid-line" />
        <line x1="38" y1="176" x2="282" y2="12" class="roc-chance-line" />
        <path v-for="definition in rocCurveDefinitions" :key="`modal-curve-${definition.key}`" :d="rocPath(enlargedRocJob.roc_curves?.[definition.key])" fill="none" :stroke="definition.color" :stroke-width="definition.width" stroke-linecap="round" stroke-linejoin="round" />
        <line x1="38" y1="176" x2="282" y2="176" class="roc-axis-line" /><line x1="38" y1="12" x2="38" y2="176" class="roc-axis-line" />
        <text x="160" y="199" class="roc-axis-label">假阳性率 FPR（越小越好）</text><text x="11" y="98" class="roc-axis-label" transform="rotate(-90 11 98)">真阳性率 TPR（越大越好）</text>
        <text x="34" y="190" class="roc-tick-label">0</text><text x="95" y="190" class="roc-tick-label">0.25</text><text x="156" y="190" class="roc-tick-label">0.50</text><text x="217" y="190" class="roc-tick-label">0.75</text><text x="278" y="190" class="roc-tick-label">1</text>
        <text x="24" y="179" class="roc-tick-label">0</text><text x="18" y="138" class="roc-tick-label">0.25</text><text x="18" y="97" class="roc-tick-label">0.50</text><text x="18" y="56" class="roc-tick-label">0.75</text><text x="24" y="16" class="roc-tick-label">1</text>
      </svg>
      <div class="roc-legend is-enlarged"><span v-for="definition in rocCurveDefinitions" :key="`modal-legend-${definition.key}`"><i :style="{ background: definition.color }"></i>{{ definition.label }} AUC <b>{{ metric(enlargedRocJob.roc_curves?.[definition.key]?.auc) }}</b></span></div>
      <div class="roc-detail-grid">
        <article><strong>横轴：假阳性率 FPR</strong><p>在“真实不属于当前类别”的测试样本中，被模型错误排到当前类别一侧的比例。计算式为 FP / (FP + TN)，越接近 0 越好。</p></article>
        <article><strong>纵轴：真阳性率 TPR</strong><p>在“真实属于当前类别”的测试样本中，被正确识别出来的比例，也就是 Recall。计算式为 TP / (TP + FN)，越接近 1 越好。</p></article>
        <article><strong>AUC 如何理解</strong><p>AUC 越接近 1，目标类样本的排序通常越靠前；0.5 接近随机排序。AUC 衡量排序区分能力，不等于准确率，也不保证输出概率可信。</p></article>
        <article><strong>本图实际数据</strong><p>{{ evaluationSplitLabel(enlargedRocJob) }}；共 {{ enlargedRocJob.roc_evaluation?.sample_count ?? enlargedRocJob.dataset.sample_count }} 条折外测试分数；{{ enlargedRocJob.roc_evaluation?.score_type === 'predict_proba' ? '测试折预测概率 predict_proba' : '测试折决策分数 decision_function（不是概率）' }}。</p></article>
      </div>
      <div class="evaluation-integrity" :class="enlargedRocJob.subject_leakage_risk ? 'is-warning' : 'is-valid'">
        <i class="bi" :class="enlargedRocJob.subject_leakage_risk ? 'bi-exclamation-triangle' : 'bi-shield-check'"></i>
        <span v-if="enlargedRocJob.subject_leakage_risk">该数据没有可靠被试 ID，曲线可能受到同一被试语言习惯跨折泄漏的影响，只能视为内部探索性结果。</span>
        <span v-else>训练折与测试折按被试隔离，且每条样本只贡献一次测试折分数；但仍属于同一数据集上的内部五折验证，不能替代独立外部测试。</span>
      </div>
    </div>
    <template #footer><button class="btn btn-primary ms-auto" @click="enlargedRocJob = null">关闭</button></template>
  </AppModal>
</template>

<style scoped>
.template-page { max-width: 1200px; margin: 0 auto; }
.research-fold-card { border: 1px solid var(--color-border); border-radius: var(--radius-lg); background: var(--color-surface); box-shadow: var(--shadow-sm); overflow: hidden; }
.research-fold-card > summary { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: 1rem 1.15rem; cursor: pointer; list-style: none; background: linear-gradient(110deg, var(--color-primary-soft), var(--color-surface) 56%); }
.research-fold-card > summary::-webkit-details-marker { display: none; }
.research-fold-card > summary > span { display: grid; grid-template-columns: auto 1fr; align-items: center; gap: .15rem .7rem; }
.research-fold-card > summary > span > i { grid-row: 1 / span 2; color: var(--color-primary); font-size: 1.15rem; }
.research-fold-card > summary small { color: var(--color-text-muted); }
.research-fold-card .fold-chevron { transition: transform .18s ease; }
.research-fold-card[open] .fold-chevron { transform: rotate(180deg); }
.fold-content { padding: 1rem; border-top: 1px solid var(--color-border); }
.research-fold-card > section { margin: 0 !important; border: 0 !important; box-shadow: none !important; }
.training-create-entry { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: .9rem 1rem; border: 1px solid var(--color-border); border-radius: 14px; background: var(--color-surface-subtle); }
.training-create-entry strong,.training-create-entry small { display: block; }
.training-create-entry small { margin-top: .15rem; color: var(--color-text-muted); }
.training-builder { display: grid; gap: .75rem; padding: .9rem; border: 1px solid color-mix(in srgb,var(--color-primary) 28%,var(--color-border)); border-radius: 16px; background: color-mix(in srgb,var(--color-primary-soft) 38%,var(--color-surface)); }
.training-builder-section { display: flex; align-items: flex-start; gap: .75rem; padding: .9rem; border: 1px solid var(--color-border); border-radius: 13px; background: var(--color-surface); }
.training-builder-step { display: grid; place-items: center; flex: 0 0 28px; width: 28px; height: 28px; border-radius: 9px; color: #fff; background: var(--color-primary); font-size: .78rem; font-weight: 800; }
.training-choice-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: .65rem; }
.training-builder-section:first-child .training-choice-grid { grid-template-columns: repeat(3,minmax(0,1fr)); }
.training-choice { display: flex; align-items: flex-start; gap: .6rem; min-height: 72px; padding: .75rem; border: 1px solid var(--color-border); border-radius: 11px; cursor: pointer; background: var(--color-surface-subtle); }
.training-choice.active { border-color: var(--color-primary); box-shadow: 0 0 0 2px color-mix(in srgb,var(--color-primary) 14%,transparent); background: var(--color-primary-soft); }
.training-choice input { margin-top: .18rem; accent-color: var(--color-primary); }
.training-choice b,.training-choice small { display: block; }
.training-choice small { margin-top: .15rem; color: var(--color-text-muted); font-size: .74rem; }
.custom-experiment-panel { padding: .8rem; border: 1px solid var(--color-border); border-radius: 13px; background: var(--color-surface-subtle); }
.custom-experiment-heading { display: flex; align-items: center; justify-content: space-between; gap: .75rem; margin-bottom: .7rem; }
.custom-experiment-heading b,.custom-experiment-heading small { display: block; }
.custom-experiment-heading small { margin-top: .15rem; color: var(--color-text-muted); font-size: .75rem; }
.selection-count { flex: 0 0 auto; padding: .25rem .6rem; border-radius: 999px; color: var(--color-primary); background: var(--color-primary-soft); font-size: .74rem; font-weight: 800; }
.selection-count.is-invalid { color: var(--color-danger); background: color-mix(in srgb,var(--color-danger) 12%,transparent); }
.custom-experiment-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: .55rem; }
.custom-experiment-option { display: grid; grid-template-columns: auto 1fr auto; align-items: start; gap: .55rem; min-width: 0; padding: .7rem .75rem; border: 1px solid var(--color-border); border-radius: 11px; cursor: pointer; background: var(--color-surface); }
.custom-experiment-option.active { border-color: color-mix(in srgb,var(--color-primary) 72%,var(--color-border)); background: color-mix(in srgb,var(--color-primary-soft) 55%,var(--color-surface)); box-shadow: inset 3px 0 0 var(--color-primary); }
.custom-experiment-option input { margin-top: .2rem; accent-color: var(--color-primary); }
.custom-experiment-option span { min-width: 0; }
.custom-experiment-option b,.custom-experiment-option small { display: block; }
.custom-experiment-option b { overflow-wrap: anywhere; font-size: .79rem; }
.custom-experiment-option small { margin-top: .15rem; color: var(--color-text-muted); font-size: .7rem; line-height: 1.4; }
.custom-experiment-option > i { color: var(--color-text-muted); }
.custom-experiment-option.active > i { color: var(--color-primary); }
.custom-selection-warning { display: flex; align-items: center; gap: .4rem; margin: .65rem 0 0; color: var(--color-danger); font-size: .75rem; }
.all-experiment-summary { display: flex; align-items: flex-start; gap: .6rem; padding: .7rem .8rem; border-radius: 11px; color: var(--color-text-secondary); background: var(--color-primary-soft); }
.all-experiment-summary > i { color: var(--color-primary); font-size: 1rem; }
.all-experiment-summary b,.all-experiment-summary small { display: block; }
.all-experiment-summary small { margin-top: .12rem; color: var(--color-text-muted); font-size: .72rem; line-height: 1.45; }
.dataset-source-note { display: flex; align-items: flex-start; gap: .55rem; padding: .7rem .8rem; border-radius: 10px; color: var(--color-text-secondary); background: var(--color-surface-subtle); font-size: .8rem; }
.dataset-source-note i { color: var(--color-primary); }
.uploaded-dataset-panel { display: grid; gap: .7rem; }
.dataset-template-entry { display: flex; align-items: center; justify-content: space-between; gap: .75rem; padding: .7rem .8rem; border: 1px dashed color-mix(in srgb,var(--color-primary) 45%,var(--color-border)); border-radius: 11px; background: color-mix(in srgb,var(--color-primary-soft) 45%,var(--color-surface)); }
.dataset-template-entry b,.dataset-template-entry small { display: block; }
.dataset-template-entry small { margin-top: .1rem; color: var(--color-text-muted); font-size: .74rem; }
.dataset-template-entry .btn { white-space: nowrap; }
.uploaded-dataset-fields { display: grid; grid-template-columns: minmax(180px,.8fr) minmax(250px,1.2fr); gap: .7rem; }
.dataset-divider { display: flex; align-items: center; gap: .6rem; color: var(--color-text-muted); font-size: .72rem; }
.dataset-divider::before,.dataset-divider::after { content: ''; flex: 1; height: 1px; background: var(--color-border); }
.training-create-row { display: grid; grid-template-columns: minmax(190px,1fr) minmax(230px,1fr) auto; align-items: end; gap: .75rem; margin-bottom: .75rem; }
.training-create-actions { display: flex; flex-wrap: wrap; gap: .5rem; }
.comparison-toolbar { display: flex; align-items: center; gap: .75rem; padding: .7rem .8rem; border: 1px solid var(--color-border); border-radius: 12px; background: color-mix(in srgb,var(--color-surface) 92%,transparent); }
.comparison-toolbar-copy { min-width: 220px; flex: 1; }
.comparison-toolbar-copy strong,.comparison-toolbar-copy small { display: block; }
.comparison-toolbar-copy strong { font-size: .82rem; }
.comparison-toolbar-copy small { margin-top: .12rem; color: var(--color-text-muted); font-size: .7rem; }
.comparison-toolbar-copy small .bi-check-circle-fill { color: var(--color-success); }
.comparison-group-select { display: flex; align-items: center; gap: .45rem; margin: 0; }
.comparison-group-select > span { flex: 0 0 auto; color: var(--color-text-muted); font-size: .72rem; }
.comparison-group-select .form-select { width: min(260px,28vw); }
.comparison-group-label { max-width: 220px; overflow: hidden; padding: .28rem .55rem; border-radius: 999px; color: var(--color-text-secondary); background: var(--color-surface-subtle); font-size: .7rem; text-overflow: ellipsis; white-space: nowrap; }
.model-comparison-grid { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: .75rem; }
.parameter-section-heading { display:flex; justify-content:space-between; gap:1rem; margin-bottom:.65rem; }
.parameter-section-heading small { display:block; color:var(--color-text-muted); margin-top:.2rem; }
.parameter-model-card { border:1px solid var(--color-border); border-radius:14px; background:color-mix(in srgb,var(--color-surface) 88%,transparent); margin-top:.65rem; overflow:hidden; }
.parameter-model-card > summary { display:flex; align-items:center; justify-content:space-between; gap:1rem; padding:.8rem 1rem; cursor:pointer; list-style:none; }
.parameter-model-card > summary::-webkit-details-marker { display:none; }
.parameter-model-card > summary span { display:flex; flex-direction:column; gap:.15rem; }
.parameter-model-card > summary small { color:var(--color-text-muted); }
.parameter-model-card[open] > summary { border-bottom:1px solid var(--color-border); }
.parameter-model-card[open] > summary > i { transform:rotate(180deg); }
.parameter-model-body { padding:1rem; }
.parameter-toggle { display:flex; align-items:flex-start; gap:.65rem; padding:.75rem; border-radius:12px; background:color-mix(in srgb,var(--color-primary) 8%,transparent); margin-bottom:1rem; }
.parameter-toggle span { display:flex; flex-direction:column; }
.parameter-toggle small { color:var(--color-text-muted); }
.parameter-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:1rem; margin-bottom:.85rem; }
.parameter-grid.is-disabled { opacity:.66; }
.parameter-grid label > small { display:block; color:var(--color-text-muted); line-height:1.45; margin-top:.35rem; }
.parameter-grid code { font-size:.72rem; color:var(--color-primary); }
.model-parameter-line { display:flex; align-items:center; gap:.45rem; margin-top:.6rem; min-width:0; }
.model-parameter-line > span,.parameter-source-badge { flex:0 0 auto; border-radius:999px; padding:.18rem .48rem; background:color-mix(in srgb,var(--color-text-muted) 12%,transparent); color:var(--color-text-muted); font-size:.7rem; font-weight:700; }
.model-parameter-line > span.is-manual,.parameter-source-badge.is-manual { background:color-mix(in srgb,var(--color-warning) 17%,transparent); color:var(--color-warning); }
.model-parameter-line small,.parameter-result-summary { display:block; min-width:0; color:var(--color-text-muted); overflow-wrap:anywhere; word-break:break-word; }
.model-parameter-line small { line-height:1.45; }
.parameter-result-summary { max-width:none; margin-top:.24rem; font-size:.72rem; line-height:1.45; }
.model-comparison-card { min-width: 0; padding: .9rem; border: 1px solid var(--color-border); border-radius: 14px; background: color-mix(in srgb,var(--color-surface) 92%,transparent); }
.model-comparison-card.is-best { border-color: color-mix(in srgb,var(--color-success) 72%,var(--color-border)); box-shadow: inset 0 2px 0 color-mix(in srgb,var(--color-success) 78%,transparent),0 0 0 1px color-mix(in srgb,var(--color-success) 12%,transparent); }
.model-comparison-heading { display: flex; align-items: flex-start; gap: .6rem; min-height: 44px; }
.model-comparison-heading > span:first-child { display: grid; place-items: center; width: 32px; height: 32px; flex: 0 0 32px; border-radius: 10px; color: var(--color-primary); background: var(--color-primary-soft); }
.model-comparison-heading > div { min-width: 0; flex: 1; }
.model-comparison-heading small,.model-comparison-heading strong { display: block; }
.model-comparison-heading strong { font-size: .86rem; line-height:1.35; overflow-wrap:anywhere; }
.model-comparison-heading small { color: var(--color-text-muted); }
.best-model-badge { display: inline-flex !important; align-items: center; gap: .2rem; flex: 0 0 auto; padding: .24rem .45rem; border-radius: 999px; color: var(--color-success); background: var(--color-success-soft); font-size: .66rem; font-weight: 800; white-space: nowrap; }
.best-risk-summary { display:flex; align-items:center; gap:.5rem; margin:-.25rem 0 .7rem; padding:.52rem .6rem; border:1px solid var(--color-border); border-radius:10px; background:var(--color-surface-subtle); }
.best-risk-summary > i { flex:0 0 auto; }
.best-risk-summary span,.best-risk-summary b,.best-risk-summary small { display:block; }
.best-risk-summary b { font-size:.7rem; }
.best-risk-summary small { margin-top:.08rem; color:var(--color-text-muted); font-size:.64rem; }
.best-risk-summary.is-low { color:var(--color-success); border-color:color-mix(in srgb,var(--color-success) 32%,var(--color-border)); background:var(--color-success-soft); }
.best-risk-summary.is-medium { color:var(--color-warning); border-color:color-mix(in srgb,var(--color-warning) 36%,var(--color-border)); background:var(--color-warning-soft); }
.best-risk-summary.is-high { color:var(--color-danger); border-color:color-mix(in srgb,var(--color-danger) 40%,var(--color-border)); background:color-mix(in srgb,var(--color-danger) 10%,var(--color-surface)); }
.best-risk-summary.is-unknown { color:var(--color-text-muted); }
.model-comparison-metrics { display: grid; grid-template-columns: repeat(3,1fr); gap: .4rem; margin: .85rem 0; }
.model-comparison-metrics span,.training-summary-metrics span { min-width: 0; padding: .5rem; border-radius: 10px; background: var(--color-surface-subtle); text-align: center; }
.model-comparison-metrics small,.model-comparison-metrics strong,.training-summary-metrics small,.training-summary-metrics strong { display: block; }
.model-comparison-metrics small,.training-summary-metrics small { color: var(--color-text-muted); font-size: .68rem; }
.model-comparison-footer { display: flex; align-items: center; justify-content: space-between; gap: .4rem; }
.model-comparison-empty { margin-top: .8rem; color: var(--color-text-muted); font-size: .8rem; }
.model-evaluation-panel { padding: 1rem; border: 1px solid var(--color-border); border-radius: 16px; background: color-mix(in srgb,var(--color-surface) 94%,transparent); }
.model-evaluation-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; margin-bottom: .9rem; }
.model-evaluation-heading strong,.model-evaluation-heading small { display: block; }
.model-evaluation-heading small { margin-top: .15rem; color: var(--color-text-muted); font-size: .76rem; }
.metric-primary-badge { display: inline-flex; align-items: center; flex: 0 0 auto; padding: .35rem .65rem; border-radius: 999px; color: var(--color-primary); background: var(--color-primary-soft); font-size: .72rem; font-weight: 700; }
.metric-chart { display: grid; gap: .7rem; }
.metric-chart-row { display: grid; grid-template-columns: minmax(180px,.72fr) minmax(300px,1.8fr); gap: 1rem; align-items: center; padding: .8rem; border: 1px solid var(--color-border); border-radius: 12px; background: var(--color-surface); }
.metric-chart-label { min-width: 0; }
.metric-chart-label strong,.metric-chart-label small { display: block; overflow-wrap:anywhere; }
.metric-chart-label strong { font-size: .84rem; }
.metric-chart-label small { margin-top: .16rem; color: var(--color-text-muted); font-size: .7rem; }
.metric-chart-bars { display: grid; gap: .42rem; }
.metric-bar-row { display: grid; grid-template-columns: 82px minmax(120px,1fr) 42px; align-items: center; gap: .55rem; font-size: .72rem; }
.metric-bar-row > span { color: var(--color-text-secondary); font-weight: 600; }
.metric-bar-row > b { font-variant-numeric: tabular-nums; text-align: right; }
.metric-bar-track { position: relative; height: 12px; overflow: hidden; border-radius: 999px; background: var(--color-surface-subtle); }
.metric-bar-track small { position: absolute; inset: 0 .4rem; overflow: hidden; color: var(--color-text-muted); font-size: .58rem; line-height: 12px; text-overflow: ellipsis; white-space: nowrap; }
.metric-bar-fill { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg,#635bff,#8f7cff); }
.metric-bar-fill.is-weighted_f1 { background: linear-gradient(90deg,#0ea5e9,#22d3ee); }
.metric-bar-fill.is-macro_auc_ovr { background: linear-gradient(90deg,#f59e0b,#facc15); }
.class-f1-comparison { margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--color-border); }
.class-f1-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; margin-bottom: .75rem; }
.class-f1-heading strong,.class-f1-heading small { display: block; }
.class-f1-heading small { margin-top: .15rem; color: var(--color-text-muted); font-size: .72rem; }
.class-f1-legend { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: .35rem .7rem; }
.class-f1-legend span { display: inline-flex; align-items: center; gap: .28rem; color: var(--color-text-secondary); font-size: .63rem; }
.class-f1-legend i { width: 8px; height: 8px; border-radius: 50%; background: #64748b; }
.class-f1-legend .is-monitoring i { background: #6366f1; }
.class-f1-legend .is-regulation i { background: #06b6d4; }
.class-f1-legend .is-evaluation i { background: #f59e0b; }
.class-f1-chart { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: .7rem; }
.class-f1-model-row { min-width: 0; padding: .8rem; border: 1px solid var(--color-border); border-radius: 12px; background: var(--color-surface); }
.class-f1-model-row > .metric-chart-label { margin-bottom: .65rem; }
.class-f1-model-bars { display: grid; gap: .45rem; }
.class-f1-bar-row { display: grid; grid-template-columns: 122px minmax(80px,1fr) 40px; align-items: center; gap: .5rem; }
.class-f1-bar-row > span { min-width: 0; }
.class-f1-bar-row > span b,.class-f1-bar-row > span small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.class-f1-bar-row > span b { font-size: .68rem; }
.class-f1-bar-row > span small { color: var(--color-text-muted); font-size: .56rem; }
.class-f1-bar-row > strong { font-size: .7rem; font-variant-numeric: tabular-nums; text-align: right; }
.metric-bar-fill.is-non-metacognitive { background: linear-gradient(90deg,#64748b,#94a3b8); }
.metric-bar-fill.is-monitoring { background: linear-gradient(90deg,#4f46e5,#818cf8); }
.metric-bar-fill.is-regulation { background: linear-gradient(90deg,#0891b2,#22d3ee); }
.metric-bar-fill.is-evaluation { background: linear-gradient(90deg,#d97706,#fbbf24); }
.class-f1-note { margin: .7rem 0 0; color: var(--color-text-muted); font-size: .7rem; line-height: 1.55; }
.probability-evaluation-section { margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--color-border); }
.roc-method-note { display: grid; grid-template-columns: 38px minmax(0,1fr); gap: .7rem; margin-bottom: .8rem; padding: .8rem; border: 1px solid color-mix(in srgb,var(--color-primary) 28%,var(--color-border)); border-radius: 12px; background: color-mix(in srgb,var(--color-primary-soft) 55%,var(--color-surface)); }
.roc-method-note > i { display: grid; place-items: center; width: 38px; height: 38px; border-radius: 11px; color: var(--color-primary); background: var(--color-surface); font-size: 1rem; }
.roc-method-note strong { font-size: .78rem; }
.roc-method-note p { margin: .25rem 0 0; color: var(--color-text-secondary); font-size: .68rem; line-height: 1.6; }
.visual-section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; margin-bottom: .75rem; }
.visual-section-heading strong,.visual-section-heading small { display: block; }
.visual-section-heading small { margin-top: .15rem; color: var(--color-text-muted); font-size: .72rem; }
.visual-section-heading > span { flex: 0 0 auto; padding: .3rem .55rem; border-radius: 999px; color: var(--color-primary); background: var(--color-primary-soft); font-size: .66rem; font-weight: 700; }
.probability-visual-layout { display: grid; grid-template-columns: minmax(0,2fr) minmax(245px,.72fr); gap: .75rem; align-items: start; }
.roc-comparison-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: .7rem; }
.roc-model-card { min-width: 0; padding: .75rem; border: 1px solid var(--color-border); border-radius: 12px; background: var(--color-surface); }
.roc-card-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: .5rem; margin-bottom: .4rem; }
.roc-card-heading strong,.roc-card-heading small { display: block; }
.roc-card-heading strong { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: .75rem; }
.roc-card-heading small { color: var(--color-text-muted); font-size: .62rem; }
.roc-card-heading > b { flex: 0 0 auto; color: var(--color-primary); font-size: .68rem; }
.roc-chart-button { position: relative; display: block; width: 100%; padding: 0; overflow: hidden; border: 1px solid transparent; border-radius: 9px; background: transparent; color: inherit; text-align: inherit; cursor: zoom-in; }
.roc-chart-button:hover,.roc-chart-button:focus-visible { border-color: color-mix(in srgb,var(--color-primary) 48%,var(--color-border)); box-shadow: 0 0 0 3px color-mix(in srgb,var(--color-primary) 12%,transparent); outline: none; }
.roc-expand-hint { position: absolute; right: .45rem; bottom: .4rem; display: inline-flex; align-items: center; gap: .25rem; padding: .22rem .4rem; border-radius: 999px; color: var(--color-text); background: color-mix(in srgb,var(--color-surface) 90%,transparent); box-shadow: var(--shadow-sm); font-size: .58rem; font-weight: 700; opacity: .78; }
.roc-chart { display: block; width: 100%; max-height: 220px; border-radius: 8px; background: color-mix(in srgb,var(--color-surface-subtle) 62%,transparent); }
.roc-grid-line { stroke: var(--color-border); stroke-width: .7; }
.roc-chance-line { stroke: var(--color-text-muted); stroke-width: 1; stroke-dasharray: 5 4; opacity: .62; }
.roc-axis-line { stroke: var(--color-text-secondary); stroke-width: 1.1; }
.roc-axis-label { fill: var(--color-text-muted); font-size: 8px; text-anchor: middle; }
.roc-tick-label { fill: var(--color-text-muted); font-size: 7px; }
.roc-legend { display: flex; flex-wrap: wrap; gap: .3rem .55rem; margin-top: .45rem; }
.roc-legend span { display: inline-flex; align-items: center; gap: .2rem; color: var(--color-text-secondary); font-size: .58rem; }
.roc-legend i { width: 11px; height: 3px; border-radius: 999px; }
.roc-legend b { font-variant-numeric: tabular-nums; }
.roc-detail-modal { display: grid; gap: .85rem; }
.roc-detail-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; }
.roc-detail-heading strong,.roc-detail-heading small { display: block; }
.roc-detail-heading small { color: var(--color-text-muted); }
.roc-detail-heading > span { padding: .35rem .6rem; border-radius: 999px; color: var(--color-primary); background: var(--color-primary-soft); font-weight: 800; }
.roc-chart.is-enlarged { width: min(100%,760px); max-height: 510px; margin: 0 auto; border: 1px solid var(--color-border); }
.roc-legend.is-enlarged { justify-content: center; gap: .55rem 1rem; }
.roc-legend.is-enlarged span { font-size: .72rem; }
.roc-detail-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: .65rem; }
.roc-detail-grid article { padding: .75rem; border: 1px solid var(--color-border); border-radius: 11px; background: var(--color-surface-subtle); }
.roc-detail-grid strong { font-size: .76rem; }
.roc-detail-grid p { margin: .3rem 0 0; color: var(--color-text-secondary); font-size: .7rem; line-height: 1.6; }
.roc-empty-state { display: grid; place-items: center; align-content: center; gap: .5rem; min-height: 190px; padding: 1rem; border-radius: 8px; color: var(--color-text-muted); background: var(--color-surface-subtle); text-align: center; font-size: .7rem; line-height: 1.5; }
.roc-empty-state i { color: var(--color-primary); font-size: 1.35rem; }
.cross-entropy-panel { position: sticky; top: 78px; padding: .85rem; border: 1px solid var(--color-border); border-radius: 12px; background: var(--color-surface); }
.cross-entropy-heading { display: grid; grid-template-columns: 34px minmax(0,1fr); gap: .6rem; align-items: start; }
.cross-entropy-heading > span { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 10px; color: #dc2626; background: rgba(239,68,68,.12); }
.cross-entropy-heading strong,.cross-entropy-heading small { display: block; }
.cross-entropy-heading strong { font-size: .8rem; }
.cross-entropy-heading small { margin-top: .12rem; color: var(--color-text-muted); font-size: .64rem; line-height: 1.45; }
.cross-entropy-bars { display: grid; gap: .75rem; margin-top: 1rem; }
.cross-entropy-bars article > div:first-child { display: flex; align-items: center; justify-content: space-between; gap: .5rem; }
.cross-entropy-bars strong { font-size: .68rem; line-height:1.4; overflow-wrap:anywhere; }
.cross-entropy-bars b { color: #dc2626; font-size: .72rem; font-variant-numeric: tabular-nums; }
.loss-bar-track { height: 8px; margin-top: .3rem; overflow: hidden; border-radius: 999px; background: var(--color-surface-subtle); }
.loss-bar-track i { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg,#fbbf24,#f97316,#ef4444); }
.cross-entropy-empty { margin: .85rem 0 0; padding: .75rem; border-radius: 9px; color: var(--color-text-muted); background: var(--color-surface-subtle); font-size: .68rem; }
.loss-model-note { margin-top: .9rem; padding-top: .75rem; border-top: 1px solid var(--color-border); }
.loss-model-note strong { font-size: .68rem; }
.loss-model-note p { margin: .25rem 0 0; color: var(--color-text-muted); font-size: .64rem; line-height: 1.5; }
.training-summary-metrics { display: grid; grid-template-columns: repeat(5,minmax(0,1fr)); gap: .5rem; }
.training-table-wrap { border: 1px solid var(--color-border); border-radius: 12px; }
.training-version-group + .training-version-group .training-group-row > td { border-top: 6px solid color-mix(in srgb,var(--color-surface-subtle) 78%,var(--color-border)); }
.training-group-row > td { padding: 0 !important; background: color-mix(in srgb,var(--color-primary-soft) 24%,var(--color-surface)); }
.training-group-toggle { display: grid; grid-template-columns: 32px minmax(220px,1fr) auto auto minmax(125px,auto); align-items: center; gap: .75rem; width: 100%; padding: .8rem .9rem; border: 0; color: var(--color-text); background: transparent; text-align: left; }
.training-group-toggle:hover { background: color-mix(in srgb,var(--color-primary-soft) 48%,transparent); }
.training-group-toggle:focus-visible { position: relative; z-index: 1; outline: 2px solid var(--color-primary); outline-offset: -2px; }
.training-group-chevron { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 9px; color: var(--color-primary); background: var(--color-primary-soft); }
.training-group-copy { min-width: 0; }
.training-group-copy > small,.training-group-copy > strong,.training-group-copy > span { display: block; }
.training-group-copy > small { color: var(--color-primary); font-size: .64rem; font-weight: 800; letter-spacing: .04em; }
.training-group-copy > strong { overflow: hidden; margin-top: .05rem; font-size: .92rem; text-overflow: ellipsis; white-space: nowrap; }
.training-group-copy > span { overflow: hidden; margin-top: .12rem; color: var(--color-text-muted); font-size: .7rem; text-overflow: ellipsis; white-space: nowrap; }
.training-group-progress,.training-group-active { display: inline-flex; align-items: center; gap: .25rem; padding: .28rem .52rem; border-radius: 999px; font-size: .68rem; font-weight: 700; white-space: nowrap; }
.training-group-progress { color: var(--color-text-secondary); background: var(--color-surface-subtle); }
.training-group-active { color: var(--color-success); background: var(--color-success-soft); }
.training-group-toggle time { color: var(--color-text-muted); font-size: .7rem; font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }
.training-job-row { scroll-margin-top:96px; }
.training-job-row > td { background: color-mix(in srgb,var(--color-surface) 96%,transparent); transition:background-color 180ms cubic-bezier(.23,1,.32,1); }
.training-job-row.is-expanded > td { background:color-mix(in srgb,var(--color-primary-soft) 44%,var(--color-surface)); }
.training-job-row > td:first-child { padding-left: 1.35rem; }
.training-status { display: inline-flex; padding: .25rem .55rem; border-radius: 999px; font-size: .75rem; font-weight: 700; background: var(--color-surface-subtle); }
.training-status.is-running { color: var(--color-primary); background: var(--color-primary-soft); }
.training-status.is-completed { color: var(--color-success); background: rgba(25,135,84,.12); }
.training-status.is-failed { color: var(--color-danger); background: rgba(220,53,69,.12); }
.training-status.is-cancelled { color: var(--color-text-muted); background: var(--color-surface-subtle); }
.training-live-progress { width: min(180px,100%); padding: .42rem .48rem; border: 1px solid color-mix(in srgb,var(--color-primary) 18%,var(--color-border)); border-radius: 9px; background: color-mix(in srgb,var(--color-primary-soft) 35%,var(--color-surface)); transition: transform 180ms cubic-bezier(.23,1,.32,1),border-color 180ms ease,box-shadow 180ms ease; }
.training-progress-heading { display: flex; align-items: center; justify-content: space-between; gap: .5rem; margin-bottom: .3rem; color: var(--color-text-muted); font-size: .64rem; }
.training-progress-heading strong { color: var(--color-primary); font-size: .72rem; font-variant-numeric: tabular-nums; }
.training-live-progress > small { display: block; margin-top: .28rem; color: var(--color-text-muted); font-size: .62rem; line-height: 1.25; }
.training-stream-progress { position: relative; height: 7px; overflow: hidden; border-radius: 999px; background: color-mix(in srgb,var(--color-primary) 10%,var(--color-surface-subtle)); box-shadow: inset 0 0 0 1px color-mix(in srgb,var(--color-primary) 12%,transparent); }
.training-stream-progress > span { position: absolute; inset: 0; transform-origin: left center; border-radius: inherit; background: linear-gradient(90deg,#5753c9 0%,#7668ef 38%,#31c5dc 68%,#a79cff 100%); box-shadow: 0 0 12px color-mix(in srgb,var(--color-primary) 55%,transparent); transition: transform 220ms cubic-bezier(.23,1,.32,1); }
.training-stream-progress > span::after { content: ''; position: absolute; inset: 0; opacity: .72; background: linear-gradient(105deg,transparent 0 30%,rgba(255,255,255,.72) 45%,transparent 60% 100%); transform: translateX(-100%); animation: training-charge 1.15s linear infinite; }
@keyframes training-charge { to { transform: translateX(100%); } }
@media (hover:hover) and (pointer:fine) { .training-live-progress:hover { transform: translateY(-2px); border-color: color-mix(in srgb,var(--color-primary) 38%,var(--color-border)); box-shadow: 0 8px 18px color-mix(in srgb,var(--color-primary) 10%,transparent); } }
.active-model-banner { display: flex; align-items: center; gap: .8rem; padding: .85rem 1rem; border: 1px solid var(--color-success); border-radius: 12px; color: var(--color-success); background: var(--color-success-soft); }
.active-model-icon { display: grid; place-items: center; flex: 0 0 42px; width: 42px; height: 42px; border-radius: 12px; background: var(--color-surface); font-size: 1.1rem; }
.active-model-banner div { display: flex; flex-wrap: wrap; align-items: baseline; gap: .25rem .7rem; }
.active-model-banner div span { flex-basis: 100%; color: var(--color-text-secondary); font-size: .78rem; }
.training-version-button { display: inline-flex; align-items: center; gap: .35rem; padding: 0; border: 0; color: inherit; background: transparent; }
.training-actions { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: .4rem; }
.training-detail-row > td { padding: 0 !important; background: var(--color-surface-subtle); }
.training-detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 1rem; padding: 1rem; }
.training-detail-grid section { min-width: 0; padding: .85rem; border: 1px solid var(--color-border); border-radius: 12px; background: var(--color-surface); }
.training-detail-grid dl { display: grid; gap: .4rem; margin: 0; }
.training-detail-grid dl div { display: grid; grid-template-columns: 92px minmax(0,1fr); gap: .65rem; }
.training-detail-grid dt { color: var(--color-text-muted); font-weight: 500; }
.training-detail-grid dd { margin: 0; }
.fingerprint { overflow-wrap: anywhere; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .72rem; }
.fold-metrics { display: grid; grid-template-columns: repeat(5, minmax(70px,1fr)); gap: .45rem; }
.fold-metrics span { display: grid; gap: .15rem; padding: .55rem; border-radius: 9px; text-align: center; background: var(--color-surface-subtle); }
.fold-metrics small { color: var(--color-text-muted); }
.evaluation-data-section { grid-column: 1 / -1; }
.evaluation-facts { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: .55rem; }
.evaluation-facts span { display: grid; gap: .15rem; padding: .65rem; border-radius: 9px; background: var(--color-surface-subtle); }
.evaluation-facts small { color: var(--color-text-muted); font-size: .66rem; }
.evaluation-facts strong { font-size: .78rem; }
.evaluation-distribution,.evaluation-boundary { margin: .65rem 0 0; color: var(--color-text-secondary); font-size: .7rem; line-height: 1.6; }
.evaluation-integrity { display: flex; align-items: flex-start; gap: .5rem; margin-top: .65rem; padding: .65rem .75rem; border-radius: 9px; font-size: .7rem; line-height: 1.55; }
.evaluation-integrity.is-valid { color: var(--color-success); background: var(--color-success-soft); }
.evaluation-integrity.is-warning { color: var(--color-warning); background: var(--color-warning-soft); }
.fold-data-table { min-width: 760px; font-size: .7rem; }
.fold-data-table th { color: var(--color-text-muted); white-space: nowrap; }
.model-performance-card {
  margin-bottom: 2rem !important;
  border: 1px solid color-mix(in srgb,var(--color-primary) 28%,var(--color-border-strong));
  background: linear-gradient(155deg,color-mix(in srgb,var(--color-primary-soft) 18%,var(--color-surface)),var(--color-surface) 32%);
  box-shadow: 0 18px 44px color-mix(in srgb,var(--color-primary) 9%,transparent),0 1px 0 rgba(255,255,255,.08) inset;
}
.model-performance-card > summary {
  min-height: 76px;
  padding: 1rem 1.15rem;
  border-bottom: 1px solid color-mix(in srgb,var(--color-primary) 19%,var(--color-border));
  background: linear-gradient(115deg,color-mix(in srgb,var(--color-primary-soft) 86%,var(--color-surface)),color-mix(in srgb,#06b6d4 12%,var(--color-surface)));
}
.model-performance-card > summary strong { font-size: 1rem; }
.model-performance-card > summary small { margin-top: .18rem; font-size: .78rem; line-height: 1.45; }
.model-performance-card > .fold-content { padding: 1.15rem; background: color-mix(in srgb,var(--color-surface-subtle) 40%,transparent); }
.performance-evidence-panel { margin: 1rem 0; padding: 1rem; border: 1px solid var(--color-border); border-radius: var(--radius-lg); background: var(--color-surface); }
.performance-evidence-grid { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: .75rem; }
.performance-evidence-grid article { min-width: 0; padding: .85rem; border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface-subtle); }
.performance-evidence-grid article.is-verified { border-color: color-mix(in srgb,var(--color-success) 55%,var(--color-border)); background: color-mix(in srgb,var(--color-success) 8%,var(--color-surface)); }
.performance-evidence-grid small { color: var(--color-text-muted); }
.performance-evidence-grid strong { display: block; margin: .25rem 0; font-size: 1.05rem; color: var(--color-text); }
.performance-evidence-grid p,.weighted-metric-note p,.performance-error-cases > p { margin: 0; color: var(--color-text-muted); font-size: .78rem; line-height: 1.55; }
.weighted-metric-note { display: flex; gap: .65rem; margin-top: .8rem; padding: .75rem .85rem; border-radius: var(--radius-md); background: color-mix(in srgb,var(--color-primary) 8%,var(--color-surface-subtle)); color: var(--color-primary); }
.performance-error-cases { margin-top: .8rem; padding: .75rem .85rem; border: 1px solid var(--color-border); border-radius: var(--radius-md); }
.performance-error-cases > summary { cursor: pointer; color: var(--color-text); font-weight: 700; }
.performance-error-cases > p { margin: .55rem 0; }
.performance-error-cases td:nth-child(2) { min-width: 260px; white-space: normal; }
.evidence-gap-list ul { margin: .65rem 0 0; padding-left: 1.1rem; color: var(--color-text-muted); font-size: .8rem; line-height: 1.65; }
.evidence-gap-list li + li { margin-top: .35rem; }
.evidence-gap-list b { color: var(--color-text); }
.performance-loading,.performance-empty { display: grid; place-items: center; gap: .65rem; min-height: 180px; color: var(--color-text-muted); text-align: center; }
.performance-empty i { color: var(--color-primary); font-size: 2rem; }
.performance-empty strong { color: var(--color-text); }
.performance-empty p { margin: 0; }
.latest-performance { display: grid; gap: .9rem; }
.performance-version-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; }
.performance-version-heading h5 { margin: .38rem 0 .2rem; font-size: 1.35rem; letter-spacing: -.015em; }
.performance-version-heading p { margin: 0; color: var(--color-text-muted); font-size: .86rem; line-height: 1.5; }
.performance-latest-badge { display: inline-flex; align-items: center; gap: .35rem; padding: .32rem .62rem; border-radius: 999px; color: var(--color-primary); background: var(--color-primary-soft); font-size: .76rem; font-weight: 800; }
.performance-method-badge { display: flex; align-items: center; gap: .55rem; padding: .55rem .7rem; border: 1px solid var(--color-border); border-radius: 11px; background: var(--color-surface-subtle); }
.performance-method-badge > i { color: var(--color-primary); font-size: 1.05rem; }
.performance-method-badge span,.performance-method-badge small { display: block; }
.performance-method-badge span { font-size: .82rem; font-weight: 800; }
.performance-method-badge small { color: var(--color-text-muted); font-size: .72rem; font-weight: 500; }
.performance-summary-grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(245px,1fr)); gap: .65rem; }
.performance-summary-grid > article { position: relative; display: grid; gap: .55rem; padding: .8rem; border: 1px solid var(--color-border); border-radius: 13px; background: var(--color-surface); }
.performance-summary-grid > article.is-best { border-color: color-mix(in srgb,var(--color-success) 62%,var(--color-border)); box-shadow: inset 0 2px var(--color-success); }
.performance-summary-grid article > div > strong,.performance-summary-grid article > div > small { display: block; }
.performance-summary-grid article > div > strong { font-size: .86rem; line-height: 1.35; overflow-wrap:anywhere; }
.performance-summary-grid article > div > small { margin-top: .15rem; color: var(--color-text-muted); font-size: .69rem; overflow-wrap: anywhere; }
.performance-summary-badges { display:flex; flex-wrap:wrap; align-items:center; gap:.35rem; }
.best-model-result,.overfit-risk-badge { display:inline-flex; align-items:center; width:max-content; max-width:100%; padding:.24rem .48rem; border-radius:999px; font-size:.68rem; font-weight:800; line-height:1.3; }
.best-model-result { color:var(--color-success); background:var(--color-success-soft); }
.overfit-risk-badge.is-low { color:var(--color-success); background:var(--color-success-soft); }
.overfit-risk-badge.is-medium { color:var(--color-warning); background:var(--color-warning-soft); }
.overfit-risk-badge.is-high { color:var(--color-danger); background:color-mix(in srgb,var(--color-danger) 12%,transparent); }
.overfit-risk-badge.is-unknown { color:var(--color-text-muted); background:var(--color-surface-subtle); }
.performance-summary-grid dl { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: .35rem; margin: 0; }
.performance-summary-grid dl div { padding: .4rem; border-radius: 8px; background: var(--color-surface-subtle); }
.performance-summary-grid dt { color: var(--color-text-muted); font-size: .68rem; }
.performance-summary-grid dd { margin: .1rem 0 0; font-size: .9rem; font-weight: 800; }
.performance-scheme-name { color:var(--color-text-secondary) !important; font-weight:700; line-height:1.45; }
.performance-visualizations { margin-top:.1rem; border-color:color-mix(in srgb,var(--color-primary) 24%,var(--color-border)); box-shadow:0 10px 28px rgba(20,26,70,.06); }
.performance-verdict { display: grid; grid-template-columns: 46px minmax(0,1fr); gap: .8rem; padding: 1rem; border: 1px solid var(--color-border); border-radius: 15px; background: var(--color-surface-subtle); }
.performance-verdict.is-strong { border-color: color-mix(in srgb,var(--color-success) 42%,var(--color-border)); background: color-mix(in srgb,var(--color-success-soft) 62%,var(--color-surface)); }
.performance-verdict.is-developing { border-color: color-mix(in srgb,var(--color-primary) 40%,var(--color-border)); background: color-mix(in srgb,var(--color-primary-soft) 62%,var(--color-surface)); }
.performance-verdict.is-caution { border-color: color-mix(in srgb,var(--color-warning) 42%,var(--color-border)); background: color-mix(in srgb,var(--color-warning-soft) 62%,var(--color-surface)); }
.performance-verdict-icon { display: grid; place-items: center; width: 46px; height: 46px; border-radius: 14px; color: var(--color-primary); background: var(--color-surface); box-shadow: var(--shadow-xs); font-size: 1.2rem; }
.performance-verdict small { color: var(--color-text-muted); font-size: .76rem; }
.performance-verdict h4 { margin: .15rem 0 .38rem; font-size: 1.2rem; }
.performance-verdict p { margin: 0; color: var(--color-text-secondary); font-size: .86rem; line-height: 1.65; }
.overfit-risk-callout { display:grid; grid-template-columns:42px minmax(0,1fr); align-items:start; gap:.75rem; padding:.85rem 1rem; border:1px solid var(--color-border); border-radius:14px; background:var(--color-surface); }
.overfit-risk-callout > span { display:grid; place-items:center; width:42px; height:42px; border-radius:12px; background:var(--color-surface); box-shadow:var(--shadow-xs); }
.overfit-risk-callout small,.overfit-risk-callout strong { display:block; }
.overfit-risk-callout small { color:var(--color-text-muted); font-size:.72rem; }
.overfit-risk-callout strong { margin-top:.1rem; font-size:.9rem; }
.overfit-risk-callout p { margin:.28rem 0 0; color:var(--color-text-secondary); font-size:.78rem; line-height:1.55; }
.overfit-risk-callout .risk-rule-note { margin-top:.35rem; line-height:1.5; }
.overfit-risk-callout.is-low { border-color:color-mix(in srgb,var(--color-success) 38%,var(--color-border)); background:color-mix(in srgb,var(--color-success-soft) 52%,var(--color-surface)); }
.overfit-risk-callout.is-low > span { color:var(--color-success); }
.overfit-risk-callout.is-medium { border-color:color-mix(in srgb,var(--color-warning) 46%,var(--color-border)); background:color-mix(in srgb,var(--color-warning-soft) 58%,var(--color-surface)); }
.overfit-risk-callout.is-medium > span { color:var(--color-warning); }
.overfit-risk-callout.is-high { border-color:color-mix(in srgb,var(--color-danger) 52%,var(--color-border)); background:color-mix(in srgb,var(--color-danger) 10%,var(--color-surface)); }
.overfit-risk-callout.is-high > span { color:var(--color-danger); }
.overfit-risk-callout.is-unknown > span { color:var(--color-text-muted); }
.performance-main-grid { display: grid; grid-template-columns: minmax(0,1.05fr) minmax(0,.95fr); gap: .8rem; }
.performance-metric-panel,.performance-conclusion-panel,.performance-model-comparison { padding: .9rem; border: 1px solid var(--color-border); border-radius: 14px; background: var(--color-surface); }
.performance-section-title { display: flex; align-items: flex-start; justify-content: space-between; gap: .75rem; margin-bottom: .75rem; }
.performance-section-title strong,.performance-section-title small { display: block; }
.performance-section-title strong { font-size: .94rem; }
.performance-section-title small { margin-top: .16rem; color: var(--color-text-muted); font-size: .75rem; line-height: 1.45; }
.performance-section-title > span { padding: .25rem .5rem; border-radius: 8px; color: var(--color-primary); background: var(--color-primary-soft); font-size: .74rem; font-weight: 800; }
.performance-metric-chart { display: grid; gap: .55rem; }
.performance-metric-chart article { display: grid; grid-template-columns: 164px minmax(80px,1fr) 48px; align-items: center; gap: .65rem; }
.performance-metric-chart article > div:first-child strong,.performance-metric-chart article > div:first-child small { display: block; }
.performance-metric-chart article > div:first-child strong { font-size: .82rem; }
.performance-metric-chart article > div:first-child small { margin-top: .08rem; color: var(--color-text-muted); font-size: .7rem; line-height: 1.35; }
.performance-metric-chart article > b { font-size: .84rem; text-align: right; font-variant-numeric: tabular-nums; }
.performance-bar-track { height: 9px; overflow: hidden; border-radius: 999px; background: var(--color-surface-subtle); }
.performance-bar-track i { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg,#6366f1,#06b6d4); }
.performance-conclusion-panel ol { display: grid; gap: .58rem; margin: 0; padding-left: 1.25rem; color: var(--color-text-secondary); font-size: .82rem; line-height: 1.62; }
.performance-boundary { display: flex; align-items: flex-start; gap: .5rem; margin-top: .75rem; padding: .65rem; border-radius: 9px; color: var(--color-text-secondary); background: var(--color-primary-soft); }
.performance-boundary i { color: var(--color-primary); }
.performance-boundary p { margin: 0; font-size: .76rem; line-height: 1.6; }
.performance-model-comparison { border-color: color-mix(in srgb,var(--color-primary) 18%,var(--color-border)); box-shadow: 0 8px 24px rgba(20,26,70,.05); }
.performance-model-comparison table { min-width: 1030px; font-size: .82rem; }
.performance-model-comparison th { padding-block: .75rem; color: var(--color-text-secondary); font-size: .74rem; letter-spacing: .01em; }
.performance-model-comparison td { padding-block: .78rem; }
.performance-model-comparison td:first-child strong,.performance-model-comparison td:first-child small { display: block; }
.performance-model-comparison td:first-child small { margin-top: .12rem; color: var(--color-text-muted); font-size: .7rem; }
.performance-model-comparison tr.is-best-performance td { background: color-mix(in srgb,var(--color-success-soft) 72%,transparent); }
.performance-model-comparison tr.is-best-performance td:first-child { box-shadow: inset 3px 0 var(--color-success); }
.performance-model-details { border-top: 1px solid var(--color-border); background: var(--color-surface-subtle); }
.performance-model-details > summary { width: max-content; margin: .45rem .8rem; padding: .4rem .65rem; border-radius: 9px; color: var(--color-primary); cursor: pointer; font-size: .78rem; font-weight: 750; list-style: none; }
.performance-model-details > summary:hover { background: var(--color-primary-soft); }
.performance-model-details > summary::-webkit-details-marker { display: none; }
.performance-detail-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: .75rem; padding: .8rem; border-top: 1px solid var(--color-border); }
.performance-detail-grid > section { min-width: 0; padding: .75rem; border: 1px solid var(--color-border); border-radius: 11px; background: var(--color-surface); }
.performance-detail-grid > section > strong { display: block; margin-bottom: .65rem; font-size: .86rem; }
.performance-detail-grid table { min-width: 440px; font-size: .76rem; }
.performance-compact-facts { display: grid; grid-template-columns: minmax(130px,auto) minmax(0,1fr); gap: .48rem .7rem; margin: 0; font-size: .76rem; }
.performance-compact-facts dt { color: var(--color-text-muted); }
.performance-compact-facts dd { margin: 0; }
.generalization-gap { display: grid; gap: .38rem; }
.generalization-gap > b { font-size: .92rem; font-variant-numeric: tabular-nums; }
.generalization-gap > small { display: flex; align-items: flex-start; gap: .38rem; padding: .52rem .58rem; border-radius: 9px; color: var(--color-text-secondary); background: var(--color-primary-soft); font-size: .73rem; line-height: 1.55; }
.generalization-gap > small i { flex: 0 0 auto; margin-top: .08rem; color: var(--color-primary); }
.validation-level { display: inline-flex; align-items: center; gap: .38rem; padding: .34rem .58rem; border: 1px solid color-mix(in srgb,var(--color-warning) 38%,var(--color-border)); border-radius: 999px; color: var(--color-warning); background: var(--color-warning-soft); font-size: .76rem; font-weight: 800; }
.validation-level.is-external { border-color: color-mix(in srgb,var(--color-success) 40%,var(--color-border)); color: var(--color-success); background: var(--color-success-soft); }
.validation-level-note { display: block; margin-top: .35rem; color: var(--color-text-muted); font-size: .71rem; line-height: 1.45; }
.performance-data-facts { grid-column: 1 / -1; }
.performance-data-facts dl { display: grid; grid-template-columns: repeat(4,minmax(100px,auto) minmax(120px,1fr)); gap: .45rem .7rem; margin: 0; font-size: .76rem; }
.performance-data-facts dt { color: var(--color-text-muted); font-weight: 600; }
.performance-data-facts dd { min-width: 0; margin: 0; overflow-wrap: anywhere; }
.performance-history { overflow: hidden; border: 1px solid color-mix(in srgb,var(--color-primary) 18%,var(--color-border)); border-radius: 14px; background: var(--color-surface); box-shadow: 0 6px 18px rgba(20,26,70,.04); }
.performance-history > summary,.performance-history-version > summary { display: flex; align-items: center; justify-content: space-between; gap: .7rem; padding: .75rem .85rem; cursor: pointer; list-style: none; }
.performance-history summary::-webkit-details-marker { display: none; }
.performance-history > summary > span { display: grid; grid-template-columns: auto 1fr; gap: .1rem .5rem; align-items: center; }
.performance-history > summary > span i { grid-row: 1 / span 2; color: var(--color-primary); }
.performance-history summary strong { font-size: .86rem; }
.performance-history summary small { display: block; color: var(--color-text-muted); font-size: .74rem; line-height: 1.45; }
.performance-history summary > i,.performance-history-version summary > i { transition: transform .18s ease; }
.performance-history[open] > summary > i,.performance-history-version[open] > summary > i { transform: rotate(180deg); }
.performance-history-list { display: grid; gap: .55rem; padding: .75rem; border-top: 1px solid var(--color-border); background: var(--color-surface-subtle); }
.performance-history-version { overflow: hidden; border: 1px solid var(--color-border); border-radius: 10px; background: var(--color-surface); }
.performance-history-version > summary { display: grid; grid-template-columns: minmax(0,1fr) auto auto; }
.history-score { padding: .28rem .48rem; border-radius: 8px; color: var(--color-primary); background: var(--color-primary-soft); font-size: .74rem; font-weight: 700; }
.history-performance-body { display: grid; gap: .65rem; padding: .75rem; border-top: 1px solid var(--color-border); }
.history-verdict { display: flex; align-items: center; justify-content: space-between; gap: .5rem; padding: .55rem .65rem; border-radius: 8px; background: var(--color-surface-subtle); }
.history-verdict strong { font-size: .82rem; }
.history-verdict span { color: var(--color-text-muted); font-size: .75rem; }
.history-metrics { display: grid; grid-template-columns: repeat(6,minmax(0,1fr)); gap: .4rem; }
.history-metrics span { display: grid; gap: .1rem; padding: .45rem; border-radius: 8px; background: var(--color-surface-subtle); text-align: center; }
.history-metrics small { color: var(--color-text-muted); font-size: .68rem; }
.history-metrics strong { font-size: .82rem; }
.history-performance-body ul { margin: 0; padding-left: 1.15rem; color: var(--color-text-secondary); font-size: .78rem; line-height: 1.6; }
.class-performance-chart { display: grid; gap: .55rem; }
.class-performance-chart > article { display: grid; grid-template-columns: 82px minmax(0,1fr); gap: .6rem; align-items: center; }
.class-performance-chart > article > div:first-child strong,.class-performance-chart > article > div:first-child small { display: block; }
.class-performance-chart > article > div:first-child strong { font-size: .75rem; }
.class-performance-chart > article > div:first-child small { color: var(--color-text-muted); font-size: .64rem; }
.class-performance-bars { display: grid; gap: 3px; }
.class-performance-bars > span { position: relative; display: block; height: 16px; overflow: hidden; border-radius: 5px; background: var(--color-surface-subtle); }
.class-performance-bars i { display: block; height: 100%; background: color-mix(in srgb,var(--color-primary) 52%,transparent); }
.class-performance-bars > span:nth-child(2) i { background: color-mix(in srgb,#0ea5e9 58%,transparent); }
.class-performance-bars > span.is-f1 i { background: linear-gradient(90deg,#635bff,#22d3ee); }
.class-performance-bars small { position: absolute; inset: 0 .35rem; color: var(--color-text); font-size: .6rem; font-weight: 700; line-height: 16px; }
.fold-visual { display: flex; align-items: end; justify-content: space-around; gap: .45rem; height: 120px; padding: .65rem .65rem 0; border-bottom: 1px solid var(--color-border); background: linear-gradient(to top,var(--color-surface-subtle),transparent); }
.fold-visual span { position: relative; display: flex; align-items: end; justify-content: center; width: min(52px,16%); height: 100%; }
.fold-visual i { width: 100%; min-height: 2px; border-radius: 7px 7px 0 0; background: linear-gradient(180deg,#8f7cff,#635bff); }
.fold-visual b { position: absolute; top: -.15rem; z-index: 1; padding: .05rem .25rem; border-radius: 5px; color: var(--color-text); background: color-mix(in srgb,var(--color-surface) 84%,transparent); font-size: .62rem; font-style: normal; }
.fold-visual small { position: absolute; bottom: .2rem; color: #fff; font-size: .6rem; font-style: normal; font-weight: 700; text-shadow: 0 1px 2px rgba(0,0,0,.35); }
.confusion-matrix { display: grid; grid-template-columns: repeat(5, minmax(44px,1fr)); gap: 3px; text-align: center; }
.confusion-matrix > * { padding: .4rem; border-radius: 6px; background: var(--color-surface-subtle); }
.confusion-matrix .is-diagonal { color: var(--color-success); background: var(--color-success-soft); font-weight: 700; }
.matrix-corner { font-size: .68rem; color: var(--color-text-muted); }
.training-audit { padding: .8rem; border: 1px solid var(--color-border); border-radius: 12px; }
.training-audit > summary { cursor: pointer; font-weight: 700; }
.card, .list-group { border-radius: var(--radius-lg); overflow: hidden; }
.section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.protocol-config-card { border: 1px solid var(--color-border) !important; }
.narration-card { border: 1px solid var(--color-border) !important; }
.template-audit-card { border: 1px solid var(--color-border) !important; }
.audit-list { display: grid; gap: .65rem; }
.audit-row { display: grid; grid-template-columns: 38px minmax(0, 1fr) auto; align-items: center; gap: .75rem; padding: .75rem; border: 1px solid var(--color-border); border-radius: 12px; background: var(--color-surface); }
.audit-icon { display: grid; place-items: center; width: 36px; height: 36px; border-radius: 10px; color: var(--bs-primary); background: rgba(79,70,229,.1); }
.audit-meta { display: grid; justify-items: end; color: var(--bs-secondary-color); font-size: .78rem; }
.narration-count-skeleton {
  width: 92px;
  height: 34px;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--color-surface-subtle) 25%, var(--color-surface) 50%, var(--color-surface-subtle) 75%);
  background-size: 200% 100%;
  animation: narration-shimmer 1.2s linear infinite;
}
.narration-skeleton-list { display: grid; gap: .75rem; }
.narration-skeleton-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(260px, .42fr);
  gap: 1rem;
  min-height: 132px;
  padding: 1rem;
  border: 1px solid var(--color-border);
  border-radius: 12px;
  background: var(--color-surface);
}
.skeleton-copy,
.skeleton-actions { display: grid; align-content: start; gap: .65rem; }
.skeleton-line,
.skeleton-control,
.skeleton-button {
  display: block;
  border-radius: 8px;
  background: linear-gradient(90deg, var(--color-surface-subtle) 25%, var(--color-surface) 50%, var(--color-surface-subtle) 75%);
  background-size: 200% 100%;
  animation: narration-shimmer 1.2s linear infinite;
}
.skeleton-line { width: 88%; height: 12px; }
.skeleton-title { width: 34%; height: 18px; }
.skeleton-short { width: 58%; }
.skeleton-control { width: 100%; height: 34px; }
.skeleton-button { width: 110px; height: 34px; }
@keyframes narration-shimmer { to { background-position: -200% 0; } }
.narration-list { display: grid; gap: .75rem; }
.narration-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(300px, 390px);
  gap: 1rem;
  align-items: center;
  padding: 1rem;
  border: 1px solid var(--color-border);
  border-radius: 12px;
  background: var(--color-surface-subtle);
}
.narration-copy { min-width: 0; }
.narration-copy p { line-height: 1.6; }
.narration-actions { display: grid; gap: .65rem; }
.protocol-config-copy { max-width: 650px; }
.protocol-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 11px;
  color: var(--color-primary);
  background: var(--color-primary-soft);
  font-size: 1.05rem;
}
.protocol-config-control {
  display: flex;
  align-items: center;
  gap: 1rem;
  min-height: 48px;
}
.questionnaire-switch {
  display: flex;
  align-items: center;
  gap: .75rem;
  cursor: pointer;
}
.questionnaire-switch input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
}
.questionnaire-switch-track {
  position: relative;
  width: 46px;
  height: 26px;
  flex: 0 0 46px;
  border-radius: 999px;
  background: var(--color-border-strong);
  transition: background .2s ease;
}
.questionnaire-switch-thumb {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--color-surface);
  box-shadow: 0 2px 5px rgba(34, 38, 65, .22);
  transition: transform .2s ease;
}
.questionnaire-switch input:checked + .questionnaire-switch-track { background: var(--color-primary); }
.questionnaire-switch input:checked + .questionnaire-switch-track .questionnaire-switch-thumb {
  transform: translateX(20px);
}
.questionnaire-switch input:focus-visible + .questionnaire-switch-track {
  box-shadow: 0 0 0 .2rem rgba(75, 94, 232, .18);
}
.questionnaire-switch strong,
.questionnaire-switch small { display: block; }
.questionnaire-switch strong { color: var(--color-text); font-size: .9rem; }
.questionnaire-switch small { color: var(--color-text-muted); font-size: .75rem; }
.template-save-area {
  display: flex;
  align-items: flex-end;
  gap: .75rem;
}
.template-save-area .form-control { min-width: 150px; }
.template-save-area .btn { white-space: nowrap; }
.template-editor { font-family: Consolas, 'Courier New', monospace; font-size: .82rem; line-height: 1.65; }
.template-tab-item {
  padding: 0.85rem 1rem;
  font-size: 0.92rem;
  font-weight: 500;
  border: 1px solid var(--color-border);
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}
.template-tab-item.active {
  background: linear-gradient(135deg, #6366f1, #4f46e5) !important;
  border-color: #6366f1 !important;
  color: #ffffff !important;
  font-weight: 600;
  box-shadow: 0 4px 16px rgba(99, 102, 241, 0.4);
}
.version-row { display: flex; align-items: center; gap: .45rem; padding: .4rem; border-bottom: 1px solid var(--color-border); border-radius: .5rem; font-size: .82rem; }
.version-row.is-viewed {
  background: rgba(99, 102, 241, 0.15) !important;
  border-left: 3px solid var(--color-primary, #6366f1);
}
.version-view { min-width: 0; margin-right: auto; padding: .2rem 0; border: 0; background: transparent; color: inherit; text-align: left; overflow-wrap: anywhere; }
.version-view:hover { color: var(--bs-primary); }
.history-comparison-card { border-color: color-mix(in srgb,#06b6d4 30%,var(--color-border-strong)); background: linear-gradient(155deg,color-mix(in srgb,#06b6d4 7%,var(--color-surface)),var(--color-surface) 38%); }
.history-comparison-card > summary { min-height: 72px; background: linear-gradient(115deg,color-mix(in srgb,#06b6d4 13%,var(--color-surface)),color-mix(in srgb,var(--color-primary-soft) 60%,var(--color-surface))); }
.history-comparison-card > summary > span > i { color:#0891b2; }
.history-comparison-content { display:grid; gap:.85rem; }
.history-comparison-toolbar { display:flex; align-items:flex-start; justify-content:space-between; gap:1rem; }
.history-comparison-toolbar h5 { margin:.15rem 0 .25rem; font-size:1.15rem; }
.history-comparison-toolbar p { max-width:700px; margin:0; color:var(--color-text-muted); font-size:.78rem; line-height:1.55; }
.comparison-kicker { color:#0891b2; font-size:.66rem; font-weight:800; letter-spacing:.1em; }
.history-comparison-actions { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:.45rem; }
.history-comparison-actions .btn { white-space:nowrap; transition:transform 140ms cubic-bezier(.23,1,.32,1); }
.history-comparison-actions .btn:active { transform:scale(.97); }
.history-model-picker { overflow:hidden; border:1px solid var(--color-border); border-radius:14px; background:var(--color-surface); }
.history-model-picker > summary { display:flex; align-items:center; justify-content:space-between; gap:.75rem; padding:.8rem .9rem; cursor:pointer; list-style:none; }
.history-model-picker > summary::-webkit-details-marker { display:none; }
.history-model-picker > summary > span { display:grid; grid-template-columns:32px minmax(0,1fr); gap:.05rem .6rem; align-items:center; }
.history-model-picker > summary > span > i { grid-row:1 / span 2; display:grid; place-items:center; width:32px; height:32px; border-radius:9px; color:var(--color-primary); background:var(--color-primary-soft); }
.history-model-picker > summary b,.history-model-picker > summary small { display:block; }
.history-model-picker > summary small { color:var(--color-text-muted); font-size:.72rem; }
.history-model-picker > summary > i { transition:transform 180ms cubic-bezier(.23,1,.32,1); }
.history-model-picker[open] > summary { border-bottom:1px solid var(--color-border); }
.history-model-picker[open] > summary > i { transform:rotate(180deg); }
.history-model-picker-body { padding:.85rem; }
.history-model-search { position:relative; display:block; margin-bottom:.7rem; }
.history-model-search > i { position:absolute; z-index:1; top:50%; left:.75rem; transform:translateY(-50%); color:var(--color-text-muted); }
.history-model-search .form-control { padding-left:2.15rem; }
.history-model-version-list { display:grid; gap:.65rem; max-height:430px; overflow:auto; overscroll-behavior:contain; padding-right:.25rem; }
.history-model-version-group { padding:.7rem; border:1px solid var(--color-border); border-radius:12px; background:var(--color-surface-subtle); }
.history-model-version-group > header { display:flex; align-items:flex-start; justify-content:space-between; gap:.6rem; margin-bottom:.55rem; }
.history-model-version-group > header strong,.history-model-version-group > header small { display:block; }
.history-model-version-group > header strong { font-size:.82rem; overflow-wrap:anywhere; }
.history-model-version-group > header small { margin-top:.12rem; color:var(--color-text-muted); font-size:.67rem; }
.history-model-version-group > header > span { flex:0 0 auto; padding:.18rem .45rem; border-radius:999px; color:var(--color-primary); background:var(--color-primary-soft); font-size:.65rem; font-weight:800; }
.history-model-options { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.45rem; }
.history-model-option { display:grid; grid-template-columns:auto minmax(0,1fr) auto; align-items:start; gap:.5rem; min-width:0; padding:.6rem; border:1px solid var(--color-border); border-radius:10px; cursor:pointer; background:var(--color-surface); }
.history-model-option.active { border-color:color-mix(in srgb,var(--color-primary) 62%,var(--color-border)); background:color-mix(in srgb,var(--color-primary-soft) 48%,var(--color-surface)); box-shadow:inset 3px 0 var(--color-primary); }
.history-model-option input { margin-top:.18rem; accent-color:var(--color-primary); }
.history-model-option b,.history-model-option small { display:block; overflow-wrap:anywhere; }
.history-model-option b { font-size:.76rem; }
.history-model-option small { margin-top:.12rem; color:var(--color-text-muted); font-size:.66rem; }
.history-model-option > i { color:var(--color-text-muted); }
.history-model-option.active > i { color:var(--color-primary); }
.history-model-no-result { margin:0; padding:1rem; color:var(--color-text-muted); text-align:center; }
.comparison-validity { display:grid; grid-template-columns:36px minmax(0,1fr); gap:.65rem; align-items:start; padding:.72rem .8rem; border:1px solid var(--color-border); border-radius:12px; }
.comparison-validity > i { display:grid; place-items:center; width:36px; height:36px; border-radius:10px; background:var(--color-surface); }
.comparison-validity strong { font-size:.78rem; }
.comparison-validity p { margin:.14rem 0 0; color:var(--color-text-secondary); font-size:.72rem; line-height:1.5; }
.comparison-validity.is-comparable { color:var(--color-success); border-color:color-mix(in srgb,var(--color-success) 38%,var(--color-border)); background:var(--color-success-soft); }
.comparison-validity.is-reference { color:var(--color-warning); border-color:color-mix(in srgb,var(--color-warning) 42%,var(--color-border)); background:var(--color-warning-soft); }
.comparison-validity.is-empty { color:var(--color-primary); background:var(--color-primary-soft); }
.is-series-0 { --series-color:#6366f1; }.is-series-1 { --series-color:#06b6d4; }.is-series-2 { --series-color:#f59e0b; }.is-series-3 { --series-color:#ec4899; }.is-series-4 { --series-color:#22c55e; }.is-series-5 { --series-color:#8b5cf6; }
.history-comparison-card,.history-comparison-card > .fold-content,.history-comparison-content,.history-metric-comparison,.history-class-comparison,.history-comparison-table { min-width:0; max-width:100%; }
.history-selected-models { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:.55rem; }
.history-selected-models > article { display:grid; grid-template-columns:5px minmax(0,1fr) 28px; gap:.55rem; align-items:start; min-width:0; padding:.65rem; border:1px solid color-mix(in srgb,var(--series-color) 34%,var(--color-border)); border-radius:11px; background:color-mix(in srgb,var(--series-color) 6%,var(--color-surface)); }
.history-selected-models > article.is-overall-best,.history-class-grid > article.is-overall-best { border-color:color-mix(in srgb,#f59e0b 65%,var(--color-border)); box-shadow:0 0 0 1px color-mix(in srgb,#f59e0b 16%,transparent),0 10px 28px color-mix(in srgb,#f59e0b 10%,transparent); }
.history-series-mark { display:block; width:5px; height:100%; min-height:40px; border-radius:999px; background:var(--series-color); }
.history-selected-models small,.history-selected-models strong,.history-selected-models p { display:block; overflow-wrap:anywhere; }
.history-selected-models small { color:var(--color-text-muted); font-size:.64rem; }
.history-selected-models strong { margin-top:.08rem; font-size:.76rem; }
.history-selected-models p { margin:.1rem 0 0; color:var(--color-text-secondary); font-size:.65rem; }
.history-selected-models button { display:grid; place-items:center; width:28px; height:28px; border:0; border-radius:8px; color:var(--color-text-muted); background:transparent; transition:color 140ms ease,background-color 140ms ease,transform 140ms cubic-bezier(.23,1,.32,1); }
.history-selected-models button:hover { color:var(--color-danger); background:color-mix(in srgb,var(--color-danger) 10%,transparent); }
.history-selected-models button:active { transform:scale(.94); }
.history-overall-best-badge { display:inline-flex !important; align-items:center; gap:.28rem; width:max-content; max-width:100%; margin-top:.35rem; padding:.2rem .42rem; border:1px solid color-mix(in srgb,#f59e0b 42%,var(--color-border)); border-radius:999px; color:#b45309 !important; background:color-mix(in srgb,#f59e0b 12%,var(--color-surface)); font-size:.61rem !important; font-weight:800; line-height:1.2; }
[data-theme="dark"] .history-overall-best-badge { color:#fbbf24 !important; }
.history-overall-winner { overflow:hidden; border:1px solid color-mix(in srgb,#f59e0b 46%,var(--color-border)); border-radius:14px; background:linear-gradient(135deg,color-mix(in srgb,#f59e0b 12%,var(--color-surface)),color-mix(in srgb,var(--color-primary) 5%,var(--color-surface))); box-shadow:0 12px 32px color-mix(in srgb,#f59e0b 8%,transparent); }
.history-overall-winner > header { display:grid; grid-template-columns:42px minmax(0,1fr) minmax(190px,auto); align-items:center; gap:.7rem; padding:.82rem .9rem; border-bottom:1px solid color-mix(in srgb,#f59e0b 25%,var(--color-border)); }
.history-overall-winner > header > span { display:grid; place-items:center; width:42px; height:42px; border-radius:12px; color:#fff; background:linear-gradient(135deg,#f59e0b,#f97316); box-shadow:0 8px 20px color-mix(in srgb,#f59e0b 28%,transparent); }
.history-overall-winner header small,.history-overall-winner header h5,.history-overall-winner header p { display:block; margin:0; }
.history-overall-winner header small { color:var(--color-text-muted); font-size:.66rem; }
.history-overall-winner header h5 { margin-top:.08rem; font-size:.92rem; }
.history-overall-winner header p { margin-top:.1rem; color:var(--color-text-secondary); font-size:.69rem; overflow-wrap:anywhere; }
.history-winner-rule { max-width:300px; padding:.48rem .58rem; border-radius:10px; background:color-mix(in srgb,var(--color-surface) 74%,transparent); }
.history-winner-rule b,.history-winner-rule small { display:block; }
.history-winner-rule b { font-size:.68rem; }
.history-winner-rule small { margin-top:.12rem; line-height:1.45; }
.history-winner-metrics { display:grid; grid-template-columns:repeat(auto-fit,minmax(125px,1fr)); gap:.45rem; padding:.72rem .9rem .9rem; }
.history-winner-metrics article { min-width:0; padding:.56rem .6rem; border:1px solid var(--color-border); border-radius:10px; background:color-mix(in srgb,var(--color-surface) 82%,transparent); }
.history-winner-metrics article.is-single-best { border-color:color-mix(in srgb,var(--color-success) 48%,var(--color-border)); background:color-mix(in srgb,var(--color-success) 8%,var(--color-surface)); }
.history-winner-metrics span,.history-winner-metrics strong,.history-winner-metrics small { display:block; }
.history-winner-metrics span { color:var(--color-text-muted); font-size:.63rem; }
.history-winner-metrics strong { margin-top:.12rem; font-size:.88rem; font-variant-numeric:tabular-nums; }
.history-winner-metrics small { margin-top:.18rem; color:#b45309; font-size:.58rem; line-height:1.3; }
.history-winner-metrics article.is-single-best small { color:var(--color-success); font-weight:800; }
.history-metric-comparison,.history-class-comparison,.history-comparison-table { padding:.9rem; border:1px solid var(--color-border); border-radius:14px; background:var(--color-surface); }
.history-metric-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.6rem; }
.history-metric-panel { position:relative; min-width:0; padding:.7rem; border:1px solid var(--color-border); border-radius:11px; background:var(--color-surface-subtle); }
.history-metric-panel:has(.history-score-hover-target:hover),.history-metric-panel:has(.history-score-hover-target:focus) { z-index:30; }
.history-metric-panel > header strong,.history-metric-panel > header small { display:block; }
.history-metric-panel > header strong { font-size:.78rem; }
.history-metric-panel > header small { margin-top:.1rem; color:var(--color-text-muted); font-size:.64rem; }
.history-metric-series { display:grid; gap:.38rem; margin-top:.6rem; }
.history-metric-series > div { display:grid; grid-template-columns:24px minmax(70px,1fr) minmax(42px,auto); align-items:center; gap:.45rem; padding:.22rem; border-radius:8px; }
.history-metric-series > div.is-overall-best,.history-class-row.is-overall-best { background:color-mix(in srgb,#f59e0b 8%,transparent); }
.history-metric-series > div > span { display:grid; place-items:center; width:22px; height:22px; border-radius:7px; color:#fff; background:var(--series-color); font-size:.64rem; font-weight:800; }
.history-score-hover-target { position:relative; display:flex; align-items:center; min-width:0; height:26px; border-radius:8px; cursor:help; outline:none; }
.history-score-hover-target:focus-visible { box-shadow:0 0 0 2px color-mix(in srgb,var(--color-primary) 58%,transparent); }
.history-score-track { width:100%; height:8px; overflow:hidden; border-radius:999px; background:var(--color-surface); transition:transform 150ms cubic-bezier(.23,1,.32,1),box-shadow 150ms ease; }
.history-metric-series > div.is-single-best .history-score-track { box-shadow:0 0 0 2px color-mix(in srgb,var(--color-success) 28%,transparent); }
.history-score-track i { display:block; height:100%; border-radius:inherit; background:var(--series-color); }
.history-score-tooltip { position:absolute; bottom:calc(100% + 7px); left:50%; z-index:40; width:min(320px,calc(100vw - 40px)); padding:.7rem; border:1px solid color-mix(in srgb,var(--series-color) 34%,var(--color-border)); border-radius:12px; color:var(--color-text); background:color-mix(in srgb,var(--color-surface) 94%,transparent); box-shadow:0 16px 38px rgba(9,14,35,.24),0 0 0 1px color-mix(in srgb,var(--series-color) 8%,transparent); backdrop-filter:blur(14px); -webkit-backdrop-filter:blur(14px); opacity:0; visibility:hidden; pointer-events:none; transform:translate(-50%,4px) scale(.98); transform-origin:bottom center; transition:opacity 150ms ease-out,transform 150ms cubic-bezier(.23,1,.32,1),visibility 0s linear 150ms; }
.history-score-tooltip::before { content:""; position:absolute; top:100%; left:50%; width:10px; height:10px; border-right:1px solid color-mix(in srgb,var(--series-color) 34%,var(--color-border)); border-bottom:1px solid color-mix(in srgb,var(--series-color) 34%,var(--color-border)); background:inherit; transform:translate(-50%,-5px) rotate(45deg); }
.history-score-hover-target:focus .history-score-tooltip { opacity:1; visibility:visible; transform:translate(-50%,0) scale(1); transition-delay:0s; }
.history-score-hover-target:focus .history-score-track { transform:translateY(-1px); box-shadow:0 0 0 2px color-mix(in srgb,var(--series-color) 30%,transparent),0 5px 12px color-mix(in srgb,var(--series-color) 14%,transparent); }
.history-score-tooltip > header { display:grid; grid-template-columns:30px minmax(0,1fr); align-items:center; gap:.5rem; padding-bottom:.55rem; border-bottom:1px solid var(--color-border); }
.history-score-tooltip header small,.history-score-tooltip header strong { display:block; overflow-wrap:anywhere; }
.history-score-tooltip header small { color:var(--color-text-muted); font-size:.62rem; }
.history-score-tooltip header strong { margin-top:.08rem; font-size:.76rem; line-height:1.35; }
.history-tooltip-index { display:grid; place-items:center; width:30px; height:30px; border-radius:9px; color:#fff; background:var(--series-color); font-size:.7rem; font-weight:900; }
.history-score-tooltip dl { display:grid; grid-template-columns:68px minmax(0,1fr); gap:.34rem .5rem; margin:.58rem 0 0; font-size:.65rem; line-height:1.45; }
.history-score-tooltip dt { color:var(--color-text-muted); font-weight:600; }
.history-score-tooltip dd { min-width:0; margin:0; overflow-wrap:anywhere; }
.history-score-tooltip dd b { color:var(--series-color); font-size:.7rem; }
.history-score-tooltip footer { display:flex; flex-wrap:wrap; gap:.35rem; margin-top:.58rem; }
.history-score-tooltip footer span { display:inline-flex; align-items:center; gap:.24rem; padding:.18rem .4rem; border-radius:999px; font-size:.59rem; font-weight:800; }
.history-score-tooltip footer .is-overall { color:#b45309; background:color-mix(in srgb,#f59e0b 13%,transparent); }
.history-score-tooltip footer .is-single { color:var(--color-success); background:color-mix(in srgb,var(--color-success) 12%,transparent); }
[data-theme="dark"] .history-score-tooltip footer .is-overall { color:#fbbf24; }
.history-metric-series b { display:inline-flex; justify-content:flex-end; align-items:center; gap:.22rem; font-size:.68rem; font-variant-numeric:tabular-nums; text-align:right; }
.history-metric-series b .bi-stars,.history-class-row b .bi-stars,.history-class-grid footer b .bi-stars { color:#f59e0b; }
.history-single-best-label { color:var(--color-success); font-size:.57rem; font-weight:800; white-space:nowrap; }
.history-metric-series > div > .history-single-best-label { grid-column:2 / -1; justify-self:end; margin-top:-.15rem; }
.history-class-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:.6rem; }
.history-class-grid > article { min-width:0; padding:.7rem; border:1px solid color-mix(in srgb,var(--series-color) 28%,var(--color-border)); border-radius:11px; background:var(--color-surface-subtle); }
.history-class-grid article > header { display:grid; grid-template-columns:5px minmax(0,1fr) auto; gap:.5rem; align-items:start; margin-bottom:.6rem; }
.history-class-grid header strong,.history-class-grid header small { display:block; }
.history-class-grid header strong { font-size:.75rem; overflow-wrap:anywhere; }
.history-class-grid header small { color:var(--color-text-muted); font-size:.64rem; }
.history-class-row { display:grid; grid-template-columns:40px minmax(70px,1fr) minmax(42px,auto); align-items:center; gap:.45rem; margin-top:.4rem; padding:.2rem; border-radius:8px; font-size:.68rem; }
.history-class-row.is-single-best > div { box-shadow:0 0 0 2px color-mix(in srgb,var(--color-success) 28%,transparent); }
.history-class-row > div { height:8px; overflow:hidden; border-radius:999px; background:var(--color-surface); }
.history-class-row > div i { display:block; height:100%; border-radius:inherit; background:#64748b; }
.history-class-row > div i.is-monitoring { background:#6366f1; }.history-class-row > div i.is-regulation { background:#06b6d4; }.history-class-row > div i.is-evaluation { background:#f59e0b; }
.history-class-row > b { display:inline-flex; justify-content:flex-end; align-items:center; gap:.2rem; text-align:right; font-variant-numeric:tabular-nums; }
.history-class-row > .history-single-best-label { grid-column:2 / -1; justify-self:end; margin-top:-.15rem; }
.history-class-grid footer { display:flex; align-items:center; justify-content:space-between; gap:.5rem; margin-top:.6rem; padding-top:.55rem; border-top:1px solid var(--color-border); color:var(--color-text-muted); font-size:.67rem; }
.history-class-grid footer > span small { display:block; margin-top:.18rem; color:var(--color-success); font-size:.57rem; font-weight:800; }
.history-class-grid footer b { color:var(--color-text); }
.history-scroll-hint { display:inline-flex; align-items:center; gap:.3rem; color:var(--color-primary); font-size:.64rem; font-weight:700; white-space:nowrap; }
.history-comparison-table { overflow:hidden; }
.history-comparison-table .table-responsive { width:100%; max-width:100%; overflow-x:auto; overscroll-behavior-x:contain; scrollbar-gutter:stable; border:1px solid var(--color-border); border-radius:11px; }
.history-comparison-table .table-responsive:focus-visible { outline:2px solid color-mix(in srgb,var(--color-primary) 68%,transparent); outline-offset:2px; }
.history-comparison-table table { width:max-content; min-width:1280px; font-size:.7rem; }
.history-comparison-table th { color:var(--color-text-muted); white-space:nowrap; }
.history-comparison-table th:first-child,.history-comparison-table td:first-child { position:sticky; left:0; z-index:2; min-width:230px; background:var(--color-surface); box-shadow:1px 0 0 var(--color-border); }
.history-comparison-table th:first-child { z-index:3; background:var(--color-surface-subtle); }
.history-comparison-table td:first-child > strong,.history-comparison-table td:first-child > small { display:block; }
.history-comparison-table td:first-child > small { margin-top:.12rem; color:var(--color-text-muted); }
.history-comparison-table tr.is-overall-best td:first-child { background:color-mix(in srgb,#f59e0b 8%,var(--color-surface)); }
.history-value-cell { min-width:82px; font-variant-numeric:tabular-nums; }
.history-value-cell > span { display:inline-flex; align-items:center; gap:.24rem; font-weight:700; }
.history-value-cell > span > .bi-stars,.history-risk-cell > .bi-stars { color:#f59e0b; }
.history-value-cell > small { display:block; margin-top:.16rem; color:var(--color-success); font-size:.56rem; font-weight:800; white-space:nowrap; }
.history-value-cell.is-overall-model-metric { background:color-mix(in srgb,#f59e0b 6%,var(--color-surface)); box-shadow:inset 0 2px 0 color-mix(in srgb,#f59e0b 34%,transparent); }
.history-value-cell.is-single-best-metric { box-shadow:inset 0 -2px 0 color-mix(in srgb,var(--color-success) 62%,transparent); }
.history-value-cell.is-primary-metric > span { color:var(--color-primary); font-weight:900; }
.history-risk-cell { min-width:150px; }
.history-risk-cell > .bi-stars { margin-left:.28rem; }
.history-table-series { display:inline-flex; align-items:center; gap:.25rem; margin-bottom:.25rem; padding:.15rem .36rem; border-radius:999px; color:var(--series-color); background:color-mix(in srgb,var(--series-color) 10%,transparent); font-size:.62rem; font-weight:800; }
.history-table-series i { width:7px; height:7px; border-radius:50%; background:var(--series-color); }
.history-comparison-empty { display:grid; place-items:center; min-height:150px; padding:1rem; color:var(--color-text-muted); text-align:center; }
.history-comparison-empty i { color:#0891b2; font-size:1.75rem; }
.history-comparison-empty strong { margin-top:.45rem; color:var(--color-text); }
.history-comparison-empty p { margin:.15rem 0 0; }
@media (hover:hover) and (pointer:fine) {
  .history-model-option:hover { border-color:color-mix(in srgb,var(--color-primary) 42%,var(--color-border)); }
  .history-score-hover-target:hover .history-score-tooltip { opacity:1; visibility:visible; transform:translate(-50%,0) scale(1); transition-delay:80ms,80ms,0s; }
  .history-score-hover-target:hover .history-score-track { transform:translateY(-1px); box-shadow:0 0 0 2px color-mix(in srgb,var(--series-color) 30%,transparent),0 5px 12px color-mix(in srgb,var(--series-color) 14%,transparent); }
}
@media (max-width: 991.98px) {
  .performance-evidence-grid { grid-template-columns: repeat(2,minmax(0,1fr)); }
  .narration-row { grid-template-columns: 1fr; padding: .85rem; }
  .comparison-toolbar { align-items: stretch; flex-wrap: wrap; }
  .comparison-toolbar-copy { flex-basis: 100%; }
  .comparison-group-select { flex: 1 1 280px; }
  .comparison-group-select .form-select { width: 100%; }
  .model-comparison-grid { grid-template-columns: repeat(2,minmax(0,1fr)); }
  .parameter-grid { grid-template-columns:1fr; }
  .training-create-row { grid-template-columns: 1fr 1fr; }
  .training-create-actions { grid-column: 1 / -1; }
  .training-detail-grid { grid-template-columns: 1fr; }
  .fold-metrics { grid-template-columns: repeat(3, 1fr); }
  .class-f1-chart { grid-template-columns: 1fr; }
  .probability-visual-layout { grid-template-columns: 1fr; }
  .cross-entropy-panel { position: static; }
  .metric-decision-rule { grid-column: auto; }
  .training-group-toggle { grid-template-columns: 32px minmax(190px,1fr) auto minmax(120px,auto); }
  .training-group-active { display: none; }
  .performance-main-grid { grid-template-columns: 1fr; }
  .performance-summary-grid { grid-template-columns: repeat(2,minmax(0,1fr)); }
  .performance-detail-grid { grid-template-columns: 1fr; }
  .performance-data-facts { grid-column: auto; }
  .performance-data-facts dl { grid-template-columns: minmax(110px,auto) minmax(0,1fr); }
  .history-metrics { grid-template-columns: repeat(3,minmax(0,1fr)); }
  .history-comparison-toolbar { flex-direction:column; }
  .history-comparison-actions { justify-content:flex-start; }
  .history-metric-grid { grid-template-columns:1fr; }
}
@media (max-width: 575.98px) {
  .performance-evidence-grid { grid-template-columns: 1fr; }
  .comparison-toolbar { flex-direction: column; }
  .comparison-group-select { align-items: stretch; flex: 0 0 auto; flex-direction: column; width: 100%; }
  .comparison-group-label { max-width: 100%; }
  .comparison-toolbar > .btn { width: 100%; }
  .model-comparison-grid,.training-create-row { grid-template-columns: 1fr; }
  .training-create-actions { grid-column: auto; }
  .training-create-actions .btn { flex: 1 1 100%; min-height: 42px; }
  .training-summary-metrics { grid-template-columns: repeat(2,minmax(0,1fr)); }
  .fold-metrics { grid-template-columns: repeat(2, 1fr); }
  .active-model-banner { align-items: flex-start; }
  .narration-skeleton-row { grid-template-columns: 1fr; min-height: 190px; padding: .85rem; }
  .narration-actions .btn { flex: 1 1 100%; }
  .protocol-config-control { align-items: stretch; flex-direction: column; width: 100%; }
  .protocol-config-control .btn { width: 100%; }
  .template-card-heading { align-items: stretch !important; }
  .template-save-area { align-items: stretch; flex-direction: column; width: 100%; }
  .history-comparison-actions { display:grid; grid-template-columns:1fr; width:100%; }
  .history-comparison-actions .btn { width:100%; }
  .history-model-options,.history-class-grid { grid-template-columns:1fr; }
  .history-selected-models { grid-template-columns:1fr; }
  .history-model-picker-body,.history-metric-comparison,.history-class-comparison,.history-comparison-table { padding:.7rem; }
  .history-overall-winner > header { grid-template-columns:42px minmax(0,1fr); }
  .history-winner-rule { grid-column:1 / -1; max-width:none; }
  .template-save-area .form-control,
  .template-save-area .btn { width: 100%; }
  .template-editor { min-height: 55dvh; font-size: .78rem; }
  .training-create-entry { align-items: stretch; flex-direction: column; }
  .training-create-entry .btn { width: 100%; }
  .training-builder-section { padding: .75rem; }
  .training-choice-grid,.training-builder-section:first-child .training-choice-grid,.uploaded-dataset-fields,.custom-experiment-grid { grid-template-columns: 1fr; }
  .dataset-template-entry { align-items: stretch; flex-direction: column; }
  .dataset-template-entry .btn { width: 100%; }
  .model-evaluation-heading { align-items: stretch; flex-direction: column; }
  .metric-primary-badge { align-self: flex-start; }
  .metric-chart-row { grid-template-columns: 1fr; gap: .65rem; }
  .metric-bar-row { grid-template-columns: 76px minmax(90px,1fr) 38px; gap: .4rem; }
  .class-f1-heading { flex-direction: column; }
  .class-f1-legend { justify-content: flex-start; }
  .class-f1-bar-row { grid-template-columns: 102px minmax(70px,1fr) 36px; gap: .38rem; }
  .visual-section-heading { flex-direction: column; }
  .roc-comparison-grid { grid-template-columns: 1fr; }
  .roc-method-note { grid-template-columns: 1fr; }
  .roc-detail-grid,.evaluation-facts { grid-template-columns: 1fr; }
  .roc-detail-heading { flex-direction: column; }
  .performance-version-heading { flex-direction: column; }
  .performance-method-badge { width: 100%; }
  .performance-summary-grid { grid-template-columns: 1fr; }
  .performance-verdict { grid-template-columns: 1fr; }
  .model-performance-card > summary { min-height: 68px; padding: .85rem; }
  .model-performance-card > .fold-content { padding: .75rem; }
  .performance-metric-chart article { grid-template-columns: 128px minmax(70px,1fr) 42px; }
  .performance-history-version > summary { grid-template-columns: minmax(0,1fr) auto; }
  .history-score { grid-column: 1; justify-self: start; }
  .performance-history-version > summary > i { grid-column: 2; grid-row: 1 / span 2; }
  .history-metrics { grid-template-columns: repeat(2,minmax(0,1fr)); }
  .history-verdict { align-items: flex-start; flex-direction: column; }
  .performance-detail-grid { padding: .55rem; }
  .training-group-toggle { grid-template-columns: 30px minmax(180px,1fr) auto; gap: .55rem; min-width: 620px; }
  .training-group-progress { grid-column: 2; justify-self: start; }
  .training-group-toggle time { grid-column: 3; grid-row: 1 / span 2; }
}
@media (max-width: 575.98px) {
  .history-overall-winner > header { grid-template-columns:36px minmax(0,1fr); padding:.7rem; }
  .history-overall-winner > header > span { width:36px; height:36px; }
  .history-winner-metrics { grid-template-columns:repeat(2,minmax(0,1fr)); padding:.65rem; }
  .history-scroll-hint { width:100%; margin-top:.25rem; }
}
@media (prefers-reduced-motion: reduce) {
  .narration-count-skeleton,
  .skeleton-line,
  .skeleton-control,
  .skeleton-button { animation: none; }
  .training-live-progress,.training-stream-progress > span { transition: none; }
  .training-stream-progress > span::after { animation: none; opacity: .25; transform: none; }
  .history-score-tooltip,.history-score-track { transition-duration:0ms; }
}
</style>
