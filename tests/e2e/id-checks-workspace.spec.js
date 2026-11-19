const { test, expect } = require('@playwright/test');

test('ID review keeps surviving candidates still after single and bulk confirmation', async ({ page, request }) => {
  const upload = await request.post('/upload', {
    headers: { 'X-Requested-With': 'XMLHttpRequest' },
    multipart: {
      files: { name: 'review.csv', mimeType: 'text/csv', buffer: Buffer.from('Код,Наименование,Цена\n1,Мышь Logitech M90,20\n') },
      'supplier_review.csv': 'Tradex',
    },
  });
  expect(upload.ok()).toBeTruthy();
  const rows = Array.from({ length: 40 }, (_, i) => ({
    item_key: 'row-' + i, product_name: 'Клавиатура Logitech K' + i, supplier: 'Tradex',
    category: 'Клавиатуры', confidence_tier: 'exact', decision_state: 'open',
    candidates: [{ id: String(1000 + i), name: 'Клавиатура Logitech K' + i, score: 1, reason: 'exact_name' }],
  }));
  let itemLoads = 0;
  let confirmed = 0;
  await page.route('**/api/experimental-noid/status*', route => route.fulfill({ json: { job: {
    job_id: 'review-job', status: 'done', processed: 40, total: 40, message: 'Подбор завершён.',
    tier_counts: { exact: 40 - confirmed }, decision_counts: { confirmed },
  } } }));
  await page.route('**/api/experimental-noid/items?*', route => {
    itemLoads++;
    return route.fulfill({ json: { items: rows, page: 1, pages: 1, total: 40 } });
  });
  await page.route('**/api/experimental-noid/decision', route => {
    expect(route.request().postDataJSON()).toMatchObject({ action: 'confirm', item_key: 'row-14', candidate_id: '1014' });
    confirmed++;
    return route.fulfill({ json: { status: 'ok' } });
  });
  await page.route('**/api/experimental-noid/bulk-preview', route => route.fulfill({ json: { count: 2 } }));
  await page.route('**/api/experimental-noid/bulk-decision', route => {
    expect(route.request().postDataJSON()).toMatchObject({ action: 'confirm', item_keys: ['row-2', 'row-3'] });
    confirmed += 2;
    return route.fulfill({ json: { item_keys: ['row-2', 'row-3'] } });
  });
  page.on('dialog', dialog => dialog.accept());
  await page.goto((await upload.json()).redirect_url);
  await page.locator('#open-ntech-checks-modal-btn').click();
  await expect(page.getByRole('dialog', { name: 'Проверки ID', exact: true })).toBeVisible();
  await page.screenshot({ path: 'test-results/id-checks-desktop.png' });
  await page.locator('#experimental-noid-open-btn').click();
  const list = page.locator('#experimental-noid-list');
  const row = i => list.locator('[data-item-key="row-' + i + '"].experimental-noid-item');
  await expect(list.locator('.experimental-noid-item')).toHaveCount(40);
  await row(2).locator('.experimental-noid-local-name').click();
  await row(3).locator('.experimental-noid-local-name').click();
  await row(14).evaluate(el => {
    const container = el.closest('#experimental-noid-list');
    container.scrollTop += el.getBoundingClientRect().top - container.getBoundingClientRect().top;
  });
  const top = locator => locator.evaluate(el => el.getBoundingClientRect().top);
  const before = await top(row(15));
  const loads = itemLoads;
  await row(14).getByRole('button', { name: 'Подтвердить', exact: true }).click();
  await expect(row(14)).toHaveCount(0);
  expect(Math.abs(await top(row(15)) - before)).toBeLessThan(2);
  await page.locator('#experimental-noid-bulk-confirm-btn').click();
  await expect(row(2)).toHaveCount(0);
  await expect(row(3)).toHaveCount(0);
  expect(Math.abs(await top(row(15)) - before)).toBeLessThan(2);
  expect(itemLoads).toBe(loads);
  await expect(page.locator('#experimental-noid-page-label')).toContainText('37');
  for (const [name, width, height] of [['desktop', 1440, 900], ['mobile', 390, 844]]) {
    await page.setViewportSize({ width, height });
    expect(await list.evaluate(el => el.clientHeight)).toBeGreaterThan(180);
    expect(await list.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBeTruthy();
    await page.screenshot({ path: `test-results/id-candidates-${name}.png` });
  }
});
