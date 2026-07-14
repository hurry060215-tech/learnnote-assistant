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
  files: []
});

const documentStub = {
  body: { dataset: {} },
  querySelector(selector) {
    if (!elements.has(selector)) elements.set(selector, makeElement());
    return elements.get(selector);
  },
  querySelectorAll() {
    return [];
  }
};

let startCalls = 0;
let openedTabs = 0;
const context = {
  console,
  document: documentStub,
  location: { href: "chrome-extension://learnnote/sidepanel.html" },
  navigator: { clipboard: { writeText() {} } },
  window: { open() {} },
  FormData: class FormData {},
  URL,
  fetch: async () => {
    throw new TypeError("Failed to fetch");
  },
  chrome: {
    storage: {
      local: {
        async get(defaults) { return defaults; },
        async set() {}
      }
    },
    runtime: {
      getManifest() { return { version: "0.1.21" }; },
      async sendMessage(message) {
        if (message.type === "get-current-context") {
          return {
            tab: { id: 7, url: "https://www.bilibili.com/video/BV181wezqEgK" },
            page: {
              title: "Bilibili lesson",
              page_url: "https://www.bilibili.com/video/BV181wezqEgK",
              page_text: "",
              active_video: null,
              frames: []
            },
            resources: []
          };
        }
        if (message.type === "start-current-task") startCalls += 1;
        return { error: "Failed to fetch" };
      }
    },
    tabs: {
      create() { openedTabs += 1; }
    }
  },
  setTimeout,
  clearTimeout
};
context.window = { ...context.window, location: context.location };

vm.createContext(context);
const code = await readFile(new URL("../sidepanel.js", import.meta.url), "utf8");
vm.runInContext(code, context);

await new Promise(resolve => setTimeout(resolve, 10));
await context.startTask("video");

assert.equal(startCalls, 0);
assert.equal(openedTabs, 0);
assert.equal(elements.get("#summarizeButton").disabled, false);
assert.match(elements.get("#backendStatus").textContent, /请先打开 LearnNote 客户端/);
assert.match(elements.get("#taskMessage").textContent, /客户端尚未启动/);

const opened = await context.openWorkbench("", "note");
assert.equal(opened, false);
assert.equal(openedTabs, 0);
assert.match(elements.get("#taskMessage").textContent, /客户端尚未启动/);
