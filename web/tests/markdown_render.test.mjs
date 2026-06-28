import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const elements = new Map();
const makeClassList = () => {
  const values = new Set();
  return {
    values,
    add(name) {
      values.add(name);
    },
    remove(name) {
      values.delete(name);
    },
    toggle(name, force) {
      const enabled = force === undefined ? !values.has(name) : Boolean(force);
      if (enabled) values.add(name);
      else values.delete(name);
      return enabled;
    },
    contains(name) {
      return values.has(name);
    }
  };
};

const makeElement = () => ({
  listeners: {},
  addEventListener(type, listener) {
    this.listeners[type] = listener;
  },
  classList: makeClassList(),
  style: {},
  dataset: {},
  attributes: {},
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
  },
  setAttribute(name, value) {
    this.attributes[name] = String(value);
  },
  getAttribute(name) {
    return this.attributes[name];
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
    location: { origin: "http://127.0.0.1:8765", href: "http://127.0.0.1:8765/", pathname: "/", search: "", hash: "", assign() {} },
    history: {
      replacedUrls: [],
      replaceState(_state, _title, url) {
        this.replacedUrls.push(String(url));
        context.window.location.href = `http://127.0.0.1:8765${url}`;
        const queryIndex = String(url).indexOf("?");
        const hashIndex = String(url).indexOf("#");
        context.window.location.pathname = queryIndex >= 0 ? String(url).slice(0, queryIndex) : String(url);
        context.window.location.search = queryIndex >= 0 ? String(url).slice(queryIndex, hashIndex >= 0 ? hashIndex : undefined) : "";
        context.window.location.hash = hashIndex >= 0 ? String(url).slice(hashIndex) : "";
      }
    },
    localStorage: {
      values: new Map(),
      getItem(key) {
        return this.values.get(key) || null;
      },
      setItem(key, value) {
        this.values.set(key, String(value));
      }
    }
  },
  Blob: class Blob {},
  FormData: class FormData {
    constructor() {
      this.values = new Map();
    }
    append(name, value) {
      this.values.set(name, value);
    }
    get(name) {
      return this.values.get(name);
    }
  },
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
const indexHtml = await readFile(new URL("../index.html", import.meta.url), "utf8");
vm.runInContext(webCode, context);

await new Promise(resolve => setTimeout(resolve, 0));
assert.match(elements.get("#detail").innerHTML, /class="empty-workbench"/);
assert.match(elements.get("#detail").innerHTML, /class="empty-demo-board"/);
assert.match(elements.get("#detail").innerHTML, /class="empty-route-grid"/);
assert.match(elements.get("#detail").innerHTML, /当前页直取/);
assert.match(elements.get("#detail").innerHTML, /打开当前页路线/);
assert.match(elements.get("#detail").innerHTML, /选择本地视频/);
assert.match(elements.get("#detail").innerHTML, /粘贴链接/);
assert.match(elements.get("#detail").innerHTML, /直取候选 · HLS/);
assert.match(elements.get("#detail").innerHTML, /浏览器字幕和转写片段会按视觉窗口对齐/);
assert.match(elements.get("#detail").innerHTML, /不.*录制页面/);
assert.equal(elements.get("#copyButton").disabled, true);
assert.equal(elements.get("#visualWindowsButton").disabled, true);
assert.match(elements.get("#sourceWorkflow").innerHTML, /class="source-workflow-card browser"/);
assert.match(elements.get("#sourceWorkflow").innerHTML, /学习生产线|当前页直取/);
assert.match(elements.get("#sourceWorkflow").innerHTML, /读取当前页/);
assert.match(elements.get("#sourceWorkflow").innerHTML, /预检资源/);
assert.match(indexHtml, /class="browser-capture-card"/);
assert.match(indexHtml, /class="capture-flow"/);
assert.match(indexHtml, /非录制/);
assert.match(indexHtml, /预检候选/);
assert.match(indexHtml, /本地总结/);
assert.match(indexHtml, /id="browserRouteSummary"/);
assert.match(indexHtml, /id="visualWindowsButton"/);
assert.ok(
  indexHtml.indexOf('id="browserRouteSummary"') < indexHtml.indexOf('id="sourceWorkflow"'),
  "current-page route summary should appear before the workflow explainer"
);
assert.match(indexHtml, /当前页直取状态/);
assert.match(indexHtml, /当前页交接流程/);
assert.match(indexHtml, /Blob\/MSE 来源映射/);
assert.match(indexHtml, /accept="video\/\*,\.mp4,\.m4v,\.mov,\.mkv,\.webm,\.flv,\.avi"/);
context.window.location.search = "?task=task%20from%20url";
assert.equal(context.taskIdFromCurrentUrl(), "task from url");
context.window.location.search = "?result_tab=frames";
assert.equal(context.resultTabFromCurrentUrl(), "frames");
context.window.location.search = "?tab=unknown";
assert.equal(context.resultTabFromCurrentUrl(), "note");
context.window.location.search = "";
assert.equal(context.isSupportedLocalVideoFile({ name: "lesson.mkv", type: "" }), true);
assert.equal(context.isSupportedLocalVideoFile({ name: "lesson.flv", type: "" }), true);
assert.equal(context.isSupportedLocalVideoFile({ name: "lesson.avi", type: "" }), true);
assert.equal(context.isSupportedLocalVideoFile({ name: "bad.txt", type: "text/plain" }), false);

const routeSummaryHtml = context.browserRouteSummaryHtml({
  id: "task-route-summary",
  title: "<script>bad()</script> 课程",
  status: "success",
  phase: "completed",
  progress: 100,
  source_type: "current_page",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/task-route-summary/media.mp4",
  note_path: "",
  selected_resource: {
    kind: "hls"
  },
  download_attempts: [{ strategy: "manifest-ffmpeg" }],
  visual_windows: [
    { id: "W001", start: 0, end: 180 },
    { id: "W002", start: 180, end: 360 }
  ]
});

assert.match(routeSummaryHtml, /class="browser-route-summary-card downloaded"/);
assert.match(routeSummaryHtml, /视频已直取到本地/);
assert.match(routeSummaryHtml, /继续切片总结/);
assert.match(routeSummaryHtml, /data-select-browser-task="task-route-summary"/);
assert.match(routeSummaryHtml, /data-rerun-browser-task="task-route-summary"/);
assert.match(routeSummaryHtml, /data-browser-route-action="refresh"/);
assert.match(routeSummaryHtml, /data-browser-route-action="copy-backend"/);
assert.match(routeSummaryHtml, /\/api\/tasks\/task-route-summary\/exports\/media/);
assert.match(routeSummaryHtml, /\/api\/tasks\/task-route-summary\/exports\/diagnostics/);
assert.match(routeSummaryHtml, /class="browser-route-handoff"/);
assert.match(routeSummaryHtml, /资源证据/);
assert.match(routeSummaryHtml, /本地落地/);
assert.match(routeSummaryHtml, /学习笔记/);
assert.match(routeSummaryHtml, /视觉窗口/);
assert.doesNotMatch(routeSummaryHtml, /<script>bad/);

const queueChipTask = {
  id: "queue-chip-task",
  status: "success",
  phase: "completed",
  progress: 100,
  source_type: "current_page",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/queue-chip-task/media.mp4",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/queue-chip-task/note.md",
  selected_resource: {
    kind: "video",
    source: "webRequest",
    playback_match: "exact-src"
  },
  visual_windows: [{ id: "W001", start: 0, end: 180 }],
  download_attempts: [{ strategy: "direct-file" }, { strategy: "page-ytdlp" }]
};

assert.equal(JSON.stringify(context.taskChipItems(queueChipTask)), JSON.stringify(["当前 src", "视频", "media.mp4", "笔记", "1 窗口"]));
assert.equal(context.taskMetaLine(queueChipTask), "已完成 · 直取 · 视频 · 100%");

const visionEvidenceHtml = context.visionEvidenceBar({
  id: "vision-task",
  title: "<script>bad()</script> 课程",
  status: "success",
  phase: "completed",
  progress: 100,
  source_type: "current_page",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/vision-task/media.mp4",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/vision-task/note.md",
  summary_source: "vision-llm",
  summary_diagnostics: {
    frame_grid_count: 3,
    vision_grid_count: 3,
    vision_image_count: 2,
    missing_vision_image_window_ids: ["W002"],
    omitted_vision_window_ids: ["W099"],
    summary_warning: "<script>bad()</script> warning"
  },
  visual_windows: [
    { id: "W001", start: 0, end: 180, grid_url: "/api/tasks/vision-task/grids/grid_001.jpg" },
    { id: "W002", start: 180, end: 360, grid_url: "" }
  ]
});

assert.match(visionEvidenceHtml, /class="vision-evidence strong"/);
assert.match(visionEvidenceHtml, /画面已参与图文总结/);
assert.match(visionEvidenceHtml, /2\/3/);
assert.match(visionEvidenceHtml, /缺图 W002/);
assert.match(visionEvidenceHtml, /超限省略 W099/);
assert.match(visionEvidenceHtml, /data-switch-result-tab="frames"/);
assert.match(visionEvidenceHtml, /data-switch-result-tab="diagnostics"/);
assert.match(visionEvidenceHtml, /\/api\/tasks\/vision-task\/exports\/bundle/);
assert.match(visionEvidenceHtml, /&lt;script&gt;bad\(\)&lt;\/script&gt; warning/);
assert.doesNotMatch(visionEvidenceHtml, /<script>bad/);

const blockedRouteSummaryHtml = context.browserRouteSummaryHtml({
  id: "task-route-blocked",
  status: "failed",
  phase: "failed",
  progress: 100,
  source_type: "current_page",
  error_code: "drm_or_encrypted",
  error_detail: "<script>bad()</script> DRM"
});

assert.match(blockedRouteSummaryHtml, /class="browser-route-summary-card blocked"/);
assert.match(blockedRouteSummaryHtml, /不可直取/);
assert.match(blockedRouteSummaryHtml, /data-browser-route-action="local-video"/);
assert.match(blockedRouteSummaryHtml, /&lt;script&gt;bad\(\)&lt;\/script&gt; DRM/);
assert.doesNotMatch(blockedRouteSummaryHtml, /导出本地视频/);
assert.doesNotMatch(blockedRouteSummaryHtml, /<script>bad/);

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

context.setHistoryCollapsed(true);
assert.equal(documentStub.body.classList.contains("queue-collapsed"), true);
assert.equal(elements.get("#toggleHistoryButton").getAttribute("aria-pressed"), "true");
assert.equal(context.window.localStorage.getItem("learnnote.historyCollapsed"), "1");

context.setReadingMode(true);
assert.equal(documentStub.body.classList.contains("reading-mode"), true);
assert.equal(elements.get("#readingModeButton").getAttribute("aria-pressed"), "true");
assert.equal(context.window.localStorage.getItem("learnnote.readingMode"), "1");

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

const visualDeckHtml = context.visualStudyDeck({
  id: "task-visual-deck",
  title: "<script>bad()</script> 视觉课程",
  summary_source: "vision-llm",
  options: { grid_columns: 3, grid_rows: 3 },
  visual_windows: [
    {
      id: "W001",
      start: 0,
      end: 180,
      frame_count: 9,
      frame_timestamps: [0, 20, 40, 60, 80],
      grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg",
      transcript_excerpt: "<script>alert(1)</script> PPT 演示"
    },
    {
      id: "W002",
      start: 180,
      end: 360,
      frame_count: 9,
      grid_url: "javascript:alert(1)",
      transcript_excerpt: ""
    }
  ]
});
assert.match(visualDeckHtml, /class="visual-study-deck"/);
assert.match(visualDeckHtml, /视觉窗口复习/);
assert.match(visualDeckHtml, /2 个窗口 · 00:00:00 - 00:06:00/);
assert.match(visualDeckHtml, /导出切片索引/);
assert.match(visualDeckHtml, /\/api\/tasks\/task-visual-deck\/exports\/visual-windows/);
assert.match(visualDeckHtml, /src="http:\/\/127\.0\.0\.1:8765\/api\/tasks\/demo\/grids\/grid_000\.jpg"/);
assert.match(visualDeckHtml, /学习动作/);
assert.match(visualDeckHtml, /复述这一窗口的结论/);
assert.match(visualDeckHtml, /回看检查点/);
assert.match(visualDeckHtml, /00:00:00/);
assert.match(visualDeckHtml, /对照画面确认对应的板书、PPT、代码或操作步骤/);
assert.match(visualDeckHtml, /00:00:00 \/ 00:00:20 \/ 00:00:40 \/ 00:01:00\.\.\./);
assert.doesNotMatch(visualDeckHtml, /src="javascript:alert/);
assert.match(visualDeckHtml, /&lt;script&gt;alert\(1\)&lt;\/script&gt; PPT 演示/);
assert.match(visualDeckHtml, /data-switch-result-tab="transcript"/);
assert.match(visualDeckHtml, /data-switch-result-tab="note"/);
assert.doesNotMatch(visualDeckHtml, /<script>bad/);

const visualDeckWithTranscriptHtml = context.visualStudyDeck({
  id: "task-visual-transcript",
  title: "带字幕切片",
  summary_source: "vision-llm",
  options: { grid_columns: 3, grid_rows: 3 },
  visual_windows: [
    {
      id: "W001",
      start: 0,
      end: 180,
      frame_count: 9,
      grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg",
      transcript_excerpt: ""
    }
  ]
}, {
  segments: [
    { start: 12, end: 18, text: "老师讲解概念定义" },
    { start: 45, end: 52, text: "<script>alert(1)</script> 例题演示" },
    { start: 220, end: 230, text: "不属于这个窗口" }
  ]
});
assert.match(visualDeckWithTranscriptHtml, /1 个窗口 · 2 段字幕已同步/);
assert.match(visualDeckWithTranscriptHtml, /class="visual-study-cues"/);
assert.match(visualDeckWithTranscriptHtml, /00:00:12/);
assert.match(visualDeckWithTranscriptHtml, /老师讲解概念定义/);
assert.match(visualDeckWithTranscriptHtml, /&lt;script&gt;alert\(1\)&lt;\/script&gt; 例题演示/);
assert.match(visualDeckWithTranscriptHtml, /回看检查点/);
assert.match(visualDeckWithTranscriptHtml, /对照画面确认对应的板书、PPT、代码或操作步骤/);
assert.match(visualDeckWithTranscriptHtml, /核对截图里的板书/);
assert.doesNotMatch(visualDeckWithTranscriptHtml, /不属于这个窗口/);
assert.doesNotMatch(visualDeckWithTranscriptHtml, /<script>/);

const studyBarHtml = context.noteStudyBar(`# <script>bad()</script> 课程

## 第一节
### 画面演示
`, {
  id: "task-study-map",
  title: "<script>bad()</script> 课程",
  status: "success",
  phase: "completed",
  progress: 100,
  source_type: "current_page",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/task-study-map/media.mp4",
  transcript_path: "D:/Projects/learnnote-assistant/data/tasks/task-study-map/transcript.json",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/task-study-map/note.md",
  options: {
    transcriber: "faster-whisper",
    whisper_model: "small"
  },
  visual_windows: [{
    id: "W001",
    start: 0,
    end: 180,
    frame_count: 9,
    grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg",
    transcript_excerpt: ""
  }],
  download_attempts: [{ strategy: "direct-file" }]
});

assert.match(studyBarHtml, /class="study-map"/);
assert.match(studyBarHtml, /笔记目录/);
assert.match(studyBarHtml, /3 个标题/);
assert.match(studyBarHtml, /1 个章节 · 1 个小节/);
assert.match(studyBarHtml, /画面切片/);
assert.match(studyBarHtml, /00:00:00 - 00:03:00/);
assert.match(studyBarHtml, /data-switch-result-tab="frames"/);
assert.match(studyBarHtml, /data-switch-result-tab="transcript"/);
assert.match(studyBarHtml, /\/api\/tasks\/task-study-map\/exports\/bundle/);
assert.doesNotMatch(studyBarHtml, /<script>bad/);
assert.match(studyBarHtml, /&lt;script&gt;bad\(\)&lt;\/script&gt; 课程/);

const taskOverviewHtml = context.taskOverview({
  id: "task-web-overview",
  title: "<script>bad()</script> 课程",
  status: "success",
  phase: "completed",
  progress: 100,
  source_type: "current_page",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/task-web-overview/media.mp4",
  selected_resource: {
    kind: "video",
    playback_match: "exact-src",
    content_length: 1048576,
    resolved_url: "https://cdn.example.com/final.mp4?token=abc"
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
assert.match(taskOverviewHtml, /导出本地视频/);
assert.match(taskOverviewHtml, /导出资料包/);
assert.match(taskOverviewHtml, /生成完整笔记/);
assert.match(taskOverviewHtml, /data-rerun-from-media="task-web-overview"/);
assert.match(taskOverviewHtml, /\/api\/tasks\/task-web-overview\/exports\/media/);
assert.match(taskOverviewHtml, /\/api\/tasks\/task-web-overview\/exports\/diagnostics/);
assert.match(taskOverviewHtml, /\/api\/tasks\/task-web-overview\/exports\/bundle/);
assert.match(taskOverviewHtml, /已完成直取下载/);
assert.match(taskOverviewHtml, /已跟踪最终 URL/);
assert.match(taskOverviewHtml, /阶段审计门/);
assert.match(taskOverviewHtml, /来源门/);
assert.match(taskOverviewHtml, /媒体门/);
assert.match(taskOverviewHtml, /转写门/);
assert.match(taskOverviewHtml, /切片门/);
assert.match(taskOverviewHtml, /总结门/);
assert.doesNotMatch(taskOverviewHtml, /<script>bad/);
assert.match(taskOverviewHtml, /&lt;script&gt;bad\(\)&lt;\/script&gt; 课程/);

const downloadedAuditItems = context.pipelineAuditItems({
  id: "audit-downloaded",
  status: "success",
  phase: "completed",
  source_type: "current_page",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/audit-downloaded/media.mp4",
  selected_resource: {
    kind: "hls",
    source: "webRequest",
    resolved_url: "https://cdn.example.com/master.m3u8"
  },
  options: { visual_understanding: true },
  download_attempts: [{ strategy: "manifest-ffmpeg" }]
});
assert.equal(JSON.stringify(downloadedAuditItems.map(item => item.state)), JSON.stringify(["pass", "pass", "warn", "warn", "warn"]));
const unsafeAuditHtml = context.pipelineAuditHtml({
  status: "failed",
  phase: "failed",
  source_type: "current_page",
  error_code: "<script>bad()</script>",
  selected_resource: { kind: "video", source: "webRequest" },
  download_attempts: []
});
assert.match(unsafeAuditHtml, /&lt;script&gt;bad\(\)&lt;\/script&gt;/);
assert.doesNotMatch(unsafeAuditHtml, /<script>bad/);
const fallbackTaskOverviewHtml = context.taskOverview({
  id: "task-web-fallback",
  title: "直取失败课程",
  status: "failed",
  phase: "failed",
  progress: 100,
  source_type: "current_page",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/task-web-fallback/note.md",
  transcript_path: "D:/Projects/learnnote-assistant/data/tasks/task-web-fallback/transcript.json",
  error_code: "download_forbidden",
  error_detail: "signed URL expired 已生成页面文本/浏览器字幕兜底笔记。",
  download_attempts: [
    {
      strategy: "direct-file",
      status: "failed",
      code: "download_forbidden",
      status_code: 403,
      message: "HTTP 403：Referer 或签名过期"
    },
    {
      strategy: "page-ytdlp",
      status: "failed",
      code: "download_forbidden",
      message: "yt-dlp no video"
    }
  ],
  options: {
    frame_interval: 20,
    grid_columns: 3,
    grid_rows: 3
  }
});
assert.match(fallbackTaskOverviewHtml, /class="task-overview status-failed"/);
assert.match(fallbackTaskOverviewHtml, /已生成兜底笔记/);
assert.match(fallbackTaskOverviewHtml, /导出 Markdown/);
assert.match(fallbackTaskOverviewHtml, /导出诊断/);
assert.match(fallbackTaskOverviewHtml, /导出资料包/);
const failureGuideHtml = context.failureGuide({
  status: "failed",
  error_code: "download_forbidden",
  note_path: "D:/note.md",
  download_attempts: [
    { strategy: "direct-file", code: "download_forbidden", status_code: 403, message: "<script>bad()</script> Referer expired" },
    { strategy: "page-ytdlp", code: "download_forbidden", message: "no fallback" }
  ]
});
assert.match(failureGuideHtml, /最近尝试：page-ytdlp · download_forbidden · no fallback/);
assert.match(failureGuideHtml, /后端已尝试 2 条路线/);
assert.match(failureGuideHtml, /已生成兜底笔记/);
assert.match(failureGuideHtml, /<ul>/);
assert.match(failureGuideHtml, /class="recovery-actions"/);
assert.match(failureGuideHtml, /data-recovery-source="local"/);
assert.match(failureGuideHtml, /data-switch-result-tab="diagnostics"/);
assert.match(failureGuideHtml, /导出 Markdown/);
assert.doesNotMatch(failureGuideHtml, /<script>bad/);
const diagnosticRecoveryHtml = context.diagnosticRecoveryHtml({
  id: "task-recovery",
  status: "success",
  media_path: "D:/media.mp4",
  note_path: "",
  selected_resource: {
    kind: "hls",
    request_headers: {
      Referer: "https://course.example.com/lesson",
      Cookie: "secret=bad"
    }
  },
  download_attempts: [
    { strategy: "direct-file", code: "download_forbidden", status_code: 403, message: "<script>bad()</script>" },
    { strategy: "manifest-ffmpeg", code: "unsupported_manifest" }
  ]
});
assert.match(diagnosticRecoveryHtml, /class="diagnostic-recovery"/);
assert.match(diagnosticRecoveryHtml, /下一步建议/);
assert.match(diagnosticRecoveryHtml, /后端已尝试 2 条路线/);
assert.match(diagnosticRecoveryHtml, /Referer/);
assert.match(diagnosticRecoveryHtml, /Cookie/);
assert.doesNotMatch(diagnosticRecoveryHtml, /secret=bad/);
assert.match(diagnosticRecoveryHtml, /继续切片总结/);
assert.match(diagnosticRecoveryHtml, /data-rerun-from-media="task-recovery"/);
assert.match(diagnosticRecoveryHtml, /\/api\/tasks\/task-recovery\/exports\/diagnostics/);
assert.match(diagnosticRecoveryHtml, /data-recovery-source="local"/);
assert.doesNotMatch(diagnosticRecoveryHtml, /<script>bad/);
assert.equal(context.hasTaskBundle({ media_path: "D:/media.mp4" }), true);
assert.equal(context.hasTaskBundle({ status: "failed", error_code: "download_forbidden" }), true);
assert.equal(context.hasTaskBundle({ download_attempts: [{ strategy: "direct-file" }] }), true);
assert.equal(context.hasTaskBundle({}), false);
assert.equal(context.hasTaskDiagnostics({ selected_resource: { kind: "video" } }), true);
assert.equal(context.hasTaskDiagnostics({ summary_diagnostics_path: "summary.json" }), true);
assert.equal(context.hasTaskDiagnostics({}), false);
assert.equal(context.canContinueFromDownloadedMedia({
  id: "task-downloaded",
  status: "success",
  media_path: "D:/media.mp4",
  note_path: ""
}), true);
assert.equal(context.canContinueFromDownloadedMedia({
  id: "task-processing-failed",
  status: "failed",
  media_path: "D:/media.mp4",
  note_path: ""
}), true);
assert.equal(context.canContinueFromDownloadedMedia({
  id: "task-running",
  status: "running",
  media_path: "D:/media.mp4",
  note_path: ""
}), false);
assert.equal(context.canContinueFromDownloadedMedia({
  id: "task-noted",
  status: "success",
  media_path: "D:/media.mp4",
  note_path: "D:/note.md"
}), false);
context.updateContinueFromMediaAction({
  id: "task-downloaded",
  status: "success",
  media_path: "D:/media.mp4",
  note_path: ""
});
assert.equal(elements.get("#continueFromMediaButton").hidden, false);
assert.equal(elements.get("#continueFromMediaButton").disabled, false);
context.updateContinueFromMediaAction({
  id: "task-noted",
  status: "success",
  media_path: "D:/media.mp4",
  note_path: "D:/note.md"
});
assert.equal(elements.get("#continueFromMediaButton").hidden, true);
assert.equal(elements.get("#continueFromMediaButton").disabled, true);

const failedMediaOverviewHtml = context.taskOverview({
  id: "task-failed-media",
  title: "Downloaded but processing failed",
  source_type: "current_page",
  status: "failed",
  phase: "failed",
  progress: 100,
  media_path: "D:/media.mp4",
  note_path: "",
  error_code: "processing_failed",
  error_detail: "Whisper failed",
  selected_resource: { kind: "video", source: "webRequest" },
  options: {},
  visual_windows: []
});
assert.match(failedMediaOverviewHtml, /data-rerun-from-media="task-failed-media"/);
assert.match(failedMediaOverviewHtml, /Whisper failed/);

const taskChipsHtml = context.taskChipsHtml({
  title: "<script>bad()</script>",
  status: "failed",
  source_type: "current_page",
  media_path: "D:/media.mp4",
  note_path: "D:/note.md",
  error_code: "download_forbidden",
  selected_resource: {
    kind: "hls",
    playback_match: "blob-source"
  },
  download_attempts: [{ strategy: "direct-file" }, { strategy: "page-ytdlp" }],
  visual_windows: [{ id: "W001" }, { id: "W002" }]
});
assert.match(taskChipsHtml, /task-chips/);
assert.match(taskChipsHtml, /HLS/);
assert.doesNotMatch(taskChipsHtml, /2 窗口/);
assert.match(taskChipsHtml, /2 次尝试/);
assert.match(taskChipsHtml, /download_forbidden/);
assert.doesNotMatch(taskChipsHtml, /<script>bad/);

const taskPreviewWithImage = context.taskPreviewHtml({
  status: "success",
  source_type: "current_page",
  visual_windows: [{
    id: "W001",
    start: 0,
    end: 180,
    frame_count: 9,
    grid_url: "/api/tasks/task-preview/assets/grid_000.jpg"
  }]
});
assert.match(taskPreviewWithImage, /class="task-preview status-success"/);
assert.match(taskPreviewWithImage, /<img src="\/api\/tasks\/task-preview\/assets\/grid_000.jpg"/);
assert.match(taskPreviewWithImage, /00:00:00 - 00:03:00/);

const taskPreviewFallback = context.taskPreviewHtml({
  status: "failed",
  source_type: "current_page",
  error_code: "drm_or_encrypted",
  selected_resource: { kind: "blob" }
});
assert.match(taskPreviewFallback, /class="task-preview status-failed empty"/);
assert.match(taskPreviewFallback, /drm_or_encrypted/);

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
    all_grids_had_images: true,
    missing_vision_image_window_ids: ["W001"],
    omitted_vision_window_ids: ["W081", "W082", "W083", "W084"],
    used_page_text_fallback: true,
    page_text_char_count: 18,
    browser_subtitle_count: 3,
    combined_text_char_count: 72
  }
});

assert.match(summaryDiagnostic, /已使用视觉 LLM/);
assert.match(summaryDiagnostic, /模型 vision-model/);
assert.match(summaryDiagnostic, /视觉窗口 2/);
assert.match(summaryDiagnostic, /送入视觉 2\/2/);
assert.match(summaryDiagnostic, /超限省略 1/);
assert.match(summaryDiagnostic, /缺图 W001/);
assert.match(summaryDiagnostic, /省略窗口 W081, W082, W083 等 4 个/);
assert.match(summaryDiagnostic, /页面文本 18 字/);
assert.match(summaryDiagnostic, /浏览器字幕 3 条/);
assert.match(summaryDiagnostic, /合并文本 72 字/);

const visualCoverageHtml = context.visualCoverageHtml({
  id: "task-visual-coverage",
  summary_warning: "<script>bad()</script> 降级",
  summary_diagnostics: {
    visual_window_count: 3,
    frame_grid_count: 3,
    vision_grid_count: 3,
    vision_image_count: 1,
    missing_vision_image_window_ids: ["W002"],
    omitted_vision_window_ids: ["W099"]
  },
  visual_windows: [
    {
      id: "W001",
      start: 0,
      end: 180,
      frame_count: 9,
      grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg"
    },
    {
      id: "W002",
      start: 180,
      end: 360,
      frame_count: 9,
      grid_url: ""
    },
    {
      id: "<script>bad()</script>",
      start: 360,
      end: 540,
      frame_count: 9,
      grid_url: ""
    }
  ]
});
assert.match(visualCoverageHtml, /class="visual-coverage"/);
assert.match(visualCoverageHtml, /视觉切片覆盖/);
assert.match(visualCoverageHtml, /3 个窗口/);
assert.match(visualCoverageHtml, /00:00:00 - 00:09:00/);
assert.match(visualCoverageHtml, /1\/3/);
assert.match(visualCoverageHtml, /缺图 W002/);
assert.match(visualCoverageHtml, /超限省略 W099/);
assert.match(visualCoverageHtml, /&lt;script&gt;bad\(\)&lt;\/script&gt;/);
assert.doesNotMatch(visualCoverageHtml, /<script>bad/);

const routeReadyHtml = context.browserRouteSummaryHtml({
  id: "route-ready",
  title: "<script>bad()</script> 课程",
  source_type: "current_page",
  status: "success",
  phase: "completed",
  progress: 100,
  media_path: "D:/Projects/learnnote-assistant/data/tasks/route-ready/media.mp4",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/route-ready/note.md",
  selected_resource: { kind: "hls" },
  visual_windows: [{ id: "W001", start: 0, end: 180, frame_count: 9 }],
  download_attempts: [{ strategy: "manifest-ffmpeg" }]
});
assert.match(routeReadyHtml, /browser-route-summary-card ready/);
assert.match(routeReadyHtml, /最近当前页直取已生成笔记/);
assert.match(routeReadyHtml, /hls · 1 次下载尝试 · 1 个视觉窗口/);
assert.doesNotMatch(routeReadyHtml, /<script>bad/);

const playerSourceOverview = context.taskOverview({
  id: "player-source-task",
  title: "播放器来源任务",
  source_type: "current_page",
  status: "success",
  phase: "completed",
  progress: 100,
  media_path: "D:/Projects/learnnote-assistant/data/tasks/player-source-task/media.mp4",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/player-source-task/note.md",
  selected_resource: {
    kind: "video",
    source: "pageHookPlayer",
    label: "DPlayer constructor switchVideo",
    url: "https://cdn.example.com/lesson.mp4?<script>bad()</script>"
  },
  summary_diagnostics: {
    visual_window_count: 0,
    frame_grid_count: 0,
    vision_grid_count: 0,
    vision_image_count: 0
  },
  options: {},
  visual_windows: []
});
assert.match(playerSourceOverview, /DPlayer 已加载源地址/);
assert.match(playerSourceOverview, /直取来源/);
assert.match(playerSourceOverview, /浏览器证据/);
assert.match(playerSourceOverview, /总结证据/);
assert.match(playerSourceOverview, /class="visual-coverage"/);
assert.match(playerSourceOverview, /等待抽帧生成视觉窗口/);
assert.doesNotMatch(playerSourceOverview, /<script>bad/);

const manifestGuessOverview = context.taskOverview({
  id: "manifest-guess-task",
  title: "Manifest guess task",
  source_type: "current_page",
  status: "failed",
  phase: "failed",
  progress: 100,
  error_code: "unsupported_manifest",
  selected_resource: {
    kind: "hls",
    source: "manifest-guess",
    label: "Guessed HLS manifest from segment directory",
    url: "https://cdn.example.com/live/master.m3u8"
  },
  options: {},
  download_attempts: [{ strategy: "manifest-ffmpeg", code: "unsupported_manifest" }],
  visual_windows: []
});
assert.match(manifestGuessOverview, /同目录 manifest 猜测/);
assert.match(manifestGuessOverview, /unsupported_manifest/);
assert.match(manifestGuessOverview, /下载路线/);
assert.match(manifestGuessOverview, /manifest-ffmpeg/);

const routeEvidenceItems = context.taskRouteEvidenceItems({
  source_type: "current_page",
  status: "failed",
  phase: "failed",
  error_code: "download_forbidden",
  selected_resource: {
    kind: "video",
    source: "webRequest",
    playback_match: "same-frame",
    mime: "video/mp4",
    content_length: 1048576,
    request_headers: {
      Referer: "https://course.example.com/lesson",
      Cookie: "secret=bad",
      Authorization: "Bearer bad"
    }
  },
  download_attempts: [
    { strategy: "direct-file", code: "download_forbidden", message: "<script>bad()</script>" }
  ],
  summary_source: "local-template",
  summary_diagnostics: {
    used_local_template: true,
    used_page_text_fallback: true,
    page_text_char_count: 24,
    browser_subtitle_count: 2,
    combined_text_char_count: 80
  }
});
assert.equal(routeEvidenceItems.length, 4);
assert.equal(routeEvidenceItems[2].value, "Referer");
assert.doesNotMatch(JSON.stringify(routeEvidenceItems), /secret=bad|Bearer bad/);
assert.match(context.taskRouteEvidenceHtml({
  source_type: "current_page",
  selected_resource: { kind: "video", source: "webRequest" },
  note_path: "D:/note.md",
  download_attempts: [{ strategy: "direct-file", code: "download_forbidden" }]
}), /route-evidence-strip/);
assert.match(context.taskRouteEvidenceHtml({
  source_type: "current_page",
  selected_resource: { kind: "video", source: "webRequest" },
  note_path: "D:/note.md",
  download_attempts: []
}), /已有笔记/);
assert.match(context.taskRouteEvidenceHtml({
  source_type: "current_page",
  selected_resource: { kind: "video", source: "webRequest" },
  note_path: "D:/note.md",
  download_attempts: []
}), /未记录总结诊断/);

const routeDownloadedHtml = context.browserRouteSummaryHtml({
  id: "route-downloaded",
  source_type: "current_page",
  status: "success",
  phase: "completed",
  progress: 100,
  media_path: "D:/Projects/learnnote-assistant/data/tasks/route-downloaded/media.mp4",
  note_path: "",
  selected_resource: { kind: "video" },
  download_attempts: [{ strategy: "direct-file" }]
});
assert.match(routeDownloadedHtml, /browser-route-summary-card downloaded/);
assert.match(routeDownloadedHtml, /视频已直取到本地/);
assert.match(routeDownloadedHtml, /继续切片总结/);

const routeBlockedHtml = context.browserRouteSummaryHtml({
  id: "route-blocked",
  source_type: "current_page",
  status: "failed",
  phase: "failed",
  progress: 100,
  error_code: "drm_or_encrypted",
  error_detail: "<script>bad()</script> encrypted"
});
assert.match(routeBlockedHtml, /browser-route-summary-card blocked/);
assert.match(routeBlockedHtml, /不会录制或绕过 DRM/);
assert.match(routeBlockedHtml, /本地视频兜底/);
assert.match(routeBlockedHtml, /&lt;script&gt;bad\(\)&lt;\/script&gt; encrypted/);
assert.doesNotMatch(routeBlockedHtml, /<script>bad/);

const browserWorkflowHtml = context.sourceWorkflowHtml("browser", {
  id: "task-workflow-browser",
  title: "Current page lesson",
  status: "running",
  phase: "downloading",
  progress: 35,
  source_type: "current_page",
  selected_resource: { kind: "hls" },
  download_attempts: [{ strategy: "manifest-ffmpeg" }],
  visual_windows: []
});
assert.match(browserWorkflowHtml, /class="source-workflow-card browser"/);
assert.match(browserWorkflowHtml, /当前页直取/);
assert.match(browserWorkflowHtml, /预检资源/);
assert.match(browserWorkflowHtml, /source-route-insights/);
assert.match(browserWorkflowHtml, /浏览器证据/);
assert.match(browserWorkflowHtml, /ffmpeg 合并|页面接口|候选资源|HLS|hls/);
assert.match(browserWorkflowHtml, /不录制、不刷课、不绕过 DRM/);
assert.match(browserWorkflowHtml, /source-workflow-actions/);
assert.match(browserWorkflowHtml, /data-source-workflow-action="refresh-browser"/);
assert.match(browserWorkflowHtml, /data-source-workflow-action="copy-backend"/);
assert.match(browserWorkflowHtml, /data-source-workflow-action="switch-local"/);
assert.match(browserWorkflowHtml, /class="active"/);
assert.match(browserWorkflowHtml, /data-select-workflow-task="task-workflow-browser"/);

const localWorkflowHtml = context.sourceWorkflowHtml("local", null);
assert.match(localWorkflowHtml, /本地视频/);
assert.match(localWorkflowHtml, /导入文件/);
assert.match(localWorkflowHtml, /本地文件直进管线/);
assert.match(localWorkflowHtml, /平台不暴露 URL 时兜底/);
assert.match(localWorkflowHtml, /data-source-workflow-action="choose-local"/);
assert.match(localWorkflowHtml, /data-source-workflow-action="upload-local"/);
assert.match(localWorkflowHtml, /选择入口后开始处理/);

const urlWorkflowHtml = context.sourceWorkflowHtml("url", {
  id: "task-workflow-url",
  title: "Manual lesson",
  status: "success",
  phase: "completed",
  progress: 100,
  source_type: "current_page",
  selected_resource: { kind: "dash", source: "manual", request_type: "manual-forced" },
  download_attempts: [{ strategy: "manifest-ffmpeg" }, { strategy: "direct-file" }],
  visual_windows: [{ id: "W001" }, { id: "W002" }]
});
assert.match(urlWorkflowHtml, /链接解析/);
assert.match(urlWorkflowHtml, /2 次下载尝试/);
assert.match(urlWorkflowHtml, /2 个视觉窗口/);
assert.match(urlWorkflowHtml, /data-source-workflow-action="preflight-url"/);
assert.match(urlWorkflowHtml, /data-source-workflow-action="start-url"/);
assert.match(urlWorkflowHtml, /data-source-workflow-action="download-url"/);

const failedWorkflowHtml = context.sourceWorkflowHtml("browser", {
  id: "task-workflow-failed",
  title: "Blocked page",
  status: "failed",
  phase: "failed",
  progress: 100,
  source_type: "current_page",
  error_code: "drm_or_encrypted",
  selected_resource: { kind: "blob" },
  download_attempts: []
});
assert.match(failedWorkflowHtml, /class="blocked"/);
assert.match(failedWorkflowHtml, /DRM/);

const routeEmptyHtml = context.browserRouteSummaryHtml(null);
assert.match(routeEmptyHtml, /等待扩展侧栏创建当前页任务/);
assert.match(routeEmptyHtml, /不做标签页录制/);
assert.match(routeEmptyHtml, /data-browser-route-action="refresh"/);
assert.match(routeEmptyHtml, /data-browser-route-action="copy-backend"/);
assert.match(routeEmptyHtml, /data-browser-route-action="local-video"/);

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
assert.match(timelineHtml, /字幕时间轴/);
assert.match(timelineHtml, /已按画面窗口对齐/);
assert.match(timelineHtml, /2<\/b>段字幕/);
assert.match(timelineHtml, /W001/);
assert.match(timelineHtml, /00:00:00 - 00:03:00/);
assert.match(timelineHtml, /第一段字幕/);
assert.match(timelineHtml, /W002/);
assert.match(timelineHtml, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
assert.doesNotMatch(timelineHtml, /<script>/);

const plainTimelineHtml = context.transcriptTimeline({
  source: "browser-subtitle",
  segments: [
    { start: 10, end: 13, text: "兜底字幕一" },
    { start: 20, end: 25, text: "兜底字幕二" }
  ]
}, {
  visual_windows: []
});
assert.match(plainTimelineHtml, /浏览器字幕/);
assert.match(plainTimelineHtml, /独立字幕时间轴/);
assert.match(plainTimelineHtml, /无切片/);
assert.match(plainTimelineHtml, /兜底字幕一/);

const posts = [];
const preflights = [];
let preflightDownloadable = true;
context.fetch = async (url, options = {}) => {
  const value = String(url);
  if (value.endsWith("/api/tasks/from-current-page")) {
    posts.push(JSON.parse(options.body));
    return { json: async () => ({ task_id: "task-url-direct" }) };
  }
  if (value.endsWith("/api/media/preflight")) {
    preflights.push(JSON.parse(options.body));
    return {
      json: async () => ({
        preflight: preflightDownloadable ? {
          ok: true,
          downloadable: true,
          kind: "hls",
          resolved_url: "https://cdn.example.com/archive/master.m3u8",
          content_type: "application/vnd.apple.mpegurl",
          status_code: 206,
          content_length: 123456,
          bytes_checked: 4096
        } : {
          ok: false,
          downloadable: false,
          code: "download_forbidden",
          message: "HTTP 403：Referer 或签名已过期"
        }
      })
    };
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
await context.startUrlTask("video");

assert.equal(posts.length, 1);
assert.equal(context.window.history.replacedUrls.at(-1), "/?task=task-url-direct&tab=note");
context.switchResultTab("frames");
assert.equal(context.window.history.replacedUrls.at(-1), "/?task=task-url-direct&tab=frames");
assert.equal(posts[0].mode, "video");
assert.equal(posts[0].resources.length, 1);
assert.equal(posts[0].resources[0].kind, "video");
assert.equal(posts[0].resources[0].source, "manual");
assert.equal(posts[0].resources[0].request_type, "manual-forced");
assert.equal(posts[0].resources[0].url, "https://cdn.example.com/api/play?id=shadow");

elements.get("#urlInput").value = "https://cdn.example.com/live/lesson.flv?token=abc";
elements.get("#urlMode").value = "auto";
await context.startUrlTask("video");

assert.equal(posts.length, 2);
assert.equal(posts[1].resources.length, 1);
assert.equal(posts[1].resources[0].kind, "video");
assert.equal(posts[1].resources[0].url, "https://cdn.example.com/live/lesson.flv?token=abc");

elements.get("#urlInput").value = "https://cdn.example.com/archive/lesson.avi?token=abc";
elements.get("#urlMode").value = "auto";
await context.startUrlTask("video");

assert.equal(posts.length, 3);
assert.equal(posts[2].resources.length, 1);
assert.equal(posts[2].resources[0].kind, "video");
assert.equal(posts[2].resources[0].url, "https://cdn.example.com/archive/lesson.avi?token=abc");

await context.startUrlTask("download_only");

assert.equal(posts.length, 4);
assert.equal(posts[3].mode, "download_only");
assert.equal(posts[3].resources.length, 1);
assert.equal(posts[3].resources[0].kind, "video");
assert.equal(posts[3].resources[0].url, "https://cdn.example.com/archive/lesson.avi?token=abc");
assert.equal(elements.get("#downloadUrlButton").disabled, false);

await context.preflightUrlTask();

assert.equal(preflights.length, 1);
assert.equal(preflights[0].resource.kind, "video");
assert.equal(preflights[0].resource.request_type, "manual-auto");
assert.equal(preflights[0].resource.url, "https://cdn.example.com/archive/lesson.avi?token=abc");
assert.match(elements.get("#urlModeHint").textContent, /预检通过/);
assert.match(elements.get("#urlModeHint").textContent, /120\.6 KB/);
assert.equal(elements.get("#preflightUrlButton").disabled, false);

await context.startUrlTask("video");

assert.equal(posts.length, 5);
assert.equal(posts[4].resources.length, 1);
assert.equal(posts[4].resources[0].url, "https://cdn.example.com/archive/lesson.avi?token=abc");
assert.equal(posts[4].resources[0].kind, "hls");
assert.equal(posts[4].resources[0].resolved_url, "https://cdn.example.com/archive/master.m3u8");
assert.equal(posts[4].resources[0].mime, "application/vnd.apple.mpegurl");
assert.equal(posts[4].resources[0].status_code, 206);
assert.equal(posts[4].resources[0].content_length, 123456);

preflightDownloadable = false;
await context.preflightUrlTask();

assert.equal(preflights.length, 2);
assert.match(elements.get("#urlModeHint").textContent, /预检未通过/);
assert.match(elements.get("#urlModeHint").textContent, /HTTP 403/);

const localUploads = [];
const droppedFile = { name: "drag-local-lesson.mkv", type: "", size: 456789 };
context.fetch = async (url, options = {}) => {
  const value = String(url);
  if (value.endsWith("/api/tasks/from-local")) {
    localUploads.push(options.body);
    return { json: async () => ({ task_id: "task-local-drop" }) };
  }
  if (value.endsWith("/api/tasks")) {
    return {
      json: async () => ({
        tasks: [{
          id: "task-local-drop",
          title: "drag-local-lesson.mkv",
          status: "queued",
          phase: "queued",
          progress: 0,
          source_type: "local",
          visual_windows: []
        }]
      })
    };
  }
  return { ok: false, json: async () => ({}), text: async () => "" };
};

await elements.get("#dropzone").listeners.drop({
  preventDefault() {},
  dataTransfer: { files: [droppedFile] }
});
await new Promise(resolve => setTimeout(resolve, 0));

assert.equal(localUploads.length, 1);
assert.equal(localUploads[0].get("file"), droppedFile);
assert.equal(localUploads[0].get("title"), "drag-local-lesson.mkv");
assert.match(localUploads[0].get("options"), /"visual_understanding":true/);
assert.equal(elements.get("#fileName").textContent, "drag-local-lesson.mkv");
assert.equal(elements.get("#uploadButton").disabled, false);

let rejectedUploadCalled = false;
context.fetch = async url => {
  const value = String(url);
  if (value.endsWith("/api/tasks/from-local")) {
    rejectedUploadCalled = true;
    return {
      ok: false,
      json: async () => ({
        detail: {
          code: "unsupported_local_file",
          message: "本地视频仅支持 mp4、m4v、mov、mkv、webm、flv、avi。"
        }
      })
    };
  }
  return { ok: false, json: async () => ({}), text: async () => "" };
};

elements.get("#fileInput").files = [{ name: "server-reject.mov", type: "video/quicktime", size: 128 }];
await context.uploadSelectedFile();

assert.equal(rejectedUploadCalled, true);
assert.match(elements.get("#fileName").textContent, /本地视频仅支持/);
assert.equal(elements.get("#uploadButton").disabled, false);

let unsupportedFetchCalled = false;
context.fetch = async () => {
  unsupportedFetchCalled = true;
  return { ok: false, json: async () => ({}), text: async () => "" };
};

elements.get("#fileInput").files = [{ name: "notes.txt", type: "text/plain", size: 64 }];
await context.uploadSelectedFile();

assert.equal(unsupportedFetchCalled, false);
assert.match(elements.get("#fileName").textContent, /暂不支持/);
