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
      return {
        json: async () => ({
          task: {
            id: "download-only-task",
            status: "success",
            phase: "completed",
            progress: 100,
            message: "downloaded",
            source_type: "current_page",
            mode: "download_only",
            media_path: "D:/media.mp4",
            subtitle_path: "D:/browser_subtitles.srt",
            transcript_path: "D:/transcript.json",
            reuse: {
              media_available: true,
              subtitle_available: true,
              transcript_ready: true,
              transcript_source: "browser-subtitle",
              rerun_from_media_ready: true
            },
            active_video: page.active_video,
            selected_resource: {
              url: resources[0].url,
              kind: "hls",
              source: "webRequest",
              playback_match: "blob-source",
              request_headers: { Referer: page.page_url }
            },
            download_attempts: [{ strategy: "manifest-ffmpeg", status: "success", kind: "hls", source: "webRequest" }],
            direct_extraction: {
              no_tab_recording: true,
              no_drm_bypass: true,
              route: "download_only_to_local_media",
              media_landed: true,
              media_reusable: true,
              selected_candidate: {
                present: true,
                kind: "hls",
                source: "webRequest",
                playback_match: "blob-source",
                safe_request_header_names: ["Referer"]
              },
              browser_context: {
                active_source_type: "blob",
                browser_subtitle_count: 0,
                cookie_domain_count: 1,
                cookie_count: 2
              },
              download: {
                attempt_count: 1,
                successful_attempt_count: 1,
                failed_attempt_count: 0,
                strategy_order: ["manifest-ffmpeg"]
              },
              processing: {
                download_only: true,
                transcript_ready: false,
                frame_grid_count: 0,
                visual_window_count: 0,
                note_ready: false
              },
              boundary: "normal_accessible_media_only"
            }
          }
        })
      };
    }
    if (value.endsWith("/api/tasks/download-only-task/transcript")) {
      return {
        ok: true,
        json: async () => ({
          source: "browser-subtitle",
          segments: [{ start: 0, end: 2, text: "saved browser subtitle" }],
          full_text: "saved browser subtitle"
        })
      };
    }
    if (value.endsWith("/api/tasks/download-only-task/note")) {
      return { ok: false, text: async () => "" };
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
assert.equal(calls.start.resources[0].user_selected, true);
assert.equal(elements.get("#downloadOnlyButton").disabled, false);
assert.equal(context.canContinueFromDownloadedMedia({
  id: "download-only-task",
  status: "success",
  media_path: "D:/media.mp4",
  note_path: ""
}), true);
assert.equal(context.canContinueFromDownloadedMedia({
  id: "reuse-media-task",
  status: "success",
  media_path: "",
  note_path: "",
  reuse: { media_available: true, rerun_from_media_ready: true }
}), true);
assert.equal(context.canContinueFromDownloadedMedia({
  id: "complete-task",
  status: "success",
  media_path: "D:/media.mp4",
  note_path: "D:/note.md"
}), false);
assert.equal(elements.get("#continueFromMediaButton").hidden, false);
assert.equal(elements.get("#continueFromMediaButton").disabled, false);
assert.match(elements.get("#result").innerHTML, /视频和字幕已直取到本地/);
assert.match(elements.get("#result").innerHTML, /浏览器字幕/);
assert.match(elements.get("#result").innerHTML, /导出字幕/);
assert.match(elements.get("#result").innerHTML, /继续切片总结/);
assert.match(elements.get("#result").innerHTML, /data-rerun-from-media="download-only-task"/);
assert.equal(elements.get("#subtitlesButton").disabled, false);
assert.doesNotMatch(elements.get("#result").innerHTML, /不会继续转写、切片或总结/);

context.switchResultTab("diagnostics");

assert.match(elements.get("#result").innerHTML, /class="direct-extraction-evidence"/);
assert.match(elements.get("#result").innerHTML, /class="task-browser-evidence"/);
assert.match(elements.get("#result").innerHTML, /class="task-route-evidence"/);
assert.match(elements.get("#result").innerHTML, /只下载到本地/);
assert.match(elements.get("#result").innerHTML, /manifest-ffmpeg/);
assert.match(elements.get("#result").innerHTML, /Referer/);

await context.openTaskExport("media");

assert.equal(calls.export.type, "download-task-export");
assert.equal(calls.export.url, "http://127.0.0.1:8765/api/tasks/download-only-task/exports/media");
assert.equal(calls.openedTab, null);
assert.equal(elements.get("#taskMessage").textContent, "已开始下载本地视频。");

let rerunPayload = null;
elements.get("#frameInterval").value = "0";
elements.get("#gridSize").value = "7xnope";
let boundedOptions = context.readOptions();
assert.equal(boundedOptions.frame_interval, 1);
assert.equal(boundedOptions.grid_columns, 6);
assert.equal(boundedOptions.grid_rows, 3);
assert.match(context.visualPlanText(), /1秒 · 6x3/);
assert.match(context.visualWindowText(), /00:00:18/);
elements.get("#frameInterval").value = "30";
elements.get("#gridSize").value = "4x3";
elements.get("#noteTemplate").value = "qa";
elements.get("#llmProvider").value = "groq";
context.applyModelProviderPreset(true);
assert.equal(elements.get("#llmBaseUrl").value, "https://api.groq.com/openai/v1");
assert.equal(elements.get("#llmModel").value, "meta-llama/llama-4-scout-17b-16e-instruct");
assert.equal(elements.get("#transcriber").value, "groq");
assert.equal(elements.get("#whisperModel").value, "whisper-large-v3");
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
    return {
      ok: true,
      json: async () => ({
        task_id: "rerun-side-task",
        source_task_id: "download-only-task",
        task: {
          id: "rerun-side-task",
          source_task_id: "download-only-task",
          source_media_path: "D:/Projects/learnnote-assistant/data/tasks/download-only-task/media.mp4"
        }
      })
    };
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
          source_task_id: "download-only-task",
          source_media_path: "D:/Projects/learnnote-assistant/data/tasks/download-only-task/media.mp4",
          reuse: {
            source_task_id: "download-only-task",
            source_media_path: "D:/Projects/learnnote-assistant/data/tasks/download-only-task/media.mp4"
          },
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
          source_task_id: "download-only-task",
          source_media_path: "D:/Projects/learnnote-assistant/data/tasks/download-only-task/media.mp4",
          reuse: {
            source_task_id: "download-only-task",
            source_media_path: "D:/Projects/learnnote-assistant/data/tasks/download-only-task/media.mp4"
          },
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
assert.equal(rerunPayload.note_template, "qa");
assert.equal(rerunPayload.visual_understanding, false);
assert.equal(rerunPayload.llm_model, "vision-rerun");
assert.equal(rerunPayload.llm_base_url, "https://models.example/v1");
assert.equal(rerunPayload.llm_api_key, "sk-rerun");
assert.match(elements.get("#taskMessage").textContent, /完整笔记任务 rerun-side-task/);
assert.match(elements.get("#taskMessage").textContent, /转写、抽帧、视觉窗口和图文总结/);
assert.match(elements.get("#taskMessage").textContent, /不会录制页面/);
