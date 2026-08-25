import { ref } from 'vue'

export type AppTheme = 'light' | 'dark'

const THEME_KEY = 'app_theme'
const PROMPTED_KEY = 'app_theme_prompted'

const currentTheme = ref<AppTheme>('light')
const showDarkPrompt = ref(false)

function applyThemeToDocument(theme: AppTheme) {
  document.documentElement.setAttribute('data-theme', theme)
  // Bootstrap 5.3 uses data-bs-theme to switch its own component variables.
  // Keep it in sync with the application's semantic theme so tables, forms,
  // dropdowns and modals do not fall back to bright light surfaces in dark mode.
  document.documentElement.setAttribute('data-bs-theme', theme)
  // 同时更新 color-scheme 属性确保原生滚动条与表单控件适配
  document.documentElement.style.colorScheme = theme
}

export function useTheme() {
  function initTheme() {
    const savedTheme = localStorage.getItem(THEME_KEY) as AppTheme | null
    const alreadyPrompted = localStorage.getItem(PROMPTED_KEY) === 'true'

    if (savedTheme === 'light' || savedTheme === 'dark') {
      currentTheme.value = savedTheme
      applyThemeToDocument(savedTheme)
      showDarkPrompt.value = false
      return
    }

    // 首次进入：默认采用浅色模式
    currentTheme.value = 'light'
    applyThemeToDocument('light')

    // 探测操作系统/浏览器深色偏好
    const systemPrefersDark = typeof window !== 'undefined'
      && window.matchMedia
      && window.matchMedia('(prefers-color-scheme: dark)').matches

    if (systemPrefersDark && !alreadyPrompted) {
      showDarkPrompt.value = true
    }
  }

  function setTheme(theme: AppTheme, persist = true) {
    currentTheme.value = theme
    applyThemeToDocument(theme)
    if (persist) {
      localStorage.setItem(THEME_KEY, theme)
    }
  }

  function toggleTheme() {
    const nextTheme: AppTheme = currentTheme.value === 'dark' ? 'light' : 'dark'
    setTheme(nextTheme, true)
    showDarkPrompt.value = false
    localStorage.setItem(PROMPTED_KEY, 'true')
  }

  function acceptDarkTheme() {
    setTheme('dark', true)
    localStorage.setItem(PROMPTED_KEY, 'true')
    showDarkPrompt.value = false
  }

  function dismissDarkPrompt() {
    setTheme('light', true)
    localStorage.setItem(PROMPTED_KEY, 'true')
    showDarkPrompt.value = false
  }

  return {
    theme: currentTheme,
    showDarkPrompt,
    initTheme,
    setTheme,
    toggleTheme,
    acceptDarkTheme,
    dismissDarkPrompt
  }
}
