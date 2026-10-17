const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const { communityFixture, heldAction, finishCapture } = require('../community-capture-visual-acceptance.cjs');

function fixture(type, { arrive = true } = {}) {
  const context = vm.createContext({ console, queueMicrotask });
  vm.runInContext(`class HTMLElement {
    constructor(id) { this.id = id; this.listeners = {}; }
    addEventListener(type, handler) { this.listeners[type] = handler; }
    click() { this.listeners.click?.call(this, {}); }
  }
  globalThis.chrome = { runtime: { sendMessage: async () => ({}), onMessage: {addListener() {}} },
    permissions: { getAll: async () => ({origins:[]}) } };
  (${communityFixture})();
  __communityFixture.enabled = true;
  globalThis.button = new HTMLElement(${JSON.stringify(type === 'community-preview' ? 'communityPreview' : 'communitySave')});
  button.addEventListener('click', async () => {
    ${arrive ? `await chrome.runtime.sendMessage({ type: ${JSON.stringify(type)}, requestId: 'held-request', selectedItemIds: ['selected'] });` : ''}
    await new Promise(resolve => queueMicrotask(resolve));
    __communityFixture.uiSettled = true;
  });`, context);
  const checks = [];
  const evaluate = (fn, arg) => vm.runInContext(`(${fn})(${JSON.stringify(arg)})`, context);
  const page = {
    evaluate: async (fn, arg) => evaluate(fn, arg),
    locator: () => ({ click: async () => { vm.runInContext('button.click()', context); } }),
    async waitForFunction(fn, arg, options) {
      assert.equal(options.timeout, 15000, 'Both arrival and settlement have a bounded browser wait');
      checks.push(fn.toString());
      for (let i = 0; i < 20; i++) {
        const value = evaluate(fn, arg);
        if (value) return { jsonValue: async () => JSON.parse(JSON.stringify(value)), dispose: async () => {} };
        await Promise.resolve();
      }
      throw Error('Synthetic predicate did not become ready');
    },
  };
  return { context, page, checks };
}
for (const type of ['community-preview', 'community-save']) {
  test(`${type}: invalidate only after transport arrival, release and await actual handler settlement`, async () => {
    const { context, page, checks } = fixture(type);
    await heldAction(page, { type, selector: '#unused', invalidate: async () => {
      const state = context.__communityFixture;
      assert.equal(state.pending.type, type);
      assert.equal(state.requests[0].settled, false);
      assert.equal(state.actions[0].settled, false);
      assert.equal(state.uiSettled, undefined);
    } });
    const state = context.__communityFixture;
    assert.equal(state.hold, false); assert.equal(state.pending, null);
    assert.equal(state.requests[0].settled, true); assert.equal(state.actions[0].settled, true);
    assert.equal(state.uiSettled, true); assert.equal(checks.length, 2);
  });
}
test('Invalidation failure still releases and settles held request without replacing primary error', async () => {
  const { context, page } = fixture('community-save'), primary = Error('navigation assertion failed');
  await assert.rejects(heldAction(page, { type: 'community-save', selector: '#unused', invalidate: () => { throw primary; } }), error => error === primary);
  assert.equal(context.__communityFixture.pending, null);
  assert.equal(context.__communityFixture.actions[0].settled, true);
});
test('Missing actual arrival fails before cancellation and always releases hold', async () => {
  const { context, page } = fixture('community-preview', { arrive: false }); let invalidated = false;
  await assert.rejects(heldAction(page, { type: 'community-preview', selector: '#unused', invalidate: () => { invalidated = true; } }), /predicate did not become ready/);
  assert.equal(invalidated, false); assert.equal(context.__communityFixture.hold, false);
});

test('Primary assertion survives browser/server/report failures and every cleanup runs', async () => {
  const calls = [], primary = Error('primary assertion'), report = { passed: false };
  await assert.rejects(finishCapture({ out: 'unused', report,
    browser: { close: async () => { calls.push('browser'); throw Error('browser failed'); } },
    server: { listening: true, closeAllConnections() { calls.push('connections'); }, close(callback) { calls.push('server'); callback(Error('server failed')); } },
    write() { calls.push('report'); throw Error('report failed'); },
  }, primary), error => error === primary);
  assert.deepEqual(calls, ['browser', 'connections', 'server', 'report']);
  assert.equal(primary.message, 'primary assertion');
  assert.deepEqual(primary.cleanup_errors, ['browser close: browser failed', 'asset server close: server failed']);
  assert.equal(primary.report_write_error, 'report failed'); assert.equal(report.passed, false);
});
test('Cleanup failure after success is recorded before report, and report failure cannot replace it', async () => {
  const calls = [], report = { passed: true };
  await assert.rejects(finishCapture({ out: 'unused', report,
    browser: { close: async () => { calls.push('browser'); throw Error('close failed'); } },
    server: { listening: true, closeAllConnections() {}, close(callback) { calls.push('server'); callback(); } },
    write(_path, content) { calls.push('report'); assert.equal(JSON.parse(content).passed, false); throw Error('disk failed'); },
  }), error => error.message === 'browser close: close failed' && error.report_write_error === 'disk failed');
  assert.deepEqual(calls, ['browser', 'server', 'report']);
});
test('Connection cleanup failure still attempts server close and report', async () => {
  const calls = [], report = { passed: true };
  await assert.rejects(finishCapture({ out: 'unused', report,
    server: { listening: true, closeAllConnections() { calls.push('connections'); throw Error('connections failed'); }, close(callback) { calls.push('server'); callback(); } },
    write() { calls.push('report'); },
  }), /asset connections close: connections failed/);
  assert.deepEqual(calls, ['connections', 'server', 'report']);
});
test('Report-only failure is not hidden after successful browser/server cleanup', async () => {
  const calls = [], primary = Error('disk failed');
  await assert.rejects(finishCapture({ out: 'unused', report: { passed: true },
    browser: { close: async () => calls.push('browser') },
    server: { listening: true, closeAllConnections() {}, close(callback) { calls.push('server'); callback(); } },
    write() { calls.push('report'); throw primary; },
  }), error => error === primary);
  assert.deepEqual(calls, ['browser', 'server', 'report']);
});
test('All sidepanel IDs exist; generated inputs and hidden-state ordering match shipped component', () => {
  const root = path.resolve(__dirname, '../..');
  const source = fs.readFileSync(path.join(root, 'scripts/community-capture-visual-acceptance.cjs'), 'utf8');
  const html = fs.readFileSync(path.join(root, 'extension/sidepanel.html'), 'utf8');
  const component = fs.readFileSync(path.join(root, 'extension/sidepanel-community.js'), 'utf8');
  const ids = [...source.matchAll(/#(community[A-Za-z]+|sendButton)/g)].map(match => match[1]);
  for (const id of new Set(ids)) assert(html.includes(`id="${id}"`), `Missing shipped selector #${id}`);
  assert.match(html, /<details id="communityPanel"[^>]*hidden>\s*<summary/);
  assert(component.includes('checkbox.type = "checkbox"') && component.includes('checkbox.checked = false'));
  assert(component.includes('panel.hidden = !ready'));
  assert(source.indexOf("keyboard.press('Escape')") < source.lastIndexOf('__communityFixture.revoke()'));
  assert(!source.includes('waitForTimeout('), 'No fixed sleep can stand in for race settlement');
});

test('Synthetic DOM diagnostics identify the missing body and cap geometry without page text', () => {
  const { syntheticDOMDiagnostics } = require('../community-capture-visual-acceptance.cjs');
  const node = { tagName: 'SPAN', id: 'synthetic', hidden: false,
    getBoundingClientRect: () => ({left: 20, top: 60, right: 220, bottom: 84, width: 200, height: 24}),
    getAttribute: () => null, hasAttribute: () => false, contains: () => true, innerText: '01:23',
    get textContent() { throw Error('Diagnostics must not read page text'); },
  };
  node.closest = () => ({querySelector: () => node});
  node.parentElement = node; // A hostile cycle cannot make diagnostics unbounded.
  node.shadowRoot = {querySelector: () => node, elementFromPoint: () => node};
  const context = vm.createContext({document: {title: 'Synthetic Bilibili-shaped visible DOM fixture', querySelector: () => node, elementFromPoint: () => node},
    window: {}, innerWidth: 1100, innerHeight: 850,
    getComputedStyle: () => ({display: 'inline-block', visibility: 'visible', opacity: '1', overflowX: 'visible', overflowY: 'visible'}),
    LearnNoteCommunityDOM: {visible: () => true},
  });
  const result = {items: [
    {text: 'Why does this example use a smaller batch?'},
    {text: 'This explanation helped me compare the examples.'},
    {text: 'Could we revisit this step?', timestamp_seconds: 83},
    {text: 'Rendered overlay without an asserted timestamp'},
  ], truncated: false};
  const diagnostic = JSON.parse(JSON.stringify(vm.runInContext(`(${syntheticDOMDiagnostics})(${JSON.stringify(result)})`, context)));
  assert.deepEqual(diagnostic.missing_expected, ['open-shadow-comment']);
  assert.equal(diagnostic.timestamp_element.expected_text_matches, true);
  assert.equal(diagnostic.timestamp_element.associated_with_timed_body, true);
  assert.equal(diagnostic.timestamp_element.collected_seconds, 83);
  assert.equal(diagnostic.timestamp_element.visible, true);
  assert.equal(diagnostic.timestamp_element.hits.length, 5);
  assert.equal(diagnostic.captured_count, 4); assert.equal(diagnostic.candidates.length, 5); assert.equal(diagnostic.exclusions.length, 6);
  for (const candidate of [...diagnostic.candidates, ...diagnostic.exclusions]) {
    assert.equal(candidate.ancestors.length, 10); assert.equal(candidate.hits.length, 5);
    assert(candidate.hits.every(point => point.chain.length <= 7));
  }
  assert(!JSON.stringify(diagnostic).includes('Why does this example'));
  assert(JSON.stringify(diagnostic).length < 50000);
  context.document.title = 'A real page';
  assert.throws(() => vm.runInContext(`(${syntheticDOMDiagnostics})(${JSON.stringify(result)})`, context), /named synthetic DOM fixture/);
});

test('The hosted collector records diagnostics before retaining the five-body assertion', () => {
  const source = fs.readFileSync(path.join(__dirname, '../community-capture-visual-acceptance.cjs'), 'utf8');
  const diagnostic = source.indexOf('report.dom_diagnostics = await bounded(dom.evaluate(syntheticDOMDiagnostics, result)');
  const assertion = source.indexOf('assert.equal(result.items.length, 5,');
  assert(diagnostic >= 0 && assertion > diagnostic);
  assert(source.includes("'synthetic DOM diagnostics', TIMEOUT"));
});

test('Measured geometry rejects the actual Edge overlap and requires five contained hit points', () => {
  const { assertSyntheticDOMGeometry } = require('../community-capture-visual-acceptance.cjs');
  // Minimized trace from exact e02dd55 / UI run 38987429130. The bottom-left
  // sample hit BILI-COMMENT-RENDERER#shadowComment then its author DIV.
  const original = {separation: {untimed_bottom: 274, following_top: 274, gap: 0}, candidates: [
    {id: 'untimed-danmaku', visible: false, hits: [
      {x: 193.867, y: 262, contained: true}, {x: 20.5, y: 250.5, contained: true},
      {x: 367.234, y: 250.5, contained: true}, {x: 20.5, y: 273.5, contained: false},
      {x: 367.234, y: 273.5, contained: true},
    ]},
  ]};
  assert.throws(() => assertSyntheticDOMGeometry(original), /measured gap/);
  const spaced = structuredClone(original); spaced.separation = {untimed_bottom: 274, following_top: 286, gap: 12};
  assert.throws(() => assertSyntheticDOMGeometry(spaced), /five.*hit points/);
  spaced.candidates[0].hits[3].contained = true;
  assert.throws(() => assertSyntheticDOMGeometry(spaced), /unchanged collector visibility/);
  spaced.candidates[0].visible = true;
  assert.doesNotThrow(() => assertSyntheticDOMGeometry(spaced));
  spaced.candidates[0].hits.pop();
  assert.throws(() => assertSyntheticDOMGeometry(spaced), /every existing.*hit-test point/);
  const html = fs.readFileSync(path.join(__dirname, '../../extension/tests/fixtures/community/visible-page.html'), 'utf8');
  assert.match(html, /bili-comment-renderer\{[^}]*margin-top:12px/);
  const source = fs.readFileSync(path.join(__dirname, '../community-capture-visual-acceptance.cjs'), 'utf8');
  assert(source.includes('assertSyntheticDOMGeometry(report.dom_diagnostics);'));
  assert(source.includes('assert.equal(result.items.length, 5,'));
});

test('Unchanged collector rejects the reported shadow hit and accepts clear separated samples', () => {
  const collector = {};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../extension/content-community.js'), 'utf8'), collector);
  const box = {left: 20, top: 250, right: 367.734, bottom: 274, width: 347.734, height: 24};
  const node = {hidden: false, parentElement: null, getRootNode: () => ({}),
    getBoundingClientRect: () => box, getAttribute: () => null, hasAttribute: () => false,
    matches: () => false, contains: hit => hit === node};
  const author = {}, host = {shadowRoot: {elementFromPoint: () => author}};
  let followingTop = 274;
  const view = {innerWidth: 1100, innerHeight: 850,
    getComputedStyle: () => ({display: 'inline-block', visibility: 'visible', opacity: '1', overflowX: 'visible', overflowY: 'visible'}),
    document: {elementFromPoint: (x, y) => x < 175 && y >= followingTop - .5 ? host : node},
  };
  assert.equal(collector.LearnNoteCommunityDOM.visible(node, view), false);
  followingTop = 286;
  assert.equal(collector.LearnNoteCommunityDOM.visible(node, view), true);
});

test('Remaining panel phases use shipped selectors and bounded state-only failure diagnostics', () => {
  const { syntheticPanelDiagnostics } = require('../community-capture-visual-acceptance.cjs');
  const html = fs.readFileSync(path.join(__dirname, '../../extension/sidepanel.html'), 'utf8');
  const source = fs.readFileSync(path.join(__dirname, '../community-capture-visual-acceptance.cjs'), 'utf8');
  const phases = ['setup-and-task', 'default-disabled', 'enable-and-preview', 'selected-save',
    'navigation-and-preview-cancel', 'save-navigation', 'escape', 'revocation'];
  for (const phase of phases) assert(source.includes(`phase('panel/${phase}')`));
  const seen = [];
  const context = vm.createContext({document: {
    getElementById(id) { seen.push(id); assert(html.includes(`id="${id}"`)); return {hidden: false, open: true, disabled: false, getAttribute: () => 'false', get textContent() {throw Error('Do not report content');}}; },
    querySelectorAll(selector) { assert(['#communityItems input', '#communityItems input:checked'].includes(selector)); return {length: 2}; },
  }, __communityFixture: {enabled: true, permission: true, calls: Array.from({length: 30}, () => ({type: 'community-preview', pageUrl: 'secret source', text: 'private body'})),
    saved: [['private selected id']], pending: {type: 'community-preview', requestId: 'private request'}, actions: [{settled: false}, {settled: true}]}});
  const diagnostic = JSON.parse(JSON.stringify(vm.runInContext(`(${syntheticPanelDiagnostics})()`, context)));
  assert.equal(diagnostic.calls.length, 10); assert.equal(diagnostic.controls.length, 6);
  assert.equal(diagnostic.saved_count, 1); assert.equal(diagnostic.unsettled_actions, 1);
  assert.equal(diagnostic.pending_type, 'community-preview');
  assert(!JSON.stringify(diagnostic).match(/secret|private/));
  assert.deepEqual(seen, ['communityPanel', 'communityPreview', 'communityEnable', 'communitySave', 'communityCancel', 'sendButton']);
  assert(source.includes("'synthetic panel diagnostics', 3000"));
  assert(!source.includes('waitForTimeout('));
});
