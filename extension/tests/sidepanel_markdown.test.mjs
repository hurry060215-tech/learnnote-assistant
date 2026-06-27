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

const visualDeckHtml = context.visualStudyDeck({
  id: "side-visual-deck",
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
      transcript_excerpt: "<script>alert(1)</script> 画面摘要"
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
assert.match(visualDeckHtml, /class="side-visual-study"/);
assert.match(visualDeckHtml, /视觉窗口复习/);
assert.match(visualDeckHtml, /2 窗口 · 00:00:00 - 00:06:00/);
assert.match(visualDeckHtml, /导出切片索引/);
assert.match(visualDeckHtml, /data-export="visual-windows"/);
assert.match(visualDeckHtml, /src="http:\/\/127\.0\.0\.1:8765\/api\/tasks\/demo\/grids\/grid_000\.jpg"/);
assert.doesNotMatch(visualDeckHtml, /src="javascript:alert/);
assert.match(visualDeckHtml, /&lt;script&gt;alert\(1\)&lt;\/script&gt; 画面摘要/);
assert.match(visualDeckHtml, /data-switch-result-tab="transcript"/);
assert.match(visualDeckHtml, /data-switch-result-tab="note"/);
assert.doesNotMatch(visualDeckHtml, /<script>bad/);

const studyMapHtml = context.noteStudyMap(`# <script>bad()</script> 课程

## 第一节
### 画面演示
`, {
  id: "side-study-map",
  title: "<script>bad()</script> 课程",
  status: "success",
  phase: "completed",
  progress: 100,
  source_type: "current_page",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/side-study-map/media.mp4",
  transcript_path: "D:/Projects/learnnote-assistant/data/tasks/side-study-map/transcript.json",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/side-study-map/note.md",
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

assert.match(studyMapHtml, /class="study-map"/);
assert.match(studyMapHtml, /学习导览/);
assert.match(studyMapHtml, /笔记目录/);
assert.match(studyMapHtml, /3 个标题/);
assert.match(studyMapHtml, /1 个章节 · 1 个小节/);
assert.match(studyMapHtml, /画面切片/);
assert.match(studyMapHtml, /00:00:00 - 00:03:00/);
assert.match(studyMapHtml, /data-switch-result-tab="frames"/);
assert.match(studyMapHtml, /data-switch-result-tab="transcript"/);
assert.match(studyMapHtml, /data-export="bundle"/);
assert.doesNotMatch(studyMapHtml, /<script>bad/);
assert.match(studyMapHtml, /&lt;script&gt;bad\(\)&lt;\/script&gt; 课程/);

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
assert.match(taskOverviewHtml, /data-export="diagnostics"/);
assert.match(taskOverviewHtml, /data-export="bundle"/);
assert.match(taskOverviewHtml, /生成完整笔记/);
assert.match(taskOverviewHtml, /data-rerun-from-media="side-overview"/);
assert.match(taskOverviewHtml, /已完成直取下载/);
assert.doesNotMatch(taskOverviewHtml, /<script>bad/);
assert.match(taskOverviewHtml, /&lt;script&gt;bad\(\)&lt;\/script&gt; 课程/);
const fallbackOverviewHtml = context.taskOverview({
  id: "side-fallback",
  title: "直取失败课程",
  status: "failed",
  phase: "failed",
  progress: 100,
  source_type: "current_page",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/side-fallback/note.md",
  transcript_path: "D:/Projects/learnnote-assistant/data/tasks/side-fallback/transcript.json",
  error_code: "download_forbidden",
  error_detail: "signed URL expired 已生成页面文本/浏览器字幕兜底笔记。",
  options: {
    frame_interval: 20,
    grid_columns: 3,
    grid_rows: 3
  }
});
assert.match(fallbackOverviewHtml, /class="task-overview status-failed"/);
assert.match(fallbackOverviewHtml, /已生成兜底笔记/);
assert.match(fallbackOverviewHtml, /data-export="markdown"/);
assert.match(fallbackOverviewHtml, /data-export="diagnostics"/);
assert.match(fallbackOverviewHtml, /download_forbidden/);
assert.equal(context.hasTaskBundle({ media_path: "D:/media.mp4" }), true);
assert.equal(context.hasTaskBundle({ status: "failed", error_code: "download_forbidden" }), true);
assert.equal(context.hasTaskBundle({ download_attempts: [{ strategy: "direct-file" }] }), true);
assert.equal(context.hasTaskBundle({}), false);
assert.equal(context.hasTaskDiagnostics({ selected_resource: { kind: "video" } }), true);
assert.equal(context.hasTaskDiagnostics({ summary_diagnostics_path: "summary.json" }), true);
assert.equal(context.hasTaskDiagnostics({}), false);
const diagnosticRecoveryHtml = context.diagnosticRecoveryHtml({
  id: "side-recovery",
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
assert.doesNotMatch(diagnosticRecoveryHtml, /<script>bad/);

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
assert.match(context.directnessText({
  kind: "hls",
  source: "pageHookPlayer",
  label: "hls.js loadSource"
}), /hls\.js 已加载 HLS manifest/);
assert.deepEqual([...context.resourceEvidenceTags({
  kind: "hls",
  source: "pageHookPlayer",
  label: "hls.js loadSource"
})], ["可合并 manifest", "hls.js 已加载源地址", "页面接口"]);
assert.match(context.resourceReasonText({
  kind: "dash",
  source: "pageHookPlayer",
  label: "dash.js attachSource"
}), /dash\.js 已加载源地址/);
assert.match(context.requestEvidence({
  kind: "dash",
  source: "pageHookPlayer",
  label: "dash.js attachSource",
  mime: "application/dash+xml"
}), /dash\.js 已加载源地址/);
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
assert.equal(context.candidateStrategyText({ kind: "hls" }), "ffmpeg 合并");
assert.equal(context.candidateStrategyText({ kind: "video" }), "直接下载");
assert.equal(context.candidateStrategyText({ kind: "blob" }), "不可直接下载");

assert.match(context.preflightRecoveryText({ code: "auth_required" }), /已登录/);
assert.match(context.preflightRecoveryText({ code: "drm_or_encrypted" }), /不会录制/);
assert.match(context.preflightRecoveryText({ code: "download_forbidden" }), /Referer/);
assert.match(context.preflightRecoveryText({ downloadable: true, kind: "video" }), /完整总结/);

vm.runInContext(`
page = {
  page_url: "https://course.example.com/lesson",
  active_video: { src: "blob:https://course.example.com/video", drm_detected: false, paused: false },
  browser_subtitles: [{ start: 0, end: 2, text: "浏览器字幕" }]
};
resources = [{
  url: "https://cdn.example.com/live/master.m3u8",
  kind: "hls",
  source: "webRequest",
  score: 98,
  label: "<script>bad()</script>",
  playback_match: "blob-source"
}];
selectedResourceUrl = "https://cdn.example.com/live/master.m3u8";
preflight = null;
preflightResourceUrl = "";
preflightResultsByUrl = new Map();
`, context);
assert.equal(context.routeSummaryState(), "candidate");
assert.match(context.routeSummaryCopy("candidate").title, /已找到可直取候选/);
assert.equal(context.candidateTryOrder(context.selectedResource()), 1);
assert.equal(context.currentStudyState(), "candidate");
assert.match(context.currentStudyCopy("candidate").title, /发现当前视频直取候选/);
assert.match(context.currentStudyActionText("candidate"), /预检资源/);
assert.deepEqual(JSON.parse(JSON.stringify(context.currentStudyMetrics().map(item => item.label))), ["播放时间", "直取路线", "字幕兜底", "画面切片"]);
assert.match(context.currentStudyMetrics()[1].value, /hls · ffmpeg 合并/);
assert.match(context.resourcePriorityBadgeHtml(context.selectedResource()), /第 1 顺位/);
assert.match(context.resourcePriorityBadgeHtml(context.selectedResource()), /ffmpeg 合并/);
assert.match(context.resourceAttemptQueueHtml(), /resource-attempt-queue/);
assert.match(context.resourceAttemptQueueHtml(), /下载队列/);
assert.match(context.resourceAttemptQueueHtml(), /待预检/);
context.renderRouteSummary();
assert.match(elements.get("#routeSummary").innerHTML, /待预检/);
assert.doesNotMatch(elements.get("#routeSummary").innerHTML, /<script>bad/);
context.renderContext();
assert.match(elements.get("#resources").innerHTML, /第 1 顺位/);
assert.match(elements.get("#resources").innerHTML, /ffmpeg 合并/);
assert.match(elements.get("#resources").innerHTML, /resource-attempt-row selected/);
assert.doesNotMatch(elements.get("#resources").innerHTML, /<script>bad/);
assert.match(elements.get("#currentStudyCard").className, /candidate/);
assert.match(elements.get("#currentStudyCard").innerHTML, /发现当前视频直取候选/);
assert.match(elements.get("#currentStudyCard").innerHTML, /00:00:00 \/ 00:00:00/);
assert.match(elements.get("#currentStudyCard").innerHTML, /1 条/);
assert.equal(context.playbackReadinessState(), "ready");
assert.match(elements.get("#playbackReadiness").innerHTML, /已读取当前播放视频/);
assert.match(elements.get("#playbackReadiness").innerHTML, /1\/1 匹配/);
assert.match(elements.get("#playbackReadiness").innerHTML, /1 条/);

vm.runInContext(`
preflight = { downloadable: true, kind: "hls", code: "", message: "ok" };
preflightResourceUrl = "https://cdn.example.com/live/master.m3u8";
preflightResultsByUrl = new Map([["https://cdn.example.com/live/master.m3u8", preflight]]);
`, context);
assert.equal(context.routeSummaryState(), "ready");
assert.equal(context.currentStudyState(), "ready");
assert.match(context.currentStudyActionText("ready"), /总结当前视频/);
assert.match(context.resourceAttemptQueueHtml(), /预检通过/);
context.renderRouteSummary();
assert.match(elements.get("#routeSummary").innerHTML, /直取路线已验证/);
assert.match(elements.get("#routeSummary").innerHTML, /预检通过/);
context.renderCurrentStudyCard();
assert.match(elements.get("#currentStudyCard").className, /ready/);
assert.match(elements.get("#currentStudyCard").innerHTML, /可以开始当前视频总结/);

vm.runInContext(`
page = {
  page_url: "https://course.example.com/drm",
  drm_detected: true,
  active_video: { src: "blob:https://course.example.com/drm", drm_detected: true },
  browser_subtitles: []
};
resources = [];
selectedResourceUrl = "";
preflight = null;
preflightResourceUrl = "";
preflightResultsByUrl = new Map();
`, context);
assert.equal(context.routeSummaryState(), "blocked");
assert.match(context.routeSummaryCopy("blocked").action, /不会录制/);
assert.equal(context.currentStudyState(), "blocked");
assert.match(context.currentStudyCopy("blocked").detail, /不会录制/);
assert.match(context.currentStudyActionText("blocked"), /本地视频上传/);
context.renderContext();
assert.equal(context.playbackReadinessState(), "blocked");
assert.match(elements.get("#playbackReadiness").className, /blocked/);
assert.match(elements.get("#playbackReadiness").innerHTML, /DRM/);
assert.match(elements.get("#currentStudyCard").className, /blocked/);
assert.match(elements.get("#currentStudyCard").innerHTML, /当前页不能直接下载/);
