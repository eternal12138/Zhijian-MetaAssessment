<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useAuthStore } from '../stores/auth'
import { researchApi, type AiEvaluationOverview, type AiEvaluationScopeItem } from '../api/research'
import { confirmAction, notify } from '../composables/useUiFeedback'

type ScopeMode = 'all' | 'student' | 'session' | 'task'

const authStore = useAuthStore()
const overview = ref<AiEvaluationOverview | null>(null)
const loading = ref(true)
const activatingId = ref('')
const running = ref(false)
const search = ref('')
const scopeMode = ref<ScopeMode>('all')
const selectedIds = ref<string[]>([])
const progressText = ref('')
const processedTotal = ref(0)

const isAdmin = computed(() => authStore.userRole === 'admin')
const filteredItems = computed(() => {
  const keyword = search.value.trim().toLocaleLowerCase('zh-CN')
  if (!keyword) return overview.value?.scope_items ?? []
  return (overview.value?.scope_items ?? []).filter(item =>
    [item.participant_name, item.username, item.class_group, item.task_title]
      .some(value => (value || '').toLocaleLowerCase('zh-CN').includes(keyword))
  )
})

const groupedItems = computed(() => {
  const items = filteredItems.value
  if (scopeMode.value === 'session' || scopeMode.value === 'all') {
    return items.map(item => ({
      id: item.session_id,
      title: `${item.participant_name} · ${item.task_title}`,
      subtitle: `账号 ${item.username} · ${item.class_group || '未分班'} · ${formatTime(item.completed_at)}`,
      items: [item]
    }))
  }
  const map = new Map<string, AiEvaluationScopeItem[]>()
  for (const item of items) {
    const key = scopeMode.value === 'student' ? item.participant_id : item.task_id
    map.set(key, [...(map.get(key) || []), item])
  }
  return [...map.entries()].map(([id, rows]) => ({
    id,
    title: scopeMode.value === 'student'
      ? `${rows[0].participant_name}（${rows[0].username}）`
      : rows[0].task_title,
    subtitle: scopeMode.value === 'student'
      ? `${rows[0].class_group || '未分班'} · ${rows.length} 次对话`
      : `${rows.length} 次对话 · ${new Set(rows.map(row => row.participant_id)).size} 名学生`,
    items: rows
  }))
})

function formatTime(value: string | null) {
  if (!value) return '完成时间未记录'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'
  }).format(new Date(value))
}

function metric(value: number | null) {
  return value == null ? '—' : value.toFixed(3)
}

function sum(rows: AiEvaluationScopeItem[], key: keyof AiEvaluationScopeItem) {
  return rows.reduce((total, row) => total + Number(row[key] || 0), 0)
}

function dimensionSum(rows: AiEvaluationScopeItem[], key: string) {
  return rows.reduce((total, row) => total + Number(row.dimension_counts[key] || 0), 0)
}

function isSelected(id: string) {
  return selectedIds.value.includes(id)
}

function toggleSelected(id: string) {
  selectedIds.value = isSelected(id)
    ? selectedIds.value.filter(item => item !== id)
    : [...selectedIds.value, id]
}

function changeScope() {
  selectedIds.value = []
}

async function load() {
  loading.value = true
  try {
    overview.value = (await researchApi.getAiEvaluationOverview()).data
  } catch (error) {
    notify(error instanceof Error ? error.message : 'AI 评估数据加载失败', 'danger')
  } finally {
    loading.value = false
  }
}

async function activate(modelId: string, version: string) {
  if (!isAdmin.value) return
  const confirmed = await confirmAction({
    title: '启用分类模型',
    message: `确定启用模型版本 ${version} 吗？之后教师将使用这个版本执行 AI 三分类。`,
    confirmText: '确认启用'
  })
  if (!confirmed) return
  activatingId.value = modelId
  try {
    await researchApi.activateModelTrainingJob(modelId)
    notify('模型已启用，教师端现可使用该版本。', 'success')
    await load()
  } catch (error) {
    notify(error instanceof Error ? error.message : '模型启用失败', 'danger')
  } finally {
    activatingId.value = ''
  }
}

async function deactivate(modelId: string, version: string) {
  if (!isAdmin.value) return
  const confirmed = await confirmAction({
    title: '取消启用模型',
    message: `确定取消启用模型版本 ${version} 吗？取消后教师将无法执行 AI 评估，训练产物和历史分类结果不会被删除。`,
    confirmText: '确认取消启用',
    tone: 'danger'
  })
  if (!confirmed) return
  activatingId.value = modelId
  try {
    await researchApi.deactivateModelTrainingJob(modelId)
    notify('模型已取消启用，AI 评估已暂停。', 'success')
    await load()
  } catch (error) {
    notify(error instanceof Error ? error.message : '取消启用失败', 'danger')
  } finally {
    activatingId.value = ''
  }
}

async function runEvaluation() {
  if (!overview.value?.enabled || running.value) return
  if (scopeMode.value !== 'all' && !selectedIds.value.length) {
    notify('请先选择至少一个评估范围。', 'warning')
    return
  }
  const confirmed = await confirmAction({
    title: '执行元认知三分类',
    message: '系统将优先采用已人工复核文本；未复核候选继续采用 AI 初筛文本，人工排除内容不会进入分类。是否继续？',
    confirmText: '开始分类'
  })
  if (!confirmed) return
  running.value = true
  processedTotal.value = 0
  progressText.value = '正在读取待分类候选…'
  try {
    let guard = 0
    while (guard < 10000) {
      guard += 1
      const result = (await researchApi.runAiEvaluation(scopeMode.value, selectedIds.value, 100)).data
      processedTotal.value += result.processed
      progressText.value = result.remaining > 0
        ? `已处理 ${processedTotal.value} 条，正在继续下一批…`
        : `分类完成，共更新 ${processedTotal.value} 条；人工排除 ${result.skipped_rejected} 条未进入分类。`
      if (result.remaining === 0 || result.processed === 0) break
    }
    notify(processedTotal.value ? 'AI 三分类已完成。' : '所选范围已是当前模型的最新结果。', 'success')
    await load()
  } catch (error) {
    notify(error instanceof Error ? error.message : 'AI 分类执行失败', 'danger')
  } finally {
    running.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="ai-evaluation-page">
    <header class="ds-page-header evaluation-header">
      <div>
        <span class="eyebrow">AI METACOGNITION ASSESSMENT</span>
        <h1>AI 评估</h1>
        <p>使用管理员启用的模型，对候选复核结果执行监控、调控、评估三分类。</p>
      </div>
      <span class="role-badge"><i class="bi" :class="isAdmin ? 'bi-shield-check' : 'bi-person-video3'"></i>{{ isAdmin ? '管理员模型治理' : '教师评估工作台' }}</span>
    </header>

    <div v-if="loading" class="evaluation-skeleton"><span></span><span></span><span></span></div>
    <template v-else-if="overview">
      <section class="model-governance">
        <div class="section-heading">
          <div><span>生产模型</span><h2>模型启用与版本状态</h2></div>
          <div v-if="overview.active_model" class="active-model-pill"><i class="bi bi-broadcast-pin"></i>当前启用：{{ overview.active_model.version }}</div>
        </div>
        <div v-if="!overview.models.length" class="empty-state">尚无训练完成的模型，请由管理员先在研究管理中完成训练。</div>
        <div v-else class="model-grid">
          <article v-for="model in overview.models" :key="model.id" class="model-card" :class="{ 'is-active': model.is_active, 'is-best': model.is_best }">
            <div class="model-card-top"><i class="bi bi-diagram-3"></i><span v-if="model.is_best" class="best-badge"><i class="bi bi-stars"></i>当前最优</span></div>
            <h3>{{ model.display_name }}</h3>
            <p>{{ model.version }}</p>
            <div class="model-metrics"><span>Macro-F1 <b>{{ metric(model.macro_f1) }}</b></span><span>Weighted-F1 <b>{{ metric(model.weighted_f1) }}</b></span></div>
            <div class="model-action">
              <template v-if="model.is_active">
                <span class="using-badge"><i class="bi bi-check-circle-fill"></i>正在使用</span>
                <button v-if="isAdmin" class="btn btn-sm btn-outline-danger ms-2" :disabled="activatingId === model.id" @click="deactivate(model.id, model.version)">
                  <span v-if="activatingId === model.id" class="spinner-border spinner-border-sm me-1"></span>取消启用
                </button>
              </template>
              <button v-else-if="isAdmin" class="btn btn-sm btn-outline-primary" :disabled="activatingId === model.id" @click="activate(model.id, model.version)">
                <span v-if="activatingId === model.id" class="spinner-border spinner-border-sm me-1"></span>启用此模型
              </button>
              <small v-else>仅管理员可启用或切换模型</small>
            </div>
          </article>
        </div>
        <div class="provenance-banner" :class="`source-${overview.training_source}`"><i class="bi bi-database-check"></i><div><strong>训练数据来源</strong><span>{{ overview.training_source_label }}</span></div></div>
      </section>

      <section class="scope-panel">
        <div class="section-heading">
          <div><span>评估范围</span><h2>选择需要分类的数据</h2></div>
          <button class="btn btn-primary" :disabled="!overview.enabled || running" @click="runEvaluation">
            <span v-if="running" class="spinner-border spinner-border-sm me-2"></span><i v-else class="bi bi-stars me-2"></i>{{ running ? '正在分类' : '一键执行三分类' }}
          </button>
        </div>
        <div v-if="!overview.enabled" class="alert alert-warning"><i class="bi bi-exclamation-triangle me-2"></i>管理员尚未启用模型，教师暂不能执行 AI 评估。</div>
        <div class="scope-toolbar">
          <label><span>分组与选择方式</span><select v-model="scopeMode" class="form-select" @change="changeScope"><option value="all">全部数据</option><option value="student">按学生</option><option value="session">按对话/测评会话</option><option value="task">按任务</option></select></label>
          <label><span>搜索</span><div class="search-input"><i class="bi bi-search"></i><input v-model="search" class="form-control" placeholder="姓名、账号、班级或任务"></div></label>
        </div>
        <div class="merge-rule"><i class="bi bi-layers"></i><span><b>文本合并规则：</b>已复核候选采用人工确认后的文本；待复核候选保留 AI 初筛文本；已排除候选不参与评估。</span></div>
        <div v-if="progressText" class="progress-feedback" :class="{ 'is-running': running }"><i class="bi" :class="running ? 'bi-arrow-repeat' : 'bi-check2-circle'"></i>{{ progressText }}</div>

        <div class="scope-list">
          <article v-for="group in groupedItems" :key="group.id" class="scope-card" :class="{ 'is-selected': isSelected(group.id) }" @click="scopeMode !== 'all' && toggleSelected(group.id)">
            <button v-if="scopeMode !== 'all'" class="scope-check" :aria-label="isSelected(group.id) ? '取消选择' : '选择'" @click.stop="toggleSelected(group.id)"><i class="bi" :class="isSelected(group.id) ? 'bi-check-square-fill' : 'bi-square'"></i></button>
            <div class="scope-main"><h3>{{ group.title }}</h3><p>{{ group.subtitle }}</p><span v-if="overview.training_source === 'system_gold' && group.items.some(item => item.training_participant)" class="training-data-badge"><i class="bi bi-mortarboard-fill"></i>该学生数据参与了当前模型训练</span><span v-else-if="overview.training_source === 'uploaded'" class="external-data-badge"><i class="bi bi-box-arrow-in-down"></i>当前模型使用外部上传训练数据</span></div>
            <div class="scope-stats"><span><b>{{ sum(group.items, 'candidate_count') }}</b>候选</span><span><b>{{ sum(group.items, 'reviewed_count') }}</b>人工复核</span><span><b>{{ sum(group.items, 'pending_count') }}</b>AI 待复核</span><span class="classified"><b>{{ sum(group.items, 'classified_count') }}</b>已分类</span></div>
            <div class="dimension-strip"><span class="monitoring">监控 {{ dimensionSum(group.items, 'monitoring') }}</span><span class="regulation">调控 {{ dimensionSum(group.items, 'regulation') }}</span><span class="evaluation">评估 {{ dimensionSum(group.items, 'evaluation') }}</span></div>
          </article>
          <div v-if="!groupedItems.length" class="empty-state">当前权限与筛选条件下没有可评估的候选数据。</div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.ai-evaluation-page{display:grid;gap:1.25rem}.evaluation-header{display:flex;justify-content:space-between;align-items:flex-start}.eyebrow,.section-heading>div>span{color:var(--color-primary);font-size:.72rem;font-weight:800;letter-spacing:.12em}.evaluation-header h1{margin:.35rem 0 .4rem;font-size:clamp(1.8rem,3vw,2.5rem)}.evaluation-header p{margin:0;color:var(--color-text-muted)}.role-badge,.active-model-pill{display:inline-flex;gap:.5rem;align-items:center;border:1px solid var(--color-border);background:color-mix(in srgb,var(--color-surface) 78%,transparent);border-radius:999px;padding:.55rem .8rem;font-size:.82rem;font-weight:700}.model-governance,.scope-panel{border:1px solid var(--color-border);border-radius:1.25rem;background:var(--color-surface);padding:1.25rem;box-shadow:var(--shadow-sm)}.section-heading{display:flex;justify-content:space-between;gap:1rem;align-items:center;margin-bottom:1rem}.section-heading h2{font-size:1.15rem;margin:.2rem 0 0}.model-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.8rem}.model-card{position:relative;border:1px solid var(--color-border);border-radius:1rem;padding:1rem;background:color-mix(in srgb,var(--color-surface) 90%,transparent)}.model-card.is-best{border-color:#8b7cf6}.model-card.is-active{box-shadow:inset 0 0 0 1px #22c59b,0 8px 24px rgba(34,197,155,.1)}.model-card-top{display:flex;justify-content:space-between;color:var(--color-primary);font-size:1.2rem}.best-badge,.using-badge,.training-data-badge,.external-data-badge{display:inline-flex;align-items:center;gap:.35rem;border-radius:999px;padding:.28rem .55rem;font-size:.7rem;font-weight:800}.best-badge{background:rgba(139,124,246,.14);color:#8b7cf6}.using-badge{background:rgba(34,197,155,.14);color:#18a77f}.model-card h3{font-size:.92rem;margin:.8rem 0 .25rem}.model-card p{font-size:.76rem;color:var(--color-text-muted);overflow-wrap:anywhere}.model-metrics{display:grid;grid-template-columns:1fr 1fr;gap:.5rem}.model-metrics span{background:var(--color-surface-subtle);border-radius:.7rem;padding:.55rem;font-size:.68rem;color:var(--color-text-muted)}.model-metrics b{display:block;color:var(--color-text);font-size:1rem}.model-action{min-height:2.1rem;margin-top:.75rem;display:flex;align-items:center}.model-action small{color:var(--color-text-muted)}.provenance-banner,.merge-rule,.progress-feedback{display:flex;align-items:center;gap:.75rem;border-radius:.9rem;padding:.8rem 1rem;margin-top:1rem;background:var(--color-surface-subtle)}.provenance-banner>i{font-size:1.2rem;color:var(--color-primary)}.provenance-banner strong,.provenance-banner span{display:block}.provenance-banner span{font-size:.78rem;color:var(--color-text-muted);margin-top:.12rem}.scope-toolbar{display:grid;grid-template-columns:260px minmax(240px,1fr);gap:.8rem}.scope-toolbar label>span{display:block;font-size:.74rem;font-weight:700;color:var(--color-text-muted);margin-bottom:.35rem}.search-input{position:relative}.search-input i{position:absolute;left:.8rem;top:.7rem;color:var(--color-text-muted)}.search-input input{padding-left:2.2rem}.merge-rule{font-size:.82rem;border:1px dashed var(--color-border)}.merge-rule i{font-size:1.2rem;color:var(--color-primary)}.progress-feedback{background:rgba(34,197,155,.11);color:#159b76;font-weight:700}.progress-feedback.is-running i{animation:spin 1s linear infinite}.scope-list{display:grid;gap:.7rem;margin-top:1rem}.scope-card{display:grid;grid-template-columns:auto minmax(220px,1fr) auto;gap:.8rem 1rem;align-items:center;border:1px solid var(--color-border);border-radius:1rem;padding:1rem;background:var(--color-surface);transition:border-color .18s ease,background .18s ease}.scope-card.is-selected{border-color:var(--color-primary);background:color-mix(in srgb,var(--color-primary) 5%,var(--color-surface))}.scope-check{border:0;background:transparent;color:var(--color-primary);font-size:1.1rem;padding:.2rem}.scope-main h3{font-size:.95rem;margin:0 0 .22rem}.scope-main p{font-size:.76rem;color:var(--color-text-muted);margin:0}.training-data-badge{margin-top:.5rem;background:rgba(139,124,246,.12);color:#7867e8}.external-data-badge{margin-top:.5rem;background:var(--color-surface-subtle);color:var(--color-text-muted)}.scope-stats{display:flex;gap:.45rem}.scope-stats span{min-width:68px;text-align:center;border-radius:.65rem;background:var(--color-surface-subtle);padding:.45rem;font-size:.67rem;color:var(--color-text-muted)}.scope-stats b{display:block;font-size:.9rem;color:var(--color-text)}.dimension-strip{grid-column:2/-1;display:flex;gap:.4rem}.dimension-strip span{padding:.25rem .55rem;border-radius:999px;font-size:.69rem;font-weight:700}.monitoring{background:rgba(72,149,239,.12);color:#4389d8}.regulation{background:rgba(139,124,246,.12);color:#7867e8}.evaluation{background:rgba(245,166,35,.13);color:#c98514}.empty-state{text-align:center;color:var(--color-text-muted);padding:2.5rem}.evaluation-skeleton{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem}.evaluation-skeleton span{height:180px;border-radius:1rem;background:linear-gradient(90deg,var(--color-surface-subtle),var(--color-surface),var(--color-surface-subtle));background-size:200% 100%;animation:shimmer 1.4s infinite}@keyframes shimmer{to{background-position:-200% 0}}@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:1100px){.model-grid{grid-template-columns:repeat(2,1fr)}.scope-card{grid-template-columns:auto 1fr}.scope-stats,.dimension-strip{grid-column:2}}
@media(max-width:700px){.evaluation-header,.section-heading{align-items:stretch;flex-direction:column}.model-grid,.scope-toolbar{grid-template-columns:1fr}.model-governance,.scope-panel{padding:1rem}.scope-card{grid-template-columns:auto 1fr}.scope-stats{display:grid;grid-template-columns:repeat(2,1fr);width:100%}.dimension-strip{flex-wrap:wrap}.active-model-pill{align-self:flex-start}}
</style>
