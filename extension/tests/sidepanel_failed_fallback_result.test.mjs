import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const elements = new Map();
const makeElement = () => ({
  listeners: {},
  addEventListener(type, handler) {
    this.listeners[type] = handler;
  },
  classList: {
    add() {},
    remove() {},
    toggle() { return false; },
    contains() { return false; }
  },
  querySelector() { return null; },
  style: {},
  dataset: {},
  value: "",
  textContent: "",
  innerHTML: "",
  disabled: false,
  onclick: null,
  onchange: null,
  files: [],
  focus() {},
  scrollIntoView() {}
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

let noteFetches = 0;
const context = {
  console,
  document: documentStub,
  location: { href: "chrome-extension://learnnote/sidepanel.html" },
  navigator: { clipboard: { writeText() {} } },
  window: { open() {}, location: { href: "chrome-extension://learnnote/sidepanel.html" } },
  FormData: class {},
  fetch: async url => {
    const value = String(url);
    if (value.endsWith("/health")) {
      return { json: async () => ({ ffmpeg: true }) };
    }
    if (value.endsWith("/api/tasks")) {
      return { json: async () => ({ tasks: [] }) };
    }
    if (value.endsWith("/api/tasks/failed-fallback-task")) {
      return {
        json: async () => ({
          task: {
            id: "failed-fallback-task",
            title: "Fallback lesson",
            source_type: "current_page",
            status: "failed",
            phase: "failed",
            progress: 100,
            message: "direct download failed",
            error_code: "download_forbidden",
            error_detail: "HTTP 403",
            note_path: "D:/Projects/learnnote-assistant/data/tasks/failed-fallback-task/note.md",
            summary_diagnostics: { used_page_text_fallback: true },
            options: {}
          }
        })
      };
    }
    if (value.endsWith("/api/tasks/failed-fallback-task/note")) {
      noteFetches += 1;
      return { ok: true, text: async () => "# Fallback Note\n\n页面文本兜底笔记" };
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
          return { page: { title: "Current page", page_url: "https://course.example.com/lesson", frames: [] }, resources: [] };
        }
        throw new Error(`unexpected message: ${message.type}`);
      }
    },
    tabs: { create() {} }
  },
  setTimeout,
  clearTimeout
};
context.window.location = context.location;

vm.createContext(context);
const sidepanelCode = await readFile(new URL("../sidepanel.js", import.meta.url), "utf8");
vm.runInContext(sidepanelCode, context);
await new Promise(resolve => setTimeout(resolve, 0));

vm.runInContext(`currentTaskId = "failed-fallback-task"; selectedTab = "note";`, context);
await context.pollTask();

assert.equal(noteFetches, 1);
assert.match(elements.get("#taskMessage").textContent, /HTTP 403/);
assert.match(elements.get("#result").innerHTML, /Fallback Note/);
assert.match(elements.get("#result").innerHTML, /页面文本兜底笔记/);
assert.match(elements.get("#result").innerHTML, /status-failed/);
