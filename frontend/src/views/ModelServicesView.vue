<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  adminApi,
  type DiagnosticStatus,
  type ModelConfigHistory,
  type ModelServicesConfig,
  type ModelServicesConfigUpdate,
  type ModelServicesDiagnostics,
  type ServiceDiagnostic
} from '../api/admin'
import { confirmAction, notify } from '../composables/useUiFeedback'
import AppPageHeader from '../components/ui/AppPageHeader.vue'
import { parseApiDate } from '../utils/datetime'

const diagnostics = ref<ModelServicesDiagnostics | null>(null)
const config = ref<ModelServicesConfig | null>(null)
const loading = ref(false)
const configLoading = ref(false)
const saving = ref(false)
const errorMessage = ref('')
const successMessage = ref('')
const llmApiKey = ref('')
const qwenApiKey = ref('')
const asrApiKey = ref('')
const asrAccessKey = ref('')
const signingSecret = ref('')
const clearLlmApiKey = ref(false)
const clearQwenApiKey = ref(false)
const clearAsrApiKey = ref(false)
const clearAsrAccessKey = ref(false)
const clearSigningSecret = ref(false)
const savedConfigSnapshot = ref('')
const asrCredentialMode = computed<'api_key' | 'legacy'>(
  () => config.value?.volcengine_asr_auth_mode === 'legacy' ? 'legacy' : 'api_key'
)
const showAdvanced = ref(false)
const configHistory = ref<ModelConfigHistory[]>([])
const rollingBackId = ref('')

const asrLanguageOptions = [
  { value: '', label: '自动/混合（中英文及主要中文方言）' },
  { value: 'zh-CN', label: '中文普通话（zh-CN）' },
  { value: 'en-US', label: '英语（en-US）' },
  { value: 'ja-JP', label: '日语（ja-JP）' },
  { value: 'id-ID', label: '印尼语（id-ID）' },
  { value: 'es-MX', label: '西班牙语（es-MX）' },
  { value: 'pt-BR', label: '葡萄牙语（pt-BR）' },
  { value: 'de-DE', label: '德语（de-DE）' },
  { value: 'fr-FR', label: '法语（fr-FR）' },
  { value: 'ko-KR', label: '韩语（ko-KR）' },
  { value: 'fil-PH', label: '菲律宾语（fil-PH）' },
  { value: 'ms-MY', label: '马来语（ms-MY）' },
  { value: 'th-TH', label: '泰语（th-TH）' },
  { value: 'ar-SA', label: '阿拉伯语（ar-SA）' },
  { value: 'it-IT', label: '意大利语（it-IT）' },
  { value: 'bn-BD', label: '孟加拉语（bn-BD）' },
  { value: 'el-GR', label: '希腊语（el-GR）' },
  { value: 'nl-NL', label: '荷兰语（nl-NL）' },
  { value: 'ru-RU', label: '俄语（ru-RU）' },
  { value: 'tr-TR', label: '土耳其语（tr-TR）' },
  { value: 'vi-VN', label: '越南语（vi-VN）' },
  { value: 'pl-PL', label: '波兰语（pl-PL）' },
  { value: 'ro-RO', label: '罗马尼亚语（ro-RO）' },
  { value: 'ne-NP', label: '尼泊尔语（ne-NP）' },
  { value: 'uk-UA', label: '乌克兰语（uk-UA）' },
  { value: 'yue-CN', label: '粤语（yue-CN）' }
] as const

const services = computed<ServiceDiagnostic[]>(() => {
  if (!diagnostics.value) return []
  return [
    diagnostics.value.llm,
    diagnostics.value.embedding,
    diagnostics.value.asr,
    diagnostics.value.audio_public_url
  ]
})

const overall = computed(() => {
  switch (diagnostics.value?.overall_status) {
    case 'ready':
      return { label: '全部可用', className: 'text-bg-success', icon: 'bi-check-circle-fill' }
    case 'degraded':
      return { label: '部分异常', className: 'text-bg-warning', icon: 'bi-exclamation-triangle-fill' }
    default:
      return { label: '不可用', className: 'text-bg-danger', icon: 'bi-x-circle-fill' }
  }
})

const asrIssues = computed(() => {
  const current = config.value
  if (!current || current.asr_provider === 'disabled') return []

  const issues: string[] = []
  if (asrCredentialMode.value === 'api_key') {
    const hasApiKey = Boolean(asrApiKey.value.trim()) ||
      (current.volcengine_asr_api_key_configured && !clearAsrApiKey.value)
    if (!hasApiKey) issues.push('请填写语音 API Key，或切换到 App ID + Access Key 鉴权。')
  } else {
    const hasAccessKey = Boolean(asrAccessKey.value.trim()) ||
      (current.volcengine_asr_access_key_configured && !clearAsrAccessKey.value)
    if (!current.volcengine_asr_app_id.trim()) issues.push('请填写 App ID。')
    if (!hasAccessKey) issues.push('请填写 Access Key。')
  }
  if (!current.volcengine_asr_resource_id.trim()) issues.push('请填写资源 ID。')
  if (!current.asr_public_base_url.startsWith('https://')) {
    issues.push('音频公网地址必须是可从互联网访问的 HTTPS 地址。')
  }
  if (!current.volcengine_asr_submit_url.startsWith('https://')) {
    issues.push('提交接口必须使用 HTTPS。')
  }
  if (!current.volcengine_asr_query_url.startsWith('https://')) {
    issues.push('查询接口必须使用 HTTPS。')
  }
  if (clearSigningSecret.value) {
    issues.push('启用 ASR 时不能清除音频签名密钥；如需轮换，请直接填写新密钥。')
  }
  return issues
})

const hasUnsavedChanges = computed(() => {
  if (!config.value) return false
  const configChanged = JSON.stringify(config.value) !== savedConfigSnapshot.value
  const secretChanged = Boolean(
    llmApiKey.value.trim()
    || qwenApiKey.value.trim()
    || asrApiKey.value.trim()
    || asrAccessKey.value.trim()
    || signingSecret.value.trim()
    || clearLlmApiKey.value
    || clearQwenApiKey.value
    || clearAsrApiKey.value
    || clearAsrAccessKey.value
    || clearSigningSecret.value
  )
  return configChanged || secretChanged
})
const canSave = computed(() => !saving.value && hasUnsavedChanges.value)

function statusMeta(status: DiagnosticStatus) {
  const values: Record<DiagnosticStatus, { label: string; className: string; icon: string }> = {
    ready: { label: '可用', className: 'text-bg-success', icon: 'bi-check-circle-fill' },
    warning: { label: '需关注', className: 'text-bg-warning', icon: 'bi-exclamation-triangle-fill' },
    error: { label: '异常', className: 'text-bg-danger', icon: 'bi-x-circle-fill' },
    disabled: { label: '已关闭', className: 'text-bg-secondary', icon: 'bi-pause-circle-fill' },
    unconfigured: { label: '未配置', className: 'text-bg-secondary', icon: 'bi-gear-fill' },
    unknown: { label: '未知', className: 'text-bg-secondary', icon: 'bi-question-circle-fill' }
  }
  return values[status]
}

function checkedTime(value: string) {
  const parsed = parseApiDate(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN')
}

function resetSecretInputs() {
  llmApiKey.value = ''
  qwenApiKey.value = ''
  asrApiKey.value = ''
  asrAccessKey.value = ''
  signingSecret.value = ''
  clearLlmApiKey.value = false
  clearQwenApiKey.value = false
  clearAsrApiKey.value = false
  clearAsrAccessKey.value = false
  clearSigningSecret.value = false
}

async function runDiagnostics() {
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await adminApi.diagnoseModelServices()
    diagnostics.value = response.data
  } catch (error: unknown) {
    errorMessage.value = error instanceof Error ? error.message : '诊断失败，请稍后重试。'
  } finally {
    loading.value = false
  }
}

async function loadConfig() {
  configLoading.value = true
  errorMessage.value = ''
  try {
    const response = await adminApi.getModelServicesConfig()
    const loaded = response.data
    if (!['disabled', 'volcengine'].includes(loaded.asr_provider)) {
      loaded.asr_provider = 'volcengine'
    }
    if (!['api_key', 'legacy'].includes(loaded.volcengine_asr_auth_mode)) {
      loaded.volcengine_asr_auth_mode = loaded.volcengine_asr_api_key_configured
        ? 'api_key'
        : loaded.volcengine_asr_access_key_configured
          ? 'legacy'
          : 'api_key'
    }
    const legacyLanguageAliases: Record<string, string> = {
      auto: '',
      zh: 'zh-CN',
      en: 'en-US',
      ja: 'ja-JP',
      ko: 'ko-KR'
    }
    loaded.asr_language = legacyLanguageAliases[loaded.asr_language] ?? loaded.asr_language
    config.value = loaded
    savedConfigSnapshot.value = JSON.stringify(loaded)
  } catch (error: unknown) {
    errorMessage.value = error instanceof Error ? error.message : '配置读取失败。'
  } finally {
    configLoading.value = false
  }
}

async function loadConfigHistory() {
  try {
    configHistory.value = (await adminApi.listModelServicesConfigHistory()).data
  } catch (error: unknown) {
    notify(error instanceof Error ? error.message : '配置历史读取失败', 'danger')
  }
}

async function rollbackConfig(item: ModelConfigHistory) {
  const confirmed = await confirmAction({
    title: '回滚模型配置',
    message: `将当前配置恢复为 ${checkedTime(item.created_at)} 的版本。密钥也会安全恢复，是否继续？`,
    confirmText: '确认回滚',
    tone: 'warning'
  })
  if (!confirmed) return
  rollingBackId.value = item.id
  try {
    config.value = (await adminApi.rollbackModelServicesConfig(item.id)).data
    resetSecretInputs()
    savedConfigSnapshot.value = JSON.stringify(config.value)
    await Promise.all([loadConfigHistory(), runDiagnostics()])
    notify('模型服务配置已回滚并重新诊断', 'success')
  } catch (error: unknown) {
    notify(error instanceof Error ? error.message : '配置回滚失败', 'danger')
  } finally {
    rollingBackId.value = ''
  }
}

async function saveConfig(event?: SubmitEvent) {
  const current = config.value
  if (!current || !canSave.value) return

  const submittedMode = event?.currentTarget instanceof HTMLFormElement
    ? new FormData(event.currentTarget).get('asr_credential_mode')
    : null
  if (submittedMode === 'api_key' || submittedMode === 'legacy') {
    current.volcengine_asr_auth_mode = submittedMode
  }

  saving.value = true
  errorMessage.value = ''
  successMessage.value = ''
  const payload: ModelServicesConfigUpdate = {
    report_use_llm: current.report_use_llm,
    llm_base_url: current.llm_base_url,
    llm_model: current.llm_model,
    llm_api_key: llmApiKey.value.trim() || null,
    clear_llm_api_key: clearLlmApiKey.value,
    llm_temperature: current.llm_temperature,
    llm_top_p: current.llm_top_p,
    llm_max_tokens: current.llm_max_tokens,
    report_llm_timeout_seconds: current.report_llm_timeout_seconds,
    qwen_embedding_base_url: current.qwen_embedding_base_url,
    qwen_embedding_model: current.qwen_embedding_model,
    qwen_embedding_api_key: qwenApiKey.value.trim() || null,
    clear_qwen_embedding_api_key: clearQwenApiKey.value,
    qwen_embedding_dimensions: current.qwen_embedding_dimensions,
    qwen_embedding_batch_size: current.qwen_embedding_batch_size,
    qwen_embedding_timeout_seconds: current.qwen_embedding_timeout_seconds,
    asr_provider: current.asr_provider,
    volcengine_asr_auth_mode: asrCredentialMode.value,
    volcengine_asr_api_key: asrCredentialMode.value === 'api_key'
      ? asrApiKey.value.trim() || null
      : null,
    clear_volcengine_asr_api_key: clearAsrApiKey.value,
    volcengine_asr_app_id: current.volcengine_asr_app_id,
    volcengine_asr_access_key: asrCredentialMode.value === 'legacy'
      ? asrAccessKey.value.trim() || null
      : null,
    clear_volcengine_asr_access_key: clearAsrAccessKey.value,
    volcengine_asr_resource_id: current.volcengine_asr_resource_id,
    volcengine_asr_submit_url: current.volcengine_asr_submit_url,
    volcengine_asr_query_url: current.volcengine_asr_query_url,
    asr_model: current.asr_model,
    asr_language: current.asr_language,
    asr_max_retries: current.asr_max_retries,
    asr_config_version: current.asr_config_version,
    asr_poll_interval_seconds: current.asr_poll_interval_seconds,
    asr_public_base_url: current.asr_public_base_url,
    asr_audio_signing_secret: signingSecret.value.trim() || null,
    clear_asr_audio_signing_secret: clearSigningSecret.value,
    asr_timeout_seconds: current.asr_timeout_seconds,
    volcengine_asr_query_interval_seconds: current.volcengine_asr_query_interval_seconds,
    volcengine_asr_max_wait_seconds: current.volcengine_asr_max_wait_seconds,
    asr_audio_url_ttl_seconds: current.asr_audio_url_ttl_seconds
  }

  try {
    const response = await adminApi.updateModelServicesConfig(payload)
    config.value = response.data
    resetSecretInputs()
    savedConfigSnapshot.value = JSON.stringify(response.data)
    successMessage.value = '配置已加密保存。API 服务立即生效，ASR 工作进程会在处理下一项任务时读取新配置。'
    await loadConfigHistory()
    await runDiagnostics()
  } catch (error: unknown) {
    errorMessage.value = error instanceof Error ? error.message : '配置保存失败。'
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadConfig(), loadConfigHistory()])
  await runDiagnostics()
})
</script>

<template>
  <div class="model-services-page">
    <AppPageHeader eyebrow="模型服务" title="模型服务配置与诊断" icon="bi-cpu" description="配置火山方舟大模型、豆包录音文件识别和音频公网访问。">
      <template #actions>
      <button class="btn btn-primary" :disabled="loading" @click="runDiagnostics">
        <span v-if="loading" class="spinner-border spinner-border-sm me-2" />
        <i v-else class="bi bi-arrow-clockwise me-2" />
        {{ loading ? '诊断中…' : '重新诊断' }}
      </button>
      </template>
    </AppPageHeader>

    <div class="alert alert-info small d-flex gap-2 align-items-start">
      <i class="bi bi-info-circle-fill mt-1" />
      <span>
        诊断会分别发送一段极短文本，验证大语言模型和文本向量服务能否真实响应；同时提交一段短音频验证语音识别链路。测试内容不含用户数据，密钥不会在页面或结果中回显。
      </span>
    </div>

    <section class="config-section">
      <div class="section-title">
        <div>
          <div class="eyebrow">运行配置</div>
          <h5 class="mb-0">运行时配置</h5>
        </div>
        <span class="badge text-bg-light border">
          <i class="bi bi-lock-fill me-1" />密钥加密保存
        </span>
      </div>

      <div v-if="configLoading" class="config-loading">
        <span class="spinner-border spinner-border-sm text-primary" />正在读取配置
      </div>

      <form v-else-if="config" class="config-form" @submit.prevent="saveConfig">
        <article class="config-panel">
          <div class="config-panel-title">
            <span class="service-icon"><i class="bi bi-cpu" /></span>
            <div>
              <strong>火山方舟 LLM</strong>
              <small>用于初步对转录文本内容进行筛选清洗</small>
            </div>
            <div class="form-check form-switch ms-auto">
              <input
                id="llm-enabled"
                v-model="config.report_use_llm"
                class="form-check-input"
                type="checkbox"
              />
            </div>
          </div>

          <label class="form-label" for="llm-base-url">Base URL</label>
          <input
            id="llm-base-url"
            v-model.trim="config.llm_base_url"
            class="form-control"
            required
            placeholder="https://ark.cn-beijing.volces.com/api/v3"
          />

          <label class="form-label" for="llm-model-id">模型接入点 ID</label>
          <input
            id="llm-model-id"
            v-model.trim="config.llm_model"
            class="form-control"
            required
            placeholder="ep-xxxxxxxx"
          />

          <label class="form-label" for="llm-api-key">
            API Key
            <span v-if="config.llm_api_key_configured" class="secret-ready">
              <i class="bi bi-check-circle-fill" />已配置
            </span>
          </label>
          <input
            id="llm-api-key"
            v-model="llmApiKey"
            class="form-control"
            type="password"
            autocomplete="new-password"
            :disabled="clearLlmApiKey"
            :placeholder="config.llm_api_key_configured ? '留空则保留现有密钥' : '请输入方舟 API Key'"
          />
          <div v-if="config.llm_api_key_configured" class="form-check secret-action">
            <input id="clear-llm-key" v-model="clearLlmApiKey" class="form-check-input" type="checkbox" />
            <label class="form-check-label" for="clear-llm-key">清除已保存的 LLM API Key</label>
          </div>
        </article>

        <article class="config-panel embedding-panel">
          <div class="config-panel-title">
            <span class="service-icon"><i class="bi bi-vector-pen" /></span>
            <div>
              <strong>文本向量（Embedding）服务</strong>
              <small>把清洗后的文本转换为数值向量，供元认知分类模型训练与推理使用</small>
            </div>
          </div>

          <label class="form-label" for="qwen-base-url">文本向量 API 基础地址</label>
          <input id="qwen-base-url" v-model.trim="config.qwen_embedding_base_url" class="form-control" placeholder="https://WorkspaceId.cn-beijing.maas.aliyuncs.com/compatible-mode/v1" />

          <label class="form-label" for="qwen-model">Model ID 或推理接入点 ID</label>
          <input id="qwen-model" v-model.trim="config.qwen_embedding_model" class="form-control" placeholder="例如 doubao-embedding-text-240715 或 ep-xxxxxxxx" />
          <div class="form-text">火山方舟同时支持已开通模型的 Model ID 和自建 Endpoint ID。请以控制台“快捷 API 接入”自动生成的 model 值为准，并使用同一账号与地域下的方舟 API Key。</div>

          <label class="form-label" for="qwen-api-key">
            API Key
            <span v-if="config.qwen_embedding_api_key_configured" class="secret-ready"><i class="bi bi-check-circle-fill" />已配置</span>
          </label>
          <input id="qwen-api-key" v-model="qwenApiKey" class="form-control" type="password" autocomplete="new-password" :disabled="clearQwenApiKey" :placeholder="config.qwen_embedding_api_key_configured ? '留空则保留现有密钥' : '请输入文本向量服务 API Key'" />
          <div v-if="config.qwen_embedding_api_key_configured" class="form-check secret-action">
            <input id="clear-qwen-key" v-model="clearQwenApiKey" class="form-check-input" type="checkbox" />
            <label class="form-check-label" for="clear-qwen-key">清除已保存的嵌入 API Key</label>
          </div>
          <div class="two-column mt-3">
            <label><span class="form-label">向量维度</span><input v-model.number="config.qwen_embedding_dimensions" type="number" min="1" max="65536" class="form-control" /></label>
            <label><span class="form-label">批量大小</span><input v-model.number="config.qwen_embedding_batch_size" type="number" min="1" max="256" class="form-control" /></label>
          </div>
          <div class="form-text">只向接口发送待训练的清洗文本，不发送账号、姓名、班级或问卷姓名。</div>
        </article>

        <article class="config-panel asr-panel">
          <div class="config-panel-title">
            <span class="service-icon"><i class="bi bi-mic-fill" /></span>
            <div>
              <strong>豆包语音 ASR</strong>
              <small>服务端权威转录，推荐使用录音文件识别极速版</small>
            </div>
          </div>

          <label class="form-label" for="asr-provider">服务状态</label>
          <select id="asr-provider" v-model="config.asr_provider" class="form-select">
            <option value="volcengine">启用火山引擎 ASR</option>
            <option value="disabled">暂时停用</option>
          </select>

          <template v-if="config.asr_provider === 'volcengine'">
            <label class="form-label">鉴权方式</label>
            <div class="credential-selector">
              <input
                id="asr-mode-api-key"
                v-model="config.volcengine_asr_auth_mode"
                class="credential-radio"
                type="radio"
                name="asr_credential_mode"
                value="api_key"
              />
              <input
                id="asr-mode-legacy"
                v-model="config.volcengine_asr_auth_mode"
                class="credential-radio"
                type="radio"
                name="asr_credential_mode"
                value="legacy"
              />
              <div class="credential-switch" role="radiogroup" aria-label="ASR 鉴权方式">
                <label for="asr-mode-api-key">
                  <i class="bi bi-key-fill" />
                  <span>API Key <small>新版控制台·推荐</small></span>
                </label>
                <label for="asr-mode-legacy">
                  <i class="bi bi-person-badge" />
                  <span>App ID + Access Key <small>旧版控制台</small></span>
                </label>
              </div>
              <div class="form-text">
                切换只改变实际使用的鉴权方式，不会清除另一套已保存凭证，也不会丢失尚未保存的输入。
              </div>

              <div class="credential-fields api-key-fields">
                <label class="form-label" for="asr-api-key">
                  语音 API Key
                  <span v-if="config.volcengine_asr_api_key_configured" class="secret-ready">
                    <i class="bi bi-check-circle-fill" />已配置
                  </span>
                </label>
                <input
                  id="asr-api-key"
                  v-model="asrApiKey"
                  class="form-control"
                  type="password"
                  autocomplete="new-password"
                  :disabled="clearAsrApiKey"
                  :placeholder="config.volcengine_asr_api_key_configured ? '留空则保留现有密钥' : '请输入豆包语音 API Key'"
                />
                <div v-if="config.volcengine_asr_api_key_configured" class="form-check secret-action">
                  <input id="clear-asr-key" v-model="clearAsrApiKey" class="form-check-input" type="checkbox" />
                  <label class="form-check-label" for="clear-asr-key">清除已保存的语音 API Key</label>
                </div>
              </div>

              <div class="credential-fields legacy-fields">
                <label class="form-label" for="asr-app-id">App ID</label>
                <input
                  id="asr-app-id"
                  v-model.trim="config.volcengine_asr_app_id"
                  class="form-control"
                  placeholder="请输入火山引擎语音 App ID"
                />
                <label class="form-label" for="asr-access-key">
                  Access Key
                  <span v-if="config.volcengine_asr_access_key_configured" class="secret-ready">
                    <i class="bi bi-check-circle-fill" />已配置
                  </span>
                </label>
                <input
                  id="asr-access-key"
                  v-model="asrAccessKey"
                  class="form-control"
                  type="password"
                  autocomplete="new-password"
                  :disabled="clearAsrAccessKey"
                  :placeholder="config.volcengine_asr_access_key_configured ? '留空则保留现有密钥' : '请输入 Access Key'"
                />
                <div v-if="config.volcengine_asr_access_key_configured" class="form-check secret-action">
                  <input id="clear-access-key" v-model="clearAsrAccessKey" class="form-check-input" type="checkbox" />
                  <label class="form-check-label" for="clear-access-key">清除已保存的 Access Key</label>
                </div>
              </div>
            </div>

            <div class="two-column">
              <label>
                <span class="form-label">资源 ID</span>
                <input
                  v-model.trim="config.volcengine_asr_resource_id"
                  class="form-control"
                  list="volcengine-asr-resource-options"
                  required
                  placeholder="volc.seedasr.auc"
                />
                <datalist id="volcengine-asr-resource-options">
                  <option value="volc.seedasr.auc">录音文件识别模型 2.0</option>
                  <option value="volc.bigasr.auc">录音文件识别模型 1.0</option>
                </datalist>
                <small class="form-text">
                  录音文件识别 2.0 使用 volc.seedasr.auc；出现 45000030
                  表示当前 API Key 未获该资源授权，并非资源 ID 拼写错误。
                </small>
              </label>
              <label>
                <span class="form-label">音频语言</span>
                <select v-model="config.asr_language" class="form-select">
                  <option
                    v-for="language in asrLanguageOptions"
                    :key="language.value || 'auto'"
                    :value="language.value"
                  >
                    {{ language.label }}
                  </option>
                </select>
              </label>
            </div>
            <div class="form-text">
              按官方接口写入 <code>audio.language</code>；选择“自动/混合”时不发送该字段。
            </div>

            <label class="form-label" for="asr-public-url">音频公网地址</label>
            <input
              id="asr-public-url"
              v-model.trim="config.asr_public_base_url"
              class="form-control"
              required
              placeholder="https://www.21050411.xyz"
            />
            <div class="form-text">
              火山引擎需要从该 HTTPS 域名拉取待识别音频。只填写域名，不要填写 /api 路径。
            </div>
          </template>

          <div v-else class="disabled-note">
            <i class="bi bi-pause-circle" />停用后，新提交的转录任务会等待配置，不会丢失录音。
          </div>
        </article>

        <div v-if="asrIssues.length" class="alert alert-warning validation-alert">
          <strong><i class="bi bi-exclamation-triangle-fill me-1" />ASR 配置尚未完整</strong>
          <ul class="mb-0 mt-1">
            <li v-for="issue in asrIssues" :key="issue">{{ issue }}</li>
          </ul>
        </div>

        <div class="advanced-row">
          <button
            type="button"
            class="btn btn-sm btn-link text-decoration-none px-2"
            @click="showAdvanced = !showAdvanced"
          >
            <i class="bi me-1" :class="showAdvanced ? 'bi-chevron-up' : 'bi-chevron-down'" />
            {{ showAdvanced ? '收起高级配置' : '展开高级配置' }}
          </button>
        </div>

        <div v-if="showAdvanced" class="advanced-grid">
          <article class="config-panel compact-panel">
            <strong>LLM 生成参数</strong>
            <div class="number-grid">
              <label>Temperature<input v-model.number="config.llm_temperature" type="number" min="0" max="2" step="0.1" class="form-control" /></label>
              <label>Top P<input v-model.number="config.llm_top_p" type="number" min="0.01" max="1" step="0.05" class="form-control" /></label>
              <label>最大 Token<input v-model.number="config.llm_max_tokens" type="number" min="1" max="32768" class="form-control" /></label>
              <label>超时（秒）<input v-model.number="config.report_llm_timeout_seconds" type="number" min="3" max="180" class="form-control" /></label>
              <label>嵌入超时（秒）<input v-model.number="config.qwen_embedding_timeout_seconds" type="number" min="1" max="600" class="form-control" /></label>
            </div>
          </article>

          <article class="config-panel compact-panel">
            <strong>ASR 任务策略</strong>
            <div class="number-grid">
              <label>模型记录标识<input v-model.trim="config.asr_model" class="form-control" placeholder="bigmodel" /></label>
              <label>配置版本<input v-model.trim="config.asr_config_version" class="form-control" placeholder="2026.1" /></label>
              <label>失败重试次数<input v-model.number="config.asr_max_retries" type="number" min="0" max="10" class="form-control" /></label>
              <label>单次请求超时（秒）<input v-model.number="config.asr_timeout_seconds" type="number" min="10" max="600" class="form-control" /></label>
              <label>工作进程轮询（秒）<input v-model.number="config.asr_poll_interval_seconds" type="number" min="0.5" max="30" step="0.5" class="form-control" /></label>
              <label>结果查询间隔（秒）<input v-model.number="config.volcengine_asr_query_interval_seconds" type="number" min="0.5" max="30" step="0.5" class="form-control" /></label>
              <label>任务最长等待（秒）<input v-model.number="config.volcengine_asr_max_wait_seconds" type="number" min="30" max="1800" class="form-control" /></label>
              <label>音频链接有效期（秒）<input v-model.number="config.asr_audio_url_ttl_seconds" type="number" min="60" max="3600" class="form-control" /></label>
            </div>
            <p class="field-hint mb-0">
              修改“配置版本”会让相同录音按新配置重新建立识别任务；无特殊需要请保持不变。
            </p>
          </article>

          <article class="config-panel compact-panel asr-interface-panel">
            <strong>ASR 接口与音频签名</strong>
            <label class="form-label">提交接口</label>
            <input v-model.trim="config.volcengine_asr_submit_url" class="form-control" required />
            <label class="form-label">查询接口</label>
            <input v-model.trim="config.volcengine_asr_query_url" class="form-control" required />
            <label class="form-label">
              音频签名密钥
              <span v-if="config.asr_audio_signing_secret_configured" class="secret-ready">
                <i class="bi bi-check-circle-fill" />已配置
              </span>
            </label>
            <input
              v-model="signingSecret"
              type="password"
              autocomplete="new-password"
              class="form-control"
              :disabled="clearSigningSecret"
              :placeholder="config.asr_audio_signing_secret_configured ? '留空则保留现有密钥' : '留空将在保存时自动生成'"
            />
            <div v-if="config.asr_audio_signing_secret_configured" class="form-check secret-action">
              <input id="clear-signing-key" v-model="clearSigningSecret" class="form-check-input" type="checkbox" />
              <label class="form-check-label" for="clear-signing-key">清除签名密钥（启用 ASR 时不建议）</label>
            </div>
          </article>
        </div>

        <div class="config-actions">
          <span class="config-note">
            <strong>{{ hasUnsavedChanges ? '有尚未保存的修改。' : '当前配置已保存。' }}</strong>
            密钥输入框留空会保留原值。服务器迁移时，运行时配置随数据库迁移。
          </span>
          <button class="btn btn-primary" type="submit" :disabled="!canSave">
            <span v-if="saving" class="spinner-border spinner-border-sm me-2" />
            <i v-else class="bi bi-floppy me-2" />
            {{ saving ? '保存中…' : hasUnsavedChanges ? '保存并诊断' : '已保存' }}
          </button>
        </div>
      </form>
    </section>

    <section class="config-history-section">
      <div class="section-title">
        <div>
          <h5 class="mb-1">配置历史</h5>
          <p class="text-muted small mb-0">仅显示脱敏摘要；回滚会恢复该版本的加密密钥与参数。</p>
        </div>
        <span class="badge text-bg-light">最近 {{ configHistory.length }} 次</span>
      </div>
      <div v-if="configHistory.length" class="history-list">
        <article v-for="item in configHistory" :key="item.id" class="history-item">
          <div>
            <strong>{{ item.summary.action === 'rollback' ? '配置回滚' : '保存配置' }}</strong>
            <span>{{ checkedTime(item.created_at) }} · {{ item.created_by_name || '系统管理员' }}</span>
            <small v-if="item.summary.action !== 'rollback'">
              LLM：{{ item.summary.llm_model || '未填写' }} · ASR：{{ item.summary.asr_provider || 'disabled' }}
            </small>
          </div>
          <button
            class="btn btn-sm btn-outline-warning"
            type="button"
            :disabled="rollingBackId === item.id"
            @click="rollbackConfig(item)"
          >
            <span v-if="rollingBackId === item.id" class="spinner-border spinner-border-sm me-1" />
            <i v-else class="bi bi-clock-history me-1" />恢复此版本
          </button>
        </article>
      </div>
      <p v-else class="text-muted small mb-0 py-3">首次保存配置后，这里会生成可回滚版本。</p>
    </section>

    <div v-if="successMessage" class="alert alert-success">{{ successMessage }}</div>
    <div v-if="errorMessage" class="alert alert-danger">{{ errorMessage }}</div>

    <div v-if="diagnostics" class="summary-card">
      <div>
        <span class="text-muted small">综合状态</span>
        <div class="d-flex align-items-center gap-2 mt-1">
          <span class="badge fs-6" :class="overall.className">
            <i class="bi me-1" :class="overall.icon" />{{ overall.label }}
          </span>
          <span class="text-muted small">检查时间：{{ checkedTime(diagnostics.checked_at) }}</span>
        </div>
      </div>
      <div class="summary-hint">
        <i class="bi bi-shield-check" />
        <span>诊断结果只包含脱敏后的服务信息</span>
      </div>
    </div>

    <div v-if="diagnostics" class="service-grid">
      <article v-for="service in services" :key="service.label" class="service-card">
        <div class="service-card-head">
          <div class="service-icon">
            <i
              class="bi"
              :class="service.provider.includes('embedding') || service.provider === 'aliyun_model_studio'
                ? 'bi-vector-pen'
                : service.provider === 'volcengine_ark'
                ? 'bi-cpu'
                : service.provider === 'volcengine_speech'
                  ? 'bi-mic-fill'
                  : 'bi-globe2'"
            />
          </div>
          <span class="badge" :class="statusMeta(service.status).className">
            <i class="bi me-1" :class="statusMeta(service.status).icon" />
            {{ statusMeta(service.status).label }}
          </span>
        </div>
        <h5>{{ service.label }}</h5>
        <p class="service-message">{{ service.message }}</p>
        <dl>
          <div v-if="service.model">
            <dt>模型/资源</dt>
            <dd>{{ service.model }}</dd>
          </div>
          <div v-if="service.endpoint">
            <dt>服务地址</dt>
            <dd class="endpoint">{{ service.endpoint }}</dd>
          </div>
          <div>
            <dt>响应时间</dt>
            <dd>{{ service.latency_ms === null ? '—' : `${service.latency_ms} ms` }}</dd>
          </div>
        </dl>
      </article>
    </div>

    <section v-if="diagnostics" class="quota-section">
      <div class="section-title">
        <div>
          <div class="eyebrow">用量与额度</div>
          <h5 class="mb-0">用量与剩余额度</h5>
        </div>
        <span class="badge text-bg-light border">精确余额以火山控制台为准</span>
      </div>

      <div class="quota-grid">
        <article class="quota-card">
          <div class="quota-title"><i class="bi bi-stars" /><span>火山方舟 LLM</span></div>
          <strong>控制台查询</strong>
          <p>{{ diagnostics.llm_quota.message }}</p>
          <a class="btn btn-sm btn-outline-primary" :href="diagnostics.llm_quota.console_url" target="_blank" rel="noopener noreferrer">
            打开方舟用量统计 <i class="bi bi-box-arrow-up-right ms-1" />
          </a>
        </article>

        <article class="quota-card">
          <div class="quota-title"><i class="bi bi-soundwave" /><span>豆包语音 ASR</span></div>
          <strong>{{ diagnostics.asr_quota.local_usage ?? 0 }} <small>小时</small></strong>
          <div class="text-muted small mb-2">
            本系统 {{ diagnostics.asr_quota.period }} 已完成识别
          </div>
          <p>{{ diagnostics.asr_quota.message }}</p>
          <a class="btn btn-sm btn-outline-primary" :href="diagnostics.asr_quota.console_url" target="_blank" rel="noopener noreferrer">
            打开豆包语音控制台 <i class="bi bi-box-arrow-up-right ms-1" />
          </a>
        </article>
      </div>
    </section>

    <div v-if="loading && !diagnostics" class="initial-loading">
      <div class="spinner-border text-primary" />
      <strong>正在检查模型服务</strong>
      <span>豆包语音探针可能需要十几秒。</span>
    </div>
  </div>
</template>

<style scoped>
.model-services-page {
  max-width: 1180px;
  margin: 0 auto;
}

.page-toolbar,
.summary-card,
.section-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
}

.page-toolbar {
  margin-bottom: 1rem;
}

.eyebrow {
  color: var(--color-primary);
  font-size: .72rem;
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
}

.summary-card,
.service-card,
.config-section,
.config-panel,
.quota-section,
.quota-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-sm);
}

.config-section {
  padding: 1.15rem;
  margin-bottom: 1rem;
}

.config-loading {
  min-height: 120px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: .6rem;
  color: var(--color-text-muted);
}

.config-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem;
  margin-top: 1rem;
}

.embedding-panel { grid-column: 1; }
.asr-panel { grid-column: 2; grid-row: 1 / span 2; }

.config-panel {
  padding: 1rem;
  box-shadow: none;
  min-width: 0;
}

.config-panel-title {
  display: flex;
  align-items: center;
  gap: .7rem;
  margin-bottom: .8rem;
}

.config-panel-title strong,
.config-panel-title small {
  display: block;
}

.config-panel-title small {
  color: var(--color-text-muted);
  font-size: .75rem;
}

.config-panel .form-label,
.two-column .form-label {
  color: var(--color-text-secondary);
  display: block;
  font-size: .76rem;
  font-weight: 600;
  margin: .65rem 0 .25rem;
}

.secret-ready {
  color: var(--color-success);
  font-size: .72rem;
  margin-left: .35rem;
}

.secret-action {
  color: var(--color-warning);
  font-size: .74rem;
  margin-top: .4rem;
}

.credential-switch {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: .5rem;
}

.credential-switch label {
  align-items: center;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 10px;
  color: var(--color-text-secondary);
  cursor: pointer;
  display: flex;
  gap: .45rem;
  justify-content: center;
  padding: .65rem .75rem;
  transition: background-color .15s ease, border-color .15s ease, color .15s ease, box-shadow .15s ease;
}

.credential-switch label:hover {
  border-color: var(--color-primary-hover);
}

.credential-switch label:focus-within {
  box-shadow: 0 0 0 .2rem var(--focus-ring);
  outline: 0;
}

.credential-selector > .credential-radio {
  height: 1px;
  opacity: 0;
  position: absolute;
  width: 1px;
}

#asr-mode-api-key:checked ~ .credential-switch label[for="asr-mode-api-key"],
#asr-mode-legacy:checked ~ .credential-switch label[for="asr-mode-legacy"] {
  background: var(--color-primary-soft);
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.credential-fields {
  display: none;
}

#asr-mode-api-key:checked ~ .api-key-fields,
#asr-mode-legacy:checked ~ .legacy-fields {
  display: block;
}

.credential-switch small {
  color: var(--color-success);
  display: block;
  font-size: .68rem;
}

.two-column {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: .7rem;
}

.disabled-note {
  background: var(--color-surface-subtle);
  border-radius: 10px;
  color: var(--color-text-muted);
  font-size: .8rem;
  margin-top: .8rem;
  padding: .8rem;
}

.validation-alert,
.advanced-row,
.config-actions {
  grid-column: 1 / -1;
}

.validation-alert {
  font-size: .8rem;
  margin: 0;
}

.advanced-grid {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem;
}

.asr-interface-panel {
  grid-column: 1 / -1;
}

.compact-panel > strong {
  color: var(--color-text);
}

.number-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: .7rem;
  margin-top: .7rem;
}

.number-grid label {
  color: var(--color-text-secondary);
  font-size: .74rem;
  font-weight: 600;
}

.number-grid input {
  margin-top: .25rem;
}

.field-hint,
.config-note {
  color: var(--color-text-muted);
  font-size: .75rem;
}

.field-hint {
  margin-top: .75rem;
}

.config-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.config-note {
  max-width: 760px;
}

.summary-card {
  padding: 1rem 1.15rem;
  margin-bottom: 1rem;
}

.summary-hint {
  color: var(--color-text-muted);
  display: flex;
  gap: .5rem;
  align-items: center;
  font-size: .82rem;
}

.service-grid,
.quota-grid {
  display: grid;
  gap: 1rem;
}

.service-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.service-card {
  padding: 1.15rem;
  min-width: 0;
}

.service-card-head,
.quota-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: .75rem;
}

.service-icon {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  font-size: 1.2rem;
}

.service-card h5 {
  margin: .9rem 0 .45rem;
}

.service-message {
  color: var(--color-text-muted);
  min-height: 3rem;
  font-size: .88rem;
}

dl {
  margin: .8rem 0 0;
}

dl > div {
  border-top: 1px solid var(--color-border);
  padding: .55rem 0;
}

dt {
  color: var(--color-text-muted);
  font-size: .72rem;
  font-weight: 600;
}

dd {
  margin: .1rem 0 0;
  color: var(--color-text);
  font-size: .82rem;
  overflow-wrap: anywhere;
}

.endpoint {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: .75rem;
}

.quota-section {
  margin-top: 1rem;
  padding: 1.15rem;
}

.config-history-section {
  margin-bottom: 1rem;
  padding: 1.15rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
}

.history-list { display: grid; gap: .65rem; margin-top: 1rem; }
.history-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: .8rem .9rem;
  border: 1px solid var(--color-border);
  border-radius: 10px;
  background: var(--color-surface-subtle);
}
.history-item span,
.history-item small { display: block; color: var(--color-text-muted); font-size: .78rem; margin-top: .12rem; }

.quota-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-top: 1rem;
}

.quota-card {
  padding: 1rem;
  box-shadow: none;
}

.quota-title {
  justify-content: flex-start;
  color: var(--color-primary);
  font-weight: 700;
}

.quota-card strong {
  display: block;
  font-size: 1.6rem;
  margin: .6rem 0 .2rem;
}

.quota-card strong small {
  font-size: .8rem;
  color: var(--color-text-muted);
}

.quota-card p {
  color: var(--color-text-muted);
  font-size: .82rem;
  min-height: 2.6rem;
}

.initial-loading {
  min-height: 280px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: .7rem;
  color: var(--color-text-muted);
}

@media (max-width: 991.98px) {
  .service-grid,
  .config-form,
  .advanced-grid {
    grid-template-columns: 1fr;
  }

  .asr-interface-panel {
    grid-column: auto;
  }

  .embedding-panel,
  .asr-panel {
    grid-column: auto;
    grid-row: auto;
  }

  .service-message {
    min-height: auto;
  }
}

@media (max-width: 767.98px) {
  .page-toolbar,
  .summary-card,
  .section-title {
    align-items: flex-start;
    flex-direction: column;
  }

  .page-toolbar .btn {
    width: 100%;
    min-height: 44px;
  }

  .summary-hint {
    display: none;
  }

  .quota-grid,
  .credential-switch,
  .two-column,
  .number-grid {
    grid-template-columns: 1fr;
  }

  .config-actions {
    position: sticky;
    bottom: max(.6rem, env(safe-area-inset-bottom));
    z-index: 15;
    align-items: stretch;
    flex-direction: column;
    margin: 0 -.35rem;
    padding: .8rem;
    border: 1px solid var(--color-border);
    border-radius: 12px;
    background: var(--color-surface);
    box-shadow: 0 -6px 24px rgba(36, 38, 72, .12);
    backdrop-filter: blur(8px);
  }

  .config-actions .btn {
    min-height: 44px;
    width: 100%;
  }

  .history-item { align-items: stretch; flex-direction: column; }
  .history-item .btn { width: 100%; min-height: 42px; }
}
</style>
