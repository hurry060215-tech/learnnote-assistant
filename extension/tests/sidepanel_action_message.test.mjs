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
  hidden: false,
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

let onMessage = null;
const calls = {
  collect: 0,
  preflight: 0,
  start: null
};

const page = {
  title: "Already open course player",
  page_url: "https://course.example.com/open",
  page_text: "lesson text",
  active_video: { src: "blob:https://course.example.com/player", current_time: 18, duration: 360, paused: false },
  frames: []
};

const resources = [{
  url: "https://cdn.example.com/open/master.m3u8",
  source: "webRequest",
  kind: "hls",
  score: 99,
  label: "HLS",
  playback_match: "blob-source"
}];

const context = {
  console,
  Date,
  document: documentStub,
  location: { href: "chrome-extension://learnnote/sidepanel.html" },
  navigator: { clipboard: { writeText() {} } },
  window: { open() {} },
  FormData: class FormData {},
  fetch: async url => {
    const value = String(url);
    if (value.endsWith("/health")) return { json: async () => ({ ffmpeg: true }) };
    if (value.endsWith("/api/tasks")) return { json: async () => ({ tasks: [] }) };
    if (value.endsWith("/api/tasks/message-task")) {
      return {
        json: async () => ({
          task: {
            id: "message-task",
            status: "failed",
            phase: "failed",
            progress: 100,
            message: "test stop",
            source_type: "current_page"
          }
        })
      };
    }
    throw new Error(`unexpected fetch: ${url}`);
  },
  chrome: {
    storage: {
      local: {
        async get(defaults) {
          return defaults;
        },
        async set() {},
        async remove() {}
      }
    },
    runtime: {
      onMessage: {
        addListener(listener) {
          onMessage = listener;
        }
      },
      async sendMessage(message) {
        if (message.type === "get-current-context") {
          calls.collect += 1;
          return { tab: { id: 88 }, page, resources };
        }
        if (message.type === "preflight-current-resource") {
          calls.preflight += 1;
          return {
            preflight: {
              ok: true,
              downloadable: true,
              strategy: "manifest-probe",
              kind: "hls",
              message: "OK"
            }
          };
        }
        if (message.type === "start-current-task") {
          calls.start = message;
          return { task_id: "message-task" };
        }
        throw new Error(`unexpected message: ${message.type}`);
      }
    },
    tabs: {
      create() {}
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
assert.equal(typeof onMessage, "function");
assert.equal(calls.start, null);

onMessage({
  type: "sidepanel-action-intent",
  intent: {
    action: "summarize-current-video",
    tabId: 88,
    createdAt: Date.now()
  }
});

await new Promise(resolve => setTimeout(resolve, 0));
await new Promise(resolve => setTimeout(resolve, 0));

assert.ok(calls.collect >= 2);
assert.equal(calls.preflight, 1);
assert.ok(calls.start, "expected open side panel action message to start a task");
assert.equal(calls.start.mode, "video");
assert.equal(calls.start.resources[0].url, "https://cdn.example.com/open/master.m3u8");
