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
  preflight: [],
  start: null
};

const page = {
  title: "Course player",
  page_url: "https://course.example.com/lesson",
  page_text: "lesson text",
  active_video: { src: "blob:https://course.example.com/player", current_time: 42, duration: 600, paused: false },
  frames: []
};

const resources = [
  {
    url: "https://cdn.example.com/stale.mp4",
    source: "webRequest",
    kind: "video",
    score: 99,
    label: "stale VIDEO",
    request_type: "media",
    playback_match: "range-near-playhead"
  },
  {
    url: "https://cdn.example.com/live/master.m3u8",
    source: "webRequest",
    kind: "hls",
    score: 94,
    label: "HLS",
    request_type: "xmlhttprequest"
  }
];

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
    if (value.endsWith("/api/tasks/task-ok")) {
      return {
        json: async () => ({
          task: {
            id: "task-ok",
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
          return { page, resources };
        }
        if (message.type === "preflight-current-resource") {
          calls.preflight.push(message.resource.url);
          if (message.resource.url.includes("stale.mp4")) {
            return {
              preflight: {
                ok: false,
                downloadable: false,
                code: "download_forbidden",
                message: "HTTP 403"
              }
            };
          }
          return {
            preflight: {
              ok: true,
              downloadable: true,
              strategy: "manifest-ffmpeg",
              kind: "hls",
              message: "OK"
            }
          };
        }
        if (message.type === "start-current-task") {
          calls.start = message;
          return { task_id: "task-ok" };
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
await context.startTask("video");

assert.deepEqual(calls.preflight, [
  "https://cdn.example.com/stale.mp4",
  "https://cdn.example.com/live/master.m3u8"
]);
assert.ok(calls.start, "expected task start after second candidate passes preflight");
assert.equal(calls.start.resources[0].url, "https://cdn.example.com/live/master.m3u8");
assert.equal(calls.start.resources[0].kind, "hls");
assert.match(elements.get("#taskMessage").textContent, /test stop|预检通过/);
assert.equal(context.preflightForResource(resources[0]).code, "download_forbidden");
assert.equal(context.preflightForResource(resources[1]).strategy, "manifest-ffmpeg");
assert.match(elements.get("#resources").innerHTML, /resource-preflight warn/);
assert.match(elements.get("#resources").innerHTML, /download_forbidden/);
assert.match(elements.get("#resources").innerHTML, /resource-preflight ok/);
assert.match(elements.get("#resources").innerHTML, /hls/);
