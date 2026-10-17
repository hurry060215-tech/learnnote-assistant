// Actual desk/classic entry points; every request is fulfilled with local synthetic data.
const { chromium } = require('playwright');
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const { fixtureResponse, createStudyPlan, TASK_ID } = require('./classic-visual-study-fixture.cjs');
const root = path.resolve(__dirname, '..'), output = path.resolve(process.argv[2] || 'build/task-diagnostic-preview'), base = 'http://127.0.0.1:8765';
const markdown = '# 安全诊断报告\n\n当前运行环境：测试\n历史构建：未知\n模型用量：未知\n<img src=x onerror="alert(1)">\n' + '有界报告字段。'.repeat(100);
function fixtureTransportAllowed(method, url) {
  const name = url.pathname, query = url.search;
  if (name.startsWith('/web/')) {
    if (method !== 'GET') return false;
    if (name.endsWith('.html')) return query === `?task=${TASK_ID}&tab=diagnostics`;
    return !query || /^\?v=[a-zA-Z0-9_.-]+$/.test(query);
  }
  if (method !== 'GET') return method === 'POST' && !query && ['/api/study/activity', '/api/study/plan/initialize'].includes(name);
  if (name === `/api/tasks/${TASK_ID}/exports/diagnostics`) return ['', '?format=json'].includes(query);
  if (name === `/api/tasks/${TASK_ID}/events`) return query === '?limit=500';
  if (name === '/api/library/materials') return ['', '?limit=500', '?limit=1000'].includes(query);
  if (name === '/api/study/due') return query === '?limit=20';
  if (name === '/api/model/route') return query === '?transcriber=faster-whisper&whisper_model=small&visual_understanding=true';
  return !query;
}
const native = process.argv.includes('--native');
const json = JSON.stringify({ schema_version: 1, versions: { historical_build: null }, model: { usage: null } }, null, 2) + '\n';
(async () => {
  fs.mkdirSync(output, { recursive: true });
  const report = { passed: false, cases: [], screenshots: [], errors: [], requests: [], unexpected: [], cleanupErrors: [] };
  let browser, server, ownedPid, prepared = false, failure;
  const nativeKey = (zoom, capturePath) => JSON.parse(require('node:child_process').execFileSync('powershell.exe',
    ['-NoProfile', '-NonInteractive', '-File', path.join(__dirname, 'timeline-native-zoom.ps1'), '-OwnedBrowserPid', String(ownedPid), '-Zoom', zoom,
      ...(capturePath ? ['-CapturePath', capturePath] : [])], { encoding: 'utf8', timeout: zoom === 'prepare' ? 45000 : 15000 }));
  try {
    if (native) {
      assert.equal(process.platform, 'win32', 'Native zoom requires hosted Windows Edge');
      server = await chromium.launchServer({ channel: 'msedge', headless: false, args: ['--window-size=1440,1000'] });
      ownedPid = server.process().pid; browser = await chromium.connect(server.wsEndpoint());
    } else browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH, headless: true } : { channel: 'msedge', headless: true });
    for (const surface of ['desk', 'classic']) for (const width of (native ? [null] : [1280, 390])) {
      const context = await browser.newContext({ viewport: native ? null : { width, height: 900 }, acceptDownloads: true, reducedMotion: 'reduce', serviceWorkers: 'block', timezoneId: 'UTC' });
      const plan = createStudyPlan(); let diagnosticGets = 0;
      await context.route('**/*', route => {
        const req = route.request(), url = new URL(req.url()), name = url.pathname;
        if (url.origin !== base || !fixtureTransportAllowed(req.method(), url)) { report.unexpected.push(`${req.method()} ${url.origin}${name}${url.search}`); return route.abort('blockedbyclient'); }
        if (name.startsWith('/web/')) {
          const file = path.resolve(root, name.slice(1)); assert(file.startsWith(path.join(root, 'web') + path.sep));
          return route.fulfill({ body: fs.readFileSync(file), contentType: ({ '.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript', '.json': 'application/json' })[path.extname(file)] || 'application/octet-stream' });
        }
        if (name === `/api/tasks/${TASK_ID}/exports/diagnostics` && ['', '?format=json'].includes(url.search)) {
          assert.equal(req.method(), 'GET'); diagnosticGets++;
          return route.fulfill({ body: url.search ? json : markdown, contentType: url.search ? 'application/json' : 'text/markdown' });
        }
        const result = fixtureResponse(name, { method: req.method(), postData: req.postData(), contentType: req.headers()['content-type'] || '', search: url.search, plan });
        if (result) return route.fulfill(result);
        if (name === '/api/study/activity' && req.method() === 'POST') return route.fulfill({ json: { ok: true } });
        assert.equal(req.method(), 'GET', 'No upload or sharing mutation'); report.requests.push(name);
        if (name === `/api/tasks/${TASK_ID}/events` && url.search === '?limit=500') return route.fulfill({ json: { events: [] } });
        if (name === '/api/model/connection') return route.fulfill({ json: { configured: false, model: {} } });
        if (name === '/api/preferences') return route.fulfill({ json: { task_options: {} } });
        if (name === `/api/personal/task/${TASK_ID}` && !url.search) return route.fulfill({ json: { annotations: [], items: [] } });
        const exact = {
          [`/api/tasks/editions/task/${TASK_ID}`]: { text: '# 合成笔记\n\n本地合成内容。', revision: 'synthetic-revision', annotations: [] },
          [`/api/tasks/editions/task/${TASK_ID}/personal-review`]: { status: 'unmarked', review_revision: '', note_revision: 'synthetic-revision', can_mark: false },
          '/api/model/route?transcriber=faster-whisper&whisper_model=small&visual_understanding=true': { routes: [], blocking_reasons: [], capability_catalog: {}, estimates: { detail: 'Synthetic unknown usage' }, data_leaving_device: [] },
          '/api/connections': { openrouter: { connected: false } },
          '/api/assistant/skills': { skills: [], features: [] },
          '/api/assistant/history': { items: [] },
          '/api/update/status': { status: 'up_to_date', preferences: { auto_check: false, auto_download: false } },
          '/api/study/due?limit=20': { cards: [] }, '/api/study/summary': { total: 0, due: 0 },
          '/api/courses': { courses: [] }, '/api/model/usage': { calls: [] },
          [`/api/tasks/${TASK_ID}/claims`]: { claims: [], sources: [] },
          [`/api/tasks/${TASK_ID}/notes`]: { notes: [] },
          [`/api/tasks/${TASK_ID}/note-versions`]: { versions: [] },
        };
        const key = name + url.search;
        if (Object.hasOwn(exact, key)) return route.fulfill({ json: exact[key] });
        report.unexpected.push(`${req.method()} ${key}`); return route.abort('blockedbyclient');
      });
      const page = await context.newPage(); page.setDefaultTimeout(15000);
      page.on('pageerror', error => report.errors.push({ surface, width, error: error.message }));
      await page.goto(`${base}/web/${surface === 'classic' ? 'classic' : 'index'}.html?task=${TASK_ID}&tab=diagnostics`);
      let opener;
      if (surface === 'desk') { await page.locator('#toolsDialog[open] [data-safe-diagnostic-report]').waitFor(); opener = page.locator('#toolsDialog [data-safe-diagnostic-report]'); }
      else {
        await page.waitForFunction(() => typeof exportTaskArtifact === 'function');
        await page.evaluate(() => { window.pywebview = { api: { export_task() { throw new Error('Direct desktop export forbidden'); } } }; document.querySelector('#resultMoreActions').open = true; });
        opener = page.locator('#diagnosticsButton');
      }
      await opener.click(); const dialog = page.locator('.task-diagnostic-export');
      await dialog.locator('pre').filter({ hasText: '历史构建' }).waitFor();
      let zoomEvidence;
      const metrics = () => page.evaluate(() => ({ width: innerWidth, height: innerHeight, dpr: devicePixelRatio,
        cssZoom: getComputedStyle(document.body).zoom, documentZoom: getComputedStyle(document.documentElement).zoom,
        visualScale: visualViewport.scale, overflow: document.documentElement.scrollWidth - innerWidth }));
      if (native) {
        await page.bringToFront(); const preparation = nativeKey('prepare'); prepared = true;
        const translation = nativeKey('dismiss-translation'); nativeKey('reset');
        await page.waitForFunction(() => Math.abs(devicePixelRatio - 1) < .01);
        const baseline = await metrics();
        const { assertZoomMetrics, waitForNativePreset } = require('./timeline-native-zoom-matrix.cjs');
        assertZoomMetrics(baseline, baseline, 100); nativeKey('200');
        const zoomed = await waitForNativePreset(page, metrics, baseline, 200);
        assertZoomMetrics(zoomed, baseline, 200);
        zoomEvidence = { preparation, translation, baseline, zoomed };
        const filename = `${surface}-native-200-owned-window.png`;
        const capture = nativeKey('capture', path.join(output, filename));
        const size = require('./timeline-native-capture.cjs').pngSize(fs.readFileSync(path.join(output, filename)));
        assert.equal(size.width, capture.width); assert.equal(size.height, capture.height); assert(capture.sampled_colors > 1);
        zoomEvidence.capture = { filename, ...capture }; report.screenshots.push(filename);
      }
      assert.equal(await dialog.locator('pre').textContent(), markdown); assert.equal(await dialog.locator('img').count(), 0);
      assert(await dialog.evaluate(node => node.contains(document.activeElement)), 'Focus starts inside native dialog');
      assert(await dialog.evaluate(node => node.scrollWidth <= node.clientWidth + 1), 'Narrow dialog wraps');
      const screenshot = `${surface}-${native ? "native-200" : width}-preview.png`;
      await page.screenshot({ path: path.join(output, screenshot), fullPage: true }); report.screenshots.push(screenshot);
      let downloads = 0; page.on('download', () => downloads++);
      for (const [format, bytes] of [['md', markdown], ['json', json]]) {
        if (format === 'json') { await dialog.locator('select').selectOption('json'); await page.waitForFunction(text => document.querySelector('.task-diagnostic-export pre')?.textContent === text, json); }
        await dialog.locator('input[type=checkbox]').check();
        if (native && format === 'md') {
          const save = dialog.getByRole('button', { name: '保存已预览报告' }); await save.scrollIntoViewIfNeeded(); await save.focus();
          assert(await save.evaluate(node => { const r = node.getBoundingClientRect(); return document.activeElement === node && r.top >= 0 && r.bottom <= innerHeight; }));
          const filename = `${surface}-native-200-save-focused-owned-window.png`, capture = nativeKey('capture', path.join(output, filename));
          const size = require('./timeline-native-capture.cjs').pngSize(fs.readFileSync(path.join(output, filename)));
          assert.equal(size.width, capture.width); assert.equal(size.height, capture.height); assert(capture.sampled_colors > 1);
          zoomEvidence.focusedSaveCapture = { filename, ...capture }; report.screenshots.push(filename);
        }
        const event = page.waitForEvent('download'); await dialog.getByRole('button', { name: '保存已预览报告' }).click();
        const download = await event; assert.equal(download.suggestedFilename(), `learnnote-diagnostics.${format}`);
        assert.deepEqual(fs.readFileSync(await download.path()), Buffer.from(bytes));
        await dialog.getByRole('button', { name: '保存已预览报告' }).evaluate(node => node.click());
      }
      assert.equal(downloads, 2); assert.equal(diagnosticGets, 2);
      await page.keyboard.press('Escape'); await dialog.waitFor({ state: 'detached' });
      assert(await opener.evaluate(node => document.activeElement === (node.closest('details:not([open])')?.querySelector('summary') || node)), 'Close restores visible opener or collapsed menu summary');
      if (surface === 'classic') await page.locator('#resultMoreActions > summary').click();
      await opener.click(); await dialog.locator('pre').filter({ hasText: '历史构建' }).waitFor();
      await dialog.getByRole('button', { name: '取消导出' }).click(); await dialog.waitFor({ state: 'detached' });
      assert.equal(downloads, 2);
      if (native) {
        nativeKey('reset');
        zoomEvidence.restored = await require('./timeline-native-zoom-matrix.cjs').waitForNativePreset(page, metrics, zoomEvidence.baseline, 100);
        prepared = false;
      }
      report.cases.push({ surface, width, native, zoomEvidence, downloads, diagnosticGets, byteEquality: true, focusRestore: true, cancel: true });
      await context.close();
    }
    assert.deepEqual(report.errors, []); assert.deepEqual(report.unexpected, []); report.passed = true;
  } catch (error) { failure = error; report.failure = error.message; }
  finally {
    if (prepared) { try { nativeKey('reset'); } catch (error) { report.cleanupErrors.push(error.message); failure ||= error; report.passed = false; } }
    try { await browser?.close(); } catch (error) { report.cleanupErrors.push(error.message); failure ||= error; report.passed = false; }
    try { await server?.close(); } catch (error) { report.cleanupErrors.push(error.message); failure ||= error; report.passed = false; }
    try { fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n'); }
    catch (error) { failure ||= error; console.error(`Could not write diagnostic preview report: ${error.message}`); }
  }
  if (failure) throw failure;
})().catch(error => { console.error(error); process.exitCode = 1; });
