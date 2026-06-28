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
  start: null,
  removed: []
};

const page = {
  title: "Course player",
  page_url: "https://course.example.com/lesson",
  page_text: "lesson text",
  active_video: { src: "blob:https://course.example.com/player", current_time: 42, duration: 600, paused: false },
  frames: []
};

const resources = [{
  url: "https://cdn.example.com/live/master.m3u8",
  source: "webRequest",
  kind: "hls",
  score: 99,
  label: "HLS",
  playback_match: "blob-source",
  request_type: "xmlhttprequest"
}];

const pendingSidePanelIntent = {
  action: "summarize-current-video",
  tabId: 77,
  createdAt: Date.now()
};

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
    if (value.endsWith("/api/tasks/one-click-task")) {
      return {
        json: async () => ({
          task: {
            id: "one-click-task",
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
          if (Object.hasOwn(defaults, "pendingSidePanelIntent")) return { ...defaults, pendingSidePanelIntent };
          return defaults;
        },
        async set() {},
        async remove(key) {
          calls.removed.push(key);
        }
      }
    },
    runtime: {
      async sendMessage(message) {
        if (message.type === "get-current-context") {
          calls.collect += 1;
          return { tab: { id: 77 }, page, resources };
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
          return { task_id: "one-click-task" };
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
await new Promise(resolve => setTimeout(resolve, 0));

assert.ok(calls.collect >= 2);
assert.equal(calls.preflight, 1);
assert.ok(calls.start, "expected one-click intent to start a current-page task");
assert.equal(calls.start.mode, "video");
assert.equal(calls.start.resources[0].url, "https://cdn.example.com/live/master.m3u8");
assert.equal(calls.start.resources[0].kind, "hls");
assert.deepEqual(calls.removed, ["pendingSidePanelIntent"]);
assert.match(elements.get("#taskMessage").textContent, /test stop|OK|预检/);
