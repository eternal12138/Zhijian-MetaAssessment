import { readonly, ref } from 'vue'

export type FeedbackTone = 'primary' | 'success' | 'warning' | 'danger'

interface ConfirmOptions {
  title: string
  message: string
  confirmText?: string
  cancelText?: string
  tone?: FeedbackTone
}

interface ConfirmState extends Required<ConfirmOptions> {
  open: boolean
}

interface ToastItem {
  id: number
  message: string
  tone: FeedbackTone
}

const confirmState = ref<ConfirmState>({
  open: false,
  title: '',
  message: '',
  confirmText: '确认',
  cancelText: '取消',
  tone: 'primary'
})
const toasts = ref<ToastItem[]>([])
let confirmResolver: ((result: boolean) => void) | null = null
let nextToastId = 1

export function confirmAction(options: ConfirmOptions): Promise<boolean> {
  if (confirmResolver) confirmResolver(false)
  confirmState.value = {
    open: true,
    title: options.title,
    message: options.message,
    confirmText: options.confirmText ?? '确认',
    cancelText: options.cancelText ?? '取消',
    tone: options.tone ?? 'primary'
  }
  return new Promise(resolve => {
    confirmResolver = resolve
  })
}

export function resolveConfirmation(result: boolean) {
  confirmState.value.open = false
  const resolver = confirmResolver
  confirmResolver = null
  resolver?.(result)
}

export function notify(
  message: string,
  tone: FeedbackTone = 'success',
  duration = 3200
) {
  const id = nextToastId++
  toasts.value.push({ id, message, tone })
  window.setTimeout(() => dismissToast(id), duration)
}

export function dismissToast(id: number) {
  toasts.value = toasts.value.filter(item => item.id !== id)
}

export function useUiFeedback() {
  return {
    confirmState: readonly(confirmState),
    toasts: readonly(toasts),
    confirmAction,
    resolveConfirmation,
    notify,
    dismissToast
  }
}
