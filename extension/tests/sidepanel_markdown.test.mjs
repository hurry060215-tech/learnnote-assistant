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
![W001 00:00:00 - 00:03:00](http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg)
![bad](javascript:alert(1))
\`\`\`js
<script>alert(1)</script>
\`\`\`
`);

assert.match(html, /<h1 id="note-标题">标题<\/h1>/);
assert.match(html, /<ul>/);
assert.match(html, /<strong>重点<\/strong>/);
assert.match(html, /<ol>/);
assert.match(html, /<blockquote>引用<\/blockquote>/);
assert.match(html, /<figure class="note-image-frame">/);
assert.match(html, /src="http:\/\/127\.0\.0\.1:8765\/api\/tasks\/demo\/grids\/grid_000\.jpg"/);
assert.doesNotMatch(html, /src="javascript:alert/);
assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
assert.doesNotMatch(html, /<script>/);

const outlineHtml = context.noteOutline(`# 当前页学习笔记

## 时间轴重点
### **画面** 解读
## 时间轴重点
\`\`\`
## 不进目录
\`\`\`
`);

assert.match(outlineHtml, /class="note-outline"/);
assert.match(outlineHtml, /href="#note-当前页学习笔记"/);
assert.match(outlineHtml, /href="#note-时间轴重点"/);
assert.match(outlineHtml, /href="#note-时间轴重点-2"/);
assert.match(outlineHtml, /画面 解读/);
assert.doesNotMatch(outlineHtml, /不进目录/);

const timelineHtml = context.transcriptTimeline({
  segments: [
    { start: 4, end: 8, text: "第一段字幕" },
    { start: 182, end: 188, text: "<script>alert(1)</script>" }
  ]
}, {
  visual_windows: [
    {
      id: "W001",
      start: 0,
      end: 180,
      frame_count: 9,
      grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg",
      transcript_excerpt: ""
    },
    {
      id: "W002",
      start: 180,
      end: 360,
      frame_count: 9,
      grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_001.jpg",
      transcript_excerpt: ""
    }
  ]
});

assert.match(timelineHtml, /class="transcript-timeline"/);
assert.match(timelineHtml, /W001/);
assert.match(timelineHtml, /00:00:00 - 00:03:00/);
assert.match(timelineHtml, /第一段字幕/);
assert.match(timelineHtml, /W002/);
assert.match(timelineHtml, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
assert.doesNotMatch(timelineHtml, /<script>/);
