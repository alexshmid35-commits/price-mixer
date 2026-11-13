const { test, expect } = require('@playwright/test');

test('catalog widget shows durable update summary without technical import details', async ({ page, request }) => {
  let summary = { finished_at: 1794560400, inserted: 1468, updated: 42 };
  let running = false;
  let failed = false;
  await page.route('**/api/onliner-db-stats*', route => route.fulfill({ json: {
    total_products: 822965, total_names: 817975, by_source: { onliner_catalog: 818021 }, last_import: summary,
  } }));
  await page.route('**/api/onliner-db-import-status*', route => route.fulfill({ json: {
    running, percent: running ? 25 : 100, finished_at: running ? null : 1794560400,
    message: failed ? 'Ошибка скачивания' : 'Готово! Всего 822965, 816875 категорий обновлено',
  } }));
  const upload = await request.post('/upload', {
    headers: { 'X-Requested-With': 'XMLHttpRequest' },
    multipart: {
      files: { name: 'widget.csv', mimeType: 'text/csv', buffer: Buffer.from('Код,Наименование,Цена\n1,Мышь Logitech M90,20\n') },
      'supplier_widget.csv': 'Tradex',
    },
  });
  expect(upload.ok()).toBeTruthy();
  const { redirect_url } = await upload.json();
  await page.goto(redirect_url);
  const widget = page.locator('#onliner-catalog-widget');
  await expect(page.locator('#db-last-changes')).toHaveText(/Новых: 1\s?468 · Изменено: 42/);
  await expect(page.locator('#db-last-updated')).not.toHaveText('Нет данных');
  await expect(page.locator('#db-import-progress-wrap')).toBeHidden();
  await expect(widget).not.toContainText('вариантов названий');
  await expect(widget).not.toContainText('onliner_catalog');
  await expect(widget).not.toContainText('SQLite');
  for (const [name, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]]) {
    await page.setViewportSize({ width, height });
    await widget.scrollIntoViewIfNeeded();
    const overflow = await widget.evaluate(el => el.scrollWidth > el.clientWidth + 1);
    expect(overflow).toBeFalsy();
    await widget.screenshot({ path: `test-results/catalog-widget-${name}.png` });
  }
  summary = { finished_at: 1794560400, inserted: 1468, updated: null };
  await page.reload();
  await expect(page.locator('#db-last-changes')).toHaveText(/Новых: 1\s?468/);
  await expect(page.locator('#db-last-changes')).not.toContainText('Изменено');
  running = true;
  await page.reload();
  await expect(page.locator('#db-import-msg')).toHaveText('Обновление каталога · 25%');
  running = false;
  summary = { finished_at: 1794560400, inserted: 0, updated: 0 };
  await expect(page.locator('#db-import-progress-wrap')).toBeHidden();
  await expect(page.locator('#db-last-changes')).toHaveText('Новых: 0 · Изменено: 0');
  failed = true;
  await page.reload();
  await expect(page.locator('#db-import-msg')).toContainText('Не удалось обновить каталог');
  await expect(page.locator('#db-last-changes')).toHaveText('Новых: 0 · Изменено: 0');
});
