import vm from 'node:vm';
import { readFile } from 'node:fs/promises';

export class Element {
  constructor(tag = 'div') { this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.hidden = false; this.parent = null; this.listeners = new Map(); this.scrollTop = 0; this.writes = 0; this.text = ''; }
  set textContent(value) { this.text = String(value); this.writes++; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
  append(...children) { for (const child of children) this.insertBefore(child, null); }
  insertBefore(child, before) { child.remove(); const index = before ? this.children.indexOf(before) : this.children.length; this.children.splice(index, 0, child); child.parent = this; }
  remove() { if (this.parent) this.parent.children.splice(this.parent.children.indexOf(this), 1); this.parent = null; }
  replaceChildren(...children) { for (const child of [...this.children]) child.remove(); this.text = ''; this.append(...children); }
  get isConnected() { return Boolean(this.parent) || this.root; }
  getBoundingClientRect() { const top = this.parent ? this.parent.children.indexOf(this) * 100 - this.parent.scrollTop : 0; return { top, bottom: top + 100 }; }
  addEventListener(name, fn) { this.listeners.set(name, fn); }
  removeEventListener(name, fn) { if (this.listeners.get(name) === fn) this.listeners.delete(name); }
  emit(name, event = {}) { return this.listeners.get(name)?.(event); }
}
export const section = (id, markdown = `# Section ${id}\nLiteral content`, revision = id) => ({ id, kind: 'text_chunk', revision, markdown, verified: false, status: 'evidence_pending' });
export async function flush() { for (let i = 0; i < 30; i++) await Promise.resolve(); }
export async function harness() {
  const doc = new Element(); doc.hidden = false; doc.createElement = tag => new Element(tag);
  const card = new Element(), status = new Element(), sections = new Element(), retry = new Element(); sections.root = true;
  const state = { task: { id: 'one', status: 'running', updated_at: 'v1', artifact_status: { partial_draft_available: true } },
    partial: { schema_version: 1, task_id: 'one', task_updated_at: 'v1', attempt_id: 'attempt1', status: 'draft', verified: false, source_revision: 'source1', generation_revision: 'generation1', revision: 'r1', sections: [section('a')] }, calls: [], streams: [], timers: new Map(), finals: [], stops: [], override: null };
  let nextTimer = 0, now = 0;
  class Stream extends Element {
    constructor(url) { super(); this.url = url; this.closed = false; state.streams.push(this); }
    close() { this.closed = true; }
    event(id, data = {}, name = 'partial_section_ready') { this.emit(name, { lastEventId: String(id), data: JSON.stringify({ schema_version: 1, ...data }) }); }
    fail() { this.onerror?.(); }
  }
  const context = vm.createContext({ globalThis: {}, URL, AbortController, setTimeout, clearTimeout });
  vm.runInContext(await readFile(new URL('../sidepanel-progress.js', import.meta.url), 'utf8'), context);
  const reader = context.globalThis.LearnNoteProgressive.create({ document: doc, card, status, sections, retry, t: key => key,
    setTimer(fn, ms) { const id = ++nextTimer; state.timers.set(id, { fn, time: now + ms }); return id; },
    clearTimer(id) { state.timers.delete(id); }, connect: url => new Stream(url),
    onTask: async (task, binding) => { state.finals.push(task); await state.finalOverride?.(binding); }, onStop: async (value, binding) => { state.stops.push(value); await state.stopOverride?.(binding); },
    fetch: async (url, options) => { state.calls.push({ url, options }); if (state.override) { const result = await state.override(url, options); if (result) return result; } return { ok: true, json: async () => structuredClone(url.endsWith('/partial-note') ? state.partial : { task: state.task }) }; }
  });
  const start = async (taskId = 'one', backendUrl = 'http://127.0.0.1:8765', sourceKey = 'source') => { reader.start({ taskId, backendUrl, sourceKey }); await flush(); };
  async function tick() { const next = [...state.timers].sort((a, b) => a[1].time - b[1].time)[0]; if (!next) return false; state.timers.delete(next[0]); now = next[1].time; next[1].fn(); await flush(); return true; }
  return { ...state, state, doc, card, status, sections, retry, reader, start, tick, Stream };
}
