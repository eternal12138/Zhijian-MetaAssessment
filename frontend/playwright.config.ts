import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  fullyParallel: false,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://127.0.0.1:5173',
    channel: 'chrome',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure'
  }
})
