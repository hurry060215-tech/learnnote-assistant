const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { runClassicVisualStudy, fixtureResponse, createStudyPlan, TASK_ID, EMPTY_ID } = require('../classic-visual-study-fixture.cjs');

test('synthetic task, transcript, grid and exported index have exact source identity', () => {
  const task = fixtureResponse(`/api/tasks/${TASK_ID}`).json.task;
  const transcript = fixtureResponse(`/api/tasks/${TASK_ID}/transcript`).json;
  const exported = JSON.parse(fixtureResponse(`/api/tasks/${TASK_ID}/exports/visual-windows`).body);
  assert.equal(task.id, TASK_ID);
  assert.equal(task.media_path, undefined, 'No fake playable media');
  assert.deepEqual(exported, { task_id: TASK_ID, windows: task.visual_windows });
  assert.deepEqual(task.visual_windows.map(window => window.id), ['W001', 'W002', 'W003', 'W004']);
  assert.deepEqual(transcript.segments.map(cue => cue.start), [0, 30, 60, 90]);
  for (const window of task.visual_windows) {
    if (!window.grid_url) continue;
    const response = fixtureResponse(window.grid_url);
    assert.equal(response.contentType, 'image/svg+xml');
    assert(response.body.includes(window.id));
    assert(!/https?:\/\/(?!www\.w3\.org)/.test(response.body), 'SVG has no external assets');
  }
  assert.deepEqual(fixtureResponse(`/api/tasks/${EMPTY_ID}`).json.task.visual_windows, []);
  for (const unknown of ['/api/tasks/real-task', `/api/tasks/${TASK_ID}/media`, '/api/model/call', '/data/classic-visual-study/W002.svg']) {
    assert.equal(fixtureResponse(unknown), null, unknown);
  }
});

test('routing is isolated, fails closed and retains a primary failure during cleanup', async () => {
  const output = fs.mkdtempSync(path.join(os.tmpdir(), 'classic-visual-contract-'));
  const primary = new Error('synthetic navigation failure');
  let handler, closed = 0;
  const browser = { async newContext(options) {
    assert.equal(options.acceptDownloads, true);
    assert.equal(options.serviceWorkers, 'block');
    assert.equal(options.timezoneId, 'UTC');
    return {
      async newPage() { return { setDefaultTimeout() {}, on() {}, async goto() { throw primary; },
        async screenshot(options) { assert.equal(options.timeout, 5000); assert.equal(options.fullPage, false); throw new Error('synthetic capture failure'); } }; },
      async route(pattern, callback) { assert.equal(pattern, '**/*'); handler = callback; },
      async close() { closed++; throw new Error('synthetic close failure'); }
    };
  } };
  try {
    await assert.rejects(runClassicVisualStudy(browser, 'http://127.0.0.1:8765/web/classic.html', output), error => error === primary);
    assert.equal(closed, 1);
    const report = JSON.parse(fs.readFileSync(path.join(output, 'report.json'), 'utf8'));
    assert.equal(report.passed, false); assert.equal(report.failure, primary.message);
    assert.deepEqual(report.cleanupErrors, ['synthetic close failure']);
    assert.deepEqual(report.captureErrors, ['synthetic capture failure']);
    const dispatch = async (url, method = 'GET', postData = null, contentType = '') => {
      const calls = [];
      await handler({ request: () => ({ url: () => url, method: () => method, postData: () => postData, headers: () => ({ 'content-type': contentType }) }),
        abort: () => calls.push('abort'), continue: () => calls.push('continue'), fulfill: response => calls.push(response) });
      return calls;
    };
    assert.deepEqual(await dispatch('https://example.test/api/tasks'), ['abort']);
    assert.deepEqual(await dispatch('http://127.0.0.1:8765/api/tasks', 'POST'), ['abort']);
    assert.deepEqual(await dispatch('http://127.0.0.1:8765/api/unexpected'), ['abort']);
    for (const url of ['https://example.test/api/study/plan/initialize',
      'http://127.0.0.1:8765/api/study/plan/initialize?extra=1', 'http://127.0.0.1:8765/web/app.js',
      'http://127.0.0.1:8765/api/study/cards', 'http://127.0.0.1:8765/api/model/call']) {
      assert.deepEqual(await dispatch(url, 'POST', '{"timezone":"UTC"}', 'application/json'), ['abort']);
    }
    const initialize = 'http://127.0.0.1:8765/api/study/plan/initialize';
    assert.deepEqual(await dispatch(initialize, 'PUT', '{"timezone":"UTC"}', 'application/json'), ['abort']);
    assert.deepEqual(await dispatch(initialize, 'POST', '{"timezone":"UTC","extra":true}', 'application/json'), ['abort']);
    assert.deepEqual(await dispatch(initialize, 'POST', '{"timezone":"UTC"}', 'text/plain'), ['abort']);
    const initialized = await dispatch(initialize, 'POST', '{"timezone":"UTC"}', 'application/json');
    assert.deepEqual(initialized, [{ json: { plan: { ...createStudyPlan(), timezone_initialized: true } } }]);
    assert.deepEqual(await dispatch('http://127.0.0.1:8765/api/study/plan'), initialized);
    assert.deepEqual(await dispatch('http://127.0.0.1:8765/web/app.js?v=fixture'), ['continue']);
    assert.deepEqual(await dispatch(`http://127.0.0.1:8765/api/tasks/${TASK_ID}`), [fixtureResponse(`/api/tasks/${TASK_ID}`)]);
  } finally { fs.rmSync(output, { recursive: true, force: true }); }
});

test('browser flow uses shipped actions and read-only DOM assertions', () => {
  const root = path.resolve(__dirname, '../..');
  const source = fs.readFileSync(path.join(root, 'scripts/classic-visual-study-fixture.cjs'), 'utf8');
  const classic = fs.readFileSync(path.join(root, 'web/classic.html'), 'utf8');
  const app = fs.readFileSync(path.join(root, 'web/app.js'), 'utf8');
  assert(app.includes('!onboardingWasCompleted()) && !hasExplicitTaskRoute()'));
  assert(source.includes("page.locator('#onboardingOverlay').isVisible(), false"));
  assert(!source.includes('storageState'), 'Contexts never inherit saved profile state');
  for (const tab of ['note', 'slices', 'frames']) assert(classic.includes(`data-tab="${tab}"`));
  assert(source.includes('page.goBack('));
  assert(source.includes('image.naturalWidth > 0'));
  assert(source.includes("page.waitForEvent('download')"));
  assert(source.includes("['desktop', 1440, 1000], ['mobile', 390, 844]"));
  assert(!source.includes('addInitScript'));
  assert(!/visualStudy\w+\(/.test(source), 'No direct renderer calls bypassing UI lifecycle');
  assert(!/\.innerHTML\s*=/.test(source), 'No injected output');
});

test('context setup failures are also preserved and cleaned up', async () => {
  for (const phase of ['newPage', 'route']) {
    const output = fs.mkdtempSync(path.join(os.tmpdir(), 'classic-visual-setup-'));
    const primary = new Error(`synthetic ${phase} failure`);
    let closed = 0;
    const browser = { async newContext() { return {
      async newPage() { if (phase === 'newPage') throw primary; return { setDefaultTimeout() {}, on() {} }; },
      async route() { throw primary; },
      async close() { closed++; throw new Error('synthetic close failure'); }
    }; } };
    try {
      await assert.rejects(runClassicVisualStudy(browser, 'http://127.0.0.1:8765/web/classic.html', output), error => error === primary);
      assert.equal(closed, 1);
      const report = JSON.parse(fs.readFileSync(path.join(output, 'report.json'), 'utf8'));
      assert.equal(report.failure, primary.message);
      assert.deepEqual(report.cleanupErrors, ['synthetic close failure']);
    } finally { fs.rmSync(output, { recursive: true, force: true }); }
  }
});

test('outer browser cleanup cannot replace the fixture failure', async () => {
  const vm = require('node:vm');
  const output = fs.mkdtempSync(path.join(os.tmpdir(), 'classic-visual-outer-'));
  const source = fs.readFileSync(path.join(__dirname, '../learning-workflow-acceptance.cjs'), 'utf8');
  const primary = new Error('synthetic fixture failure');
  let stderr = '', closed = 0, status;
  const cleanup = [];
  try {
    await vm.runInNewContext(source, {
      require(name) {
        if (name === 'playwright') return { chromium: { async launch() { return {
          async close() { closed++; throw new Error('synthetic browser close failure'); }
        }; } } };
        if (name === './classic-visual-study-fixture.cjs') return { async runClassicVisualStudy() { throw primary; } };
        return require(name);
      },
      process: { argv: ['node', 'fixture', 'http://127.0.0.1:8765/web/classic.html', output],
        stderr: { write(value) { stderr += value; } }, exit(value) { status = value; } },
      console: { error(value) { cleanup.push(value); } }
    });
    assert.equal(closed, 1); assert.equal(status, 1);
    assert(stderr.includes(primary.stack));
    assert.deepEqual(cleanup, ['Could not close learning acceptance browser: synthetic browser close failure']);
  } finally { fs.rmSync(output, { recursive: true, force: true }); }
});

test('study initialization accepts only the pinned startup payload and keeps contexts separate', () => {
  const plan = createStudyPlan(), other = createStudyPlan();
  const initialize = options => fixtureResponse('/api/study/plan/initialize', {
    method: 'POST', postData: '{"timezone":"UTC"}', contentType: 'application/json', plan, ...options
  });
  for (const postData of ['{', 'null', '[]', '"UTC"', '{}', '{"timezone":null}', '{"timezone":42}',
    '{"timezone":""}', '{"timezone":"Invalid/Zone"}', '{"timezone":"Asia/Shanghai"}',
    '{"timezone":"UTC","title":"unexpected"}', '{"timezone":"UTC","task_id":"real-task"}']) {
    assert.equal(initialize({ postData }), null, postData);
    assert.equal(plan.timezone_initialized, false);
  }
  for (const method of ['GET', 'PUT', 'PATCH', 'DELETE']) assert.equal(initialize({ method }), null, method);
  assert.equal(initialize({ search: '?timezone=UTC' }), null);
  assert.equal(initialize({ contentType: 'text/plain' }), null);
  assert.equal(initialize({ plan: null }), null);
  assert.deepEqual(fixtureResponse('/api/study/plan', { plan }).json.plan, createStudyPlan());
  const response = initialize({});
  assert.deepEqual(response.json.plan, { ...createStudyPlan(), timezone_initialized: true });
  assert.deepEqual(initialize({}), response, 'Repeated startup is idempotent');
  assert.deepEqual(fixtureResponse('/api/study/plan', { plan }), response);
  assert.deepEqual(fixtureResponse('/api/study/plan', { plan: other }).json.plan, createStudyPlan());
  response.json.plan.daily_target = 99;
  assert.equal(plan.daily_target, 10, 'Response snapshots cannot mutate the fixture state');
  for (const options of [{ method: 'POST', plan }, { method: 'PUT', plan }, { search: '?extra=1', plan }]) {
    assert.equal(fixtureResponse('/api/study/plan', options), null);
  }
});

test('actual classic startup hydrates the plan through POST then GET on each navigation', async () => {
  const vm = require('node:vm');
  const source = fs.readFileSync(path.join(__dirname, '../../web/app.js'), 'utf8').replace(/\r\n/g, '\n');
  const actualFunction = name => {
    let start = source.indexOf(`function ${name}(`);
    assert(start >= 0, name);
    if (source.slice(start - 6, start) === 'async ') start -= 6;
    const end = source.indexOf('\n}\n', start);
    assert(end > start, name);
    return source.slice(start, end + 3);
  };
  assert(source.includes('\nloadStudyPlan();\n'), 'The actual entrypoint initializes study state unconditionally');
  for (const viewport of ['desktop', 'mobile']) {
    const plan = createStudyPlan(), calls = [];
    for (const navigation of ['initial task', 'empty task', 'browser Back']) {
      const timezone = { value: '' }, els = { studyPlanTarget: { value: '' }, studyPlanPaused: { checked: true } };
      const context = vm.createContext({ els, document: { querySelector(selector) {
        assert.equal(selector, '#studyPlanTimezone'); return timezone;
      } }, Intl: { DateTimeFormat: () => ({ resolvedOptions: () => ({ timeZone: 'UTC' }) }) },
      apiUrl: value => value, async fetchJson(pathname, options = {}) {
        const method = options.method || 'GET';
        calls.push([method, pathname]);
        const response = fixtureResponse(pathname, { method, postData: options.body || null,
          contentType: options.headers?.['Content-Type'] || '', plan });
        assert(response, `${viewport} ${navigation}: ${method} ${pathname}`);
        return response.json;
      } });
      vm.runInContext(actualFunction('initializeLocalStudyTimezone') + actualFunction('loadStudyPlan'), context);
      await context.loadStudyPlan();
      assert.equal(els.studyPlanTarget.value, '10'); assert.equal(els.studyPlanPaused.checked, false);
      assert.equal(timezone.value, 'UTC'); assert.equal(plan.timezone_initialized, true);
    }
    assert.deepEqual(calls, Array.from({ length: 3 }, () => [
      ['POST', '/api/study/plan/initialize'], ['GET', '/api/study/plan']
    ]).flat());
  }
});
