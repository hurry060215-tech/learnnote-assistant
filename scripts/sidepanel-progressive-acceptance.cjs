/* Actual Edge + shipped sidepanel assets; synthetic task transport and Chrome APIs.
 * No native installation/permission prompt, provider, extraction or model call. */
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const { execFileSync } = require('node:child_process');
const ROOT = path.resolve(__dirname, '..');
const { asset } = require('./extension-locale-visual-acceptance.cjs');
function installFixture() {
  const nativeFetch = globalThis.fetch.bind(globalThis);
  const endpoint = 'http://127.0.0.1:18765';
  const original = '<img src=x onerror="globalThis.injected=true">\n原文 cafe\u0301 🧭 {model}';
  const section = (id, text = original) => ({ id, revision: id, status: 'evidence_pending', verified: false, kind: 'text_chunk', markdown: text });
  const c = globalThis.__progressFixture = { calls: [], streams: [], messages: [], permissions: [], id: 'synthetic-one',
    task: { id: 'synthetic-one', status: 'running', updated_at: 'v1', artifact_status: { draft_available: true, partial_draft_available: false } },
    partial: { schema_version: 1, task_id: 'synthetic-one', task_updated_at: 'v1', status: 'draft', verified: false, revision: 'r1', attempt_id: 'a1', source_revision: 's1', generation_revision: '', sections: [{ id: 'draft-time-0', kind: 'temporal_outline', revision: 'outline', status: 'draft', verified: false, summary_generated: false, excerpts: [{ text: original, source_cue_index: 0, start: 0, end: 5 }] }] },
    section, original, fail: false, hidden: false, closeCalls: 0,
    emit(id, status = '', name = 'partial_section_ready', stream = this.streams.at(-1)) { stream.emit(name, { lastEventId: String(id), data: JSON.stringify({ schema_version: 1, status, task_id: this.id }) }); },
    visibility(hidden) { this.hidden = hidden; document.dispatchEvent(new Event('visibilitychange')); }
  };
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => c.hidden });
  const site = 'https://www.bilibili.com/video/BV1SYNTHETIC/';
  const context = { tab: { id: 7, url: site, title: 'Synthetic progressive task' }, page: { page_url: site, title: 'Synthetic progressive task', active_video: { duration: 120 }, browser_subtitles: Array.from({ length: 12 }, (_, i) => ({ start: i * 10, end: i * 10 + 10, text: 'Original subtitle ' + i })) }, resources: [] };
  const json = value => new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } });
  globalThis.fetch = async (input, options = {}) => {
    const url = new URL(input, location.href);
    if (url.origin === location.origin) return nativeFetch(input, options);
    if (url.origin !== endpoint) throw Error('Unexpected transport destination');
    c.calls.push({ path: url.pathname, method: options.method || 'GET' });
    if (url.pathname === '/health') return json({ service: 'learnnote', app_version: 'fixture', backend_version: 'fixture', protocol_version: 1, llm_model_configured: true, default_llm_model: 'synthetic' });
    if (c.fail) throw Error('Synthetic disconnected transport');
    if (url.pathname === `/api/tasks/${c.id}/partial-note`) return json(c.partial);
    if (url.pathname === `/api/tasks/${c.id}`) return json({ task: c.task });
    if (url.pathname.endsWith('/note')) return new Response('# Final synthetic note');
    if (url.pathname.endsWith('/transcript')) return json({ segments: context.page.browser_subtitles });
    throw Error('Unexpected task request ' + url.pathname);
  };
  globalThis.EventSource = class {
    constructor(url) { if (!url.startsWith(endpoint + '/api/tasks/' + c.id + '/events/stream?after=')) throw Error('Unexpected stream'); this.url = url; this.events = new Map(); this.closed = false; c.streams.push(this); }
    addEventListener(name, fn) { this.events.set(name, fn); }
    emit(name, event) { this.events.get(name)?.(event); }
    close() { this.closed = true; c.closeCalls++; }
  };
  globalThis.chrome = {
    i18n: { getUILanguage: () => 'en-US', getMessage: () => '' },
    storage: { local: { get: async defaults => ({ ...defaults, backendUrl: endpoint }), set: async () => {} } },
    permissions: { getAll: async () => ({ origins: ['https://www.bilibili.com/*'] }), contains: async () => true, request: async value => { c.permissions.push(value); return false; } },
    tabs: { query: async () => [] },
    runtime: { onMessage: { addListener() {} }, sendMessage: async message => { c.messages.push(message); if (message.type === 'get-current-context') return context; if (message.type === 'start-current-task') return { task_id: c.id, accepted: true }; throw Error('Unexpected extension action'); } }
  };
}
async function run() {
  const { chromium } = require('playwright');
  const out = path.resolve(process.argv[2] || 'build/sidepanel-progressive-ui'); fs.mkdirSync(out, { recursive: true });
  const server = http.createServer((req, res) => { const file = asset(req.url); if (!file) { res.writeHead(404); return res.end(); } res.setHeader('Content-Type', file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'text/javascript' : file.endsWith('.png') ? 'image/png' : 'text/html'); fs.createReadStream(file).pipe(res); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({ channel: 'msedge', headless: true });
    const page = await browser.newPage({ viewport: { width: 390, height: 900 }, locale: 'en-US' }); page.setDefaultTimeout(10000);
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(installFixture);
    await page.goto(`http://127.0.0.1:${server.address().port}/extension/sidepanel.html`);
    await page.waitForFunction(() => __learnnoteSidepanel.getState().clientConnected);
    await page.locator('#sendButton').click(); await page.locator('[data-section-id="draft-time-0"]').waitFor();
    assert.match(await page.locator('[data-section-id="draft-time-0"]').innerText(), /Not an AI summary/);
    const replayReads = await page.evaluate(() => __progressFixture.calls.length);
    await page.evaluate(() => __progressFixture.emit(1, 'failed', 'task_updated'));
    await page.waitForFunction(count => __progressFixture.calls.length > count && document.querySelector('#progressiveStatus').textContent.includes('Unverified'), replayReads);
    assert(await page.evaluate(() => !__progressFixture.streams.at(-1).closed));
    await page.evaluate(() => {
      const c = __progressFixture; c.outlineNode = document.querySelector('[data-section-id="draft-time-0"]');
      c.partial.sections.push(c.section('middle', c.original + '\n' + 'Literal line\n'.repeat(45)), c.section('last'));
      c.partial.generation_revision = 'g1'; c.task.artifact_status.partial_draft_available = true; c.emit(2);
    });
    await page.locator('[data-section-id="middle"]').waitFor();
    assert(await page.evaluate(() => document.querySelector('[data-section-id="draft-time-0"]') === __progressFixture.outlineNode));
    assert.match(await page.locator('#progressiveStatus').innerText(), /Unverified/);
    assert.equal(await page.locator('#progressiveSections img').count(), 0);
    assert(await page.evaluate(() => document.querySelector('[data-section-id="middle"] pre').textContent.startsWith(__progressFixture.original)));
    await page.evaluate(() => {
      const node = document.querySelector('[data-section-id="middle"]'); const text = node.querySelector('pre').firstChild;
      const range = document.createRange(); range.setStart(text, 0); range.setEnd(text, 12);
      getSelection().removeAllRanges(); getSelection().addRange(range);
      const scroller = document.querySelector('#progressiveSections'); scroller.scrollTop += node.getBoundingClientRect().top - scroller.getBoundingClientRect().top + 80;
      __progressFixture.saved = { node, text, selection: getSelection().toString(), offset: node.getBoundingClientRect().top - scroller.getBoundingClientRect().top };
      __progressFixture.partial.sections.splice(1, 0, __progressFixture.section('earlier', '# Arrived earlier\nAnother draft'));
      __progressFixture.emit(8);
    });
    await page.locator('[data-section-id="earlier"]').waitFor();
    assert(await page.evaluate(() => {
      const c = __progressFixture, node = document.querySelector('[data-section-id="middle"]');
      return node === c.saved.node && node.querySelector('pre').firstChild === c.saved.text && getSelection().toString() === c.saved.selection
        && Math.abs(node.getBoundingClientRect().top - document.querySelector('#progressiveSections').getBoundingClientRect().top - c.saved.offset) < 2;
    }), 'real DOM identity, text selection and scroll survive earlier section insertion');
    const calls = await page.evaluate(() => __progressFixture.calls.length);
    await page.evaluate(() => { __progressFixture.emit(8); __progressFixture.emit(7); });
    assert.equal(await page.evaluate(() => __progressFixture.calls.length), calls);
    await page.evaluate(() => __progressFixture.streams.at(-1).onerror());
    await page.waitForFunction(() => __progressFixture.streams.length === 2);
    assert.match(await page.evaluate(() => __progressFixture.streams.at(-1).url), /after=8$/);
    await page.evaluate(() => __progressFixture.visibility(true));
    assert(await page.evaluate(() => __progressFixture.streams.every(stream => stream.closed)));
    await page.evaluate(() => { __progressFixture.partial.sections.push(__progressFixture.section('hidden-arrival')); __progressFixture.visibility(false); });
    await page.locator('[data-section-id="hidden-arrival"]').waitFor();
    await page.evaluate(() => { __progressFixture.fail = true; __progressFixture.streams.at(-1).onerror(); });
    await page.waitForFunction(() => document.querySelector('#progressiveStatus').textContent.includes('Reconnecting'));
    await page.evaluate(() => { __progressFixture.fail = false; __progressFixture.visibility(true); __progressFixture.visibility(false); });
    await page.waitForFunction(() => document.querySelector('#progressiveStatus').textContent.includes('Unverified'));
    await page.screenshot({ path: path.join(out, 'sections.png'), fullPage: true });
    await page.evaluate(() => { __progressFixture.task.status = 'cancelled'; __progressFixture.emit(9, 'cancelled', 'task_updated'); });
    await page.waitForFunction(() => document.querySelector('#progressiveStatus').textContent.includes('cancelled'));
    await page.waitForFunction(() => __progressFixture.calls.filter(call => call.path.endsWith('/transcript')).length === 1);
    await page.waitForFunction(() => document.querySelector('#quickTranscriptPanel').textContent.includes('Original subtitle'));
    const cancelledCalls = await page.evaluate(() => __progressFixture.calls.length);
    await page.evaluate(() => { __progressFixture.emit(10); __progressFixture.visibility(true); __progressFixture.visibility(false); });
    assert.equal(await page.evaluate(() => __progressFixture.calls.length), cancelledCalls);
    await page.evaluate(() => {
      __learnnoteSidepanel.setProcessingMode('quick');
      const c = __progressFixture; c.id = c.task.id = c.partial.task_id = 'synthetic-two'; c.task.status = 'running';
      c.partial.attempt_id = 'a2'; c.partial.sections = [c.section('new-task')];
    });
    await page.locator('#sendButton').click(); await page.locator('[data-section-id="new-task"]').waitFor();
    assert.equal(await page.locator('[data-section-id="middle"]').count(), 0);
    await page.evaluate(() => { __progressFixture.task.status = 'failed'; __progressFixture.emit(1, 'failed', 'task_updated'); });
    await page.waitForFunction(() => document.querySelector('#progressiveStatus').textContent.includes('did not finish'));
    await page.setViewportSize({ width: 320, height: 740 });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    assert.deepEqual(await page.evaluate(() => __progressFixture.permissions), []);
    assert(await page.evaluate(() => __progressFixture.calls.every(call => call.method === 'GET')));
    assert.equal(await page.evaluate(() => Boolean(globalThis.injected)), false); assert.deepEqual(errors, []);
    await page.screenshot({ path: path.join(out, 'stopped.png'), fullPage: true });
    const report = { passed: true, source_sha: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: ROOT, encoding: 'utf8' }).trim(), browser: browser.version(), assets: 'Actual extension/sidepanel.html, sidepanel.js and sidepanel-progress.js', transport: 'Synthetic task HTTP replies and EventSource; real browser DOM, selection and scroll', chrome_apis: 'Synthetic runtime/storage/permissions', native_chrome_permission_acceptance: 'unverified', model_or_extraction_calls: 0, page_errors: errors,
      checks: ['source outline before model output', 'literal unverified sections', 'keyed DOM and real selection', 'scroll anchor', 'duplicate and out-of-order events', 'rejoin cursor', 'hidden/resume', 'fallback recovery', 'cancel stops progress with one bounded transcript recovery', 'task/source switch', 'failure', '320px layout', 'no new permissions or mutation'] };
    fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify(report));
  } finally { await browser?.close(); await new Promise(resolve => server.close(resolve)); }
}
if (process.argv.includes('--self-test')) {
  assert(asset('/extension/sidepanel-progress.js')); assert.equal(asset('/extension/../backend/app/main.py'), null);
  new Function('return ' + installFixture.toString());
  console.log('Sidepanel progressive fixture asset/path/syntax checks pass. Browser execution pending Windows Edge CI.');
} else if (require.main === module) run().catch(error => { console.error(error); process.exitCode = 1; });
module.exports = { installFixture };
