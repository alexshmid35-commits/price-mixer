const { defineConfig } = require('@playwright/test');
const {
  adminPassword,
  adminUsername,
  baseURL,
} = require('./tests/e2e/server-utils.cjs');

module.exports = defineConfig({
  testDir: './tests/e2e',
  globalSetup: './tests/e2e/global-setup.cjs',
  globalTeardown: './tests/e2e/global-teardown.cjs',
  outputDir: './test-results/playwright',
  timeout: 120000,
  expect: {
    timeout: 15000,
  },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    headless: true,
    httpCredentials: {
      username: adminUsername,
      password: adminPassword,
    },
  },
});
