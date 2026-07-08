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
  pagePreflight: null,
  resourcePreflight: 0
};

const page = {
  title: "Blob player with page fallback",
  page_url: "https://course.example.com/lesson",
  page_text: "lesson text",
  active_video: { src: "blob:https://course.example.com/player", current_time: 42, duration: 600, paused: false },
  frames: [{ frame_id: 3, page_url: "https://course.example.com/player-iframe" }]
};

const resources = [{
  url: "blob:https://course.example.com/player",
  source: "activeVideo",
  kind: "blob",
  score: 5,
  label: "active blob"
}];

const discovered = {
  url: "https://cdn.example.com/live/master.m3u8",
  source: "page-scan",
  kind: "hls",
  mime: "application/vnd.apple.mpegurl",
  score: 96,
  label: "backend page scan"
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
      async sendMessage(message) {
        if (message.type === "get-current-context") {
          calls.collect += 1;
          return { tab: { id: 77 }, page, resources };
        }
        if (message.type === "preflight-current-page") {
          calls.pagePreflight = message;
          return {
            report: {
              ok: true,
              ready: true,
              code: "",
              message: "后端页面扫描找到 HLS",
              selected_url: discovered.url,
              candidate_count: 1,
              probed_count: 1,
              downloadable_count: 1,
              candidates: [{
                rank: 1,
                resource: discovered,
                preflight: {
                  ok: true,
                  downloadable: true,
                  strategy: "manifest-probe",
                  kind: "hls",
                  url: discovered.url,
                  message: "ok"
                }
              }]
            }
          };
        }
        if (message.type === "preflight-current-resource") {
          calls.resourcePreflight += 1;
          return { preflight: { ok: false, downloadable: false, code: "no_media_found" } };
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
const report = await context.runPreflight();

assert.ok(report, "expected page-level preflight report for blob-only playback evidence");
assert.ok(calls.pagePreflight.resources.length >= 2);
assert.ok(
  calls.pagePreflight.resources.some(item => item.url === "https://course.example.com/player-iframe" && item.request_type === "page-scan-fallback"),
  "expected iframe URL to be passed as a backend page-scan context"
);
assert.ok(
  calls.pagePreflight.resources.some(item => item.url === "https://course.example.com/lesson" && item.request_type === "page-scan-fallback"),
  "expected top page URL to be passed as a backend page-scan context"
);
assert.equal(calls.pagePreflight.page.page_url, "https://course.example.com/lesson");
assert.equal(calls.resourcePreflight, 0);
assert.equal(context.selectedResource().url, "https://cdn.example.com/live/master.m3u8");
assert.equal(context.preflightForResource(context.selectedResource()).downloadable, true);
assert.match(elements.get("#taskMessage").textContent, /后端页面扫描找到 HLS/);
