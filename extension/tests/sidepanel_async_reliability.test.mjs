import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const sidepanelCode = await readFile(new URL("../sidepanel.js", import.meta.url), "utf8");

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function makeElement() {
  const attributes = new Map();
  return {
    addEventListener() {},
    classList: { add() {}, remove() {}, toggle() {} },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    style: {},
    dataset: {},
    value: "",
    textContent: "",
    innerHTML: "",
    disabled: false,
    hidden: false,
    onclick: null,
    onchange: null,
    files: [],
    setAttribute(name, value) { attributes.set(name, String(value)); },
    removeAttribute(name) { attributes.delete(name); },
    getAttribute(name) { return attributes.get(name) ?? null; }
  };
}

function makePanel({ fetchImpl, sendMessage, createTab, setTimeoutImpl = setTimeout }) {
  const elements = new Map();
  let onMessage = null;
  const document = {
    body: { dataset: {} },
    querySelector(selector) {
      if (!elements.has(selector)) elements.set(selector, makeElement());
      return elements.get(selector);
    },
    querySelectorAll() { return []; }
  };
  const context = {
    console,
    document,
    location: { href: "chrome-extension://learnnote/sidepanel.html" },
    navigator: { clipboard: { async writeText() {} } },
    window: { open() { return null; } },
    FormData: class FormData {},
    URL,
    fetch: fetchImpl,
    chrome: {
      storage: {
        local: {
          async get(defaults) { return defaults; },
          async set() {}
        }
      },
      runtime: {
        getManifest() { return { version: "test" }; },
        onMessage: { addListener(listener) { onMessage = listener; } },
        sendMessage
      },
      tabs: { create: createTab || (async () => ({ id: 1 })) }
    },
    setTimeout: setTimeoutImpl,
    clearTimeout
  };
  context.window = { ...context.window, location: context.location };
  vm.createContext(context);
  vm.runInContext(sidepanelCode, context);
  return { context, elements, getOnMessage: () => onMessage };
}

function baseFetch(extra = null) {
  return async (url, options) => {
    if (extra) {
      const result = await extra(String(url), options);
      if (result) return result;
    }
    const value = String(url);
    if (value.endsWith("/health")) return { ok: true, json: async () => ({ ffmpeg: true }) };
    if (value.endsWith("/api/extension/heartbeat")) return { ok: true, json: async () => ({ ok: true }) };
    if (value.endsWith("/api/tasks")) return { ok: true, json: async () => ({ tasks: [] }) };
    if (value.endsWith("/api/preferences")) return { ok: true, json: async () => ({}) };
    if (value.endsWith("/api/desktop/focus")) return { ok: true, json: async () => ({ ok: true, available: false }) };
    throw new Error(`unexpected fetch: ${url}`);
  };
}

const firstPreflight = deferred();
const startResponse = deferred();
let preflightMode = "deferred";
let startCalls = 0;
const page = {
  title: "Lesson A",
  page_url: "https://course.example.com/lesson-a",
  playback_session_id: "session-a",
  page_text: "lesson text",
  active_video: { src: "https://cdn.example.com/a.mp4", current_time: 10, duration: 90, paused: false },
  frames: []
};
const resources = [{
  url: "https://cdn.example.com/a.mp4",
  kind: "video",
  source: "webRequest",
  request_type: "media",
  score: 99
}];

const stalePanel = makePanel({
  fetchImpl: baseFetch(),
  async sendMessage(message) {
    if (message.type === "get-current-context") return { tab: { id: 7, url: page.page_url }, page, resources };
    if (message.type === "preflight-current-page") {
      if (preflightMode === "deferred") return firstPreflight.promise;
      return {
        report: {
          ok: true,
          ready: true,
          selected_url: resources[0].url,
          candidate_count: 1,
          probed_count: 1,
          downloadable_count: 1,
          candidates: [{ resource: resources[0], preflight: { ok: true, downloadable: true } }]
        }
      };
    }
    if (message.type === "start-current-task") {
      startCalls += 1;
      return startResponse.promise;
    }
    throw new Error(`unexpected message: ${message.type}`);
  }
});

await new Promise(resolve => setTimeout(resolve, 0));
const stalePreflightRun = stalePanel.context.runPreflight();
await new Promise(resolve => setTimeout(resolve, 0));
stalePanel.getOnMessage()({ type: "current-context-updated", tabId: 7, reason: "tab-activated" });
firstPreflight.resolve({
  report: {
    ok: true,
    ready: true,
    selected_url: resources[0].url,
    candidate_count: 1,
    probed_count: 1,
    downloadable_count: 1,
    candidates: [{ resource: resources[0], preflight: { ok: true, downloadable: true } }]
  }
});
assert.equal(await stalePreflightRun, null);
assert.match(stalePanel.elements.get("#taskMessage").textContent, /已丢弃旧的预检结果/);
assert.equal(stalePanel.elements.get("#preflightButton").disabled, false);
assert.equal(vm.runInContext("preflightResultsByUrl.size", stalePanel.context), 0);

preflightMode = "ready";
const staleStartRun = stalePanel.context.startTask("video");
while (!startCalls) await new Promise(resolve => setTimeout(resolve, 0));
stalePanel.getOnMessage()({ type: "current-context-updated", tabId: 9, reason: "tab-activated" });
startResponse.resolve({ task_id: "old-context-task" });
await staleStartRun;
assert.notEqual(vm.runInContext("currentTaskId", stalePanel.context), "old-context-task");
assert.match(stalePanel.elements.get("#taskMessage").textContent, /已丢弃旧的任务启动结果/);
assert.equal(stalePanel.elements.get("#summarizeButton").disabled, false);

const never = deferred();
const neverStart = deferred();
let timeoutMode = "preflight";
const timeoutPanel = makePanel({
  fetchImpl: baseFetch(),
  setTimeoutImpl(fn, delay) {
    if (delay >= 15000) {
      queueMicrotask(fn);
      return 99;
    }
    return setTimeout(fn, delay);
  },
  async sendMessage(message) {
    if (message.type === "get-current-context") return { tab: { id: 7, url: page.page_url }, page, resources };
    if (message.type === "preflight-current-page") {
      if (timeoutMode === "preflight") return never.promise;
      return {
        report: {
          ok: true,
          ready: true,
          selected_url: resources[0].url,
          candidate_count: 1,
          probed_count: 1,
          downloadable_count: 1,
          candidates: [{ resource: resources[0], preflight: { ok: true, downloadable: true } }]
        }
      };
    }
    if (message.type === "start-current-task") return neverStart.promise;
    throw new Error(`unexpected message: ${message.type}`);
  }
});
await new Promise(resolve => setTimeout(resolve, 0));
assert.equal(await timeoutPanel.context.runPreflight(), null);
assert.match(timeoutPanel.elements.get("#taskMessage").textContent, /页面预检超时/);
assert.equal(timeoutPanel.elements.get("#preflightButton").disabled, false);
assert.equal(timeoutPanel.elements.get("#summarizeButton").disabled, false);
timeoutMode = "start";
await timeoutPanel.context.startTask("video");
assert.match(timeoutPanel.elements.get("#taskMessage").textContent, /任务启动超时/);
assert.equal(timeoutPanel.elements.get("#summarizeButton").disabled, false);
assert.equal(timeoutPanel.elements.get("#downloadOnlyButton").disabled, false);

const retryTimers = [];
let taskFetches = 0;
const pollPanel = makePanel({
  fetchImpl: baseFetch(async value => {
    if (!value.endsWith("/api/tasks/task-retry")) return null;
    taskFetches += 1;
    if (taskFetches === 1) return { ok: true, json: async () => { throw new SyntaxError("bad json"); } };
    return {
      ok: true,
      json: async () => ({ task: { id: "task-retry", status: "running", phase: "transcribing", progress: 35, message: "正在转写" } })
    };
  }),
  setTimeoutImpl(fn, delay) {
    if (delay >= 2500) {
      retryTimers.push({ fn, delay });
      return retryTimers.length;
    }
    return setTimeout(fn, delay);
  },
  async sendMessage(message) {
    if (message.type === "get-current-context") return { tab: { id: 7, url: page.page_url }, page, resources };
    throw new Error(`unexpected message: ${message.type}`);
  }
});
await new Promise(resolve => setTimeout(resolve, 0));
vm.runInContext('currentTaskId = "task-retry"', pollPanel.context);
await pollPanel.context.pollTask();
assert.match(pollPanel.elements.get("#taskMessage").textContent, /暂时断开/);
assert.equal(retryTimers[0].delay, 2500);
await retryTimers.shift().fn();
assert.equal(taskFetches, 2);
assert.match(pollPanel.elements.get("#taskMessage").textContent, /正在转写/);

let allowTabCreate = false;
const handoffPanel = makePanel({
  fetchImpl: baseFetch(),
  async sendMessage(message) {
    if (message.type === "get-current-context") return { tab: { id: 7, url: page.page_url }, page, resources };
    throw new Error(`unexpected message: ${message.type}`);
  },
  async createTab() {
    if (!allowTabCreate) throw new Error("tabs.create failed");
    return { id: 22 };
  }
});
await new Promise(resolve => setTimeout(resolve, 0));
assert.equal(await handoffPanel.context.openClientForLocalVideo(), false);
assert.match(handoffPanel.elements.get("#taskMessage").textContent, /无法唤起/);
assert.doesNotMatch(handoffPanel.elements.get("#taskMessage").textContent, /已交给客户端/);
allowTabCreate = true;
assert.equal(await handoffPanel.context.openClientForLocalVideo(), true);
assert.match(handoffPanel.elements.get("#taskMessage").textContent, /已交给客户端/);

let overlapStarts = 0;
const overlapPanel = makePanel({
  fetchImpl: baseFetch(async value => {
    if (!value.endsWith("/api/tasks/overlap-task")) return null;
    return {
      ok: true,
      json: async () => ({ task: { id: "overlap-task", status: "failed", phase: "failed", progress: 100, message: "test stop" } })
    };
  }),
  async sendMessage(message) {
    if (message.type === "get-current-context") return { tab: { id: 7, url: page.page_url }, page, resources };
    if (message.type === "preflight-current-page") {
      return {
        report: {
          ok: true,
          ready: true,
          selected_url: resources[0].url,
          candidate_count: 1,
          probed_count: 1,
          downloadable_count: 1,
          candidates: [{ resource: resources[0], preflight: { ok: true, downloadable: true } }]
        }
      };
    }
    if (message.type === "start-current-task") {
      overlapStarts += 1;
      return { task_id: "overlap-task" };
    }
    throw new Error(`unexpected message: ${message.type}`);
  }
});
await new Promise(resolve => setTimeout(resolve, 0));
vm.runInContext("isCollectingContext = true", overlapPanel.context);
await overlapPanel.context.startTask("video");
vm.runInContext("isCollectingContext = false", overlapPanel.context);
assert.equal(overlapStarts, 1, "an overlapping passive refresh must not swallow the explicit send click");
assert.equal(overlapPanel.elements.get("#handoffStatus").hidden, false);
assert.equal(overlapPanel.elements.get("#handoffStatus").dataset.state, "success");
assert.match(overlapPanel.elements.get("#handoffStatus").textContent, /客户端已接收/);
assert.equal(overlapPanel.elements.get("#handoffProgress").getAttribute("aria-valuenow"), "100");

const livePreflight = deferred();
let livePreflightCalls = 0;
let liveStarts = 0;
const livePanel = makePanel({
  fetchImpl: baseFetch(async value => {
    if (!value.endsWith("/api/tasks/live-task")) return null;
    return {
      ok: true,
      json: async () => ({ task: { id: "live-task", status: "failed", phase: "failed", progress: 100, message: "test stop" } })
    };
  }),
  async sendMessage(message) {
    if (message.type === "get-current-context") return { tab: { id: 7, url: page.page_url }, page, resources };
    if (message.type === "preflight-current-page") {
      livePreflightCalls += 1;
      return livePreflight.promise;
    }
    if (message.type === "start-current-task") {
      liveStarts += 1;
      return { task_id: "live-task" };
    }
    throw new Error(`unexpected message: ${message.type}`);
  }
});
await new Promise(resolve => setTimeout(resolve, 0));
const liveStart = livePanel.context.startTask("video");
for (let attempt = 0; attempt < 20 && !livePreflightCalls; attempt += 1) {
  await new Promise(resolve => setTimeout(resolve, 0));
}
assert.equal(livePreflightCalls, 1, "expected the current video to enter preflight");
livePanel.getOnMessage()({ type: "current-context-updated", tabId: 7, reason: "media" });
livePreflight.resolve({
  report: {
    ok: true,
    ready: true,
    selected_url: resources[0].url,
    candidate_count: 1,
    probed_count: 1,
    downloadable_count: 1,
    candidates: [{ resource: resources[0], preflight: { ok: true, downloadable: true } }]
  }
});
const liveResult = await Promise.race([
  liveStart.then(() => "done"),
  new Promise(resolve => setTimeout(() => resolve("timeout"), 1500))
]);
assert.equal(liveResult, "done", "same-video playback update should not leave the send action pending");
assert.equal(liveStarts, 1, "same-video playback updates must not cancel an in-flight preflight");
assert.doesNotMatch(livePanel.elements.get("#taskMessage").textContent, /已丢弃旧的/);
