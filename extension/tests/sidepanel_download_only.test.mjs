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

const calls = {
  preflight: 0,
  start: null,
  export: null,
  openedTab: null
};

const page = {
  title: "Course player",
  page_url: "https://course.example.com/lesson",
  page_text: "lesson text",
  active_video: { src: "blob:https://course.example.com/player", current_time: 12, duration: 120, paused: false },
  frames: []
};

const resources = [{
  url: "https://cdn.example.com/lesson.m3u8",
  source: "webRequest",
  kind: "hls",
  score: 100,
  label: "HLS",
  playback_match: "blob-source"
}];

const context = {
  console,
  document: documentStub,
  location: { href: "chrome-extension://learnnote/sidepanel.html" },
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
    if (value.endsWith("/api/tasks/download-only-task")) {
      return { json: async () => ({ task: { id: "download-only-task", status: "success", phase: "completed", progress: 100, message: "downloaded", media_path: "D:/media.mp4", download_attempts: [] } }) };
    }
    throw new Error(`unexpected fetch: ${url}`);
  },
  chrome: {
    storage: {
      local: {
        async get(defaults) {
          return defaults;
        },
        async set() {}
      }
    },
    runtime: {
      async sendMessage(message) {
        if (message.type === "get-current-context") {
          return { page, resources };
        }
        if (message.type === "preflight-current-resource") {
          calls.preflight += 1;
          return {
            preflight: {
              ok: true,
              downloadable: true,
              kind: "hls",
              strategy: "manifest-probe",
              message: "ok"
            }
          };
        }
        if (message.type === "start-current-task") {
          calls.start = message;
          return { task_id: "download-only-task" };
        }
        if (message.type === "download-task-export") {
          calls.export = message;
          return { ok: true, downloadId: 9 };
        }
        throw new Error(`unexpected message: ${message.type}`);
      }
    },
    tabs: {
      create(options) {
        calls.openedTab = options;
      }
    }
  },
  setTimeout,
  clearTimeout
};
context.window = { ...context.window, location: context.location };

vm.createContext(context);
const sidepanelCode = await readFile(new URL("../sidepanel.js", import.meta.url), "utf8");
vm.runInContext(sidepanelCode, context);

await new Promise(resolve => setTimeout(resolve, 0));
await context.startTask("download_only");
await new Promise(resolve => setTimeout(resolve, 0));

assert.equal(calls.preflight, 1);
assert.equal(calls.start.mode, "download_only");
assert.equal(calls.start.resources.length, 1);
assert.equal(calls.start.resources[0].url, resources[0].url);
assert.equal(elements.get("#downloadOnlyButton").disabled, false);
assert.equal(context.canContinueFromDownloadedMedia({
  id: "download-only-task",
  status: "success",
  media_path: "D:/media.mp4",
  note_path: ""
}), true);
assert.equal(context.canContinueFromDownloadedMedia({
  id: "complete-task",
  status: "success",
  media_path: "D:/media.mp4",
  note_path: "D:/note.md"
}), false);
assert.equal(elements.get("#continueFromMediaButton").hidden, false);
assert.equal(elements.get("#continueFromMediaButton").disabled, false);

await context.openTaskExport("media");

assert.equal(calls.export.type, "download-task-export");
assert.equal(calls.export.url, "http://127.0.0.1:8765/api/tasks/download-only-task/exports/media");
assert.equal(calls.openedTab, null);
assert.equal(elements.get("#taskMessage").textContent, "已开始下载本地视频。");

let rerunPayload = null;
elements.get("#frameInterval").value = "30";
elements.get("#gridSize").value = "4x3";
elements.get("#transcriber").value = "openai-compatible";
elements.get("#whisperModel").value = "whisper-1";
elements.get("#llmModel").value = "vision-rerun";
elements.get("#llmBaseUrl").value = "https://models.example/v1";
elements.get("#llmApiKey").value = "sk-rerun";
elements.get("#visualUnderstanding").checked = false;
context.refreshOptionDependentUi();
assert.match(elements.get("#currentStudyCard").innerHTML, /\u65e0\u89c6\u89c9/);
assert.match(elements.get("#launchBar").innerHTML, /\u65e0\u89c6\u89c9/);
assert.match(elements.get("#routeSummary").innerHTML, /\u65e0\u89c6\u89c9/);
context.fetch = async (url, options = {}) => {
  const value = String(url);
  if (value.endsWith("/api/tasks/download-only-task/rerun-from-media")) {
    rerunPayload = JSON.parse(options.body);
    return { ok: true, json: async () => ({ task_id: "rerun-side-task" }) };
  }
  if (value.endsWith("/api/tasks")) {
    return {
      json: async () => ({
        tasks: [{
          id: "rerun-side-task",
          title: "rerun",
          status: "failed",
          phase: "failed",
          progress: 100,
          message: "stop polling",
          source_type: "local",
          visual_windows: []
        }]
      })
    };
  }
  if (value.endsWith("/api/tasks/rerun-side-task")) {
    return {
      json: async () => ({
        task: {
          id: "rerun-side-task",
          title: "rerun",
          status: "failed",
          phase: "failed",
          progress: 100,
          message: "stop polling",
          source_type: "local",
          visual_windows: []
        }
      })
    };
  }
  throw new Error(`unexpected fetch: ${url}`);
};
await context.rerunTaskFromMedia("download-only-task");

assert.equal(rerunPayload.frame_interval, 30);
assert.equal(rerunPayload.grid_columns, 4);
assert.equal(rerunPayload.grid_rows, 3);
assert.equal(rerunPayload.visual_understanding, false);
assert.equal(rerunPayload.llm_model, "vision-rerun");
assert.equal(rerunPayload.llm_base_url, "https://models.example/v1");
assert.equal(rerunPayload.llm_api_key, "sk-rerun");
assert.match(elements.get("#taskMessage").textContent, /当前切片/);
