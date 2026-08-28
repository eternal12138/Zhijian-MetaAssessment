<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import StatCard from '../components/dashboard/StatCard.vue'
import PlanetOrbitHero from '../components/dashboard/PlanetOrbitHero.vue'
import MacroAnalyticsDashboard from '../components/dashboard/MacroAnalyticsDashboard.vue'
import { reportApi } from '../api/reports'
import {
  protocolApi,
  type AssessmentProtocol,
  type AssessmentRun
} from '../api/protocol'
import { useReportStore } from '../stores/report'
import { useUserStore } from '../stores/user'

const userStore = useUserStore()
const reportStore = useReportStore()
const report = computed(() => reportStore.latestReport)
const reportCount = ref(0)
const protocol = ref<AssessmentProtocol | null>(null)
const currentRun = ref<AssessmentRun | null>(null)
const isLoading = ref(true)

const nextTask = computed(() => {
  const tasks = protocol.value?.tasks ?? []
  if (!currentRun.value) return tasks[0] ?? null
  const nextSession = [...currentRun.value.sessions]
    .sort((left, right) => left.sequence_no - right.sequence_no)
    .find(session => session.status !== 'completed')
  return tasks.find(task => task.id === nextSession?.task_id) ?? tasks[0] ?? null
})
const assessmentInProgress = computed(() => Boolean(currentRun.value))
const assessmentActionLabel = computed(() =>
  assessmentInProgress.value ? '继续本次测评' : '开始测评'
)

onMounted(async () => {
  try {
    reportStore.clearReports()
    const [reportResult, protocolResult, runResult] = await Promise.allSettled([
      reportApi.list(),
      protocolApi.getProtocol(),
      protocolApi.getCurrentRun()
    ])

    if (protocolResult.status === 'fulfilled') protocol.value = protocolResult.value.data
    if (runResult.status === 'fulfilled') currentRun.value = runResult.value.data

    if (reportResult.status === 'fulfilled') {
      const listResponse = reportResult.value
      reportCount.value = listResponse.data.length
      const latest = listResponse.data[0]
      if (latest) {
        try {
          const detail = (await reportApi.get(latest.id)).data
          reportStore.addReport({
            id: detail.id,
            generatedAt: detail.generated_at,
            overallScore: detail.overall_score,
            level: detail.level,
            summary: detail.summary,
            dimensions: detail.dimension_details.map(item => ({
              dimension: item.dimension,
              label: item.label,
              score: item.score,
              max: 100
            }))
          })
        } catch {
          // 报告详情暂时不可用时保留真实报告数量，不展示过期的本地报告。
        }
      }
    } else {
      reportCount.value = 0
    }
  } finally {
    isLoading.value = false
  }
})
</script>

<template>
  <div class="dashboard-page">
    <div v-if="isLoading" class="dashboard-loading" aria-label="正在加载学习概览" aria-busy="true">
      <div class="skeleton-block skeleton-welcome" />
      <div class="stats-grid">
        <div v-for="index in 3" :key="index" class="skeleton-block skeleton-stat" />
      </div>
      <div class="dashboard-grid">
        <div class="skeleton-block skeleton-panel" />
        <div class="skeleton-block skeleton-panel" />
      </div>
    </div>
    <div v-else class="dashboard-content">
      <section class="welcome-card">
        <!-- 全幅宇宙星空与行星环绕交互引擎 -->
        <PlanetOrbitHero />
        <div class="welcome-info">
          <span class="badge-soft"><i class="bi bi-stars"></i> 本周学习计划</span>
          <h2>你好，{{ userStore.displayName }}！</h2>
          <p>通过两项问题解决任务，看看你如何计划、监控并调整自己的思考。</p>
          <RouterLink to="/assessment" class="btn btn-welcome-action px-4">
            {{ assessmentActionLabel }} <i class="bi bi-arrow-right ms-2"></i>
          </RouterLink>
        </div>
      </section>

      <section class="stats-grid">
        <StatCard icon="bi-clipboard-check" tone="purple" label="已发布报告" :value="reportCount" unit="次" hint="经研究审核后正式发布" />
        <StatCard icon="bi-bullseye" tone="blue" label="最近综合分" :value="report?.overallScore ?? '--'" hint="阶段性学习反馈" />
        <StatCard icon="bi-clock-history" tone="coral" label="常模状态" value="--" hint="尚未建立正式常模" />
      </section>

      <!-- 卡片 1：宏观元认知三类构成与群体参照 -->
      <section class="dashboard-macro-section">
        <MacroAnalyticsDashboard user-role="student" />
      </section>

      <!-- 卡片 2 & 3：我的元认知画像 与 下一项任务 -->
      <section class="dashboard-grid">
        <article class="panel profile-panel">
          <div class="panel-head">
            <div>
              <p class="panel-kicker">最近一次测评</p>
              <h2>最近发布的综合报告</h2>
            </div>
            <RouterLink to="/report" class="panel-action-link">
              查看报告 <i class="bi bi-arrow-up-right"></i>
            </RouterLink>
          </div>

          <div v-if="report" class="report-summary-wrap">
            <div class="score-note">
              <span>综合表现</span>
              <strong>{{ report.level }}</strong>
              <p>{{ report.summary }}</p>
            </div>
          </div>

          <div v-else class="profile-empty-state">
            <div class="empty-icon-circle">
              <i class="bi bi-file-earmark-bar-graph"></i>
            </div>
            <p class="empty-title">暂未发布综合报告</p>
            <p class="empty-desc">三维测量画像会在上方依据最终有效对话独立显示；综合报告需经研究复核发布后才可查看。</p>
          </div>
        </article>

        <article class="panel task-panel">
          <div class="panel-head">
            <div>
              <p class="panel-kicker">待完成任务</p>
              <h2>下一项任务</h2>
            </div>
            <span class="status-pill" :class="{ 'is-in-progress': assessmentInProgress }">
              {{ assessmentInProgress ? '进行中' : '待开始' }}
            </span>
          </div>

          <div class="task-illustration">
            <i class="bi bi-calculator"></i>
            <span class="ball ball-a"></span>
            <span class="ball ball-b"></span>
          </div>

          <div class="task-info-block">
            <h3 class="task-title">{{ nextTask?.title ?? '标准问题解决任务' }}</h3>
            <p class="task-desc">{{ nextTask?.description ?? '按照标准指导语完成任务，并在解决过程中持续说出你的思考过程。' }}</p>
            
            <div class="task-meta-tags">
              <span class="meta-tag"><i class="bi bi-clock me-1"></i>约 {{ nextTask?.estimated_minutes ?? 12 }} 分钟</span>
              <span class="meta-tag"><i class="bi bi-mic me-1"></i>需要语音采集</span>
            </div>
          </div>

          <div class="task-action-wrapper">
            <RouterLink to="/assessment" class="btn btn-task-action w-100">
              <span>{{ assessmentActionLabel }}</span>
              <i class="bi bi-arrow-right ms-2"></i>
            </RouterLink>
          </div>
        </article>
      </section>
    </div>
  </div>
</template>

<style scoped>
.dashboard-macro-section {
  margin: 32px 0;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(340px, 1fr);
  gap: 28px;
  align-items: stretch;
  margin-top: 32px;
}

.panel {
  display: flex;
  flex-direction: column;
  padding: 30px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.04);
  transition: transform var(--motion-popover) var(--ease-out), box-shadow var(--motion-popover) ease, border-color var(--motion-popover) ease;
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 22px;
}

.panel-kicker {
  font-size: 11.5px;
  font-weight: 700;
  letter-spacing: 0.6px;
  color: var(--color-text-muted);
  margin-bottom: 5px;
}

.panel h2 {
  margin: 0;
  font-size: 1.22rem;
  font-weight: 800;
  color: var(--color-text);
}

.panel-action-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  color: var(--color-primary);
  font-size: 12.5px;
  font-weight: 700;
  text-decoration: none;
  background: var(--color-primary-soft);
  transition: all var(--motion-fast) ease;
}

.panel-action-link:hover {
  background: var(--color-primary);
  color: #fff;
}

.profile-empty-state {
  flex: 1;
  min-height: 290px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 2.5rem 1.5rem;
}

.empty-icon-circle {
  width: 68px;
  height: 68px;
  border-radius: 50%;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  display: grid;
  place-items: center;
  font-size: 1.8rem;
  margin-bottom: 16px;
}

.empty-title {
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--color-text);
  margin-bottom: 8px;
}

.empty-desc {
  max-width: 380px;
  margin: 0;
  font-size: 0.88rem;
  line-height: 1.65;
  color: var(--color-text-muted);
}

.task-panel {
  justify-content: space-between;
}

.task-illustration {
  position: relative;
  height: 98px;
  margin: 4px 0 20px;
  overflow: hidden;
  border-radius: 14px;
  background: var(--color-surface-subtle);
  border: 1px solid var(--color-border);
  color: var(--color-primary);
}

.task-illustration i {
  position: absolute;
  bottom: -12px;
  right: 24px;
  font-size: 96px;
  opacity: 0.35;
}

.task-info-block {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.task-title {
  font-size: 1.16rem;
  font-weight: 700;
  color: var(--color-text);
  margin-bottom: 10px;
  line-height: 1.4;
}

.task-desc {
  color: var(--color-text-secondary);
  font-size: 0.88rem;
  line-height: 1.7;
  margin-bottom: 18px;
  flex-grow: 1;
}

.task-meta-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-bottom: 22px;
}

.meta-tag {
  display: inline-flex;
  align-items: center;
  padding: 5px 12px;
  border-radius: 20px;
  background: var(--color-surface-subtle);
  border: 1px solid var(--color-border);
  color: var(--color-text-muted);
  font-size: 0.82rem;
  font-weight: 500;
}

.meta-tag i {
  color: var(--color-primary);
}

.status-pill {
  padding: 5px 12px;
  border-radius: 999px;
  color: var(--color-text-muted);
  background: var(--color-surface-subtle);
  border: 1px solid var(--color-border);
  font-size: 11px;
  font-weight: 700;
}

.status-pill.is-in-progress {
  color: var(--color-success);
  background: var(--color-success-soft);
  border-color: transparent;
}

.btn-task-action {
  min-height: 46px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  font-weight: 700;
  font-size: 0.95rem;
  background: var(--color-primary);
  border: 1px solid var(--color-primary);
  color: #fff;
  transition: all var(--motion-fast) ease;
}

.btn-task-action:hover {
  background: var(--color-primary-hover);
  border-color: var(--color-primary-hover);
  color: #fff;
  transform: translateY(-1px);
  box-shadow: 0 6px 18px rgba(75, 73, 172, 0.25);
}

@media (max-width: 992px) {
  .dashboard-grid {
    grid-template-columns: 1fr;
    gap: 22px;
  }
}

@media (max-width: 575.98px) {
  .panel {
    padding: 20px;
  }
  .task-illustration {
    height: 84px;
  }
}
</style>
