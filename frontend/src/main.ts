import { createApp } from 'vue'
import { createPinia } from 'pinia'
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate'
import 'bootstrap/dist/css/bootstrap.min.css'
import 'bootstrap-icons/font/bootstrap-icons.css'
import './styles/main.css'
import App from './App.vue'
import router from './router'

const pinia = createPinia()
pinia.use(piniaPluginPersistedstate)

const app = createApp(App)

// 全局未捕获异常防护（杜绝整应用崩溃）
app.config.errorHandler = (err, instance, info) => {
  console.error('[GlobalErrorHandler] Vue error caught:', err, info)
}

window.addEventListener('unhandledrejection', event => {
  console.warn('[GlobalErrorHandler] Unhandled promise rejection:', event.reason)
})

app.use(pinia).use(router).mount('#app')
