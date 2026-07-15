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
let activeTabId = 7;
const sentMessages = [];
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
      onMessage: {
        addListener(listener) {
          onMessageListener = listener;
        }
      },
      async sendMessage(message) {
        sentMessages.push(message);
        if (message.type === "get-current-context") {
          collectCalls += 1;
          return {
            tab: { id: activeTabId, url: `https://course.example.com/lesson-${activeTabId}` },
            page: {
              title: `Course player ${collectCalls}`,
              page_url: `https://course.example.com/lesson-${activeTabId}`,
              playback_session_id: `session-${activeTabId}-${collectCalls}`,
              page_text: "lesson text",
              active_video: collectCalls > 1 ? {
                src: "https://cdn.example.com/lesson.mp4",
                current_time: 42,
                duration: 600,
                paused: false,
                is_visible: true,
                width: 1280,
                height: 720
              } : null,
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

activeTabId = 99;
onMessageListener({ type: "current-context-updated", tabId: 99, reason: "tab-activated" });
await new Promise(resolve => setTimeout(resolve, 0));

assert.equal(collectCalls, 2);
assert.equal(sentMessages[1].targetTabId, 99);
assert.equal(elements.get("#resourceCount").textContent, "1");
assert.match(elements.get("#taskMessage").textContent, /当前标签页/);
assert.equal(elements.get("#pageIdentityLabel").textContent, "正在播放的视频");
assert.equal(elements.get("#pageUrl").textContent, "course.example.com");
assert.match(elements.get("#activeVideo").innerHTML, /播放中/);
assert.match(elements.get("#activeVideo").innerHTML, /已锁定/);
assert.doesNotMatch(elements.get("#activeVideo").innerHTML, /Frame|播放器尺寸|cdn\.example\.com/);

vm.runInContext(`resourceSelectionPinned = true; selectedResourceUrl = "https://cdn.example.com/lesson.mp4";`, context);

onMessageListener({ type: "current-context-updated", tabId: 7, reason: "media" });
await new Promise(resolve => setTimeout(resolve, 0));
assert.equal(collectCalls, 2);

onMessageListener({ type: "current-context-updated", tabId: 99, reason: "media" });
await new Promise(resolve => setTimeout(resolve, 0));
assert.equal(collectCalls, 3);
assert.equal(sentMessages.at(-1).targetTabId, 99);
assert.match(elements.get("#taskMessage").textContent, /刷新候选资源/);
assert.equal(vm.runInContext("resourceSelectionPinned", context), false, "expected a changed playback session to release the previous resource pin");
assert.equal(vm.runInContext("currentPlaybackSessionId", context), "session-99-3");
