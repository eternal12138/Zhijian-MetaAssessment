<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import WaveSurfer from 'wavesurfer.js'
import RecordPlugin from 'wavesurfer.js/dist/plugins/record.esm.js'

const props = withDefaults(defineProps<{
  stream: MediaStream | null
  active?: boolean
  status?: 'idle' | 'recording' | 'quiet' | 'warning'
  height?: number
}>(), {
  active: false,
  status: 'idle',
  height: 66
})

const container = ref<HTMLElement | null>(null)
const renderError = ref('')
let wavesurfer: WaveSurfer | null = null
let record: RecordPlugin | null = null
let micHandle: ReturnType<RecordPlugin['renderMicStream']> | null = null
let themeObserver: MutationObserver | null = null
let motionMedia: MediaQueryList | null = null
let reduceMotion = false
let flowPhase = 0
let previousRenderAt = 0

function color(variable: string, fallback: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(variable).trim() || fallback
}

function waveformColors() {
  return {
    waveColor: color('--color-primary-soft', 'rgba(99, 102, 241, .28)'),
    progressColor: color('--color-primary', '#5753c9'),
    cursorColor: 'transparent'
  }
}

function auroraPalette() {
  if (props.status === 'warning') {
    return { start: '#f5a623', middle: '#ffd368', end: '#ff8a5b', glow: 'rgba(245, 166, 35, .55)' }
  }
  if (props.status === 'quiet') {
    return { start: '#5863b2', middle: '#5b88c6', end: '#7a76f8', glow: 'rgba(91, 115, 210, .42)' }
  }
  return { start: '#7a76f8', middle: '#3ee6c8', end: '#5cb4ff', glow: 'rgba(92, 180, 255, .58)' }
}

function smoothedEnvelope(samples: Float32Array | number[], targetLength: number) {
  const result = new Float32Array(targetLength)
  if (!samples.length) return result
  const scale = samples.length / targetLength
  let previous = 0
  for (let index = 0; index < targetLength; index += 1) {
    const from = Math.floor(index * scale)
    const to = Math.max(from + 1, Math.min(samples.length, Math.ceil((index + 1) * scale)))
    let peak = 0
    for (let sample = from; sample < to; sample += 1) peak = Math.max(peak, Math.abs(samples[sample] ?? 0))
    previous = previous * .66 + peak * .34
    result[index] = previous
  }
  return result
}

function drawFluidLayer(
  ctx: CanvasRenderingContext2D,
  values: Float32Array,
  centerY: number,
  amplitudeScale: number,
  frequency: number,
  phaseOffset: number,
  detailStrength: number
) {
  const step = ctx.canvas.width / Math.max(1, values.length - 1)
  ctx.beginPath()
  let previousX = 0
  const firstAmplitude = Math.max(1.25, values[0] * amplitudeScale)
  let previousY = centerY + Math.sin(flowPhase + phaseOffset) * firstAmplitude
  ctx.moveTo(previousX, previousY)
  for (let index = 1; index < values.length; index += 1) {
    const x = index * step
    const normalizedX = index / Math.max(1, values.length - 1)
    const taper = Math.sin(Math.PI * normalizedX) ** .58
    const localAmplitude = (1.25 + values[index] * amplitudeScale) * (.28 + taper * .72)
    const harmonic = Math.sin(normalizedX * Math.PI * frequency + flowPhase + phaseOffset)
    const detail = Math.sin(
      normalizedX * Math.PI * frequency * 2.15 - flowPhase * .64 + phaseOffset
    ) * detailStrength
    const y = centerY + (harmonic + detail) * localAmplitude
    const controlX = (previousX + x) / 2
    ctx.bezierCurveTo(controlX, previousY, controlX, y, x, y)
    previousX = x
    previousY = y
  }
}

function renderAuroraWaveform(
  peaks: Array<Float32Array | number[]>,
  ctx: CanvasRenderingContext2D
) {
  const samples = peaks[0]
  const width = ctx.canvas.width
  const height = ctx.canvas.height
  if (!samples?.length || width <= 0 || height <= 0) return

  const palette = auroraPalette()
  const pointCount = Math.max(36, Math.min(180, Math.round(width / 7)))
  const envelope = smoothedEnvelope(samples, pointCount)
  const centerY = height / 2
  const amplitudeScale = height * .37
  const now = performance.now()
  const elapsed = previousRenderAt ? Math.min(48, now - previousRenderAt) : 16
  previousRenderAt = now
  if (!reduceMotion && props.active) flowPhase += elapsed * .0022
  const warningPulse = props.status === 'warning'
    ? .82 + Math.sin(flowPhase * .72) * .18
    : 1
  const lineGradient = ctx.createLinearGradient(0, 0, width, 0)
  lineGradient.addColorStop(0, 'rgba(122, 118, 248, 0)')
  lineGradient.addColorStop(.16, palette.start)
  lineGradient.addColorStop(.55, palette.middle)
  lineGradient.addColorStop(.86, palette.end)
  lineGradient.addColorStop(1, 'rgba(92, 180, 255, 0)')

  ctx.clearRect(0, 0, width, height)
  ctx.save()
  ctx.globalCompositeOperation = 'lighter'
  ctx.strokeStyle = lineGradient
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'

  ctx.globalAlpha = .22
  ctx.lineWidth = Math.max(8, height * .12)
  ctx.shadowColor = palette.glow
  ctx.shadowBlur = Math.max(12, height * .2)
  drawFluidLayer(ctx, envelope, centerY + 2, amplitudeScale * .72 * warningPulse, 4.2, .5, .2)
  ctx.stroke()

  ctx.globalAlpha = .92
  ctx.lineWidth = Math.max(2, height * .026)
  ctx.shadowBlur = Math.max(5, height * .08)
  drawFluidLayer(ctx, envelope, centerY - 1, amplitudeScale * warningPulse, 5.4, 0, .22)
  ctx.stroke()

  ctx.globalAlpha = .42
  ctx.lineWidth = Math.max(1, height * .014)
  ctx.shadowBlur = 0
  drawFluidLayer(ctx, envelope, centerY + 1, amplitudeScale * .58, 7.2, 1.7, .16)
  ctx.stroke()
  ctx.restore()
}

function releaseMicRenderer() {
  micHandle?.onDestroy()
  micHandle = null
}

function renderStream() {
  releaseMicRenderer()
  renderError.value = ''
  if (!record || !props.stream?.active || !props.active) return
  try {
    micHandle = record.renderMicStream(props.stream)
  } catch (error) {
    renderError.value = error instanceof Error ? error.message : '实时波形暂不可用'
  }
}

function updateTheme() {
  wavesurfer?.setOptions(waveformColors())
}

function handleMotionPreference(event: MediaQueryListEvent) {
  reduceMotion = event.matches
  if (reduceMotion) flowPhase = 0
}

onMounted(async () => {
  await nextTick()
  if (!container.value) return
  motionMedia = window.matchMedia('(prefers-reduced-motion: reduce)')
  reduceMotion = motionMedia.matches
  motionMedia.addEventListener('change', handleMotionPreference)
  record = RecordPlugin.create({
    scrollingWaveform: true,
    scrollingWaveformWindow: 8,
    renderRecordedAudio: false
  })
  wavesurfer = WaveSurfer.create({
    container: container.value,
    height: props.height,
    ...waveformColors(),
    cursorWidth: 0,
    barWidth: 2,
    barGap: 2,
    barRadius: 2,
    barMinHeight: 2,
    normalize: true,
    interact: false,
    hideScrollbar: true,
    renderFunction: renderAuroraWaveform,
    plugins: [record]
  })
  themeObserver = new MutationObserver(updateTheme)
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  renderStream()
})

watch(() => [props.stream, props.active] as const, () => {
  flowPhase = 0
  previousRenderAt = 0
  renderStream()
})
watch(() => props.height, height => wavesurfer?.setOptions({ height }))
watch(() => props.status, updateTheme)

onBeforeUnmount(() => {
  themeObserver?.disconnect()
  motionMedia?.removeEventListener('change', handleMotionPreference)
  motionMedia = null
  releaseMicRenderer()
  wavesurfer?.destroy()
  wavesurfer = null
  record = null
})
</script>

<template>
  <div
    class="live-waveform"
    :class="[`is-${status}`, { 'is-active': active }]"
    :style="{ height: `${height}px` }"
    role="img"
    :aria-label="active ? '麦克风实时波形正在显示' : '麦克风波形尚未开始'"
  >
    <div ref="container" class="live-waveform-canvas" aria-hidden="true" />
    <div v-if="!active" class="waveform-idle" aria-hidden="true" />
    <span class="visually-hidden" role="status" aria-live="polite">
      {{ active ? '麦克风实时波形正在显示' : '麦克风实时波形未启动' }}
    </span>
    <small v-if="renderError" class="waveform-error">波形显示暂不可用，录音仍在继续</small>
  </div>
</template>

<style scoped>
.live-waveform {
  position: relative;
  overflow: hidden;
  min-height: 58px;
  border: 1px solid color-mix(in srgb, var(--color-primary) 18%, var(--color-border));
  border-radius: var(--radius-md);
  background:
    radial-gradient(ellipse at 50% 100%, rgba(92, 180, 255, .12), transparent 64%),
    color-mix(in srgb, var(--color-surface-subtle) 82%, transparent);
}
.live-waveform-canvas { width: 100%; height: 100%; }
.waveform-idle {
  position: absolute;
  inset: 50% 7% auto;
  height: 2px;
  border-radius: 999px;
  background: linear-gradient(90deg, transparent, rgba(122, 118, 248, .62), rgba(62, 230, 200, .76), rgba(92, 180, 255, .62), transparent);
  box-shadow: 0 0 12px rgba(92, 180, 255, .35);
  opacity: .64;
  transform: translateY(-50%);
}
.is-active { border-color: color-mix(in srgb, var(--color-primary) 42%, var(--color-border)); }
.is-warning {
  border-color: color-mix(in srgb, var(--color-warning) 60%, var(--color-border));
  background: color-mix(in srgb, var(--color-warning-soft) 48%, var(--color-surface));
}
.is-quiet {
  border-color: color-mix(in srgb, #5b88c6 42%, var(--color-border));
  background:
    radial-gradient(ellipse at 50% 100%, rgba(91, 136, 198, .12), transparent 64%),
    color-mix(in srgb, var(--color-surface-subtle) 86%, #5863b2 4%);
}
.waveform-error {
  position: absolute;
  right: .5rem;
  bottom: .25rem;
  padding: .12rem .35rem;
  border-radius: 999px;
  color: var(--color-warning);
  background: color-mix(in srgb, var(--color-surface) 88%, transparent);
}
@media (prefers-reduced-motion: reduce) {
  .waveform-idle { box-shadow: none; }
}
</style>
