// ============================================================
// 元认知测评系统 - 核心类型定义
// 基于 Zepeda et al. (2023) 三维度元认知框架
// ============================================================

// -------------------- 元认知维度 --------------------

/** 元认知三维度：监控、控制/调试、评估 */
export type MetacognitionDimension = 'monitoring' | 'controlDebugging' | 'evaluation'

/** 维度中文标签映射 */
export const DIMENSION_LABELS: Record<MetacognitionDimension, string> = {
  monitoring: '监控',
  controlDebugging: '控制/调试',
  evaluation: '评估'
}

// -------------------- 量表体系 --------------------

/** 量表条目 - 原始自评视角 */
export interface ScaleItem {
  id: string
  dimension: MetacognitionDimension
  /** 原始量表条目文本（第一人称） */
  selfReportText: string
  /** 他评视角改写（第三人称，供 AI 观察评分使用） */
  observationText: string
  /** 特征关键词列表 */
  keywords: string[]
  /** Likert 量表范围 */
  scaleRange: [number, number]
  /** 评分细则 */
  scoringRubric: string
  /** 来源量表缩写（MAI/MSLQ/SMI/IMSR/言语报告法） */
  source: string
  /** 是否为反向题 */
  reversed: boolean
}

/** 量表维度组 */
export interface ScaleDimensionGroup {
  dimension: MetacognitionDimension
  label: string
  description: string
  items: ScaleItem[]
}

// -------------------- 测评任务 --------------------

/** 测评任务 - 教师端发布的问题解决任务 */
export interface AssessmentTask {
  id: string
  /** 任务标题，如“最优投球机判断” */
  title: string
  /** 学科领域 */
  subject: 'mathematics' | 'science' | 'language' | 'general'
  /** 任务描述 */
  description: string
  /** 问题情境详细说明 */
  scenario: string
  /** 预计完成时长（分钟） */
  estimatedMinutes: number
  /** 是否需要语音输入 */
  requiresVoice: boolean
  /** 任务状态 */
  status: 'draft' | 'published' | 'closed'
  /** 发布者ID */
  publisherId: string
  /** 发布时间 */
  publishedAt?: string
  /** 截止时间 */
  deadline?: string
  /** 关联的量表维度组 */
  dimensionGroups: ScaleDimensionGroup[]
  /** 启发式提问路径（引导AI提问的策略） */
  questionPaths: QuestionPath[]
}

/** 启发式提问路径 */
export interface QuestionPath {
  dimension: MetacognitionDimension
  /** 阶段：基础概念 → 深入应用 → 举一反三 */
  stage: 'basic' | 'deep' | 'transfer'
  /** 示例提问模板 */
  promptTemplate: string
  /** 触发条件关键词 */
  triggerKeywords: string[]
}

// -------------------- 对话与编码 --------------------

/** 对话角色 */
export type DialogueRole = 'agent' | 'user' | 'system'

/** 单条对话记录 */
export interface DialogueTurn {
  id: string
  sessionId: string
  role: DialogueRole
  /** 文本内容 */
  content: string
  /** 语音文件URL（如有） */
  audioUrl?: string
  /** 时间戳 */
  timestamp: number
  /** 语音情绪特征（多模态分析） */
  emotionFeatures?: EmotionFeatures
}

/** 语音情绪特征 */
export interface EmotionFeatures {
  /** 情绪类别 */
  emotion: 'neutral' | 'confident' | 'hesitant' | 'confused' | 'frustrated'
  /** 语速（字/分钟） */
  speechRate: number
  /** 停顿次数 */
  pauseCount: number
  /** 平均停顿时长（秒） */
  avgPauseDuration: number
  /** 语调变化幅度 */
  pitchVariation: number
}

/** AI 编码后的对话片段 - 对应项目书 JSON 输出结构 */
export interface CodedSegment {
  id: string
  sessionId: string
  /** 关联的原始对话轮次 */
  turnId: string
  /** 被试原话（Segment） */
  segment: string
  /** 映射的元认知维度（Dimension） */
  dimension: MetacognitionDimension | null
  /** 关联的量表条目ID */
  scaleItemId?: string
  /** Likert 评分 1-7 */
  score: number | null
  /** 编码理由（Reason） */
  reason: string
  /** AI 置信度 0-1 */
  confidence: number
  /** 编码时间 */
  codedAt: string
  /** 是否需要人工复核 */
  needsReview: boolean
  /** 人工复核评分（如有） */
  humanScore?: number
  /** 人工复核备注 */
  reviewNote?: string
}

// -------------------- 测评会话 --------------------

/** 会话状态 */
export type SessionStatus = 'preparation' | 'in_progress' | 'paused' | 'completed' | 'abandoned'

/** 测评会话 */
export interface AssessmentSession {
  id: string
  userId: string
  taskId: string
  status: SessionStatus
  /** 当前对话轮次 */
  dialogueHistory: DialogueTurn[]
  /** 已编码的片段 */
  codedSegments: CodedSegment[]
  /** 会话开始时间 */
  startTime: string
  /** 会话结束时间 */
  endTime?: string
  /** 实际耗时（分钟） */
  elapsedMinutes: number
  /** AI Agent 版本号 */
  aiAgentVersion: string
  /** 使用的模型标识 */
  modelId: string
  /** 模型超参数快照 */
  modelParams: ModelParams
}

/** 模型超参数 */
export interface ModelParams {
  temperature: number
  topP: number
  maxTokens: number
  /** 是否启用 CoT 思维链 */
  enableCoT: boolean
  /** 是否启用 RAG */
  enableRAG: boolean
}

// -------------------- 前端进度（简化版）--------------------

/** 前端展示用的测评进度 */
export interface AssessmentProgress {
  sessionId: string | null
  taskTitle: string
  status: 'not_started' | 'in_progress' | 'completed'
  currentStep: number
  totalSteps: number
  elapsedMinutes: number
}

// -------------------- 元认知画像 --------------------

/** 维度详细得分 */
export interface DimensionDetail {
  dimension: MetacognitionDimension
  label: string
  /** 原始得分 (1-7 或 0-100) */
  score: number
  /** 百分位排名 */
  percentile: number
  /** 得分解读 */
  interpretation: string
  /** 支持该评分的对话证据 */
  evidence: EvidenceItem[]
}

/** 对话证据条目 */
export interface EvidenceItem {
  segmentId: string
  /** 摘录的对话文本 */
  excerpt: string
  /** 关联的量表条目ID */
  scaleItemId: string
}

/** 维度得分（轻量版，用于图表展示） */
export interface DimensionScore {
  dimension: MetacognitionDimension
  label: string
  score: number
  /** 该维度的满分值，默认 100（如量表满分 5 则传 5，图表自动适配） */
  max?: number
}

/** 学习建议 */
export interface LearningSuggestion {
  id: string
  dimension: MetacognitionDimension
  title: string
  description: string
  /** 具体练习方法 */
  practices: string[]
  /** 难度等级 */
  difficulty: 'easy' | 'medium' | 'hard'
}

/** 元认知画像 - 测评完成后生成的完整报告 */
export interface MetacognitiveProfile {
  id: string
  userId: string
  sessionId: string
  generatedAt: string
  /** 综合得分 0-100 */
  overallScore: number
  /** 等级 */
  level: '优秀' | '良好' | '发展中' | '起步'
  /** 综合评语 */
  summary: string
  /** 各维度详情 */
  dimensions: DimensionDetail[]
  /** 优势维度 */
  strengths: string[]
  /** 薄弱环节 */
  weaknesses: string[]
  /** 个性化学习建议 */
  recommendations: LearningSuggestion[]
}

// -------------------- 测评报告（前端展示用）--------------------

/** 前端报告（轻量版） */
export interface AssessmentReport {
  id: string
  generatedAt: string
  overallScore: number
  level: string
  summary: string
  dimensions: DimensionScore[]
}

// -------------------- 人机一致性 --------------------

/** 人机一致性校验结果 */
export interface ConsistencyReport {
  id: string
  sessionId: string
  generatedAt: string
  /** 总体皮尔逊相关系数 */
  overallPearsonR: number
  /** 总体二次加权 Kappa */
  overallQWK: number
  /** 各维度一致性 */
  dimensions: DimensionConsistency[]
  /** 不一致片段列表 */
  discrepancies: DiscrepancyItem[]
}

/** 维度一致性 */
export interface DimensionConsistency {
  dimension: MetacognitionDimension
  label: string
  /** 该维度的 Cronbach's α */
  cronbachAlpha: number
  /** 该维度的人机皮尔逊 r */
  pearsonR: number
  /** 评分一致的片段数 */
  agreedCount: number
  /** 评分不一致的片段数 */
  disagreedCount: number
}

/** 不一致条目 */
export interface DiscrepancyItem {
  segmentId: string
  segment: string
  aiScore: number
  humanScore: number
  aiReason: string
  humanReason?: string
  /** 差异程度 */
  deviation: number
  /** 是否需要补充到 Few-shot 示例库 */
  shouldAddToFewShot: boolean
}

// -------------------- 用户与角色 --------------------

/** 用户角色 */
export type UserRole = 'student' | 'teacher' | 'admin'

/** 用户信息 */
export interface UserProfile {
  id: string
  name: string
  role: UserRole
  avatarText: string
  /** 所属班级（学生）或负责班级（教师） */
  classGroup?: string
}

// -------------------- 教师端 --------------------

/** 班级聚合数据 */
export interface ClassAggregation {
  classGroup: string
  studentCount: number
  completedCount: number
  /** 平均综合得分 */
  avgOverallScore: number
  /** 各维度班级平均分 */
  dimensionAverages: DimensionScore[]
  /** 得分分布 */
  scoreDistribution: ScoreDistribution
}

/** 得分分布 */
export interface ScoreDistribution {
  excellent: number   // 优秀 人数
  good: number        // 良好
  developing: number  // 发展中
  beginning: number   // 起步
}

/** 学生完成情况 */
export interface StudentCompletion {
  userId: string
  studentName: string
  taskId: string
  taskTitle: string
  status: SessionStatus
  overallScore?: number
  completedAt?: string
  elapsedMinutes: number
}

// -------------------- 管理端 --------------------

/** AI 评分规则版本 */
export interface ScoringRuleVersion {
  id: string
  version: string
  /** System Prompt 内容 */
  systemPrompt: string
  /** Few-shot 示例列表 */
  fewShotExamples: FewShotExample[]
  /** 创建时间 */
  createdAt: string
  /** 是否激活 */
  isActive: boolean
  /** 该版本的一致性表现 */
  consistency?: ConsistencyReport
}

/** Few-shot 示例 */
export interface FewShotExample {
  id: string
  /** 场景描述 */
  scenario: string
  /** 对话片段 */
  dialogue: string
  /** AI 编码结果 */
  coding: CodedSegment
  /** CoT 思维链推理过程 */
  chainOfThought: string
  /** 质量等级 */
  quality: 'excellent' | 'good' | 'developing' | 'beginning'
}

// -------------------- API 通用 --------------------

/** 分页参数 */
export interface PaginationParams {
  page: number
  pageSize: number
}

/** 分页响应 */
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  pageSize: number
  totalPages: number
}

/** API 通用响应包装 */
export interface ApiResponse<T> {
  code: number
  message: string
  data: T
}
