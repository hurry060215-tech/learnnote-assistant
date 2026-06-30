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
  preflight: null,
  preflightKindAtRequest: "",
  start: null
};

const page = {
  title: "Course player",
  page_url: "https://course.example.com/lesson",
  page_text: "lesson text",
  active_video: { src: "https://course.example.com/api/play?id=42", current_time: 18, duration: 900, paused: false },
  frames: []
};

const resources = [{
  url: "https://course.example.com/api/play?id=42",
  source: "webRequest",
  kind: "unknown",
  score: 98,
  label: "JSON play endpoint",
  request_type: "xmlhttprequest",
  request_headers: {
    Referer: "https://course.example.com/lesson",
    "X-Requested-With": "XMLHttpRequest"
  }
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
    if (value.endsWith("/health")) return { json: async () => ({ ffmpeg: true }) };
    if (value.endsWith("/api/tasks")) return { json: async () => ({ tasks: [] }) };
    if (value.endsWith("/api/tasks/task-direct-response")) {
      return {
        json: async () => ({
          task: {
            id: "task-direct-response",
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
          calls.preflight = message;
          calls.preflightKindAtRequest = message.resource.kind;
          return {
            preflight: {
              ok: true,
              downloadable: true,
              strategy: "direct-response-probe",
              kind: "video",
              resolved_url: "https://media.example.com/real/lesson.mp4?sig=abc",
              content_type: "application/json",
              content_length: 96,
              message: "JSON play endpoint resolved to media"
            }
          };
        }
        if (message.type === "start-current-task") {
          calls.start = message;
          return { task_id: "task-direct-response" };
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
assert.equal(calls.preflight.resource.url, "https://course.example.com/api/play?id=42");
assert.equal(calls.preflightKindAtRequest, "unknown");
assert.equal(context.looksLikePlayableEndpoint(resources[0]), true);
assert.ok(calls.start, "expected task start after direct-response preflight");
assert.equal(calls.start.mode, "video");
assert.equal(calls.start.resources[0].url, "https://course.example.com/api/play?id=42");
assert.equal(calls.start.resources[0].kind, "video");
assert.equal(calls.start.resources[0].mime, "video/mp4");
assert.equal(calls.start.resources[0].resolved_url, "https://media.example.com/real/lesson.mp4?sig=abc");
assert.equal(calls.start.resources[0].headers["content-type"], "application/json");
assert.equal(calls.start.resources[0].request_headers.Referer, "https://course.example.com/lesson");
assert.equal(calls.start.resources[0].request_headers["X-Requested-With"], "XMLHttpRequest");
assert.equal(context.preflightForResource(resources[0]).strategy, "direct-response-probe");
assert.equal(resources[0].resolved_url, "https://media.example.com/real/lesson.mp4?sig=abc");
assert.equal(resources[0].mime, "video/mp4");
assert.match(elements.get("#resources").innerHTML, /resource-preflight ok/);
assert.match(elements.get("#resources").innerHTML, /解析媒体 URL/);
