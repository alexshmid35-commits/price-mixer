const { test, expect } = require('@playwright/test');

test('consolidated workspace keeps products first and tools available on desktop and mobile', async ({ page, request }) => {
  const upload = await request.post('/upload', {
    headers: { 'X-Requested-With': 'XMLHttpRequest' },
    multipart: {
      files: {
        name: 'workspace.csv', mimeType: 'text/csv',
        buffer: Buffer.from('Код,Наименование,Цена,Onliner_ID\n1,Мышь Logitech M90,20,12345\n2,Клавиатура Cherry KC1000,30,\n'),
      },
      'supplier_workspace.csv': 'Tradex',
    },
  });
  expect(upload.ok()).toBeTruthy();
  const panelRequests = [];
  page.on('request', req => {
    const path = new URL(req.url()).pathname;
    if (['/api/categories', '/api/category-markups', '/api/suppliers', '/api/auto-refresh-settings'].includes(path)) panelRequests.push(path);
  });
  await page.goto((await upload.json()).redirect_url);
  await expect(page.getByRole('heading', { name: 'Сводный прайс' })).toBeVisible();
  await expect(page.locator('#tbl-main tbody')).toContainText('Logitech M90');
  await expect(page.locator('#tbl-main tbody')).toContainText('Cherry KC1000');
  await page.locator('#toggle-noid-btn').click();
  await expect(page.locator('#tbl-main tbody')).not.toContainText('Logitech M90');
  await expect(page.locator('#tbl-main tbody')).toContainText('Cherry KC1000');
  await page.locator('#toggle-noid-btn').click();
  await expect(page.locator('#tbl-main tbody')).toContainText('Logitech M90');

  expect(panelRequests).toEqual([]);
  await page.locator('#open-pricing-btn').click();
  await expect(page.locator('#pricing-modal')).toBeVisible();
  await expect.poll(() => panelRequests.length).toBe(4);
  await page.locator('#close-pricing-btn').click();
  await expect(page.locator('#pricing-modal')).toBeHidden();

  page.on('dialog', dialog => dialog.accept());
  const exportButton = page.locator('#export-google-sheet-btn');
  const headerPositions = () => page.locator('.workspace-actions .btn').evaluateAll(buttons =>
    buttons.map(button => {
      const { x, y, width, height } = button.getBoundingClientRect();
      return { x, y, width, height };
    }));
  for (const [name, width, height] of [['desktop', 1440, 900], ['mobile', 390, 844]]) {
    await page.setViewportSize({ width, height });
    expect(await page.evaluate(async () => (await document.fonts.load('650 14px Manrope', 'Прайс')).length)).toBeGreaterThan(0);
    await expect(page.locator('#tbl-main tbody tr').first()).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1);
    const before = await headerPositions();
    let release;
    const pending = new Promise(resolve => { release = resolve; });
    await page.route('**/api/export-google-sheets', async route => {
      await pending;
      const ok = name === 'desktop';
      await route.fulfill({ status: ok ? 200 : 500, json: {
        status: ok ? 'ok' : 'error', message: ok ? 'Готово' : 'Тестовая ошибка выгрузки',
      } });
    });
    try {
      await exportButton.click();
      await expect(exportButton).toBeDisabled();
      await expect(exportButton).toHaveText('Записываю в лист');
      await expect(exportButton.locator('.workspace-export-spinner')).toBeVisible();
      expect(await headerPositions()).toEqual(before);
      await page.screenshot({ path: `test-results/consolidated-workspace-${name}.png` });
    } finally {
      release();
    }
    await expect(exportButton).toBeEnabled();
    await expect(exportButton).toHaveText('В Google Таблицу');
    expect(await headerPositions()).toEqual(before);
    await page.unroute('**/api/export-google-sheets');
  }
  expect(await page.locator('.workspace-table-scroll').evaluate(el => el.scrollWidth > el.clientWidth)).toBeTruthy();
  await page.getByRole('link', { name: 'База Onliner', exact: true }).click();
  await expect(page.locator('#db-search-query')).toBeInViewport();
  await page.getByRole('link', { name: 'К товарам', exact: true }).click();
  await expect(page.locator('#tbl-main_filter input')).toBeInViewport();
});

test('quality control puts products and reasons first without changing check actions', async ({ page, request }, testInfo) => {
  const upload = await request.post('/upload', {
    headers: { 'X-Requested-With': 'XMLHttpRequest' },
    multipart: {
      files: {
        name: 'quality.csv', mimeType: 'text/csv',
        buffer: Buffer.from('Код,Наименование,Цена,Onliner_ID\n1,Мышь Logitech M90,20,12345\n'),
      },
      'supplier_quality.csv': 'Tradex',
    },
  });
  expect(upload.ok()).toBeTruthy();
  const checkCalls = [];
  const markupCalls = [];
  const mixed = {
    status: 'ok', checked: 42,
    suspicious_price_count: 9, duplicate_count: 2, missing_id_count: 1,
    suspicious_price_samples: ['[Мыши] Logitech M90 <USB> | причина: РРЦ <= опт | опт=20.0, РРЦ=19.0, маржа=-1.0 (-5.0%)'],
    duplicate_samples: ['[Мониторы] Acer Vero (x2)', '[Мониторы] Acer Vero (x2)'],
    missing_id_samples: ['[Клавиатуры] Cherry KC1000'],
  };
  let report = mixed;
  await page.route('**/api/preexport-quality-check', route => {
    checkCalls.push(route.request().method());
    return route.fulfill({ json: report });
  });
  await page.route('**/api/reapply-saved-markups', route => {
    markupCalls.push(route.request().postDataJSON());
    return route.fulfill({ json: { status: 'ok', updated_rows: 1 } });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto((await upload.json()).redirect_url);
  const open = page.locator('#run-quality-check-btn');
  const panel = page.getByRole('region', { name: 'Контроль качества' });
  await expect(panel).toBeHidden();
  expect(checkCalls).toEqual([]);
  await open.click();
  const list = panel.getByRole('list');
  await expect(panel.getByRole('button', { name: 'Цены 9' })).toHaveAttribute('aria-pressed', 'true');
  await expect(list.getByText('Logitech M90 <USB>', { exact: true })).toBeVisible();
  await expect(list.getByText('РРЦ <= опт', { exact: true })).toBeVisible();
  await expect(list.getByText('Опт: 20.0 · РРЦ: 19.0 · Маржа: -1.0 (-5.0%)')).toBeVisible();
  await expect(panel.getByText('Показано 1 из 9')).toBeVisible();
  await panel.screenshot({ path: testInfo.outputPath('quality-desktop.png'), animations: 'disabled' });

  await panel.getByRole('button', { name: 'Дубли 2' }).click();
  await expect(list.getByRole('listitem')).toHaveCount(2);
  await expect(list.getByText('Дубль · 2 одинаковых строк').first()).toBeVisible();
  await panel.getByRole('button', { name: 'Без OnlinerID 1' }).click();
  await expect(list.getByText('Cherry KC1000')).toBeVisible();
  expect(checkCalls).toEqual(['GET']);
  expect(markupCalls).toEqual([]);

  await page.setViewportSize({ width: 390, height: 844 });
  await panel.getByRole('button', { name: 'Цены 9' }).click();
  expect(await panel.evaluate(el => el.scrollWidth <= el.clientWidth)).toBeTruthy();
  await panel.screenshot({ path: testInfo.outputPath('quality-mobile.png'), animations: 'disabled' });
  await panel.getByRole('button', { name: 'Свернуть' }).click();
  await expect(list).toBeHidden();
  await panel.getByRole('button', { name: 'Развернуть' }).click();
  await expect(list).toBeVisible();

  report = { status: 'ok', checked: 42 };
  await panel.getByRole('button', { name: 'Доприменить наценки' }).click();
  await expect(panel.getByText('Замечаний по ценам нет.')).toBeVisible();
  expect(markupCalls).toEqual([{ source: 'quality_check' }]);
  expect(checkCalls).toEqual(['GET', 'GET']);

  report = { status: 'error', message: 'Тестовая ошибка проверки' };
  await open.click();
  await expect(panel.getByText(report.message)).toBeVisible();
  await expect(panel.getByRole('group', { name: 'Тип замечания' })).toBeHidden();
});
