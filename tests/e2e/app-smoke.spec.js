const fs = require('fs');
const path = require('path');
const { test, expect } = require('@playwright/test');

const fixturePath = path.resolve(
  __dirname,
  '..',
  'fixtures',
  'e2e-price.csv',
);

test('health, version and request correlation are available', async ({
  request,
}) => {
  const health = await request.get('/api/health', {
    headers: { 'X-Request-ID': 'e2e-health-check' },
  });
  expect(health.status()).toBe(200);
  expect(health.headers()['x-request-id']).toBe('e2e-health-check');
  expect(await health.json()).toMatchObject({ status: 'ok' });

  const version = await request.get('/api/version');
  expect(version.status()).toBe(200);
  expect(await version.json()).toMatchObject({ module: 'price_mixer.api' });

  const worker = await request.get('/api/worker-status');
  expect(worker.status()).toBe(200);
  expect(await worker.json()).toMatchObject({
    mode: 'external',
    status: 'ok',
  });

  const staticAsset = await request.get('/static/js/result-pevm.js');
  expect(staticAsset.status()).toBe(200);
  expect(staticAsset.headers()['cache-control']).toBe(
    'public, max-age=300',
  );
});

test('home page renders upload form', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('h1')).toContainText('Price Mixer');
  await expect(page.locator('input[type="file"]')).toHaveCount(1);
  await expect(page.locator('button[type="submit"]')).toHaveCount(1);
});

test('synthetic supplier price uploads, consolidates and downloads', async ({
  request,
}) => {
  const upload = await request.post('/upload', {
    headers: { 'X-Requested-With': 'XMLHttpRequest' },
    multipart: {
      files: {
        name: 'e2e-price.csv',
        mimeType: 'text/csv',
        buffer: fs.readFileSync(fixturePath),
      },
      'supplier_e2e-price.csv': 'E2E',
    },
  });
  expect(upload.status()).toBe(200);
  const uploadPayload = await upload.json();
  expect(uploadPayload.status).toBe('ok');
  expect(uploadPayload.redirect_url).toMatch(/^\/result\?sid=/);

  const result = await request.get(uploadPayload.redirect_url);
  expect(result.status()).toBe(200);
  const resultHtml = await result.text();
  expect(resultHtml).toContain('Price Mixer');
  expect(resultHtml).toContain('id="run-all-pevm-checks-btn"');
  expect(resultHtml).toContain('id="autofill-ntech-pc-btn"');
  expect(resultHtml).toContain('id="autofill-iven-pc-btn"');

  const ntechPeVmStatus = await request.get(
    '/api/autofill-ntech-pc-status',
  );
  const ivenPeVmStatus = await request.get(
    '/api/autofill-iven-pc-status',
  );
  expect(ntechPeVmStatus.status()).toBe(200);
  expect(ivenPeVmStatus.status()).toBe(200);

  const stats = await request.get('/api/stats');
  expect(stats.status()).toBe(200);
  expect(await stats.json()).toMatchObject({
    // The second synthetic row intentionally has no Onliner ID and is
    // excluded by the default export policy.
    export_rows: 1,
    without_id: 1,
  });

  const download = await request.get('/download');
  expect(download.status()).toBe(200);
  expect(download.headers()['content-type']).toContain(
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  );
  expect((await download.body()).length).toBeGreaterThan(1000);
});
