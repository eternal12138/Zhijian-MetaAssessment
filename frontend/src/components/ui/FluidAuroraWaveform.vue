<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

type WaveformStatus = 'idle' | 'recording' | 'quiet' | 'warning'

const props = withDefaults(defineProps<{
  audioLevel: number
  frequencyData: Uint8Array
  status: WaveformStatus
  height?: number
}>(), {
  height: 56
})

const canvasRef = ref<HTMLCanvasElement | null>(null)
const accessibleLabel = computed(() => ({
  idle: '麦克风波形尚未开始',
  recording: '正在检测到语音输入',
  quiet: '当前输入声音偏小',
  warning: '接近静默提醒时间'
}[props.status]))

let context: CanvasRenderingContext2D | null = null
let bufferCanvas: HTMLCanvasElement | null = null
let bufferContext: CanvasRenderingContext2D | null = null
let resizeObserver: ResizeObserver | null = null
let themeObserver: MutationObserver | null = null
let animationFrameId = 0
let canvasWidth = 0
let canvasHeight = 0
let phase = 0
let previousFrameAt = 0
let reduceMotion = false
let visible = true
let motionMedia: MediaQueryList | null = null

function colorSet() {
  if (props.status === 'warning') {
    return { primary: [245, 166, 35], secondary: [255, 211, 104], glow: [245, 166, 35] }
  }
  if (props.status === 'quiet' || props.status === 'idle') {
    return { primary: [86, 99, 178], secondary: [91, 136, 198], glow: [91, 115, 210] }
  }
  return { primary: [122, 118, 248], secondary: [62, 230, 200], glow: [92, 180, 255] }
}

function bandEnergy(fromRatio: number, toRatio: number) {
  const data = props.frequencyData
  if (!data.length) return 0
  const start = Math.max(0, Math.floor(data.length * fromRatio))
  const end = Math.max(start + 1, Math.min(data.length, Math.ceil(data.length * toRatio)))
  let sum = 0
  for (let index = start; index < end; index += 1) sum += data[index] ?? 0
  return sum / Math.max(1, end - start) / 255
}

function rgba(color: number[], opacity: number) {
  return `rgba(${color[0]}, ${color[1]}, ${color[2]}, ${opacity})`
}

function drawWave(
  ctx: CanvasRenderingContext2D,
  centerY: number,
  amplitude: number,
  frequency: number,
  phaseOffset: number,
  opacity: number,
  lineWidth: number,
  colors: ReturnType<typeof colorSet>
) {
  const gradient = ctx.createLinearGradient(0, 0, canvasWidth, 0)
  gradient.addColorStop(0, rgba(colors.primary, 0))
  gradient.addColorStop(.18, rgba(colors.primary, opacity))
  gradient.addColorStop(.58, rgba(colors.secondary, opacity))
  gradient.addColorStop(1, rgba(colors.secondary, 0))
  ctx.beginPath()
  const segmentWidth = Math.max(12, canvasWidth / 28)
  let previousX = 0
  let previousY = centerY
  ctx.moveTo(previousX, previousY)
  for (let x = segmentWidth; x <= canvasWidth + segmentWidth; x += segmentWidth) {
    const normalizedX = x / Math.max(1, canvasWidth)
    const taper = Math.sin(Math.PI * Math.min(1, normalizedX)) ** .72
    const harmonic = Math.sin(normalizedX * Math.PI * frequency + phase + phaseOffset)
    const detail = Math.sin(normalizedX * Math.PI * (frequency * 2.15) - phase * .64 + phaseOffset) * .22
    const y = centerY + (harmonic + detail) * amplitude * taper
    const controlX = (previousX + x) / 2
    ctx.bezierCurveTo(controlX, previousY, controlX, y, x, y)
    previousX = x
    previousY = y
  }
  ctx.strokeStyle = gradient
  ctx.lineWidth = lineWidth
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  ctx.stroke()
}

function renderFrame() {
  if (!context || !bufferContext || !bufferCanvas || canvasWidth <= 0 || canvasHeight <= 0) return
  const ctx = bufferContext
  ctx.clearRect(0, 0, canvasWidth, canvasHeight)
  const colors = colorSet()
  const low = bandEnergy(.01, .12)
  const mid = bandEnergy(.12, .42)
  const high = bandEnergy(.42, .86)
  const signal = Math.max(0, Math.min(1, props.audioLevel * .7 + low * .42 + mid * .18))
  const idleAmplitude = props.status === 'idle' ? 1.5 : 2.2
  const amplitude = idleAmplitude + signal * canvasHeight * .31
  const centerY = canvasHeight / 2
  const warningPulse = props.status === 'warning'
    ? .8 + Math.sin(phase * .72) * .18
    : 1

  ctx.save()
  ctx.globalCompositeOperation = 'lighter'
  ctx.shadowColor = rgba(colors.glow, .5)
  ctx.shadowBlur = 14
  drawWave(ctx, centerY + 2, amplitude * .72, 4.2 + high * 2, .5, .22 * warningPulse, 8, colors)
  ctx.shadowBlur = 7
  drawWave(ctx, centerY - 1, amplitude, 5.4 + high * 2.8, 0, .74 * warningPulse, 2.3, colors)
  ctx.shadowBlur = 4
  drawWave(ctx, centerY + 1, amplitude * .58, 7.2 + mid * 2.2, 1.7, .48, 1.25, colors)
  ctx.restore()

  context.clearRect(0, 0, canvasWidth, canvasHeight)
  context.drawImage(bufferCanvas, 0, 0, canvasWidth, canvasHeight)
}

function scheduleFrame(now: number) {
  if (!visible) {
    animationFrameId = requestAnimationFrame(scheduleFrame)
    return
  }
  const lowPowerDevice = (navigator.hardwareConcurrency || 8) <= 4
  const targetFps = reduceMotion ? 12 : lowPowerDevice ? 30 : 60
  const interval = 1000 / targetFps
  if (now - previousFrameAt >= interval) {
    if (!reduceMotion && props.status !== 'idle') phase += (now - previousFrameAt) * .0022
    previousFrameAt = now
    renderFrame()
  }
  animationFrameId = requestAnimationFrame(scheduleFrame)
}

function resize() {
  const canvas = canvasRef.value
  if (!canvas) return
  const rect = canvas.getBoundingClientRect()
  const ratio = Math.min(2, window.devicePixelRatio || 1)
  canvasWidth = Math.max(1, Math.round(rect.width))
  canvasHeight = Math.max(1, Math.round(props.height))
  canvas.width = Math.round(canvasWidth * ratio)
  canvas.height = Math.round(canvasHeight * ratio)
  context = canvas.getContext('2d')
  context?.setTransform(ratio, 0, 0, ratio, 0, 0)
  bufferCanvas ??= document.createElement('canvas')
  bufferCanvas.width = Math.round(canvasWidth * ratio)
  bufferCanvas.height = Math.round(canvasHeight * ratio)
  bufferContext = bufferCanvas.getContext('2d')
  bufferContext?.setTransform(ratio, 0, 0, ratio, 0, 0)
  renderFrame()
}

function handleMotionPreference(event: MediaQueryListEvent | MediaQueryList) {
  reduceMotion = event.matches
  phase = 0
  renderFrame()
}

function handleVisibility() {
  visible = document.visibilityState === 'visible'
  previousFrameAt = performance.now()
}

watch(() => [props.status, props.height], () => {
  if (props.height !== canvasHeight) resize()
  else renderFrame()
})

onMounted(() => {
  motionMedia = window.matchMedia('(prefers-reduced-motion: reduce)')
  handleMotionPreference(motionMedia)
  motionMedia.addEventListener('change', handleMotionPreference)
  resizeObserver = new ResizeObserver(resize)
  if (canvasRef.value) resizeObserver.observe(canvasRef.value)
  themeObserver = new MutationObserver(renderFrame)
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  document.addEventListener('visibilitychange', handleVisibility)
  resize()
  animationFrameId = requestAnimationFrame(scheduleFrame)
})

onBeforeUnmount(() => {
  cancelAnimationFrame(animationFrameId)
  resizeObserver?.disconnect()
  themeObserver?.disconnect()
  motionMedia?.removeEventListener('change', handleMotionPreference)
  document.removeEventListener('visibilitychange', handleVisibility)
})
</script>

<template>
  <div class="aurora-waveform" :class="`is-${status}`" :style="{ height: `${props.height}px` }">
    <canvas
      ref="canvasRef"
      :height="props.height"
      role="img"
      :aria-label="accessibleLabel"
    />
    <span class="aurora-waveform-center" aria-hidden="true" />
  </div>
</template>

<style scoped>
.aurora-waveform {
  position: relative;
  width: 100%;
  min-width: 0;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--color-primary) 18%, var(--color-border));
  border-radius: var(--radius-md);
  background:
    radial-gradient(ellipse at 50% 100%, rgba(92, 180, 255, .1), transparent 62%),
    color-mix(in srgb, var(--color-surface-subtle) 82%, transparent);
}
.aurora-waveform canvas { display: block; width: 100%; height: 100%; }
.aurora-waveform-center {
  position: absolute;
  inset: 50% 8% auto;
  height: 1px;
  pointer-events: none;
  background: linear-gradient(to right, transparent, color-mix(in srgb, var(--color-primary) 18%, transparent), transparent);
  opacity: .6;
  transform: translateY(-50%);
}
.aurora-waveform.is-warning {
  border-color: color-mix(in srgb, var(--color-warning) 38%, var(--color-border));
  background: color-mix(in srgb, var(--color-warning-soft) 58%, transparent);
}
@media (prefers-reduced-motion: reduce) {
  .aurora-waveform { box-shadow: none; }
}
</style>
