<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { RadarChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'
import { RadarComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { use } from 'echarts/core'
import type { DimensionScore } from '../../types/assessment'
import { useTheme } from '../../composables/useTheme'
import { radarLayout, radarAxisLabel, escapeChartText } from './radarLayout'

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
  displayAsPercentage?: boolean
}>(), {
  name: '本次测评',
  comparisonName: '对比测评',
  height: 320,
  showNorm: false,
  normReference: '',
  globalMax: 100,
  valueUnit: '',
  displayAsPercentage: false
})

const emit = defineEmits<{
  (e: 'select-dimension', dimension: { dimension: string; label: string; score: number }): void
}>()

const chartRef = ref<HTMLDivElement | null>(null)
const chartError = ref('')
let chart: echarts.ECharts | undefined
const { theme } = useTheme()
const legendItems = ref<Array<{ name: string; color: string; dashed: boolean }>>([])
const hiddenSeries = ref<string[]>([])
let resizeObserver: ResizeObserver | undefined
let frame = 0

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

function scheduleRender() {
  if (frame) cancelAnimationFrame(frame)
  frame = requestAnimationFrame(() => {
    frame = 0
    chart?.resize()
    renderChart()
  })
}

function toggleSeries(name: string) {
  hiddenSeries.value = hiddenSeries.value.includes(name)
    ? hiddenSeries.value.filter(item => item !== name) : [...hiddenSeries.value, name]
  chart?.dispatchAction({ type: 'legendToggleSelect', name })
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

    // Explicit app preference wins over the operating system's color scheme.
    const dark = theme.value === 'dark'
    const styles = getComputedStyle(chartRef.value)
    const token = (name: string, fallback: string) => styles.getPropertyValue(name).trim() || fallback
    const surface = token('--color-surface', dark ? '#1a1b26' : '#ffffff')
    const subtle = token('--color-surface-subtle', dark ? '#222434' : '#f8f8fc')
    const border = token('--color-border', dark ? '#2e3146' : '#e6e7ef')
    const text = token('--color-text', dark ? '#f1f3f9' : '#25253d')
    const muted = token('--color-text-muted', dark ? '#9ca0ba' : '#6b6c82')
    const primary = token('--color-primary', dark ? '#7d7bf2' : '#4b49ac')
    const layout = radarLayout(chartRef.value.clientWidth, chartRef.value.clientHeight, indicators.value.length)
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
        color: primary,
        width: 3
      },
      itemStyle: {
        color: primary
      }
    }
    ]

    const comparisonColors = dark
      ? ['#34c38f', '#22d3ee', '#f59e0b', '#ec4899']
      : ['#218c68', '#0891b2', '#d97706', '#db2777']
    const legends = [{ name: props.name, color: primary, dashed: false }]
    validComparisons.forEach((item, index) => {
      const color = item.color || comparisonColors[index % comparisonColors.length]
      legends.push({ name: item.name, color, dashed: item.dashed !== false })
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
    legendItems.value = hasComparison ? legends : []
    hiddenSeries.value = hiddenSeries.value.filter(name => legends.some(item => item.name === name))

    const option: echarts.EChartsCoreOption = {
    backgroundColor: 'transparent',
    animation: false,
    legend: {
      show: false,
      data: legends.map(item => item.name),
      selected: Object.fromEntries(legends.map(item => [item.name, !hiddenSeries.value.includes(item.name)]))
    },
    tooltip: {
      trigger: 'item',
      confine: true,
      backgroundColor: surface,
      borderColor: border,
      extraCssText: 'max-width: min(320px, calc(100vw - 48px)); white-space: normal; overflow-wrap: anywhere;',
      textStyle: {
        color: text,
        fontSize: 13
      },
      formatter: (params: any) => {
        const seriesName = escapeChartText(params.name || props.name)
        let html = `<div style="font-weight:700;margin-bottom:6px;border-bottom:1px solid ${dark ? '#3c3e5a' : '#edf0f5'};padding-bottom:4px">${seriesName}</div>`
        dims.forEach((d, i) => {
          const val = params.value?.[i] ?? 0
          const pct = d.max > 0 ? Math.round((val / d.max) * 100) : 0
          const displayValue = props.displayAsPercentage
            ? `${(Number(val) * 100).toFixed(1)}%`
            : `${typeof val === 'number' ? val.toFixed(1) : val}${props.valueUnit || ` / ${d.max} (${pct}%)`}`
          html += `<div style="display:flex;justify-content:space-between;gap:16px;margin:3px 0;">
            <span>${escapeChartText(d.name)}:</span>
            <strong>${displayValue}</strong>
          </div>`
        })
        if (props.showNorm && props.normReference) {
          html += `<div style="margin-top:6px;font-size:12px;color:${muted}">常模：${escapeChartText(props.normReference)}</div>`
        }
        return html
      }
    },
    radar: {
      indicator: dims,
      radius: layout.radius,
      center: layout.center,
      axisNameGap: 10,
      splitNumber: 4,
      axisName: {
        color: muted,
        fontSize: 13,
        fontWeight: 600,
        formatter: radarAxisLabel,
        width: layout.labelWidth,
        overflow: 'break',
        align: 'center',
        lineHeight: 19,
        borderRadius: 4,
        padding: [2, 4]
      },
      splitArea: {
        areaStyle: {
          color: [surface, subtle]
        }
      },
      axisLine: {
        lineStyle: {
          color: border
        }
      },
      splitLine: {
        lineStyle: {
          color: border
        }
      }
    },
    series: [{
      type: 'radar',
      data: seriesData
    }]
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

onMounted(() => {
  renderChart()
  // Sidebar collapse, container queries and card expansion also change width.
  resizeObserver = new ResizeObserver(scheduleRender)
  if (chartRef.value) resizeObserver.observe(chartRef.value)
  window.addEventListener('resize', scheduleRender)
})

watch(theme, scheduleRender, { flush: 'post' })

watch(
  () => [
    props.scores,
    props.name,
    props.comparisonScores,
    props.comparisonName,
    props.comparisonSeries,
    props.globalMax,
    props.valueUnit,
    props.displayAsPercentage,
    props.height,
    props.showNorm,
    props.normReference
  ],
  scheduleRender,
  { deep: true, flush: 'post' }
)

onBeforeUnmount(() => {
  window.removeEventListener('resize', scheduleRender)
  resizeObserver?.disconnect()
  if (frame) cancelAnimationFrame(frame)
  chart?.dispose()
})
</script>

<template>
  <div class="radar-chart-wrapper">
    <div ref="chartRef" class="radar-chart" :class="{ 'has-error': chartError }" :style="{ height: `${height}px` }" />
    <div v-if="chartError" class="radar-chart-error"><i class="bi bi-bar-chart-line" /><span>{{ chartError }}</span></div>
    <ul v-else-if="legendItems.length" class="radar-legend" aria-label="雷达图对比图例">
      <li v-for="item in legendItems" :key="item.name">
        <button type="button" :aria-pressed="!hiddenSeries.includes(item.name)" @click="toggleSeries(item.name)">
          <span class="legend-line" :class="{ dashed: item.dashed }" :style="{ borderColor: item.color }" />
          <span>{{ item.name }}</span>
        </button>
      </li>
    </ul>
    <div v-if="showNorm && normReference" class="radar-norm-note">
      <i class="bi bi-info-circle"></i>
      <span>常模参照：{{ normReference }}</span>
    </div>
  </div>
</template>

<style scoped>
.radar-chart-wrapper {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
  min-width: 0;
  max-width: 100%;
}
.radar-chart {
  width: 100%;
  min-width: 0;
}
.radar-chart.has-error { visibility: hidden; }
.radar-chart-error {
  position: absolute;
  inset: 0;
  min-height: 180px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: .5rem;
  color: var(--color-text-muted);
  text-align: center;
}
.radar-legend { display: flex; flex-wrap: wrap; justify-content: center; gap: .4rem .75rem; list-style: none; padding: 0; margin: .25rem 0 0; width: 100%; }
.radar-legend li { min-width: 0; max-width: 100%; }
.radar-legend button { display: flex; align-items: center; gap: .5rem; max-width: 100%; min-height: 36px; padding: .35rem .55rem; border: 1px solid var(--color-border); border-radius: var(--radius-sm); background: var(--color-surface); color: var(--color-text); font-size: .82rem; text-align: left; overflow-wrap: anywhere; }
.radar-legend button[aria-pressed="false"] { color: var(--color-text-muted); text-decoration: line-through; }
.radar-legend button:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.legend-line { flex: 0 0 20px; border-top: 3px solid; }
.legend-line.dashed { border-top-style: dashed; }
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
