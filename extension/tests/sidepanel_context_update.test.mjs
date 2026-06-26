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

let onMessageListener = null;
let collectCalls = 0;
const context = {
  console,
  document: documentStub,
  location: { href: "chrome-extension://learnnote/sidepanel.html" },
  navigator: { clipboard: { writeText() {} } },
  window: { open() {} },
  FormData: class FormData {},
  setTimeout(fn) {
    fn();
    return 1;
  },
  clearTimeout() {},
  fetch: async url => {
    if (String(url).endsWith("/health")) {
      return { json: async () => ({ ffmpeg: true }) };
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
      onMessage: {
        addListener(listener) {
          onMessageListener = listener;
        }
      },
      async sendMessage(message) {
        if (message.type === "get-current-context") {
          collectCalls += 1;
          return {
            tab: { id: 7, url: "https://course.example.com/lesson" },
            page: {
              title: `Course player ${collectCalls}`,
              page_url: "https://course.example.com/lesson",
              page_text: "lesson text",
              active_video: null,
              frames: []
            },
            resources: collectCalls > 1 ? [{
              url: "https://cdn.example.com/lesson.mp4",
              source: "webRequest",
              kind: "video",
              score: 96,
              label: "VIDEO"
            }] : []
          };
        }
        throw new Error(`unexpected message: ${message.type}`);
      }
    },
    tabs: {
      create() {}
    }
  }
};
context.window = { ...context.window, location: context.location };

vm.createContext(context);
const sidepanelCode = await readFile(new URL("../sidepanel.js", import.meta.url), "utf8");
vm.runInContext(sidepanelCode, context);

await new Promise(resolve => setTimeout(resolve, 0));
assert.equal(collectCalls, 1);
assert.equal(typeof onMessageListener, "function");
assert.equal(context.shouldAcceptContextUpdate({ type: "current-context-updated" }), true);

onMessageListener({ type: "current-context-updated", tabId: 99, reason: "media" });
await new Promise(resolve => setTimeout(resolve, 0));
assert.equal(collectCalls, 1);

onMessageListener({ type: "current-context-updated", tabId: 7, reason: "media" });
await new Promise(resolve => setTimeout(resolve, 0));

assert.equal(collectCalls, 2);
assert.equal(elements.get("#resourceCount").textContent, "1");
assert.match(elements.get("#taskMessage").textContent, /刷新候选资源/);
