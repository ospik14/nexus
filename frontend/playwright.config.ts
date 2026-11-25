import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 35_000,
  workers: 1,
  use: { baseURL: 'https://127.0.0.1:8875', ignoreHTTPSErrors: true, trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'cd .. && .venv/bin/python -m tests.browser_server',
    url: 'https://127.0.0.1:8875/',
    ignoreHTTPSErrors: true,
    timeout: 25_000,
  },
})
