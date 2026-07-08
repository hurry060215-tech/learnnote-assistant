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
  resourcePreflight: [],
  start: null
};

const page = {
  title: "Course player",
  page_url: "https://course.example.com/lesson",
  active_video: { src: "blob:https://course.example.com/player", current_time: 32, duration: 900, paused: false },
  frames: []
};

const resources = [
  {
    url: "https://cdn.example.com/stale-ad.mp4",
    source: "webRequest",
    kind: "video",
    score: 100,
    label: "stale media",
    request_type: "media"
  },
  {
    url: "https://cdn.example.com/current/master.m3u8",
    source: "webRequest",
    kind: "hls",
    score: 94,
    label: "current hls",
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
    if (value.endsWith("/health")) return { json: async () => ({ ffmpeg: true }) };
    if (value.endsWith("/api/tasks")) return { json: async () => ({ tasks: [] }) };
    if (value.includes("/api/tasks/task-from-second-candidate")) {
      return {
        ok: true,
        json: async () => ({
          task: {
            id: "task-from-second-candidate",
            status: "failed",
            phase: "failed",
            progress: 0,
            message: "terminal test task",
            selected_resource: resources[1],
            download_attempts: []
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
        if (message.type === "preflight-current-page") {
          calls.pagePreflight += 1;
          return {
            report: {
              ok: true,
              ready: false,
              code: "download_forbidden",
              message: "首个候选 HTTP 403，还有候选未探测",
              selected_url: "",
              candidate_count: 2,
              probed_count: 1,
              downloadable_count: 0,
              candidates: [{
                rank: 1,
                resource: resources[0],
                preflight: {
                  ok: false,
                  downloadable: false,
                  code: "download_forbidden",
                  message: "HTTP 403"
                }
              }]
            }
          };
        }
        if (message.type === "preflight-current-resource") {
          calls.resourcePreflight.push(message.resource.url);
          if (message.resource.url.includes("stale-ad.mp4")) {
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
          return { task_id: "task-from-second-candidate" };
        }
        throw new Error(`unexpected message: ${message.type}`);
      }
    },
    tabs: { create() {} }
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

assert.equal(calls.pagePreflight, 1);
assert.deepEqual(calls.resourcePreflight, [
  "https://cdn.example.com/current/master.m3u8"
]);
assert.ok(calls.start, "expected task to start after later candidate preflight passes");
assert.equal(context.selectedResource().url, "https://cdn.example.com/current/master.m3u8");
assert.equal(calls.start.resources[0].url, "https://cdn.example.com/current/master.m3u8");
assert.equal(context.preflightForResource(resources[1]).downloadable, true);
