// Synthetic responses only; the shipped classic page owns rendering and actions.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const TASK_ID = 'classic-visual-study-synthetic';
const EMPTY_ID = 'classic-visual-study-empty';
const windows = Array.from({ length: 4 }, (_, index) => ({
  id: `W00${index + 1}`, start: index * 30, end: (index + 1) * 30,
  frame_count: index === 1 ? 0 : 3, frame_timestamps: [index * 30, index * 30 + 10, index * 30 + 20],
  grid_url: index === 1 ? '' : `/data/classic-visual-study/W00${index + 1}.svg`,
  local_summary: `合成窗口 ${index + 1}：核对板书步骤与原始字幕。`,
  transcript_excerpt: `合成摘录 ${index + 1}，只用于界面验收。`
}));
const task = {
  id: TASK_ID, title: '合成图文讲义 · 证据状态与出处', status: 'success', phase: 'completed', progress: 100,
  source_type: 'local', note_path: 'synthetic/note.md', transcript_path: 'synthetic/transcript.json',
  created_at: '2026-10-17T00:00:00Z', updated_at: '2026-10-17T00:01:00Z',
  options: { grid_columns: 3, grid_rows: 1 }, visual_windows: windows,
  summary_diagnostics: { vision_image_window_ids: ['W001'], missing_vision_image_window_ids: ['W002'], omitted_vision_window_ids: ['W003'] }
};
const emptyTask = { ...task, id: EMPTY_ID, title: '合成空窗口 · 导航隔离', visual_windows: [], summary_diagnostics: {} };
const transcript = { source: 'browser', segments: windows.map(window => ({
  start: window.start, end: window.end - 1, text: `${window.id} 原始字幕：按时间核对对应的合成画面。`
})) };
const grid = id => `<svg xmlns="http://www.w3.org/2000/svg" width="720" height="240" viewBox="0 0 720 240"><rect width="720" height="240" fill="#edf2eb"/><g fill="none" stroke="#58635d"><rect x="12" y="12" width="216" height="216"/><rect x="252" y="12" width="216" height="216"/><rect x="492" y="12" width="216" height="216"/></g><g font-family="sans-serif" font-size="28" fill="#26332c"><text x="36" y="110">${id} / 1</text><text x="276" y="110">${id} / 2</text><text x="516" y="110">${id} / 3</text></g></svg>`;

function fixtureResponse(pathname) {
  if (pathname === '/health') return { json: { ffmpeg: true, extension_connected: false, llm_model_configured: false } };
  if (pathname === '/api/tasks') return { json: { tasks: [task, emptyTask] } };
  if (pathname === '/api/library/materials') return { json: { materials: [] } };
  const image = /^\/data\/classic-visual-study\/(W00[134])\.svg$/.exec(pathname);
  if (image) return { contentType: 'image/svg+xml', body: grid(image[1]) };
  for (const record of [task, emptyTask]) {
    const prefix = `/api/tasks/${record.id}`;
    if (pathname === prefix) return { json: { task: record } };
    if (pathname === `${prefix}/note`) return { contentType: 'text/markdown; charset=utf-8', body: `# ${record.title}\n\n这是一份纯合成验收笔记，任务标识：${record.id}。` };
    if (pathname === `${prefix}/note-document`) return { json: { schema_version: 1, title: record.title, sections: [] } };
    if (pathname === `${prefix}/transcript`) return { json: record.id === TASK_ID ? transcript : { source: 'browser', segments: [] } };
    if (pathname === `${prefix}/exports/visual-windows`) return {
      contentType: 'application/json', headers: { 'Content-Disposition': 'attachment; filename="synthetic-visual-windows.json"' },
      body: JSON.stringify({ task_id: record.id, windows: record.visual_windows })
    };
  }
  return null;
}

async function runClassicVisualStudy(browser, baseValue, output) {
  const base = new URL(baseValue);
  assert(base.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(base.hostname));
  fs.mkdirSync(output, { recursive: true });
  const report = { passed: false, fixture: 'synthetic metadata, transcript and SVG grids', screenshots: [], viewports: [],
    excluded: ['video playback', 'model/provider calls', 'dormant review-path/navigator renderers'], errors: [], blocked: [], captureErrors: [], cleanupErrors: [] };
  let primaryError;
  try {
    for (const [name, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]]) {
      const context = await browser.newContext({ viewport: { width, height }, reducedMotion: 'reduce', acceptDownloads: true, serviceWorkers: 'block' });
      let page, pageFailure;
      try {
        page = await context.newPage();
        page.setDefaultTimeout(12000);
        page.on('pageerror', error => report.errors.push(error.message));
        await context.route('**/*', route => {
          const request = route.request(), url = new URL(request.url());
          if (url.origin !== base.origin || request.method() !== 'GET') {
            report.blocked.push(`${request.method()} ${url.origin}${url.pathname}`);
            return route.abort();
          }
          const response = fixtureResponse(url.pathname);
          if (response) return route.fulfill(response);
          if (url.pathname.startsWith('/web/') || url.pathname === '/favicon.ico') return route.continue();
          report.blocked.push(`${request.method()} ${url.pathname}`);
          return route.abort();
        });
        const target = id => new URL(`/web/classic.html?task=${id}&tab=note`, base).href;
        const capture = async suffix => {
          const filename = `${name}-${suffix}.png`;
          await page.screenshot({ path: path.join(output, filename), fullPage: true });
          report.screenshots.push(filename);
        };
        const assertSource = async tab => {
          const url = new URL(page.url());
          assert.equal(url.searchParams.get('task'), TASK_ID);
          assert.equal(url.searchParams.get('tab'), tab);
        };
        const slices = async () => {
          await page.locator('.result-tabs [data-tab="slices"]').click();
          await page.locator('.visual-study-overview').waitFor();
          await page.locator('.visual-study-handout [data-visual-window="W004"]').waitFor();
          await assertSource('slices');
        };
        await page.goto(target(TASK_ID), { waitUntil: 'load' });
        await page.locator('.markdown-note').getByText(new RegExp(TASK_ID)).waitFor();
        assert.equal(await page.locator('#onboardingOverlay').isVisible(), false, 'Explicit task routes skip first-run onboarding');
        await slices();
        const handout = page.locator('.visual-study-handout');
        assert.deepEqual(await handout.locator('article[data-visual-window]').evaluateAll(nodes => nodes.map(node => [node.dataset.visualWindow, node.className])),
          [['W001', 'vision'], ['W002', 'missing'], ['W003', 'omitted'], ['W004', 'ready']]);
        await page.waitForFunction(() => [...document.querySelectorAll('.visual-study-handout img')].every(image => image.complete && image.naturalWidth > 0));
        assert.deepEqual(await handout.locator('img').evaluateAll(images => images.map(image => new URL(image.src).pathname)),
          windows.filter(window => window.grid_url).map(window => window.grid_url));
        const exported = page.waitForEvent('download');
        await page.locator('.visual-study-overview a').click();
        const download = await exported;
        const exportPath = path.join(output, `${name}-synthetic-index.json`);
        await download.saveAs(exportPath);
        assert.deepEqual(JSON.parse(fs.readFileSync(exportPath, 'utf8')), { task_id: TASK_ID, windows });
        await capture('overview-handout');

        await handout.locator('[data-visual-window="W002"] [data-switch-result-tab="transcript"]').click();
        const focused = page.locator('.transcript-window[data-visual-window="W002"].visual-window-focused');
        await focused.waitFor();
        assert.match(await focused.innerText(), /W002 原始字幕/);
        await assertSource('transcript');
        await capture('source-window');

        await page.locator('.result-tool-tabs > summary').click();
        await page.locator('.result-tabs [data-tab="frames"]').click();
        await page.locator('.visual-study-correlation').waitFor();
        await page.locator('.visual-study-deck').waitFor();
        await assertSource('frames');
        for (const selector of ['.visual-study-correlation article', '.visual-study-card']) {
          assert.deepEqual(await page.locator(selector).evaluateAll(nodes => nodes.map(node => node.dataset.visualWindow)),
            windows.map(window => window.id));
        }
        assert.equal(await page.locator('.visual-study-placeholder').count(), 1);
        assert.deepEqual(await page.locator('.visual-study-deck img').evaluateAll(images => images.map(image => new URL(image.src).pathname)),
          windows.filter(window => window.grid_url).map(window => window.grid_url));
        await page.waitForFunction(() => [...document.querySelectorAll('.visual-study-deck img')].every(image => image.complete && image.naturalWidth > 0));
        const geometry = await page.evaluate(() => ({ width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
          deckWidth: document.querySelector('.visual-study-deck').getBoundingClientRect().width }));
        assert(geometry.scrollWidth <= width + 1, `${name} overflow: ${JSON.stringify(geometry)}`);
        assert(geometry.deckWidth > 240, `${name} deck must remain readable`);
        await capture('correlation-deck');
        await page.locator('.visual-study-card').first().locator('[data-switch-result-tab="note"]').click();
        await page.locator('.markdown-note').getByText(new RegExp(TASK_ID)).waitFor();
        await assertSource('note');
        await slices();
        assert.equal(await page.locator('.visual-study-handout article').count(), 4, 'Repeated source entry must not duplicate windows');
        await page.goto(target(EMPTY_ID), { waitUntil: 'load' });
        await page.locator('.markdown-note').getByText(new RegExp(EMPTY_ID)).waitFor();
        await page.locator('.result-tabs [data-tab="slices"]').click();
        await page.getByText('画面切片尚未生成。', { exact: true }).waitFor();
        assert.equal(await page.locator('.visual-study-handout, .visual-study-deck').count(), 0);
        await page.goBack({ waitUntil: 'load' });
        await slices();
        assert.equal(await page.locator('.visual-study-handout article').count(), 4);
        report.viewports.push({ name, width, height, geometry, task_id: TASK_ID, focused_window: 'W002', export_verified: true,
          repeated_navigation: true, empty_task_clears_windows: true });
      } catch (error) {
        pageFailure = error;
        if (page) {
          const filename = `${name}-failure.png`;
          try {
            await page.screenshot({ path: path.join(output, filename), fullPage: false, timeout: 5000 });
            report.screenshots.push(filename);
          } catch (captureError) { report.captureErrors.push(captureError.message); }
        }
        throw error;
      } finally {
        try { await context.close(); } catch (error) {
          report.cleanupErrors.push(error.message);
          if (!pageFailure) throw error;
        }
      }
    }
    assert.deepEqual(report.errors, []);
    assert.deepEqual(report.blocked, []);
    report.passed = true;
    return report;
  } catch (error) {
    primaryError = error;
    report.failure = error.message;
    throw error;
  } finally {
    try { fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n'); } catch (error) {
      if (!primaryError) throw error;
      console.error(`Could not write synthetic visual-study report: ${error.message}`);
    }
  }
}
module.exports = { runClassicVisualStudy, fixtureResponse, TASK_ID, EMPTY_ID };
