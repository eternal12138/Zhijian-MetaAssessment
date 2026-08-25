<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import LiangIntensityCalibrator from '../easteregg/LiangIntensityCalibrator.vue'

const containerRef = ref<HTMLDivElement | null>(null)
const canvasRef = ref<HTMLCanvasElement | null>(null)
let animId: number | null = null
let resizeObserver: ResizeObserver | null = null

interface Planet {
  radiusX: number        // 椭圆长半轴
  radiusY: number        // 椭圆短半轴
  tiltAngle: number      // 轨道倾斜角度 (弧度)
  baseSpeed: number      // 基础角速度
  angle: number          // 当前角度 (弧度)
  planetRadius: number   // 小球半径
  color: string          // 小球颜色
  tailColor: [number, number, number] // 拖尾 RGB
  baseTailLength: number // 基础拖尾弧度
}

interface CosmicStar {
  xRatio: number
  yRatio: number
  size: number
  baseAlpha: number
  alpha: number
  twinkleSpeed: number
  phase: number
  colorType: 'white' | 'blue' | 'gold' | 'pink'
}

interface CosmicNebula {
  xRatio: number
  yRatio: number
  radiusRatio: number
  freqX: number
  freqY: number
  phase: number
  colorLight: [number, number, number]
  colorDark: [number, number, number]
  alphaLight: number
  alphaDark: number
}

interface Stardust {
  x: number
  y: number
  vx: number
  vy: number
  size: number
  color: [number, number, number]
  alpha: number
  decay: number
}

interface Shockwave {
  x: number
  y: number
  radius: number
  maxRadius: number
  alpha: number
  speed: number
  lineWidth: number
  color: string
}

// 动态卡片尺寸与中心星坐标
let canvasWidth = 800
let canvasHeight = 220
let centerStarX = 640
let centerStarY = 110
const CENTER_TRIGGER_RADIUS = 48
const showHeroCalibrator = ref(false)
let lastHeroClickTime = 0 // 判定在中心球上的半径阈值

const planets: Planet[] = [
  {
    radiusX: 90,
    radiusY: 36,
    tiltAngle: -0.42,   // 约 -24度
    baseSpeed: 0.022,
    angle: 0.4,
    planetRadius: 6.5,
    color: '#ffcd42',
    tailColor: [255, 205, 66],
    baseTailLength: 0.95
  },
  {
    radiusX: 110,
    radiusY: 46,
    tiltAngle: 0.66,    // 约 +38度
    baseSpeed: 0.015,
    angle: 2.7,
    planetRadius: 7.5,
    color: '#4ee6cb',
    tailColor: [78, 230, 203],
    baseTailLength: 1.15
  },
  {
    radiusX: 82,
    radiusY: 54,
    tiltAngle: -1.02,   // 约 -58度
    baseSpeed: 0.026,
    angle: 4.8,
    planetRadius: 6.0,
    color: '#ff7d8d',
    tailColor: [255, 125, 141],
    baseTailLength: 0.85
  }
]

const cosmicStars: CosmicStar[] = []
const cosmicNebulas: CosmicNebula[] = [
  {
    xRatio: 0.82,
    yRatio: 0.48,
    radiusRatio: 0.65,
    freqX: 0.0012,
    freqY: 0.0009,
    phase: 0,
    colorLight: [98, 88, 238],
    colorDark: [68, 58, 208],
    alphaLight: 0.65,
    alphaDark: 0.55
  },
  {
    xRatio: 0.65,
    yRatio: 0.35,
    radiusRatio: 0.55,
    freqX: 0.0008,
    freqY: 0.0014,
    phase: 1.8,
    colorLight: [62, 220, 195],
    colorDark: [35, 190, 165],
    alphaLight: 0.45,
    alphaDark: 0.38
  },
  {
    xRatio: 0.25,
    yRatio: 0.65,
    radiusRatio: 0.70,
    freqX: 0.0010,
    freqY: 0.0007,
    phase: 3.2,
    colorLight: [75, 65, 190],
    colorDark: [45, 38, 145],
    alphaLight: 0.60,
    alphaDark: 0.50
  },
  {
    xRatio: 0.45,
    yRatio: 0.30,
    radiusRatio: 0.48,
    freqX: 0.0013,
    freqY: 0.0011,
    phase: 4.6,
    colorLight: [235, 110, 165],
    colorDark: [205, 75, 135],
    alphaLight: 0.35,
    alphaDark: 0.28
  }
]

const stardusts: Stardust[] = []
const shockwaves: Shockwave[] = []

// 交互状态与宇宙共鸣插值
const isCursorOnCenter = ref(false)
let cosmicHoverIntensity = 0 // 0 -> 1 平滑插值
let currentScaleFactor = 1.0
let currentSpeedMultiplier = 1.0
let rippleRadius = 34
let rippleAlpha = 0
let clickEnergyBoost = 0

// 标准矢量灯泡 Path (24x24 视口)
const bulbHeadPath = new Path2D(
  'M 12 2 C 7.58 2 4 5.58 4 10 C 4 12.8 5.4 15.28 7.5 16.7 L 7.5 19 C 7.5 19.55 7.95 20 8.5 20 L 15.5 20 C 16.05 20 16.5 19.55 16.5 19 L 16.5 16.7 C 18.6 15.28 20 12.8 20 10 C 20 5.58 16.42 2 12 2 Z'
)
const bulbScrewPath = new Path2D(
  'M 9 21 C 9 21.55 9.45 22 10 22 L 14 22 C 14.55 22 15 21.55 15 21 L 15 20.5 L 9 20.5 Z'
)

// 初始化宇宙背景繁星
function initCosmicStars() {
  cosmicStars.length = 0
  const count = 75
  const types: Array<'white' | 'blue' | 'gold' | 'pink'> = ['white', 'blue', 'gold', 'pink']
  for (let i = 0; i < count; i++) {
    const baseAlpha = Math.random() * 0.55 + 0.25
    cosmicStars.push({
      xRatio: Math.random(),
      yRatio: Math.random(),
      size: Math.random() * 1.8 + 0.7,
      baseAlpha,
      alpha: baseAlpha,
      twinkleSpeed: Math.random() * 0.003 + 0.0015,
      phase: Math.random() * Math.PI * 2,
      colorType: types[Math.floor(Math.random() * types.length)]
    })
  }
}

// 椭圆空间旋转变换
function getOrbitPos(p: Planet, angle: number, scaleFactor: number) {
  const a = p.radiusX * scaleFactor
  const b = p.radiusY * scaleFactor
  const x0 = a * Math.cos(angle)
  const y0 = b * Math.sin(angle)
  const cosT = Math.cos(p.tiltAngle)
  const sinT = Math.sin(p.tiltAngle)
  const x = centerStarX + (x0 * cosT - y0 * sinT)
  const y = centerStarY + (x0 * sinT + y0 * cosT)
  const z = y0 // z > 0 为前景（在恒星前方），z < 0 为背景（在恒星后方）
  return { x, y, z }
}

// 绘制宇宙星云与动态背景
function drawCosmicBackground(ctx: CanvasRenderingContext2D, t: number, isDark: boolean) {
  const w = canvasWidth
  const h = canvasHeight

  // 1. 基础深邃宇宙渐变
  const spaceGrad = ctx.createLinearGradient(0, 0, w, h)
  if (isDark) {
    spaceGrad.addColorStop(0, '#151336')
    spaceGrad.addColorStop(0.5, '#1e1a4d')
    spaceGrad.addColorStop(1, '#271f5c')
  } else {
    spaceGrad.addColorStop(0, '#36329c')
    spaceGrad.addColorStop(0.45, '#4b45be')
    spaceGrad.addColorStop(0.8, '#5d54db')
    spaceGrad.addColorStop(1, '#725fe8')
  }
  ctx.fillStyle = spaceGrad
  ctx.fillRect(0, 0, w, h)

  // 2. 动态流动星云光斑 (Cosmic Nebulas)
  const hoverBoost = cosmicHoverIntensity * 0.35
  for (const neb of cosmicNebulas) {
    const shiftX = Math.sin(t * neb.freqX + neb.phase) * 0.08
    const shiftY = Math.cos(t * neb.freqY + neb.phase) * 0.08
    const pulse = 1 + Math.sin(t * 0.0015 + neb.phase) * 0.12 + hoverBoost * 0.2

    const cx = (neb.xRatio + shiftX) * w
    const cy = (neb.yRatio + shiftY) * h
    const r = neb.radiusRatio * Math.max(w, h) * 0.5 * pulse

    const rgb = isDark ? neb.colorDark : neb.colorLight
    const alpha = (isDark ? neb.alphaDark : neb.alphaLight) + hoverBoost * 0.2

    const nebGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, r)
    nebGrad.addColorStop(0, `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha.toFixed(3)})`)
    nebGrad.addColorStop(0.5, `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${(alpha * 0.45).toFixed(3)})`)
    nebGrad.addColorStop(0.85, `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${(alpha * 0.1).toFixed(3)})`)
    nebGrad.addColorStop(1, 'rgba(0, 0, 0, 0)')

    ctx.beginPath()
    ctx.arc(cx, cy, r, 0, Math.PI * 2)
    ctx.fillStyle = nebGrad
    ctx.fill()
  }

  // 3. 宇宙背景闪烁繁星 (Twinkling Cosmic Stars)
  for (const s of cosmicStars) {
    const twinkle = 0.6 + 0.4 * Math.sin(t * (s.twinkleSpeed * (1 + cosmicHoverIntensity * 1.5)) + s.phase)
    const curAlpha = s.baseAlpha * twinkle + cosmicHoverIntensity * 0.2

    let starRGB = '255, 255, 255'
    if (s.colorType === 'blue') starRGB = '160, 225, 255'
    else if (s.colorType === 'gold') starRGB = '255, 220, 140'
    else if (s.colorType === 'pink') starRGB = '255, 180, 210'

    const sx = s.xRatio * w
    const sy = s.yRatio * h

    ctx.beginPath()
    ctx.arc(sx, sy, s.size, 0, Math.PI * 2)
    ctx.fillStyle = `rgba(${starRGB}, ${Math.min(1, curAlpha).toFixed(3)})`
    ctx.fill()

    // 较亮星星自带十字微光晕
    if (s.size > 1.8 && curAlpha > 0.4) {
      ctx.save()
      ctx.strokeStyle = `rgba(${starRGB}, ${(curAlpha * 0.35).toFixed(3)})`
      ctx.lineWidth = 0.75
      ctx.beginPath()
      ctx.moveTo(sx - 3.5, sy)
      ctx.lineTo(sx + 3.5, sy)
      ctx.moveTo(sx, sy - 3.5)
      ctx.lineTo(sx, sy + 3.5)
      ctx.stroke()
      ctx.restore()
    }
  }

  // 4. 悬停时中心恒星向整个宇宙激发的引力涟漪波
  if (cosmicHoverIntensity > 0.05) {
    const warpRadius = 120 + Math.sin(t * 0.003) * 20
    const waveGrad = ctx.createRadialGradient(centerStarX, centerStarY, 40, centerStarX, centerStarY, warpRadius + 80)
    waveGrad.addColorStop(0, `rgba(255, 255, 255, ${(0.15 * cosmicHoverIntensity).toFixed(3)})`)
    waveGrad.addColorStop(0.5, `rgba(140, 125, 255, ${(0.08 * cosmicHoverIntensity).toFixed(3)})`)
    waveGrad.addColorStop(1, 'rgba(0, 0, 0, 0)')

    ctx.beginPath()
    ctx.arc(centerStarX, centerStarY, warpRadius + 80, 0, Math.PI * 2)
    ctx.fillStyle = waveGrad
    ctx.fill()
  }
}

// 绘制中心恒星（白色发光球体 + 高清矢量发光灯泡 + 引力波）
function drawCenterStar(ctx: CanvasRenderingContext2D, t: number) {
  const hoverActive = isCursorOnCenter.value
  const pulse = Math.sin(t * 0.003) * 1.8
  const baseRadius = 33 + pulse + (hoverActive ? 3.5 : 0)

  // 1. 引力波涟漪环（悬停在中心球时持续扩散）
  if (rippleAlpha > 0.01) {
    ctx.beginPath()
    ctx.arc(centerStarX, centerStarY, rippleRadius, 0, Math.PI * 2)
    ctx.strokeStyle = `rgba(255, 255, 255, ${rippleAlpha})`
    ctx.lineWidth = 2.4
    ctx.stroke()
  }

  // 2. 恒星外层辉光（Corona Glow）—— 无方框边界约束，自然融入全景宇宙
  const glowMult = hoverActive ? 1.5 : 1.0
  const outerGlow = ctx.createRadialGradient(
    centerStarX,
    centerStarY,
    baseRadius * 0.6,
    centerStarX,
    centerStarY,
    baseRadius * 3.2 * glowMult
  )
  outerGlow.addColorStop(0, 'rgba(255, 255, 255, 0.65)')
  outerGlow.addColorStop(0.35, hoverActive ? 'rgba(255, 215, 110, 0.45)' : 'rgba(255, 215, 110, 0.25)')
  outerGlow.addColorStop(0.7, 'rgba(135, 130, 248, 0.18)')
  outerGlow.addColorStop(1, 'rgba(125, 123, 242, 0)')
  ctx.beginPath()
  ctx.arc(centerStarX, centerStarY, baseRadius * 3.2 * glowMult, 0, Math.PI * 2)
  ctx.fillStyle = outerGlow
  ctx.fill()

  // 3. 恒星实体白色球心
  ctx.save()
  ctx.shadowColor = hoverActive ? 'rgba(255, 255, 255, 0.95)' : 'rgba(255, 255, 255, 0.65)'
  ctx.shadowBlur = hoverActive ? 28 : 18
  ctx.beginPath()
  ctx.arc(centerStarX, centerStarY, baseRadius, 0, Math.PI * 2)
  ctx.fillStyle = '#ffffff'
  ctx.fill()
  ctx.restore()

  // 4. 矢量灯泡图标（居中、自发光）
  ctx.save()
  ctx.translate(centerStarX, centerStarY)
  ctx.scale(1.4, 1.4)
  ctx.translate(-12, -12) // 将 24x24 视口居中
  ctx.fillStyle = '#ffb326'
  ctx.shadowColor = 'rgba(255, 179, 38, 0.7)'
  ctx.shadowBlur = hoverActive ? 12 : 6
  ctx.fill(bulbHeadPath)
  ctx.fill(bulbScrewPath)
  ctx.restore()
}

// 绘制单颗行星及其流光拖尾
function drawPlanet(
  ctx: CanvasRenderingContext2D,
  p: Planet,
  pos: { x: number; y: number; z: number },
  tailLen: number,
  scaleFactor: number
) {
  const steps = 42
  const stepAngle = tailLen / steps

  // 1. 绘制渐变流光拖尾
  for (let i = steps; i >= 1; i--) {
    const a1 = p.angle - i * stepAngle
    const a2 = p.angle - (i - 1) * stepAngle
    const pos1 = getOrbitPos(p, a1, scaleFactor)
    const pos2 = getOrbitPos(p, a2, scaleFactor)

    const progress = 1 - (i - 1) / steps
    const segmentAlpha = Math.pow(progress, 2.2) * 0.85
    const segmentWidth = p.planetRadius * (0.2 + progress * 0.95) * 1.8

    ctx.beginPath()
    ctx.moveTo(pos1.x, pos1.y)
    ctx.lineTo(pos2.x, pos2.y)
    ctx.strokeStyle = `rgba(${p.tailColor[0]}, ${p.tailColor[1]}, ${p.tailColor[2]}, ${segmentAlpha})`
    ctx.lineWidth = segmentWidth
    ctx.lineCap = 'round'
    ctx.stroke()
  }

  // 2. 行星本体
  const hoverActive = isCursorOnCenter.value
  ctx.save()
  ctx.shadowColor = p.color
  ctx.shadowBlur = hoverActive ? 22 : 12
  ctx.beginPath()
  ctx.arc(pos.x, pos.y, p.planetRadius, 0, Math.PI * 2)
  ctx.fillStyle = p.color
  ctx.fill()

  // 3. 高光核心点
  ctx.beginPath()
  ctx.arc(pos.x - p.planetRadius * 0.28, pos.y - p.planetRadius * 0.28, p.planetRadius * 0.35, 0, Math.PI * 2)
  ctx.fillStyle = 'rgba(255, 255, 255, 0.85)'
  ctx.fill()
  ctx.restore()
}

// 主渲染动画循环
function draw(timestamp: number) {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const dpr = window.devicePixelRatio || 1
  if (canvas.width !== canvasWidth * dpr || canvas.height !== canvasHeight * dpr) {
    canvas.width = canvasWidth * dpr
    canvas.height = canvasHeight * dpr
  }

  const isDark = document.documentElement.getAttribute('data-theme') === 'dark'

  ctx.save()
  ctx.scale(dpr, dpr)

  // 1. 宇宙悬停平滑插值
  const targetHover = isCursorOnCenter.value ? 1 : 0
  cosmicHoverIntensity += (targetHover - cosmicHoverIntensity) * 0.08

  // 2. 绘制全景动态宇宙背景
  drawCosmicBackground(ctx, timestamp, isDark)

  // 3. 动态引力参数更新
  const targetScale = isCursorOnCenter.value ? 1.08 : 1.0
  const targetSpeed = isCursorOnCenter.value ? 2.2 : 1.0
  currentScaleFactor += (targetScale - currentScaleFactor) * 0.08
  currentSpeedMultiplier += (targetSpeed - currentSpeedMultiplier) * 0.08

  if (clickEnergyBoost > 0) {
    clickEnergyBoost = Math.max(0, clickEnergyBoost - 0.02)
  }

  // 4. 引力波动画
  if (isCursorOnCenter.value) {
    rippleRadius += 1.8
    rippleAlpha = Math.max(0, 0.6 * (1 - (rippleRadius - 34) / 75))
    if (rippleRadius > 109) {
      rippleRadius = 34
      rippleAlpha = 0.6
    }
  } else {
    rippleAlpha = Math.max(0, rippleAlpha - 0.04)
  }

  // 5. 计算行星位置与深度排序
  const renderedPlanets = planets.map(p => {
    const distToCenter = Math.sqrt(
      Math.pow(p.radiusX * Math.cos(p.angle), 2) + Math.pow(p.radiusY * Math.sin(p.angle), 2)
    )
    const meanRadius = (p.radiusX + p.radiusY) / 2
    const gravityAccel = 1 + (1 - distToCenter / (p.radiusX * 1.1)) * 0.8
    const finalSpeed = p.baseSpeed * currentSpeedMultiplier * (1 + clickEnergyBoost * 1.5) * gravityAccel

    p.angle = (p.angle + finalSpeed) % (Math.PI * 2)

    const tailLen = p.baseTailLength * (1 + (currentSpeedMultiplier - 1) * 0.6 + clickEnergyBoost * 0.8)
    const pos = getOrbitPos(p, p.angle, currentScaleFactor)
    return { planet: p, pos, tailLen }
  })

  // 背景行星 (z < 0)
  const backPlanets = renderedPlanets.filter(item => item.pos.z < 0)
  // 前景行星 (z >= 0)
  const frontPlanets = renderedPlanets.filter(item => item.pos.z >= 0)

  // 6. 绘制背景层行星
  for (const item of backPlanets) {
    drawPlanet(ctx, item.planet, item.pos, item.tailLen, currentScaleFactor)
  }

  // 7. 绘制中心发光恒星
  drawCenterStar(ctx, timestamp)

  // 8. 绘制前景层行星
  for (const item of frontPlanets) {
    drawPlanet(ctx, item.planet, item.pos, item.tailLen, currentScaleFactor)
  }

  // 9. 绘制超新星冲击波 (Shockwaves)
  for (let i = shockwaves.length - 1; i >= 0; i--) {
    const sw = shockwaves[i]
    sw.radius += sw.speed
    sw.alpha = Math.max(0, 1 - sw.radius / sw.maxRadius)
    if (sw.alpha <= 0) {
      shockwaves.splice(i, 1)
      continue
    }

    ctx.save()
    ctx.beginPath()
    ctx.arc(sw.x, sw.y, sw.radius, 0, Math.PI * 2)
    ctx.strokeStyle = sw.color.replace('ALPHA', sw.alpha.toFixed(3))
    ctx.lineWidth = sw.lineWidth * (1 - sw.radius / sw.maxRadius * 0.5)
    ctx.stroke()
    ctx.restore()
  }

  // 10. 绘制星尘火花 (Stardusts)
  for (let i = stardusts.length - 1; i >= 0; i--) {
    const sd = stardusts[i]
    sd.x += sd.vx
    sd.y += sd.vy
    sd.vx *= 0.94
    sd.vy *= 0.94
    sd.alpha -= sd.decay

    if (sd.alpha <= 0) {
      stardusts.splice(i, 1)
      continue
    }

    ctx.save()
    ctx.beginPath()
    ctx.arc(sd.x, sd.y, sd.size, 0, Math.PI * 2)
    ctx.fillStyle = `rgba(${sd.color[0]}, ${sd.color[1]}, ${sd.color[2]}, ${sd.alpha.toFixed(3)})`
    ctx.shadowColor = `rgb(${sd.color[0]}, ${sd.color[1]}, ${sd.color[2]})`
    ctx.shadowBlur = 6
    ctx.fill()
    ctx.restore()
  }

  ctx.restore()
  animId = requestAnimationFrame(draw)
}

function updateDimensions() {
  const container = containerRef.value
  if (!container) return
  const rect = container.getBoundingClientRect()
  canvasWidth = Math.max(300, Math.round(rect.width))
  canvasHeight = Math.max(160, Math.round(rect.height))

  // 根据卡片宽度自适应恒星位置：宽屏靠右（约右侧 150px），小屏居中
  if (canvasWidth > 640) {
    centerStarX = canvasWidth - 145
    centerStarY = canvasHeight / 2
  } else {
    centerStarX = canvasWidth * 0.78
    centerStarY = canvasHeight / 2
  }
}

function handleMouseMove(e: MouseEvent) {
  const container = containerRef.value
  if (!container) return
  const rect = container.getBoundingClientRect()
  const mouseX = e.clientX - rect.left
  const mouseY = e.clientY - rect.top

  const dx = mouseX - centerStarX
  const dy = mouseY - centerStarY
  const dist = Math.sqrt(dx * dx + dy * dy)

  isCursorOnCenter.value = dist <= CENTER_TRIGGER_RADIUS
}

function handleMouseLeave() {
  isCursorOnCenter.value = false
}

function handleClick(e: MouseEvent) {
  const now = Date.now()
  // 严格按要求：连续点击两次且两次间隔小于 1.5 秒 (1500ms) 时呼出滑动变祖器
  if (lastHeroClickTime > 0 && (now - lastHeroClickTime) < 1500) {
    showHeroCalibrator.value = true
    lastHeroClickTime = 0
  } else {
    lastHeroClickTime = now
  }
  const container = containerRef.value
  if (!container) return
  const rect = container.getBoundingClientRect()
  const clickX = e.clientX - rect.left
  const clickY = e.clientY - rect.top

  const dx = clickX - centerStarX
  const dy = clickY - centerStarY
  const dist = Math.sqrt(dx * dx + dy * dy)

  if (dist <= CENTER_TRIGGER_RADIUS + 25) {
    clickEnergyBoost = 1.0

    // 双重超新星冲击波
    shockwaves.push({
      x: centerStarX,
      y: centerStarY,
      radius: 35,
      maxRadius: 180,
      alpha: 1,
      speed: 4.8,
      lineWidth: 3.5,
      color: 'rgba(255, 255, 255, ALPHA)'
    })
    shockwaves.push({
      x: centerStarX,
      y: centerStarY,
      radius: 20,
      maxRadius: 240,
      alpha: 0.9,
      speed: 3.2,
      lineWidth: 2.2,
      color: 'rgba(255, 215, 100, ALPHA)'
    })

    // 迸发 24 颗星尘微粒
    const sparkColors: [number, number, number][] = [
      [255, 205, 66],
      [78, 230, 203],
      [255, 125, 141],
      [255, 255, 255]
    ]
    for (let i = 0; i < 24; i++) {
      const angle = (Math.PI * 2 * i) / 24 + (Math.random() - 0.5) * 0.3
      const speed = Math.random() * 5.5 + 2.5
      stardusts.push({
        x: centerStarX,
        y: centerStarY,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        size: Math.random() * 2.8 + 1.2,
        color: sparkColors[i % sparkColors.length],
        alpha: 1.0,
        decay: Math.random() * 0.02 + 0.015
      })
    }
  }
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
  initCosmicStars()
  updateDimensions()
  animId = requestAnimationFrame(draw)

  if (containerRef.value) {
    resizeObserver = new ResizeObserver(() => {
      updateDimensions()
    })
    resizeObserver.observe(containerRef.value)
  }

  document.addEventListener('visibilitychange', handleVisibility)
})

onBeforeUnmount(() => {
  if (animId) cancelAnimationFrame(animId)
  if (resizeObserver) resizeObserver.disconnect()
  document.removeEventListener('visibilitychange', handleVisibility)
})
</script>

<template>
  <div
    ref="containerRef"
    class="planet-orbit-container"
    :class="{ 'center-hovered': isCursorOnCenter }"
    aria-label="行星环绕引力动效，悬停中间球或点击触发共鸣"
    @mousemove="handleMouseMove"
    @mouseleave="handleMouseLeave"
    @click="handleClick"
  >
    <canvas ref="canvasRef" class="planet-canvas" />
    <LiangIntensityCalibrator v-model="showHeroCalibrator" />
  </div>
</template>

<style scoped>
.planet-orbit-container {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  border-radius: inherit;
  overflow: hidden;
  user-select: none;
  cursor: default;
  z-index: 0;
  pointer-events: auto;
}

.planet-orbit-container.center-hovered {
  cursor: pointer;
}

.planet-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
}
</style>
