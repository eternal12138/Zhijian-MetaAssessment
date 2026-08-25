<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import RadarChart from '../components/charts/RadarChart.vue'
import StatCard from '../components/dashboard/StatCard.vue'
import PlanetOrbitHero from '../components/dashboard/PlanetOrbitHero.vue'
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

      <section class="dashboard-grid">
        <article class="panel profile-panel">
          <div class="panel-head"><div><p class="panel-kicker">最近一次测评</p><h2>我的元认知画像</h2></div><RouterLink to="/report">查看报告 <i class="bi bi-arrow-up-right"></i></RouterLink></div>
          <div v-if="report" class="radar-wrap"><RadarChart :scores="report.dimensions" :show-norm="false" /><div class="score-note"><span>综合表现</span><strong>{{ report.level }}</strong><p>{{ report.summary }}</p></div></div>
          <div v-else class="text-center text-muted py-5">报告经研究复核并正式发布后将在这里显示。</div>
        </article>
        <article class="panel task-panel">
          <div class="panel-head"><div><p class="panel-kicker">待完成</p><h2>下一项任务</h2></div><span class="status-pill">{{ assessmentInProgress ? '进行中' : '待开始' }}</span></div>
          <div class="task-illustration"><i class="bi bi-calculator"></i><span class="ball ball-a"></span><span class="ball ball-b"></span></div>
          <h3>{{ nextTask?.title ?? '标准问题解决任务' }}</h3>
          <p>{{ nextTask?.description ?? '按照标准指导语完成任务，并持续说出你的思考过程。' }}</p>
          <div class="task-meta"><span><i class="bi bi-clock"></i> 约 {{ nextTask?.estimated_minutes ?? 12 }} 分钟</span><span><i class="bi bi-mic"></i> 需要语音</span></div>
          <RouterLink to="/assessment" class="btn btn-outline-primary w-100 mt-3">进入任务</RouterLink>
        </article>
      </section>
    </div>
  </div>
</template>
