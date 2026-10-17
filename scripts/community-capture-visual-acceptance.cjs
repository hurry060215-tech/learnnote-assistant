/* Hosted Edge renders the shipped collector and sidepanel. Synthetic DOM and local replies only. */
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const { execFileSync } = require('node:child_process');
const { asset, installFixtures, FIXTURE } = require('./extension-locale-visual-acceptance.cjs');
const { bounded, cleanup, writeReport } = require('./range-platform-browser-acceptance.cjs');
const { syntheticTimestampRanges } = require('./community-timestamp-fixture.cjs');
const TIMEOUT = 15000;
const ROOT = path.resolve(__dirname, '..'), SITE = 'https://www.bilibili.com/video/BV1234567890?p=2';
function communityFixture() {
  const base = chrome.runtime.sendMessage, listeners = [];
  const control = globalThis.__communityFixture = { calls: [], enabled: false, permission: true, pending: null, hold: false, saved: [], requests: [], actions: [], release() { this.pending?.release(); this.pending = null; } };
  // Observe the promise returned by the shipped click handler, not click timing.
  const add = HTMLElement.prototype.addEventListener;
  HTMLElement.prototype.addEventListener = function (type, handler, options) {
    if (type === 'click' && ['communityPreview', 'communitySave'].includes(this.id)) {
      const original = handler;
      handler = function (event) {
        const action = { id: control.actions.length + 1, type: this.id, settled: false }; control.actions.push(action);
        try {
          const result = original.call(this, event);
          Promise.resolve(result).then(() => { action.settled = true; }, error => { action.settled = true; action.error = String(error); });
          return result;
        } catch (error) { action.settled = true; action.error = String(error); throw error; }
      };
    }
    return add.call(this, type, handler, options);
  };
  const previousAdd = chrome.runtime.onMessage.addListener;
  chrome.runtime.onMessage.addListener = fn => { listeners.push(fn); previousAdd(fn); };
  control.change = () => listeners.forEach(fn => fn({ type: 'current-context-updated', reason: 'navigation', tabId: 7 }));
  control.revoke = () => { control.permission = false; listeners.forEach(fn => fn({ type: 'site-permission-revoked', origin: 'https://www.bilibili.com/*' })); };
  const getAll = chrome.permissions.getAll;
  chrome.permissions.contains = async () => control.permission;
  chrome.permissions.getAll = async () => { const all = await getAll(); return control.permission ? all : { origins: [] }; };
  chrome.permissions.request = async () => { throw Error('Community flow must not request permission'); };
  chrome.runtime.sendMessage = async message => {
    if (!message.type.startsWith('community-')) return base(message);
    control.calls.push(message);
    if (message.type === 'community-cancel') return { ok: true };
    const request = { id: message.requestId, type: message.type, settled: false }; control.requests.push(request);
    try {
      if (control.hold) await new Promise(release => { control.pending = { requestId: message.requestId, type: message.type, release }; });
      if (message.type === 'community-settings') { control.enabled = message.enabled; return { enabled: control.enabled }; }
      if (!control.permission) return { error: 'community_permission_required' };
      if (!control.enabled) return { error: 'community_context_disabled' };
      if (message.type === 'community-preview') return { preview_id: 'a'.repeat(64), fingerprint: 'b'.repeat(64), items: [
        { item_id: 'c'.repeat(32), kind: 'comment', timestamp_seconds: null, text: 'Why use this example? [邮箱已省略]' },
        { item_id: 'd'.repeat(32), kind: 'danmaku', timestamp_seconds: 83, text: '<img src=x onerror="globalThis.injected=true"> Literal audience content.' }
      ] };
      if (message.type === 'community-save') { control.saved.push(message.selectedItemIds); return { stored_count: message.selectedItemIds.length }; }
      throw Error('Unexpected community action');
    } finally { request.settled = true; }
  };
}
async function heldAction(page, { selector, type, invalidate }) {
  let primary, held;
  try {
    await page.evaluate(() => { __communityFixture.hold = true; });
    await page.locator(selector).click();
    const handle = await page.waitForFunction(type => {
      const control = __communityFixture, action = control.actions.at(-1);
      return control.pending?.type === type && action && !action.settled
        ? { requestId: control.pending.requestId, actionId: action.id } : false;
    }, type, { timeout: TIMEOUT });
    try { held = await handle.jsonValue(); } finally { await handle.dispose(); }
    await invalidate();
  } catch (error) { primary = error; }
  finally { await cleanup(primary, [
    ['release held request', () => page.evaluate(() => { __communityFixture.hold = false; __communityFixture.release(); })],
    ['settle held request and UI action', async () => {
      if (!held) return;
      const handle = await page.waitForFunction(({ requestId, actionId }) => {
        const control = __communityFixture;
        return !control.pending && control.requests.some(item => item.id === requestId && item.settled)
          && control.actions.some(item => item.id === actionId && item.settled);
      }, held, { timeout: TIMEOUT });
      await handle.dispose();
      const action = await page.evaluate(({ actionId }) => __communityFixture.actions.find(item => item.id === actionId), held);
      assert.equal(action.error, undefined, 'The actual click handler must settle successfully');
    }],
  ]); }
}
async function finishCapture({ out, report, browser, server, write = fs.writeFileSync }, primary) {
  try {
    await cleanup(primary, [['browser close', () => browser?.close()],
      ['asset connections close', () => { if (server?.listening) server.closeAllConnections(); }],
      ['asset server close', () => {
        if (!server?.listening) return;
        return new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
      }]]);
  } catch (error) {
    primary = error; report.passed = false; report.error ||= String(error.stack || error);
    report.cleanup_errors = error.cleanup_errors || [];
  }
  writeReport(out, report, primary, write);
}
async function collect(page) {
  return page.evaluate(site => LearnNoteCommunityDOM.collect({ document, view: window, pageUrl: site, expectedPageUrl: site }), SITE);
}
function syntheticDOMDiagnostics(result) {
  if (document.title !== 'Synthetic Bilibili-shaped visible DOM fixture') throw Error('Diagnostics require the named synthetic DOM fixture');
  const expected = [
    ['legacy-comment', '.reply-item .reply-content', 'Why does this example use a smaller batch?'],
    ['comment-with-controls', '.reply-wrap .reply-content', 'This explanation helped me compare the examples.'],
    ['timed-danmaku', '.bpx-player-dm-list-dm', 'Could we revisit this step?'],
    ['untimed-danmaku', '.bili-dm', 'Rendered overlay without an asserted timestamp'],
    ['open-shadow-comment', null, 'Open-shadow comment body only.'],
  ];
  const parent = node => node?.parentElement || node?.getRootNode?.()?.host || null;
  const label = node => node ? { tag: String(node.tagName || '').slice(0, 40), id: String(node.id || '').slice(0, 80) } : null;
  const rect = node => { const bounds = node.getBoundingClientRect(); return Object.fromEntries(['left', 'top', 'right', 'bottom', 'width', 'height'].map(key => [key, Math.round(bounds[key] * 1000) / 1000])); };
  const describe = node => {
    if (!node) return { missing: true };
    const bounds = rect(node), ancestors = [];
    for (let current = node, depth = 0; current && depth < 10; current = parent(current), depth++) {
      const style = getComputedStyle(current);
      ancestors.push({ ...label(current), rect: rect(current), hidden: current.hidden,
        aria_hidden: current.getAttribute('aria-hidden') === 'true', inert: current.hasAttribute('inert'),
        style: Object.fromEntries(['display', 'visibility', 'opacity', 'overflowX', 'overflowY'].map(key => [key, String(style[key]).slice(0, 40)])) });
    }
    const left = Math.max(0, bounds.left), top = Math.max(0, bounds.top), right = Math.min(innerWidth, bounds.right), bottom = Math.min(innerHeight, bounds.bottom);
    const points = [[(left + right) / 2, (top + bottom) / 2], [left + .5, top + .5], [right - .5, top + .5], [left + .5, bottom - .5], [right - .5, bottom - .5]];
    const hits = points.map(([x, y]) => {
      let hit = document.elementFromPoint(x, y); const chain = [label(hit)];
      for (let depth = 0; hit?.shadowRoot?.elementFromPoint && depth < 6; depth++) {
        const next = hit.shadowRoot.elementFromPoint(x, y); chain.push(label(next));
        if (!next || next === hit) break; hit = next;
      }
      return { x, y, chain, contained: hit === node || node.contains(hit) };
    });
    return { visible: LearnNoteCommunityDOM.visible(node, window), rect: bounds, ancestors, hits };
  };
  const captured = result.items.slice(0, 20);
  const candidates = expected.map(([id, selector, text]) => {
    const node = selector ? document.querySelector(selector) : document.querySelector('#shadowComment')?.shadowRoot?.querySelector('bili-rich-text')?.shadowRoot?.querySelector('#contents');
    const item = captured.find(item => item.text === text);
    return { id, accepted: Boolean(item), timestamp_seconds: Number.isFinite(item?.timestamp_seconds) ? item.timestamp_seconds : null, ...describe(node) };
  });
  const exclusions = [['hidden-parent', '.reply-item[hidden] .reply-content'], ['offscreen', '.offscreen .reply-content'],
    ['aria-hidden', '[aria-hidden="true"] .reply-content'], ['clipped', '.clipped .reply-content'],
    ['covered', '.covered .reply-content'], ['partial-viewport', '.partial .reply-content']].map(([id, selector]) => ({ id, ...describe(document.querySelector(selector)) }));
  const time = document.querySelector('.bpx-player-dm-list-time'), timed = document.querySelector('.bpx-player-dm-list-dm');
  const seconds = captured.find(item => item.text === expected[2][2])?.timestamp_seconds;
  const timestamp_element = { collected_seconds: Number.isFinite(seconds) ? seconds : null, expected_text_matches: time?.innerText?.trim() === '01:23',
    associated_with_timed_body: Boolean(time && timed?.closest?.('.bpx-player-dm-list-item')?.querySelector?.('.bpx-player-dm-list-time') === time), ...describe(time) };
  const untimed = document.querySelector('.bili-dm'), following = document.querySelector('#shadowComment');
  const separation = untimed && following ? { untimed_bottom: rect(untimed).bottom, following_top: rect(following).top, gap: rect(following).top - rect(untimed).bottom } : null;
  return { fixture: 'synthetic-community-dom-v1', viewport: { width: innerWidth, height: innerHeight }, separation, timestamp_element,
    captured_count: result.items.length, truncated: result.truncated,
    missing_expected: candidates.filter(item => !item.accepted).map(item => item.id), candidates, exclusions };
}
function assertSyntheticDOMGeometry(diagnostics) {
  assert(diagnostics.separation?.gap >= 8, 'Independent untimed-danmaku and following shadow fixture must have a measured gap');
  const untimed = diagnostics.candidates.find(item => item.id === 'untimed-danmaku');
  assert.equal(untimed?.hits.length, 5, 'Measure every existing untimed-danmaku hit-test point');
  assert(untimed.hits.every(point => point.contained), 'All five untimed-danmaku hit points must stay inside that body');
  assert.equal(untimed.visible, true, 'The separated positive body must pass the unchanged collector visibility gate');
}
function syntheticPanelDiagnostics() {
  const fixture = globalThis.__communityFixture;
  if (!fixture) return { fixture_installed: false };
  const ids = ['communityPanel', 'communityPreview', 'communityEnable', 'communitySave', 'communityCancel', 'sendButton'];
  return { fixture_installed: true, enabled: fixture.enabled, permission: fixture.permission,
    calls: fixture.calls.slice(-10).map(item => String(item.type).slice(0, 80)), saved_count: fixture.saved.length,
    pending_type: fixture.pending ? String(fixture.pending.type).slice(0, 80) : null, unsettled_actions: fixture.actions.filter(item => !item.settled).length,
    item_count: document.querySelectorAll('#communityItems input').length,
    selected_count: document.querySelectorAll('#communityItems input:checked').length,
    controls: ids.map(id => { const node = document.getElementById(id); return { id, found: Boolean(node), hidden: node?.hidden, open: node?.open, disabled: node?.disabled, busy: node?.getAttribute('aria-busy') }; }) };
}
async function captureInlineTimestampProbes({ browser, origin, out, report }) {
  let inline, primary;
  try {
    inline = await bounded(browser.newPage({ viewport: { width: 1100, height: 850 } }), 'create inline timestamp probe page', TIMEOUT);
    await inline.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
    await inline.goto(origin + '/extension/tests/fixtures/community/inline-timestamp.html');
    for (const name of ['community-source.js', 'content-community.js']) await inline.addScriptTag({ url: origin + '/extension/' + name });
    const sample = await collect(inline);
    report.inline_timestamp_ranges = await bounded(inline.evaluate(syntheticTimestampRanges, { mode: 'representative', items: sample.items }), 'representative inline timestamp ranges', TIMEOUT);
    await inline.screenshot({ path: path.join(out, 'inline-timestamp-probes.png') }); report.screenshots.push('inline-timestamp-probes.png');
    const covered = report.inline_timestamp_ranges.samples.find(item => item.id === 'covered-inline');
    assert.equal(covered.characters[4].values[0].hits[0].hit?.id, 'timestampCover', 'The negative fixture must actually cover a digit center');
    assert.equal(sample.items.find(item => item.text === 'Covered inline timestamp example.')?.timestamp_seconds, null, 'A genuinely covered digit cannot supply timestamp provenance');
    assert.equal(sample.items.find(item => item.text === 'Clear inline timestamp example.')?.timestamp_seconds, 83, 'A clear inline timestamp retains its explicit time');
    for (const label of ['Hidden', 'Offscreen', 'Partially clipped']) {
      assert.equal(sample.items.find(item => item.text === `${label} timestamp example.`)?.timestamp_seconds, null, `${label} timestamp cannot supply provenance`);
    }
  } catch (error) { primary = error; }
  finally { await cleanup(primary, [['close inline timestamp probe page', () => inline?.close()]]); }
}
async function run() {
  const { chromium } = require('playwright');
  const out = path.resolve(process.argv[2] || 'build/community-capture-ui'); fs.mkdirSync(out, { recursive: true });
  const report = { source_sha: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: ROOT, encoding: 'utf8' }).trim(), passed: false, synthetic_data: true, native_permissions_tested: false, live_platform_tested: false, model_called: false, checks: [], screenshots: [] };
  const server = http.createServer((req, res) => { const file = asset(req.url); if (!file) { res.writeHead(404); return res.end(); } res.setHeader('Content-Type', file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'text/javascript' : file.endsWith('.png') ? 'image/png' : 'text/html'); fs.createReadStream(file).pipe(res); });
  let browser, activePage, primary;
  const phase = name => { report.phase = name; };
  try {
    await bounded(new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); }), 'listen for community assets', TIMEOUT);
    browser = await chromium.launch({ channel: 'msedge', headless: true });
    const origin = `http://127.0.0.1:${server.address().port}`;
    const dom = activePage = await browser.newPage({ viewport: { width: 1100, height: 850 } });
    await dom.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
    await dom.goto(origin + '/extension/tests/fixtures/community/visible-page.html');
    for (const name of ['community-source.js', 'content-community.js']) await dom.addScriptTag({ url: origin + '/extension/' + name });
    phase('dom/initial-collection');
    const result = await collect(dom);
    report.dom_diagnostics = await bounded(dom.evaluate(syntheticDOMDiagnostics, result), 'synthetic DOM diagnostics', TIMEOUT);
    report.timestamp_ranges = await bounded(dom.evaluate(syntheticTimestampRanges, { mode: 'original', items: result.items }), 'synthetic timestamp ranges', TIMEOUT);
    // Preserve the original inline case and gather a separate truly covered digit
    // before the unchanged 83s assertion. No fixture style is used to make it pass.
    phase('dom/inline-timestamp-probes');
    await captureInlineTimestampProbes({ browser, origin, out, report });
    assertSyntheticDOMGeometry(report.dom_diagnostics);
    assert.equal(result.items.length, 5, `Expected all five fixture bodies; missing: ${report.dom_diagnostics.missing_expected.join(', ')}`);
    assert(result.items.some(item => item.text === 'Open-shadow comment body only.'));
    phase('dom/timestamp-and-privacy');
    assert(result.items.some(item => item.timestamp_seconds === 83));
    assert(result.items.some(item => item.kind === 'danmaku' && item.timestamp_seconds === null));
    assert(!JSON.stringify(result.items).match(/decoy|secret|Offscreen|Covered|Clipped|Unseen|Only this first|Like 999/));
    await dom.screenshot({ path: path.join(out, 'visible-dom.png') }); report.screenshots.push('visible-dom.png');
    phase('dom/oversize');
    await dom.evaluate(() => { document.querySelector('.reply-content').firstChild.nodeValue = 'x'.repeat(2001); });
    assert(!(await collect(dom)).items.some(item => item.text.startsWith('xxx')));
    phase('dom/traversal-limit');
    await dom.evaluate(() => { document.body.replaceChildren(); const wrapper = document.createElement('div'); for (let i = 0; i < 1600; i++) wrapper.append(document.createElement('div')); document.body.append(wrapper); });
    const limited = await collect(dom); assert.equal(limited.items.length, 0); assert.equal(limited.truncated, true);
    await dom.close(); report.checks.push('real DOM: content-only/open-shadow, hidden/offscreen/clipped/occluded rejection, explicit/unknown timestamps, oversize and traversal bounds');
    for (const locale of ['zh-CN', 'en-US']) for (const width of [390, 768]) {
      report.current_case = { locale, width }; phase('panel/setup-and-task');
      const page = activePage = await browser.newPage({ viewport: { width, height: 900 }, locale });
      const errors = []; page.on('pageerror', error => errors.push(error.message));
      const catalog = JSON.parse(fs.readFileSync(path.join(ROOT, 'extension/_locales', locale === 'en-US' ? 'en' : 'zh_CN', 'messages.json')));
      await page.addInitScript({ content: `(${installFixtures})(${JSON.stringify({ locale, catalog, fixture: FIXTURE })});(${communityFixture})();` });
      await page.goto(origin + '/extension/sidepanel.html');
      await page.evaluate(() => __localeFixture.connect());
      await page.waitForFunction(() => __learnnoteSidepanel.getState().clientConnected);
      await page.locator('#sendButton').click();
      await page.locator('#communityPanel').waitFor();
      phase('panel/default-disabled');
      assert.equal(await page.evaluate(() => __communityFixture.calls.length), 0, 'No automatic community read');
      await page.locator('#communityPanel > summary').click();
      assert.equal(await page.evaluate(() => __communityFixture.calls.length), 0, 'Opening disclosure is not capture');
      await page.locator('#communityPreview').click();
      await page.waitForFunction(() => !document.querySelector('#communityPanel').getAttribute('aria-busy').includes('true'));
      assert.equal(await page.locator('#communityItems input').count(), 0, 'Default disabled');
      phase('panel/enable-and-preview');
      await page.locator('#communityEnable').click();
      await page.waitForFunction(() => __communityFixture.enabled && document.querySelector('#communityPanel').getAttribute('aria-busy') === 'false');
      await page.locator('#communityPreview').click();
      await page.locator('#communityItems input').first().waitFor();
      assert.equal(await page.locator('#communityItems input:checked').count(), 0);
      assert(await page.locator('#communitySave').isDisabled());
      assert.equal(await page.locator('#communityItems img').count(), 0, 'Literal content is not HTML');
      await page.locator('#communityItems input').first().check();
      const filename = `${locale}-${width}-preview.png`;
      await page.locator('#communityPanel').screenshot({ path: path.join(out, filename) }); report.screenshots.push(filename);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      phase('panel/selected-save');
      await page.locator('#communitySave').click();
      await page.waitForFunction(() => __communityFixture.saved.length === 1);
      assert.deepEqual(await page.evaluate(() => __communityFixture.saved[0]), ['c'.repeat(32)]);
      await page.waitForFunction(() => document.querySelector('#communityPanel').getAttribute('aria-busy') === 'false');
      await page.locator('#communityPreview').click(); await page.locator('#communityItems input').first().waitFor();
      phase('panel/navigation-and-preview-cancel');
      await page.evaluate(() => __communityFixture.change());
      assert.equal(await page.locator('#communityItems input').count(), 0, 'Navigation clears preview');
      await heldAction(page, { selector: '#communityPreview', type: 'community-preview', invalidate: () => page.locator('#communityCancel').click() });
      assert.equal(await page.locator('#communityItems input').count(), 0, 'Late cancelled result is ignored');
      await page.locator('#communityPreview').click(); await page.locator('#communityItems input').first().waitFor();
      await page.locator('#communityItems input').first().check();
      phase('panel/save-navigation');
      await heldAction(page, { selector: '#communitySave', type: 'community-save', invalidate: async () => {
        await page.evaluate(() => { __communityFixture.change(); document.querySelector('#communityPanel').open = false; });
        const handle = await page.waitForFunction(() => document.querySelector('#communityStatus').textContent === LearnNoteI18n.message('community_save_uncertain'), null, { timeout: TIMEOUT });
        await handle.dispose();
      } });
      assert.equal(await page.locator('#communityItems input').count(), 0, 'Late save cannot restore stale preview');
      assert.equal(await page.locator('#communityStatus').textContent(), catalog.community_save_uncertain.message);
      await page.locator('#communityPanel > summary').click();
      await page.locator('#communityPreview').click(); await page.locator('#communityItems input').first().waitFor();
      phase('panel/escape');
      await page.locator('#communityPanel > summary').focus(); await page.keyboard.press('Escape');
      assert.equal(await page.locator('#communityPanel').evaluate(element => element.open), false);
      assert.equal(await page.evaluate(() => document.activeElement === document.querySelector('#communityPanel > summary')), true);
      await page.locator('#communityPanel > summary').click();
      await page.locator('#communityPreview').click(); await page.locator('#communityItems input').first().waitFor();
      phase('panel/revocation');
      await page.evaluate(() => __communityFixture.revoke());
      assert.equal(await page.locator('#communityItems input').count(), 0, 'Revocation clears preview');
      assert(await page.locator('#communityPanel').isHidden(), 'Existing panel clears revoked source identity');
      assert.deepEqual(errors, []); assert.deepEqual(await page.evaluate(() => __communityFixture.actions.filter(action => action.error)), []);
      assert.equal(await page.evaluate(() => Boolean(globalThis.injected)), false);
      await page.close();
    }
    report.checks.push('shipped panel: no automatic collection, disabled lane, local opt-in, unchecked selection, exact selected save, literal content, navigation/revocation/cancel races, Escape/focus, bilingual 390/768px');
    report.passed = true; phase('complete');
  } catch (error) { primary = error; report.error = String(error.stack || error); if (activePage && !activePage.isClosed()) {
    if (report.phase?.startsWith('panel/')) { try { report.panel_diagnostics = await bounded(activePage.evaluate(syntheticPanelDiagnostics), 'synthetic panel diagnostics', 3000); } catch { report.panel_diagnostics = { unavailable: true }; } }
    try { await activePage.screenshot({ path: path.join(out, 'failure.png'), timeout: 3000 }); report.screenshots.push('failure.png'); } catch {} } }
  await finishCapture({ out, report, browser, server }, primary);
  console.log(JSON.stringify(report));
}
if (require.main === module && process.argv.includes('--self-test')) {
  assert(asset('/extension/community-source.js')); assert(asset('/extension/content-community.js')); assert(asset('/extension/tests/fixtures/community/visible-page.html'));
  assert(asset('/extension/tests/fixtures/community/inline-timestamp.html'));
  assert.equal(asset('/extension/../backend/app/community.py'), null);
  new Function('return ' + communityFixture.toString());
  console.log('Community rendered fixture syntax and asset/path checks pass; actual Edge rendering is a hosted gate.');
} else if (require.main === module) run().catch(error => { console.error(error); process.exitCode = 1; });
module.exports = { communityFixture, heldAction, finishCapture, syntheticDOMDiagnostics, assertSyntheticDOMGeometry, syntheticPanelDiagnostics, captureInlineTimestampProbes };
