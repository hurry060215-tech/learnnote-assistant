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

const startCalls = [];
let preflightCalls = 0;

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
    if (value.includes("/api/tasks/task-")) {
      return {
        json: async () => ({
          task: {
            id: value.split("/").pop(),
            title: "Started task",
            status: "success",
            phase: "completed",
            progress: 100,
            source_type: "current_page",
            visual_windows: []
          }
        })
      };
    }
    if (value.includes("/api/tasks/from-current-page")) {
      startCalls.push("fetch-current-page");
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
              active_video: {
                src: "blob:https://course.example.com/player",
                current_time: 10,
                duration: 120,
                paused: false
              },
              frames: []
            },
            resources: [{
              url: "https://cdn.example.com/lesson.mp4",
              source: "webRequest",
              kind: "video",
              mime: "video/mp4",
              score: 96,
              playback_match: "blob-source"
            }]
          };
        }
        if (message.type === "preflight-current-page") {
          preflightCalls += 1;
          const resource = message.resources[0];
          return {
            report: {
              ok: true,
              ready: true,
              selected_url: resource.url,
              downloadable_count: 1,
              candidate_count: 1,
              probed_count: 1,
              candidates: [{
                resource,
                preflight: {
                  ok: true,
                  downloadable: true,
                  strategy: "direct-file-probe",
                  kind: "video",
                  url: resource.url,
                  resolved_url: resource.url,
                  message: "预检通过"
                }
              }]
            }
          };
        }
        if (message.type === "start-current-task") {
          startCalls.push(message.mode);
          return { task_id: `task-${message.mode}` };
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

await sourceButtons[1].listeners.click();
assert.equal(sourceButtons[0].classList.contains("active"), false);
assert.equal(sourceButtons[1].classList.contains("active"), true);
assert.equal(elements.get("#localVideoCard").scrollCount, 1);
assert.equal(elements.get("#localVideoCard").dataset.localState, "idle");
assert.equal(elements.get("#fileInput").clicks, 0);
assert.deepEqual(startCalls, []);

await sourceButtons[2].listeners.click();
assert.equal(sourceButtons[1].classList.contains("active"), false);
assert.equal(sourceButtons[2].classList.contains("active"), true);
assert.equal(elements.get("#textButton").focusCount, 1);
assert.deepEqual(startCalls, []);

await sourceButtons[0].listeners.click();
assert.equal(sourceButtons[0].classList.contains("active"), true);
assert.equal(elements.get("#currentStudyCard").scrollCount, 1);
assert.equal(preflightCalls, 0);
assert.deepEqual(startCalls, []);
