<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { RadarChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'
import { RadarComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { use } from 'echarts/core'
import type { DimensionScore } from '../../types/assessment'

use([RadarChart, CanvasRenderer, RadarComponent, TooltipComponent, LegendComponent])

interface RadarComparisonSeries {
  name: string
  scores: DimensionScore[]
  color?: string
  dashed?: boolean
}

const props = withDefaults(defineProps<{
  scores: DimensionScore[]
  name?: string
  comparisonScores?: DimensionScore[]
  comparisonName?: string
  comparisonSeries?: RadarComparisonSeries[]
  height?: number
  showNorm?: boolean
  normReference?: string
  globalMax?: number
  valueUnit?: string
}>(), {
  name: '本次测评',
  comparisonName: '对比测评',
  height: 320,
  showNorm: false,
  normReference: '',
  globalMax: 100,
  valueUnit: ''
})

const emit = defineEmits<{
  (e: 'select-dimension', dimension: { dimension: string; label: string; score: number }): void
}>()

const chartRef = ref<HTMLDivElement | null>(null)
const chartError = ref('')
let chart: echarts.ECharts | undefined

const indicators = computed(() =>
  props.scores
    .filter(item => item && typeof item.label === 'string' && Number.isFinite(Number(item.score)))
    .map(({ label, max }) => ({
      name: label,
      max: Number.isFinite(Number(max)) && Number(max) > 0
        ? Number(max)
        : props.globalMax ?? 100
    }))
)

function isDarkMode(): boolean {
  if (typeof document === 'undefined') return false
  return document.documentElement.getAttribute('data-theme') === 'dark'
    || window.matchMedia?.('(prefers-color-scheme: dark)').matches
}

function renderChart() {
  if (!chartRef.value) return
  chartError.value = ''
  const validScores = props.scores.filter(item => item && Number.isFinite(Number(item.score)))
  if (validScores.length < 3 || indicators.value.length !== validScores.length) {
    chart?.clear()
    chartError.value = '当前数据不足以绘制三维雷达图'
    return
  }
  const comparisonInputs: RadarComparisonSeries[] = []
  if (props.comparisonScores?.length) {
    comparisonInputs.push({
      name: props.comparisonName,
      scores: props.comparisonScores,
      dashed: true
    })
  }
  comparisonInputs.push(...(props.comparisonSeries ?? []))
  const validComparisons = comparisonInputs
    .map(item => ({
      ...item,
      scores: item.scores.filter(score => score && Number.isFinite(Number(score.score)))
    }))
    .filter(item => item.scores.length === validScores.length)
  const hasComparison = validComparisons.length > 0

  try {
    chart ??= echarts.init(chartRef.value)

    const dark = isDarkMode()
    const dims = indicators.value.map(item => ({ ...item }))
    const primaryValues = validScores.map(({ score }) => Number(score))
    const seriesData: any[] = [
    {
      value: primaryValues,
      name: props.name,
      areaStyle: {
        color: dark ? 'rgba(117, 115, 231, 0.28)' : 'rgba(75, 73, 172, 0.18)'
      },
      lineStyle: {
        color: dark ? '#7573e7' : '#4b49ac',
        width: 3
      },
      itemStyle: {
        color: dark ? '#7573e7' : '#4b49ac'
      }
    }
    ]

    const comparisonColors = dark
      ? ['#34c38f', '#22d3ee', '#f59e0b', '#ec4899']
      : ['#218c68', '#0891b2', '#d97706', '#db2777']
    validComparisons.forEach((item, index) => {
      const color = item.color || comparisonColors[index % comparisonColors.length]
      seriesData.push({
        value: item.scores.map(({ score }) => Number(score)),
        name: item.name,
        areaStyle: { color: `${color}20` },
        lineStyle: {
          color,
          width: 2,
          type: item.dashed === false ? 'solid' : 'dashed'
        },
        itemStyle: { color }
      })
    })

    const option: echarts.EChartsCoreOption = {
    tooltip: {
      trigger: 'item',
      backgroundColor: dark ? '#242537' : '#ffffff',
      borderColor: dark ? '#3c3e5a' : '#e6e7ef',
      textStyle: {
        color: dark ? '#f0f1f8' : '#25253d',
        fontSize: 12
      },
      formatter: (params: any) => {
        const seriesName = params.seriesName || params.name
        let html = `<div style="font-weight:700;margin-bottom:6px;border-bottom:1px solid ${dark ? '#3c3e5a' : '#edf0f5'};padding-bottom:4px">${seriesName}</div>`
        dims.forEach((d, i) => {
          const val = params.value?.[i] ?? 0
          const pct = d.max > 0 ? Math.round((val / d.max) * 100) : 0
          html += `<div style="display:flex;justify-content:space-between;gap:16px;margin:3px 0;">
            <span>${d.name}:</span>
            <strong>${typeof val === 'number' ? val.toFixed(1) : val}${props.valueUnit || ` / ${d.max} (${pct}%)`}</strong>
          </div>`
        })
        if (props.showNorm && props.normReference) {
          html += `<div style="margin-top:6px;font-size:11px;color:${dark ? '#8284a6' : '#83839d'}">常模：${props.normReference}</div>`
        }
        return html
      }
    },
    radar: {
      indicator: dims,
      radius: hasComparison ? '62%' : '68%',
      splitNumber: 4,
      axisName: {
        color: dark ? '#abadd0' : '#55566c',
        fontSize: 12,
        fontWeight: 600,
        borderRadius: 4,
        padding: [2, 4]
      },
      splitArea: {
        areaStyle: {
          color: dark
            ? ['#1c1d29', '#242537']
            : ['#ffffff', '#f8f8fc']
        }
      },
      axisLine: {
        lineStyle: {
          color: dark ? '#2b2d42' : '#e6e7ef'
        }
      },
      splitLine: {
        lineStyle: {
          color: dark ? '#2b2d42' : '#e6e7ef'
        }
      }
    },
    series: [{
      type: 'radar',
      data: seriesData
    }]
    }
    if (hasComparison) {
      option.legend = {
        show: true,
        bottom: 0,
        textStyle: {
          color: dark ? '#abadd0' : '#66687d',
          fontSize: 12
        }
      }
    }

    chart.clear()
    chart.setOption(option, { notMerge: true })

  // 绑定点击事件，向外派发维度信息
    chart.off('click')
    chart.on('click', (params: any) => {
      if (params.componentType === 'radar' || params.seriesType === 'radar') {
        const idx = params.dataIndex ?? 0
        const d = validScores[idx]
        if (d) {
          emit('select-dimension', {
            dimension: d.dimension,
            label: d.label,
            score: d.score
          })
        }
      }
    })
  } catch (error) {
    console.error('[RadarChart] render failed:', error)
    chart?.dispose()
    chart = undefined
    chartError.value = '图表引擎暂时无法渲染，分数明细仍可正常查看'
  }
}

function resize() {
  chart?.resize()
}

onMounted(() => {
  renderChart()
  window.addEventListener('resize', resize)
})

watch(
  () => [
    props.scores,
    props.name,
    props.comparisonScores,
    props.comparisonName,
    props.comparisonSeries,
    props.globalMax,
    props.valueUnit
  ],
  renderChart,
  { deep: true }
)

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
})
</script>

<template>
  <div class="radar-chart-wrapper">
    <div ref="chartRef" class="radar-chart" :class="{ 'has-error': chartError }" :style="{ height: `${height}px` }" />
    <div v-if="chartError" class="radar-chart-error"><i class="bi bi-bar-chart-line" /><span>{{ chartError }}</span></div>
    <div v-if="showNorm && normReference" class="radar-norm-note">
      <i class="bi bi-info-circle"></i>
      <span>常模参照：{{ normReference }}</span>
    </div>
  </div>
</template>

<style scoped>
.radar-chart-wrapper {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
}
.radar-chart {
  width: 100%;
}
.radar-chart.has-error { visibility: hidden; }
.radar-chart-error {
  position: absolute;
  min-height: 180px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: .5rem;
  color: var(--color-text-muted);
  text-align: center;
}
.radar-chart-error i { color: var(--color-primary); font-size: 2rem; }
.radar-norm-note {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
  padding: 5px 14px;
  border-radius: var(--radius-sm);
  background: var(--color-surface-subtle);
  color: var(--color-text-muted);
  font-size: 11px;
}
.radar-norm-note i {
  color: var(--color-primary);
  font-size: 13px;
}
</style>
