import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

function listener(name = "") {
  return {
    addListener(callback) {
      if (name) listeners[name] = callback;
    }
  };
}

const listeners = {};
const queriedTabs = [];
const fetchedTabs = [];
const messagedTabs = [];
let capturedPreflightBody = null;

const context = {
  console,
  Date,
  URL,
  fetch: async (url, options = {}) => {
    if (String(url).endsWith("/api/media/preflight-current-page")) {
      capturedPreflightBody = JSON.parse(String(options.body || "{}"));
      return { json: async () => ({ report: { ok: true, ready: true } }) };
    }
    throw new Error(`unexpected fetch: ${url}`);
  },
  setTimeout(fn) {
    fn();
    return 1;
  },
  clearTimeout() {},
  chrome: {
    webRequest: {
      onBeforeSendHeaders: listener(),
      onHeadersReceived: listener(),
      onBeforeRedirect: listener(),
      onCompleted: listener(),
      onErrorOccurred: listener()
    },
    tabs: {
      onRemoved: listener(),
      onActivated: listener(),
      onUpdated: listener(),
      async query(query) {
        queriedTabs.push(query);
        return [{ id: 22, title: "Active tab", url: "https://active.example.com/lesson" }];
      },
      async get(tabId) {
        fetchedTabs.push(tabId);
        return { id: tabId, title: `Pinned tab ${tabId}`, url: `https://course.example.com/lesson-${tabId}` };
      },
      async sendMessage(tabId) {
        messagedTabs.push(tabId);
        return {
          title: `Course ${tabId}`,
          page_url: `https://course.example.com/lesson-${tabId}`,
          page_text: "lesson text",
          active_video: null,
          browser_subtitles: [],
          drm_detected: false,
          drm_signals: [],
          resources: [{
            url: `https://cdn.example.com/lesson-${tabId}.mp4`,
            source: "dom",
            kind: "video",
            score: 90
          }]
        };
      }
    },
    action: { onClicked: listener() },
    runtime: {
      sendMessage() {},
      onMessage: listener("runtimeMessage")
    },
    webNavigation: {
      getAllFrames(_details, callback) {
        callback([{ frameId: 0 }]);
      }
    },
    sidePanel: { open() {} },
    scripting: { executeScript() {} },
    cookies: { async getAll() { return []; } }
  }
};

vm.createContext(context);
const backgroundCode = await readFile(new URL("../background.js", import.meta.url), "utf8");
vm.runInContext(backgroundCode, context);

assert.equal(typeof listeners.runtimeMessage, "function");

const response = await new Promise(resolve => {
  const keepAlive = listeners.runtimeMessage(
    { type: "get-current-context", targetTabId: 11 },
    {},
    resolve
  );
  assert.equal(keepAlive, true);
});

assert.deepEqual(fetchedTabs, [11]);
assert.deepEqual(messagedTabs, [11]);
assert.deepEqual(queriedTabs, []);
assert.equal(response.tab.id, 11);
assert.equal(response.page.page_url, "https://course.example.com/lesson-11");
assert.equal(response.resources[0].url, "https://cdn.example.com/lesson-11.mp4");

const activeVideo = { src: "https://cdn.example.com/current.mp4", current_time: 33, duration: 600, paused: false };
const preflightResponse = await new Promise(resolve => {
  const keepAlive = listeners.runtimeMessage(
    {
      type: "preflight-current-page",
      targetTabId: 11,
      backendUrl: "http://127.0.0.1:8765",
      probeLimit: 2,
      page: {
        title: "Course 11",
        page_url: "https://course.example.com/lesson-11",
        active_video: activeVideo,
        drm_detected: false,
        frames: []
      },
      resources: [{
        url: "https://cdn.example.com/current.mp4",
        source: "webRequest",
        kind: "video",
        score: 80
      }]
    },
    {},
    resolve
  );
  assert.equal(keepAlive, true);
});

assert.deepEqual(preflightResponse, { report: { ok: true, ready: true } });
assert.equal(capturedPreflightBody.page_url, "https://course.example.com/lesson-11");
assert.deepEqual(capturedPreflightBody.active_video, activeVideo);
assert.equal(capturedPreflightBody.resources[0].url, "https://cdn.example.com/current.mp4");
assert.equal(capturedPreflightBody.probe_limit, 2);
