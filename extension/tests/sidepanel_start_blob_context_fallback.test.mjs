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
  collect: 0,
  pagePreflight: 0,
  resourcePreflight: 0,
  start: null
};

const page = {
  title: "Blob iframe course player",
  page_url: "https://course.example.com/lesson",
  page_text: "lesson text",
  active_video: {
    src: "blob:https://course.example.com/9a91",
    frame_url: "https://course.example.com/player-iframe",
    frame_id: 9,
    current_time: 42,
    duration: 600,
    paused: false
  },
  frames: [{
    frame_id: 9,
    title: "Player iframe",
    page_url: "https://course.example.com/player-iframe",
    has_active_video: true
  }]
};

const resources = [{
  url: "blob:https://course.example.com/9a91",
  source: "activeVideo",
  kind: "blob",
  score: 5,
  label: "active blob",
  frame_url: "https://course.example.com/player-iframe",
  playback_match: "blob-same-frame"
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
    if (value.endsWith("/api/tasks/task-blob-context")) {
      return {
        json: async () => ({
          task: {
            id: "task-blob-context",
            status: "failed",
            phase: "failed",
            progress: 100,
            message: "backend page fallback attempted",
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
          return { tab: { id: 77 }, page, resources };
        }
        if (message.type === "preflight-current-page") {
          calls.pagePreflight += 1;
          return { report: { ok: true, ready: false, candidate_count: 0, probed_count: 0, downloadable_count: 0, candidates: [] } };
        }
        if (message.type === "preflight-current-resource") {
          calls.resourcePreflight += 1;
          return { preflight: { ok: false, downloadable: false, code: "no_media_found" } };
        }
        if (message.type === "start-current-task") {
          calls.start = message;
          return { task_id: "task-blob-context" };
        }
        throw new Error(`unexpected message: ${message.type}`);
      }
    },
    tabs: {
      create() {}
    }
  },
  setTimeout(fn) {
    fn();
    return 0;
  },
  clearTimeout() {}
};
context.window = { ...context.window, location: context.location };

vm.createContext(context);
const sidepanelCode = await readFile(new URL("../sidepanel.js", import.meta.url), "utf8");
vm.runInContext(sidepanelCode, context);

await new Promise(resolve => setTimeout(resolve, 0));
await context.startTask("video");

assert.ok(calls.start, "expected backend task start for blob-only playback evidence");
assert.equal(calls.pagePreflight, 0);
assert.equal(calls.resourcePreflight, 0);
assert.equal(calls.start.mode, "video");
assert.equal(calls.start.page.page_url, "https://course.example.com/lesson");
assert.ok(
  calls.start.resources.some(item => item.url === "blob:https://course.example.com/9a91" && item.kind === "blob"),
  "expected original blob evidence to stay in task resources"
);
assert.ok(
  calls.start.resources.some(item => item.url === "https://course.example.com/player-iframe" && item.request_type === "page-scan-fallback"),
  "expected iframe URL to be passed to backend task fallback"
);
assert.ok(
  calls.start.resources.some(item => item.url === "https://course.example.com/lesson" && item.request_type === "page-scan-fallback"),
  "expected top page URL to be passed to backend task fallback"
);
