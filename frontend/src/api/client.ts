/**
 * Axios 实例 —— 统一封装 baseURL、JWT 注入、5次退避重试、幂等键注入与错误拦截
 */
import axios from 'axios'
import type { AxiosError, InternalAxiosRequestConfig } from 'axios'
import router from '../router'

interface ApiValidationError {
  loc?: Array<string | number>
  msg?: string
  message?: string
  code?: string
}

type ApiErrorDetail = string | ApiValidationError | ApiValidationError[]

interface RetryableRequestConfig extends InternalAxiosRequestConfig {
  __retryCount?: number
}

// 用户明确要求的最多 5 次智能重试
const MAX_RETRIES = 5

function wait(ms: number) {
  return new Promise(resolve => window.setTimeout(resolve, ms))
}

function generateUUID(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID()
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = (Math.random() * 16) | 0
    const v = c === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

function canRetry(error: AxiosError) {
  const config = error.config as RetryableRequestConfig | undefined
  if (!config || config.responseType === 'blob') return false
  if (!navigator.onLine) return false

  const method = config.method?.toLowerCase() ?? ''
  const status = error.response?.status
  const isIdempotentMethod = ['get', 'head', 'options'].includes(method)
  const hasIdempotencyKey = Boolean(config.headers?.['X-Idempotency-Key'] || config.headers?.['x-idempotency-key'])

  const isTransientError =
    status === undefined ||
    error.code === 'ECONNABORTED' ||
    error.message?.includes('timeout') ||
    error.message?.includes('Network Error') ||
    [502, 503, 504].includes(status)

  return (
    (isIdempotentMethod || hasIdempotencyKey) &&
    isTransientError &&
    (config.__retryCount ?? 0) < MAX_RETRIES
  )
}

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api',
  timeout: 35_000
})

// ---- 请求拦截：自动注入 JWT、幂等键 X-Idempotency-Key 与时序追踪 ----
apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem('access_token')
  const isOffline = localStorage.getItem('offline_mode') === 'true'

  // 离线模式下只允许登录请求通过（以便恢复在线状态）
  if (isOffline && !config.url?.includes('/auth/login')) {
    return Promise.reject(new Error('当前处于离线模式，此功能需要连接服务器'))
  }

  if (config.headers) {
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    // 对写操作（POST / PUT / PATCH / DELETE）自动注入全局唯一幂等键与客户端时间戳
    const method = config.method?.toLowerCase() ?? ''
    if (['post', 'put', 'patch', 'delete'].includes(method) && !config.headers['X-Idempotency-Key']) {
      config.headers['X-Idempotency-Key'] = generateUUID()
    }
    config.headers['X-Request-Client-Time'] = String(Date.now())
  }
  return config
})

// ---- 响应拦截：5次指数退避智能重试 + 统一错误处理 + 英→中翻译 ----
apiClient.interceptors.response.use(
  response => response,
  async (error: AxiosError<{ detail?: ApiErrorDetail }>) => {
    if (axios.isCancel(error)) return Promise.reject(error)

    if (canRetry(error)) {
      const config = error.config as RetryableRequestConfig
      config.__retryCount = (config.__retryCount ?? 0) + 1
      // 指数退避算法: 250ms * 2^(n-1) + 抖动 jitter
      const jitter = Math.floor(Math.random() * 120)
      const delay = Math.min(6000, 250 * Math.pow(2, config.__retryCount - 1) + jitter)
      await wait(delay)
      return apiClient.request(config)
    }

    // 401 且已有 token → token 过期，跳转登录页
    // 401 且无 token → 正在登录页输入错误密码，不跳转
    if (error.response?.status === 401 && localStorage.getItem('access_token')) {
      localStorage.removeItem('access_token')
      localStorage.removeItem('offline_mode')
      localStorage.removeItem('needs_password_change')
      router.push('/login')
      return Promise.reject(new Error('登录已过期，请重新登录'))
    }

    if (error.response?.status === 429) {
      const retryAfter = Number(error.response.headers?.['retry-after'] ?? 0)
      const waitHint = retryAfter > 0 ? `，约 ${retryAfter} 秒后可重试` : ''
      const detail = error.response.data?.detail
      return Promise.reject(new Error(
        `${typeof detail === 'string' ? detail : '请求频率过高，已触发系统防刷保护'}${waitHint}`
      ))
    }

    // 后端返回的中文错误直接透传
    if (error.response?.data?.detail) {
      const detail = error.response.data.detail
      if (Array.isArray(detail)) {
        const messages = detail
          .map(item => {
            const field = item.loc?.filter(value => value !== 'body').join('.')
            const message = item.msg || item.message
            return [field, message].filter(Boolean).join('：')
          })
          .filter(Boolean)
        return Promise.reject(new Error(messages.join('；') || '提交的数据未通过校验'))
      }
      return Promise.reject(new Error(
        typeof detail === 'string'
          ? detail
          : detail.message || detail.msg || '请求失败'
      ))
    }

    // 常见网络错误 → 友好中文提示
    const msg = error.message ?? ''
    if (msg.includes('Network Error') || msg.includes('connect')) {
      return Promise.reject(new Error('无法连接服务器，已自动尝试重连未果，请检查网络'))
    }
    if (msg.includes('timeout')) {
      return Promise.reject(new Error('请求响应超时（已自动重试5次），请检查网络连接后重试'))
    }
    if (error.response?.status === 404) {
      return Promise.reject(new Error('请求的资源不存在'))
    }
    if (error.response?.status === 403) {
      return Promise.reject(new Error('没有权限执行此操作'))
    }
    if (error.response?.status === 500) {
      return Promise.reject(new Error(
        '服务器处理请求时发生内部错误（HTTP 500）。服务仍可连接，请联系管理员查看后端日志。'
      ))
    }
    if ([502, 503, 504].includes(error.response?.status ?? 0)) {
      return Promise.reject(new Error('后端服务暂时不可用（已重试5次），请稍后重试或联系管理员'))
    }

    return Promise.reject(new Error('请求失败，请稍后重试'))
  }
)

export default apiClient
