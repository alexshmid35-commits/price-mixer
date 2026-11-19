const { test, expect } = require('@playwright/test');

test('supplier list shows last successful download even after an error', async ({ page }) => {
  await page.route('**/api/source-fetch-status', route => route.fulfill({ json: {
    status: 'ok',
    items: [
      { source_key: 'iven_zakaz', label: 'IVEN_ZAKAZ', enabled: true, configured: true, status: 'error', message: 'Лимит скачиваний', finished_at: 1794592000 },
      { source_key: 'tradex', label: 'Tradex', enabled: true, configured: true, status: 'ready', ready: true, progress: 100, finished_at: 1794590000 },
      { source_key: 'techlab', label: 'Techlab', enabled: true, configured: true, status: 'idle' },
    ],
    history: [{ source_key: 'iven_zakaz', event_type: 'fetch', status: 'ok', finished_at: 1794580000 }],
  } }));
  await page.goto('/');
  const order = page.locator('[data-source="iven_zakaz"].api-source-item');
  await expect(order).toContainText('Лимит скачиваний');
  await expect(order.locator('.api-source-time strong')).not.toHaveText('Нет загрузок');
  await expect(page.locator('[data-source="techlab"].api-source-item .api-source-time strong')).toHaveText('Нет загрузок');
  await expect(page.locator('#api-process-ready-btn')).toHaveText('Обработать готовые прайсы (1)');
  await expect(page.locator('.api-source-progress')).toHaveCount(0);
  await page.locator('#api-history-toggle-btn').click();
  await expect(page.locator('#api-history-body')).toBeVisible();
  await page.locator('#api-history-toggle-btn').click();
  for (const [name, width, height] of [['desktop', 1440, 900], ['mobile', 390, 844]]) {
    await page.setViewportSize({ width, height });
    expect(await page.evaluate(async () => (await document.fonts.load('650 14px Manrope', 'Поставщики')).length)).toBeGreaterThan(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1);
    await page.screenshot({ path: `test-results/supplier-workspace-${name}.png` });
  }
});
