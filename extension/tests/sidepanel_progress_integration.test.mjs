import assert from 'node:assert/strict';
import { createSidepanelHarness, videoContext } from './sidepanel_test_harness.mjs';

const captions = videoContext();
captions.page.browser_subtitles = Array.from({ length: 12 }, (_, i) => ({ start: i * 55, end: i * 55 + 50, text: `Literal subtitle ${i}` }));
const switched = videoContext({ bvid: 'BV9SWITCHED99' });
for (const initial of [captions, videoContext({ subtitle: false })]) {
  const h = await createSidepanelHarness({ contexts: [initial, initial, switched], startDelayMs: 60 });
  const sending = h.api.sendToClient();
  while (!h.sentMessages.some(message => message.type === 'start-current-task')) await new Promise(resolve => setTimeout(resolve, 1));
  await h.api.collectContext(true);
  assert.equal(await sending, false, 'late creation confirmation cannot select a task for a different source');
  assert.equal(h.api.getState().currentTaskId, '');
  assert.equal(h.elements.get('#progressiveCard').hidden, true);
  assert.equal(h.fetchCalls.some(call => call.url.includes('/api/tasks/')), false);
}

const live = { service: 'learnnote', app_version: 'fixture', backend_version: 'fixture', protocol_version: 1 };
const healthByUrl = { 'http://127.0.0.1:8765/health': live };
const h = await createSidepanelHarness({ contexts: [captions], startDelayMs: 60, healthByUrl, tabs: [{ id: 9, url: 'http://127.0.0.1:18898/' }] });
const sending = h.api.sendToClient();
while (!h.sentMessages.some(message => message.type === 'start-current-task')) await new Promise(resolve => setTimeout(resolve, 1));
delete healthByUrl['http://127.0.0.1:8765/health']; healthByUrl['http://127.0.0.1:18898/health'] = live;
await h.api.checkClient(); assert.equal(h.api.getState().backendUrl, 'http://127.0.0.1:18898');
assert.equal(await sending, false, 'creation on the original backend cannot read its task on a newly discovered backend');
assert.equal(h.api.getState().currentTaskId, '');
assert.equal(h.fetchCalls.some(call => call.url.includes('/api/tasks/')), false);
console.log('Late subtitle/video task creation cannot rebind progressive reading after source or backend switches');

for (const status of ['failed', 'cancelled']) {
  const h = await createSidepanelHarness({ contexts: [captions], fetchOverride: async url => {
    if (/\/api\/tasks\/[^/]+$/.test(url)) return { ok: true, json: async () => ({ task: { id: 'abc123def456', status } }) };
    if (url.endsWith('/transcript')) return { ok: true, json: async () => ({ segments: [{ start: 1, end: 2, text: '<img src=x> 原始字幕' }] }) };
    return null;
  } });
  await h.api.sendToClient(); await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(h.fetchCalls.filter(call => call.url.endsWith('/transcript')).length, 1);
  assert.match(h.elements.get('#quickTranscriptPanel').innerHTML, /&lt;img src=x&gt; 原始字幕/);
  assert.equal(h.fetchCalls.some(call => call.url.endsWith('/partial-note')), false);
}
let finishTranscript;
const late = await createSidepanelHarness({ contexts: [captions, captions, switched], fetchOverride: async url => {
  if (/\/api\/tasks\/[^/]+$/.test(url)) return { ok: true, json: async () => ({ task: { id: 'abc123def456', status: 'failed' } }) };
  if (url.endsWith('/transcript')) return new Promise(resolve => { finishTranscript = resolve; });
  return null;
} });
await late.api.sendToClient();
while (!finishTranscript) await new Promise(resolve => setTimeout(resolve, 1));
const terminalRead = late.fetchCalls.find(call => call.url.endsWith('/transcript'));
await late.api.collectContext(true); assert(terminalRead.options.signal.aborted);
finishTranscript({ ok: true, json: async () => ({ segments: [{ start: 0, end: 1, text: 'Wrong source' }] }) });
await new Promise(resolve => setTimeout(resolve, 20));
assert.doesNotMatch(late.elements.get('#quickTranscriptPanel').innerHTML, /Wrong source/);
console.log('Initial failed/cancelled tasks recover existing escaped subtitles once; source switches abort and discard late recovery');
