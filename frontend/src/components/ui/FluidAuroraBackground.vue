<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

const canvasRef = ref<HTMLCanvasElement | null>(null)
let animId: number | null = null

interface FluidOrb {
  baseXRatio: number
  baseYRatio: number
  radiusRatio: number
  freqX1: number
  freqX2: number
  freqY1: number
  freqY2: number
  phaseX: number
  phaseY: number
  colorLight: [number, number, number]
  colorDark: [number, number, number]
  alphaLight: number
  alphaDark: number
}

interface BokehParticle {
  xRatio: number
  yRatio: number
  radius: number
  speedY: number
  speedX: number
  alpha: number
  baseAlpha: number
  pulseSpeed: number
  phase: number
}

// 调优后的光团配置：运动速度提升约 1.8 倍，色彩过渡更加生动流畅
const orbs: FluidOrb[] = [
  {
    baseXRatio: 0.22,
    baseYRatio: 0.28,
    radiusRatio: 0.46,
    freqX1: 0.0012,
    freqX2: 0.0008,
    freqY1: 0.0010,
    freqY2: 0.0014,
    phaseX: 0,
    phaseY: 1.2,
    colorLight: [122, 118, 248], // 核心极光紫
    colorDark: [108, 102, 240],
    alphaLight: 0.70,
    alphaDark: 0.60
  },
  {
    baseXRatio: 0.78,
    baseYRatio: 0.72,
    radiusRatio: 0.48,
    freqX1: 0.0009,
    freqX2: 0.0013,
    freqY1: 0.0011,
    freqY2: 0.0007,
    phaseX: 2.1,
    phaseY: 0.5,
    colorLight: [62, 230, 200], // 灵动青碧
    colorDark: [35, 205, 172],
    alphaLight: 0.65,
    alphaDark: 0.55
  },
  {
    baseXRatio: 0.74,
    baseYRatio: 0.24,
    radiusRatio: 0.40,
    freqX1: 0.0014,
    freqX2: 0.0007,
    freqY1: 0.0009,
    freqY2: 0.0012,
    phaseX: 4.0,
    phaseY: 3.1,
    colorLight: [255, 130, 172], // 梦幻樱粉
    colorDark: [230, 90, 142],
    alphaLight: 0.58,
    alphaDark: 0.48
  },
  {
    baseXRatio: 0.26,
    baseYRatio: 0.76,
    radiusRatio: 0.44,
    freqX1: 0.0010,
    freqX2: 0.0012,
    freqY1: 0.0014,
    freqY2: 0.0008,
    phaseX: 1.5,
    phaseY: 4.6,
    colorLight: [255, 198, 80], // 晨曦金光
    colorDark: [240, 170, 50],
    alphaLight: 0.55,
    alphaDark: 0.42
  },
  {
    baseXRatio: 0.50,
    baseYRatio: 0.50,
    radiusRatio: 0.54,
    freqX1: 0.0007,
    freqX2: 0.0011,
    freqY1: 0.0009,
    freqY2: 0.0013,
    phaseX: 3.2,
    phaseY: 2.4,
    colorLight: [148, 126, 255], // 深邃极光紫
    colorDark: [120, 90, 240],
    alphaLight: 0.62,
    alphaDark: 0.52
  }
]

const bokehList: BokehParticle[] = []

// 鼠标视差平滑插值
let mouseXRatio = 0.5
let mouseYRatio = 0.5
let targetMouseX = 0.5
let targetMouseY = 0.5

function initBokeh() {
  bokehList.length = 0
  const count = 36
  for (let i = 0; i < count; i++) {
    const baseAlpha = Math.random() * 0.45 + 0.22
    bokehList.push({
      xRatio: Math.random(),
      yRatio: Math.random(),
      radius: Math.random() * 2.8 + 1.2,
      speedY: -(Math.random() * 0.0005 + 0.00025), // 粒子上升速度同步提速
      speedX: (Math.random() - 0.5) * 0.00024,
      alpha: baseAlpha,
      baseAlpha,
      pulseSpeed: Math.random() * 0.003 + 0.0015,
      phase: Math.random() * Math.PI * 2
    })
  }
}

function resizeCanvas() {
  const canvas = canvasRef.value
  if (!canvas) return
  const dpr = window.devicePixelRatio || 1
  const w = window.innerWidth
  const h = window.innerHeight
  canvas.width = w * dpr
  canvas.height = h * dpr
}

function draw(timestamp: number) {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const dpr = window.devicePixelRatio || 1
  const w = window.innerWidth
  const h = window.innerHeight

  if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
    canvas.width = w * dpr
    canvas.height = h * dpr
  }

  const isDark = document.documentElement.getAttribute('data-theme') === 'dark'

  ctx.save()
  ctx.scale(dpr, dpr)

  // 1. 底色渐变
  if (isDark) {
    const bgGrad = ctx.createLinearGradient(0, 0, w, h)
    bgGrad.addColorStop(0, '#0c0d14')
    bgGrad.addColorStop(0.5, '#12141f')
    bgGrad.addColorStop(1, '#0b0c13')
    ctx.fillStyle = bgGrad
  } else {
    const bgGrad = ctx.createLinearGradient(0, 0, w, h)
    bgGrad.addColorStop(0, '#eef0f9')
    bgGrad.addColorStop(0.5, '#f4f5fc')
    bgGrad.addColorStop(1, '#ebedf8')
    ctx.fillStyle = bgGrad
  }
  ctx.fillRect(0, 0, w, h)

  // 2. 鼠标视差平滑跟随
  mouseXRatio += (targetMouseX - mouseXRatio) * 0.05
  mouseYRatio += (targetMouseY - mouseYRatio) * 0.05
  const offsetX = (mouseXRatio - 0.5) * 90
  const offsetY = (mouseYRatio - 0.5) * 70

  // 3. 流动多色极光团渲染（动态加速）
  const minDim = Math.min(w, h)
  for (const orb of orbs) {
    const shiftX =
      Math.sin(timestamp * orb.freqX1 + orb.phaseX) * 0.18 +
      Math.cos(timestamp * orb.freqX2) * 0.09
    const shiftY =
      Math.cos(timestamp * orb.freqY1 + orb.phaseY) * 0.18 +
      Math.sin(timestamp * orb.freqY2) * 0.09
    const pulse = 1 + Math.sin(timestamp * 0.0014 + orb.phaseX) * 0.16

    const cx = (orb.baseXRatio + shiftX) * w + offsetX
    const cy = (orb.baseYRatio + shiftY) * h + offsetY
    const r = orb.radiusRatio * minDim * pulse

    const rgb = isDark ? orb.colorDark : orb.colorLight
    const alpha = isDark ? orb.alphaDark : orb.alphaLight

    const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(10, r))
    grad.addColorStop(0, `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha})`)
    grad.addColorStop(0.42, `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${(alpha * 0.48).toFixed(3)})`)
    grad.addColorStop(0.78, `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${(alpha * 0.14).toFixed(3)})`)
    grad.addColorStop(1, 'rgba(0, 0, 0, 0)')

    ctx.beginPath()
    ctx.arc(cx, cy, Math.max(10, r), 0, Math.PI * 2)
    ctx.fillStyle = grad
    ctx.fill()
  }

  // 4. 浮光微粒 (Bokeh Sparks)
  for (const b of bokehList) {
    b.yRatio += b.speedY
    b.xRatio += b.speedX + Math.sin(timestamp * 0.0015 + b.phase) * 0.00015
    b.alpha = b.baseAlpha * (0.55 + 0.45 * Math.sin(timestamp * b.pulseSpeed + b.phase))

    if (b.yRatio < -0.05) b.yRatio = 1.05
    if (b.xRatio < -0.05) b.xRatio = 1.05
    if (b.xRatio > 1.05) b.xRatio = -0.05

    const bx = b.xRatio * w
    const by = b.yRatio * h

    ctx.beginPath()
    ctx.arc(bx, by, b.radius, 0, Math.PI * 2)
    ctx.fillStyle = isDark
      ? `rgba(220, 225, 255, ${b.alpha.toFixed(3)})`
      : `rgba(135, 130, 245, ${b.alpha.toFixed(3)})`
    ctx.shadowColor = isDark ? 'rgba(255, 255, 255, 0.6)' : 'rgba(125, 120, 245, 0.4)'
    ctx.shadowBlur = 6
    ctx.fill()
    ctx.shadowBlur = 0
  }

  ctx.restore()
  animId = requestAnimationFrame(draw)
}

function handleMouseMove(e: MouseEvent) {
  targetMouseX = e.clientX / window.innerWidth
  targetMouseY = e.clientY / window.innerHeight
}

function handleVisibility() {
  if (document.hidden) {
    if (animId) {
      cancelAnimationFrame(animId)
      animId = null
    }
  } else {
    if (!animId) {
      animId = requestAnimationFrame(draw)
    }
  }
}

onMounted(() => {
  resizeCanvas()
  initBokeh()
  animId = requestAnimationFrame(draw)
  window.addEventListener('resize', resizeCanvas, { passive: true })
  window.addEventListener('mousemove', handleMouseMove, { passive: true })
  document.addEventListener('visibilitychange', handleVisibility)
})

onBeforeUnmount(() => {
  if (animId) cancelAnimationFrame(animId)
  window.removeEventListener('resize', resizeCanvas)
  window.removeEventListener('mousemove', handleMouseMove)
  document.removeEventListener('visibilitychange', handleVisibility)
})
</script>

<template>
  <div class="fluid-aurora-bg" aria-hidden="true">
    <canvas ref="canvasRef" class="fluid-canvas" />
    <div class="fluid-vignette" />
  </div>
</template>

<style scoped>
.fluid-aurora-bg {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  z-index: 0;
}

.fluid-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  filter: blur(24px);
  transform: scale(1.05); /* 防止边缘模糊留白 */
}

.fluid-vignette {
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at center, transparent 40%, rgba(0, 0, 0, 0.04) 100%);
  pointer-events: none;
}

html[data-theme="dark"] .fluid-vignette {
  background: radial-gradient(circle at center, transparent 35%, rgba(0, 0, 0, 0.35) 100%);
}
</style>
