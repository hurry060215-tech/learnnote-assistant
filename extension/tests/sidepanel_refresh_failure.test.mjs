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
  preflight: 0,
  start: 0
};

const page = {
  title: "Old course player",
  page_url: "https://course.example.com/old-lesson",
  page_text: "old lesson text",
  active_video: { src: "https://cdn.example.com/old.mp4", current_time: 12, duration: 120, paused: false },
  frames: []
};

const resources = [{
  url: "https://cdn.example.com/old.mp4",
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
          if (calls.collect === 1) return { page, resources };
          return { error: "cannot access active tab" };
        }
        if (message.type === "preflight-current-resource") {
          calls.preflight += 1;
          return { preflight: { ok: true, downloadable: true } };
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
assert.equal(calls.preflight, 0);
assert.equal(calls.start, 0);
assert.match(elements.get("#taskMessage").textContent, /刷新当前页面失败/);
