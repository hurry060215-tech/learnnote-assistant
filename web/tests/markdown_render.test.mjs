import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const elements = new Map();
const makeElement = () => ({
  addEventListener() {},
  classList: { add() {}, remove() {}, toggle() {} },
  style: {},
  dataset: {},
  value: "",
  textContent: "",
  innerHTML: "",
  disabled: false,
  onclick: null,
  onchange: null,
  files: []
});

const documentStub = {
  body: makeElement(),
  createElement() {
    return makeElement();
  },
  querySelector(selector) {
    if (!elements.has(selector)) elements.set(selector, makeElement());
    return elements.get(selector);
  },
  querySelectorAll() {
    return [];
  }
};

const context = {
  console,
  document: documentStub,
  location: { href: "http://127.0.0.1:8765/" },
  navigator: { clipboard: { writeText() {} } },
  window: {
    location: { origin: "http://127.0.0.1:8765", assign() {} }
  },
  Blob: class Blob {},
  FormData: class FormData {},
  URL: class URL {},
  fetch: async url => {
    const value = String(url);
    if (value.endsWith("/health")) return { json: async () => ({ ffmpeg: true }) };
    if (value.endsWith("/api/tasks")) return { json: async () => ({ tasks: [] }) };
    return { ok: false, json: async () => ({}), text: async () => "" };
  },
  setInterval() {},
  setTimeout,
  clearTimeout
};
context.window.document = context.document;
context.window.navigator = context.navigator;

vm.createContext(context);
const webCode = await readFile(new URL("../app.js", import.meta.url), "utf8");
vm.runInContext(webCode, context);

const html = context.markdownToHtml(`## 画面索引

![W001](http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg)
![bad](javascript:alert(1))
`);

assert.match(html, /<h2>画面索引<\/h2>/);
assert.match(html, /<figure class="note-image-frame">/);
assert.match(html, /src="http:\/\/127\.0\.0\.1:8765\/api\/tasks\/demo\/grids\/grid_000\.jpg"/);
assert.doesNotMatch(html, /src="javascript:alert/);
