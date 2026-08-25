import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import type { AppRole } from '../stores/auth'
import { roleHome } from '../utils/roleNavigation'
import { isChunkLoadFailure } from './chunkRecovery'

// ---- 路由元信息类型 ----
declare module 'vue-router' {
  interface RouteMeta {
    /** 是否需要登录 */
    requiresAuth?: boolean
    /** 允许访问的角色列表；未设置表示所有已登录角色均可访问 */
    allowedRoles?: AppRole[]
    /** 侧边栏图标 */
    icon?: string
    /** 页面描述 */
    description?: string
    /** 页面标题 */
    title?: string
  }
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    // ---- 公开路由 ----
    {
      path: '/login',
      name: 'Login',
      component: () => import('../views/LoginView.vue'),
      meta: { title: '登录', requiresAuth: false }
    },
    {
      path: '/cosmos',
      name: 'Cosmos',
      component: () => import('../views/CosmosView.vue'),
      meta: { title: '太阳系模拟', requiresAuth: false }
    },

    // ---- 学生 & 教师 & 管理员共享 ----
    {
      path: '/',
      name: 'Dashboard',
      component: () => import('../views/DashboardView.vue'),
      meta: { title: '学习概览', icon: 'bi-grid-1x2-fill', requiresAuth: true }
    },
    {
      path: '/assessment',
      name: 'Assessment',
      component: () => import('../views/AssessmentView.vue'),
      meta: { title: '开始测评', icon: 'bi-chat-square-text-fill', description: '在真实问题解决情境中完成标准化出声思维测评。', requiresAuth: true, allowedRoles: ['student'] }
    },
    {
      path: '/report',
      name: 'Report',
      component: () => import('../views/ReportView.vue'),
      meta: { title: '我的报告', icon: 'bi-bar-chart-fill', description: '查看监控、控制/调试与评估三个维度的成长轨迹。', requiresAuth: true, allowedRoles: ['student'] }
    },
    {
      path: '/notifications',
      name: 'NotificationCenter',
      component: () => import('../views/NotificationCenterView.vue'),
      meta: { title: '消息中心', requiresAuth: true }
    },
    {
      path: '/account',
      name: 'Account',
      component: () => import('../views/AccountView.vue'),
      meta: { title: '个人信息与安全', requiresAuth: true }
    },
    {
      path: '/privacy',
      name: 'Privacy',
      component: () => import('../views/PrivacyView.vue'),
      meta: { title: '隐私与数据说明', requiresAuth: true }
    },
    {
      path: '/help',
      name: 'Help',
      component: () => import('../views/HelpView.vue'),
      meta: { title: '帮助与使用指南', requiresAuth: true }
    },

    // ---- 教师 & 管理员 ----
    {
      path: '/teacher',
      name: 'TeacherCenter',
      component: () => import('../views/TeacherCenterView.vue'),
      meta: { title: '教师中心', icon: 'bi-mortarboard-fill', description: '发布测评任务、跟进完成情况并查看班级聚合数据。', requiresAuth: true, allowedRoles: ['teacher', 'admin'] }
    },
    {
      path: '/review',
      name: 'CodingReview',
      component: () => import('../views/CodingReviewView.vue'),
      meta: { title: '双人盲编与仲裁', icon: 'bi-check2-square', description: '对人工确认候选进行独立盲编、一致生成共识、分歧交由第三方仲裁。', requiresAuth: true, allowedRoles: ['teacher', 'admin'] }
    },
    {
      path: '/candidate-review',
      name: 'CandidateReview',
      component: () => import('../views/CandidateReviewView.vue'),
      meta: { title: '候选片段复核', icon: 'bi-soundwave', description: '结合权威转录与原始录音复核 AI 高召回候选。', requiresAuth: true, allowedRoles: ['teacher', 'admin'] }
    },
    {
      path: '/ai-evaluation',
      name: 'AiEvaluation',
      component: () => import('../views/AiEvaluationView.vue'),
      meta: { title: 'AI 评估', icon: 'bi-stars', description: '使用管理员启用的生产模型，对复核候选执行元认知三分类。', requiresAuth: true, allowedRoles: ['teacher', 'admin'] }
    },
    {
      path: '/transcripts',
      name: 'TranscriptReview',
      component: () => import('../views/TranscriptReviewView.vue'),
      meta: { title: '权威转录校订', icon: 'bi-file-earmark-text-fill', description: '检查服务端 ASR 结果并保存人工校订版本。', requiresAuth: true, allowedRoles: ['teacher', 'admin'] }
    },

    // ---- 管理员专属 ----
    {
      path: '/users',
      name: 'UserManagement',
      component: () => import('../views/AdminView.vue'),
      meta: { title: '用户管理', icon: 'bi-people-fill', description: '创建、编辑、冻结用户账号。', requiresAuth: true, allowedRoles: ['admin'] }
    },
    {
      path: '/admin',
      name: 'Admin',
      component: () => import('../views/PromptManageView.vue'),
      meta: { title: '研究管理', icon: 'bi-sliders2-vertical', description: '系统提示词模板配置。', requiresAuth: true, allowedRoles: ['admin'] }
    },
    {
      path: '/data-management',
      name: 'DataManagement',
      component: () => import('../views/DialogueManageView.vue'),
      meta: { title: '数据管理', icon: 'bi-database-fill-gear', description: '按账号和测评时间管理录音、转录、问卷及完整记录。', requiresAuth: true, allowedRoles: ['admin'] }
    },
    {
      path: '/dialogue',
      redirect: '/data-management'
    },
    {
      path: '/model-services',
      name: 'ModelServices',
      component: () => import('../views/ModelServicesView.vue'),
      meta: { title: '模型服务状态', icon: 'bi-activity', description: '检查火山方舟、豆包语音、音频公网链路与额度信息。', requiresAuth: true, allowedRoles: ['admin'] }
    },
    {
      path: '/dialogue/:userId/:taskId',
      name: 'DialogueDetail',
      component: () => import('../views/DialogueDetailView.vue'),
      meta: { title: '对话详情', requiresAuth: true, allowedRoles: ['admin'] }
    },

    // ---- 兜底 ----
    { path: '/:pathMatch(.*)*', redirect: '/' }
  ]
})

// A browser tab opened before a production deployment can still reference an
// old hashed lazy-route chunk. In that case Vue Router cannot render the page
// until the user refreshes. Recover once automatically and preserve the exact
// destination; the per-target marker prevents an endless reload when the
// failure is caused by something other than a stale deployment.
const CHUNK_RECOVERY_KEY = 'mc-router-chunk-recovery'

router.onError((error, to) => {
  if (!isChunkLoadFailure(error)) return
  const target = to.fullPath || '/'
  if (sessionStorage.getItem(CHUNK_RECOVERY_KEY) === target) {
    sessionStorage.removeItem(CHUNK_RECOVERY_KEY)
    return
  }
  sessionStorage.setItem(CHUNK_RECOVERY_KEY, target)
  window.location.assign(target)
})

router.afterEach(() => {
  sessionStorage.removeItem(CHUNK_RECOVERY_KEY)
})

// ---- 全局前置守卫 ----
router.beforeEach((to, _from, next) => {
  const authStore = useAuthStore()

  // 本地持久化状态可能比访问令牌存活更久；令牌被拦截器清除后同步退出。
  const hasActiveSession = Boolean(localStorage.getItem('access_token'))
    || localStorage.getItem('offline_mode') === 'true'
  if (authStore.isLoggedIn && !hasActiveSession) {
    authStore.logout()
  }

  // 已登录访问登录页时回到当前身份的工作台。
  if (to.name === 'Login' && authStore.isLoggedIn) {
    return next(roleHome(authStore.userRole))
  }

  // 1) 无需登录 → 直接放行
  if (to.meta.requiresAuth === false) {
    return next()
  }

  // 2) 需要登录但未登录 → 踢到登录页
  if (to.meta.requiresAuth && !authStore.isLoggedIn) {
    return next({ name: 'Login', query: { redirect: to.fullPath } })
  }

  // 教师和管理员不进入学生学习概览，各身份回到自己的工作台。
  if (
    to.name === 'Dashboard'
    && authStore.userRole
    && authStore.userRole !== 'student'
  ) {
    return next(roleHome(authStore.userRole))
  }

  // 3) 角色白名单校验
  if (to.meta.allowedRoles && to.meta.allowedRoles.length > 0) {
    if (!authStore.userRole || !to.meta.allowedRoles.includes(authStore.userRole)) {
      // 角色不匹配 → 返回当前身份的工作台
      return next(roleHome(authStore.userRole))
    }
  }

  next()
})

export default router
