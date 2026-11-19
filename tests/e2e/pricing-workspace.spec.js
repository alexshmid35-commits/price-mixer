const { test, expect } = require('@playwright/test');

test('pricing and preview share one dialog without applying markups or exporting', async ({ page, request }) => {
  const upload = await request.post('/upload', {
    headers: { 'X-Requested-With': 'XMLHttpRequest' },
    multipart: {
      files: {
        name: 'pricing.csv', mimeType: 'text/csv',
        buffer: Buffer.from('Код,Наименование,Цена,Onliner_ID\n1,Мышь Logitech M90,20,12345\n'),
      },
      'supplier_pricing.csv': 'Tradex',
    },
  });
  expect(upload.ok()).toBeTruthy();
  const writes = [];
  page.on('request', req => {
    const path = new URL(req.url()).pathname;
    if (['/api/apply-markup', '/api/export-google-sheets'].includes(path)) writes.push(path);
  });
  await page.route('**/api/category-preview-items', async route => {
    if (!route.request().postDataJSON().with_market) return route.continue();
    await route.fulfill({ json: { items: [
      { row_idx: 0, onliner_id: '12345', name: 'Мышь Logitech M90', wholesale: 20, market_min: 22 },
    ] } });
  });
  await page.goto((await upload.json()).redirect_url);
  await page.setViewportSize({ width: 1440, height: 900 });
  const opener = page.locator('#open-pricing-btn');
  await opener.click();
  const dialog = page.getByRole('dialog', { name: 'Цены и категории' });
  const rules = dialog.locator('#workspace-price-rules');
  const preview = dialog.locator('#preview-modal');
  const previewButton = dialog.getByRole('button', { name: 'Предпросмотр', exact: true });
  const rulesButton = dialog.getByRole('button', { name: 'Наценки и категории', exact: true });
  await expect(rules.locator('#markup-categories option').first()).toBeAttached();
  await expect(rules.getByText('Видимость категорий', { exact: true })).toBeVisible();
  await rules.locator('#markup-percent').fill('17');
  await page.screenshot({ path: 'test-results/pricing-rules-desktop.png' });

  const response = page.waitForResponse(res => new URL(res.url()).pathname === '/api/category-preview-items'
    && res.request().postDataJSON().with_market);
  await previewButton.click();
  expect((await response).request().postDataJSON().categories.length).toBeGreaterThan(0);
  await expect(previewButton).toHaveAttribute('aria-pressed', 'true');
  await expect(rules).toBeHidden();
  await expect(preview.locator('#preview-percent')).toHaveValue('17');
  await expect(preview.locator('#preview-full-table tbody')).toContainText('Logitech M90');
  await page.screenshot({ path: 'test-results/pricing-preview-desktop.png' });
  await page.setViewportSize({ width: 390, height: 844 });
  const table = preview.getByRole('region', { name: 'Таблица предпросмотра' });
  expect(await table.evaluate(el => el.scrollWidth > el.clientWidth)).toBeTruthy();
  expect(await dialog.evaluate(el => el.scrollWidth)).toBeLessThanOrEqual(391);
  await page.screenshot({ path: 'test-results/pricing-preview-mobile.png' });

  await rulesButton.click();
  await expect(rulesButton).toHaveAttribute('aria-pressed', 'true');
  await expect(preview).toBeHidden();
  await expect(rules.locator('#markup-percent')).toHaveValue('17');
  await page.screenshot({ path: 'test-results/pricing-rules-mobile.png' });
  await previewButton.click();
  await dialog.locator('#close-pricing-btn').click();
  await expect(opener).toBeFocused();
  await opener.click();
  await expect(rules).toBeVisible();
  expect(writes).toEqual([]);
});
