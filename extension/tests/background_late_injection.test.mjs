import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const listeners = {};
const injections = [];
let sendAttempts = 0;

function listener(name = "") {
  return { addListener(callback) { if (name) listeners[name] = callback; } };
}

const context = {
  console,
  Date,
  URL,
  fetch: async () => { throw new Error("unexpected fetch"); },
  setTimeout(fn) { fn(); return 1; },
  clearTimeout() {},
  chrome: {
    webRequest: {
      onBeforeSendHeaders: listener(), onHeadersReceived: listener(),
      onBeforeRedirect: listener(), onCompleted: listener(), onErrorOccurred: listener()
    },
    tabs: {
      onRemoved: listener(), onActivated: listener(), onUpdated: listener(),
      async query() { return [{ id: 91, title: "Existing lesson", url: "https://course.example/lesson" }]; },
      async get(id) { return { id, title: "Existing lesson", url: "https://course.example/lesson" }; },
      async sendMessage() {
        sendAttempts += 1;
        if (sendAttempts === 1) throw new Error("Receiving end does not exist");
        return {
          title: "Existing lesson",
          page_url: "https://course.example/lesson",
          active_video: { src: "https://cdn.example/lesson.mp4", paused: false },
          resources: [{ url: "https://cdn.example/lesson.mp4", source: "dom", kind: "video", score: 100 }]
        };
      }
    },
    action: { onClicked: listener() },
    runtime: { sendMessage() {}, onMessage: listener("message") },
    webNavigation: { getAllFrames(_details, callback) { callback([{ frameId: 0 }]); } },
    sidePanel: { open() {}, setPanelBehavior() { return Promise.resolve(); } },
    scripting: {
      async executeScript(details) {
        injections.push(details);
        return [];
      }
    },
    cookies: { async getAll() { return []; } }
  }
};

vm.createContext(context);
const code = await readFile(new URL("../background.js", import.meta.url), "utf8");
vm.runInContext(code, context);

const response = await new Promise(resolve => {
  const keepAlive = listeners.message({ type: "get-current-context", targetTabId: 91 }, {}, resolve);
  assert.equal(keepAlive, true);
});

assert.equal(sendAttempts, 2);
assert.equal(injections.length, 2);
assert.deepEqual(injections.map(item => item.files?.[0]), ["page_hook.js", "content.js"]);
assert.equal(injections[0].world, "MAIN");
assert.equal(response.page.active_video.src, "https://cdn.example/lesson.mp4");
assert.equal(response.resources[0].url, "https://cdn.example/lesson.mp4");
