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

const page = {
  title: "Course player",
  page_url: "https://mooc1.chaoxing.com/mycourse/studentstudy",
  page_text: "lesson text",
  active_video: { src: "blob:https://mooc1.chaoxing.com/player", current_time: 88, duration: 900, paused: false },
  frames: []
};

const playbackApi = {
  url: "https://mooc1.chaoxing.com/ananas/status/play?id=course-video",
  source: "webRequest",
  kind: "unknown",
  score: 30,
  label: "Chaoxing play API",
  request_type: "xmlhttprequest",
  method: "POST",
  request_body: { content: "objectid=abc&dtoken=def", type: "form" },
  request_headers: { Referer: page.page_url }
};

const staleDownload = {
  url: "https://cdn.example.com/archive.mp4",
  source: "webRequest",
  kind: "video",
  score: 96,
  label: "stale archive mp4",
  request_type: "media"
};

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
          return { page, resources: [staleDownload, playbackApi] };
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

assert.equal(context.selectedResource().url, playbackApi.url);
assert.equal(context.looksLikePlayableEndpoint(context.selectedResource()), true);
assert.equal(context.hasReplayableRequestBody(context.selectedResource()), true);
const queueUrls = context.preflightCandidatesForStart("video").slice(0, 2).map(item => item.url);
assert.equal(queueUrls[0], playbackApi.url);
assert.equal(queueUrls[1], staleDownload.url);
