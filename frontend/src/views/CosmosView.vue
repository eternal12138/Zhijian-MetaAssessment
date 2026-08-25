<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import LiangIntensityCalibrator from '../components/easteregg/LiangIntensityCalibrator.vue'

type Planet = {
  name: string
  color: string
  accent: string
  period: number
  eccentricity: number
  radius: number
  angle: number
  diameter: string
  distance: string
  rings?: boolean
}

type Star = { x: number; y: number; size: number; alpha: number; phase: number; hue: number }
type PlanetPoint = { planet: Planet; x: number; y: number; size: number; isDeepSeek: boolean; semiMajor: number; rotation: number }

const router = useRouter()
const canvas = ref<HTMLCanvasElement | null>(null)
const speedInput = ref(32)
const paused = ref(false)
const showOrbits = ref(true)
const showLabels = ref(true)
const displayDays = ref(0)
const hoveredPlanet = ref<Planet | null>(null)
const prefersReducedMotion = ref(false)
const pointerCoarse = ref(false)
const pageVisible = ref(typeof document === 'undefined' ? true : document.visibilityState === 'visible')
const showCalibrator = ref(false)
const isEarthNearPerihelion = ref(false)
let lastEarthClickTime = 0
let lastSecretTarget = ''

// 视角透视倾角常量（0.62，模拟斜俯视太阳系公转轨道面）
const TILT_Y = 0.62

function handleSecretTrigger(planet: Planet | null) {
  if (planet?.name === '地球' || planet?.name === 'DeepSeek') {
    const now = Date.now()
    if (lastSecretTarget === planet.name && lastEarthClickTime > 0 && (now - lastEarthClickTime) < 850) {
      showCalibrator.value = true
      lastEarthClickTime = 0
      lastSecretTarget = ''
    } else {
      lastEarthClickTime = now
      lastSecretTarget = planet.name
    }
  }
}

const planets: Planet[] = [
  { name: '水星', color: '#a7a4a0', accent: '#dedad1', period: 87.97, eccentricity: .2056, radius: 3.5, angle: .2, diameter: '4,879 km', distance: '0.39 AU' },
  { name: '金星', color: '#d9a85e', accent: '#ffe0a3', period: 224.7, eccentricity: .0068, radius: 4.8, angle: 1.4, diameter: '12,104 km', distance: '0.72 AU' },
  { name: '地球', color: '#3f8de3', accent: '#80d6ff', period: 365.26, eccentricity: .0167, radius: 5.2, angle: 2.7, diameter: '12,742 km', distance: '1.00 AU' },
  { name: '火星', color: '#bd5539', accent: '#ff9271', period: 686.98, eccentricity: .0934, radius: 4.2, angle: 4.1, diameter: '6,779 km', distance: '1.52 AU' },
  { name: '木星', color: '#c89b72', accent: '#f3cfaa', period: 4332.6, eccentricity: .0489, radius: 10.5, angle: 5.2, diameter: '139,820 km', distance: '5.20 AU' },
  { name: '土星', color: '#d7bd78', accent: '#fff0b0', period: 10759, eccentricity: .0565, radius: 9.2, angle: .85, diameter: '116,460 km', distance: '9.58 AU', rings: true },
  { name: '天王星', color: '#77cad5', accent: '#b9f5ff', period: 30687, eccentricity: .0457, radius: 7.2, angle: 2.1, diameter: '50,724 km', distance: '19.2 AU' },
  { name: '海王星', color: '#4169d8', accent: '#789cff', period: 60190, eccentricity: .0113, radius: 7.0, angle: 3.45, diameter: '49,244 km', distance: '30.1 AU' }
]

// 鼠标悬停时的行星展示数据（地球近日点时变成 DeepSeek 且属性显示为未知 / ？）
const inspectedPlanet = computed(() => {
  if (!hoveredPlanet.value) return null
  const isEarth = hoveredPlanet.value.name === '地球' || hoveredPlanet.value.name === 'DeepSeek'
  if (isEarth && isEarthNearPerihelion.value) {
    return {
      name: 'DeepSeek',
      color: '#0284c7',
      accent: '#38bdf8',
      period: '未知',
      eccentricity: '未知',
      radius: hoveredPlanet.value.radius,
      angle: hoveredPlanet.value.angle,
      diameter: '未知',
      distance: '未知',
      isAnomaly: true
    }
  }
  return {
    ...hoveredPlanet.value,
    isAnomaly: false
  }
})

const speed = computed(() => .1 * Math.pow(1280, speedInput.value / 100))
const speedLabel = computed(() => speed.value < 1 ? `${speed.value.toFixed(2)}×` : `${speed.value.toFixed(speed.value < 10 ? 1 : 0)}×`)
const effectivePaused = computed(() => paused.value || prefersReducedMotion.value || !pageVisible.value)
const interactionHint = computed(() => pointerCoarse.value
  ? '轻触行星读取数据，连续轻触地球可发现隐藏彩蛋'
  : '悬停行星读取数据，连续点击地球可发现隐藏彩蛋'
)
const simulatedDate = computed(() => {
  const date = new Date(Date.UTC(2026, 0, 1))
  date.setUTCDate(date.getUTCDate() + Math.floor(displayDays.value))
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' }).format(date)
})

let frame = 0
let lastTime = 0
let lastUiUpdate = 0
let lastRenderedAt = 0
let simulationDays = 0
let stars: Star[] = []
let planetPoints: PlanetPoint[] = []
let resizeObserver: ResizeObserver | null = null
let motionMedia: MediaQueryList | null = null
let motionListener: (() => void) | null = null
let pointerMedia: MediaQueryList | null = null
let pointerListener: (() => void) | null = null

function seeded(index: number) {
  const value = Math.sin(index * 9283.17 + 17.31) * 43758.5453
  return value - Math.floor(value)
}

function createStars(count: number) {
  stars = Array.from({ length: count }, (_, index) => ({
    x: seeded(index * 6),
    y: seeded(index * 6 + 1),
    size: .35 + seeded(index * 6 + 2) * 1.5,
    alpha: .18 + seeded(index * 6 + 3) * .72,
    phase: seeded(index * 6 + 4) * Math.PI * 2,
    hue: 190 + seeded(index * 6 + 5) * 55
  }))
}

// 求解开普勒方程 M = E - e*sin(E)
function solveEccentricAnomaly(mean: number, eccentricity: number) {
  let eccentric = mean
  for (let iteration = 0; iteration < 5; iteration += 1) {
    eccentric -= (eccentric - eccentricity * Math.sin(eccentric) - mean)
      / (1 - eccentricity * Math.cos(eccentric))
  }
  return eccentric
}

function resizeCanvas() {
  const target = canvas.value
  if (!target) return
  const rect = target.getBoundingClientRect()
  const lowPowerDevice = (navigator.hardwareConcurrency || 8) <= 4
  const ratioLimit = pointerCoarse.value || lowPowerDevice ? 1.5 : 2
  const ratio = Math.min(window.devicePixelRatio || 1, ratioLimit)
  target.width = Math.max(1, Math.round(rect.width * ratio))
  target.height = Math.max(1, Math.round(rect.height * ratio))
  const context = target.getContext('2d')
  context?.setTransform(ratio, 0, 0, ratio, 0, 0)
  const starLimit = pointerCoarse.value || lowPowerDevice ? 240 : 520
  createStars(Math.min(starLimit, Math.max(110, Math.round(rect.width * rect.height / 4200))))
}

// 严格绘制开普勒真实公转轨道线（与行星点完全数学对齐）
function drawOrbit(
  context: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  semiMajor: number,
  eccentricity: number,
  rotation: number,
  isHighlighted: boolean
) {
  context.save()
  context.translate(cx, cy)
  context.rotate(rotation)
  context.beginPath()
  const semiMinor = semiMajor * Math.sqrt(Math.max(0.01, 1 - eccentricity ** 2)) * TILT_Y
  const focusOffsetX = -semiMajor * eccentricity
  context.ellipse(focusOffsetX, 0, semiMajor, semiMinor, 0, 0, Math.PI * 2)

  if (isHighlighted) {
    context.strokeStyle = 'rgba(56, 189, 248, 0.75)'
    context.lineWidth = 1.6
    context.shadowColor = '#38bdf8'
    context.shadowBlur = 10
  } else {
    context.strokeStyle = 'rgba(128, 155, 226, 0.2)'
    context.lineWidth = 1
    context.shadowBlur = 0
  }
  context.stroke()
  context.restore()
}

function drawSun(context: CanvasRenderingContext2D, cx: number, cy: number, scale: number) {
  const glow = context.createRadialGradient(cx, cy, 0, cx, cy, 58 * scale)
  glow.addColorStop(0, 'rgba(255,255,225,1)')
  glow.addColorStop(.13, 'rgba(255,208,75,.98)')
  glow.addColorStop(.34, 'rgba(255,129,32,.38)')
  glow.addColorStop(1, 'rgba(255,89,20,0)')
  context.fillStyle = glow
  context.beginPath()
  context.arc(cx, cy, 58 * scale, 0, Math.PI * 2)
  context.fill()
  context.fillStyle = '#ffd76b'
  context.shadowColor = '#ff9f32'
  context.shadowBlur = 26 * scale
  context.beginPath()
  context.arc(cx, cy, 12 * scale, 0, Math.PI * 2)
  context.fill()
  context.shadowBlur = 0
}

function drawPlanet(context: CanvasRenderingContext2D, point: PlanetPoint) {
  const { planet, x, y, size, isDeepSeek } = point
  context.save()
  context.translate(x, y)
  if (planet.rings) {
    context.strokeStyle = 'rgba(235,216,163,.75)'
    context.lineWidth = 2
    context.beginPath()
    context.ellipse(0, 0, size * 1.9, size * .62, -.18, 0, Math.PI * 2)
    context.stroke()
  }

  const pColor = isDeepSeek ? '#0284c7' : planet.color
  const pAccent = isDeepSeek ? '#38bdf8' : planet.accent

  const gradient = context.createRadialGradient(-size * .35, -size * .42, size * .08, 0, 0, size)
  gradient.addColorStop(0, pAccent)
  gradient.addColorStop(.48, pColor)
  gradient.addColorStop(1, '#111525')
  context.fillStyle = gradient
  context.shadowColor = isDeepSeek ? '#38bdf8' : planet.color
  context.shadowBlur = hoveredPlanet.value?.name === planet.name ? 22 : isDeepSeek ? 16 : 8
  context.beginPath()
  context.arc(0, 0, size, 0, Math.PI * 2)
  context.fill()
  context.restore()

  if (showLabels.value) {
    const isHovered = hoveredPlanet.value?.name === planet.name || (isDeepSeek && hoveredPlanet.value?.name === '地球')
    context.fillStyle = isDeepSeek ? '#38bdf8' : isHovered ? '#ffffff' : 'rgba(216,226,255,.78)'
    context.font = `${isHovered || isDeepSeek ? 700 : 500} 11px system-ui, sans-serif`
    context.textAlign = 'center'
    const labelText = isDeepSeek ? 'DeepSeek' : planet.name
    context.fillText(labelText, x, y - size - 9)
  }
}

function render(timestamp: number) {
  const target = canvas.value
  const context = target?.getContext('2d')
  if (!target || !context) return
  const lowPowerDevice = pointerCoarse.value || (navigator.hardwareConcurrency || 8) <= 4
  const targetFps = effectivePaused.value ? 12 : lowPowerDevice ? 30 : 60
  if (timestamp - lastRenderedAt < 1000 / targetFps) {
    frame = window.requestAnimationFrame(render)
    return
  }
  lastRenderedAt = timestamp
  const width = target.clientWidth
  const height = target.clientHeight
  const delta = lastTime ? Math.min((timestamp - lastTime) / 1000, .08) : 0
  lastTime = timestamp
  if (!effectivePaused.value) simulationDays += delta * 8 * speed.value
  if (timestamp - lastUiUpdate > 250) {
    displayDays.value = simulationDays
    lastUiUpdate = timestamp
  }

  context.clearRect(0, 0, width, height)
  const background = context.createRadialGradient(width * .5, height * .52, 20, width * .5, height * .52, Math.max(width, height) * .72)
  background.addColorStop(0, '#101a3c')
  background.addColorStop(.45, '#070c22')
  background.addColorStop(1, '#02040d')
  context.fillStyle = background
  context.fillRect(0, 0, width, height)

  for (const star of stars) {
    const twinkle = prefersReducedMotion.value ? 1 : .72 + Math.sin(timestamp * .00055 + star.phase) * .28
    context.fillStyle = `hsla(${star.hue}, 86%, 88%, ${star.alpha * twinkle})`
    context.beginPath()
    context.arc(star.x * width, star.y * height, star.size, 0, Math.PI * 2)
    context.fill()
  }

  const cx = width * .5
  const cy = height * .5
  const maxOrbit = Math.max(130, Math.min(width * .46, height * .45))
  const minOrbit = Math.min(48, maxOrbit * .2)
  const scale = Math.max(.72, Math.min(1.18, Math.min(width, height) / 780))
  planetPoints = []

  // 1. 绘制公转轨道线（与行星轨道严格对齐）
  if (showOrbits.value) {
    planets.forEach((planet, index) => {
      const semiMajor = minOrbit + Math.pow(index / 7, .78) * (maxOrbit - minOrbit)
      const rotation = planet.angle * .17
      const isHighlighted = hoveredPlanet.value?.name === planet.name || (planet.name === '地球' && hoveredPlanet.value?.name === 'DeepSeek')
      drawOrbit(context, cx, cy, semiMajor, planet.eccentricity, rotation, isHighlighted)
    })
  }

  // 2. 绘制太阳
  drawSun(context, cx, cy, scale)

  // 3. 计算行星开普勒运动坐标（严格约束在已绘制的椭圆轨道线上）
  planets.forEach((planet, index) => {
    const semiMajor = minOrbit + Math.pow(index / 7, .78) * (maxOrbit - minOrbit)
    const semiMinor = semiMajor * Math.sqrt(Math.max(0.01, 1 - planet.eccentricity ** 2)) * TILT_Y
    const rotation = planet.angle * .17

    // 平均近点角 M = M0 + n*t
    const mean = planet.angle + (simulationDays / planet.period) * Math.PI * 2
    // 偏近点角 E
    const eccentric = solveEccentricAnomaly(mean, planet.eccentricity)

    // 焦点在 (0, 0) 的开普勒椭圆坐标
    const localX = semiMajor * (Math.cos(eccentric) - planet.eccentricity)
    const localY = semiMinor * Math.sin(eccentric)

    // 旋转并平移到画布中心
    const x = cx + localX * Math.cos(rotation) - localY * Math.sin(rotation)
    const y = cy + localX * Math.sin(rotation) + localY * Math.cos(rotation)
    const size = Math.max(3.2, planet.radius * scale)

    // 地球在近日点判定 (cos(eccentric) > 0.85 即处于靠近太阳的近日点弧段)
    const isEarth = planet.name === '地球'
    const isNearPeri = isEarth && Math.cos(eccentric) > 0.85
    if (isEarth) {
      isEarthNearPerihelion.value = isNearPeri
    }

    planetPoints.push({ planet, x, y, size, isDeepSeek: isNearPeri, semiMajor, rotation })
  })

  // 按 Y 轴景深排序渲染行星
  planetPoints.sort((a, b) => a.y - b.y).forEach(point => drawPlanet(context, point))
  frame = window.requestAnimationFrame(render)
}

function planetAtPointer(event: PointerEvent) {
  const target = canvas.value
  if (!target) return null
  const rect = target.getBoundingClientRect()
  const x = event.clientX - rect.left
  const y = event.clientY - rect.top
  const minimumTarget = pointerCoarse.value ? 24 : 12
  return planetPoints.find(point => (
    Math.hypot(point.x - x, point.y - y) <= Math.max(minimumTarget, point.size + 7)
  )) ?? null
}

function inspectPlanet(event: PointerEvent) {
  if (event.pointerType === 'touch') return
  const point = planetAtPointer(event)
  hoveredPlanet.value = point?.planet ?? null
  if (canvas.value) canvas.value.style.cursor = point ? 'crosshair' : 'default'
}

function selectPlanet(event: PointerEvent) {
  const point = planetAtPointer(event)
  hoveredPlanet.value = point?.planet ?? null
  handleSecretTrigger(point?.planet ?? null)
}

function setSpeed(value: number) {
  speedInput.value = Math.max(0, Math.min(100, Math.log(value / .1) / Math.log(1280) * 100))
}

onMounted(() => {
  motionMedia = window.matchMedia('(prefers-reduced-motion: reduce)')
  motionListener = () => {
    prefersReducedMotion.value = motionMedia?.matches ?? false
  }
  motionListener()
  motionMedia.addEventListener('change', motionListener)
  pointerMedia = window.matchMedia('(hover: none), (pointer: coarse)')
  pointerListener = () => {
    pointerCoarse.value = pointerMedia?.matches ?? false
    resizeCanvas()
  }
  pointerListener()
  pointerMedia.addEventListener('change', pointerListener)
  document.addEventListener('visibilitychange', handleVisibilityChange)
  resizeObserver = new ResizeObserver(resizeCanvas)
  if (canvas.value) resizeObserver.observe(canvas.value)
  resizeCanvas()
  frame = window.requestAnimationFrame(render)
})

watch(paused, value => { if (!value) lastTime = performance.now() })

function handleVisibilityChange() {
  pageVisible.value = document.visibilityState === 'visible'
  lastTime = performance.now()
}

onBeforeUnmount(() => {
  window.cancelAnimationFrame(frame)
  resizeObserver?.disconnect()
  if (motionMedia && motionListener) motionMedia.removeEventListener('change', motionListener)
  if (pointerMedia && pointerListener) pointerMedia.removeEventListener('change', pointerListener)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})
</script>

<template>
  <main class="cosmos-page">
    <canvas ref="canvas" class="cosmos-canvas" aria-label="动态太阳系轨道模拟" @pointermove="inspectPlanet" @pointerleave="hoveredPlanet = null" @pointerup="selectPlanet" />
    <div class="cosmos-vignette" />

    <header class="cosmos-header">
      <button class="glass-icon-button" type="button" aria-label="返回系统" @click="router.back()">
        <i class="bi bi-arrow-left" />
      </button>
      <div>
        <p>ZHJIAN · ORBITAL LAB</p>
        <h1>太阳系轨道模拟</h1>
      </div>
      <div class="live-indicator" :class="{ paused: effectivePaused }"><span />{{ prefersReducedMotion ? '减少动态' : paused ? '已暂停' : '实时演算' }}</div>
    </header>

    <section class="cosmos-info" aria-live="polite">
      <template v-if="inspectedPlanet">
        <p>
          轨道目标
          <span v-if="inspectedPlanet.isAnomaly" class="badge bg-info-subtle text-info ms-1">近日点引力跃迁</span>
        </p>
        <h2>{{ inspectedPlanet.name }}</h2>
        <dl>
          <div><dt>直径</dt><dd>{{ typeof inspectedPlanet.diameter === 'string' && inspectedPlanet.diameter !== '未知' ? inspectedPlanet.diameter : '未知' }}</dd></div>
          <div><dt>日距</dt><dd>{{ typeof inspectedPlanet.distance === 'string' && inspectedPlanet.distance !== '未知' ? inspectedPlanet.distance : '未知' }}</dd></div>
          <div><dt>公转周期</dt><dd>{{ typeof inspectedPlanet.period === 'number' ? inspectedPlanet.period.toLocaleString('zh-CN') + ' 天' : '未知' }}</dd></div>
        </dl>
      </template>
      <template v-else>
        <p>模拟纪元</p>
        <h2>{{ simulatedDate }}</h2>
        <span>{{ interactionHint }}</span>
      </template>
    </section>

    <section class="cosmos-controls" aria-label="模拟控制台">
      <div class="speed-control">
        <div class="control-heading"><span>时间流速</span><strong>{{ speedLabel }}</strong></div>
        <input v-model.number="speedInput" type="range" min="0" max="100" step="1" aria-label="调整模拟速度" />
        <div class="speed-presets">
          <button v-for="preset in [.25, 1, 8, 32, 128]" :key="preset" type="button" @click="setSpeed(preset)">{{ preset }}×</button>
        </div>
      </div>
      <div class="control-actions">
        <button class="primary-control" type="button" :disabled="prefersReducedMotion" @click="paused = !paused">
          <i class="bi" :class="prefersReducedMotion ? 'bi-universal-access' : paused ? 'bi-play-fill' : 'bi-pause-fill'" />{{ prefersReducedMotion ? '已减少动态' : paused ? '继续模拟' : '暂停模拟' }}
        </button>
        <button type="button" :class="{ active: showOrbits }" @click="showOrbits = !showOrbits"><i class="bi bi-bullseye" />轨道</button>
        <button type="button" :class="{ active: showLabels }" @click="showLabels = !showLabels"><i class="bi bi-type" />标牌</button>
      </div>
    </section>

    <LiangIntensityCalibrator v-model="showCalibrator" />
  </main>
</template>

<style scoped>
.cosmos-page {
  position: relative;
  width: 100vw;
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
  background: #02040d;
  color: #f8fafc;
  user-select: none;
}

.cosmos-canvas {
  width: 100%;
  height: 100%;
  display: block;
  touch-action: manipulation;
}

.cosmos-vignette {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: radial-gradient(circle at center, transparent 45%, rgba(2, 4, 13, 0.65) 100%);
}

.cosmos-header {
  position: absolute;
  top: max(1.5rem, env(safe-area-inset-top));
  left: max(1.5rem, env(safe-area-inset-left));
  right: max(1.5rem, env(safe-area-inset-right));
  display: flex;
  align-items: center;
  gap: 1.25rem;
  z-index: 10;
  pointer-events: auto;
}

.cosmos-header p {
  margin: 0;
  font-size: 0.72rem;
  letter-spacing: 0.15em;
  color: #94a3b8;
  font-weight: 700;
}

.cosmos-header h1 {
  margin: 0;
  font-size: 1.4rem;
  font-weight: 800;
  background: linear-gradient(135deg, #fff, #94a3b8);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.glass-icon-button {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.15);
  backdrop-filter: blur(12px);
  color: #fff;
  display: grid;
  place-items: center;
  cursor: pointer;
  transition: transform var(--motion-fast) var(--ease-out), background-color var(--motion-fast) ease, border-color var(--motion-fast) ease;
}
.glass-icon-button:focus-visible,
.speed-presets button:focus-visible,
.control-actions button:focus-visible { outline: 2px solid #7dd3fc; outline-offset: 3px; }

.live-indicator {
  margin-left: auto;
  font-size: 0.76rem;
  font-weight: 700;
  padding: 0.35rem 0.75rem;
  border-radius: 999px;
  background: rgba(16, 185, 129, 0.15);
  border: 1px solid rgba(16, 185, 129, 0.3);
  color: #34d399;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.live-indicator span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #34d399;
  box-shadow: 0 0 8px #34d399;
}

.live-indicator.paused {
  background: rgba(245, 158, 11, 0.15);
  border-color: rgba(245, 158, 11, 0.3);
  color: #fbbf24;
}

.live-indicator.paused span {
  background: #fbbf24;
  box-shadow: 0 0 8px #fbbf24;
}

.cosmos-info {
  position: absolute;
  top: 5.5rem;
  left: max(1.5rem, env(safe-area-inset-left));
  min-width: 220px;
  padding: 1.25rem 1.5rem;
  background: rgba(15, 23, 42, 0.65);
  border: 1px solid rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(16px);
  border-radius: 18px;
  z-index: 10;
  pointer-events: none;
}

.cosmos-info p {
  margin: 0 0 0.25rem;
  font-size: 0.72rem;
  color: #94a3b8;
  font-weight: 600;
  letter-spacing: 0.05em;
}

.cosmos-info h2 {
  margin: 0 0 0.75rem;
  font-size: 1.45rem;
  font-weight: 800;
  color: #38bdf8;
}

.cosmos-info dl {
  margin: 0;
  display: grid;
  gap: 0.4rem;
  font-size: 0.82rem;
}

.cosmos-info dl div {
  display: flex;
  justify-content: space-between;
  gap: 1.5rem;
}

.cosmos-info dt {
  color: #64748b;
}

.cosmos-info dd {
  margin: 0;
  font-weight: 700;
  color: #f1f5f9;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.cosmos-info span {
  font-size: 0.8rem;
  color: #64748b;
}

.cosmos-controls {
  position: absolute;
  bottom: max(1.5rem, env(safe-area-inset-bottom));
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 1.5rem;
  padding: 0.85rem 1.5rem;
  background: rgba(15, 23, 42, 0.75);
  border: 1px solid rgba(255, 255, 255, 0.12);
  backdrop-filter: blur(20px);
  border-radius: 22px;
  z-index: 10;
  pointer-events: auto;
}

.speed-control {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  min-width: 170px;
}

.control-heading {
  display: flex;
  justify-content: space-between;
  font-size: 0.75rem;
  color: #94a3b8;
}

.speed-control input[type="range"] {
  width: 100%;
  height: 6px;
  border-radius: 999px;
  accent-color: #38bdf8;
  cursor: pointer;
}

.speed-presets {
  display: flex;
  justify-content: space-between;
  gap: 0.3rem;
}

.speed-presets button {
  padding: 0.15rem 0.4rem;
  font-size: 0.68rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #cbd5e1;
  border-radius: 6px;
  cursor: pointer;
  transition: background-color var(--motion-fast) ease, color var(--motion-fast) ease, border-color var(--motion-fast) ease;
}

.control-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.control-actions button {
  padding: 0.45rem 0.85rem;
  font-size: 0.82rem;
  font-weight: 600;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #cbd5e1;
  border-radius: 10px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 0.35rem;
  min-height: 38px;
  transition: background-color var(--motion-fast) ease, color var(--motion-fast) ease, border-color var(--motion-fast) ease, transform var(--motion-fast) var(--ease-out);
}

.control-actions button.active {
  background: rgba(56, 189, 248, 0.2);
  border-color: #38bdf8;
  color: #38bdf8;
}

.control-actions button.primary-control {
  background: #38bdf8;
  color: #0f172a;
  border-color: #38bdf8;
}

.control-actions button:disabled { cursor: default; opacity: .72; }

@media (hover: hover) and (pointer: fine) {
  .glass-icon-button:hover { background: rgba(255, 255, 255, 0.18); transform: scale(1.05); }
  .speed-presets button:hover { background: rgba(56, 189, 248, 0.2); color: #38bdf8; }
  .control-actions button:hover { background: rgba(255, 255, 255, 0.15); color: #fff; transform: translateY(-1px); }
  .control-actions button.primary-control:hover { background: #7dd3fc; color: #0f172a; }
}

@media (max-width: 900px) {
  .cosmos-header {
    top: max(.85rem, env(safe-area-inset-top));
    left: max(.85rem, env(safe-area-inset-left));
    right: max(.85rem, env(safe-area-inset-right));
    gap: .75rem;
  }
  .cosmos-info {
    top: calc(max(.85rem, env(safe-area-inset-top)) + 3.6rem);
    left: max(.85rem, env(safe-area-inset-left));
    right: max(.85rem, env(safe-area-inset-right));
    min-width: 0;
    padding: .8rem 1rem;
    border-radius: 14px;
  }
  .cosmos-info h2 { margin-bottom: .45rem; font-size: 1.15rem; }
  .cosmos-info dl { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .55rem; }
  .cosmos-info dl div { display: block; min-width: 0; }
  .cosmos-info dd { margin-top: .1rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .cosmos-controls {
    right: max(.85rem, env(safe-area-inset-right));
    bottom: max(.85rem, env(safe-area-inset-bottom));
    left: max(.85rem, env(safe-area-inset-left));
    width: auto;
    transform: none;
    flex-direction: column;
    align-items: stretch;
    gap: .75rem;
    padding: .8rem 1rem;
    border-radius: 18px;
  }
  .speed-control { min-width: 0; }
  .speed-control input[type="range"] { min-height: 24px; }
  .speed-presets button { min-width: 40px; min-height: 32px; }
  .control-actions { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .control-actions button { min-height: 44px; justify-content: center; padding: .5rem .6rem; }
}

@media (max-width: 575.98px) {
  .cosmos-vignette { background: radial-gradient(circle at center, transparent 34%, rgba(2, 4, 13, .72) 100%); }
  .cosmos-header p { display: none; }
  .cosmos-header h1 { font-size: 1.05rem; }
  .glass-icon-button { width: 44px; height: 44px; }
  .live-indicator { padding: .35rem .55rem; font-size: .68rem; }
  .cosmos-info p { font-size: .66rem; }
  .cosmos-info span { font-size: .72rem; }
  .cosmos-info dl { font-size: .72rem; }
  .speed-presets { gap: .2rem; }
  .speed-presets button { flex: 1 1 0; padding: .15rem .2rem; }
  .control-actions button { font-size: .75rem; }
}

@media (max-height: 520px) and (orientation: landscape) {
  .cosmos-header {
    top: max(.5rem, env(safe-area-inset-top));
    left: max(.5rem, env(safe-area-inset-left));
    right: max(.5rem, env(safe-area-inset-right));
  }
  .cosmos-header p { display: none; }
  .cosmos-header h1 { font-size: 1rem; }
  .cosmos-info {
    top: calc(max(.5rem, env(safe-area-inset-top)) + 3.25rem);
    left: max(.5rem, env(safe-area-inset-left));
    right: auto;
    width: min(32vw, 230px);
    padding: .65rem .8rem;
  }
  .cosmos-info dl { display: none; }
  .cosmos-info h2 { margin: 0; font-size: 1rem; }
  .cosmos-controls {
    right: max(.5rem, env(safe-area-inset-right));
    bottom: max(.5rem, env(safe-area-inset-bottom));
    left: auto;
    width: min(67vw, 650px);
    flex-direction: row;
    align-items: center;
    gap: .7rem;
    padding: .55rem .7rem;
  }
  .speed-control { flex: 1 1 auto; }
  .speed-presets { display: none; }
  .control-actions { flex: 0 0 auto; display: flex; }
  .control-actions button { min-height: 42px; padding: .4rem .6rem; }
}

@media (prefers-reduced-motion: reduce) {
  .glass-icon-button,
  .control-actions button { transition: background-color 120ms ease, color 120ms ease, border-color 120ms ease; }
}
</style>
