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
  querySelectorAll() { return []; }
};

let currentPage = {
  title: "Plain page",
  page_url: "https://example.com/article",
  page_text: "article",
  active_video: null,
  frames: []
};
const starts = [];
const realSetTimeout = setTimeout;

const context = {
  console,
  document: documentStub,
  location: { href: "chrome-extension://learnnote/sidepanel.html" },
  navigator: { clipboard: { writeText() {} } },
  window: { open() {} },
  FormData: class FormData {},
  URL,
  fetch: async url => {
    const value = String(url);
    if (value.endsWith("/health")) return { ok: true, json: async () => ({ ffmpeg: true }) };
    if (value.endsWith("/api/tasks")) return { ok: true, json: async () => ({ tasks: [] }) };
    if (value.endsWith("/api/desktop/focus")) return { ok: true, json: async () => ({ ok: true, available: true }) };
    if (/\/api\/tasks\/task-\d+$/.test(value)) {
      const id = value.split("/").pop();
      return { ok: true, json: async () => ({ task: { id, status: "success", phase: "completed", progress: 100, message: "done", source_type: "current_page" } }) };
    }
    if (/\/api\/tasks\/task-\d+\/(note|transcript)$/.test(value)) {
      return { ok: true, json: async () => ({ segments: [] }), text: async () => "# Done" };
    }
    throw new Error(`unexpected fetch: ${url}`);
  },
  chrome: {
    storage: { local: { async get(defaults) { return defaults; }, async set() {} } },
    runtime: {
      async sendMessage(message) {
        if (message.type === "get-current-context") return { tab: { id: 12, url: currentPage.page_url }, page: currentPage, resources: [] };
        if (message.type === "start-current-task") {
          starts.push(message);
          return { task_id: `task-${starts.length}` };
        }
        throw new Error(`unexpected message: ${message.type}`);
      }
    },
    tabs: { create() { throw new Error("desktop focus should handle the handoff"); } }
  },
  setTimeout(callback) { return realSetTimeout(callback, 0); },
  clearTimeout
};
context.window = { ...context.window, location: context.location };

vm.createContext(context);
const code = await readFile(new URL("../sidepanel.js", import.meta.url), "utf8");
vm.runInContext(code, context);
await new Promise(resolve => realSetTimeout(resolve, 0));

for (const pageUrl of [
  "https://www.bilibili.com/video/BV181wezqEgK",
  "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "https://mooc1.chaoxing.com/mycourse/studentstudy?chapterId=42"
]) {
  currentPage = { ...currentPage, title: "Video lesson", page_url: pageUrl };
  await context.startTask("video");
}

assert.equal(starts.length, 3);
assert.deepEqual(starts.map(item => item.page.page_url), [
  "https://www.bilibili.com/video/BV181wezqEgK",
  "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "https://mooc1.chaoxing.com/mycourse/studentstudy?chapterId=42"
]);

currentPage = { ...currentPage, title: "Plain page", page_url: "https://example.com/article" };
await context.startTask("video");

assert.equal(starts.length, 3, "plain pages without media evidence must not create video tasks");
assert.match(elements.get("#taskMessage").textContent, /还没有读取到正在播放的视频|本地视频上传|页面文本总结/);
assert.equal(elements.get("#summarizeButton").disabled, false);
