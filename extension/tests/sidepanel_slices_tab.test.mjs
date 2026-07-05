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

const makeElement = (dataset = {}) => ({
  addEventListener() {},
  classList: makeClassList(),
  querySelector() { return null; },
  style: {},
  dataset,
  value: "",
  textContent: "",
  innerHTML: "",
  scrollTop: 0,
  disabled: false,
  onclick: null,
  onchange: null,
  files: []
});

const resultTabs = ["note", "transcript", "slices", "frames", "diagnostics"]
  .map(tab => makeElement({ tab }));

const documentStub = {
  querySelector(selector) {
    if (!elements.has(selector)) elements.set(selector, makeElement());
    return elements.get(selector);
  },
  querySelectorAll(selector) {
    if (selector === ".result-tab") return resultTabs;
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
      return { json: async () => ({ ffmpeg: true, vision_model_configured: true }) };
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

vm.runInContext(`
currentTaskId = "slice-task";
currentTask = {
  id: "slice-task",
  title: "Slice Review Lesson",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/slice-task/media.mp4",
  transcript_path: "D:/Projects/learnnote-assistant/data/tasks/slice-task/transcript.json",
  summary_source: "vision-llm",
  options: { grid_columns: 3, grid_rows: 3 },
  summary_diagnostics: {
    used_vision_llm: true,
    frame_grid_count: 2,
    vision_grid_count: 2,
    vision_image_window_ids: ["W001"],
    missing_vision_image_window_ids: ["W002"]
  },
  visual_windows: [
    {
      id: "W001",
      start: 12,
      end: 48,
      frame_count: 9,
      frame_timestamps: [12, 24, 36],
      grid_url: "http://127.0.0.1:8765/api/tasks/slice-task/grids/grid_000.jpg",
      transcript_excerpt: "Introduce the theorem and compare the two diagrams."
    },
    {
      id: "W002",
      start: 48,
      end: 70,
      frame_count: 9,
      frame_timestamps: [48, 58, 68],
      grid_url: "",
      transcript_excerpt: "Missing image window should rely on transcript."
    }
  ]
};
transcriptCache = {
  segments: [
    { start: 15, end: 20, text: "The first diagram gives the theorem setup." },
    { start: 75, end: 80, text: "Outside the slice window." }
  ]
};
selectedTab = "note";
`, context);

elements.get("#result").scrollTop = 88;
resultTabs.find(tab => tab.dataset.tab === "slices").onclick();

const resultHtml = elements.get("#result").innerHTML;
assert.equal(elements.get("#result").scrollTop, 0);
assert.equal(context.workbenchUrl("slice-task", "slices"), "http://127.0.0.1:8765/?task=slice-task&tab=slices");
assert.equal(resultTabs.find(tab => tab.dataset.tab === "slices").classList.contains("active"), true);
assert.equal(resultTabs.find(tab => tab.dataset.tab === "slices").ariaSelected, "true");
assert.equal(resultTabs.find(tab => tab.dataset.tab === "note").ariaSelected, "false");
assert.match(resultHtml, /class="side-visual-study-navigator"/);
assert.match(resultHtml, /复习队列/);
assert.match(resultHtml, /按画面窗口回看/);
assert.match(resultHtml, /class="side-visual-study"/);
assert.match(resultHtml, /side-visual-study-card vision/);
assert.match(resultHtml, /side-visual-study-card missing/);
assert.match(resultHtml, /side-visual-evidence vision/);
assert.match(resultHtml, /side-visual-evidence missing/);
assert.match(resultHtml, /已进视觉 · 网格图已参与图文总结/);
assert.match(resultHtml, /缺图 · 未送入视觉模型，按字幕与索引复习/);
assert.match(resultHtml, /W001/);
assert.match(resultHtml, /W002/);
assert.match(resultHtml, /已进视觉 · 9 帧 · 1 字幕/);
assert.match(resultHtml, /00:00:12 - 00:00:48/);
assert.match(resultHtml, /grid_000\.jpg/);
assert.match(resultHtml, /The first diagram gives the theorem setup\./);
assert.doesNotMatch(resultHtml, /Outside the slice window/);
assert.match(resultHtml, /data-media-seek-time="12\.000"/);
assert.match(resultHtml, /data-switch-result-tab="transcript"/);
assert.match(resultHtml, /data-switch-result-tab="note"/);

vm.runInContext(`
currentTaskId = "download-only-task";
currentTask = {
  id: "download-only-task",
  title: "Downloaded only lesson",
  status: "success",
  phase: "completed",
  mode: "download_only",
  source_type: "current_page",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/download-only-task/downloaded-original.mp4",
  download_attempts: [{ strategy: "direct-file", status: "success" }],
  visual_windows: []
};
transcriptCache = null;
selectedTab = "note";
`, context);

elements.get("#result").innerHTML = "";
resultTabs.find(tab => tab.dataset.tab === "slices").onclick();

const pendingHtml = elements.get("#result").innerHTML;
assert.match(pendingHtml, /class="side-slice-pending"/);
assert.match(pendingHtml, /视频已直取到本地，可以继续切片总结/);
assert.match(pendingHtml, /不会录制页面/);
assert.match(pendingHtml, /data-rerun-from-media="download-only-task"/);
assert.match(pendingHtml, /data-export="media"/);
assert.match(pendingHtml, /downloaded-original\.mp4/);
assert.doesNotMatch(pendingHtml, /导出 media\.mp4/);
assert.match(pendingHtml, /data-switch-result-tab="diagnostics"/);
assert.match(pendingHtml, /media-preview-card/);

vm.runInContext(`
currentTaskId = "failed-current-page-task";
currentTask = {
  id: "failed-current-page-task",
  title: "Failed current page lesson",
  status: "failed",
  phase: "failed",
  source_type: "current_page",
  error_code: "download_forbidden",
  error_detail: "signed URL expired",
  selected_resource: { kind: "hls", source: "webRequest" },
  download_attempts: [{ strategy: "manifest-ffmpeg", status: "failed", code: "download_forbidden" }],
  visual_windows: []
};
transcriptCache = null;
selectedTab = "note";
`, context);

elements.get("#result").innerHTML = "";
resultTabs.find(tab => tab.dataset.tab === "frames").onclick();
const failedFramesHtml = elements.get("#result").innerHTML;
assert.match(failedFramesHtml, /画面切片尚未生成/);
assert.match(failedFramesHtml, /直取链路需要处理/);
assert.match(failedFramesHtml, /data-switch-result-tab="diagnostics"/);
assert.match(failedFramesHtml, /data-recovery-local/);
assert.match(failedFramesHtml, /class="pipeline-audit"/);

resultTabs.find(tab => tab.dataset.tab === "transcript").onclick();
const failedTranscriptHtml = elements.get("#result").innerHTML;
assert.match(failedTranscriptHtml, /转写尚未生成/);
assert.match(failedTranscriptHtml, /当前页视频直取没有走到字幕\/ASR 阶段/);
assert.match(failedTranscriptHtml, /data-switch-result-tab="diagnostics"/);
assert.match(failedTranscriptHtml, /data-recovery-local/);
