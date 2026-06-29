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

const stored = { backendUrl: "https://evil.example" };
const calls = { storageSet: [], fetchUrls: [] };
let promptValue = "";

const context = {
  console,
  document: documentStub,
  location: { href: "chrome-extension://learnnote/sidepanel.html" },
  navigator: { clipboard: { writeText() {} } },
  window: { open() {} },
  FormData: class FormData {},
  URL,
  prompt: () => promptValue,
  fetch: async url => {
    calls.fetchUrls.push(String(url));
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
          return { ...defaults, ...stored };
        },
        async set(value) {
          calls.storageSet.push(value);
          Object.assign(stored, value);
        },
        async remove(key) {
          delete stored[key];
        }
      }
    },
    runtime: {
      async sendMessage(message) {
        if (message.type === "get-current-context") {
          return { page: null, resources: [] };
        }
        throw new Error(`unexpected message: ${message.type}`);
      },
      onMessage: { addListener() {} }
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

assert.equal(context.normalizeBackendUrl("127.0.0.1:8000/"), "http://127.0.0.1:8000");
assert.equal(context.normalizeBackendUrl("localhost:8765/workbench"), "http://localhost:8765");
assert.equal(context.normalizeBackendUrl("https://evil.example"), "");
assert.equal(context.normalizeBackendUrl("ftp://127.0.0.1:8765"), "");
assert.equal(context.normalizeBackendUrl("http://user:pass@127.0.0.1:8765"), "");

assert.equal(context.workbenchUrl("task-default", "frames"), "http://127.0.0.1:8765/?task=task-default&tab=frames");

promptValue = "127.0.0.1:8000/";
await context.saveSettings();

assert.equal(calls.storageSet.at(-1).backendUrl, "http://127.0.0.1:8000");
assert.equal(context.workbenchUrl("task-local", "note"), "http://127.0.0.1:8000/?task=task-local&tab=note");

calls.storageSet = [];
promptValue = "https://evil.example";
await context.saveSettings();

assert.equal(calls.storageSet.length, 0);
assert.equal(context.workbenchUrl("task-local", "note"), "http://127.0.0.1:8000/?task=task-local&tab=note");
assert.match(elements.get("#backendStatus").textContent, /127\.0\.0\.1|localhost/);
assert.match(elements.get("#taskMessage").textContent, /本机后端/);
