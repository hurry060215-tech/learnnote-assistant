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

const context = {
  console,
  Date,
  URL,
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
    cookies: { getAll() {} }
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
