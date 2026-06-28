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

const task = {
  id: "task-history-1",
  title: "History lesson",
  status: "success",
  phase: "completed",
  progress: 100,
  source_type: "current_page",
  selected_resource: { kind: "hls" },
  options: {},
  note_path: "note.md",
  media_path: "media.mp4",
  download_attempts: [{ strategy: "manifest-ffmpeg" }],
  visual_windows: [
    { id: "W001", start: 0, end: 180, frame_count: 9, grid_url: "/api/tasks/task-history-1/assets/grid_000.jpg" },
    { id: "W002", start: 180, end: 360, frame_count: 9, grid_url: "/api/tasks/task-history-1/assets/grid_001.jpg" }
  ]
};

const failedTask = {
  id: "task-history-failed",
  title: "Failed lesson",
  status: "failed",
  phase: "failed",
  progress: 100,
  source_type: "current_page",
  message: "Download failed",
  error_code: "download_forbidden",
  error_detail: "HTTP 403",
  options: {},
  download_attempts: [{ strategy: "direct-file", status: "failed" }],
  visual_windows: []
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
      return { json: async () => ({ tasks: [task, failedTask] }) };
    }
    if (value.endsWith("/api/tasks/task-history-1")) {
      return { ok: true, json: async () => ({ task }) };
    }
    if (value.endsWith("/api/tasks/task-history-failed")) {
      return { ok: true, json: async () => ({ task: failedTask }) };
    }
    if (value.endsWith("/api/tasks/task-history-1/transcript")) {
      return { ok: true, json: async () => ({ segments: [{ start: 0, end: 2, text: "history transcript" }] }) };
    }
    if (value.endsWith("/api/tasks/task-history-1/note")) {
      return { ok: true, text: async () => "# History lesson\n\nGenerated note" };
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

assert.match(elements.get("#taskHistory").innerHTML, /History lesson/);
assert.match(elements.get("#taskHistory").innerHTML, /直取/);
assert.match(elements.get("#taskHistory").innerHTML, /HLS/);
assert.match(elements.get("#taskHistory").innerHTML, /media\.mp4/);
assert.match(elements.get("#taskHistory").innerHTML, /history-task-preview status-success/);
assert.match(elements.get("#taskHistory").innerHTML, /\/api\/tasks\/task-history-1\/assets\/grid_000.jpg/);
assert.match(elements.get("#taskHistory").innerHTML, /00:00:00 - 00:03:00/);
assert.match(elements.get("#taskHistory").innerHTML, /history-task-chips/);
assert.match(elements.get("#taskHistory").innerHTML, /2 窗口/);
const successHistoryCard = elements.get("#taskHistory").innerHTML.split('data-id="task-history-failed"')[0];
assert.doesNotMatch(successHistoryCard, /1 次尝试/);

await context.selectHistoryTask("task-history-1");

assert.match(elements.get("#result").innerHTML, /History lesson/);
assert.match(elements.get("#result").innerHTML, /Generated note/);
assert.equal(elements.get("#copyButton").disabled, false);
assert.equal(elements.get("#bundleButton").disabled, false);
assert.equal(elements.get("#diagnosticsButton").disabled, false);
assert.equal(elements.get("#visualWindowsButton").disabled, false);
assert.equal(elements.get("#mediaButton").disabled, false);
assert.equal(elements.get("#downloadButton").disabled, false);
assert.match(elements.get("#taskHistory").innerHTML, /selected/);

await context.selectHistoryTask("task-history-failed");

assert.match(elements.get("#result").innerHTML, /HTTP 403|Download failed/);
assert.equal(elements.get("#copyButton").disabled, true);
assert.equal(elements.get("#diagnosticsButton").disabled, false);
assert.equal(elements.get("#visualWindowsButton").disabled, true);
assert.equal(elements.get("#mediaButton").disabled, true);
assert.match(elements.get("#taskHistory").innerHTML, /Failed lesson/);
assert.match(elements.get("#taskHistory").innerHTML, /history-task-preview status-failed empty/);
assert.match(elements.get("#taskHistory").innerHTML, /download_forbidden/);
assert.match(elements.get("#taskHistory").innerHTML, /1 次尝试/);
