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
  files: [],
  scrollCalls: [],
  scrollIntoView(options) {
    this.scrollCalls.push(options || {});
  }
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
    innerWidth: 1280,
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

assert.match(html, /<h2 id="note-画面索引">画面索引<\/h2>/);
assert.match(html, /<figure class="note-image-frame">/);
assert.match(html, /src="http:\/\/127\.0\.0\.1:8765\/api\/tasks\/demo\/grids\/grid_000\.jpg"/);
assert.doesNotMatch(html, /src="javascript:alert/);

const outlineHtml = context.noteOutline(`# Smoke Current Page Video

## 画面索引
### **重点** 片段
## 画面索引
\`\`\`
## 不应进入目录
\`\`\`
`);

assert.match(outlineHtml, /class="note-outline"/);
assert.match(outlineHtml, /href="#note-smoke-current-page-video"/);
assert.match(outlineHtml, /href="#note-画面索引"/);
assert.match(outlineHtml, /href="#note-画面索引-2"/);
assert.match(outlineHtml, /重点 片段/);
assert.doesNotMatch(outlineHtml, /不应进入目录/);

const resultPanel = elements.get(".result-panel") || documentStub.querySelector(".result-panel");
context.window.innerWidth = 1280;
context.focusResultPanelOnMobile();
assert.equal(resultPanel.scrollCalls.length, 0);

context.window.innerWidth = 390;
context.focusResultPanelOnMobile();
assert.equal(resultPanel.scrollCalls.length, 1);
assert.equal(resultPanel.scrollCalls[0].block, "start");

const railHtml = context.visualRail({
  visual_windows: [{
    id: "W001",
    start: 0,
    end: 180,
    frame_count: 9,
    grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg",
    transcript_excerpt: "<script>alert(1)</script> 课程演示"
  }]
});

assert.match(railHtml, /class="visual-rail"/);
assert.match(railHtml, /W001/);
assert.match(railHtml, /00:00:00 - 00:03:00/);
assert.match(railHtml, /src="http:\/\/127\.0\.0\.1:8765\/api\/tasks\/demo\/grids\/grid_000\.jpg"/);
assert.doesNotMatch(railHtml, /<script>/);
assert.match(railHtml, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);

const readingRailHtml = context.readingRail("## 第一节", {
  visual_windows: [{
    id: "W001",
    start: 0,
    end: 30,
    frame_count: 3,
    grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg",
    transcript_excerpt: ""
  }]
});

assert.match(readingRailHtml, /class="reading-rail"/);
assert.match(readingRailHtml, /class="note-outline"/);
assert.match(readingRailHtml, /class="visual-rail"/);

const summaryDiagnostic = context.summaryDiagnosticText({
  summary_source: "vision-llm",
  summary_diagnostics: {
    used_vision_llm: true,
    llm_model: "vision-model",
    visual_window_count: 2,
    frame_grid_count: 2,
    vision_image_count: 2,
    all_grids_had_images: true
  }
});

assert.match(summaryDiagnostic, /已使用视觉 LLM/);
assert.match(summaryDiagnostic, /模型 vision-model/);
assert.match(summaryDiagnostic, /视觉窗口 2/);
assert.match(summaryDiagnostic, /已发送图片 2/);

const timelineHtml = context.transcriptTimeline({
  segments: [
    { start: 5, end: 8, text: "第一段字幕" },
    { start: 190, end: 196, text: "<script>alert(1)</script>" }
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

const posts = [];
context.fetch = async (url, options = {}) => {
  const value = String(url);
  if (value.endsWith("/api/tasks/from-current-page")) {
    posts.push(JSON.parse(options.body));
    return { json: async () => ({ task_id: "task-url-direct" }) };
  }
  if (value.endsWith("/api/tasks/task-url-direct")) {
    return { json: async () => ({ task: { id: "task-url-direct", status: "queued", phase: "downloading", progress: 0, source_type: "url" } }) };
  }
  if (value.endsWith("/api/tasks")) {
    return { json: async () => ({ tasks: [{ id: "task-url-direct", status: "queued", phase: "downloading", progress: 0, source_type: "url" }] }) };
  }
  return { ok: false, json: async () => ({}), text: async () => "" };
};

elements.get("#urlInput").value = "https://cdn.example.com/api/play?id=shadow";
elements.get("#urlMode").value = "video";
elements.get("#titleInput").value = "无后缀直连课件";
await context.startUrlTask();

assert.equal(posts.length, 1);
assert.equal(posts[0].resources.length, 1);
assert.equal(posts[0].resources[0].kind, "video");
assert.equal(posts[0].resources[0].source, "manual");
assert.equal(posts[0].resources[0].request_type, "manual-forced");
assert.equal(posts[0].resources[0].url, "https://cdn.example.com/api/play?id=shadow");
