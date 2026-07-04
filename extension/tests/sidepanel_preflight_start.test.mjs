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
  start: 0
};

const page = {
  title: "Course player",
  page_url: "chrome-extension://learnnote/sidepanel.html",
  page_text: "lesson text",
  active_video: { src: "https://cdn.example.com/api/play?id=1", current_time: 12, duration: 120, paused: false },
  frames: []
};

const resources = [{
  url: "https://cdn.example.com/api/play?id=1",
  source: "webRequest",
  kind: "video",
  score: 98,
  label: "VIDEO",
  request_type: "media"
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
              message: "HTTP 403：登录态或 Referer 不匹配",
              selected_url: "",
              candidate_count: 1,
              probed_count: 1,
              downloadable_count: 0,
              candidates: [{
                rank: 1,
                resource: resources[0],
                preflight: {
                  ok: false,
                  downloadable: false,
                  code: "download_forbidden",
                  message: "HTTP 403：登录态或 Referer 不匹配"
                }
              }]
            }
          };
        }
        if (message.type === "preflight-current-resource") {
          calls.resourcePreflight += 1;
          return {
            preflight: {
              ok: false,
              downloadable: false,
              code: "download_forbidden",
              message: "HTTP 403：登录态或 Referer 不匹配"
            }
          };
        }
        if (message.type === "start-current-task") {
          calls.start += 1;
          return { task_id: "should-not-start" };
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
assert.equal(calls.pagePreflight, 1);
assert.equal(calls.resourcePreflight, 0);
assert.equal(calls.start, 0);
assert.match(elements.get("#extractionPlan").innerHTML, /data-step="fallback"/);
assert.match(elements.get("#extractionPlan").innerHTML, /extraction-step blocked/);
assert.match(elements.get("#taskMessage").textContent, /HTTP 403/);

vm.runInContext(`
page = {
  title: "Blob-only player",
  page_url: "chrome-extension://learnnote/sidepanel.html",
  page_text: "lesson text",
  active_video: { src: "blob:https://course.example.com/player", current_time: 12, duration: 120, paused: false },
  frames: []
};
resources = [{
  url: "blob:https://course.example.com/player",
  source: "activeVideo",
  kind: "blob",
  score: 5,
  label: "active blob"
}];
selectedResourceUrl = "blob:https://course.example.com/player";
`, context);

assert.equal(context.preflightCandidatesForStart("video").length, 0);
assert.equal(context.canAttemptBackendPageFallback("video"), false);

const activeOnlyCandidates = context.resourcesWithActiveVideoCandidate([], {
  src: "https://cdn.example.com/current-player?id=active",
  current_time: 33,
  duration: 600,
  width: 1280,
  height: 720,
  frame_id: 4,
  label: "current lesson video"
});
assert.equal(activeOnlyCandidates.length, 1);
assert.equal(activeOnlyCandidates[0].source, "activeVideo");
assert.equal(activeOnlyCandidates[0].kind, "video");
assert.equal(activeOnlyCandidates[0].request_type, "active-video");
assert.equal(activeOnlyCandidates[0].playback_match, "exact-src");
assert.equal(activeOnlyCandidates[0].current_time, 33);

vm.runInContext(`
page = {
  title: "Active only player",
  page_url: "https://course.example.com/watch",
  active_video: { src: "https://cdn.example.com/current-player?id=active", current_time: 33, duration: 600, paused: false },
  frames: []
};
resources = resourcesWithActiveVideoCandidate([], page.active_video);
selectedResourceUrl = "https://cdn.example.com/current-player?id=active";
`, context);

const activeOnlyPreflightCandidates = context.preflightCandidatesForStart("video");
assert.equal(activeOnlyPreflightCandidates.length, 1);
assert.equal(activeOnlyPreflightCandidates[0].source, "activeVideo");
assert.equal(activeOnlyPreflightCandidates[0].url, "https://cdn.example.com/current-player?id=active");
assert.equal(context.selectedResourcesForTask()[0].user_selected, true);

assert.equal(context.mediaKindFromUrl("https://cdn.example.com/live/master.m3u8?token=abc"), "hls");
assert.equal(context.mediaKindFromUrl("https://cdn.example.com/live/manifest.mpd?token=abc"), "dash");
assert.equal(context.mediaKindFromUrl("https://cdn.example.com/course/dashboard-player?id=42"), "video");
