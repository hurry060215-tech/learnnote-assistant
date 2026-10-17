// State contracts; rendered geometry is separately exercised by hosted Edge.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
class Element {
  constructor(tag = 'div') { this.tagName = tag; this.children = []; this.events = {}; this.hidden = false; this.open = true; this.checked = false; this.textContent = ''; this.attributes = {}; }
  addEventListener(name, callback) { this.events[name] = callback; }
  setAttribute(name, value) { this.attributes[name] = value; }
  append(...children) { this.children.push(...children); }
  replaceChildren() { this.children = []; }
  querySelectorAll(selector) { return this.children.flatMap(child => [...(child.tagName === 'input' && (selector !== 'input:checked' || child.checked) ? [child] : []), ...child.querySelectorAll(selector)]); }
  querySelector() { return this.summary; }
  focus() { this.focused = true; }
}
const ids = Object.fromEntries(['communityPanel', 'communityStatus', 'communityItems', 'communityPreview', 'communitySave', 'communityEnable', 'communityCancel', 'communityDestination'].map(id => [id, new Element()]));
ids.communityPanel.summary = new Element('summary');
const document = { querySelector: selector => ids[selector.slice(1)], createElement: tag => new Element(tag) };
const calls = [], listeners = [];
let state = { currentTaskId: 'task1', backendUrl: 'http://127.0.0.1:8765', displayedIdentity: { tab_id: 7, canonical_page_url: 'https://www.bilibili.com/video/BV1234567890?p=2' }, sitePermissionEpoch: 0 };
let release, held = false, failType = '';
const preview = { preview_id: 'a'.repeat(64), fingerprint: 'b'.repeat(64), items: [{ item_id: 'c'.repeat(32), kind: 'comment', timestamp_seconds: null, text: '<img src=x> Literal text' }] };
const chrome = { runtime: { onMessage: { addListener: fn => listeners.push(fn) }, sendMessage: async message => {
  calls.push(message);
  if (message.type === 'community-cancel') return { ok: true };
  if (message.type === failType) return { error: 'community_request_failed' };
  if (held) await new Promise(resolve => { release = resolve; });
  if (message.type === 'community-preview') return structuredClone(preview);
  return { stored_count: 1 };
} } };
const context = vm.createContext({ console, URL, chrome });
for (const name of ['community-source.js', 'sidepanel-community.js']) vm.runInContext(fs.readFileSync(new URL('../' + name, import.meta.url), 'utf8'), context);
const panel = context.LearnNoteCommunityPanel.mount({ document, chrome, state: () => state, text: key => key, now: () => 1 });
assert.equal(calls.length, 0, 'Mount and disclosure opening do not collect');
ids.communityPanel.events.toggle(); assert.equal(calls.length, 0);
await panel.run('preview');
const inputs = ids.communityItems.querySelectorAll('input');
assert.equal(inputs.length, 1); assert.equal(inputs[0].checked, false); assert.equal(ids.communitySave.disabled, true);
assert.equal(ids.communityItems.children[0].children[1].children[1].textContent, '<img src=x> Literal text');
inputs[0].checked = true; ids.communityItems.events.change(); assert.equal(ids.communitySave.disabled, false);
await panel.run('save');
const saved = calls.find(call => call.type === 'community-save');
assert.deepEqual(Array.from(saved.selectedItemIds), ['c'.repeat(32)]); assert.equal(saved.text, undefined); assert.equal(saved.items, undefined);
assert.equal(ids.communityItems.children.length, 0);
await panel.run('preview');
state = { ...state, displayedIdentity: { ...state.displayedIdentity, canonical_page_url: state.displayedIdentity.canonical_page_url.replace('p=2', 'p=3') } }; panel.sync();
assert.equal(ids.communityItems.children.length, 0); assert.equal(ids.communityStatus.textContent, 'community_source_changed');
held = true; const pending = panel.run('preview');
ids.communityCancel.events.click(); release(); await pending; held = false;
assert.equal(ids.communityItems.children.length, 0, 'Late cancelled preview is ignored');
await panel.run('preview'); ids.communityItems.querySelectorAll('input')[0].checked = true;
held = true; const saving = panel.run('save');
state = { ...state, currentTaskId: 'task2' }; panel.sync();
assert.equal(ids.communityStatus.textContent, 'community_save_uncertain', 'Source change cannot promise that an in-flight save was cancelled');
ids.communityPanel.open = false; ids.communityPanel.events.toggle();
assert.equal(ids.communityStatus.textContent, 'community_save_uncertain', 'Closing disclosure preserves uncertainty');
release(); await saving; held = false;
assert.equal(ids.communityStatus.textContent, 'community_save_uncertain');
ids.communityPanel.open = true; await panel.run('preview');
listeners[0]({ type: 'site-permission-revoked' });
assert.equal(ids.communityItems.children.length, 0);
ids.communityPanel.events.keydown({ key: 'Escape', preventDefault() {} });
assert.equal(ids.communityPanel.open, false); assert.equal(ids.communityPanel.summary.focused, true);
assert(!calls.some(call => /model|scroll|permission-request/.test(call.type)));
ids.communityPanel.open = true;
await panel.run('preview'); ids.communityItems.querySelectorAll('input')[0].checked = true;
failType = 'community-save'; await panel.run('save'); failType = '';
assert.equal(ids.communityStatus.textContent, 'community_save_uncertain');
ids.communityPanel.open = false; ids.communityPanel.events.toggle();
assert.equal(ids.communityStatus.textContent, 'community_save_uncertain', 'Failed Save uncertainty survives close');
ids.communityPanel.open = true; ids.communityPanel.events.toggle();
assert.equal(ids.communityStatus.textContent, 'community_save_uncertain', 'Failed Save uncertainty survives reopen');
state = { ...state, currentTaskId: 'task3' }; panel.sync();
assert.equal(ids.communityStatus.textContent, 'community_save_uncertain', 'Failed Save uncertainty survives navigation');
await panel.run('preview');
assert.equal(ids.communityStatus.textContent, 'community_review', 'An explicit fresh action resets prior uncertainty');
for (const backendUrl of ['http://user:secret@127.0.0.1:8765', 'http://127.0.0.1:8765/?token=secret', 'https://external.example/secret']) {
  state = { ...state, backendUrl }; panel.sync();
  assert.equal(ids.communityDestination.textContent, 'community_invalid_destination');
  assert(!ids.communityStatus.textContent.includes('secret'));
}
console.log('Community panel opt-in, selection, literal text, stale identity, cancel/revoke and uncertain-save contracts passed.');
