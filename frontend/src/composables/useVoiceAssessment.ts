import { computed, onBeforeUnmount, ref, shallowRef, triggerRef } from 'vue'

export type MicrophonePermission = 'idle' | 'requesting' | 'granted' | 'denied' | 'unsupported'
export type RecordingStatus = 'idle' | 'starting' | 'recording' | 'paused' | 'stopped' | 'error'
export type MicrophoneTestStatus = 'idle' | 'testing' | 'passed' | 'too_quiet' | 'error'

export interface TranscriptSegment {
  id: string
  text: string
  createdAt: number
  startedAtMs: number
  endedAtMs: number
}

export interface AudioChunkPayload {
  blob: Blob
  chunkIndex: number
  startedAtMs: number
  endedAtMs: number
  mimeType: string
}

export interface SpeechActivityPayload {
  occurredAtMs: number
  detectedAt: number
}

interface SpeechRecognitionAlternativeLike {
  transcript: string
}

interface SpeechRecognitionResultLike {
  isFinal: boolean
  length: number
  [index: number]: SpeechRecognitionAlternativeLike
}

interface SpeechRecognitionEventLike extends Event {
  resultIndex: number
  results: {
    length: number
    [index: number]: SpeechRecognitionResultLike
  }
}

interface SpeechRecognitionErrorEventLike extends Event {
  error: string
}

interface SpeechRecognitionLike {
  continuous: boolean
  interimResults: boolean
  lang: string
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null
  onend: (() => void) | null
  start(): void
  stop(): void
  abort(): void
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike

declare global {
  interface Window {
    SpeechRecognition?: SpeechRecognitionConstructor
    webkitSpeechRecognition?: SpeechRecognitionConstructor
  }
}

interface VoiceAssessmentOptions {
  silenceThresholdMs?: number
  volumeThreshold?: number
  audioChunkTimesliceMs?: number
  onAudioChunk?: (payload: AudioChunkPayload) => void
  onFinalTranscript?: (segment: TranscriptSegment) => void
  onSilence?: () => void
  onSpeechStart?: (payload: SpeechActivityPayload) => void
  onSpeechEnd?: (payload: SpeechActivityPayload) => void
  onRecognitionUnavailable?: (reason: string) => void
}

export function useVoiceAssessment(options: VoiceAssessmentOptions = {}) {
  const silenceThresholdMs = options.silenceThresholdMs ?? 15_000
  const volumeThreshold = options.volumeThreshold ?? 0.025
  const audioChunkTimesliceMs = options.audioChunkTimesliceMs ?? 5_000

  const permission = ref<MicrophonePermission>('idle')
  const recordingStatus = ref<RecordingStatus>('idle')
  const errorMessage = ref('')
  const interimTranscript = ref('')
  const finalTranscript = ref('')
  const transcriptSegments = ref<TranscriptSegment[]>([])
  const audioBlob = ref<Blob | null>(null)
  const volumeLevel = ref(0)
  const frequencyData = shallowRef(new Uint8Array(256))
  const mediaStream = shallowRef<MediaStream | null>(null)
  const hasDetectedAudio = ref(false)
  const silentForMs = ref(0)
  const recordingDurationSeconds = ref(0)
  const recognitionAvailable = ref(
    typeof window !== 'undefined'
    && Boolean(window.SpeechRecognition ?? window.webkitSpeechRecognition)
  )
  const microphoneTestStatus = ref<MicrophoneTestStatus>('idle')
  const microphoneTestLevel = ref(0)
  const microphoneTestSecondsRemaining = ref(0)

  let stream: MediaStream | null = null
  let mediaRecorder: MediaRecorder | null = null
  let recognition: SpeechRecognitionLike | null = null
  let audioContext: AudioContext | null = null
  let analyser: AnalyserNode | null = null
  let animationFrameId: number | null = null
  let durationTimer: ReturnType<typeof setInterval> | null = null
  let lastVoiceAt = 0
  let lastSilenceReminderAt = 0
  let chunks: BlobPart[] = []
  let shouldRestartRecognition = false
  let chunkIndex = 0
  let recordingTimelineOffsetMs = 0
  let lastChunkEndMs = 0
  let lastTranscriptEndMs = 0
  let stopResolver: ((blob: Blob | null) => void) | null = null
  let voiceActive = false
  let voiceBelowSince = 0
  let recognitionUnavailableNotified = false
  let testAudioContext: AudioContext | null = null
  let testAnimationFrameId: number | null = null
  let testFinishTimer: ReturnType<typeof setTimeout> | null = null
  let testCountdownTimer: ReturnType<typeof setInterval> | null = null
  let testResolver: ((passed: boolean) => void) | null = null

  const isRecording = computed(() => recordingStatus.value === 'recording')
  const silenceRemainingSeconds = computed(() =>
    Math.max(0, Math.ceil((silenceThresholdMs - silentForMs.value) / 1000))
  )

  function getRecognitionConstructor() {
    return window.SpeechRecognition ?? window.webkitSpeechRecognition
  }

  async function requestMicrophonePermission() {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      permission.value = 'unsupported'
      errorMessage.value = '当前浏览器不支持录音，请使用最新版 Chrome 或 Edge。'
      return null
    }

    if (stream?.active) {
      mediaStream.value = stream
      permission.value = 'granted'
      return stream
    }

    permission.value = 'requesting'
    errorMessage.value = ''
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      })
      mediaStream.value = stream
      permission.value = 'granted'
      return stream
    } catch (error) {
      permission.value = 'denied'
      recordingStatus.value = 'error'
      errorMessage.value = error instanceof DOMException && error.name === 'NotAllowedError'
        ? '麦克风权限被拒绝，请在浏览器地址栏中允许麦克风后重试。'
        : '无法访问麦克风，请检查设备是否被其他程序占用。'
      return null
    }
  }

  function stopMicrophoneTest(resetStatus = true) {
    if (testAnimationFrameId !== null) cancelAnimationFrame(testAnimationFrameId)
    if (testFinishTimer) clearTimeout(testFinishTimer)
    if (testCountdownTimer) clearInterval(testCountdownTimer)
    testAnimationFrameId = null
    testFinishTimer = null
    testCountdownTimer = null
    void testAudioContext?.close()
    testAudioContext = null
    resetFrequencyData()
    if (testResolver) {
      testResolver(false)
      testResolver = null
    }
    if (resetStatus) {
      microphoneTestStatus.value = 'idle'
      microphoneTestLevel.value = 0
      microphoneTestSecondsRemaining.value = 0
    }
  }

  function resetFrequencyData() {
    frequencyData.value.fill(0)
    triggerRef(frequencyData)
  }

  async function testMicrophone(durationMs = 5_000) {
    stopMicrophoneTest()
    const activeStream = stream?.active ? stream : await requestMicrophonePermission()
    if (!activeStream) {
      microphoneTestStatus.value = 'error'
      return false
    }

    microphoneTestStatus.value = 'testing'
    microphoneTestLevel.value = 0
    microphoneTestSecondsRemaining.value = Math.ceil(durationMs / 1_000)
    let testAnalyser: AnalyserNode
    try {
      testAudioContext = new AudioContext()
      testAnalyser = testAudioContext.createAnalyser()
      testAnalyser.fftSize = 512
      testAnalyser.smoothingTimeConstant = 0.82
      testAudioContext.createMediaStreamSource(activeStream).connect(testAnalyser)
    } catch {
      stopMicrophoneTest(false)
      microphoneTestStatus.value = 'error'
      errorMessage.value = '麦克风已授权，但无法读取声音信号。请关闭占用麦克风的其他程序后重试。'
      return false
    }
    const samples = new Uint8Array(testAnalyser.fftSize)
    frequencyData.value = new Uint8Array(testAnalyser.frequencyBinCount)
    let peakRms = 0

    const monitor = () => {
      testAnalyser.getByteTimeDomainData(samples)
      testAnalyser.getByteFrequencyData(frequencyData.value)
      triggerRef(frequencyData)
      let sum = 0
      for (const sample of samples) {
        const normalized = (sample - 128) / 128
        sum += normalized * normalized
      }
      const rms = Math.sqrt(sum / samples.length)
      peakRms = Math.max(peakRms, rms)
      microphoneTestLevel.value = Math.min(1, rms * 8)
      testAnimationFrameId = requestAnimationFrame(monitor)
    }
    testAnimationFrameId = requestAnimationFrame(monitor)
    testCountdownTimer = setInterval(() => {
      microphoneTestSecondsRemaining.value = Math.max(
        0,
        microphoneTestSecondsRemaining.value - 1
      )
    }, 1_000)

    return await new Promise<boolean>(resolve => {
      testResolver = resolve
      testFinishTimer = setTimeout(() => {
        const passed = peakRms >= 0.006
        const complete = testResolver
        testResolver = null
        stopMicrophoneTest(false)
        microphoneTestLevel.value = 0
        microphoneTestSecondsRemaining.value = 0
        microphoneTestStatus.value = passed ? 'passed' : 'too_quiet'
        resetFrequencyData()
        complete?.(passed)
      }, durationMs)
    })
  }

  function chooseMimeType() {
    const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']
    return candidates.find(type => MediaRecorder.isTypeSupported(type)) ?? ''
  }

  function startSpeechRecognition() {
    const Recognition = getRecognitionConstructor()
    recognitionAvailable.value = Boolean(Recognition)
    if (!Recognition) {
      notifyRecognitionUnavailable('unsupported')
      return
    }

    recognition = new Recognition()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = 'zh-CN'
    shouldRestartRecognition = true

    recognition.onresult = event => {
      let interim = ''
      const finals: string[] = []
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index]
        const text = result[0]?.transcript.trim() ?? ''
        if (!text) continue
        if (result.isFinal) finals.push(text)
        else interim += text
      }

      interimTranscript.value = interim
      if (finals.length > 0) {
        const text = finals.join(' ')
        const endedAtMs = recordingTimelineOffsetMs
          + recordingDurationSeconds.value * 1_000
        const segment: TranscriptSegment = {
          id: `speech-${Date.now()}-${transcriptSegments.value.length}`,
          text,
          createdAt: Date.now(),
          startedAtMs: lastTranscriptEndMs,
          endedAtMs: Math.max(endedAtMs, lastTranscriptEndMs)
        }
        lastTranscriptEndMs = segment.endedAtMs
        finalTranscript.value = [finalTranscript.value, text].filter(Boolean).join(' ')
        transcriptSegments.value.push(segment)
        interimTranscript.value = ''
        options.onFinalTranscript?.(segment)
      }
    }

    recognition.onerror = event => {
      if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
        shouldRestartRecognition = false
        recognitionAvailable.value = false
        errorMessage.value = '浏览器实时语音识别不可用，录音仍会继续保存。'
        notifyRecognitionUnavailable(event.error)
      }
    }

    recognition.onend = () => {
      if (shouldRestartRecognition && recordingStatus.value === 'recording') {
        try {
          recognition?.start()
        } catch {
          // 浏览器可能在上一次识别尚未完全结束时拒绝重启，等待下一次录音即可。
        }
      }
    }

    try {
      recognition.start()
    } catch {
      errorMessage.value = '实时字幕启动失败，录音仍会继续保存。'
      notifyRecognitionUnavailable('start_failed')
    }
  }

  function notifyRecognitionUnavailable(reason: string) {
    if (recognitionUnavailableNotified) return
    recognitionUnavailableNotified = true
    options.onRecognitionUnavailable?.(reason)
  }

  function endSpeechActivity() {
    if (!voiceActive) return
    voiceActive = false
    voiceBelowSince = 0
    options.onSpeechEnd?.({
      occurredAtMs: recordingDurationSeconds.value * 1_000,
      detectedAt: Date.now()
    })
  }

  function startAudioMonitoring(activeStream: MediaStream) {
    audioContext = new AudioContext()
    analyser = audioContext.createAnalyser()
    analyser.fftSize = 512
    analyser.smoothingTimeConstant = 0.82
    const source = audioContext.createMediaStreamSource(activeStream)
    source.connect(analyser)

    const samples = new Uint8Array(analyser.fftSize)
    frequencyData.value = new Uint8Array(analyser.frequencyBinCount)
    lastVoiceAt = Date.now()
    lastSilenceReminderAt = 0
    voiceActive = false
    voiceBelowSince = 0

    const monitor = () => {
      if (!analyser || recordingStatus.value !== 'recording') return
      analyser.getByteTimeDomainData(samples)
      analyser.getByteFrequencyData(frequencyData.value)
      triggerRef(frequencyData)
      let sum = 0
      for (const sample of samples) {
        const normalized = (sample - 128) / 128
        sum += normalized * normalized
      }
      const rms = Math.sqrt(sum / samples.length)
      volumeLevel.value = Math.min(1, rms * 8)
      if (rms >= 0.006) hasDetectedAudio.value = true

      const now = Date.now()
      if (rms >= volumeThreshold) {
        if (!voiceActive) {
          voiceActive = true
          options.onSpeechStart?.({
            occurredAtMs: recordingDurationSeconds.value * 1_000,
            detectedAt: now
          })
        }
        voiceBelowSince = 0
        lastVoiceAt = now
        lastSilenceReminderAt = 0
      } else if (voiceActive) {
        if (!voiceBelowSince) voiceBelowSince = now
        if (now - voiceBelowSince >= 500) endSpeechActivity()
      }
      silentForMs.value = now - lastVoiceAt

      if (
        silentForMs.value >= silenceThresholdMs
        && now - lastSilenceReminderAt >= silenceThresholdMs
      ) {
        lastSilenceReminderAt = now
        lastVoiceAt = now
        silentForMs.value = 0
        options.onSilence?.()
      }
      animationFrameId = requestAnimationFrame(monitor)
    }

    animationFrameId = requestAnimationFrame(monitor)
  }

  async function startRecording(
    initialChunkIndex = 0,
    initialTimelineMs = 0
  ) {
    if (recordingStatus.value === 'recording') return true
    stopMicrophoneTest()
    recordingStatus.value = 'starting'
    const activeStream = stream?.active ? stream : await requestMicrophonePermission()
    if (!activeStream) return false

    chunks = []
    chunkIndex = Math.max(0, initialChunkIndex)
    recordingTimelineOffsetMs = Math.max(0, initialTimelineMs)
    lastChunkEndMs = recordingTimelineOffsetMs
    lastTranscriptEndMs = recordingTimelineOffsetMs
    recognitionUnavailableNotified = false
    audioBlob.value = null
    hasDetectedAudio.value = false
    interimTranscript.value = ''
    recordingDurationSeconds.value = 0

    const mimeType = chooseMimeType()
    mediaRecorder = mimeType
      ? new MediaRecorder(activeStream, { mimeType })
      : new MediaRecorder(activeStream)

    mediaRecorder.ondataavailable = event => {
      if (event.data.size <= 0) return
      chunks.push(event.data)
      const endedAtMs = recordingTimelineOffsetMs
        + recordingDurationSeconds.value * 1_000
      options.onAudioChunk?.({
        blob: event.data,
        chunkIndex,
        startedAtMs: lastChunkEndMs,
        endedAtMs: Math.max(endedAtMs, lastChunkEndMs),
        mimeType: event.data.type || mediaRecorder?.mimeType || 'audio/webm'
      })
      chunkIndex += 1
      lastChunkEndMs = Math.max(endedAtMs, lastChunkEndMs)
    }
    mediaRecorder.onstop = () => {
      audioBlob.value = new Blob(chunks, {
        type: mediaRecorder?.mimeType || 'audio/webm'
      })
      stopResolver?.(audioBlob.value)
      stopResolver = null
    }

    mediaRecorder.start(audioChunkTimesliceMs)
    recordingStatus.value = 'recording'
    startSpeechRecognition()
    startAudioMonitoring(activeStream)
    durationTimer = setInterval(() => {
      recordingDurationSeconds.value += 1
    }, 1_000)
    return true
  }

  function pauseRecording() {
    if (mediaRecorder?.state !== 'recording') return
    endSpeechActivity()
    mediaRecorder.pause()
    recordingStatus.value = 'paused'
    shouldRestartRecognition = false
    recognition?.stop()
    stopTimers()
    void audioContext?.close()
    audioContext = null
    analyser = null
    resetFrequencyData()
  }

  function resumeRecording() {
    if (mediaRecorder?.state !== 'paused') return
    mediaRecorder.resume()
    recordingStatus.value = 'recording'
    startSpeechRecognition()
    if (stream) startAudioMonitoring(stream)
    durationTimer = setInterval(() => {
      recordingDurationSeconds.value += 1
    }, 1_000)
  }

  function stopTimers() {
    if (animationFrameId !== null) cancelAnimationFrame(animationFrameId)
    animationFrameId = null
    if (durationTimer) clearInterval(durationTimer)
    durationTimer = null
  }

  function stopRecording(): Promise<Blob | null> {
    endSpeechActivity()
    shouldRestartRecognition = false
    recognition?.stop()
    recognition = null
    const stopped = new Promise<Blob | null>(resolve => {
      if (!mediaRecorder || mediaRecorder.state === 'inactive') {
        resolve(audioBlob.value)
        return
      }
      stopResolver = resolve
      mediaRecorder.stop()
    })
    recordingStatus.value = 'stopped'
    stopTimers()
    void audioContext?.close()
    audioContext = null
    analyser = null
    resetFrequencyData()
    return stopped
  }

  function clearTranscript() {
    interimTranscript.value = ''
    finalTranscript.value = ''
    transcriptSegments.value = []
  }

  function dispose() {
    stopMicrophoneTest()
    void stopRecording()
    stream?.getTracks().forEach(track => track.stop())
    stream = null
    mediaStream.value = null
  }

  onBeforeUnmount(dispose)

  return {
    permission,
    recordingStatus,
    errorMessage,
    interimTranscript,
    finalTranscript,
    transcriptSegments,
    audioBlob,
    volumeLevel,
    frequencyData,
    mediaStream,
    hasDetectedAudio,
    silentForMs,
    recordingDurationSeconds,
    recognitionAvailable,
    microphoneTestStatus,
    microphoneTestLevel,
    microphoneTestSecondsRemaining,
    isRecording,
    silenceRemainingSeconds,
    requestMicrophonePermission,
    testMicrophone,
    startRecording,
    pauseRecording,
    resumeRecording,
    stopRecording,
    clearTranscript,
    dispose
  }
}
