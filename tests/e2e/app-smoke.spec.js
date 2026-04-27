const { test, expect } = require('@playwright/test');

test('home page renders upload form', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('h1')).toContainText('Price Mixer');
  await expect(page.locator('input[type="file"]')).toHaveCount(1);
  await expect(page.locator('button[type="submit"]')).toHaveCount(1);
});
