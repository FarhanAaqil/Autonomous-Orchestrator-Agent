import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './browser', workers: 1, timeout: 45000, retries: 0,
  use: {baseURL: process.env.PHASE3_BASE_URL || 'http://127.0.0.1:8081', headless: true,
    channel: process.env.CI ? undefined : 'chrome', trace: 'retain-on-failure'},
  reporter: 'list',
});
