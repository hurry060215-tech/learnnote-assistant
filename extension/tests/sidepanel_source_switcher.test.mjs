import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const elements = new Map();

const makeClassList = () => {
  const values = new Set();
  return {
    values,
    add(name) {
      values.add(name);
    },
    remove(name) {
      values.delete(name);
    },
    toggle(name, force) {
      const enabled = force === undefined ? !values.has(name) : Boolean(force);
      if (enabled) values.add(name);
      else values.delete(name);
      return enabled;
    },
    contains(name) {
      return values.has(name);
    }
  };
};

const makeElement = () => ({
  listeners: {},
  classList: makeClassList(),
  dataset: {},
  style: {},
  value: "",
  textContent: "",
  innerHTML: "",
  disabled: false,
  hidden: false,
  files: [],
  clicks: 0,
  focusCount: 0,
  scrollCount: 0,
  addEventListener(type, handler) {
    this.listeners[type] = handler;
  },
  click() {
    this.clicks += 1;
  },
  focus() {
    this.focusCount += 1;
  },
  scrollIntoView() {
    this.scrollCount += 1;
  },
  querySelector() {
    return null;
  }
});

const sourceButtons = [
  { ...makeElement(), dataset: { sourceAction: "summarize" } },
  { ...makeElement(), dataset: { sourceAction: "local" } },
  { ...makeElement(), dataset: { sourceAction: "text" } }
];
sourceButtons[0].classList.add("active");

const documentStub = {
  querySelector(selector) {
    if (!elements.has(selector)) elements.set(selector, makeElement());
    return elements.get(selector);
  },
  querySelectorAll(selector) {
    if (selector === "[data-source-action]") return sourceButtons;
    return [];
  }
};

let startCalls = 0;

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
    if (value.includes("/api/tasks/from-current-page")) {
      startCalls += 1;
      return { ok: true, json: async () => ({ task_id: "unexpected-task" }) };
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
          return {
            page: {
              title: "Current page",
              page_url: "https://course.example.com/lesson",
              page_text: "page text",
              active_video: null,
              frames: []
            },
            resources: []
          };
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

sourceButtons[1].listeners.click();
assert.equal(sourceButtons[0].classList.contains("active"), false);
assert.equal(sourceButtons[1].classList.contains("active"), true);
assert.equal(elements.get("#localDrop").scrollCount, 1);
assert.equal(elements.get("#fileInput").clicks, 0);
assert.equal(startCalls, 0);

sourceButtons[2].listeners.click();
assert.equal(sourceButtons[1].classList.contains("active"), false);
assert.equal(sourceButtons[2].classList.contains("active"), true);
assert.equal(elements.get("#textButton").focusCount, 1);
assert.equal(startCalls, 0);

sourceButtons[0].listeners.click();
assert.equal(sourceButtons[0].classList.contains("active"), true);
assert.equal(elements.get("#currentStudyCard").scrollCount, 1);
assert.equal(startCalls, 0);
