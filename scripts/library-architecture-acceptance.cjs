// Synthetic imports only. Run against an isolated loopback fixture backend.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

async function main() {
  const base = process.argv[2], out = path.resolve(process.argv[3]);
  assert(['127.0.0.1', 'localhost'].includes(new URL(base).hostname));
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 }, reducedMotion: 'reduce' });
  const page = await context.newPage(), errors = [], reads = [], imports = [], prefix = `Library fixture ${Date.now()}`;
  const report = { browser: browser.version(), synthetic: true, cases: [], errors, external: [], passed: false };
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.origin !== new URL(base).origin) { report.external.push(url.origin); return route.abort(); }
    reads.push(url.pathname); return route.continue();
  });
  async function importFixture(index) {
    const name = `${prefix} ${String(index).padStart(3, '0')}`;
    const response = await context.request.post(base + '/api/library/materials/import', { multipart: { file: {
      name: name + '.md', mimeType: 'text/markdown', buffer: Buffer.from(`# ${name}\n\nSynthetic pagination evidence ${index}.\n`),
    } } });
    assert(response.ok()); return (await response.json()).material;
  }
  try {
    for (let index = 0; index < 105; index++) imports.push(await importFixture(index));
    const listing = await (await context.request.get(base + '/api/library/materials?standalone=true&limit=100')).json();
    const expected = listing.total;
    assert(listing.has_more); assert.equal(listing.materials.length, 100);
    const tail = await (await context.request.get(base + '/api/library/materials?standalone=true&limit=100&cursor=' + encodeURIComponent(listing.next_cursor))).json();
    const target = tail.materials.find(item => item.title.startsWith(prefix));
    assert(target, 'Choose a synthetic document proven outside the first page');
    await page.goto(base); await page.locator('#notes .library-row').first().waitFor();
    await page.waitForFunction(() => document.querySelectorAll('#notes .library-row').length === 100);
    assert.equal(await page.locator('#homeLibraryCount').textContent(), `${expected} 份内容`);
    assert(await page.locator('#moreMaterials').isVisible());
    await page.screenshot({ path: path.join(out, '1440-library-first-page.png') });
    const focused = await page.locator('#notes [data-id]').first().elementHandle();
    await focused.focus();
    await page.waitForTimeout(5600); // Observe the real five-second recovery poll.
    assert(await focused.evaluate(node => node.isConnected && document.activeElement === node));
    report.cases.push('unchanged recovery poll preserves the exact focused row');
    while (await page.locator('#moreMaterials').isVisible()) {
      const before = await page.locator('#notes .library-row').count();
      await page.locator('#moreMaterials').click();
      await page.waitForFunction(count => document.querySelectorAll('#notes .library-row').length > count, before);
    }
    await page.waitForFunction(count => document.querySelectorAll('#notes .library-row').length === count, expected);
    assert(!(await page.locator('#moreMaterials').isVisible()));
    await importFixture(105); await page.locator('#refresh').click();
    await page.waitForFunction(count => document.querySelectorAll('#notes .library-row').length === count, expected + 1);
    report.cases.push('refresh finds a newly imported document and retains every opened page');
    await page.locator('#search').fill(target.title);
    await page.waitForFunction(() => document.querySelectorAll('#notes .library-row').length === 1);
    assert.equal(await page.locator('#notes [data-id]').getAttribute('data-id'), target.material_id);
    assert.equal(await page.locator('#homeLibraryCount').textContent(), `${expected + 1} 份内容`);
    await page.screenshot({ path: path.join(out, '1440-library-full-catalog-search.png') });
    report.cases.push('full-catalog title search finds a document outside the first page without changing the total');
    await page.goto(base); await page.reload();
    await page.waitForFunction(() => document.querySelectorAll('#notes .library-row').length === 100);
    assert.equal(await page.locator(`#notes [data-id="${target.material_id}"]`).count(), 0);
    await page.goto(base + '/#material/' + target.material_id);
    await page.locator('#document h1').filter({ hasText: target.title }).waitFor();
    assert(reads.includes('/api/library/materials/' + target.material_id));
    assert(!reads.includes('/api/tasks'), 'The shipped workspace must use the artifact-free task catalog');
    report.cases.push('direct material routes read by ID and task-list reads use the catalog endpoint');
    await page.goto(base); await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('#moreMaterials').waitFor({ state: 'attached' });
    if (await page.locator('#menu').getAttribute('aria-expanded') !== 'true') await page.locator('#menu').click();
    await page.locator('#moreMaterials').waitFor({ state: 'visible' });
    await page.screenshot({ path: path.join(out, '390-library-more.png') });
    assert(await page.locator('#moreMaterials').evaluate(node => node.getBoundingClientRect().height >= 44));
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    report.cases.push('mobile pagination stays reachable with a 44px target and no horizontal overflow');
    assert.deepEqual(errors, []); assert.deepEqual(report.external, []); report.passed = true;
  } finally {
    fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 2));
    await browser.close();
  }
  console.log(JSON.stringify(report));
}
main().catch(error => { console.error(error); process.exitCode = 1; });
