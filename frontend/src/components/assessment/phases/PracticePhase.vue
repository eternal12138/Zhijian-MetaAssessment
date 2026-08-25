<script setup lang="ts">
import LiveRecordingWaveform from '../../audio/LiveRecordingWaveform.vue'

defineProps<{
  isRecording: boolean
  audioLevel: number
  mediaStream: MediaStream | null
  transcript: string
  practiceCompleted: boolean
  isBusy: boolean
}>()

const emit = defineEmits<{
  (e: 'toggle-recording'): void
  (e: 'next'): void
}>()
</script>

<template>
  <div class="card border-0 shadow-sm">
    <div class="card-body p-4 p-lg-5">
      <span class="badge bg-info-subtle text-info mb-3">练习录音不会作为正式任务数据上传</span>
      <h4 class="practice-question">练习：为了考察甲、乙两地小麦的长势，分别从中抽出10株苗，测得苗高如表1所示（单位：cm）。试问哪个地的小麦长得比较整齐。</h4>
      <div class="practice-table-panel mt-4">
        <p class="practice-table-title">表1 甲乙两地小麦苗高</p>
        <div class="table-responsive">
          <table class="table table-bordered practice-data-table mb-0" aria-label="表1 甲乙两地小麦苗高，单位厘米">
            <tbody>
              <tr>
                <th scope="row">甲</th>
                <td>12</td><td>13</td><td>14</td><td>15</td><td>10</td>
                <td>16</td><td>13</td><td>11</td><td>15</td><td>11</td>
              </tr>
              <tr>
                <th scope="row">乙</th>
                <td>11</td><td>16</td><td>17</td><td>14</td><td>13</td>
                <td>19</td><td>6</td><td>8</td><td>10</td><td>16</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <p class="text-muted mt-3">请点击录音按钮，并持续口头说出你的思考过程与答案。点击开始时会立即结束尚未播放完的题目朗读。</p>
      <button
        class="btn"
        :class="isRecording ? 'btn-danger' : 'btn-primary'"
        @click="emit('toggle-recording')"
      >
        <i :class="isRecording ? 'bi bi-stop-fill' : 'bi bi-mic-fill'" class="me-1" />
        {{ isRecording ? '结束练习录音' : '开始练习录音' }}
      </button>
      <LiveRecordingWaveform
        class="mt-3"
        :stream="mediaStream"
        :active="isRecording"
        :status="isRecording ? (audioLevel < .05 ? 'quiet' : 'recording') : 'idle'"
        :height="60"
      />
      <div class="transcript-box mt-4">
        {{ transcript || '实时字幕将显示在这里。' }}
      </div>
      <button
        class="btn btn-success mt-4"
        :disabled="isRecording || !practiceCompleted || isBusy"
        @click="emit('next')"
      >
        <span v-if="isBusy" class="spinner-border spinner-border-sm me-2"></span>
        练习完成，进入正式任务
      </button>
    </div>
  </div>
</template>

<style scoped>
.practice-question { max-width: 980px; font-size: 1.15rem; line-height: 1.75; }
.practice-table-panel {
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}
.practice-table-title {
  margin: 0;
  padding: .75rem 1rem;
  border-bottom: 1px solid var(--color-border);
  color: var(--color-text);
  background: var(--color-surface-subtle);
  font-weight: 700;
  text-align: center;
}
.practice-data-table { min-width: 680px; table-layout: fixed; }
.practice-data-table th,
.practice-data-table td {
  padding: .65rem .45rem;
  color: var(--color-text);
  text-align: center;
  vertical-align: middle;
}
.practice-data-table th { width: 64px; background: var(--color-surface-subtle); font-weight: 700; }
.transcript-box {
  min-height: 120px;
  max-height: 230px;
  overflow-y: auto;
  line-height: 1.7;
  border: 1px solid var(--color-border);
  background: var(--color-surface-subtle);
  border-radius: var(--radius-lg);
  padding: 1.25rem;
}
@media (max-width: 575.98px) {
  .practice-question { font-size: 1.02rem; line-height: 1.65; }
  .practice-table-title { text-align: left; }
  .transcript-box { min-height: 105px; max-height: 190px; padding: 1rem; }
}
</style>
