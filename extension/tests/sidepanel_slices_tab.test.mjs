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

const makeElement = (dataset = {}) => ({
  addEventListener() {},
  classList: makeClassList(),
  querySelector() { return null; },
  style: {},
  dataset,
  value: "",
  textContent: "",
  innerHTML: "",
  scrollTop: 0,
  disabled: false,
  onclick: null,
  onchange: null,
  files: []
});

const resultTabs = ["note", "transcript", "slices", "frames", "diagnostics"]
  .map(tab => makeElement({ tab }));

const documentStub = {
  querySelector(selector) {
    if (!elements.has(selector)) elements.set(selector, makeElement());
    return elements.get(selector);
  },
  querySelectorAll(selector) {
    if (selector === ".result-tab") return resultTabs;
    return [];
  }
};

const context = {
  console,
  document: documentStub,
  location: { href: "file:///sidepanel.html" },
  navigator: { clipboard: { writeText() {} } },
  window: { open() {} },
  FormData: class FormData {},
  fetch: async url => {
    const value = String(url);
    if (value.endsWith("/health")) {
      return { json: async () => ({ ffmpeg: true, vision_model_configured: true }) };
    }
    if (value.endsWith("/api/tasks")) {
      return { json: async () => ({ tasks: [] }) };
    }
    throw new Error(`unexpected fetch: ${url}`);
  },
  setTimeout,
  clearTimeout
};
context.window = { ...context.window, location: context.location };

vm.createContext(context);
const sidepanelCode = await readFile(new URL("../sidepanel.js", import.meta.url), "utf8");
vm.runInContext(sidepanelCode, context);
await new Promise(resolve => setTimeout(resolve, 0));

vm.runInContext(`
currentTaskId = "slice-task";
currentTask = {
  id: "slice-task",
  title: "Slice Review Lesson",
  media_path: "D:/Projects/learnnote-assistant/data/tasks/slice-task/media.mp4",
  transcript_path: "D:/Projects/learnnote-assistant/data/tasks/slice-task/transcript.json",
  summary_source: "vision-llm",
  options: { grid_columns: 3, grid_rows: 3 },
  summary_diagnostics: { used_vision_llm: true, frame_grid_count: 1, vision_grid_count: 1 },
  visual_windows: [{
    id: "W001",
    start: 12,
    end: 48,
    frame_count: 9,
    frame_timestamps: [12, 24, 36],
    grid_url: "http://127.0.0.1:8765/api/tasks/slice-task/grids/grid_000.jpg",
    transcript_excerpt: "Introduce the theorem and compare the two diagrams."
  }]
};
transcriptCache = {
  segments: [
    { start: 15, end: 20, text: "The first diagram gives the theorem setup." },
    { start: 75, end: 80, text: "Outside the slice window." }
  ]
};
selectedTab = "note";
`, context);

elements.get("#result").scrollTop = 88;
resultTabs.find(tab => tab.dataset.tab === "slices").onclick();

const resultHtml = elements.get("#result").innerHTML;
assert.equal(elements.get("#result").scrollTop, 0);
assert.equal(context.workbenchUrl("slice-task", "slices"), "http://127.0.0.1:8765/?task=slice-task&tab=slices");
assert.equal(resultTabs.find(tab => tab.dataset.tab === "slices").classList.contains("active"), true);
assert.match(resultHtml, /class="side-visual-study"/);
assert.match(resultHtml, /class="side-visual-study-card"/);
assert.match(resultHtml, /W001/);
assert.match(resultHtml, /00:00:12 - 00:00:48/);
assert.match(resultHtml, /grid_000\.jpg/);
assert.match(resultHtml, /The first diagram gives the theorem setup\./);
assert.doesNotMatch(resultHtml, /Outside the slice window/);
assert.match(resultHtml, /data-media-seek-time="12\.000"/);
assert.match(resultHtml, /data-switch-result-tab="transcript"/);
assert.match(resultHtml, /data-switch-result-tab="note"/);
