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
  addEventListener() {},
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
    location: { origin: "http://127.0.0.1:8765", assign() {} },
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

await new Promise(resolve => setTimeout(resolve, 0));
assert.match(elements.get("#detail").innerHTML, /class="empty-workbench"/);
assert.match(elements.get("#detail").innerHTML, /当前页直取/);
assert.match(elements.get("#detail").innerHTML, /不.*录制页面/);
assert.equal(elements.get("#copyButton").disabled, true);

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
assert.match(visualDeckHtml, /src="http:\/\/127\.0\.0\.1:8765\/api\/tasks\/demo\/grids\/grid_000\.jpg"/);
assert.doesNotMatch(visualDeckHtml, /src="javascript:alert/);
assert.match(visualDeckHtml, /&lt;script&gt;alert\(1\)&lt;\/script&gt; PPT 演示/);
assert.match(visualDeckHtml, /data-switch-result-tab="transcript"/);
assert.match(visualDeckHtml, /data-switch-result-tab="note"/);
assert.doesNotMatch(visualDeckHtml, /<script>bad/);

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
    content_length: 1048576
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
assert.doesNotMatch(taskOverviewHtml, /<script>bad/);
assert.match(taskOverviewHtml, /&lt;script&gt;bad\(\)&lt;\/script&gt; 课程/);
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
assert.match(taskChipsHtml, /hls/);
assert.match(taskChipsHtml, /2 视觉窗口/);
assert.match(taskChipsHtml, /2 次下载尝试/);
assert.match(taskChipsHtml, /download_forbidden/);
assert.doesNotMatch(taskChipsHtml, /<script>bad/);

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
assert.match(routeBlockedHtml, /&lt;script&gt;bad\(\)&lt;\/script&gt; encrypted/);
assert.doesNotMatch(routeBlockedHtml, /<script>bad/);

const routeEmptyHtml = context.browserRouteSummaryHtml(null);
assert.match(routeEmptyHtml, /等待扩展侧栏创建当前页任务/);
assert.match(routeEmptyHtml, /不做标签页录制/);

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
          kind: "video",
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
assert.equal(posts[0].mode, "video");
assert.equal(posts[0].resources.length, 1);
assert.equal(posts[0].resources[0].kind, "video");
assert.equal(posts[0].resources[0].source, "manual");
assert.equal(posts[0].resources[0].request_type, "manual-forced");
assert.equal(posts[0].resources[0].url, "https://cdn.example.com/api/play?id=shadow");

await context.startUrlTask("download_only");

assert.equal(posts.length, 2);
assert.equal(posts[1].mode, "download_only");
assert.equal(posts[1].resources.length, 1);
assert.equal(posts[1].resources[0].kind, "video");
assert.equal(posts[1].resources[0].request_type, "manual-forced");
assert.equal(elements.get("#downloadUrlButton").disabled, false);

await context.preflightUrlTask();

assert.equal(preflights.length, 1);
assert.equal(preflights[0].resource.kind, "video");
assert.equal(preflights[0].resource.request_type, "manual-forced");
assert.match(elements.get("#urlModeHint").textContent, /预检通过/);
assert.match(elements.get("#urlModeHint").textContent, /120\.6 KB/);
assert.equal(elements.get("#preflightUrlButton").disabled, false);

preflightDownloadable = false;
await context.preflightUrlTask();

assert.equal(preflights.length, 2);
assert.match(elements.get("#urlModeHint").textContent, /预检未通过/);
assert.match(elements.get("#urlModeHint").textContent, /HTTP 403/);
