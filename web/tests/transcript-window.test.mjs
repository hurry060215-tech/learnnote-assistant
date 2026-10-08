import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const source = readFileSync(new URL("../transcript-window.js", import.meta.url), "utf8");
const { createTranscriptWindow } = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
class Element {
  constructor() { this.dataset = {}; this.style = {}; this.children = []; this.events = new Map(); this.scrollTop = 0; this.clientHeight = 300; }
  setAttribute(key, value) { (this.attributes ||= {})[key] = value; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  querySelectorAll() { return this.children; }
  querySelector(selector) { return this.children.find(node => node.dataset.cueIndex === selector.match(/"(\d+)"/)[1]); }
  addEventListener(name, fn) { this.events.set(name, fn); }
  removeEventListener(name, fn) { if (this.events.get(name) === fn) this.events.delete(name); }
  focus() { this.focused = true; }
  closest() { return this; }
}
const document = { createElement: () => new Element(), createTextNode: text => ({ textContent: text }) };
const content = new Element(), viewport = new Element();
const cues = Array.from({ length: 10000 }, (_, index) => ({ start: index * 5, text: `字幕原文 ${index}` }));
let renders = 0, rendered = [];
const window = createTranscriptWindow({ content, viewport, cues, document, timestamp: String, onRender: value => { rendered = value; renders++; } });
assert(rendered.length < 30, "Long transcripts must have a bounded DOM");
window.render(40000);
assert(rendered.some(node => node.dataset.cueIndex === "8000"), "Playback follows beyond the first virtual window");
const oldRenders = renders;
window.render(40000);
assert.equal(renders, oldRenders, "Repeated ticks must not replace focused DOM unnecessarily");
const keydown = viewport.events.get("keydown");
let prevented = false;
keydown({ key: "End", target: rendered[0], preventDefault() { prevented = true; } });
assert(prevented);
assert(rendered.find(node => node.dataset.cueIndex === "9999")?.focused, "Keyboard navigation reaches unmounted cues");
keydown({ key: "Home", target: rendered.at(-1), preventDefault() {} });
assert(rendered.find(node => node.dataset.cueIndex === "0")?.focused);
const scroll = content.events.get("scroll");
window.destroy();
assert.equal(content.events.size, 0);
assert.equal(viewport.events.size, 0);
const count = renders;
scroll(); window.render(25000);
assert.equal(renders, count, "Queued old-source scrolls cannot render into a new source");
const desk = readFileSync(new URL("../desk.js", import.meta.url), "utf8");
assert.match(desk, /sourceCueCleanup\?\.\(\)/);
assert.match(desk, /if \(sourceCueRender && \$\("followTranscript"\)\?\.checked\) sourceCueRender\(time\)/);
console.log("Long transcript follow, keyboard navigation and source cleanup pass");
