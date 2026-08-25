import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget = env.VITE_DEV_API_TARGET || 'http://127.0.0.1:8000'
  const allowedHosts = (env.VITE_ALLOWED_HOSTS || 'meta.21050411.xyz')
    .split(',')
    .map((host) => host.trim())
    .filter(Boolean)

  return {
    plugins: [vue()],
    server: {
      port: 5173,
      host: '0.0.0.0',
      allowedHosts,
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          ws: true
        }
      }
    }
  }
})
