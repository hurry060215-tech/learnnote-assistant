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
  frames: [{
    url: "https://course.example.com/player-iframe",
    title: "Player iframe",
    frame_id: 9
  }]
};

const resources = [{
  url: "https://cdn.example.com/protected/play?id=1",
  source: "webRequest",
  kind: "video",
  score: 98,
  label: "protected VIDEO",
  request_type: "media",
  frame_url: "https://course.example.com/player-iframe"
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
    if (value.endsWith("/api/tasks/task-fallback")) {
      return {
        json: async () => ({
          task: {
            id: "task-fallback",
            status: "failed",
            phase: "failed",
            progress: 100,
            message: "backend fallback attempted",
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
          return {
            preflight: {
              ok: false,
              downloadable: false,
              code: "download_forbidden",
              status_code: 403,
              message: "HTTP 403"
            }
          };
        }
        if (message.type === "start-current-task") {
          calls.start = message;
          return { task_id: "task-fallback" };
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

assert.equal(calls.collect, 2);
assert.deepEqual(calls.preflight, ["https://cdn.example.com/protected/play?id=1"]);
assert.ok(calls.start, "expected backend task start when page URL can be scanned");
assert.equal(calls.start.mode, "video");
assert.equal(calls.start.page.page_url, "https://course.example.com/lesson");
assert.equal(calls.start.resources[0].url, "https://cdn.example.com/protected/play?id=1");
assert.equal(context.canAttemptBackendPageFallback("video"), true);
assert.match(elements.get("#extractionPlan").innerHTML, /data-step="fallback"/);
assert.match(elements.get("#extractionPlan").innerHTML, /extraction-step active/);
assert.match(elements.get("#extractionPlan").innerHTML, /yt-dlp/);
assert.match(elements.get("#taskMessage").textContent, /backend fallback attempted|yt-dlp|HTTP 403/);
