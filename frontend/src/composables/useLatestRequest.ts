import { onScopeDispose, ref } from 'vue'

/** Ignore late responses/errors after filters change, refresh or unmount. */
export function useLatestRequest() {
  const loading = ref(false)
  const error = ref('')
  let version = 0
  function invalidate() { version++; loading.value = true; error.value = '' }
  async function run<T>(fetch: () => Promise<T>, apply: (value: T) => void) {
    const current = ++version
    loading.value = true
    error.value = ''
    try {
      const value = await fetch()
      if (current === version) apply(value)
    } catch (reason) {
      if (current === version) error.value = reason instanceof Error ? reason.message : '列表加载失败，请重试'
    } finally {
      if (current === version) loading.value = false
    }
  }
  onScopeDispose(() => { version++ })
  return { loading, error, run, invalidate }
}
