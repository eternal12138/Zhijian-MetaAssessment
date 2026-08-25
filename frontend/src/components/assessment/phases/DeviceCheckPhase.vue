<script setup lang="ts">
import LiveRecordingWaveform from '../../audio/LiveRecordingWaveform.vue'

defineProps<{
  permission: string
  microphoneTestStatus: string
  microphoneTestSecondsRemaining: number
  microphoneTestLevel: number
  mediaStream: MediaStream | null
  recognitionAvailable: boolean
  speechSynthesisAvailable: boolean
  narrationAssetsCount: number
  isBusy: boolean
}>()

const emit = defineEmits<{
  (e: 'test-microphone'): void
  (e: 'next'): void
}>()
</script>

<template>
  <div class="card border-0 shadow-sm">
    <div class="card-body p-4 p-lg-5">
      <h4>设备检查</h4>
      <p class="text-muted">开始前需要完成一次 5 秒声音测试，确保实验录音可以正常采集。</p>
      <div class="device-check-layout my-4">
        <ol class="device-steps" aria-label="麦克风检查步骤">
          <li :class="{ complete: permission === 'granted' }">
            <span>1</span><div><strong>允许麦克风</strong><small>在浏览器提示中选择“允许”</small></div>
          </li>
          <li :class="{ complete: microphoneTestStatus === 'passed' }">
            <span>2</span><div><strong>朗读测试语句</strong><small>用正常音量说“我正在测试麦克风”</small></div>
          </li>
          <li :class="{ complete: microphoneTestStatus === 'passed' }">
            <span>3</span><div><strong>确认声音清晰</strong><small>通过后即可进入测评说明</small></div>
          </li>
        </ol>
        <div class="device-panel d-flex align-items-center gap-3">
          <span class="device-icon" :class="{ 'is-testing': microphoneTestStatus === 'testing' }">
            <i class="bi bi-mic-fill" />
          </span>
          <div class="flex-grow-1">
            <div class="fw-semibold">
              {{
                microphoneTestStatus === 'testing'
                  ? `正在检测声音，请持续说话（${microphoneTestSecondsRemaining} 秒）`
                  : microphoneTestStatus === 'passed'
                    ? '声音测试通过'
                    : microphoneTestStatus === 'too_quiet'
                      ? '声音过低或未检测到人声'
                      : permission === 'granted' ? '麦克风已授权，等待声音测试' : '等待麦克风授权'
              }}
            </div>
            <LiveRecordingWaveform
              class="mt-2 mb-2"
              :stream="mediaStream"
              :active="microphoneTestStatus === 'testing'"
              :status="microphoneTestStatus === 'testing' ? 'recording' : microphoneTestStatus === 'too_quiet' ? 'quiet' : 'idle'"
              :height="58"
            />
            <small v-if="microphoneTestStatus === 'too_quiet'" class="d-block text-danger mt-2">
              请确认麦克风未静音、靠近设备后重新测试。
            </small>
            <small :class="recognitionAvailable ? 'text-success' : 'text-danger'">
              实时字幕：{{ recognitionAvailable ? '当前浏览器支持' : '当前浏览器不支持' }}
            </small>
            <small class="d-block" :class="narrationAssetsCount ? 'text-success' : 'text-warning'">
              真人录音：{{ narrationAssetsCount ? `已配置 ${narrationAssetsCount} 段` : '尚未配置' }}
            </small>
            <small class="d-block" :class="speechSynthesisAvailable ? 'text-muted' : 'text-danger'">
              备用朗读：{{ speechSynthesisAvailable ? '浏览器支持' : '当前浏览器不支持' }}
            </small>
          </div>
        </div>
      </div>
      <div v-if="!recognitionAvailable" class="alert alert-warning">
        <i class="bi bi-badge-cc me-2" />
        当前浏览器不支持实时字幕。系统仍可录制并上传音频，但页面不会显示实时转录文字；
        建议改用最新版 Chrome 或 Edge。
      </div>
      <div class="device-actions d-flex gap-2">
        <button
          class="btn btn-outline-primary"
          :disabled="microphoneTestStatus === 'testing'"
          @click="emit('test-microphone')"
        >
          <span v-if="microphoneTestStatus === 'testing'" class="spinner-border spinner-border-sm me-2" />
          {{ microphoneTestStatus === 'testing' ? '正在测试' : microphoneTestStatus === 'passed' ? '重新测试' : '授权并测试麦克风' }}
        </button>
        <button
          class="btn btn-primary"
          :disabled="microphoneTestStatus !== 'passed' || isBusy"
          @click="emit('next')"
        >
          下一步
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.device-panel {
  border: 1px solid var(--color-border);
  background: var(--color-surface-subtle);
  border-radius: var(--radius-lg);
  padding: 1.25rem;
}
.device-check-layout {
  display: grid;
  grid-template-columns: minmax(230px, .72fr) minmax(0, 1.28fr);
  gap: 1rem;
}
.device-steps {
  display: grid;
  gap: .7rem;
  margin: 0;
  padding: 0;
  list-style: none;
}
.device-steps li { display: flex; align-items: center; gap: .7rem; color: var(--color-text-muted); }
.device-steps li > span {
  display: grid;
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  place-items: center;
  border: 1px solid var(--color-border);
  border-radius: 50%;
  background: var(--color-surface);
  font-size: .76rem;
  font-weight: 700;
}
.device-steps strong,
.device-steps small { display: block; }
.device-steps strong { color: var(--color-text); font-size: .84rem; }
.device-steps small { margin-top: .1rem; font-size: .72rem; }
.device-steps li.complete > span { color: #fff; border-color: var(--color-success); background: var(--color-success); }
.device-steps li.complete > span::before { content: '✓'; }
.device-steps li.complete > span { font-size: 0; }
.device-steps li.complete > span::before { font-size: .8rem; }
.device-icon {
  display: grid;
  place-items: center;
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-size: 1.35rem;
}
.device-icon.is-testing { color: #fff; background: var(--color-primary); }
@media (max-width: 768px) {
  .device-check-layout { grid-template-columns: 1fr; }
}
@media (max-width: 575.98px) {
  .device-panel { align-items: flex-start !important; padding: 1rem; }
  .device-icon { width: 44px; height: 44px; flex: 0 0 44px; }
  .device-actions { flex-wrap: wrap; }
  .device-actions .btn { flex: 1 1 100%; min-height: 44px; }
  .device-steps { gap: .55rem; }
}
</style>
