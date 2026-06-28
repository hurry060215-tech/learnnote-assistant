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
  resourcePreflight: 0
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
    if (value.endsWith("/health")) return { json: async () => ({ ffmpeg: true }) };
    if (value.endsWith("/api/tasks")) return { json: async () => ({ tasks: [] }) };
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
              ready: true,
              message: "page report ok",
              selected_url: "https://cdn.example.com/live/master.m3u8",
              candidate_count: 2,
              probed_count: 2,
              downloadable_count: 1,
              candidates: [
                {
                  rank: 1,
                  resource: resources[0],
                  preflight: {
                    ok: false,
                    downloadable: false,
                    code: "download_forbidden",
                    message: "HTTP 403"
                  }
                },
                {
                  rank: 2,
                  resource: resources[1],
                  preflight: {
                    ok: true,
                    downloadable: true,
                    strategy: "manifest-probe",
                    kind: "hls",
                    message: "OK"
                  }
                }
              ]
            }
          };
        }
        if (message.type === "preflight-current-resource") {
          calls.resourcePreflight += 1;
          return { preflight: { ok: false, downloadable: false } };
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
await context.runPreflight();

assert.equal(calls.pagePreflight, 1);
assert.equal(calls.resourcePreflight, 0);
assert.equal(context.selectedResource().url, "https://cdn.example.com/live/master.m3u8");
assert.equal(context.preflightForResource(resources[0]).code, "download_forbidden");
assert.equal(context.preflightForResource(resources[1]).strategy, "manifest-probe");
assert.match(elements.get("#taskMessage").textContent, /page report ok/);
assert.match(elements.get("#resources").innerHTML, /preflight-audit-summary/);
assert.match(elements.get("#resources").innerHTML, /预检审计/);
assert.match(elements.get("#resources").innerHTML, /1 可下载/);
assert.match(elements.get("#resources").innerHTML, /resource-preflight warn/);
assert.match(elements.get("#resources").innerHTML, /resource-preflight ok/);
