const { test, expect } = require('@playwright/test');

test('Tradex PCs have an isolated check and stay without ID until exact cards exist', async ({ page, request }) => {
  const csv = [
    'Код,Наименование,Цена,Onliner_ID,Гарантия',
    'pc1,WOUK Game N000021BK,100,,24',
    'pc2,WOUK Multi N000001WH,200,,24',
    'pc3,WOUK Night L000017BK,300,999,24',
  ].join('\n');
  const upload = await request.post('/upload', {
    headers: { 'X-Requested-With': 'XMLHttpRequest' },
    multipart: {
      files: { name: 'tradex-pc.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) },
      'supplier_tradex-pc.csv': 'Tradex',
    },
  });
  expect(upload.status()).toBe(200);
  const result = await upload.json();
  await page.goto(result.redirect_url);
  await page.locator('#open-ntech-checks-modal-btn').click();
  const panel = page.locator('#pevm-autofill-panel');
  await expect(panel).toBeVisible();
  await expect(page.locator('#tradex-pc-review-badge')).toHaveText('2');
  await page.locator('#autofill-tradex-pc-btn').click();
  await expect(page.locator('#pevm-autofill-results')).toHaveText(
    'Компьютеры Tradex: подставлено 0 из 2, оставлено на ручную проверку 2.',
  );
  const status = await request.get('/api/autofill-tradex-pc-status');
  expect(await status.json()).toMatchObject({ running: false, total: 2, applied: 0, skipped: 2 });
  const download = await request.get('/download');
  expect(download.status()).toBe(200);
  expect((await download.body()).length).toBeGreaterThan(1000);
  for (const [width, height, name] of [[1280, 900, 'desktop'], [390, 844, 'mobile']]) {
    await page.setViewportSize({ width, height });
    await expect.poll(() => page.locator('#pevm-autofill-progress-value').evaluate(element => (
      Math.round(element.getBoundingClientRect().width / element.parentElement.getBoundingClientRect().width * 100)
    ))).toBe(100);
    await page.screenshot({ path: `test-results/tradex-pc-${name}.png` });
    const sizes = await panel.evaluate(element => ({ width: element.clientWidth, content: element.scrollWidth }));
    expect(sizes.content).toBeLessThanOrEqual(sizes.width + 1);
    const boxes = await panel.locator('button').evaluateAll(buttons => buttons.map(button => {
      const box = button.getBoundingClientRect();
      return { x: box.x, y: box.y, right: box.right, bottom: box.bottom };
    }));
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i], b = boxes[j];
        expect(a.x < b.right && a.right > b.x && a.y < b.bottom && a.bottom > b.y).toBe(false);
      }
    }
  }
  const catalog = [
    'Category,B,Model,D,OnlinerID,F,G,FullName',
    'Компьютеры,,WOUK Game N000021BK,,123,,,Компьютер WOUK Game N000021BK',
    'Компьютеры,,WOUK Multi N000001BK,,124,,,Компьютер WOUK Multi N000001BK',
  ].join('\n');
  const imported = await request.post('/api/onliner-db-import-csv', {
    multipart: { file: { name: 'catalog.csv', mimeType: 'text/csv', buffer: Buffer.from(catalog) } },
  });
  expect(imported.status()).toBe(200);
  await expect.poll(async () => (await (await request.get('/api/onliner-db-import-status')).json()).percent).toBe(100);
  const quickPick = await request.post('/api/id-replace-candidates', {
    data: { name: 'WOUK Game N000021BK', category: 'Компьютеры' },
  });
  expect((await quickPick.json()).items).toMatchObject([{ id: '123', score: 1 }]);
  const wrongColor = await request.post('/api/id-replace-candidates', {
    data: { name: 'WOUK Multi N000001WH', category: 'Компьютеры' },
  });
  expect((await wrongColor.json()).items).toEqual([]);
  await page.locator('#autofill-tradex-pc-btn').click();
  await expect(page.locator('#pevm-autofill-results')).toHaveText(
    'Компьютеры Tradex: подставлено 1 из 2, оставлено на ручную проверку 1.',
  );
  for (const [supplier, expectedId] of [['Tradex', '123'], ['IVEN', '']]) {
    const fresh = await request.post('/upload', {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      multipart: {
        files: { name: 'prices.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) },
        'supplier_prices.csv': supplier,
      },
    });
    expect(fresh.status()).toBe(200);
    await request.get((await fresh.json()).redirect_url);
    const table = await request.get('/api/consolidated-page?search%5Bvalue%5D=N000021BK');
    expect((await table.json()).data[0][0]).toBe(expectedId);
  }
});
