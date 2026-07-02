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

const clipboardWrites = [];
const openedTabs = [];

const context = {
  console,
  document: documentStub,
  location: { href: "file:///sidepanel.html" },
  navigator: { clipboard: { writeText(value) { clipboardWrites.push(value); } } },
  window: { open(url, target, features) { openedTabs.push({ url, target, features }); } },
  FormData: class FormData {},
  fetch: async url => {
    const value = String(url);
    if (value.endsWith("/health")) {
      return { json: async () => ({ ffmpeg: true, ffprobe: false, ffprobe_optional: true, duration_probe: "ffmpeg", vision_model_configured: true, default_llm_model: "gpt-4.1-mini" }) };
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
await new Promise(resolve => setTimeout(resolve, 0));
assert.equal(elements.get("#backendStatus").classList.contains("backend-status-grid"), true);
assert.match(elements.get("#backendStatus").innerHTML, /backend-status-chip bridge/);
assert.match(elements.get("#backendStatus").innerHTML, /当前标签页/);
assert.match(elements.get("#backendStatus").innerHTML, /backend-status-chip media/);
assert.match(elements.get("#backendStatus").innerHTML, /gpt-4\.1-mini/);
assert.match(elements.get("#backendStatus").title, /视觉模型/);

vm.runInContext("captureLog = { restored: 3, updated_at: Date.now() - 45000 }", context);
const captureHint = context.captureLogHintHtml();
assert.match(captureHint, /Network 捕获缓存已合并 3 条候选/);
assert.match(captureHint, /45s ago/);

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
    llm_provider: "openrouter",
    llm_base_host: "openrouter.ai",
    llm_failure_stage: "vision_merge",
    llm_failure_code: "api_error",
    llm_failure_reason: "HTTP 429",
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

assert.match(summaryDiagnostic, /Provider openrouter/);
assert.match(summaryDiagnostic, /Base openrouter\.ai/);
assert.match(summaryDiagnostic, /LLM 失败 vision_merge\/api_error/);
assert.match(summaryDiagnostic, /原因 HTTP 429/);

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
  id: "side-visual-coverage",
  summary_diagnostics: {
    visual_window_count: 3,
    frame_grid_count: 3,
    vision_grid_count: 3,
    vision_image_count: 1,
    missing_vision_image_window_ids: ["W002"],
    omitted_vision_window_ids: ["W099"],
    summary_warning: "<script>bad()</script> 降级"
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

const visionEvidenceStrongHtml = context.visionEvidenceBar({
  id: "side-vision-strong",
  status: "success",
  phase: "completed",
  source_type: "current_page",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/side-vision-strong/media.mp4",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/side-vision-strong/note.md",
  summary_source: "vision-llm",
  options: { visual_understanding: true },
  summary_diagnostics: {
    used_vision_llm: true,
    frame_grid_count: 2,
    vision_grid_count: 2,
    vision_image_count: 2
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
      grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_001.jpg"
    }
  ]
});
assert.match(visionEvidenceStrongHtml, /class="vision-evidence strong"/);
assert.match(visionEvidenceStrongHtml, /画面已参与图文总结/);
assert.match(visionEvidenceStrongHtml, /2\/2/);
assert.match(visionEvidenceStrongHtml, /data-switch-result-tab="frames"/);
assert.match(visionEvidenceStrongHtml, /data-switch-result-tab="diagnostics"/);
assert.match(visionEvidenceStrongHtml, /data-export="bundle"/);
assert.match(visionEvidenceStrongHtml, /data-export="manifest"/);

const visionEvidencePartialHtml = context.visionEvidenceBar({
  id: "side-vision-partial",
  status: "success",
  phase: "completed",
  source_type: "current_page",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/side-vision-partial/note.md",
  summary_source: "text-llm",
  options: { visual_understanding: true },
  summary_diagnostics: {
    used_text_llm: true,
    frame_grid_count: 3,
    vision_grid_count: 3,
    vision_image_count: 1,
    missing_vision_image_window_ids: ["W002"],
    omitted_vision_window_ids: ["W099"],
    summary_warning: "<script>bad()</script> 降级"
  },
  visual_windows: [
    { id: "W001", start: 0, end: 180, grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg" },
    { id: "W002", start: 180, end: 360, grid_url: "" }
  ]
});
assert.match(visionEvidencePartialHtml, /class="vision-evidence partial"/);
assert.match(visionEvidencePartialHtml, /模型链路存在降级/);
assert.match(visionEvidencePartialHtml, /缺图 W002/);
assert.match(visionEvidencePartialHtml, /超限省略 W099/);
assert.match(visionEvidencePartialHtml, /&lt;script&gt;bad\(\)&lt;\/script&gt; 降级/);
assert.doesNotMatch(visionEvidencePartialHtml, /<script>bad/);

const visionEvidenceSkipHtml = context.visionEvidenceBar({
  id: "side-vision-skip",
  status: "success",
  phase: "completed",
  source_type: "page_text",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/side-vision-skip/note.md",
  options: { visual_understanding: false },
  summary_diagnostics: {
    used_page_text_fallback: true,
    combined_text_char_count: 88
  }
});
assert.match(visionEvidenceSkipHtml, /class="vision-evidence skip"/);
assert.match(visionEvidenceSkipHtml, /本任务走文本路线/);
assert.doesNotMatch(visionEvidenceSkipHtml, /data-switch-result-tab="frames"/);

const routeEvidenceItems = context.taskRouteEvidenceItems({
  source_type: "current_page",
  status: "failed",
  phase: "failed",
  error_code: "download_forbidden",
  selected_resource: {
    kind: "video",
    source: "webRequest",
    url: "https://course.example.com/player/video?id=1",
    resolved_url: "https://cdn.example.com/final.mp4?token=abc",
    playback_match: "same-frame",
    mime: "video/mp4",
    content_length: 1048576,
    mse_append_count: 12,
    mse_append_total_bytes: 2097152,
    mse_append_magic: "ftyp",
    mse_append_mime: "video/mp4",
    mse_append_detected_kind: "video",
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
assert.match(routeEvidenceItems[2].detail, /MSE append 12x ftyp 2\.0 MB video\/mp4/);
assert.match(JSON.stringify(routeEvidenceItems), /final\.mp4\?token=abc/);
assert.doesNotMatch(JSON.stringify(routeEvidenceItems), /secret=bad|Bearer bad/);
assert.match(context.taskBrowserEvidenceHtml({
  source_type: "current_page",
  active_video: { src: "blob:https://course.example.com/player", current_time: 12, duration: 120, paused: false },
  selected_resource: {
    kind: "blob",
    source: "pageHookMse",
    url: "blob:https://course.example.com/player",
    blob_url: "blob:https://course.example.com/player",
    mse_append_count: 12,
    mse_append_total_bytes: 2097152,
    mse_append_magic: "ftyp",
    mse_append_mime: "video/mp4",
    mse_append_detected_kind: "video"
  }
}), /MSE append 12x ftyp 2\.0 MB video\/mp4/);
assert.match(context.taskRouteEvidenceHtml({
  source_type: "current_page",
  selected_resource: {
    kind: "video",
    source: "webRequest",
    url: "https://course.example.com/player/video?id=1",
    resolved_url: "https://cdn.example.com/final.mp4?token=abc"
  },
  note_path: "D:/note.md",
  download_attempts: [{ strategy: "direct-file", code: "download_forbidden" }]
}), /final\.mp4\?token=abc/);
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

const rerunRouteEvidenceHtml = context.taskRouteEvidenceHtml({
  mode: "rerun_from_media",
  source_type: "local",
  source_task_id: "download-only-task<script>bad()</script>",
  source_media_path: "D:/Projects/learnnote-assistant/data/tasks/download-only-task/media.mp4",
  reuse: {
    source_task_id: "download-only-task<script>bad()</script>",
    source_media_path: "D:/Projects/learnnote-assistant/data/tasks/download-only-task/media.mp4"
  },
  media_path: "D:/Projects/learnnote-assistant/data/tasks/rerun-task/media.mp4",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/rerun-task/note.md",
  selected_resource: { kind: "video", source: "webRequest" },
  download_attempts: [{ strategy: "direct-file", status: "success" }]
});
assert.match(rerunRouteEvidenceHtml, /复用来源/);
assert.match(rerunRouteEvidenceHtml, /download-only-task/);
assert.match(rerunRouteEvidenceHtml, /media\.mp4/);
assert.match(rerunRouteEvidenceHtml, /&lt;script&gt;bad\(\)&lt;\/script&gt;/);
assert.doesNotMatch(rerunRouteEvidenceHtml, /<script>bad/);

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
assert.equal(context.transcriptSourceText("embedded-subtitle"), "视频内嵌字幕");
const embeddedTimelineHtml = context.transcriptTimeline({
  source: "embedded-subtitle",
  segments: [
    { start: 0, end: 2, text: "内嵌字幕" }
  ]
}, {
  visual_windows: []
});
assert.match(embeddedTimelineHtml, /视频内嵌字幕/);

const railHtml = context.noteVisualRail({
  visual_windows: [
    {
      id: "W001",
      start: 0,
      end: 180,
      frame_count: 9,
      frame_timestamps: [0, 20, 40, 60, 80],
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
      frame_timestamps: [0, 20, 40, 60, 80],
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
assert.match(visualDeckHtml, /回看检查点/);
assert.match(visualDeckHtml, /00:00:00/);
assert.match(visualDeckHtml, /对照画面确认对应的板书、PPT、代码或操作步骤/);
assert.match(visualDeckHtml, /class="side-visual-study-questions"/);
assert.match(visualDeckHtml, /自测问题/);
assert.match(visualDeckHtml, /这句“&lt;script&gt;alert\(1\)&lt;\/script&gt; 画面摘要”在画面中对应的标题、公式、代码或操作状态是什么？/);
assert.match(visualDeckHtml, /00:00:00 \/ 00:00:20 \/ 00:00:40 \/ 00:01:00\.\.\./);
assert.doesNotMatch(visualDeckHtml, /src="javascript:alert/);
assert.match(visualDeckHtml, /&lt;script&gt;alert\(1\)&lt;\/script&gt; 画面摘要/);
assert.match(visualDeckHtml, /data-switch-result-tab="transcript"/);
assert.match(visualDeckHtml, /data-switch-result-tab="note"/);
assert.match(visualDeckHtml, /data-media-seek-time="0\.000"/);
assert.match(visualDeckHtml, /data-window-start="180\.000"/);
assert.match(visualDeckHtml, />回看此段<\/button>/);
assert.doesNotMatch(visualDeckHtml, /<script>bad/);

const visualDeckWithTranscriptHtml = context.visualStudyDeck({
  id: "side-visual-transcript",
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
assert.match(visualDeckWithTranscriptHtml, /1 窗口 · 2 段字幕已同步/);
assert.match(visualDeckWithTranscriptHtml, /class="side-visual-study-cues"/);
assert.match(visualDeckWithTranscriptHtml, /00:00:12/);
assert.match(visualDeckWithTranscriptHtml, /data-media-seek-time="12\.000"/);
assert.match(visualDeckWithTranscriptHtml, /data-media-seek-time="45\.000"/);
assert.match(visualDeckWithTranscriptHtml, /老师讲解概念定义/);
assert.match(visualDeckWithTranscriptHtml, /&lt;script&gt;alert\(1\)&lt;\/script&gt; 例题演示/);
assert.match(visualDeckWithTranscriptHtml, /回看检查点/);
assert.match(visualDeckWithTranscriptHtml, /自测问题/);
assert.match(visualDeckWithTranscriptHtml, /这句“老师讲解概念定义”在画面中对应的标题、公式、代码或操作状态是什么？/);
assert.match(visualDeckWithTranscriptHtml, /核对截图里的板书/);
assert.doesNotMatch(visualDeckWithTranscriptHtml, /不属于这个窗口/);
assert.doesNotMatch(visualDeckWithTranscriptHtml, /<script>/);

const mediaPreviewHtml = context.mediaPreviewHtml({
  id: "side-media-preview",
  title: "本地回看",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/side-media-preview/media.mp4",
  status: "success"
});
assert.match(mediaPreviewHtml, /data-learning-video/);
assert.match(mediaPreviewHtml, /点击字幕或视觉窗口时间可回看对应画面/);

const transcriptSeekHtml = context.transcriptTimeline({
  source: "whisper",
  segments: [
    { start: 12, end: 18, text: "第一句" },
    { start: 190, end: 195, text: "第二句" }
  ]
}, {
  id: "side-transcript-seek",
  title: "转写回看",
  visual_windows: [{
    id: "W001",
    start: 0,
    end: 180,
    frame_count: 9,
    grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg"
  }]
});
assert.match(transcriptSeekHtml, /class="transcript-window"/);
assert.match(transcriptSeekHtml, /data-media-seek-time="0\.000"/);
assert.match(transcriptSeekHtml, /data-media-seek-time="12\.000"/);
assert.match(transcriptSeekHtml, /data-line-time="190\.000"/);

const seekVideo = documentStub.querySelector("[data-learning-video]");
let playCalls = 0;
seekVideo.play = () => {
  playCalls += 1;
  return Promise.resolve();
};
assert.equal(context.seekLearningVideo(42.25), true);
assert.equal(seekVideo.currentTime, 42.25);
assert.equal(playCalls, 1);
assert.equal(seekVideo.classList.contains("media-seek-active"), true);

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
assert.match(studyMapHtml, /data-export="manifest"/);
assert.doesNotMatch(studyMapHtml, /<script>bad/);
assert.match(studyMapHtml, /&lt;script&gt;bad\(\)&lt;\/script&gt; 课程/);

const taskOverviewHtml = context.taskOverview({
  id: "side-overview",
  title: "<script>bad()</script> 课程",
  status: "success",
  phase: "completed",
  progress: 100,
  source_type: "current_page",
  mode: "download_only",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/side-overview/media.mp4",
  active_video: {
    src: "blob:https://course.example.com/current-player",
    current_time: 42,
    duration: 600,
    width: 1280,
    height: 720,
    frame_id: 7,
    paused: false
  },
  selected_resource: {
    url: "https://cdn.example.com/source.mp4?token=abc",
    kind: "video",
    playback_match: "exact-src",
    content_length: 2097152,
    resolved_url: "https://cdn.example.com/final.mp4?token=abc",
    frame_url: "https://course.example.com/player/frame.html",
    blob_url: "blob:https://course.example.com/current-player",
    request_headers: {
      Referer: "https://course.example.com/lesson",
      Cookie: "secret=1",
      Authorization: "Bearer secret"
    }
  },
  direct_extraction: {
    no_tab_recording: true,
    no_drm_bypass: true,
    route: "download_only_to_local_media",
    media_landed: true,
    media_reusable: true,
    selected_candidate: {
      kind: "hls",
      source: "webRequest",
      playback_match: "blob-source",
      safe_request_header_names: ["Referer", "Origin", "Cookie", "Authorization"]
    },
    browser_context: {
      active_source_type: "blob",
      browser_subtitle_count: 2,
      cookie_domain_count: 1
    },
    download: {
      successful_attempt_count: 1,
      failed_attempt_count: 0,
      strategy_order: ["manifest-ffmpeg", "yt-dlp-page"]
    },
    processing: {
      download_only: true,
      transcript_ready: false,
      frame_grid_count: 0,
      visual_window_count: 0,
      note_ready: false
    },
    boundary: "normal_accessible_media_only"
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
assert.match(taskOverviewHtml, /data-open-workbench="side-overview"/);
assert.match(taskOverviewHtml, /Web 工作台/);
assert.match(taskOverviewHtml, /data-export="media"/);
assert.match(taskOverviewHtml, /data-export="diagnostics"/);
assert.match(taskOverviewHtml, /data-export="manifest"/);
assert.match(taskOverviewHtml, /data-export="bundle"/);
assert.match(taskOverviewHtml, /生成完整笔记/);
assert.match(taskOverviewHtml, /data-rerun-from-media="side-overview"/);
assert.match(taskOverviewHtml, /已完成直取下载/);
assert.match(taskOverviewHtml, /当前页下载/);
assert.match(taskOverviewHtml, /已跟踪最终 URL/);
assert.match(taskOverviewHtml, /final\.mp4\?token=abc/);
assert.match(taskOverviewHtml, /浏览器播放证据/);
assert.match(taskOverviewHtml, /非录制直取/);
assert.match(taskOverviewHtml, /播放中 · 00:00:42 \/ 00:10:00 · 1280x720 · frame 7/);
assert.match(taskOverviewHtml, /直取目标/);
assert.match(taskOverviewHtml, /请求上下文/);
assert.match(taskOverviewHtml, /Referer/);
assert.match(taskOverviewHtml, /blob 已映射/);
assert.match(taskOverviewHtml, /class="direct-extraction-evidence"/);
assert.match(taskOverviewHtml, /直取证据/);
assert.match(taskOverviewHtml, /非录制下载路线/);
assert.match(taskOverviewHtml, /只下载到本地/);
assert.match(taskOverviewHtml, /不录制标签页/);
assert.match(taskOverviewHtml, /已落地 media\.mp4/);
assert.match(taskOverviewHtml, /可复用本地视频/);
assert.match(taskOverviewHtml, /headers Origin, Referer/);
assert.match(taskOverviewHtml, /manifest-ffmpeg → yt-dlp-page/);
assert.match(taskOverviewHtml, /仅可访问媒体/);
assert.doesNotMatch(taskOverviewHtml, /secret=1/);
assert.doesNotMatch(taskOverviewHtml, /Bearer secret/);
assert.doesNotMatch(taskOverviewHtml, /Authorization/);
assert.match(taskOverviewHtml, /阶段审计门/);
assert.match(taskOverviewHtml, /class="task-command-center"/);
assert.match(taskOverviewHtml, /class="task-command-grid"/);
assert.match(taskOverviewHtml, /data-switch-result-tab="diagnostics"/);
assert.match(taskOverviewHtml, /data-rerun-from-media="side-overview"/);
assert.match(taskOverviewHtml, /class="next-step-card ready"/);
assert.match(taskOverviewHtml, /继续生成完整笔记/);
assert.match(taskOverviewHtml, /看下载证据/);
assert.match(taskOverviewHtml, /class="media-preview-card"/);
assert.match(taskOverviewHtml, /本地视频核对/);
assert.match(taskOverviewHtml, /\/api\/tasks\/side-overview\/media/);
assert.match(taskOverviewHtml, /导出 media\.mp4/);
assert.match(taskOverviewHtml, /来源门/);
assert.match(taskOverviewHtml, /媒体门/);
assert.match(taskOverviewHtml, /转写门/);
assert.match(taskOverviewHtml, /切片门/);
assert.match(taskOverviewHtml, /总结门/);
assert.match(taskOverviewHtml, /pipeline-audit-actions/);
assert.match(taskOverviewHtml, /data-rerun-from-media="side-overview"/);
assert.doesNotMatch(taskOverviewHtml, /<script>bad/);
assert.match(taskOverviewHtml, /&lt;script&gt;bad\(\)&lt;\/script&gt; 课程/);

const downloadedAuditItems = context.pipelineAuditItems({
  id: "side-audit-downloaded",
  status: "success",
  phase: "completed",
  source_type: "current_page",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/side-audit-downloaded/media.mp4",
  selected_resource: {
    kind: "hls",
    source: "webRequest",
    resolved_url: "https://cdn.example.com/master.m3u8"
  },
  options: { visual_understanding: true },
  download_attempts: [{ strategy: "manifest-ffmpeg" }]
});
assert.equal(JSON.stringify(downloadedAuditItems.map(item => item.state)), JSON.stringify(["pass", "pass", "warn", "warn", "warn"]));
const backendAuditHtml = context.pipelineAuditHtml({
  status: "success",
  source_type: "current_page",
  media_path: "D:/media.mp4",
  options: {},
  audit: {
    gates: [
      { key: "source", state: "pass", value: "browser", detail: "server source" },
      { key: "media", state: "pass", value: "media.mp4", detail: "server media" },
      { key: "transcript", state: "warn", value: "backend transcript", detail: "server says wait" },
      { key: "visual", state: "wait", value: "backend visual", detail: "server visual" },
      { key: "summary", state: "wait", value: "backend summary", detail: "server summary" }
    ]
  }
});
assert.match(backendAuditHtml, /backend transcript/);
assert.match(backendAuditHtml, /server says wait/);
assert.match(backendAuditHtml, /class="warn"/);
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
assert.match(unsafeAuditHtml, /data-recovery-local/);

const failedMediaOverviewHtml = context.taskOverview({
  id: "side-failed-media",
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
assert.match(failedMediaOverviewHtml, /data-rerun-from-media="side-failed-media"/);
assert.match(failedMediaOverviewHtml, /Whisper failed/);

const failedNextStepHtml = context.nextStepHtml({
  id: "side-failed-next",
  source_type: "current_page",
  status: "failed",
  phase: "failed",
  error_code: "<script>bad()</script>",
  error_detail: "signed URL expired",
  selected_resource: { kind: "video", source: "webRequest" },
  options: {}
});
assert.match(failedNextStepHtml, /直取链路需要处理/);
assert.match(failedNextStepHtml, /signed URL expired/);
assert.match(failedNextStepHtml, /data-recovery-local/);
assert.doesNotMatch(failedNextStepHtml, /<script>bad/);

vm.runInContext(`
page = {
  page_url: "https://course.example.com/lesson",
  page_text: "页面文本兜底",
  browser_subtitles: []
};
`, context);
const failedDirectChoiceHtml = context.nextStepHtml({
  id: "side-failed-direct-choice",
  source_type: "current_page",
  page_url: "https://course.example.com/lesson",
  status: "failed",
  phase: "failed",
  error_code: "download_forbidden",
  error_detail: "<script>bad()</script> signed URL expired",
  selected_resource: {
    kind: "hls",
    url: "https://cdn.example.com/live/master.m3u8",
    source: "webRequest"
  },
  options: {}
});
assert.match(failedDirectChoiceHtml, /class="direct-failure-choices"/);
assert.match(failedDirectChoiceHtml, /重新预检候选/);
assert.match(failedDirectChoiceHtml, /data-route-action="preflight"/);
assert.match(failedDirectChoiceHtml, /data-route-action="redetect"/);
assert.match(failedDirectChoiceHtml, /data-route-action="local"/);
assert.match(failedDirectChoiceHtml, /data-route-action="text"/);
assert.match(failedDirectChoiceHtml, /只总结页面文本/);
assert.doesNotMatch(failedDirectChoiceHtml, /<script>bad/);

const coverageOverviewHtml = context.taskOverview({
  id: "side-coverage-overview",
  title: "侧栏切片覆盖",
  source_type: "current_page",
  status: "success",
  phase: "completed",
  progress: 100,
  media_path: "D:/media.mp4",
  note_path: "D:/note.md",
  selected_resource: { kind: "hls", source: "webRequest" },
  options: { frame_interval: 20, grid_columns: 3, grid_rows: 3 },
  summary_diagnostics: {
    visual_window_count: 1,
    frame_grid_count: 1,
    vision_grid_count: 1,
    vision_image_count: 1
  },
  visual_windows: [{
    id: "W001",
    start: 0,
    end: 180,
    frame_count: 9,
    grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg"
  }]
});
assert.match(coverageOverviewHtml, /class="visual-coverage"/);
assert.match(coverageOverviewHtml, /视觉切片覆盖/);
assert.match(coverageOverviewHtml, /1\/1/);
assert.match(coverageOverviewHtml, /W001/);

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
assert.equal(context.canContinueFromDownloadedMedia({
  id: "side-failed-media",
  status: "failed",
  media_path: "D:/media.mp4",
  note_path: ""
}), true);
assert.equal(context.canContinueFromDownloadedMedia({
  id: "side-running-media",
  status: "running",
  media_path: "D:/media.mp4",
  note_path: ""
}), false);
const diagnosticRecoveryHtml = context.diagnosticRecoveryHtml({
  id: "side-recovery",
  status: "success",
  media_path: "D:/media.mp4",
  note_path: "",
  selected_resource: {
    kind: "hls",
    url: "https://mooc1.chaoxing.com/ananas/status/lesson.m3u8",
    request_headers: {
      Referer: "https://course.example.com/lesson",
      Range: "bytes=100-200",
      Cookie: "secret=bad"
    }
  },
  download_attempts: [
    { strategy: "direct-file", code: "download_forbidden", status_code: 403, message: "<script>bad()</script>" },
    { strategy: "manifest-ffmpeg", code: "unsupported_manifest" }
  ]
});
assert.match(diagnosticRecoveryHtml, /class="diagnostic-recovery"/);
assert.match(diagnosticRecoveryHtml, /学习通\/超星/);
assert.match(diagnosticRecoveryHtml, /不刷课/);
assert.match(diagnosticRecoveryHtml, /下一步建议/);
assert.match(diagnosticRecoveryHtml, /后端已尝试 2 条路线/);
assert.match(diagnosticRecoveryHtml, /Referer/);
assert.match(diagnosticRecoveryHtml, /Range 只作为浏览器播放证据/);
assert.match(diagnosticRecoveryHtml, /Cookie/);
assert.doesNotMatch(diagnosticRecoveryHtml, /secret=bad/);
assert.match(diagnosticRecoveryHtml, /继续切片总结/);
assert.match(diagnosticRecoveryHtml, /class="recovery-actions"/);
assert.match(diagnosticRecoveryHtml, /data-recovery-local/);
assert.match(diagnosticRecoveryHtml, /data-switch-result-tab="diagnostics"/);
assert.match(diagnosticRecoveryHtml, /data-export="diagnostics"/);
assert.match(diagnosticRecoveryHtml, /data-rerun-from-media="side-recovery"/);
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
assert.match(context.directnessText({
  kind: "video",
  source: "pageHookPlayer",
  label: "DPlayer constructor switchVideo"
}), /DPlayer 已加载 视频文件/);
assert.match(context.resourceReasonText({
  kind: "hls",
  source: "pageHookPlayer",
  label: "xgplayer Player constructor switchUrl"
}), /xgplayer 已加载源地址/);
assert.match(context.resourceReasonText({
  kind: "hls",
  source: "manifest-guess",
  label: "Guessed HLS manifest from segment directory"
}), /同目录 manifest 猜测/);
assert.match(context.resourceReasonText({
  kind: "dash",
  source: "inferred-manifest",
  label: "Inferred DASH manifest"
}), /分片路径回推/);
assert.equal(context.resourceSourceText({ source: "iframeHint" }), "iframe 内播放器线索");
assert.equal(context.resourceSourceText({ source: "scriptHint" }), "页面脚本线索");
assert.equal(context.resourceSourceText({ source: "domHint" }), "页面元素线索");
assert.equal(context.resourceSourceText({ source: "locationHint" }), "页面 URL 线索");
assert.match(context.requestEvidence({
  kind: "video",
  source: "pageHookPlayer",
  label: "jwplayer setup"
}), /jwplayer 已加载源地址/);
assert.match(context.responseEvidenceLine({
  status_code: 200,
  mime: "application/octet-stream",
  content_length: 123456,
  headers: {
    "content-disposition": "attachment; filename*=UTF-8''lesson%20download.mp4",
    "content-range": "bytes 0-123455/123456"
  }
}), /HTTP 200.*application\/octet-stream.*filename lesson download\.mp4.*120\.6 KB.*range bytes 0-123455\/123456/);
assert.match(context.selectedResourceReport({
  kind: "video",
  source: "webRequest",
  label: "header named",
  url: "https://cdn.example.com/download?id=1",
  resolved_url: "https://media.example.com/real/lesson.mp4?sig=abc",
  mime: "application/octet-stream",
  status_code: 200,
  content_length: 123456,
  headers: {
    "content-disposition": "attachment; filename*=UTF-8''lesson%20download.mp4"
  }
}), /实际媒体 URL: https:\/\/media\.example\.com\/real\/lesson\.mp4\?sig=abc[\s\S]*HTTP 200.*filename lesson download\.mp4/);
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
const manifestGuessConfidence = context.candidateConfidence({
  kind: "hls",
  source: "manifest-guess"
});
assert.equal(manifestGuessConfidence.className, "low");
assert.equal(manifestGuessConfidence.label, "低置信兜底");
assert.equal(manifestGuessConfidence.detail, "由分片同目录猜测 manifest，需要预检确认。");
assert.equal(context.candidateConfidence({
  kind: "video",
  source: "webRequest",
  playback_match: "range-near-playhead"
}).label, "播放匹配");
const opaqueVideoCandidate = {
  kind: "video",
  source: "webRequest",
  request_type: "fetch",
  mime: "application/octet-stream",
  request_headers: {
    Accept: "video/mp4,video/*;q=0.9,*/*;q=0.1",
    "Sec-Fetch-Dest": "video",
    Referer: "https://course.example.com/lesson"
  }
};
assert.equal(context.candidateConfidence(opaqueVideoCandidate).label, "浏览器实证");
assert.match(context.directnessText(opaqueVideoCandidate), /浏览器实际请求的视频响应/);
assert.match(context.resourceReasonText(opaqueVideoCandidate), /视频请求头/);
assert.match(context.candidateConfidenceHtml({
  kind: "hls",
  source: "manifest-guess"
}), /resource-confidence low/);

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
  playback_match: "blob-source",
  request_headers: {
    Referer: "https://course.example.com/lesson",
    Cookie: "secret=1",
    Authorization: "Bearer secret"
  }
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
assert.match(context.candidateConfidenceHtml(context.selectedResource()), /播放匹配/);
assert.match(context.resourceAttemptQueueHtml(), /resource-attempt-queue/);
assert.match(context.resourceAttemptQueueHtml(), /下载队列/);
assert.match(context.resourceAttemptQueueHtml(), /播放匹配/);
assert.match(context.resourceAttemptQueueHtml(), /待预检/);
vm.runInContext("resourceSelectionPinned = false;", context);
assert.equal(context.pickDefaultResourceUrl([
  { url: "https://cdn.example.com/stale.mp4", kind: "video", score: 85 },
  { url: "https://cdn.example.com/current.m3u8", kind: "hls", playback_match: "range-near-playhead", score: 100 }
], "https://cdn.example.com/stale.mp4"), "https://cdn.example.com/current.m3u8");
vm.runInContext("resourceSelectionPinned = true;", context);
assert.equal(context.pickDefaultResourceUrl([
  { url: "https://cdn.example.com/stale.mp4", kind: "video", score: 85 },
  { url: "https://cdn.example.com/current.m3u8", kind: "hls", playback_match: "range-near-playhead", score: 100 }
], "https://cdn.example.com/stale.mp4"), "https://cdn.example.com/stale.mp4");
vm.runInContext("resourceSelectionPinned = false;", context);
context.renderRouteSummary();
assert.match(elements.get("#routeSummary").innerHTML, /待预检/);
assert.match(elements.get("#routeSummary").innerHTML, /class="route-handoff"/);
assert.match(elements.get("#routeSummary").innerHTML, /资源证据/);
assert.match(elements.get("#routeSummary").innerHTML, /可下载性/);
assert.match(elements.get("#routeSummary").innerHTML, /切片笔记/);
assert.match(elements.get("#routeSummary").innerHTML, /data-route-action="preflight"/);
assert.match(elements.get("#routeSummary").innerHTML, /data-route-action="summarize"/);
assert.match(elements.get("#routeSummary").innerHTML, /data-route-action="download"/);
assert.doesNotMatch(elements.get("#routeSummary").innerHTML, /<script>bad/);
context.renderLaunchBar();
assert.match(elements.get("#launchBar").className, /candidate/);
assert.match(elements.get("#launchBar").innerHTML, /data-route-action="preflight"/);
assert.match(elements.get("#launchBar").innerHTML, /data-route-action="summarize"/);
assert.match(elements.get("#launchBar").innerHTML, /data-route-action="download"/);
assert.match(elements.get("#launchBar").innerHTML, /hls/);
assert.doesNotMatch(elements.get("#launchBar").innerHTML, /Cookie: secret/);
context.renderContext();
assert.match(elements.get("#resources").innerHTML, /第 1 顺位/);
assert.match(elements.get("#resources").innerHTML, /ffmpeg 合并/);
assert.match(elements.get("#resources").innerHTML, /resource-confidence high/);
assert.match(elements.get("#resources").innerHTML, /resource-filter-bar/);
assert.match(elements.get("#resources").innerHTML, /data-resource-filter="downloadable"/);
assert.match(elements.get("#resources").innerHTML, /data-resource-filter="matched"/);
assert.match(elements.get("#resources").innerHTML, /resource-attempt-row selected/);
assert.match(elements.get("#resourceInspector").innerHTML, /候选置信度/);
assert.match(elements.get("#resourceInspector").innerHTML, /播放匹配/);
assert.match(elements.get("#resourceInspector").innerHTML, /复制链接/);
assert.match(elements.get("#resourceInspector").innerHTML, /复制证据/);
assert.doesNotMatch(elements.get("#resources").innerHTML, /<script>bad/);
assert.match(elements.get("#currentStudyCard").className, /candidate/);
assert.match(elements.get("#currentStudyCard").innerHTML, /发现当前视频直取候选/);
assert.match(elements.get("#currentStudyCard").innerHTML, /workbench-route/);
assert.match(elements.get("#currentStudyCard").innerHTML, /workbench-slice-plan/);
assert.doesNotMatch(elements.get("#currentStudyCard").innerHTML, /workbench-local-fallback/);
assert.doesNotMatch(elements.get("#currentStudyCard").innerHTML, /data-route-action="local"/);
assert.match(elements.get("#currentStudyCard").innerHTML, /20秒 · 3x3/);
assert.match(elements.get("#currentStudyCard").innerHTML, /每窗 00:03:00/);
assert.match(elements.get("#currentStudyCard").innerHTML, /视觉 API \/ 本地索引/);
assert.match(elements.get("#currentStudyCard").innerHTML, /网格图 \+ 对应字幕合并/);
assert.match(elements.get("#currentStudyCard").innerHTML, /https:\/\/cdn\.example\.com\/live\/master\.m3u8/);
assert.match(elements.get("#currentStudyCard").innerHTML, /data-workbench-copy="url"/);
assert.match(elements.get("#currentStudyCard").innerHTML, /data-workbench-copy="report"/);
assert.match(elements.get("#currentStudyCard").innerHTML, /data-workbench-copy="audit"/);
assert.doesNotMatch(elements.get("#currentStudyCard").innerHTML, /Cookie: secret/);
assert.doesNotMatch(elements.get("#currentStudyCard").innerHTML, /Authorization/);
assert.match(elements.get("#currentStudyCard").innerHTML, /00:00:00 \/ 00:00:00/);
assert.match(elements.get("#currentStudyCard").innerHTML, /1 条/);
assert.equal(context.playbackReadinessState(), "ready");
assert.match(elements.get("#playbackReadiness").innerHTML, /已读取当前播放视频/);
assert.match(elements.get("#playbackReadiness").innerHTML, /1\/1 匹配/);
assert.match(elements.get("#playbackReadiness").innerHTML, /1 条/);

vm.runInContext("els.visualUnderstanding.checked = false; renderCurrentStudyCard();", context);
assert.match(elements.get("#currentStudyCard").innerHTML, /无视觉 · 仅转写/);
assert.match(elements.get("#currentStudyCard").innerHTML, /已关闭/);
vm.runInContext("els.visualUnderstanding.checked = true; renderCurrentStudyCard();", context);

await context.copySelectedResourceUrl();
assert.equal(clipboardWrites.at(-1), "https://cdn.example.com/live/master.m3u8");
assert.equal(elements.get("#taskMessage").textContent, "已复制候选资源 URL。");

vm.runInContext(`selectedResource().resolved_url = "https://media.example.com/real/master.m3u8?sig=abc";`, context);
await context.copySelectedResourceUrl();
assert.equal(clipboardWrites.at(-1), "https://media.example.com/real/master.m3u8?sig=abc");
assert.equal(elements.get("#taskMessage").textContent, "已复制实际媒体 URL。");

const report = vm.runInContext("selectedResourceReport()", context);
assert.match(report, /下载策略: ffmpeg 合并/);
assert.match(report, /实际媒体 URL: https:\/\/media\.example\.com\/real\/master\.m3u8\?sig=abc/);
assert.match(report, /复用请求头: Referer/);
assert.doesNotMatch(report, /Cookie/);
assert.doesNotMatch(report, /Authorization/);
await context.copySelectedResourceReport();
assert.equal(clipboardWrites.at(-1), report);
assert.equal(elements.get("#taskMessage").textContent, "已复制候选资源证据摘要。");

const auditReport = vm.runInContext("currentPageAuditReport()", context);
assert.match(auditReport, /LearnNote 当前页直取审计报告/);
assert.match(auditReport, /候选资源: 1\/1 可直取/);
assert.match(auditReport, /Cookie 只在点击任务时一次性同步给本地后端/);
assert.match(auditReport, /本工具不录制标签页/);
assert.match(auditReport, /选中候选证据/);
assert.doesNotMatch(auditReport, /Cookie: secret/);
assert.doesNotMatch(auditReport, /Authorization/);
await context.copyCurrentPageAuditReport();
assert.equal(clipboardWrites.at(-1), auditReport);
assert.equal(elements.get("#taskMessage").textContent, "已复制当前页直取审计报告。");

vm.runInContext(`
resources = [
  {
    url: "https://cdn.example.com/live/master.m3u8",
    kind: "hls",
    source: "webRequest",
    score: 98,
    label: "master",
    playback_match: "blob-source"
  },
  {
    url: "blob:https://course.example.com/video",
    kind: "blob",
    source: "activeVideo",
    score: 5,
    label: "blob source"
  },
  {
    url: "https://cdn.example.com/captions.vtt",
    kind: "subtitle",
    source: "subtitleTrack",
    score: 62,
    label: "caption"
  }
];
selectedResourceUrl = "https://cdn.example.com/live/master.m3u8";
resourceFilter = "diagnostic";
`, context);
context.renderContext();
assert.equal(context.filteredResources().length, 2);
assert.equal(context.selectedResource().url, "blob:https://course.example.com/video");
assert.match(elements.get("#resources").innerHTML, /data-resource-filter="diagnostic"/);
assert.match(elements.get("#resources").innerHTML, /class="active" data-resource-filter="diagnostic"/);
assert.match(elements.get("#resourceInspector").innerHTML, /blob 播放地址线索/);
assert.match(elements.get("#resourceInspector").innerHTML, /blob:https:\/\/course\.example\.com\/video/);

vm.runInContext(`
resourceFilter = "matched";
resources = [{
  url: "https://cdn.example.com/only-caption.vtt",
  kind: "subtitle",
  source: "subtitleTrack",
  score: 62,
  label: "only caption"
}];
selectedResourceUrl = "https://cdn.example.com/only-caption.vtt";
`, context);
context.renderContext();
assert.equal(context.filteredResources().length, 0);
assert.match(elements.get("#resources").innerHTML, /resource-filter-empty/);
assert.match(elements.get("#resources").innerHTML, /data-resource-filter="all"/);

vm.runInContext(`
resources = [{
  url: "https://cdn.example.com/live/master.m3u8",
  kind: "hls",
  source: "webRequest",
  score: 98,
  label: "master",
  playback_match: "blob-source"
}];
selectedResourceUrl = "https://cdn.example.com/live/master.m3u8";
resourceFilter = "all";
`, context);
vm.runInContext(`currentTaskId = "task-url-direct"; selectedTab = "frames"; backendUrl = "http://127.0.0.1:8765/";`, context);
assert.equal(context.workbenchUrl(), "http://127.0.0.1:8765/?task=task-url-direct&tab=frames");
assert.equal(context.workbenchUrl("task-url-direct", "bad-tab"), "http://127.0.0.1:8765/?task=task-url-direct&tab=note");
context.openWorkbench("task-url-direct", "frames");
assert.deepEqual(JSON.parse(JSON.stringify(openedTabs.at(-1))), {
  url: "http://127.0.0.1:8765/?task=task-url-direct&tab=frames",
  target: "_blank",
  features: "noopener"
});

vm.runInContext(`
currentTaskId = "task-scroll-reset";
currentTask = {
  id: "task-scroll-reset",
  title: "Scroll reset lesson",
  status: "success",
  phase: "completed",
  progress: 100,
  source_type: "current_page",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/task-scroll-reset/media.mp4",
  note_path: "D:/Projects/learnnote-assistant/data/tasks/task-scroll-reset/note.md",
  summary_source: "vision-llm",
  options: { visual_understanding: true },
  summary_diagnostics: { used_vision_llm: true, frame_grid_count: 1, vision_grid_count: 1, vision_image_count: 1 },
  visual_windows: [{
    id: "W001",
    start: 0,
    end: 180,
    frame_count: 9,
    grid_url: "http://127.0.0.1:8765/api/tasks/demo/grids/grid_000.jpg"
  }]
};
transcriptCache = {
  segments: [
    { start: 12, end: 18, text: "frames 接线字幕" },
    { start: 240, end: 245, text: "不属于 frames 窗口" }
  ]
};
selectedTab = "note";
`, context);
elements.get("#result").scrollTop = 128;
context.switchResultTab("frames");
assert.equal(elements.get("#result").scrollTop, 0);
assert.match(elements.get("#result").innerHTML, /class="vision-evidence strong"/);
assert.match(elements.get("#result").innerHTML, /class="side-visual-study-cues"/);
assert.match(elements.get("#result").innerHTML, /frames 接线字幕/);
assert.doesNotMatch(elements.get("#result").innerHTML, /不属于 frames 窗口/);

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
assert.match(elements.get("#routeSummary").innerHTML, /class="done"/);
assert.match(elements.get("#routeSummary").innerHTML, /本地落地/);
context.renderCurrentStudyCard();
assert.match(elements.get("#currentStudyCard").className, /ready/);
assert.match(elements.get("#currentStudyCard").innerHTML, /可以开始当前视频总结/);
assert.match(elements.get("#currentStudyCard").innerHTML, /workbench-audit-gate/);
assert.match(elements.get("#currentStudyCard").innerHTML, /直取审计门/);
assert.match(elements.get("#currentStudyCard").innerHTML, /复制审计/);
assert.match(elements.get("#currentStudyCard").innerHTML, /预检通过/);
assert.match(elements.get("#currentStudyCard").innerHTML, /非录制路径/);
assert.equal(context.workbenchAuditGateItems("ready").length, 5);
context.renderLaunchBar();
assert.match(elements.get("#launchBar").className, /ready/);
assert.match(elements.get("#launchBar").innerHTML, /data-route-action="summarize"/);
assert.match(elements.get("#launchBar").innerHTML, /data-route-action="download"/);
assert.doesNotMatch(elements.get("#launchBar").innerHTML, /data-route-action="preflight"/);

vm.runInContext(`
page = {
  page_url: "https://course.example.com/drm",
  page_text: "章节标题 课程说明",
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
assert.match(context.routeSummaryActionsHtml("blocked"), /data-route-action="local"/);
assert.match(context.routeSummaryActionsHtml("blocked"), /data-route-action="text"/);
assert.match(context.routeSummaryActionsHtml("blocked"), /data-route-action="redetect"/);
assert.equal(context.currentStudyState(), "blocked");
assert.match(context.currentStudyCopy("blocked").detail, /不会录制/);
assert.match(context.currentStudyActionText("blocked"), /本地视频上传/);
context.renderContext();
assert.equal(context.playbackReadinessState(), "blocked");
assert.match(elements.get("#playbackReadiness").className, /blocked/);
assert.match(elements.get("#playbackReadiness").innerHTML, /DRM/);
assert.match(elements.get("#currentStudyCard").className, /blocked/);
assert.match(elements.get("#currentStudyCard").innerHTML, /当前页不能直接下载/);
assert.match(elements.get("#currentStudyCard").innerHTML, /workbench-audit-gate/);
assert.match(elements.get("#currentStudyCard").innerHTML, /失败边界/);
assert.match(elements.get("#currentStudyCard").innerHTML, /转本地入口/);
assert.match(elements.get("#currentStudyCard").innerHTML, /workbench-local-fallback urgent/);
assert.match(elements.get("#currentStudyCard").innerHTML, /直取受限/);
assert.match(elements.get("#currentStudyCard").innerHTML, /上传本地视频/);
assert.match(elements.get("#currentStudyCard").innerHTML, /不会录制页面/);
assert.match(elements.get("#resources").innerHTML, /no-resource-guide blocked/);
assert.match(elements.get("#resources").innerHTML, /data-resource-empty-action="redetect"/);
assert.match(elements.get("#resources").innerHTML, /data-resource-empty-action="local"/);
assert.match(elements.get("#resources").innerHTML, /data-resource-empty-action="text"/);
assert.match(elements.get("#launchBar").className, /blocked/);
assert.match(elements.get("#launchBar").innerHTML, /data-route-action="redetect"/);
assert.match(elements.get("#launchBar").innerHTML, /data-route-action="local"/);
assert.match(elements.get("#launchBar").innerHTML, /data-route-action="text"/);
assert.doesNotMatch(elements.get("#launchBar").innerHTML, /data-route-action="summarize"/);

vm.runInContext(`
page = {
  page_url: "https://course.example.com/stream",
  page_text: "MediaStream 课程说明",
  drm_detected: false,
  active_video: {
    src: "",
    src_object: true,
    src_object_type: "MediaStream",
    src_object_track_count: 2,
    src_object_video_tracks: 1,
    src_object_audio_tracks: 1,
    current_time: 18,
    duration: 90,
    paused: false,
    width: 1280,
    height: 720
  },
  browser_subtitles: []
};
resources = [];
selectedResourceUrl = "";
preflight = null;
preflightResourceUrl = "";
preflightResultsByUrl = new Map();
`, context);
assert.equal(context.playbackReadinessState(), "blocked");
assert.equal(context.routeSummaryState(), "blocked");
assert.match(context.playbackSourceLabel({ src_object: true }), /MediaStream/);
context.renderContext();
assert.match(elements.get("#playbackReadiness").innerHTML, /MediaStream/);
assert.match(elements.get("#readiness").textContent, /MediaStream\/srcObject/);
assert.match(elements.get("#activeVideo").innerHTML, /MediaStream/);
assert.match(elements.get("#resources").innerHTML, /当前视频来自 MediaStream/);
assert.match(elements.get("#launchBar").className, /blocked/);
assert.doesNotMatch(elements.get("#launchBar").innerHTML, /data-route-action="summarize"/);
