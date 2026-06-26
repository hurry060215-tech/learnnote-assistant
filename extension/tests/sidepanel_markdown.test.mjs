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
    const value = String(url);
    if (value.endsWith("/health")) {
      return { json: async () => ({ ffmpeg: true }) };
    }
    if (value.endsWith("/api/tasks")) {
      return { json: async () => ({ tasks: [] }) };
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

const summaryDiagnostic = context.summaryDiagnosticText({
  summary_source: "vision-llm",
  summary_diagnostics: {
    used_vision_llm: true,
    llm_model: "vision-model",
    visual_window_count: 2,
    frame_grid_count: 2,
    vision_grid_count: 2,
    vision_image_count: 2,
    omitted_frame_grid_count: 1,
    all_grids_had_images: true
  }
});

assert.match(summaryDiagnostic, /已使用视觉 LLM/);
assert.match(summaryDiagnostic, /模型 vision-model/);
assert.match(summaryDiagnostic, /视觉窗口 2/);
assert.match(summaryDiagnostic, /送入视觉 2\/2/);
assert.match(summaryDiagnostic, /超限省略 1/);

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

const railHtml = context.noteVisualRail({
  visual_windows: [
    {
      id: "W001",
      start: 0,
      end: 180,
      frame_count: 9,
      grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg",
      transcript_excerpt: "<script>alert(1)</script> 画面摘要"
    }
  ]
});

assert.match(railHtml, /class="note-visual-rail"/);
assert.match(railHtml, /画面索引/);
assert.match(railHtml, /W001/);
assert.match(railHtml, /00:00:00 - 00:03:00/);
assert.match(railHtml, /src="http:\/\/127\.0\.0\.1:8765\/api\/tasks\/demo\/grids\/grid_000\.jpg"/);
assert.match(railHtml, /&lt;script&gt;alert\(1\)&lt;\/script&gt; 画面摘要/);
assert.doesNotMatch(railHtml, /<script>/);

const taskOverviewHtml = context.taskOverview({
  id: "side-overview",
  title: "<script>bad()</script> 课程",
  status: "success",
  phase: "completed",
  progress: 100,
  source_type: "current_page",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/side-overview/media.mp4",
  selected_resource: {
    kind: "video",
    playback_match: "exact-src",
    content_length: 2097152
  },
  options: {
    frame_interval: 20,
    grid_columns: 3,
    grid_rows: 3,
    whisper_model: "small",
    note_style: "study",
    visual_understanding: true
  },
  visual_windows: []
});

assert.match(taskOverviewHtml, /class="task-overview status-success"/);
assert.match(taskOverviewHtml, /本地视频/);
assert.match(taskOverviewHtml, /data-export="media"/);
assert.match(taskOverviewHtml, /已完成直取下载/);
assert.doesNotMatch(taskOverviewHtml, /<script>bad/);
assert.match(taskOverviewHtml, /&lt;script&gt;bad\(\)&lt;\/script&gt; 课程/);

const evidenceTags = context.resourceEvidenceTags({
  kind: "hls",
  source: "webRequest",
  request_type: "media",
  status_code: 206,
  is_main_video: true,
  playback_match: "blob-source",
  blob_url: "blob:https://course.example.com/demo",
  request_headers: {
    Range: "bytes=100-200",
    Referer: "https://course.example.com/lesson"
  }
});

assert.deepEqual([...evidenceTags], [
  "\u5f53\u524d\u4e3b\u89c6\u9891",
  "Blob/MSE \u6765\u6e90\u6620\u5c04",
  "\u53ef\u5408\u5e76 manifest",
  "blob/MSE \u6620\u5c04",
  "\u6d4f\u89c8\u5668\u8bf7\u6c42",
  "media \u8bf7\u6c42",
  "Range \u64ad\u653e\u8bf7\u6c42",
  "\u5e26 Referer/Origin",
  "HTTP 206"
]);
assert.match(context.resourceReasonText({ kind: "fragment", source: "pageHookFetch" }), /\u5206\u7247\u7ebf\u7d22/);
assert.match(context.resourceTagHtml({
  kind: "hls",
  source: "webRequest",
  request_type: "media",
  status_code: 206,
  is_main_video: true,
  playback_match: "blob-source",
  blob_url: "blob:https://course.example.com/demo",
  request_headers: {
    Range: "bytes=100-200",
    Referer: "https://course.example.com/lesson"
  }
}), /<em>\+5<\/em>/);
