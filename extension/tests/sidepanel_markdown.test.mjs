import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const elements = new Map();
const makeElement = () => ({
  addEventListener() {},
  classList: { add() {}, remove() {}, toggle() {} },
  querySelector() { return null; },
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
  location: { href: "file:///sidepanel.html" },
  navigator: { clipboard: { writeText() {} } },
  window: { open() {} },
  FormData: class FormData {},
  fetch: async url => {
    if (String(url).endsWith("/health")) {
      return { json: async () => ({ ffmpeg: true }) };
    }
    throw new Error(`unexpected fetch: ${url}`);
  },
  setTimeout,
  clearTimeout
};
context.window = { ...context.window, location: context.location };

vm.createContext(context);
const sidepanelCode = await readFile(new URL("../sidepanel.js", import.meta.url), "utf8");
vm.runInContext(sidepanelCode, context);

const html = context.markdownToHtml(`# 标题

- **重点** \`code\`
1. 步骤
> 引用
\`\`\`js
<script>alert(1)</script>
\`\`\`
`);

assert.match(html, /<h1>标题<\/h1>/);
assert.match(html, /<ul>/);
assert.match(html, /<strong>重点<\/strong>/);
assert.match(html, /<ol>/);
assert.match(html, /<blockquote>引用<\/blockquote>/);
assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
assert.doesNotMatch(html, /<script>/);
