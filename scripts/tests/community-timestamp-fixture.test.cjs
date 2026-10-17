// API doubles verify bounded diagnostic contracts, not native rendering.
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const { syntheticTimestampRanges } = require('../community-timestamp-fixture.cjs');
const { captureInlineTimestampProbes } = require('../community-capture-visual-acceptance.cjs');
function harness({ mode = 'original', exact = true, manyRects = false } = {}) {
  const rectangle = (left, right) => ({ left, right, top: 217, bottom: 234, width: right - left, height: 17 });
  const parent = { nodeType: 1, tagName: 'SECTION', id: '', hidden: false, parentElement: null,
    getAttribute: () => null, hasAttribute: () => false, getBoundingClientRect: () => rectangle(20, 1080) };
  const node = { nodeType: 1, tagName: 'SPAN', id: '', hidden: false, parentElement: parent,
    getAttribute: () => null, hasAttribute: () => false, getBoundingClientRect: () => rectangle(20, 60.046875),
    getClientRects: () => [rectangle(20, 60.046875)], closest: () => ({ querySelector: () => ({}) }),
    contains: hit => hit === node, get textContent() { throw Error('Never dump element text'); } };
  const text = { nodeType: 3, parentElement: node, data: exact ? '01:23' : 'unrelated private text' };
  node.childNodes = [text]; node.firstChild = text;
  const calls = [], ranges = [];
  const context = vm.createContext({ document: {
    title: mode === 'original' ? 'Synthetic Bilibili-shaped visible DOM fixture' : 'Synthetic inline timestamp geometry fixture',
    querySelector: selector => selector === '#timestampCover' ? null : node,
    elementFromPoint: x => x > 59 ? parent : node, elementsFromPoint: x => x > 59 ? [parent] : [node, parent],
    createRange() {
      calls.push('range'); let start = 0, end = 5;
      return { setStart(n, offset) { assert.equal(n, text); start = offset; }, setEnd(n, offset) { assert.equal(n, text); end = offset; },
        getClientRects() { ranges.push([start, end]); const box = rectangle(20 + 8 * start, 20 + 8 * end);
          return manyRects ? { length: 100, 0: box, 1: box, 2: box, 3: box, get 4() { throw Error('No unbounded native rect read'); } } : [box]; } };
    },
  }, getComputedStyle: () => ({ display: 'inline', fontFamily: 'fixture-font', fontSize: '16px', lineHeight: '24px', opacity: '1', visibility: 'visible' }),
  devicePixelRatio: 1.25, innerWidth: 1100, innerHeight: 850, window: {}, LearnNoteCommunityDOM: { visible: () => false } });
  const run = () => JSON.parse(JSON.stringify(vm.runInContext(`(${syntheticTimestampRanges})(${JSON.stringify({mode, items: [{text: 'Could we revisit this step?', timestamp_seconds: null}]})})`, context)));
  return { run, context, calls, ranges, node };
}
test('original inline diagnostics retain fractional geometry, native text-node ancestry, DPR and five character ranges', () => {
  const h = harness(), report = h.run(), sample = report.samples[0];
  assert.equal(report.device_pixel_ratio, 1.25); assert.equal(sample.expected_text_matches, true);
  assert.equal(sample.direct_text_node, true); assert.equal(sample.text_parent_matches, true);
  assert.equal(sample.text_node.node_type, 3); assert.equal(sample.ancestors[0].style.display, 'inline');
  assert.equal(sample.ancestors[0].style.lineHeight, '24px'); assert.equal(sample.ancestors[0].style.fontSize, '16px');
  assert.equal(sample.element_rects.values[0].rect.right, 60.046875, 'Do not round away fractional edges');
  assert.equal(sample.element_rects.values[0].hits[2].contained, false);
  assert.equal(sample.element_rects.values[0].hits[2].hit.tag, 'SECTION');
  assert.equal(sample.element_rects.values[0].hits[2].device_x, 59.546875 * 1.25);
  assert.deepEqual(h.ranges, [[0, 5], [0, 1], [1, 2], [2, 3], [3, 4], [4, 5]]);
  assert.equal(sample.characters.length, 5); assert.equal(sample.collected_seconds, null);
  assert(!JSON.stringify(report).includes('01:23')); assert(JSON.stringify(report).length < 24000);
});
test('range capture refuses arbitrary text or another page and caps fragment/layer traversal', () => {
  const h = harness({exact: false}), report = h.run();
  assert.equal(report.samples[0].expected_text_matches, false); assert.equal(h.calls.length, 0);
  assert.equal(report.samples[0].characters, undefined); assert(!JSON.stringify(report).includes('private'));
  h.context.document.title = 'A real page'; assert.throws(h.run, /named synthetic fixture/);
  const capped = harness({manyRects: true}).run().samples[0];
  assert.equal(capped.text_rects.truncated, true); assert.equal(capped.text_rects.values.length, 4);
  assert(capped.characters.every(item => item.values.length === 4 && item.count === 100));
});
test('representative fixture preserves inline spans and uses the exact last-digit native range for its opaque cover', () => {
  const read = file => fs.readFileSync(path.join(__dirname, '../..', file), 'utf8');
  const original = read('extension/tests/fixtures/community/visible-page.html');
  const html = read('extension/tests/fixtures/community/inline-timestamp.html');
  for (const source of [original, html]) assert.doesNotMatch(source, /\.bpx-player-dm-list-time\s*\{[^}]*display\s*:/);
  assert(html.includes('id="inlineClearTime"') && html.includes('id="inlineCoveredTime"'));
  assert(html.includes('range.setStart(time.firstChild,4);range.setEnd(time.firstChild,5)'));
  assert.match(html, /#timestampCover\{[^}]*background:#000;pointer-events:auto/);
  const source = read('scripts/community-capture-visual-acceptance.cjs');
  assert(source.indexOf('report.timestamp_ranges = ') < source.indexOf('await captureInlineTimestampProbes('));
  assert(source.indexOf('await captureInlineTimestampProbes(') < source.indexOf('assert(result.items.some(item => item.timestamp_seconds === 83))'));
  assert(source.includes('assert.equal(result.items.length, 5,'));
  assert(source.includes("sample.items.find(item => item.text === 'Clear inline timestamp example.')?.timestamp_seconds, 83"));
  for (const label of ['Hidden', 'Offscreen', 'Partially clipped']) assert(html.includes(`${label} timestamp example.`));
  assert(source.includes("['Hidden', 'Offscreen', 'Partially clipped']"));
});
test('body visibility still rejects the observed inline parent-edge hit', () => {
  const context = {};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../extension/content-community.js'), 'utf8'), context);
  const box = {left: 20, right: 60.046875, top: 217, bottom: 234, width: 40.046875, height: 17};
  const node = {hidden: false, parentElement: null, getRootNode: () => ({}), getBoundingClientRect: () => box,
    getAttribute: () => null, hasAttribute: () => false, matches: () => false, contains: hit => hit === node};
  const row = {}, view = {innerWidth: 1100, innerHeight: 850,
    getComputedStyle: () => ({display: 'inline', visibility: 'visible', opacity: '1', overflowX: 'visible', overflowY: 'visible'}),
    document: {elementFromPoint: x => x > 59 ? row : node}};
  assert.equal(context.LearnNoteCommunityDOM.visible(node, view), false);
});
function collectorHarness() {
  const context = { LearnNoteCommunitySource: { canonicalPage: value => value } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../extension/content-community.js'), 'utf8'), context);
  const box = (left, right, top = 217, bottom = 234) => ({left, right, top, bottom, width: right - left, height: bottom - top});
  const element = rect => ({nodeType: 1, hidden: false, parentElement: null, children: [], childNodes: [],
    rect, style: {display: 'inline', visibility: 'visible', opacity: '1', overflowX: 'visible', overflowY: 'visible'},
    attributes: {}, getRootNode: () => ({}), getBoundingClientRect() { return this.rect; },
    getAttribute(name) { return this.attributes[name] ?? null; }, hasAttribute(name) { return name in this.attributes; },
    matches: () => false, contains(hit) { return hit === this || this.children.includes(hit); }});
  const row = element(box(20, 600, 214, 238)), time = element(box(20, 60.046875)), body = element(box(70, 300));
  row.matches = selector => selector === '.bpx-player-dm-list-item';
  row.querySelector = selector => selector === '.bpx-player-dm-list-time' ? time : null;
  row.children = [time, body]; time.parentElement = row; body.parentElement = row;
  body.matches = selector => selector === '.bpx-player-dm-list-dm'; body.closest = () => row;
  body.childNodes = [{nodeType: 3, nodeValue: 'Synthetic timed body'}]; time.innerText = '01:23';
  const calls = [], cover = element(box(51.140625, 60.046875));
  const document = { documentElement: row,
    elementFromPoint: x => x >= 70 ? body : x > 59 ? row : time,
    elementsFromPoint: (x, y) => { calls.push([x, y]); return [time, row]; } };
  const view = {document, innerWidth: 1100, innerHeight: 850, getComputedStyle: node => node.style};
  const collect = () => context.LearnNoteCommunityDOM.collect({document, view, pageUrl: 'fixture', expectedPageUrl: 'fixture'});
  return {context, collect, row, time, body, cover, view, document, calls, box};
}
test('only timestamp collection uses the first topmost hit at all five original fractional coordinates', () => {
  const h = collectorHarness();
  assert.equal(h.context.LearnNoteCommunityDOM.visible(h.time, h.view), false, 'General/body visibility stays conservative');
  assert.equal(h.collect().items[0].timestamp_seconds, 83);
  assert.deepEqual(h.calls, [[40.0234375, 225.5], [20.5, 217.5], [59.546875, 217.5], [20.5, 233.5], [59.546875, 233.5]]);
  h.document.elementsFromPoint = () => ({0: h.time, get 1() { throw Error('Do not search deeper hits'); }});
  assert.equal(h.collect().items[0].timestamp_seconds, 83);
  const child = {}; h.time.children = [child]; h.document.elementsFromPoint = () => [child, h.time];
  assert.equal(h.collect().items[0].timestamp_seconds, 83, 'An actual contained descendant may be first');
  h.document.elementFromPoint = () => h.row;
  h.document.elementsFromPoint = () => [h.body];
  assert.equal(h.collect().items.length, 0, 'A permissive list result never changes body visibility');
});
test('timestamp hit mode rejects a covered final digit, a first parent/host, empty/missing lists and never falls back', () => {
  for (const variant of ['covered-digit', 'parent', 'shadow-host', 'empty', 'missing', 'throws']) {
    const h = collectorHarness();
    if (variant === 'covered-digit') h.document.elementsFromPoint = x => x > 51 ? [h.cover, h.time] : [h.time];
    if (variant === 'parent' || variant === 'shadow-host') h.document.elementsFromPoint = () => [h.row, h.time];
    if (variant === 'shadow-host') { h.row.shadowRoot = {children: h.row.children}; h.time.parentElement = null; h.time.getRootNode = () => ({host: h.row}); }
    if (variant === 'empty') h.document.elementsFromPoint = () => [];
    if (variant === 'missing') delete h.document.elementsFromPoint;
    if (variant === 'throws') h.document.elementsFromPoint = () => { throw Error('Unavailable hit test'); };
    const result = h.collect();
    assert.equal(result.items.length, 1, `${variant}: body survives`);
    assert.equal(result.items[0].timestamp_seconds, null, variant);
  }
});
test('timestamp topmost hits cannot override hidden styles, ancestor clipping, partial viewport or absent geometry', () => {
  const variants = {
    hidden: h => { h.time.hidden = true; },
    aria: h => { h.time.attributes['aria-hidden'] = 'true'; },
    inert: h => { h.time.attributes.inert = ''; },
    display: h => { h.time.style.display = 'none'; },
    visibility: h => { h.time.style.visibility = 'hidden'; },
    collapse: h => { h.time.style.visibility = 'collapse'; },
    opacity: h => { h.time.style.opacity = '0'; },
    ancestor: h => { h.row.hidden = true; },
    clipped: h => { h.row.style.overflowX = 'hidden'; h.row.rect = h.box(21, 600, 214, 238); },
    partial: h => { h.time.rect = h.box(-1, 39.046875); },
    offscreen: h => { h.time.rect = h.box(1200, 1240.046875); },
    empty: h => { h.time.rect = h.box(20, 20); },
  };
  for (const [name, change] of Object.entries(variants)) {
    const h = collectorHarness(); change(h);
    assert.equal(h.collect().items[0]?.timestamp_seconds ?? null, null, name);
    assert.equal(h.calls.length, 0, `${name}: reject before topmost hit lookup`);
  }
});
test('probe failure retains its primary error if closing the extra page also fails', async () => {
  const primary = Error('timestamp page failed'); let closed = false;
  await assert.rejects(captureInlineTimestampProbes({ browser: {newPage: async () => ({route: async () => {},
    goto: async () => { throw primary; }, close: async () => { closed = true; throw Error('close failed'); }})},
    origin: 'http://127.0.0.1:1234', out: 'unused', report: {screenshots: []} }), error => error === primary);
  assert.equal(closed, true); assert.deepEqual(primary.cleanup_errors, ['close inline timestamp probe page: close failed']);
});
