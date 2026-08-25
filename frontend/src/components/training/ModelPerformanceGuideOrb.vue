<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

const root = ref<HTMLElement | null>(null)
const panel = ref<HTMLElement | null>(null)
const expanded = ref(false)
const dragging = ref(false)
const position = ref({ x: 16, y: 16 })
const viewport = ref({ width: 0, height: 0 })
let dragState: {
  pointerId: number
  startX: number
  startY: number
  originX: number
  originY: number
  moved: boolean
} | null = null
let suppressClick = false
let clickTimer: number | null = null

const ORB_SIZE = 58
const EDGE_GAP = 12
const rootStyle = computed(() => ({
  transform: `translate3d(${position.value.x}px, ${position.value.y}px, 0)`
}))
const opensRight = computed(() => position.value.x < viewport.value.width / 2)
const opensBelow = computed(() => position.value.y < viewport.value.height / 2)
const panelStyle = computed(() => ({
  maxHeight: `${Math.max(220, opensBelow.value
    ? viewport.value.height - position.value.y - ORB_SIZE - 24
    : position.value.y - 24)}px`
}))

function clampPosition(x: number, y: number) {
  return {
    x: Math.max(EDGE_GAP, Math.min(x, viewport.value.width - ORB_SIZE - EDGE_GAP)),
    y: Math.max(EDGE_GAP, Math.min(y, viewport.value.height - ORB_SIZE - EDGE_GAP))
  }
}

function applyPosition(next: { x: number; y: number }) {
  position.value = clampPosition(next.x, next.y)
  if (root.value) root.value.style.transform = `translate3d(${position.value.x}px, ${position.value.y}px, 0)`
}

function updateViewport(initial = false) {
  viewport.value = { width: window.innerWidth, height: window.innerHeight }
  applyPosition(initial
    ? { x: window.innerWidth - ORB_SIZE - 24, y: Math.max(96, window.innerHeight * .28) }
    : position.value)
}

function handleResize() {
  updateViewport(false)
}

function startDrag(event: PointerEvent) {
  if (dragState) return
  dragState = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    originX: position.value.x,
    originY: position.value.y,
    moved: false
  }
  dragging.value = true
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
}

function moveDrag(event: PointerEvent) {
  if (!dragState || dragState.pointerId !== event.pointerId) return
  const dx = event.clientX - dragState.startX
  const dy = event.clientY - dragState.startY
  if (!dragState.moved && Math.hypot(dx, dy) >= 5) dragState.moved = true
  if (!dragState.moved) return
  event.preventDefault()
  applyPosition({ x: dragState.originX + dx, y: dragState.originY + dy })
}

function endDrag(event: PointerEvent) {
  if (!dragState || dragState.pointerId !== event.pointerId) return
  suppressClick = dragState.moved
  dragState = null
  dragging.value = false
  if (clickTimer !== null) window.clearTimeout(clickTimer)
  clickTimer = window.setTimeout(() => { suppressClick = false }, 0)
}

function togglePanel() {
  if (suppressClick) return
  expanded.value = !expanded.value
  if (expanded.value) void nextTick(() => panel.value?.focus({ preventScroll: true }))
}

function moveWithKeyboard(event: KeyboardEvent) {
  const direction = ({
    ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]
  } as Record<string, [number, number]>)[event.key]
  if (!direction) return
  event.preventDefault()
  const step = event.shiftKey ? 24 : 8
  applyPosition({ x: position.value.x + direction[0] * step, y: position.value.y + direction[1] * step })
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && expanded.value) expanded.value = false
}

onMounted(() => {
  updateViewport(true)
  window.addEventListener('resize', handleResize)
  window.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  window.removeEventListener('keydown', handleKeydown)
  if (clickTimer !== null) window.clearTimeout(clickTimer)
})
</script>

<template>
  <Teleport to="body">
    <aside
      ref="root"
      class="performance-guide"
      :class="{ 'is-dragging': dragging, 'opens-right': opensRight, 'opens-below': opensBelow }"
      :style="rootStyle"
    >
      <Transition name="performance-guide-panel">
        <section
          v-if="expanded"
          id="model-performance-guide-panel"
          ref="panel"
          class="performance-guide-panel"
          :style="panelStyle"
          tabindex="-1"
          aria-label="模型性能评估查看说明"
        >
          <header>
            <span><i class="bi bi-clipboard2-pulse" /></span>
            <div><small>模型性能评估</small><strong>如何验看并判断训练结果</strong></div>
            <button type="button" aria-label="关闭模型评估说明" @click="expanded = false"><i class="bi bi-x-lg" /></button>
          </header>

          <div class="performance-guide-content">
            <section class="guide-first">
              <h6><i class="bi bi-signpost-split" />推荐验看顺序</h6>
              <ol class="guide-steps">
                <li><b>1</b><span><strong>先核对版本。</strong>确认训练版本、数据版本、训练时间和数据指纹属于同一次训练。</span></li>
                <li><b>2</b><span><strong>再看 Macro-F1。</strong>它是当前首要比较指标，兼顾三个类别且不让多数类占据更大权重。</span></li>
                <li><b>3</b><span><strong>检查每类别 F1 与 Recall。</strong>尤其关注样本较少或业务重要的类别，避免平均分掩盖单类失效。</span></li>
                <li><b>4</b><span><strong>查看混淆矩阵。</strong>定位“哪一类经常被错判成哪一类”，再回到错误文本分析原因。</span></li>
                <li><b>5</b><span><strong>判断稳定性与边界。</strong>结合五折标准差、折间极差、训练—折外差距和被试隔离情况决定能否启用。</span></li>
              </ol>
            </section>

            <section>
              <h6><i class="bi bi-bar-chart-line" />核心指标是什么意思？</h6>
              <dl class="metric-guide">
                <div><dt>Accuracy</dt><dd>全部折外样本中预测正确的比例；类别不平衡时不能单独使用。</dd></div>
                <div><dt>Macro-Precision</dt><dd>分别计算各类别精准率后等权平均，反映预测为某类时有多可靠。</dd></div>
                <div><dt>Macro-Recall</dt><dd>分别计算各类别召回率后等权平均，反映各类真实样本被找回的程度。</dd></div>
                <div class="is-primary"><dt>Macro-F1</dt><dd>各类别 F1 的算术平均，是当前比较模型的首要指标。</dd></div>
                <div><dt>Weighted-F1</dt><dd>按各类别真实样本数加权的 F1，更接近当前样本构成下的总体表现。</dd></div>
                <div><dt>Macro-AUC</dt><dd>各类别一对其余 AUC 的宏平均；LinearSVC 使用决策分数，不代表概率。</dd></div>
                <div><dt>Specificity</dt><dd>其他类别没有被误判为目标类别的能力；历史结果缺失时显示“—”。</dd></div>
                <div><dt>Support</dt><dd>折外评估中该类别的真实样本数量，不是全量训练集数量。</dd></div>
              </dl>
            </section>

            <section>
              <h6><i class="bi bi-grid-3x3-gap" />如何看混淆矩阵？</h6>
              <div class="matrix-guide">
                <span>行 = 真实类别</span><i class="bi bi-arrow-right" /><span>列 = 预测类别</span>
              </div>
              <p>对角线越大越好；非对角线代表误分类。例如“评估 → 调控 19 次”表示有 19 条真实评估文本被模型判断为调控。</p>
            </section>

            <section>
              <h6><i class="bi bi-shield-check" />什么时候可以考虑启用？</h6>
              <ul class="guide-checks">
                <li><i class="bi bi-check2-circle" />Macro-F1 在候选模型中领先，且优势不是仅由一个类别贡献。</li>
                <li><i class="bi bi-check2-circle" />三个类别的 F1、Recall 均达到研究可以接受的水平。</li>
                <li><i class="bi bi-check2-circle" />五折波动较小，训练分数与折外分数差距不过大。</li>
                <li><i class="bi bi-check2-circle" />模型使用相同数据指纹、相同标签顺序和相同评估划分进行比较。</li>
                <li><i class="bi bi-check2-circle" />结合 2C4G 部署资源、推理延迟和模型体积后仍可稳定运行。</li>
              </ul>
            </section>

            <section class="guide-boundary">
              <h6><i class="bi bi-exclamation-diamond" />可信度边界</h6>
              <p>当前页面主要展示内部五折折外结果，不等同于独立外部测试。若缺少可靠被试 ID，句子级分层可能产生被试信息泄漏；正式研究结论仍应增加独立样本验证。</p>
              <p>“—”表示训练产物没有保存该指标，不等于 0。页面出现版本校验警告时，不应比较或启用模型。</p>
            </section>
          </div>
        </section>
      </Transition>

      <button
        type="button"
        class="performance-guide-orb"
        :class="{ 'is-expanded': expanded }"
        aria-label="模型评估查看说明，可拖动；按方向键可调整位置"
        aria-controls="model-performance-guide-panel"
        :aria-expanded="expanded"
        title="模型评估说明（可拖动）"
        @pointerdown="startDrag"
        @pointermove="moveDrag"
        @pointerup="endDrag"
        @pointercancel="endDrag"
        @keydown="moveWithKeyboard"
        @click="togglePanel"
      >
        <i class="bi" :class="expanded ? 'bi-chevron-down' : 'bi-question-lg'" />
        <span>查看说明</span>
      </button>
    </aside>
  </Teleport>
</template>

<style scoped>
.performance-guide {
  --guide-ease: cubic-bezier(.23,1,.32,1);
  position: fixed;
  z-index: 12045;
  top: 0;
  left: 0;
  width: 58px;
  height: 58px;
  pointer-events: none;
  will-change: transform;
}
.performance-guide-orb {
  position: relative;
  display: grid;
  place-items: center;
  width: 58px;
  height: 58px;
  padding: 0;
  border: 1px solid color-mix(in srgb,#22d3ee 58%,var(--color-primary));
  border-radius: 50%;
  color: #fff;
  background: radial-gradient(circle at 32% 24%,rgba(255,255,255,.35),transparent 28%),linear-gradient(145deg,#675cff,#087fba);
  box-shadow: 0 14px 34px rgba(52,66,190,.34),0 0 0 5px color-mix(in srgb,var(--color-primary) 9%,transparent),inset 0 1px 0 rgba(255,255,255,.34);
  cursor: grab;
  pointer-events: auto;
  touch-action: none;
  user-select: none;
  transition: transform 140ms var(--guide-ease),box-shadow 180ms var(--guide-ease);
}
.performance-guide-orb i { font-size: 1.1rem; }
.performance-guide-orb span {
  position: absolute;
  right: calc(100% + 9px);
  padding: .34rem .62rem;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  color: var(--color-text-secondary);
  background: color-mix(in srgb,var(--color-surface) 91%,transparent);
  box-shadow: var(--shadow-sm);
  backdrop-filter: blur(12px);
  font-size: .75rem;
  font-weight: 750;
  white-space: nowrap;
}
.performance-guide.opens-right .performance-guide-orb span { right: auto; left: calc(100% + 9px); }
.performance-guide.is-dragging .performance-guide-orb { transform: scale(.97); cursor: grabbing; }
.performance-guide-orb:active { transform: scale(.96); }
.performance-guide-orb:focus-visible { outline: 3px solid color-mix(in srgb,var(--color-primary) 35%,transparent); outline-offset: 3px; }

.performance-guide-panel {
  position: absolute;
  right: 0;
  bottom: calc(100% + 12px);
  width: min(480px,calc(100vw - 24px));
  overflow: hidden auto;
  border: 1px solid color-mix(in srgb,var(--color-primary) 30%,var(--color-border-strong));
  border-radius: 20px;
  color: var(--color-text);
  background: color-mix(in srgb,var(--color-surface) 96%,transparent);
  box-shadow: 0 28px 72px rgba(12,18,55,.34);
  backdrop-filter: blur(20px) saturate(1.15);
  pointer-events: auto;
  transform-origin: bottom right;
  scrollbar-width: thin;
}
.performance-guide.opens-right .performance-guide-panel { right: auto; left: 0; transform-origin: bottom left; }
.performance-guide.opens-below .performance-guide-panel { top: calc(100% + 12px); bottom: auto; transform-origin: top right; }
.performance-guide.opens-right.opens-below .performance-guide-panel { transform-origin: top left; }
.performance-guide-panel > header {
  position: sticky;
  z-index: 2;
  top: 0;
  display: grid;
  grid-template-columns: 42px minmax(0,1fr) 34px;
  align-items: center;
  gap: .75rem;
  padding: 1rem;
  border-bottom: 1px solid var(--color-border);
  background: color-mix(in srgb,var(--color-surface) 94%,transparent);
  backdrop-filter: blur(16px);
}
.performance-guide-panel > header > span { display: grid; place-items: center; width: 42px; height: 42px; border-radius: 13px; color: var(--color-primary); background: var(--color-primary-soft); font-size: 1.05rem; }
.performance-guide-panel header small,.performance-guide-panel header strong { display: block; }
.performance-guide-panel header small { color: var(--color-text-muted); font-size: .72rem; }
.performance-guide-panel header strong { margin-top: .08rem; font-size: .98rem; }
.performance-guide-panel header button { display: grid; place-items: center; width: 34px; height: 34px; padding: 0; border: 0; border-radius: 10px; color: var(--color-text-muted); background: transparent; transition: color 140ms ease,background 140ms ease,transform 140ms var(--guide-ease); }
.performance-guide-panel header button:hover { color: var(--color-text); background: var(--color-surface-subtle); }
.performance-guide-panel header button:active { transform: scale(.95); }
.performance-guide-content { display: grid; gap: 1rem; padding: 1rem; }
.performance-guide-content > section { padding: .95rem; border: 1px solid var(--color-border); border-radius: 14px; background: var(--color-surface-subtle); }
.performance-guide-content h6 { display: flex; align-items: center; gap: .5rem; margin: 0 0 .75rem; font-size: .88rem; }
.performance-guide-content h6 i { color: var(--color-primary); }
.guide-first { background: linear-gradient(135deg,color-mix(in srgb,var(--color-primary-soft) 58%,var(--color-surface)),color-mix(in srgb,#22d3ee 7%,var(--color-surface))) !important; }
.guide-steps { display: grid; gap: .65rem; margin: 0; padding: 0; list-style: none; }
.guide-steps li { display: grid; grid-template-columns: 28px minmax(0,1fr); align-items: start; gap: .6rem; color: var(--color-text-secondary); font-size: .79rem; line-height: 1.58; }
.guide-steps b { display: grid; place-items: center; width: 27px; height: 27px; border-radius: 9px; color: var(--color-primary); background: var(--color-surface); box-shadow: var(--shadow-xs); }
.metric-guide { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: .55rem; margin: 0; }
.metric-guide div { padding: .65rem .7rem; border: 1px solid transparent; border-radius: 10px; background: var(--color-surface); }
.metric-guide div.is-primary { border-color: color-mix(in srgb,var(--color-primary) 38%,var(--color-border)); background: var(--color-primary-soft); }
.metric-guide dt { font-size: .78rem; font-weight: 800; }
.metric-guide dd { margin: .2rem 0 0; color: var(--color-text-muted); font-size: .75rem; line-height: 1.5; }
.matrix-guide { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: .5rem; margin-bottom: .6rem; }
.matrix-guide span { padding: .55rem; border-radius: 9px; background: var(--color-surface); text-align: center; font-size: .77rem; font-weight: 750; }
.matrix-guide i { color: var(--color-primary); }
.performance-guide-content section > p { margin: 0; color: var(--color-text-secondary); font-size: .77rem; line-height: 1.6; }
.guide-checks { display: grid; gap: .52rem; margin: 0; padding: 0; list-style: none; }
.guide-checks li { display: grid; grid-template-columns: 20px minmax(0,1fr); gap: .45rem; color: var(--color-text-secondary); font-size: .78rem; line-height: 1.55; }
.guide-checks i { color: var(--color-success); }
.guide-boundary { border-color: color-mix(in srgb,var(--color-warning) 34%,var(--color-border)) !important; background: color-mix(in srgb,var(--color-warning-soft) 65%,var(--color-surface)) !important; }
.guide-boundary p + p { margin-top: .55rem; }

.performance-guide-panel-enter-active,.performance-guide-panel-leave-active { transition: opacity 180ms var(--guide-ease),transform 180ms var(--guide-ease); }
.performance-guide-panel-enter-from,.performance-guide-panel-leave-to { opacity: 0; transform: scale(.97); }
@media (hover: hover) and (pointer: fine) {
  .performance-guide-orb:hover { transform: translateY(-2px); box-shadow: 0 18px 42px rgba(52,66,190,.4),0 0 0 7px color-mix(in srgb,var(--color-primary) 11%,transparent); }
}
@media (max-width: 575.98px) {
  .performance-guide-panel { width: min(370px,calc(100vw - 24px)); }
  .performance-guide-orb span { display: none; }
  .metric-guide { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  .performance-guide-orb { transition: box-shadow 150ms ease; }
  .performance-guide-orb:hover,.performance-guide-orb:active,.performance-guide.is-dragging .performance-guide-orb { transform: none; }
  .performance-guide-panel-enter-active,.performance-guide-panel-leave-active { transition: opacity 150ms ease; }
  .performance-guide-panel-enter-from,.performance-guide-panel-leave-to { transform: none; }
}
</style>
