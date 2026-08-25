<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import WaveSurfer from 'wavesurfer.js'
import RegionsPlugin, { type Region } from 'wavesurfer.js/dist/plugins/regions.esm.js'
import TimelinePlugin from 'wavesurfer.js/dist/plugins/timeline.esm.js'
import HoverPlugin from 'wavesurfer.js/dist/plugins/hover.esm.js'

export interface TranscriptPlayerSegment {
  segment_no?: number
  text: string
  started_at_ms: number
  ended_at_ms: number
  confidence?: number | null
}

const props = withDefaults(defineProps<{
  src: string
  segments?: TranscriptPlayerSegment[]
  activeIndex?: number
  title?: string
  autoPlayOnSeek?: boolean
  peaks?: number[]
  durationSeconds?: number
  compact?: boolean
}>(), {
  segments: () => [], activeIndex: -1, title: '', autoPlayOnSeek: true,
  peaks: () => [], durationSeconds: 0, compact: false
})

const emit = defineEmits<{
  (e: 'update:activeIndex', index: number): void
  (e: 'timeupdate', currentTimeMs: number): void
  (e: 'play'): void
  (e: 'pause'): void
  (e: 'ended'): void
  (e: 'ready'): void
  (e: 'error', message: string): void
  (e: 'segment-change', index: number, segment: TranscriptPlayerSegment | null): void
}>()

const waveform = ref<HTMLElement | null>(null)
const isPlaying = ref(false)
const isReady = ref(false)
const currentTime = ref(0)
const duration = ref(0)
const playbackRate = ref(1)
const isLoopingSegment = ref(false)
const loadError = ref('')
const playbackRates = [0.75, 1, 1.25, 1.5, 2]
let wavesurfer: WaveSurfer | null = null
let regions: RegionsPlugin | null = null
let activeRange: Region | null = null
let loadVersion = 0
let themeObserver: MutationObserver | null = null

const currentTimeMs = computed(() => Math.round(currentTime.value * 1000))
const currentSegmentIndex = computed(() => props.segments.findIndex(segment =>
  currentTimeMs.value >= segment.started_at_ms && currentTimeMs.value <= segment.ended_at_ms
))
const currentSegment = computed(() => currentSegmentIndex.value >= 0 ? props.segments[currentSegmentIndex.value] : null)

function css(variable: string, fallback: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(variable).trim() || fallback
}
function formatTime(seconds: number) {
  if (!Number.isFinite(seconds) || seconds < 0) return '00:00'
  const total = Math.floor(seconds)
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}
function colors() {
  return {
    waveColor: css('--color-primary-soft', 'rgba(99, 102, 241, .24)'),
    progressColor: css('--color-primary', '#5753c9'),
    cursorColor: css('--color-danger', '#dc3545')
  }
}
function regionColor(index: number) {
  return index === props.activeIndex ? 'rgba(250, 166, 26, .30)' : 'rgba(87, 83, 201, .10)'
}
function rebuildRegions() {
  if (!regions || !isReady.value) return
  regions.clearRegions()
  activeRange = null
  props.segments.forEach((segment, index) => regions?.addRegion({
    id: `segment-${index}`,
    start: Math.max(0, segment.started_at_ms / 1000),
    end: Math.max(segment.started_at_ms + 50, segment.ended_at_ms) / 1000,
    drag: false, resize: false, color: regionColor(index), content: String(index + 1)
  }))
}
function updateRegionColors() {
  regions?.getRegions().forEach(region => {
    const index = Number(region.id.replace('segment-', ''))
    if (Number.isInteger(index)) region.setOptions({ color: regionColor(index) })
  })
}
async function loadAudio() {
  const version = ++loadVersion
  isReady.value = false
  loadError.value = ''
  currentTime.value = 0
  duration.value = props.durationSeconds || 0
  if (!wavesurfer || !props.src) return
  try {
    await wavesurfer.load(
      props.src,
      props.peaks.length ? [props.peaks] : undefined,
      props.durationSeconds || undefined
    )
    if (version !== loadVersion) return
  } catch (error) {
    if (version !== loadVersion) return
    const message = error instanceof Error ? error.message : '音频加载失败'
    loadError.value = `波形加载失败，已切换到基础播放器：${message}`
    emit('error', message)
  }
}
function seek(seconds: number, autoPlay = false) {
  if (!wavesurfer) return
  const clamped = Math.max(0, Math.min(seconds, duration.value || wavesurfer.getDuration() || 0))
  wavesurfer.setTime(clamped)
  currentTime.value = clamped
  emit('timeupdate', Math.round(clamped * 1000))
  if (autoPlay || (props.autoPlayOnSeek && isPlaying.value)) void wavesurfer.play()
}
function seekToMs(ms: number, autoPlay = true) { seek(ms / 1000, autoPlay) }
function seekToSegment(index: number, autoPlay = true) {
  const segment = props.segments[index]
  if (!segment) return
  emit('update:activeIndex', index)
  const region = regions?.getRegions().find(item => item.id === `segment-${index}`)
  if (autoPlay && region) region.play(true)
  else seekToMs(segment.started_at_ms, autoPlay)
}
function playRange(startedAtMs: number, endedAtMs: number) {
  activeRange?.remove()
  activeRange = regions?.addRegion({
    id: 'active-range', start: Math.max(0, startedAtMs / 1000),
    end: Math.max(startedAtMs + 50, endedAtMs) / 1000,
    drag: false, resize: false, color: 'rgba(250, 166, 26, .34)', content: '试听范围'
  }) ?? null
  if (activeRange) activeRange.play(true)
  else seekToMs(startedAtMs, true)
}
function togglePlay() {
  if (!wavesurfer || !props.src) return
  wavesurfer.playPause().catch(error => {
    loadError.value = error instanceof Error ? error.message : '音频播放失败'
  })
}
function step(delta: number) { seek(currentTime.value + delta) }
function prevSegment() { seekToSegment(Math.max(0, currentSegmentIndex.value - 1)) }
function nextSegment() {
  const next = currentSegmentIndex.value < 0 ? 0 : currentSegmentIndex.value + 1
  if (next < props.segments.length) seekToSegment(next)
  else step(3)
}
function setPlaybackRate(rate: number) { playbackRate.value = rate; wavesurfer?.setPlaybackRate(rate, true) }
function toggleSegmentLoop() { isLoopingSegment.value = !isLoopingSegment.value }
function onKeydown(event: KeyboardEvent) {
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes((event.target as HTMLElement).tagName)) return
  if (event.code === 'Space') { event.preventDefault(); togglePlay() }
  if (event.code === 'ArrowLeft') { event.preventDefault(); step(-3) }
  if (event.code === 'ArrowRight') { event.preventDefault(); step(3) }
  if (event.code === 'ArrowUp') { event.preventDefault(); prevSegment() }
  if (event.code === 'ArrowDown') { event.preventDefault(); nextSegment() }
  if (event.code === 'KeyL') { event.preventDefault(); toggleSegmentLoop() }
}

onMounted(async () => {
  await nextTick()
  if (!waveform.value) return
  regions = RegionsPlugin.create()
  const timeline = TimelinePlugin.create({
    height: 18, formatTimeCallback: formatTime,
    style: { color: css('--color-text-muted', '#697386'), fontSize: '10px' }
  })
  const hover = HoverPlugin.create({
    lineColor: css('--color-primary', '#5753c9'), labelColor: '#fff',
    labelBackground: css('--color-text', '#17214a'), formatTimeCallback: formatTime
  })
  wavesurfer = WaveSurfer.create({
    container: waveform.value, height: props.compact ? 58 : 84, ...colors(),
    cursorWidth: 2, barWidth: 2, barGap: 2, barRadius: 2, barMinHeight: 2,
    normalize: true, dragToSeek: true, hideScrollbar: false, backend: 'MediaElement',
    plugins: [regions, timeline, hover]
  })
  wavesurfer.on('ready', loadedDuration => {
    duration.value = loadedDuration || props.durationSeconds
    isReady.value = true
    wavesurfer?.setPlaybackRate(playbackRate.value, true)
    rebuildRegions()
    emit('ready')
  })
  wavesurfer.on('timeupdate', seconds => {
    currentTime.value = seconds
    emit('timeupdate', Math.round(seconds * 1000))
    if (isLoopingSegment.value && currentSegment.value && seconds >= currentSegment.value.ended_at_ms / 1000) {
      wavesurfer?.setTime(currentSegment.value.started_at_ms / 1000)
    }
  })
  wavesurfer.on('play', () => { isPlaying.value = true; emit('play') })
  wavesurfer.on('pause', () => { isPlaying.value = false; emit('pause') })
  wavesurfer.on('finish', () => { isPlaying.value = false; emit('ended') })
  wavesurfer.on('error', error => { loadError.value = '波形加载失败，已提供基础播放器。'; emit('error', error.message) })
  regions.on('region-clicked', (region, event) => {
    event.stopPropagation()
    const index = Number(region.id.replace('segment-', ''))
    if (Number.isInteger(index)) {
      emit('update:activeIndex', index)
      emit('segment-change', index, props.segments[index] ?? null)
    }
    region.play(true)
  })
  themeObserver = new MutationObserver(() => wavesurfer?.setOptions(colors()))
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  await loadAudio()
})

watch(() => props.src, loadAudio)
watch(() => [props.peaks, props.durationSeconds], loadAudio, { deep: true })
watch(() => props.segments, rebuildRegions, { deep: true })
watch(() => props.activeIndex, updateRegionColors)
watch(currentSegmentIndex, index => {
  if (index !== props.activeIndex) {
    emit('update:activeIndex', index)
    emit('segment-change', index, index >= 0 ? props.segments[index] : null)
  }
})

onBeforeUnmount(() => { themeObserver?.disconnect(); wavesurfer?.destroy(); wavesurfer = null; regions = null })
defineExpose({
  play: () => wavesurfer?.play(), pause: () => wavesurfer?.pause(), togglePlay, seek,
  seekToMs, seekToSegment, playRange, prevSegment, nextSegment, setPlaybackRate,
  toggleSegmentLoop, currentTime, duration, isPlaying
})
</script>

<template>
  <section class="audio-transcript-player" :class="[{ 'is-playing': isPlaying, compact }]" tabindex="0" @keydown="onKeydown">
    <header class="player-header">
      <div class="player-meta">
        <span class="status-dot" :class="{ 'is-active': isPlaying }" />
        <strong>{{ title || '音文精细化对齐试听' }}</strong>
        <span v-if="currentSegment" class="current-segment-badge">第 {{ currentSegmentIndex + 1 }} 段</span>
      </div>
      <span class="time-display"><strong>{{ formatTime(currentTime) }}</strong> / {{ formatTime(duration) }}</span>
    </header>
    <div class="waveform-shell">
      <div ref="waveform" class="waveform" />
      <div v-if="!isReady && !loadError" class="waveform-loading"><span class="spinner-border spinner-border-sm" />正在生成波形</div>
    </div>
    <div class="player-controls">
      <div class="main-controls">
        <button class="btn btn-sm btn-outline-secondary" type="button" title="上一段" :disabled="!src" @click="prevSegment"><i class="bi bi-chevron-bar-left" /></button>
        <button class="btn btn-sm btn-outline-secondary" type="button" title="后退 3 秒" :disabled="!src" @click="step(-3)"><i class="bi bi-arrow-counterclockwise" /></button>
        <button class="btn btn-primary btn-play" type="button" :disabled="!src" @click="togglePlay"><i class="bi" :class="isPlaying ? 'bi-pause-fill' : 'bi-play-fill'" />{{ isPlaying ? '暂停' : '播放' }}</button>
        <button class="btn btn-sm btn-outline-secondary" type="button" title="前进 3 秒" :disabled="!src" @click="step(3)"><i class="bi bi-arrow-clockwise" /></button>
        <button class="btn btn-sm btn-outline-secondary" type="button" title="下一段" :disabled="!src" @click="nextSegment"><i class="bi bi-chevron-bar-right" /></button>
      </div>
      <div class="aux-controls">
        <button class="btn btn-sm btn-outline-secondary" :class="{ active: isLoopingSegment }" type="button" @click="toggleSegmentLoop"><i class="bi bi-repeat-1 me-1" />片段循环</button>
        <div class="btn-group" role="group" aria-label="播放速度">
          <button v-for="rate in playbackRates" :key="rate" class="btn btn-sm btn-outline-secondary" :class="{ active: playbackRate === rate }" type="button" @click="setPlaybackRate(rate)">{{ rate }}x</button>
        </div>
      </div>
    </div>
    <div v-if="loadError" class="player-error-alert">
      <i class="bi bi-exclamation-circle-fill me-1" />{{ loadError }}
      <audio :src="src" controls preload="metadata" class="native-fallback mt-2" />
    </div>
  </section>
</template>

<style scoped>
.audio-transcript-player { display: grid; gap: .75rem; padding: 1rem; border: 1px solid var(--color-border); border-radius: var(--radius-lg); background: var(--color-surface); box-shadow: var(--shadow-sm); outline: none; }
.audio-transcript-player:focus-visible { box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-primary) 24%, transparent); }
.audio-transcript-player.is-playing { border-color: color-mix(in srgb, var(--color-primary) 42%, var(--color-border)); }
.player-header, .player-controls, .main-controls, .aux-controls, .player-meta { display: flex; align-items: center; gap: .55rem; }
.player-header, .player-controls { justify-content: space-between; flex-wrap: wrap; }
.player-meta { min-width: 0; color: var(--color-text); }
.status-dot { width: 8px; height: 8px; flex: 0 0 auto; border-radius: 50%; background: var(--color-text-muted); }
.status-dot.is-active { background: var(--color-success); box-shadow: 0 0 9px var(--color-success); }
.current-segment-badge { padding: .14rem .45rem; border-radius: 999px; color: var(--color-primary); background: var(--color-primary-soft); font-size: .72rem; font-weight: 700; }
.time-display { color: var(--color-text-muted); font: .78rem ui-monospace, SFMono-Regular, Menlo, monospace; }
.time-display strong { color: var(--color-text); }
.waveform-shell { position: relative; min-height: 104px; overflow: hidden; border-radius: var(--radius-md); background: color-mix(in srgb, var(--color-surface-subtle) 86%, transparent); }
.compact .waveform-shell { min-height: 78px; }
.waveform { width: 100%; }
.waveform-loading { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; gap: .5rem; color: var(--color-text-muted); background: color-mix(in srgb, var(--color-surface) 74%, transparent); font-size: .78rem; }
.btn-play { min-width: 82px; }
.player-error-alert { padding: .65rem .75rem; border-radius: var(--radius-md); color: var(--color-warning); background: color-mix(in srgb, var(--color-warning) 10%, var(--color-surface)); font-size: .78rem; }
.native-fallback { display: block; width: 100%; }
.waveform :deep([part="region"]) { border-inline: 1px solid color-mix(in srgb, var(--color-primary) 45%, transparent); }
@media (max-width: 767.98px) {
  .audio-transcript-player { padding: .75rem; }
  .player-controls, .main-controls, .aux-controls { width: 100%; }
  .main-controls { justify-content: center; }
  .aux-controls { justify-content: space-between; overflow-x: auto; padding-bottom: .2rem; }
  .waveform-shell { min-height: 90px; }
}
</style>
