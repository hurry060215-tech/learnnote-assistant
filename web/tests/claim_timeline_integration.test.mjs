// Real production functions with synthetic DOM/HTTP timing; no browser claim.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
test('source-review clones, cancelled navigation and changed task attempts retain binding', async t => {
const previousDocument = globalThis.document;
t.after(() => { globalThis.document = previousDocument; });
const load = async file => import('data:text/javascript;base64,' + Buffer.from(readFileSync(new URL('../../' + file, import.meta.url), 'utf8')).toString('base64'));
const { collapseSourceReviews } = await load('web/source-review.js');
const { claimNoteTarget, claimMapVersion } = await load('web/claim-timeline.js');
class Element {
  constructor(tag, text = '') {
    this.tagName = tag.toUpperCase(); this.nodeType = tag === '#text' ? 3 : 1;
    this.value = text; this.children = []; this.dataset = {};
  }
  get textContent() { return this.value + this.children.map(node => node.textContent).join(''); }
  set textContent(value) { this.value = value; this.children = []; }
  append(...nodes) { for (const node of nodes) { node.parentElement = this; this.children.push(node); } }
  matches(selector) {
    return selector.split(',').some(value => value === '[data-source-reviews]' ? 'sourceReviews' in this.dataset
      : value === '[data-note-start][data-note-end]' ? 'noteStart' in this.dataset && 'noteEnd' in this.dataset
        : value.toUpperCase() === this.tagName);
  }
  closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector); }
  querySelectorAll(selector) { return this.children.flatMap(node => [...(node.matches(selector) ? [node] : []), ...node.querySelectorAll(selector)]); }
  get nextSibling() { return this.parentElement?.children[this.parentElement.children.indexOf(this) + 1]; }
  cloneNode(deep) {
    const copy = new Element(this.tagName, this.value); copy.dataset = { ...this.dataset };
    if (deep) copy.append(...this.children.map(node => node.cloneNode(true)));
    return copy;
  }
  replaceWith(node) {
    const parent = this.parentElement; parent.children[parent.children.indexOf(this)] = node;
    node.parentElement = parent; this.parentElement = null;
  }
  setAttribute(key, value) { this[key] = value; }
}
globalThis.document = { createElement: tag => new Element(tag) };
for (const continuation of [false, true]) {
  const root = new Element('main'), list = new Element('ul'), parent = new Element('li');
  const child = new Element(continuation ? 'p' : 'li', 'Child claim.');
  parent.dataset = { noteStart: '0', noteEnd: '60' };
  child.dataset = { noteStart: '61', noteEnd: '77' };
  parent.append(new Element('strong', '【待核对：仅定位到来源】'), new Element('#text', ' Parent claim.'));
  if (continuation) parent.append(child);
  else { const nested = new Element('ul'); nested.append(child); parent.append(nested); }
  list.append(parent); root.append(list);
  const claim = { source_span: { start: 65, end: 77 } };
  const before = claimNoteTarget(root, claim) === child;
  collapseSourceReviews(root);
  assert(before);
  assert.equal(root.querySelectorAll('[data-note-start][data-note-end]').filter(node => Number(node.dataset.noteStart) <= 65 && Number(node.dataset.noteEnd) >= 77).length, 2, 'fixture preserves a cloned source excerpt');
  assert.equal(claimNoteTarget(root, claim), child, continuation ? 'original continuation paragraph' : 'original nested list item');
}
const desk = readFileSync(new URL('../desk.js', import.meta.url), 'utf8');
async function cancellationProbe(close) {
  const calls = [], nodes = new Map();
  const $ = id => {
    if (!nodes.has(id)) nodes.set(id, { hidden: false, dataset: {}, textContent: '', classList: { remove() {} },
      setAttribute() {}, replaceChildren() {}, removeAttribute() {}, pause() {} });
    return nodes.get(id);
  };
  const one = { kind: 'task', id: 'one' }, two = { kind: 'task', id: 'two', media_path: 'synthetic.wav' };
  let finishEdition;
  const context = vm.createContext({ $, state: { epoch: 1, selected: one, items: [one, two], editing: false }, guard: () => true,
    window: { dispatchEvent() {} }, Event: class {}, CustomEvent: class {},
    document: { body: { classList: { remove() {} } } }, history: { replaceState() {} },
    claimTimeline: { reset() {}, clearActive() {} }, personalAnchorPicker: { reset() {} },
    api: async () => ({}), drawList() {}, renderStatus() {},
    loadEdition: () => new Promise(resolve => finishEdition = resolve), loadAnnotations: async () => {},
    openSource: async seconds => { $('sourcePanel').hidden = false; calls.push(['openSource', seconds]); },
    localPlayer: {cancelSeek() {}}, sourceCueCleanup: null, sourceCueRender: null, sourceWindowRender: null,
  });
  vm.runInContext('let sourceRequest = 0, editionRequest = 0;'
    + desk.slice(desk.indexOf('function readerSnapshotSource('), desk.indexOf('async function adoptSelectedSnapshot(')) + desk.slice(desk.indexOf('function closeSource('), desk.indexOf('let inlineSourceRequest'))
    + desk.slice(desk.indexOf('async function openItem('), desk.indexOf('let editionRequest'))
    + desk.slice(desk.indexOf('let evidenceRequest = 0;'), desk.indexOf('async function drawReview()')), context);
  const pending = context.openEvidenceSource(two, 10);
  if (close) context.closeSource();
  else await context.openEvidenceSource(two, 20);
  const before = { hidden: $('sourcePanel').hidden, calls: [...calls] };
  finishEdition(); await pending;
  assert.equal($('sourcePanel').hidden, close, 'cancelled load cannot reopen the panel');
  assert.deepEqual(calls, close ? [] : [['openSource', 20]], 'older load cannot overtake a newer seek');
  assert.deepEqual(calls, before.calls);
}
await cancellationProbe(true);
await cancellationProbe(false);

// A newly persisted evidence map may change while the note bytes stay identical.
const { renderEditionStable } = await load('web/reader-progress.js');
const revision = 'a'.repeat(64), note = 'Repeated same note.';
const selected = { kind: 'task', id: 'synthetic', updated_at: 'new-generation', summary_source: 'llm', status: 'success', claim_evidence: { path: 'claim_evidence_map.json' } };
const editionNodes = new Map([
  ['document', { dataset: { readerSource: 'task:synthetic', readerRevision: `${revision}:llm:` }, querySelector: () => null, querySelectorAll: () => [] }],
  ['annotations', { dataset: {} }],
]);
let renderCalls = 0, timelineCalls = 0;
const editionContext = vm.createContext({ claimMapVersion, state: { selected, epoch: 3, text: note, revision, editing: false }, $: id => editionNodes.get(id),
  api: async () => ({ text: note, revision }), sourcePath: () => '/synthetic/edition', LearnNoteMarkdown: { configure() {} },
  taskAsset: value => value, sectionReader: { retainableSnapshot: () => false, render: () => false }, renderEditionStable,
  document: { scrollingElement: { scrollTop: 0 } }, renderNote: () => { renderCalls++; timelineCalls++; },
  loadClaimTimeline: () => timelineCalls++,
});
vm.runInContext('let editionRequest = 0;' + desk.slice(desk.indexOf('async function loadEdition('), desk.indexOf('function renderNote()')), editionContext);
await editionContext.loadEdition(3);
assert.equal(renderCalls, 0, 'unchanged text preserves DOM and scroll');
assert.equal(timelineCalls, 1, 'new task state refreshes evidence independently');

// Execute the real desk timeline wiring with a delayed previous-generation map.
const { createHash } = await import('node:crypto');
const { createClaimTimeline } = await load('web/claim-timeline.js');
Element.prototype.replaceChildren = function (...nodes) { for (const node of this.children) node.parentElement = null; this.children = []; this.append(...nodes); };
Element.prototype.remove = function () {
  if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(node => node !== this);
  this.parentElement = null;
};
Element.prototype.removeAttribute = function (key) { delete this[key]; };
Element.prototype.contains = function (node) { return node === this || this.children.some(child => child.contains(node)); };
Element.prototype.getBoundingClientRect = () => ({ top: 0, bottom: 20 });
Element.prototype.getClientRects = () => [1];
Element.prototype.scrollIntoView = () => {};
const makeElement = (tag, text = '') => {
  const node = new Element(tag, text);
  node.classList = { add() {}, remove() {}, toggle() {} };
  return node;
};
const delayedNote = 'Synthetic exact claim.', delayedRevision = createHash('sha256').update(delayedNote).digest('hex');
const delayedMap = { schema_version: 7, task_id: 'same-task', source_revision_kind: 'normalized_note_utf8_sha256', source_revision: delayedRevision,
  evidence: [{ evidence_id: 'old-source', kind: 'transcript', start: 1, end: 2 }],
  claims: [{ claim_id: 'same-claim', text: delayedNote, source_span: { unit: 'unicode_codepoints', start: 0, end: delayedNote.length },
    evidence_ids: ['old-source'], candidate_evidence_ids: [], verification: 'direct' }],
};
const delayedNodes = new Map(), delayedDocument = {
  createElement: tag => makeElement(tag), createTextNode: value => makeElement('#text', value),
  activeElement: null, documentElement: { clientHeight: 800 }, getSelection: () => null,
};
const getNode = id => { if (!delayedNodes.has(id)) delayedNodes.set(id, makeElement('div')); return delayedNodes.get(id); };
const bodyBlock = makeElement('p', delayedNote); bodyBlock.dataset = { noteStart: '0', noteEnd: String(delayedNote.length) }; getNode('document').append(bodyBlock);
getNode('sourceContent').before = node => delayedNodes.set(node.id, node);
let returnOldMap;
const delayedState = { selected: { kind: 'task', id: 'same-task', updated_at: 'old', control_generation: 'old-generation', claim_evidence: { path: 'claim_evidence_map.json' } },
  epoch: 7, text: delayedNote, revision: delayedRevision, editing: false,
};
const delayedContext = vm.createContext({ claimMapVersion, state: delayedState, $: getNode, document: delayedDocument,
  createClaimTimeline: options => createClaimTimeline({ ...options, document: delayedDocument }), timestamp: String,
  api: () => new Promise(resolve => returnOldMap = resolve), openClaimEvidence: async () => {}, failure: error => { throw error; },
});
vm.runInContext(desk.slice(desk.indexOf('const claimContainer ='), desk.indexOf('const presets =')), delayedContext);
for (const change of [{ updated_at: 'published-map' }, { control_generation: 'new-attempt' }, { control_retry_count: 2 }]) {
  const pendingMap = delayedContext.loadClaimTimeline();
  delayedState.selected = { ...delayedState.selected, ...change };
  returnOldMap(delayedMap); await pendingMap;
  assert.equal(bodyBlock.children.length, 0, 'late old map rejected after ' + Object.keys(change)[0]);
}
});
