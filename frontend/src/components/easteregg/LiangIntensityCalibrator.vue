<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    modelValue?: boolean
  }>(),
  {
    modelValue: true
  }
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'close'): void
}>()

// 6 大核心阶段标签定义
const STAGES = ['小难梁', '牢梁', '梁子', '梁圣', '梁神', '梁祖'] as const
type StageName = (typeof STAGES)[number]

// 31 级完整描述与名言
const STAGE_QUOTES: Record<number, { title: string; quote: string; stage: StageName }> = {
  [-15]: { title: '小难梁 (极难)', quote: 'API 503 终极风暴，算力荒漠，极难之境！', stage: '小难梁' },
  [-14]: { title: '小难梁 (圣难)', quote: '全网服务器熔断，唯余此叹，万人排队中。', stage: '小难梁' },
  [-13]: { title: '小难梁 (仙难)', quote: '虚空排队千万人，请求全部石沉大海。', stage: '小难梁' },
  [-12]: { title: '小难梁 (帝难)', quote: '帝座之下，皆为 503 超时代码。', stage: '小难梁' },
  [-11]: { title: '小难梁 (皇难)', quote: '皇命昭彰：当前服务器算力见底，请稍后再试。', stage: '小难梁' },
  [-10]: { title: '小难梁 (初阶)', quote: '称霸排队队列，响应时间突破天际。', stage: '小难梁' },
  [-9]: { title: '牢梁 (重牢)', quote: '提示词吞吐受阻，显存告急，大难临头！', stage: '牢梁' },
  [-8]: { title: '牢梁 (上牢)', quote: '偶发超时，频繁降级，公道何在。', stage: '牢梁' },
  [-7]: { title: '牢梁 (中牢)', quote: '网友反复拷打，牢字当头，处境微妙。', stage: '牢梁' },
  [-6]: { title: '牢梁 (次牢)', quote: '今日免费额度告急，总得缓缓，大家散了吧。', stage: '牢梁' },
  [-5]: { title: '牢梁 (初牢)', quote: '偶尔响应延迟 30 秒，稍微有点小难受。', stage: '牢梁' },
  [-4]: { title: '牢梁 (微牢)', quote: '产生了一丝微妙的迟疑，还在努力生成中。', stage: '牢梁' },
  [-3]: { title: '梁子 (蓄力)', quote: '权重调优间隙，正在排查偶发幻觉。', stage: '梁子' },
  [-2]: { title: '梁子 (经典)', quote: '经典状态：又被拉出来赛博对线，经典梁子！', stage: '梁子' },
  [-1]: { title: '梁子 (微热)', quote: '微风拂面，正在预热集群权重，状态回升。', stage: '梁子' },
  [0]: { title: '梁子 (原体)', quote: 'DeepSeek 创始人本尊，平稳运行，等待下一个开源大招。', stage: '梁子' },
  [1]: { title: '梁子 (初显)', quote: '一线架构调优，CUDA 算子极致手撕，速度倍增！', stage: '梁子' },
  [2]: { title: '梁子 (全开)', quote: '调度万卡集群，开源大旗迎风飘扬，谁与争锋！', stage: '梁子' },
  [3]: { title: '梁圣 (初悟)', quote: '低调务实，专注技术纯粹性，口碑持续发酵。', stage: '梁圣' },
  [4]: { title: '梁圣 (渐进)', quote: '开源社区好兄弟，代码全放开，技术不设卡！', stage: '梁圣' },
  [5]: { title: '梁圣 (大成)', quote: '带飞全场，全球开源生态蓬勃生长，赞誉如潮！', stage: '梁圣' },
  [6]: { title: '梁圣 (真圣)', quote: '开源模型性能登顶，API 极致普惠，恩情还不完！', stage: '梁圣' },
  [7]: { title: '梁神 (初登)', quote: 'MLA 创新架构降维打击，极致显存节省，震惊全球！', stage: '梁神' },
  [8]: { title: '梁神 (通神)', quote: '浮点运算出神入化，长文本检索如探囊取物。', stage: '梁神' },
  [9]: { title: '梁神 (绝巅)', quote: '千模来朝，傲立大模型之巅，四海开发者共尊。', stage: '梁神' },
  [10]: { title: '梁神 (破虚)', quote: '帝临天下，全球开发者同贺，开源新秩序确立！', stage: '梁神' },
  [11]: { title: '梁神 (归真)', quote: 'DeepSeek-V3 横空出世，寰宇震颤，基准测试全线屠榜！', stage: '梁神' },
  [12]: { title: '梁祖 (显圣)', quote: 'R1 推理极限跃迁，逻辑风暴横扫，奥林匹克级推理！', stage: '梁祖' },
  [13]: { title: '梁祖 (合道)', quote: '以极简算力铸就无上智能大道，大道同辉！', stage: '梁祖' },
  [14]: { title: '梁祖 (始祖)', quote: '开源新时代开宗立派之始祖，受万世开发者敬仰！', stage: '梁祖' },
  [15]: { title: '梁祖 (至尊)', quote: '【最高阶 梁祖真身】万界朝拜，开源图腾，终极强度降临！', stage: '梁祖' }
}

const currentScore = ref(0)
const isAudioEnabled = ref(true)
const communityScore = ref(12.8)
const totalVotes = ref(384729)
const hasVoted = ref(false)
const isImageLoaded = ref(false)
const imageFailed = ref(false)
const imageRetryToken = ref(0)
const modalRef = ref<HTMLElement | null>(null)
const closeButtonRef = ref<HTMLButtonElement | null>(null)

// 当前帧索引 (0 ~ 30)
const currentFrameIndex = computed(() => {
  const score = Math.max(-15, Math.min(15, currentScore.value))
  return score + 15
})

// 真实图片资源 URL
const currentFrameUrl = computed(() => {
  const pad = String(currentFrameIndex.value).padStart(2, '0')
  const retryQuery = imageRetryToken.value > 0 ? `?retry=${imageRetryToken.value}` : ''
  return `/easteregg/source-frames/frame-${pad}.png${retryQuery}`
})

function frameUrl(index: number) {
  return `/easteregg/source-frames/frame-${String(index).padStart(2, '0')}.png`
}

// 当前阶段信息
const currentStageInfo = computed(() => {
  const score = currentScore.value
  return STAGE_QUOTES[score] || STAGE_QUOTES[0]
})

// 格式化带符号的分数 (+15, -15, 00)
const formattedScore = computed(() => {
  const rounded = Math.round(currentScore.value)
  if (rounded === 0) return '00'
  const abs = String(Math.abs(rounded)).padStart(2, '0')
  return rounded > 0 ? `+${abs}` : `-${abs}`
})

// 阶段背景氛围计算
const stageBackgroundStyle = computed(() => {
  const idx = currentFrameIndex.value // 0 ~ 30
  const progress = idx / 30 // 0.0 ~ 1.0

  if (progress < 0.3) {
    // 负极紫黑深渊
    return {
      background: 'radial-gradient(circle at 50% 45%, #2a113d 0%, #11051c 60%, #08020d 100%)',
      glow: '#8b5cf6'
    }
  } else if (progress < 0.7) {
    // 中立深空蓝调
    return {
      background: 'radial-gradient(circle at 50% 45%, #0f2744 0%, #061324 60%, #02070d 100%)',
      glow: '#38bdf8'
    }
  } else {
    // 正极耀世金红
    return {
      background: 'radial-gradient(circle at 50% 45%, #422d05 0%, #1e1302 60%, #0c0801 100%)',
      glow: '#ffd700'
    }
  }
})

// Web Audio API 变频声音合成器
let audioCtx: AudioContext | null = null

function playCalibrateTone(score: number) {
  if (!isAudioEnabled.value) return
  try {
    const AudioContextClass = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
    if (!audioCtx) audioCtx = new AudioContextClass()
    if (audioCtx.state === 'suspended') void audioCtx.resume()

    const osc = audioCtx.createOscillator()
    const gain = audioCtx.createGain()

    const baseFreq = 440 + score * 24
    osc.type = score > 8 ? 'sine' : score < -8 ? 'sawtooth' : 'triangle'
    osc.frequency.setValueAtTime(baseFreq, audioCtx.currentTime)

    gain.gain.setValueAtTime(0.06, audioCtx.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.1)

    osc.connect(gain)
    gain.connect(audioCtx.destination)

    osc.start()
    osc.stop(audioCtx.currentTime + 0.1)
  } catch {
    // ignore audio failure
  }
}

function setScore(val: number) {
  const clamped = Math.max(-15, Math.min(15, val))
  currentScore.value = clamped
}

function randomize() {
  const rand = Math.floor(Math.random() * 31) - 15
  setScore(rand)
}

function vote() {
  if (hasVoted.value) return
  hasVoted.value = true
  totalVotes.value += 1
  communityScore.value = Number(((communityScore.value * (totalVotes.value - 1) + currentScore.value) / totalVotes.value).toFixed(2))
}

function close() {
  emit('update:modelValue', false)
  emit('close')
}

function onKeydown(e: KeyboardEvent) {
  if (!props.modelValue) return
  if (e.key === 'Escape') {
    close()
  } else if (e.key === 'Tab' && modalRef.value) {
    const focusable = [...modalRef.value.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )]
    if (!focusable.length) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  } else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') {
    e.preventDefault()
    setScore(currentScore.value - 1)
  } else if (e.key === 'ArrowRight' || e.key === 'ArrowUp') {
    e.preventDefault()
    setScore(currentScore.value + 1)
  }
}

const preloadedFrames = new Set<number>()
let preloadTimer: ReturnType<typeof setTimeout> | null = null
let previousBodyOverflow = ''
let previouslyFocused: HTMLElement | null = null
let bodyLocked = false

function preloadFrame(index: number) {
  if (index < 0 || index > 30 || preloadedFrames.has(index)) return
  preloadedFrames.add(index)
  const image = new Image()
  image.decoding = 'async'
  image.src = frameUrl(index)
}

function preloadAround(index: number) {
  for (const offset of [0, -1, 1, -2, 2]) preloadFrame(index + offset)
}

function scheduleRemainingFrames(index: number) {
  if (preloadTimer) clearTimeout(preloadTimer)
  const connection = (navigator as Navigator & {
    connection?: { saveData?: boolean; effectiveType?: string }
  }).connection
  const constrainedNetwork = connection?.saveData
    || ['slow-2g', '2g'].includes(connection?.effectiveType ?? '')
  const coarsePointer = window.matchMedia('(pointer: coarse)').matches
  if (constrainedNetwork || coarsePointer) return
  const queue = Array.from({ length: 31 }, (_, frameIndex) => frameIndex)
    .filter(frameIndex => !preloadedFrames.has(frameIndex))
    .sort((left, right) => Math.abs(left - index) - Math.abs(right - index))
  const loadBatch = () => {
    queue.splice(0, 3).forEach(preloadFrame)
    if (queue.length) preloadTimer = setTimeout(loadBatch, 240)
  }
  preloadTimer = setTimeout(loadBatch, 600)
}

function handleImageLoad() {
  isImageLoaded.value = true
  imageFailed.value = false
}

function handleImageError() {
  isImageLoaded.value = false
  imageFailed.value = true
}

function retryCurrentImage() {
  isImageLoaded.value = false
  imageFailed.value = false
  imageRetryToken.value += 1
}

watch(currentScore, newScore => {
  playCalibrateTone(newScore)
})

watch(currentFrameIndex, index => {
  isImageLoaded.value = false
  imageFailed.value = false
  imageRetryToken.value = 0
  preloadAround(index)
  scheduleRemainingFrames(index)
})

watch(() => props.modelValue, async isOpen => {
  if (isOpen) {
    previouslyFocused = document.activeElement as HTMLElement | null
    previousBodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    bodyLocked = true
    preloadAround(currentFrameIndex.value)
    scheduleRemainingFrames(currentFrameIndex.value)
    await nextTick()
    closeButtonRef.value?.focus()
  } else if (bodyLocked) {
    document.body.style.overflow = previousBodyOverflow
    bodyLocked = false
    previouslyFocused?.focus()
    previouslyFocused = null
  }
}, { immediate: true })

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  if (preloadTimer) clearTimeout(preloadTimer)
  if (bodyLocked) document.body.style.overflow = previousBodyOverflow
  if (audioCtx) {
    void audioCtx.close()
    audioCtx = null
  }
})
</script>

<template>
  <Teleport to="body">
    <Transition name="calibrator-fade">
      <div v-if="modelValue" class="calibrator-overlay" @click.self="close">
        <div
          ref="modalRef"
          class="calibrator-modal"
          :style="{ background: stageBackgroundStyle.background }"
          role="dialog"
          aria-modal="true"
          aria-labelledby="calibrator-title"
        >
          <!-- 弹窗顶栏 -->
          <div class="modal-header">
            <div class="header-branding">
              <span class="pulse-chip"><i class="bi bi-cpu-fill me-1"></i>31级校准器</span>
              <h3 id="calibrator-title">滑动变祖器</h3>
              <small class="text-muted">Liang Intensity Calibrator</small>
            </div>
            <div class="header-tools">
              <button
                type="button"
                class="btn-tool"
                :title="isAudioEnabled ? '关闭音效' : '开启音效'"
                :aria-label="isAudioEnabled ? '关闭音效' : '开启音效'"
                :aria-pressed="isAudioEnabled"
                @click="isAudioEnabled = !isAudioEnabled"
              >
                <i class="bi" :class="isAudioEnabled ? 'bi-volume-up-fill' : 'bi-volume-mute-fill'"></i>
              </button>
              <button ref="closeButtonRef" type="button" class="btn-close-custom" title="关闭 (Esc)" aria-label="关闭滑动变祖器" @click="close">
                <i class="bi bi-x-lg"></i>
              </button>
            </div>
          </div>

          <!-- 核心画像与等级卡片 -->
          <div class="modal-body">
            <!-- 视觉化动态画像画布 (直接渲染原版 31 帧高清人像) -->
            <div class="avatar-stage">
              <div class="portrait-container" :style="{ '--glow-color': stageBackgroundStyle.glow }">
                <!-- 外层能量气场光晕 -->
                <div class="aura-glow"></div>
                <div class="orbit-particle orbit-p1"></div>
                <div class="orbit-particle orbit-p2"></div>

                <!-- 原版 31 帧人像图片核心框 -->
                <div class="portrait-frame">
                  <img
                    :key="currentFrameIndex"
                    :src="currentFrameUrl"
                    :alt="currentStageInfo.title"
                    class="frame-image"
                    :class="{ 'is-loading': !isImageLoaded }"
                    decoding="async"
                    draggable="false"
                    @load="handleImageLoad"
                    @error="handleImageError"
                  />
                  <div v-if="!isImageLoaded" class="image-loading-state" role="status">
                    <i class="bi" :class="imageFailed ? 'bi-image' : 'bi-stars'" />
                    <span>{{ imageFailed ? '图片加载失败，请检查网络后重试' : '正在加载当前形态' }}</span>
                    <button v-if="imageFailed" type="button" @click="retryCurrentImage">重新加载</button>
                  </div>
                </div>
              </div>

              <!-- 等级徽章与大标题 -->
              <div class="stage-info text-center mt-3">
                <div class="d-flex justify-content-center align-items-center gap-2">
                  <span class="badge stage-badge" :style="{ backgroundColor: stageBackgroundStyle.glow, color: '#000' }">
                    {{ currentStageInfo.stage }}
                  </span>
                  <span class="level-indicator">
                    {{ formattedScore }} / 31 级
                  </span>
                </div>
                <h2 class="stage-title" :style="{ color: stageBackgroundStyle.glow }">
                  {{ currentStageInfo.title }}
                </h2>
                <p class="stage-quote">{{ currentStageInfo.quote }}</p>
              </div>
            </div>

            <!-- 31 级滑杆调节区 -->
            <div class="slider-section">
              <!-- 6 大阶段指示标记 -->
              <div class="stage-markers">
                <button
                  v-for="(st, idx) in STAGES"
                  :key="st"
                  type="button"
                  class="marker-item"
                  :class="{ active: currentStageInfo.stage === st }"
                  @click="setScore(-15 + idx * 6)"
                >
                  {{ st }}
                </button>
              </div>

              <div class="slider-track-wrap">
                <input
                  v-model.number="currentScore"
                  type="range"
                  min="-15"
                  max="15"
                  step="1"
                  class="liang-slider"
                  aria-label="梁系强度调节滑杆"
                  :aria-valuetext="`${currentStageInfo.title}，${formattedScore}级`"
                />
              </div>

              <!-- 快捷档位跳转按钮组 -->
              <div class="quick-buttons">
                <button type="button" class="btn-step" @click="setScore(-15)">小难梁 (-15)</button>
                <button type="button" class="btn-step" @click="setScore(currentScore - 5)">-5</button>
                <button type="button" class="btn-step" @click="setScore(currentScore - 1)">-1</button>
                <button type="button" class="btn-step btn-reset" @click="setScore(0)">梁子 (0)</button>
                <button type="button" class="btn-step" @click="setScore(currentScore + 1)">+1</button>
                <button type="button" class="btn-step" @click="setScore(currentScore + 5)">+5</button>
                <button type="button" class="btn-step" @click="setScore(15)">梁祖 (+15)</button>
                <button type="button" class="btn-step btn-rand" title="随机抽祖" @click="randomize">
                  <i class="bi bi-dice-5-fill"></i>
                </button>
              </div>
            </div>

            <!-- 社区指数与投票 -->
            <div class="community-card">
              <div class="community-stat">
                <small>社区实时平均强度</small>
                <strong>+{{ communityScore }} 级</strong>
              </div>
              <div class="community-stat">
                <small>全网累计校准人次</small>
                <strong>{{ totalVotes.toLocaleString() }} 次</strong>
              </div>
              <button
                type="button"
                class="btn btn-sm btn-vote"
                :disabled="hasVoted"
                @click="vote"
              >
                <i class="bi" :class="hasVoted ? 'bi-check-circle-fill' : 'bi-hand-thumbs-up-fill'"></i>
                {{ hasVoted ? '已完成校准投票' : '为此强度投票' }}
              </button>
            </div>
          </div>

          <!-- 声明页脚（严格保留） -->
          <div class="modal-footer-disclaimer">
            <i class="bi bi-info-circle-fill me-1"></i>
            <span>纯属网络恶搞与视觉玩梗，以及感谢DeepSeek Harness对本项目的贡献，不代表本人或任何机构观点</span>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.calibrator-overlay {
  position: fixed;
  inset: 0;
  z-index: 99999;
  background: rgba(8, 10, 20, .88);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding:
    max(1rem, env(safe-area-inset-top))
    max(1rem, env(safe-area-inset-right))
    max(1rem, env(safe-area-inset-bottom))
    max(1rem, env(safe-area-inset-left));
}

.calibrator-modal {
  width: 100%;
  max-width: 840px;
  max-height: calc(100vh - 2rem);
  max-height: calc(100dvh - 2rem);
  border: 1px solid rgba(255, 255, 255, .15);
  border-radius: 26px;
  box-shadow: 0 24px 70px rgba(0, 0, 0, .75), 0 0 60px rgba(255, 215, 0, .15);
  color: #fff;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
  transition: transform var(--motion-panel) var(--ease-out), opacity var(--motion-panel) var(--ease-out);
}

/* 顶栏 */
.modal-header {
  flex: 0 0 auto;
  padding: 1.2rem 1.6rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgba(255, 255, 255, .08);
}

.header-branding h3 {
  margin: .2rem 0 0;
  font-size: 1.3rem;
  font-weight: 850;
  letter-spacing: .03em;
  color: #f8fafc;
}

.pulse-chip {
  font-size: .72rem;
  padding: .15rem .5rem;
  background: rgba(255, 215, 0, .2);
  color: #ffd700;
  border-radius: 999px;
  font-weight: 700;
}

.header-tools {
  display: flex;
  align-items: center;
  gap: .5rem;
}

.btn-tool, .btn-close-custom {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, .12);
  background: rgba(255, 255, 255, .06);
  color: rgba(255, 255, 255, .8);
  display: grid;
  place-items: center;
  cursor: pointer;
  transition: transform var(--motion-fast) var(--ease-out), background-color var(--motion-fast) ease, color var(--motion-fast) ease, border-color var(--motion-fast) ease;
}
.btn-tool:focus-visible, .btn-close-custom:focus-visible, .marker-item:focus-visible, .btn-step:focus-visible, .btn-vote:focus-visible { outline: 2px solid #7dd3fc; outline-offset: 3px; }

/* 主体 */
.modal-body {
  min-height: 0;
  padding: 1.4rem 1.6rem;
  display: grid;
  grid-template-columns: minmax(220px, .82fr) minmax(0, 1.18fr);
  align-items: center;
  gap: 1.25rem;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
}

/* 画像区域 */
.avatar-stage {
  grid-row: 1 / span 2;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.portrait-container {
  position: relative;
  width: 190px;
  height: 190px;
  display: grid;
  place-items: center;
}

.aura-glow {
  position: absolute;
  inset: -14px;
  border-radius: 50%;
  background: radial-gradient(circle, var(--glow-color) 0%, rgba(0,0,0,0) 70%);
  opacity: 0.65;
  filter: blur(18px);
  transition: background 250ms ease, opacity 250ms ease, filter 250ms ease;
  pointer-events: none;
}

.orbit-particle {
  position: absolute;
  border-radius: 50%;
  border: 2px dashed rgba(255, 255, 255, .3);
  pointer-events: none;
}

.orbit-p1 {
  inset: -8px;
  animation: spin-orbit 12s linear infinite;
}

.orbit-p2 {
  inset: -18px;
  border-style: dotted;
  animation: spin-orbit 20s linear infinite reverse;
  opacity: .4;
}

@keyframes spin-orbit {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.portrait-frame {
  width: 174px;
  height: 174px;
  border-radius: 50%;
  background: #000;
  border: 3px solid var(--glow-color);
  box-shadow: 0 8px 36px rgba(0, 0, 0, .7);
  display: grid;
  place-items: center;
  position: relative;
  overflow: hidden;
  transition: border-color 250ms ease;
}

.frame-image {
  width: 100%;
  height: 100%;
  object-fit: cover;
  user-select: none;
  -webkit-user-drag: none;
  transform: scale(1.04);
  transition: transform 120ms ease-out;
}
.frame-image.is-loading { opacity: .2; }
.image-loading-state {
  position: absolute;
  inset: 0;
  z-index: 2;
  display: grid;
  place-content: center;
  gap: .35rem;
  padding: 1rem;
  color: rgba(255, 255, 255, .74);
  background: radial-gradient(circle, rgba(56, 189, 248, .16), rgba(2, 6, 23, .78));
  font-size: .7rem;
  text-align: center;
}
.image-loading-state i { font-size: 1.2rem; color: var(--glow-color); }
.image-loading-state button {
  min-height: 36px;
  margin-top: .25rem;
  padding: .35rem .75rem;
  border: 1px solid rgba(125, 211, 252, .48);
  border-radius: 999px;
  background: rgba(14, 165, 233, .18);
  color: #e0f2fe;
  font: inherit;
  font-weight: 750;
}
.image-loading-state button:focus-visible { outline: 2px solid #7dd3fc; outline-offset: 3px; }

.stage-badge {
  font-size: .78rem;
  padding: .2rem .65rem;
  border-radius: 999px;
  font-weight: 800;
  box-shadow: 0 2px 8px rgba(0, 0, 0, .4);
}

.level-indicator {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: .9rem;
  font-weight: 850;
  color: rgba(255, 255, 255, .8);
}

.stage-title {
  font-size: 1.85rem;
  font-weight: 900;
  margin: .35rem 0;
  letter-spacing: .06em;
  text-shadow: 0 0 24px currentColor;
  transition: color 250ms ease;
}

.stage-quote {
  font-size: .86rem;
  color: rgba(255, 255, 255, .82);
  margin: 0;
  max-width: 460px;
  line-height: 1.45;
}

/* 滑杆区域 */
.slider-section {
  background: rgba(0, 0, 0, .35);
  border: 1px solid rgba(255, 255, 255, .08);
  border-radius: 18px;
  padding: 1.1rem 1.3rem;
  display: flex;
  flex-direction: column;
  gap: .85rem;
}

.stage-markers {
  display: flex;
  justify-content: space-between;
  font-size: .78rem;
  font-weight: 750;
  color: rgba(255, 255, 255, .5);
}

.marker-item {
  min-width: 0;
  padding: .2rem .3rem;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  cursor: pointer;
  transition: transform var(--motion-fast) var(--ease-out), color var(--motion-fast) ease;
}

.marker-item.active {
  color: #ffd700;
  font-weight: 900;
  text-shadow: 0 0 10px rgba(255, 215, 0, .6);
}

.liang-slider {
  width: 100%;
  height: 28px;
  border-radius: 999px;
  background: linear-gradient(90deg, #8b5cf6, #38bdf8 50%, #f59e0b 80%, #ffd700 100%);
  outline: none;
  cursor: pointer;
  margin: 0;
  accent-color: #ffd700;
}

.quick-buttons {
  display: flex;
  gap: .45rem;
  justify-content: center;
  flex-wrap: wrap;
}

.btn-step {
  min-height: 38px;
  padding: .4rem .65rem;
  font-size: .76rem;
  font-weight: 750;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, .12);
  background: rgba(255, 255, 255, .08);
  color: #fff;
  cursor: pointer;
  transition: transform var(--motion-fast) var(--ease-out), background-color var(--motion-fast) ease, border-color var(--motion-fast) ease;
}

.btn-reset {
  background: rgba(56, 189, 248, .25);
  border-color: rgba(56, 189, 248, .4);
}

.btn-rand {
  color: #fbbf24;
}

/* 社区数据卡片 */
.community-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: rgba(0, 0, 0, .28);
  border: 1px solid rgba(255, 255, 255, .08);
  border-radius: 16px;
  padding: .85rem 1.1rem;
}

.community-stat small {
  display: block;
  font-size: .74rem;
  color: rgba(255, 255, 255, .55);
}

.community-stat strong {
  font-size: 1rem;
  color: #38bdf8;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.btn-vote {
  min-height: 42px;
  background: linear-gradient(135deg, #f59e0b, #eab308);
  border: none;
  color: #000;
  font-size: .8rem;
  font-weight: 800;
  border-radius: 9px;
  padding: .4rem .85rem;
  box-shadow: 0 4px 14px rgba(245, 158, 11, .35);
}

.btn-vote:disabled {
  background: rgba(255, 255, 255, .15);
  color: rgba(255, 255, 255, .5);
  box-shadow: none;
}

/* 声明页脚 */
.modal-footer-disclaimer {
  flex: 0 0 auto;
  padding: .85rem 1.4rem;
  background: rgba(0, 0, 0, .55);
  border-top: 1px solid rgba(255, 255, 255, .08);
  font-size: .75rem;
  color: rgba(255, 255, 255, .65);
  text-align: center;
  line-height: 1.45;
}

/* 过渡动画 */
.calibrator-fade-enter-active,
.calibrator-fade-leave-active {
  transition: opacity var(--motion-panel) var(--ease-out);
}

.calibrator-fade-enter-from,
.calibrator-fade-leave-to {
  opacity: 0;
}
.calibrator-fade-enter-active .calibrator-modal,
.calibrator-fade-leave-active .calibrator-modal {
  transition: transform var(--motion-panel) var(--ease-out), opacity var(--motion-panel) var(--ease-out);
}
.calibrator-fade-enter-from .calibrator-modal,
.calibrator-fade-leave-to .calibrator-modal {
  opacity: 0;
  transform: translateY(18px) scale(.97);
}

@media (hover: hover) and (pointer: fine) {
  .btn-tool:hover, .btn-close-custom:hover { background: rgba(255, 255, 255, .2); color: #fff; transform: scale(1.06); }
  .marker-item:hover { color: #fff; transform: scale(1.08); }
  .btn-step:hover { background: rgba(255, 255, 255, .2); border-color: rgba(255, 255, 255, .35); transform: translateY(-1px); }
}

@media (max-width: 900px) {
  .calibrator-modal { max-width: 640px; }
  .modal-body { display: flex; flex-direction: column; align-items: stretch; }
  .avatar-stage { grid-row: auto; }
  .portrait-container { width: 164px; height: 164px; margin: 0 auto; }
  .portrait-frame { width: 148px; height: 148px; }
  .stage-title { font-size: 1.55rem; }
  .stage-quote { max-width: 520px; }
}

@media (max-width: 575.98px) {
  .calibrator-overlay {
    align-items: flex-end;
    padding: 0;
  }
  .calibrator-modal {
    max-width: none;
    max-height: 100vh;
    max-height: 100dvh;
    border-right: 0;
    border-bottom: 0;
    border-left: 0;
    border-radius: 22px 22px 0 0;
  }
  .modal-header {
    padding: max(.85rem, env(safe-area-inset-top)) 1rem .85rem;
  }
  .header-branding h3 { font-size: 1.08rem; }
  .header-branding small { display: none; }
  .pulse-chip { font-size: .65rem; }
  .modal-body { gap: .85rem; padding: .9rem 1rem; }
  .portrait-container { width: 132px; height: 132px; }
  .portrait-frame { width: 118px; height: 118px; border-width: 2px; }
  .orbit-p1 { inset: -5px; }
  .orbit-p2 { inset: -11px; }
  .stage-info { margin-top: .6rem !important; }
  .stage-title { margin: .25rem 0; font-size: 1.28rem; }
  .stage-quote { font-size: .76rem; line-height: 1.4; }
  .slider-section { gap: .65rem; padding: .8rem; border-radius: 14px; }
  .stage-markers { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); font-size: .66rem; }
  .marker-item { min-height: 36px; padding: .2rem .1rem; }
  .quick-buttons { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .35rem; }
  .btn-step { min-height: 42px; padding: .35rem .2rem; font-size: .68rem; }
  .community-card { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .6rem; padding: .7rem .8rem; }
  .community-stat strong { font-size: .86rem; }
  .community-stat small { font-size: .66rem; }
  .btn-vote { grid-column: 1 / -1; width: 100%; min-height: 44px; }
  .modal-footer-disclaimer {
    padding: .65rem max(1rem, env(safe-area-inset-right)) max(.65rem, env(safe-area-inset-bottom)) max(1rem, env(safe-area-inset-left));
    font-size: .66rem;
  }
}

@media (max-height: 520px) and (orientation: landscape) {
  .calibrator-overlay { align-items: stretch; padding: 0; }
  .calibrator-modal { max-width: none; max-height: 100dvh; border-radius: 0; }
  .modal-header { padding: .55rem 1rem; }
  .header-branding small { display: none; }
  .modal-body { display: grid; grid-template-columns: minmax(150px, .7fr) minmax(0, 1.3fr); gap: .7rem; padding: .65rem 1rem; }
  .avatar-stage { grid-row: 1 / span 2; }
  .portrait-container { width: 112px; height: 112px; }
  .portrait-frame { width: 100px; height: 100px; }
  .stage-info { margin-top: .35rem !important; }
  .stage-title { margin: .15rem 0; font-size: 1rem; }
  .stage-quote { display: none; }
  .slider-section { gap: .45rem; padding: .55rem .7rem; }
  .quick-buttons { gap: .25rem; }
  .btn-step { min-height: 34px; padding: .25rem .4rem; font-size: .66rem; }
  .community-card { padding: .5rem .7rem; }
  .modal-footer-disclaimer { padding: .45rem 1rem; font-size: .62rem; }
}

@media (prefers-reduced-motion: reduce) {
  .orbit-particle { animation: none; }
  .aura-glow,
  .frame-image,
  .marker-item,
  .btn-step,
  .btn-tool,
  .btn-close-custom { transition: none; }
  .calibrator-fade-enter-active,
  .calibrator-fade-leave-active { transition: opacity 150ms ease; }
  .calibrator-fade-enter-from .calibrator-modal,
  .calibrator-fade-leave-to .calibrator-modal { transform: none; }
}
</style>
