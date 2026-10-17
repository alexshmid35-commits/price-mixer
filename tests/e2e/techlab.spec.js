const { test, expect } = require('@playwright/test');

test('Techlab download card, manual supplier detection and settings', async ({ page }) => {
  await page.goto('/');
  const card = page.locator('.api-source-item[data-source="techlab"]');
  await expect(card).toContainText('Techlab');
  await expect(card.locator('.api-source-fetch')).toBeEnabled();

  await page.locator('input[type="file"]').setInputFiles({
    name: 'techlab_bn.xlsx',
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    buffer: Buffer.from('supplier name detection only'),
  });
  await expect(page.locator('.file-item input[type="text"]')).toHaveValue('Techlab');

  await Promise.all([
    page.waitForResponse(response => response.url().endsWith('/api/app-settings') && response.request().method() === 'GET'),
    page.locator('#open-settings-btn').click(),
  ]);
  await expect(page.locator('#settings-save-note')).toHaveText('');
  await page.getByRole('button', { name: 'Поставщики', exact: true }).click();
  await expect(page.locator('#st-techlab-price')).toHaveValue('Опт');
  await expect(page.locator('#st-techlab-stock-days')).toHaveValue('2');
  await expect(page.locator('#st-techlab-order-days')).toHaveValue('2');
  await page.locator('#st-techlab-price').selectOption('Vip');
  await page.locator('#st-techlab-order-days').fill('5');
  await page.locator('#save-settings-btn').click();
  await expect(page.locator('#settings-save-note')).toHaveText('Настройки сохранены.');
  await page.locator('#close-settings-btn').click();
  await Promise.all([
    page.waitForResponse(response => response.url().endsWith('/api/app-settings') && response.request().method() === 'GET'),
    page.locator('#open-settings-btn').click(),
  ]);
  await expect(page.locator('#settings-save-note')).toHaveText('');
  await expect(page.locator('#st-techlab-price')).toHaveValue('Vip');
  await expect(page.locator('#st-techlab-order-days')).toHaveValue('5');
  await page.locator('#st-techlab-price').selectOption('Опт');
  await page.locator('#st-techlab-order-days').fill('2');
  await page.locator('#save-settings-btn').click();
  await expect(page.locator('#settings-save-note')).toHaveText('Настройки сохранены.');
  await page.screenshot({ path: 'test-results/techlab-desktop.png' });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: 'test-results/techlab-mobile.png' });
  const overflows = await page.locator('#settings-pane-suppliers').evaluate(
    element => element.scrollWidth > element.clientWidth + 1,
  );
  expect(overflows).toBe(false);
});
