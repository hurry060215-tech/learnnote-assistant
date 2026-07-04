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
  pagePreflight: 0,
  resourcePreflight: 0,
  start: null,
  removed: []
};

const page = {
  title: "Blob-only player",
  page_url: "chrome-extension://learnnote/sidepanel.html",
  page_text: "lesson text",
  active_video: { src: "blob:https://course.example.com/player", current_time: 42, duration: 600, paused: false },
  frames: []
};

const resources = [{
  url: "blob:https://course.example.com/player",
  source: "activeVideo",
  kind: "blob",
  score: 5,
  label: "active blob"
}];

const pendingSidePanelIntent = {
  action: "summarize-current-video",
  tabId: 77,
  createdAt: Date.now()
};

const realSetTimeout = setTimeout;
const timerDelays = [];

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
        if (message.type === "preflight-current-page") {
          calls.pagePreflight += 1;
          return { report: { ok: false, ready: false, code: "no_media_found", candidates: [] } };
        }
        if (message.type === "preflight-current-resource") {
          calls.resourcePreflight += 1;
          return { preflight: { ok: false, downloadable: false, code: "no_media_found" } };
        }
        if (message.type === "start-current-task") {
          calls.start = message;
          return { task_id: "should-not-start" };
        }
        throw new Error(`unexpected message: ${message.type}`);
      }
    },
    tabs: {
      create() {}
    }
  },
  setTimeout(callback, ms) {
    timerDelays.push(ms);
    return realSetTimeout(callback, 0);
  },
  clearTimeout
};
context.window = { ...context.window, location: context.location };

vm.createContext(context);
const sidepanelCode = await readFile(new URL("../sidepanel.js", import.meta.url), "utf8");
vm.runInContext(sidepanelCode, context);

for (let i = 0; i < 20 && calls.collect < 5; i += 1) {
  await new Promise(resolve => realSetTimeout(resolve, 0));
}

assert.ok(calls.collect >= 5, "expected one-click intent to retry before giving up");
assert.ok(timerDelays.filter(delay => delay === 900).length >= 4, "expected one-click retry timers");
assert.equal(calls.pagePreflight, 0);
assert.equal(calls.resourcePreflight, 0);
assert.equal(calls.start, null);
assert.deepEqual(calls.removed, ["pendingSidePanelIntent"]);
assert.match(elements.get("#taskMessage").textContent, /本地视频上传|页面文本总结|重新检测/);
