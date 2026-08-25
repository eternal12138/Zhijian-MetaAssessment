<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

const props = withDefaults(defineProps<{
  hasPreviousExport?: boolean
  includeAudio?: boolean
  newlyReviewedCount?: number
  newlyAcceptedCount?: number
  incrementalSessionCount?: number
}>(), {
  hasPreviousExport: false,
  includeAudio: true,
  newlyReviewedCount: 0,
  newlyAcceptedCount: 0,
  incrementalSessionCount: 0
})

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

const ORB_SIZE = 54
const EDGE_GAP = 12

const rootStyle = computed(() => ({
  transform: `translate3d(${position.value.x}px, ${position.value.y}px, 0)`
}))
const opensRight = computed(() => position.value.x < viewport.value.width / 2)
const opensBelow = computed(() => position.value.y < viewport.value.height / 2)
const panelStyle = computed(() => ({
  maxHeight: `${Math.max(180, opensBelow.value
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
  if (root.value) {
    root.value.style.transform = `translate3d(${position.value.x}px, ${position.value.y}px, 0)`
  }
}

function updateViewport(initial = false) {
  viewport.value = { width: window.innerWidth, height: window.innerHeight }
  applyPosition(initial
    ? { x: window.innerWidth - ORB_SIZE - 22, y: window.innerHeight - ORB_SIZE - 92 }
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
  if (expanded.value) {
    void nextTick(() => panel.value?.focus({ preventScroll: true }))
  }
}

function moveWithKeyboard(event: KeyboardEvent) {
  const directions: Record<string, [number, number]> = {
    ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]
  }
  const direction = directions[event.key]
  if (!direction) return
  event.preventDefault()
  const step = event.shiftKey ? 24 : 8
  applyPosition({
    x: position.value.x + direction[0] * step,
    y: position.value.y + direction[1] * step
  })
}

function handleGlobalKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && expanded.value) expanded.value = false
}

onMounted(() => {
  updateViewport(true)
  window.addEventListener('resize', handleResize)
  window.addEventListener('keydown', handleGlobalKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  window.removeEventListener('keydown', handleGlobalKeydown)
  if (clickTimer !== null) window.clearTimeout(clickTimer)
})
</script>

<template>
  <Teleport to="body">
    <aside
      ref="root"
      class="export-guide"
      :class="{
        'is-dragging': dragging,
        'opens-right': opensRight,
        'opens-below': opensBelow
      }"
      :style="rootStyle"
    >
      <Transition name="export-guide-panel">
        <section
          v-if="expanded"
          id="export-guide-panel"
          ref="panel"
          class="export-guide-panel"
          :style="panelStyle"
          tabindex="-1"
          aria-label="研究数据包导出说明"
        >
          <header>
            <span><i class="bi bi-journal-text" /></span>
            <div><small>研究数据导出</small><strong>如何选择和使用导出包</strong></div>
            <button type="button" aria-label="收起导出说明" @click="expanded = false"><i class="bi bi-x-lg" /></button>
          </header>

          <div class="export-guide-content">
            <section>
              <h6><i class="bi bi-ui-checks-grid" />选择哪一种？</h6>
              <div class="guide-choice is-all"><strong>全部已完成测评</strong><p>首次建立完整归档、准备正式分析、需要重新生成当前完整快照，或历史导出的复核状态不确定时选择。</p></div>
              <div class="guide-choice is-incremental"><strong>仅导出上次之后新增内容</strong><p>日常补充归档时选择。包含新完成测评，以及旧测评中上次导出后新完成的人工复核结果。</p></div>
              <div class="guide-choice is-accepted"><strong>仅导出当前已接受内容</strong><p>只需要正式人工接受文本时选择。不会处理或打包 WAV，适合快速下载训练数据和阶段性复核成果。</p></div>
              <p v-if="hasPreviousExport" class="guide-live-note"><i class="bi bi-arrow-repeat" />按当前{{ includeAudio ? '含录音' : '不含录音' }}条件，检测到新增复核 {{ newlyReviewedCount }} 条，其中新增接受 {{ newlyAcceptedCount }} 条，涉及 {{ incrementalSessionCount }} 个任务。</p>
              <p v-else class="guide-live-note"><i class="bi bi-info-circle" />当前没有历史导出；选择“仅新增”时，首次会自动按全部数据导出。</p>
            </section>

            <section>
              <h6><i class="bi bi-diagram-3" />如何导出？</h6>
              <ol class="guide-steps">
                <li><b>1</b><span>先查看人工复核进度警告，确认当前数据是否适合归档。</span></li>
                <li><b>2</b><span>根据用途选择导出范围，并决定是否包含原始录音；不含录音时生成和下载更快。</span></li>
                <li><b>3</b><span>任务在后台整理，可继续使用其他功能；完成后自动开始流式下载。</span></li>
                <li><b>4</b><span>下载完成后妥善保存；服务器仅保留最近一次派生 ZIP，不会删除原始录音和数据库记录。</span></li>
              </ol>
            </section>

            <section>
              <h6><i class="bi bi-file-earmark-zip" />压缩包里有什么？</h6>
              <dl class="guide-files">
                <div><dt>00 用户信息</dt><dd>账号、系统姓名、问卷填写姓名、班级与测评编号。</dd></div>
                <div><dt>01 原始录音（可选）</dt><dd>勾选导出录音时，包含每项任务的 WAV、声音检测结果与 SHA256 校验值。</dd></div>
                <div><dt>02 原始转录</dt><dd>ASR 或人工转录原文，并标明文本来源。</dd></div>
                <div><dt>03 AI筛选文本</dt><dd>最新抽取版本的全部候选及当前人工复核状态。</dd></div>
                <div><dt>04 人工校对文本</dt><dd>只包含人工接受的正式复核文本；增量包中只列出上次之后新接受的候选。</dd></div>
              </dl>
            </section>

            <p class="guide-warning"><i class="bi bi-exclamation-triangle-fill" />若仍有待复核候选，导出包只是过程版本，不能作为最终专家复核数据。</p>
          </div>
        </section>
      </Transition>

      <button
        type="button"
        class="export-guide-orb"
        :class="{ 'is-expanded': expanded }"
        aria-label="导出说明，可拖动；按方向键可调整位置"
        aria-controls="export-guide-panel"
        :aria-expanded="expanded"
        title="导出说明（可拖动）"
        @pointerdown="startDrag"
        @pointermove="moveDrag"
        @pointerup="endDrag"
        @pointercancel="endDrag"
        @keydown="moveWithKeyboard"
        @click="togglePanel"
      >
        <i class="bi" :class="expanded ? 'bi-chevron-down' : 'bi-question-lg'" />
        <span>导出说明</span>
      </button>
    </aside>
  </Teleport>
</template>

<style scoped>
.export-guide {
  --ease-out: cubic-bezier(.23, 1, .32, 1);
  position: fixed;
  z-index: 12040;
  top: 0;
  left: 0;
  width: 54px;
  height: 54px;
  pointer-events: none;
  will-change: transform;
}
.export-guide-orb {
  position: relative;
  display: grid;
  place-items: center;
  width: 54px;
  height: 54px;
  padding: 0;
  border: 1px solid color-mix(in srgb,var(--color-primary) 52%,var(--color-border));
  border-radius: 50%;
  color: #fff;
  background: linear-gradient(145deg,color-mix(in srgb,var(--color-primary) 92%,#fff),color-mix(in srgb,var(--color-primary) 72%,#111827));
  box-shadow: 0 12px 30px rgba(45,55,155,.28),inset 0 1px 0 rgba(255,255,255,.3);
  cursor: grab;
  pointer-events: auto;
  touch-action: none;
  user-select: none;
  transition: transform 140ms var(--ease-out),box-shadow 180ms var(--ease-out);
}
.export-guide-orb i { font-size: 1.05rem; }
.export-guide-orb span {
  position: absolute;
  right: calc(100% + 8px);
  padding: .28rem .5rem;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  color: var(--color-text-secondary);
  background: color-mix(in srgb,var(--color-surface) 90%,transparent);
  box-shadow: var(--shadow-sm);
  backdrop-filter: blur(10px);
  font-size: .65rem;
  font-weight: 700;
  white-space: nowrap;
}
.export-guide.opens-right .export-guide-orb span { right: auto; left: calc(100% + 8px); }
.export-guide.is-dragging .export-guide-orb { transform: scale(.97); cursor: grabbing; box-shadow: 0 18px 38px rgba(45,55,155,.34); }
.export-guide-orb:active { transform: scale(.96); }
.export-guide-orb:focus-visible { outline: 3px solid color-mix(in srgb,var(--color-primary) 34%,transparent); outline-offset: 3px; }

.export-guide-panel {
  position: absolute;
  right: 0;
  bottom: calc(100% + 10px);
  width: min(410px,calc(100vw - 24px));
  overflow: hidden auto;
  border: 1px solid var(--color-border-strong);
  border-radius: 18px;
  color: var(--color-text);
  background: color-mix(in srgb,var(--color-surface) 94%,transparent);
  box-shadow: 0 22px 60px rgba(12,18,55,.3);
  backdrop-filter: blur(18px) saturate(1.15);
  pointer-events: auto;
  transform-origin: bottom right;
  scrollbar-width: thin;
}
.export-guide.opens-right .export-guide-panel { right: auto; left: 0; transform-origin: bottom left; }
.export-guide.opens-below .export-guide-panel { top: calc(100% + 10px); bottom: auto; transform-origin: top right; }
.export-guide.opens-right.opens-below .export-guide-panel { transform-origin: top left; }
.export-guide-panel > header {
  position: sticky;
  z-index: 1;
  top: 0;
  display: grid;
  grid-template-columns: 36px minmax(0,1fr) 30px;
  align-items: center;
  gap: .65rem;
  padding: .8rem;
  border-bottom: 1px solid var(--color-border);
  background: color-mix(in srgb,var(--color-surface) 92%,transparent);
  backdrop-filter: blur(14px);
}
.export-guide-panel > header > span { display: grid; place-items: center; width: 36px; height: 36px; border-radius: 11px; color: var(--color-primary); background: var(--color-primary-soft); }
.export-guide-panel header small,.export-guide-panel header strong { display: block; }
.export-guide-panel header small { color: var(--color-text-muted); font-size: .62rem; }
.export-guide-panel header strong { font-size: .84rem; }
.export-guide-panel header button { display: grid; place-items: center; width: 30px; height: 30px; padding: 0; border: 0; border-radius: 9px; color: var(--color-text-muted); background: transparent; }
.export-guide-panel header button:hover { color: var(--color-text); background: var(--color-surface-subtle); }
.export-guide-content { display: grid; gap: .9rem; padding: .9rem; }
.export-guide-content > section { padding-bottom: .85rem; border-bottom: 1px solid var(--color-border); }
.export-guide-content h6 { display: flex; align-items: center; gap: .4rem; margin: 0 0 .6rem; font-size: .76rem; }
.export-guide-content h6 i { color: var(--color-primary); }
.guide-choice { padding: .65rem .7rem; border-left: 3px solid var(--color-primary); border-radius: 0 10px 10px 0; background: var(--color-surface-subtle); }
.guide-choice + .guide-choice { margin-top: .45rem; }
.guide-choice.is-incremental { border-left-color: #0ea5e9; }
.guide-choice.is-accepted { border-left-color: #10b981; }
.guide-choice strong { display: block; font-size: .72rem; }
.guide-choice p { margin: .2rem 0 0; color: var(--color-text-muted); font-size: .68rem; line-height: 1.5; }
.guide-live-note { display: flex; gap: .35rem; margin: .55rem 0 0; padding: .5rem .6rem; border-radius: 9px; color: var(--color-primary); background: var(--color-primary-soft); font-size: .67rem; line-height: 1.45; }
.guide-steps { display: grid; gap: .5rem; margin: 0; padding: 0; list-style: none; }
.guide-steps li { display: grid; grid-template-columns: 24px minmax(0,1fr); align-items: start; gap: .5rem; color: var(--color-text-secondary); font-size: .68rem; line-height: 1.5; }
.guide-steps b { display: grid; place-items: center; width: 22px; height: 22px; border-radius: 7px; color: var(--color-primary); background: var(--color-primary-soft); }
.guide-files { display: grid; gap: .42rem; margin: 0; }
.guide-files div { display: grid; grid-template-columns: 92px minmax(0,1fr); gap: .45rem; }
.guide-files dt { color: var(--color-text); font-size: .67rem; }
.guide-files dd { margin: 0; color: var(--color-text-muted); font-size: .66rem; line-height: 1.45; }
.guide-warning { display: flex; gap: .4rem; margin: 0; padding: .62rem .68rem; border-radius: 10px; color: var(--color-warning); background: var(--color-warning-soft); font-size: .67rem; line-height: 1.5; }

.export-guide-panel-enter-active,.export-guide-panel-leave-active { transition: opacity 180ms var(--ease-out),transform 180ms var(--ease-out); }
.export-guide-panel-enter-from,.export-guide-panel-leave-to { opacity: 0; transform: scale(.96); }

@media (hover: hover) and (pointer: fine) {
  .export-guide-orb:hover { transform: translateY(-2px); box-shadow: 0 16px 36px rgba(45,55,155,.36),0 0 0 5px color-mix(in srgb,var(--color-primary) 10%,transparent); }
}
@media (max-width: 575.98px) {
  .export-guide-panel { width: min(360px,calc(100vw - 24px)); }
  .export-guide-orb span { display: none; }
  .guide-files div { grid-template-columns: 82px minmax(0,1fr); }
}
@media (prefers-reduced-motion: reduce) {
  .export-guide-orb { transition: box-shadow 150ms ease; }
  .export-guide-orb:hover,.export-guide-orb:active,.export-guide.is-dragging .export-guide-orb { transform: none; }
  .export-guide-panel-enter-active,.export-guide-panel-leave-active { transition: opacity 150ms ease; }
  .export-guide-panel-enter-from,.export-guide-panel-leave-to { transform: none; }
}
</style>
