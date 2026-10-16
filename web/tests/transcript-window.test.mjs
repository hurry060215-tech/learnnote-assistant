import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const source = readFileSync(new URL("../transcript-window.js", import.meta.url), "utf8");
const { createTranscriptWindow } = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
function makeDocument() {
  const document = {};
  class Element {
    constructor() {
      this.dataset = {}; this.style = {}; this.attributes = {}; this.children = []; this.events = new Map();
      this._scrollTop = 0; this.clientHeight = 300;
      this.classList = {
        toggle: (name, active) => { const names = new Set((this.className || "").split(" ")); active ? names.add(name) : names.delete(name); this.className = [...names].join(" "); },
        contains: name => (this.className || "").split(" ").includes(name),
      };
    }
    get scrollTop() { return this._scrollTop; }
    set scrollTop(value) {
      const layout = document.layout;
      if (!layout || this !== layout.content) { this._scrollTop = value; return; }
      const { viewport, rowHeight } = layout;
      const maximum = Math.max(0, (parseFloat(viewport.style.paddingTop) || 0) + (parseFloat(viewport.style.paddingBottom) || 0)
        + viewport.children.length * rowHeight + 16 - this.clientHeight);
      this._scrollTop = Math.min(maximum, Math.max(0, value));
    }
    getClientRects() { return document.layout && this.dataset.cueIndex !== undefined ? [{}] : []; }
    getBoundingClientRect() {
      const { content, viewport, rowHeight } = document.layout;
      if (this === content) return { top: 0, bottom: this.clientHeight };
      const top = (parseFloat(viewport.style.paddingTop) || 0) + viewport.children.indexOf(this) * rowHeight - content.scrollTop;
      return { top, bottom: top + rowHeight };
    }
    setAttribute(key, value) { this.attributes[key] = value; }
    getAttribute(key) { return this.attributes[key] ?? null; }
    removeAttribute(key) { delete this.attributes[key]; }
    append(...items) { for (const item of items) { item.parent = this; this.children.push(item); } }
    contains(node) { return this === node || this.children.some(child => child.contains?.(node)); }
    replaceChildren(...items) {
      // Model browsers that emit focusout when a focused row is removed, too.
      if (this.contains(document.activeElement)) document.body.focus();
      for (const child of this.children) child.parent = null;
      this.children = []; this.append(...items);
    }
    querySelectorAll() { return this.children.filter(node => node.classList?.contains("cue")); }
    querySelector(selector) { return this.children.find(node => node.dataset.cueIndex === selector.match(/"(\d+)"/)[1]); }
    addEventListener(name, fn) { this.events.set(name, fn); }
    removeEventListener(name, fn) { if (this.events.get(name) === fn) this.events.delete(name); }
    focus() {
      const previous = document.activeElement;
      if (previous === this) return;
      document.activeElement = this;
      for (let node = previous; node; node = node.parent) node.events?.get("focusout")?.({ target: previous, relatedTarget: this });
    }
    closest() { return this.dataset.cueIndex === undefined ? this.parent?.closest() : this; }
  }
  document.createElement = () => new Element();
  document.createTextNode = text => ({ textContent: text });
  document.body = new Element(); document.activeElement = document.body;
  return document;
}
const document = makeDocument(), content = document.createElement(), viewport = document.createElement();
content.append(viewport);
const outside = document.createElement();
const cues = Array.from({ length: 10000 }, (_, index) => ({ start: index * 5, text: `字幕原文 ${index}` }));
let renders = 0, rendered = [], follow = true;
const window = createTranscriptWindow({ content, viewport, cues, document, timestamp: String,
  followEnabled: () => follow, onRender: value => { rendered = value; renders++; } });
const sync = seconds => window.render(seconds, undefined, { automatic: true });
const cue = index => rendered.find(node => node.dataset.cueIndex === String(index));
const current = () => rendered.filter(node => node.getAttribute("aria-current") === "time");
const flushFocus = () => Promise.resolve();
assert(rendered.length < 30, "Long transcripts must have a bounded DOM");
sync(40000);
assert(cue(8000), "Playback follows beyond the first virtual window");
assert.deepEqual(current(), [cue(8000)], "The actual current cue exposes aria-current=time");
const oldRenders = renders;
sync(40000);
assert.equal(renders, oldRenders, "Repeated ticks must not replace the same virtual window");
const focused = cue(8000), pinnedScroll = content.scrollTop;
focused.focus();
for (const seconds of [40005, 45000, 49750]) sync(seconds);
assert.equal(document.activeElement, focused, "Playback across distant windows retains the exact focused node");
assert(viewport.contains(focused));
assert.equal(content.scrollTop, pinnedScroll, "Playback leaves the focused reader's scroll untouched");
assert.equal(renders, oldRenders);
assert.deepEqual(current(), [], "An off-window playing cue must not mark the last mounted row current");
assert(rendered.every(node => !node.classList.contains("active")));
outside.focus(); await flushFocus();
assert.equal(document.activeElement, outside, "Resuming follow must not steal focus");
assert.deepEqual(current(), [cue(9950)], "Focusout follows the latest tick, not the first deferred tick");
assert.notEqual(content.scrollTop, pinnedScroll);
assert.equal(follow, true, "A focus pause must not toggle the user's follow preference");

cue(9950).focus(); follow = false;
const disabledScroll = content.scrollTop;
sync(100);
outside.focus(); await flushFocus();
assert.equal(content.scrollTop, disabledScroll, "Focusout respects a disabled follow preference");
assert.deepEqual(current(), []);
follow = true; sync(100);
assert.deepEqual(current(), [cue(20)]);
follow = false; sync(105);
assert.deepEqual(current(), [cue(21)], "Semantic current state still updates while follow is disabled");
follow = true;

const keydown = viewport.events.get("keydown");
let prevented = false;
cue(21).focus();
keydown({ key: "End", target: document.activeElement, preventDefault() { prevented = true; } });
assert(prevented);
assert.equal(document.activeElement, cue(9999), "End reaches and focuses the unmounted last cue");
assert(rendered.length < 30);
keydown({ key: "Home", target: document.activeElement, preventDefault() {} });
assert.equal(document.activeElement, cue(0), "Home reaches and focuses the unmounted first cue");
keydown({ key: "ArrowDown", target: document.activeElement, preventDefault() {} });
assert.equal(document.activeElement, cue(1));
keydown({ key: "ArrowUp", target: document.activeElement, preventDefault() {} });
assert.equal(document.activeElement, cue(0));
await flushFocus();
assert.equal(document.activeElement, cue(0), "Internal keyboard focus moves must not resume playback follow");

const scroll = content.events.get("scroll");
content.scrollTop = 500 * 72; scroll(); await flushFocus();
assert.equal(document.activeElement, document.body, "User scroll may unmount a cue without restoring its focus");
assert.equal(content.scrollTop, 500 * 72, "Removal-triggered focusout must not undo user scroll");
assert(rendered.length < 30);
rendered[0].focus(); outside.focus();
content.scrollTop = 600 * 72; scroll(); await flushFocus();
assert.equal(content.scrollTop, 600 * 72, "A new user scroll wins over a queued focusout catch-up");
assert.equal(document.activeElement, outside);

rendered[0].focus(); outside.focus();
window.destroy(); await flushFocus();
assert.equal(content.events.size, 0);
assert.equal(viewport.events.size, 0);
const count = renders;
scroll(); sync(25000);
assert.equal(renders, count, "Queued old-source scroll, focusout and playback cannot render into a new source");
const replacement = createTranscriptWindow({ content, viewport, cues: cues.slice(0, 2), document, timestamp: String,
  onRender: value => { rendered = value; } });
assert.equal(document.activeElement, outside, "A source change does not transfer a previous cue's focus");
assert.deepEqual(current(), [], "A fresh source starts with no previous playback cue");
replacement.render(0);
assert.deepEqual(current(), [cue(0)]);
replacement.destroy();
// Real scrolling clamps to actual content height, while virtualization uses a
// 72px estimate. End's later scroll event must not replace the focused node when
// font metrics or wrapped/reflowed text make those heights disagree.
for (const rowHeight of [58, 60.067, 62, 90, 120]) {
  const doc = makeDocument(), scroller = doc.createElement(), rows = doc.createElement();
  scroller.clientHeight = 280; scroller.append(rows);
  doc.layout = { content: scroller, viewport: rows, rowHeight };
  const model = createTranscriptWindow({ content: scroller, viewport: rows, cues: cues.slice(0, 203), document: doc,
    timestamp: String, onRender() {} });
  model.render(5); rows.querySelector('[data-cue-index="1"]').focus();
  const press = key => rows.events.get("keydown")({ key, target: doc.activeElement, preventDefault() {} });
  press("End");
  const lastCue = doc.activeElement;
  assert.equal(lastCue.dataset.cueIndex, "202");
  for (let event = 0; event < 2; event++) scroller.events.get("scroll")();
  await flushFocus();
  assert.equal(doc.activeElement, lastCue, `End retains the exact node after deferred scroll at ${rowHeight}px row height`);
  model.render(1000, undefined, { automatic: true });
  assert.equal(doc.activeElement, lastCue);
  press("Home");
  const firstCue = doc.activeElement;
  assert.equal(firstCue.dataset.cueIndex, "0");
  scroller.events.get("scroll")(); await flushFocus();
  assert.equal(doc.activeElement, firstCue, "Home survives its queued scroll event too");
  scroller.scrollTop = 4000; scroller.events.get("scroll")(); await flushFocus();
  assert.equal(doc.activeElement, doc.body, "A genuinely new user scroll still unmounts the off-screen cue without restoring focus");
  assert.equal(scroller.scrollTop, 4000);
  assert(rows.children.length < 80);
  model.destroy();
}
const desk = readFileSync(new URL("../desk.js", import.meta.url), "utf8");
assert.match(desk, /sourceCueCleanup\?\.\(\)/);
assert.match(desk, /followEnabled: \(\) => Boolean\(\$\("followTranscript"\)\?\.checked\)/);
assert.match(desk, /sourceCueRender\(time, undefined, \{ automatic: true \}\)/);
assert.match(desk, /setAttribute\("aria-current", "time"\)/);
console.log("Transcript focus pinning, bounded playback follow, active semantics, keyboard navigation and source cleanup pass");
