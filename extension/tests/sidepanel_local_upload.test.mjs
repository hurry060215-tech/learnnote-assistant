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
  addEventListener(type, handler) {
    this.listeners[type] = handler;
  },
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
  files: [],
  clicks: 0,
  click() {
    this.clicks += 1;
    if (typeof this.onclick === "function") return this.onclick();
  },
  scrollIntoView() {
    this.scrolled = true;
  },
  focus() {
    this.focused = true;
  }
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
const sidepanelCss = await readFile(new URL("../sidepanel.css", import.meta.url), "utf8");
vm.runInContext(sidepanelCode, context);

await new Promise(resolve => setTimeout(resolve, 0));
assert.match(sidepanelHtml, /sidepanel\.css\?v=20260712-v0113/);
assert.match(sidepanelHtml, /<body data-ui="learnnote-sidepanel-v2" data-source-mode="summarize">/);
assert.match(sidepanelHtml, /sidepanel\.js\?v=20260712-v0113/);
assert.doesNotMatch(sidepanelHtml, /class="capture-cockpit"/);
assert.match(sidepanelHtml, /class="learning-goal-control"/);
assert.match(sidepanelHtml, /自动整理/);
assert.match(sidepanelHtml, /深入理解/);
assert.match(sidepanelHtml, /快速回顾/);
assert.match(sidepanelHtml, /备考自测/);
assert.match(sidepanelHtml, /id="localVideoCard"/);
assert.match(sidepanelHtml, /本地视频同管线/);
assert.match(sidepanelHtml, /选择本地视频/);
assert.match(sidepanelHtml, /抽帧网格 \+ 时间窗/);
assert.match(sidepanelCss, /\.capture-cockpit/);
assert.match(sidepanelCss, /Compact Side Panel workbench/);
assert.match(sidepanelCss, /preserving the direct-extraction promise/);
assert.doesNotMatch(sidepanelCss, /\.current-card \.source-route-rail,\s*\.current-card \.capture-cockpit,\s*\.current-card \.mode-row \{\s*display: none;/);
assert.match(sidepanelCss, /\.current-card #currentStudyCard \{\s*order: 3;/);
assert.match(sidepanelCss, /\.evidence-steps/);
assert.match(sidepanelCss, /\.local-video-card/);
assert.match(sidepanelCss, /\.local-video-actions/);
assert.match(sidepanelCss, /writing-mode:\s*vertical-rl/);
assert.match(sidepanelCss, /\.workbench-local-pipeline/);
assert.match(sidepanelCss, /Side Panel visual v2: one obvious learning path at a 420px panel width/);
assert.match(sidepanelCss, /grid-template-columns: repeat\(4, minmax\(0, 1fr\)\)/);
assert.match(sidepanelCss, /body\[data-ui="learnnote-sidepanel-v2"\]\[data-panel-mode="study"\] \.actions/);
assert.match(sidepanelHtml, /accept="video\/\*,\.mp4,\.m4v,\.mov,\.mkv,\.webm,\.flv,\.avi"/);
assert.equal(context.isSupportedLocalVideoFile({ name: "lesson.mkv", type: "" }), true);
assert.equal(context.isSupportedLocalVideoFile({ name: "lesson.flv", type: "" }), true);
assert.equal(context.isSupportedLocalVideoFile({ name: "lesson.avi", type: "" }), true);
assert.equal(context.isSupportedLocalVideoFile({ name: "bad.txt", type: "text/plain" }), false);

elements.get("#chooseLocalButton").onclick();
assert.equal(elements.get("#fileInput").clicks, 1);
assert.equal(elements.get("#localVideoCard").classList.contains("focus-pulse"), true);

elements.get("#uploadButton").onclick();
assert.equal(elements.get("#fileInput").clicks, 2);
assert.equal(elements.get("#localVideoCard").classList.contains("focus-pulse"), true);

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
assert.equal(elements.get("#localVideoCard").classList.contains("state-ready"), true);
assert.match(elements.get("#taskMessage").textContent, /done/);

const droppedFile = { name: "drag-side-lesson.webm", size: 654321, type: "" };
await elements.get("#localDrop").listeners.drop({
  preventDefault() {},
  dataTransfer: { files: [droppedFile] }
});
await new Promise(resolve => setTimeout(resolve, 0));

assert.equal(uploadBodies.length, 2);
assert.equal(elements.get("#fileInput").files[0], lessonFile);
assert.equal(uploadBodies[1].get("file"), droppedFile);
assert.equal(uploadBodies[1].get("title"), "drag-side-lesson.webm");
assert.equal(elements.get("#localDropText").textContent, "drag-side-lesson.webm");
assert.equal(elements.get("#localDrop").classList.contains("uploading"), false);
assert.equal(elements.get("#localVideoCard").dataset.localState, "ready");

uploadShouldFail = true;
elements.get("#fileInput").files = [{ name: "server-reject.mov", size: 10, type: "video/quicktime" }];
await context.uploadLocal();

assert.equal(uploadBodies.length, 3);
assert.equal(uploadBodies[2].get("title"), "server-reject.mov");
assert.equal(elements.get("#localDropText").textContent, "unsupported local file");
assert.equal(elements.get("#uploadButton").disabled, false);
assert.equal(elements.get("#localDrop").classList.contains("uploading"), false);
assert.equal(elements.get("#localVideoCard").classList.contains("state-error"), true);
assert.equal(elements.get("#taskMessage").textContent, "unsupported local file");

elements.get("#fileInput").files = [{ name: "bad.txt", size: 10, type: "text/plain" }];
await context.uploadLocal(elements.get("#fileInput").files[0]);

assert.equal(uploadBodies.length, 3);
assert.match(elements.get("#localDropText").textContent, /mp4 \/ m4v \/ mov/);
assert.equal(elements.get("#uploadButton").disabled, false);
assert.equal(elements.get("#localDrop").classList.contains("uploading"), false);
assert.equal(elements.get("#localVideoCard").dataset.localState, "error");
assert.equal(elements.get("#taskMessage").textContent, "bad.txt 不是支持的视频格式。");
