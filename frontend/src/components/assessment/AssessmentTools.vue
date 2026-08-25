<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useTheme } from '../../composables/useTheme'

type ToolName = 'calculator' | 'scratchpad'
type ToolEvent = {
  tool: ToolName
  action: 'opened' | 'closed' | 'calculated' | 'undo' | 'cleared'
}
type Point = { x: number; y: number }
type TaskImage = { src: string; title: string; alt: string }

const props = defineProps<{
  taskKey: string
  taskTitle: string
  taskScenario: string
  taskImage?: TaskImage | null
  taskUnitNote?: string | null
}>()
const emit = defineEmits<{
  event: [value: ToolEvent]
}>()
const { theme } = useTheme()

const toolsOpen = ref(false)
const calculatorExpanded = ref(false)
const expression = ref('')
const calculatorResult = ref('0')
const calculatorError = ref('')
const calculatorPanel = ref<HTMLElement | null>(null)
const calculatorPosition = ref<Point | null>(null)
const calculatorDragging = ref(false)
const scratchText = ref('')
const canvas = ref<HTMLCanvasElement | null>(null)
const strokes = ref<Point[][]>([])
let activeStroke: Point[] | null = null
let previousBodyOverflow = ''
let calculatorDragPointerId: number | null = null
let calculatorDragOffset: Point = { x: 0, y: 0 }

const calculatorPositionStyle = computed(() => {
  const position = calculatorPosition.value
  if (!position) return undefined
  return {
    left: `${position.x}px`,
    top: `${position.y}px`,
    right: 'auto',
    bottom: 'auto'
  }
})

function clampCalculatorPosition(x: number, y: number): Point {
  const panel = calculatorPanel.value
  const margin = 12
  const width = panel?.offsetWidth ?? 360
  const height = panel?.offsetHeight ?? 520
  return {
    x: Math.min(Math.max(margin, x), Math.max(margin, window.innerWidth - width - margin)),
    y: Math.min(Math.max(margin, y), Math.max(margin, window.innerHeight - height - margin))
  }
}

function startCalculatorDrag(event: PointerEvent) {
  if (window.innerWidth < 768 || event.button !== 0) return
  if ((event.target as HTMLElement).closest('button, input, textarea, select, a')) return
  const panel = calculatorPanel.value
  const handle = event.currentTarget as HTMLElement
  if (!panel) return
  const rect = panel.getBoundingClientRect()
  calculatorPosition.value = { x: rect.left, y: rect.top }
  calculatorDragOffset = { x: event.clientX - rect.left, y: event.clientY - rect.top }
  calculatorDragPointerId = event.pointerId
  calculatorDragging.value = true
  handle.setPointerCapture(event.pointerId)
  event.preventDefault()
}

function moveCalculator(event: PointerEvent) {
  if (!calculatorDragging.value || calculatorDragPointerId !== event.pointerId) return
  calculatorPosition.value = clampCalculatorPosition(
    event.clientX - calculatorDragOffset.x,
    event.clientY - calculatorDragOffset.y
  )
}

function endCalculatorDrag(event: PointerEvent) {
  if (calculatorDragPointerId !== event.pointerId) return
  const handle = event.currentTarget as HTMLElement
  if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId)
  calculatorDragPointerId = null
  calculatorDragging.value = false
}

function resetCalculatorPosition() {
  calculatorPosition.value = null
}

function keepCalculatorInViewport() {
  const position = calculatorPosition.value
  if (position) calculatorPosition.value = clampCalculatorPosition(position.x, position.y)
}

function openTools() {
  if (toolsOpen.value) return
  toolsOpen.value = true
  emit('event', { tool: 'scratchpad', action: 'opened' })
  void nextTick(redrawCanvas)
}

function closeTools() {
  if (!toolsOpen.value) return
  if (calculatorExpanded.value) {
    emit('event', { tool: 'calculator', action: 'closed' })
  }
  calculatorExpanded.value = false
  calculatorDragging.value = false
  calculatorDragPointerId = null
  resetCalculatorPosition()
  toolsOpen.value = false
  emit('event', { tool: 'scratchpad', action: 'closed' })
}

function toggleCalculator() {
  calculatorExpanded.value = !calculatorExpanded.value
  if (!calculatorExpanded.value) resetCalculatorPosition()
  emit('event', {
    tool: 'calculator',
    action: calculatorExpanded.value ? 'opened' : 'closed'
  })
}

function tokenize(source: string): Array<number | string> {
  const normalized = source
    .replace(/×/g, '*')
    .replace(/÷/g, '/')
    .replace(/−/g, '-')
    .replace(/\s+/g, '')
  const tokens: Array<number | string> = []
  let index = 0
  while (index < normalized.length) {
    const char = normalized[index]
    if (/[0-9.]/.test(char)) {
      let end = index + 1
      while (end < normalized.length && /[0-9.]/.test(normalized[end])) end += 1
      const raw = normalized.slice(index, end)
      if ((raw.match(/\./g) ?? []).length > 1) throw new Error('数字格式不正确')
      const value = Number(raw)
      if (!Number.isFinite(value)) throw new Error('数字格式不正确')
      tokens.push(value)
      index = end
      continue
    }
    if ('+-*/()%√'.includes(char)) {
      tokens.push(char)
      index += 1
      continue
    }
    throw new Error('包含不支持的字符')
  }
  return tokens
}

function evaluateExpression(source: string): number {
  const tokens = tokenize(source)
  let cursor = 0
  const peek = () => tokens[cursor]
  const take = () => tokens[cursor++]

  function primary(): number {
    const token = take()
    if (typeof token === 'number') return token
    if (token === '(') {
      const value = expressionLevel()
      if (take() !== ')') throw new Error('缺少右括号')
      return value
    }
    if (token === '√') {
      const value = unary()
      if (value < 0) throw new Error('负数不能开平方')
      return Math.sqrt(value)
    }
    throw new Error('算式不完整')
  }

  function postfix(): number {
    let value = primary()
    while (peek() === '%') {
      take()
      value /= 100
    }
    return value
  }

  function unary(): number {
    if (peek() === '+') {
      take()
      return unary()
    }
    if (peek() === '-') {
      take()
      return -unary()
    }
    return postfix()
  }

  function term(): number {
    let value = unary()
    while (peek() === '*' || peek() === '/') {
      const operator = take()
      const right = unary()
      if (operator === '/' && right === 0) throw new Error('不能除以零')
      value = operator === '*' ? value * right : value / right
    }
    return value
  }

  function expressionLevel(): number {
    let value = term()
    while (peek() === '+' || peek() === '-') {
      const operator = take()
      const right = term()
      value = operator === '+' ? value + right : value - right
    }
    return value
  }

  if (!tokens.length) throw new Error('请输入算式')
  const result = expressionLevel()
  if (cursor !== tokens.length) throw new Error('请检查括号或运算符')
  if (!Number.isFinite(result)) throw new Error('计算结果超出范围')
  return result
}

function calculate() {
  calculatorError.value = ''
  try {
    const result = evaluateExpression(expression.value)
    calculatorResult.value = Number(result.toPrecision(12)).toString()
    emit('event', { tool: 'calculator', action: 'calculated' })
  } catch (error) {
    calculatorError.value = error instanceof Error ? error.message : '无法计算'
  }
}

function pressCalculator(value: string) {
  calculatorError.value = ''
  if (value === 'clear') {
    expression.value = ''
    calculatorResult.value = '0'
    return
  }
  if (value === 'backspace') {
    expression.value = expression.value.slice(0, -1)
    return
  }
  if (value === '=') {
    calculate()
    return
  }
  expression.value += value
}

function onCalculatorKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter') {
    event.preventDefault()
    calculate()
  }
}

const calculatorButtons = [
  { label: 'C', value: 'clear', tone: 'muted' },
  { label: '(', value: '(', tone: 'muted' },
  { label: ')', value: ')', tone: 'muted' },
  { label: '⌫', value: 'backspace', tone: 'muted' },
  { label: '√', value: '√', tone: 'operator' },
  { label: '%', value: '%', tone: 'operator' },
  { label: '÷', value: '÷', tone: 'operator' },
  { label: '×', value: '×', tone: 'operator' },
  { label: '7', value: '7' },
  { label: '8', value: '8' },
  { label: '9', value: '9' },
  { label: '−', value: '−', tone: 'operator' },
  { label: '4', value: '4' },
  { label: '5', value: '5' },
  { label: '6', value: '6' },
  { label: '+', value: '+', tone: 'operator' },
  { label: '1', value: '1' },
  { label: '2', value: '2' },
  { label: '3', value: '3' },
  { label: '=', value: '=', tone: 'equals', tall: true },
  { label: '0', value: '0', wide: true },
  { label: '.', value: '.' }
]

function pointFromEvent(event: PointerEvent): Point {
  const target = canvas.value
  if (!target) return { x: 0, y: 0 }
  const rect = target.getBoundingClientRect()
  return {
    x: (event.clientX - rect.left) * (target.width / rect.width),
    y: (event.clientY - rect.top) * (target.height / rect.height)
  }
}

function drawStroke(context: CanvasRenderingContext2D, points: Point[]) {
  if (!points.length) return
  context.beginPath()
  context.moveTo(points[0].x, points[0].y)
  for (const point of points.slice(1)) context.lineTo(point.x, point.y)
  if (points.length === 1) context.lineTo(points[0].x + 0.1, points[0].y + 0.1)
  context.stroke()
}

function redrawCanvas() {
  const target = canvas.value
  const context = target?.getContext('2d')
  if (!target || !context) return
  context.clearRect(0, 0, target.width, target.height)
  const rootStyles = window.getComputedStyle(document.documentElement)
  context.strokeStyle = rootStyles.getPropertyValue('--color-text').trim() || '#25253d'
  context.lineWidth = 3
  context.lineCap = 'round'
  context.lineJoin = 'round'
  for (const stroke of strokes.value) drawStroke(context, stroke)
}

watch(theme, () => nextTick(redrawCanvas))

function startStroke(event: PointerEvent) {
  const target = canvas.value
  if (!target) return
  target.setPointerCapture(event.pointerId)
  activeStroke = [pointFromEvent(event)]
  strokes.value.push(activeStroke)
  redrawCanvas()
}

function continueStroke(event: PointerEvent) {
  if (!activeStroke) return
  activeStroke.push(pointFromEvent(event))
  redrawCanvas()
}

function endStroke(event: PointerEvent) {
  if (canvas.value?.hasPointerCapture(event.pointerId)) {
    canvas.value.releasePointerCapture(event.pointerId)
  }
  activeStroke = null
}

function undoStroke() {
  if (!strokes.value.length) return
  strokes.value.pop()
  redrawCanvas()
  emit('event', { tool: 'scratchpad', action: 'undo' })
}

function clearScratchpad() {
  strokes.value = []
  scratchText.value = ''
  redrawCanvas()
  emit('event', { tool: 'scratchpad', action: 'cleared' })
}

function onWindowKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && toolsOpen.value) closeTools()
}

watch(toolsOpen, (open) => {
  if (open) {
    previousBodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
  } else {
    document.body.style.overflow = previousBodyOverflow
  }
})

watch(
  () => props.taskKey,
  () => {
    toolsOpen.value = false
    calculatorExpanded.value = false
    resetCalculatorPosition()
    expression.value = ''
    calculatorResult.value = '0'
    calculatorError.value = ''
    strokes.value = []
    scratchText.value = ''
  }
)

onMounted(() => {
  window.addEventListener('keydown', onWindowKeydown)
  window.addEventListener('resize', keepCalculatorInViewport)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onWindowKeydown)
  window.removeEventListener('resize', keepCalculatorInViewport)
  document.body.style.overflow = previousBodyOverflow
})
</script>

<template>
  <div class="tool-workspace">
    <div class="assessment-tools" aria-label="任务辅助工具">
      <button
        class="btn btn-sm btn-outline-primary"
        :class="{ active: toolsOpen }"
        type="button"
        :aria-expanded="toolsOpen"
        aria-controls="calculation-workspace"
        @click="openTools"
      >
        <i class="bi bi-calculator me-1" />计算工具
      </button>
    </div>

    <Teleport to="body">
      <Transition name="tool-panel">
        <section
          v-if="toolsOpen"
          id="calculation-workspace"
          class="tool-fullscreen"
          role="dialog"
          aria-modal="true"
          aria-labelledby="calculation-workspace-title"
        >
          <header class="fullscreen-header">
            <div>
              <span class="tool-kicker">任务辅助工作区</span>
              <h4 id="calculation-workspace-title" class="mb-0">计算工具</h4>
            </div>
            <button class="btn btn-outline-secondary" type="button" @click="closeTools">
              <i class="bi bi-x-lg me-1" />关闭并返回题目
            </button>
          </header>

          <div class="fullscreen-content">
            <section
              id="scratchpad-panel"
              class="tool-dialog scratch-dialog"
              role="region"
              aria-label="电子草稿纸"
            >
          <header class="tool-header">
            <div>
              <span class="tool-kicker">下方工具</span>
              <h5 class="mb-0">电子草稿纸</h5>
            </div>
          </header>

          <div class="scratch-body">
            <article class="scratch-question-reference" aria-label="当前题目">
              <div class="scratch-question-copy">
                <span class="tool-kicker">当前题目</span>
                <h6>{{ taskTitle }}</h6>
                <p>{{ taskScenario }}</p>
                <div v-if="taskUnitNote" class="scratch-question-note">{{ taskUnitNote }}</div>
              </div>
              <figure v-if="taskImage" class="scratch-question-image">
                <h6>{{ taskImage.title }}</h6>
                <img :src="taskImage.src" :alt="taskImage.alt">
              </figure>
            </article>
            <div class="scratch-toolbar">
              <span class="text-muted small">可使用鼠标、触控笔或手指书写</span>
              <div class="d-flex gap-2">
                <button class="btn btn-sm btn-outline-secondary" type="button" @click="undoStroke">
                  <i class="bi bi-arrow-counterclockwise me-1" />撤销
                </button>
                <button class="btn btn-sm btn-outline-danger" type="button" @click="clearScratchpad">
                  <i class="bi bi-trash3 me-1" />清空
                </button>
              </div>
            </div>
            <div class="scratch-canvas-wrap">
              <canvas
                ref="canvas"
                width="900"
                height="520"
                aria-label="可书写草稿区域"
                @pointerdown="startStroke"
                @pointermove="continueStroke"
                @pointerup="endStroke"
                @pointercancel="endStroke"
              />
            </div>
            <label class="form-label small fw-semibold mt-3" for="scratch-text">键盘草稿（可选）</label>
            <textarea
              id="scratch-text"
              v-model="scratchText"
              class="form-control"
              rows="3"
              placeholder="也可以在这里键入算式或简短备注"
            />
            <p class="privacy-note mb-0">
              草稿内容仅保留在当前任务页面，不提交给 AI，也不进入测评评分。
            </p>
          </div>
            </section>
          </div>

          <Transition name="calculator-pop" mode="out-in">
            <aside
              v-if="calculatorExpanded"
              key="calculator"
              ref="calculatorPanel"
              class="floating-calculator"
              :class="{ 'is-dragging': calculatorDragging }"
              :style="calculatorPositionStyle"
              aria-labelledby="calculator-title"
            >
              <header
                class="floating-calculator-header"
                title="拖动可调整计算器位置，双击恢复默认位置"
                @pointerdown="startCalculatorDrag"
                @pointermove="moveCalculator"
                @pointerup="endCalculatorDrag"
                @pointercancel="endCalculatorDrag"
                @dblclick="resetCalculatorPosition"
              >
                <div>
                  <span class="tool-kicker">悬浮工具</span>
                  <h5 id="calculator-title" class="mb-0">数学计算器</h5>
                  <small class="calculator-drag-hint"><i class="bi bi-arrows-move me-1" />拖动调整位置</small>
                </div>
                <button
                  class="btn btn-sm btn-light calculator-collapse"
                  type="button"
                  aria-label="收起计算器"
                  title="收起计算器"
                  @click="toggleCalculator"
                >
                  <i class="bi bi-chevron-down" />
                </button>
              </header>
              <div class="calculator-body">
                <label class="visually-hidden" for="calculator-expression">计算表达式</label>
                <input
                  id="calculator-expression"
                  v-model="expression"
                  class="calculator-expression"
                  inputmode="decimal"
                  autocomplete="off"
                  placeholder="输入算式"
                  @keydown="onCalculatorKeydown"
                >
                <div class="calculator-result" aria-live="polite">
                  <span>{{ calculatorError || '结果' }}</span>
                  <strong :class="{ 'text-danger': calculatorError }">
                    {{ calculatorError ? '—' : calculatorResult }}
                  </strong>
                </div>
                <div class="calculator-grid">
                  <button
                    v-for="button in calculatorButtons"
                    :key="`${button.label}-${button.value}`"
                    type="button"
                    class="calculator-key"
                    :class="[
                      button.tone ? `key-${button.tone}` : '',
                      { 'key-wide': button.wide, 'key-tall': button.tall }
                    ]"
                    @click="pressCalculator(button.value)"
                  >
                    {{ button.label }}
                  </button>
                </div>
              </div>
            </aside>
            <button
              v-else
              key="launcher"
              class="calculator-fab"
              type="button"
              aria-label="打开悬浮计算器"
              title="打开计算器"
              @click="toggleCalculator"
            >
              <i class="bi bi-calculator" aria-hidden="true" />
              <span>计算器</span>
            </button>
          </Transition>
        </section>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.tool-workspace { min-width: 0; }
.assessment-tools { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: .5rem; }
.assessment-tools .btn.active {
  color: #fff;
  border-color: var(--color-primary);
  background: var(--color-primary);
}
.tool-fullscreen {
  position: fixed;
  inset: 0;
  z-index: 2050;
  min-width: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  color: var(--color-text);
  background: var(--color-canvas);
  scrollbar-gutter: stable;
}
.fullscreen-header {
  position: sticky;
  top: 0;
  z-index: 5;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: .9rem clamp(1rem, 3vw, 2.5rem);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
  box-shadow: 0 6px 20px rgba(30, 41, 59, .06);
  backdrop-filter: blur(12px);
}
.fullscreen-content {
  display: grid;
  width: min(1400px, calc(100% - 2rem));
  gap: 1rem;
  margin: 0 auto;
  padding: 1rem 0 2rem;
}
.tool-dialog {
  width: 100%;
  min-width: 0;
  margin: 0;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: var(--shadow-md);
}
.tool-panel-enter-active,
.tool-panel-leave-active {
  transition: opacity var(--motion-panel) var(--ease-out), transform var(--motion-panel) var(--ease-out);
}
.tool-panel-enter-from,
.tool-panel-leave-to {
  opacity: 0;
  transform: scale(.992);
}
.scratch-dialog { width: 100%; }
.calculator-fab,
.floating-calculator {
  position: fixed;
  right: clamp(1rem, 2.5vw, 2rem);
  bottom: clamp(1rem, 2.5vw, 2rem);
  z-index: 12;
}
.calculator-fab {
  display: inline-flex;
  width: 76px;
  height: 76px;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: .18rem;
  border: 1px solid rgba(255,255,255,.75);
  border-radius: 50%;
  color: #fff;
  background: linear-gradient(145deg, #5a57bd, #3f3d99);
  box-shadow: 0 14px 34px rgba(75, 73, 172, .34);
  font-size: .72rem;
  font-weight: 700;
}
.calculator-fab i { font-size: 1.35rem; }
.calculator-fab:hover,
.calculator-fab:focus-visible {
  color: #fff;
  background: linear-gradient(145deg, #6663c8, #4744a3);
  box-shadow: 0 17px 38px rgba(75, 73, 172, .42);
  transform: translateY(-2px);
}
.floating-calculator {
  width: min(360px, calc(100vw - 2rem));
  max-height: calc(100dvh - 7rem);
  overflow: auto;
  border: 1px solid var(--color-border);
  border-radius: 18px;
  background: var(--color-surface);
  box-shadow: 0 22px 55px rgba(30, 41, 59, .24);
  scrollbar-width: thin;
  will-change: left, top;
}
.floating-calculator.is-dragging { box-shadow: 0 26px 62px rgba(30, 41, 59, .3); }
.floating-calculator-header {
  position: sticky;
  top: 0;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: .75rem .9rem;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
  backdrop-filter: blur(10px);
  cursor: grab;
  touch-action: none;
  user-select: none;
}
.floating-calculator.is-dragging .floating-calculator-header { cursor: grabbing; }
.floating-calculator-header button { cursor: pointer; }
.floating-calculator-header h5 { font-size: 1rem; }
.calculator-drag-hint { display: block; margin-top: .15rem; color: var(--color-text-muted); font-size: .66rem; }
.calculator-collapse {
  display: inline-grid;
  width: 36px;
  height: 36px;
  place-items: center;
  padding: 0;
  border-radius: 50%;
}
.calculator-pop-enter-active,
.calculator-pop-leave-active {
  transition: opacity 180ms var(--ease-out), transform 220ms var(--ease-out);
  transform-origin: right bottom;
}
.calculator-pop-enter-from,
.calculator-pop-leave-to {
  opacity: 0;
  transform: translateY(10px) scale(.92);
}
@media (prefers-reduced-motion: reduce) {
  .tool-panel-enter-active,
  .tool-panel-leave-active { transition: opacity 150ms ease; }
  .tool-panel-enter-from,
  .tool-panel-leave-to { transform: none; }
  .calculator-pop-enter-active,
  .calculator-pop-leave-active { transition: opacity 120ms ease; }
  .calculator-pop-enter-from,
  .calculator-pop-leave-to { transform: none; }
}
.tool-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 1rem 1.15rem;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
}
.tool-kicker {
  display: block;
  margin-bottom: .15rem;
  color: var(--color-primary);
  font-size: .7rem;
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.calculator-body, .scratch-body { padding: 1.15rem; }
.floating-calculator .calculator-body { padding: .75rem .9rem .9rem; }
.calculator-expression {
  width: 100%;
  border: 0;
  border-bottom: 1px solid var(--color-border);
  outline: 0;
  padding: .65rem .25rem;
  color: var(--color-text);
  font: 500 1.1rem/1.4 ui-monospace, SFMono-Regular, Menlo, monospace;
  text-align: right;
}
.calculator-result {
  display: flex;
  min-height: 68px;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: .8rem .25rem;
}
.calculator-result span { color: var(--color-text-muted); font-size: .78rem; }
.calculator-result strong {
  overflow-wrap: anywhere;
  color: var(--color-text);
  font: 700 1.65rem/1.2 ui-monospace, SFMono-Regular, Menlo, monospace;
}
.calculator-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  grid-auto-rows: 52px;
  gap: .55rem;
}
.calculator-key {
  border: 1px solid var(--color-border);
  border-radius: 12px;
  background: var(--color-surface-subtle);
  color: var(--color-text);
  font-weight: 650;
}
.calculator-key:hover, .calculator-key:focus-visible { border-color: var(--color-primary-hover); background: var(--color-primary-soft); }
.key-muted { color: var(--color-text-muted); background: var(--color-surface-subtle); }
.key-operator { color: var(--color-primary); background: var(--color-primary-soft); }
.key-equals { grid-row: span 2; color: #fff; border-color: var(--color-primary); background: var(--color-primary); }
.key-equals:hover, .key-equals:focus-visible { color: #fff; background: var(--color-primary-hover); }
.key-wide { grid-column: span 2; }
.scratch-question-reference {
  display: grid;
  grid-template-columns: minmax(260px, .8fr) minmax(0, 1.2fr);
  gap: 1rem;
  margin-bottom: 1rem;
  padding: 1rem;
  border: 1px solid var(--color-border);
  border-radius: 12px;
  background: var(--color-surface-subtle);
}
.scratch-question-copy h6 {
  margin-bottom: .6rem;
  color: var(--color-text);
  font-size: 1rem;
  font-weight: 750;
}
.scratch-question-copy p {
  margin: 0;
  color: var(--color-text-secondary);
  line-height: 1.7;
}
.scratch-question-note {
  margin-top: .75rem;
  padding: .65rem .75rem;
  border-left: 3px solid var(--color-warning);
  border-radius: 8px;
  color: var(--color-warning);
  background: var(--color-warning-soft);
  font-size: .84rem;
  font-weight: 600;
  line-height: 1.55;
}
.scratch-question-image {
  margin: 0;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 10px;
  background: var(--color-surface);
}
.scratch-question-image h6 {
  margin: 0;
  padding: .55rem .75rem;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-text);
  font-size: .84rem;
  font-weight: 700;
  text-align: center;
}
.scratch-question-image img {
  display: block;
  width: 100%;
  max-height: 380px;
  object-fit: contain;
}
.scratch-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: .75rem;
}
.scratch-canvas-wrap {
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 12px;
  background-color: var(--color-surface);
  background-image:
    linear-gradient(var(--color-border) 1px, transparent 1px),
    linear-gradient(90deg, var(--color-border) 1px, transparent 1px);
  background-size: 24px 24px;
}
.scratch-canvas-wrap canvas {
  display: block;
  width: 100%;
  height: auto;
  aspect-ratio: 900 / 520;
  cursor: crosshair;
  touch-action: none;
}
.privacy-note {
  margin-top: .75rem;
  padding: .65rem .75rem;
  border-radius: 9px;
  color: var(--color-text-muted);
  background: var(--color-surface-subtle);
  font-size: .76rem;
}
@media (min-width: 992px) {
  .floating-calculator .calculator-grid { grid-auto-rows: 42px; gap: .4rem; }
}
@media (max-width: 575.98px) {
  .assessment-tools { width: 100%; justify-content: stretch; }
  .assessment-tools .btn { flex: 1 1 100%; min-height: 44px; }
  .fullscreen-header { align-items: flex-start; padding: .75rem; }
  .fullscreen-header .btn { padding-inline: .65rem; font-size: .78rem; }
  .fullscreen-content { width: calc(100% - 1rem); padding-top: .5rem; }
  .tool-dialog {
    width: 100%;
    border-radius: 12px;
  }
  .scratch-dialog { width: 100%; }
  .calculator-grid { grid-auto-rows: 48px; gap: .45rem; }
  .scratch-question-reference { grid-template-columns: 1fr; padding: .75rem; }
  .scratch-question-image img { max-height: none; }
  .scratch-toolbar { align-items: flex-start; flex-direction: column; }
  .scratch-toolbar > div { width: 100%; }
  .scratch-toolbar .btn { flex: 1; }
  .scratch-canvas-wrap canvas { min-height: 260px; object-fit: fill; }
  .calculator-fab {
    right: .75rem;
    bottom: .75rem;
    width: 66px;
    height: 66px;
  }
  .floating-calculator {
    right: .75rem;
    bottom: .75rem;
    width: min(320px, calc(100vw - 1.5rem));
    max-height: calc(100dvh - 6rem);
  }
  .floating-calculator .calculator-grid { grid-auto-rows: 43px; gap: .4rem; }
  .floating-calculator .calculator-result { min-height: 54px; padding-block: .55rem; }
  .floating-calculator-header { cursor: default; touch-action: auto; }
  .calculator-drag-hint { display: none; }
}
</style>
