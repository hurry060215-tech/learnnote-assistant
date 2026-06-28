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
  start: null
};

const page = {
  title: "Text only lesson",
  page_url: "https://course.example.com/text-only",
  page_text: "第一章 函数封装\n本节介绍函数参数、返回值和调用顺序。",
  active_video: null,
  frames: []
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
    if (value.endsWith("/health")) {
      return { json: async () => ({ ffmpeg: true }) };
    }
    if (value.endsWith("/api/tasks")) {
      return { json: async () => ({ tasks: [] }) };
    }
    if (value.endsWith("/api/tasks/text-task")) {
      return {
        json: async () => ({
          task: {
            id: "text-task",
            status: "failed",
            phase: "failed",
            progress: 100,
            message: "test stop",
            source_type: "page_text"
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
          return { page, resources: [] };
        }
        if (message.type === "start-current-task") {
          calls.start = message;
          return { task_id: "text-task" };
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
context.renderContext();

assert.equal(context.routeSummaryState(), "empty");
assert.match(elements.get("#routeSummary").innerHTML, /data-route-action="redetect"/);
assert.match(elements.get("#routeSummary").innerHTML, /data-route-action="text"/);
assert.match(elements.get("#launchBar").innerHTML, /data-route-action="redetect"/);
assert.match(elements.get("#launchBar").innerHTML, /data-route-action="text"/);

context.handleRouteAction("redetect");
await new Promise(resolve => setTimeout(resolve, 0));
assert.equal(calls.collect, 2);

context.handleRouteAction("text");
await new Promise(resolve => setTimeout(resolve, 0));

assert.equal(calls.collect, 3);
assert.ok(calls.start, "expected page-text task start");
assert.equal(calls.start.mode, "page_text");
assert.equal(calls.start.page.page_text, page.page_text);
assert.equal(calls.start.resources.length, 0);
