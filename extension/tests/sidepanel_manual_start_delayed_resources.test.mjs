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

const calls = {
  collect: 0,
  preflight: 0,
  start: null
};

const emptyPage = {
  title: "Manual slow course",
  page_url: "https://course.example.com/manual-slow",
  page_text: "lesson text",
  active_video: { src: "blob:https://course.example.com/player", current_time: 5, duration: 600, paused: false },
  frames: []
};

const delayedResources = [{
  url: "https://cdn.example.com/manual-slow/master.m3u8",
  source: "webRequest",
  kind: "hls",
  score: 99,
  label: "HLS",
  playback_match: "blob-source"
}];

const realSetTimeout = setTimeout;
const timerDelays = [];

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
    if (value.endsWith("/api/tasks/manual-delayed-task")) {
      return {
        json: async () => ({
          task: {
            id: "manual-delayed-task",
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
        async set() {}
      }
    },
    runtime: {
      async sendMessage(message) {
        if (message.type === "get-current-context") {
          calls.collect += 1;
          const ready = calls.collect >= 3;
          return {
            tab: { id: 91 },
            page: emptyPage,
            resources: ready ? delayedResources : []
          };
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
          return { task_id: "manual-delayed-task" };
        }
        throw new Error(`unexpected message: ${message.type}`);
      }
    },
    tabs: {
      create() {}
    }
  },
  setTimeout(callback, ms) {
    timerDelays.push(ms);
    return realSetTimeout(callback, 0);
  },
  clearTimeout
};
context.window = { ...context.window, location: context.location };

vm.createContext(context);
const sidepanelCode = await readFile(new URL("../sidepanel.js", import.meta.url), "utf8");
vm.runInContext(sidepanelCode, context);

await new Promise(resolve => realSetTimeout(resolve, 0));
await context.startTask("video");

assert.ok(calls.collect >= 3, "expected manual start to retry context collection before starting");
assert.ok(timerDelays.includes(900), "expected manual start to wait for delayed media candidates");
assert.equal(calls.preflight, 1);
assert.ok(calls.start, "expected manual start to proceed after delayed media candidate appears");
assert.equal(calls.start.mode, "video");
assert.equal(calls.start.resources[0].url, "https://cdn.example.com/manual-slow/master.m3u8");
