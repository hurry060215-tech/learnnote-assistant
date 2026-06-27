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
  addEventListener() {},
  classList: makeClassList(),
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

class FakeFormData {
  constructor() {
    this.values = [];
  }

  append(name, value) {
    this.values.push([name, value]);
  }

  get(name) {
    return this.values.find(([key]) => key === name)?.[1];
  }
}

const uploadBodies = [];
const lessonFile = { name: "local-lesson.mp4", size: 123456, type: "video/mp4" };
let uploadShouldFail = false;

const context = {
  console,
  document: documentStub,
  location: { href: "chrome-extension://learnnote/sidepanel.html" },
  navigator: { clipboard: { writeText() {} } },
  window: { open() {} },
  FormData: FakeFormData,
  fetch: async (url, options = {}) => {
    const value = String(url);
    if (value.endsWith("/health")) {
      return { json: async () => ({ ffmpeg: true }) };
    }
    if (value.endsWith("/api/tasks")) {
      return { json: async () => ({ tasks: [] }) };
    }
    if (value.endsWith("/api/tasks/from-local")) {
      uploadBodies.push(options.body);
      if (uploadShouldFail) {
        return { ok: false, json: async () => ({ detail: { message: "unsupported local file" } }) };
      }
      return { ok: true, json: async () => ({ task_id: "local-task" }) };
    }
    if (value.endsWith("/api/tasks/local-task")) {
      return {
        json: async () => ({
          task: {
            id: "local-task",
            title: "local-lesson.mp4",
            source_type: "local",
            status: "success",
            phase: "completed",
            progress: 100,
            message: "done",
            media_path: "D:/Projects/learnnote-assistant/data/tasks/local-task/media.mp4",
            options: {}
          }
        })
      };
    }
    if (value.endsWith("/api/tasks/local-task/transcript") || value.endsWith("/api/tasks/local-task/note")) {
      return { ok: false, json: async () => ({}), text: async () => "" };
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
              page_text: "",
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
const sidepanelHtml = await readFile(new URL("../sidepanel.html", import.meta.url), "utf8");
vm.runInContext(sidepanelCode, context);

await new Promise(resolve => setTimeout(resolve, 0));
assert.match(sidepanelHtml, /accept="video\/\*,\.mp4,\.m4v,\.mov,\.mkv,\.webm,\.flv,\.avi"/);
assert.equal(context.isSupportedLocalVideoFile({ name: "lesson.mkv", type: "" }), true);
assert.equal(context.isSupportedLocalVideoFile({ name: "lesson.flv", type: "" }), true);
assert.equal(context.isSupportedLocalVideoFile({ name: "bad.txt", type: "text/plain" }), false);

elements.get("#fileInput").files = [lessonFile];
await context.uploadLocal();
await new Promise(resolve => setTimeout(resolve, 0));

assert.equal(uploadBodies.length, 1);
assert.equal(uploadBodies[0].get("file"), lessonFile);
assert.equal(uploadBodies[0].get("title"), "local-lesson.mp4");
assert.match(uploadBodies[0].get("options"), /"frame_interval":20/);
assert.equal(elements.get("#localDropText").textContent, "local-lesson.mp4");
assert.equal(elements.get("#uploadButton").disabled, false);
assert.equal(elements.get("#localDrop").classList.contains("uploading"), false);
assert.match(elements.get("#taskMessage").textContent, /done/);

uploadShouldFail = true;
elements.get("#fileInput").files = [{ name: "bad.txt", size: 10, type: "text/plain" }];
await context.uploadLocal();

assert.equal(uploadBodies.length, 1);
assert.equal(elements.get("#uploadButton").disabled, false);
assert.equal(elements.get("#localDrop").classList.contains("uploading"), false);
assert.equal(elements.get("#taskMessage").textContent, "bad.txt 不是支持的视频格式。");
