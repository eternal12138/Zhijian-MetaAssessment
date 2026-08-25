/**
 * 评分数据清洗与聚合工具
 *
 * 解决 CodedSegment.score 为 number | null 的类型安全问题：
 *   - 聚合计算前先过滤未评分片段
 *   - 提供统一的维度均值、综合分数计算
 */

import type { CodedSegment, DimensionScore, MetacognitionDimension } from '../types/assessment'
import { DIMENSION_LABELS } from '../types/assessment'

// ---- 类型守卫 ----

/** 已编码且有评分片段的"安全"类型 */
export type ScoredSegment = CodedSegment & {
  dimension: MetacognitionDimension
  score: number
}

/**
 * 判断片段是否已完成编码且评分非空
 */
export function isScored(seg: CodedSegment): seg is ScoredSegment {
  return seg.dimension !== null && seg.score !== null
}

/**
 * 过滤未评分 / 未编码的片段，返回类型安全的数组
 */
export function sanitizeSegments(segments: CodedSegment[]): ScoredSegment[] {
  return segments.filter(isScored)
}

// ---- 维度聚合 ----

interface DimensionGroup {
  dimension: MetacognitionDimension
  scores: number[]
}

/**
 * 按维度分组，计算每个维度的平均分
 *
 * @param segments  原始编码片段（含 null）
 * @param maxScore  量表满分，默认 7（Likert 1-7）
 * @returns 维度得分数组，未评分的维度不出现在结果中
 */
export function aggregateByDimension(
  segments: CodedSegment[],
  maxScore: number = 7
): DimensionScore[] {
  const scored = sanitizeSegments(segments)

  const groups = new Map<MetacognitionDimension, number[]>()
  for (const s of scored) {
    const list = groups.get(s.dimension) ?? []
    list.push(s.score)
    groups.set(s.dimension, list)
  }

  return Array.from(groups.entries()).map(([dim, scores]) => {
    const avg = roundTo(scores.reduce((a, b) => a + b, 0) / scores.length, 1)
    return {
      dimension: dim,
      label: DIMENSION_LABELS[dim] ?? dim,
      score: avg,
      max: maxScore
    }
  })
}

/**
 * 计算综合得分（各维度均值的算术平均）
 */
export function computeOverallScore(dimensions: DimensionScore[]): number {
  if (dimensions.length === 0) return 0
  const sum = dimensions.reduce((a, d) => a + d.score, 0)
  return roundTo(sum / dimensions.length, 1)
}

/**
 * 计算得分等级
 *
 * 等级划分（基于百分制换算）：
 *   >= 90 优秀 | >= 75 良好 | >= 60 发展中 | < 60 起步
 */
export function computeLevel(percentScore: number): string {
  if (percentScore >= 90) return '优秀'
  if (percentScore >= 75) return '良好'
  if (percentScore >= 60) return '发展中'
  return '起步'
}

/**
 * 将 Likert 1-7 的原始均分换算为百分制
 *
 * @param raw      原始均分（如 4.3）
 * @param maxScore 量表满分，默认 7
 */
export function toPercent(raw: number, maxScore: number = 7): number {
  return Math.round((raw / maxScore) * 100)
}

// ---- 班级聚合 ----

/** 班级维度聚合输入 */
export interface ClassAggregationInput {
  /** classGroup → 该班所有学生的编码片段 */
  segmentsByClass: Map<string, CodedSegment[]>
}

/**
 * 计算某个班级的维度均值
 *
 * @param segments   该班所有学生的编码片段
 * @param maxScore   量表满分
 */
export function computeClassDimensionAverages(
  segments: CodedSegment[],
  maxScore: number = 7
): DimensionScore[] {
  return aggregateByDimension(segments, maxScore)
}

// ---- 工具 ----

function roundTo(value: number, decimals: number): number {
  const factor = 10 ** decimals
  return Math.round(value * factor) / factor
}
