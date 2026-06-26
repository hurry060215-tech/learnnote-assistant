import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

function listener() {
  return { addListener() {} };
}

const messages = [];
const context = {
  console,
  URL,
  Date,
  setTimeout(fn) {
    fn();
    return 1;
  },
  clearTimeout() {},
  chrome: {
    webRequest: {
      onBeforeSendHeaders: listener(),
      onHeadersReceived: listener(),
      onCompleted: listener(),
      onErrorOccurred: listener()
    },
    tabs: {
      onRemoved: listener(),
      onUpdated: listener(),
      query() {}
    },
    action: { onClicked: listener() },
    runtime: {
      sendMessage(message) {
        messages.push(message);
      },
      onMessage: listener()
    },
    webNavigation: { getAllFrames() {} },
    sidePanel: { open() {} },
    scripting: { executeScript() {} },
    cookies: { getAll() {} }
  }
};

vm.createContext(context);
const backgroundCode = await readFile(new URL("../background.js", import.meta.url), "utf8");
vm.runInContext(backgroundCode, context);

context.addResource(42, {
  url: "https://cdn.example.com/lesson.mp4",
  source: "webRequest",
  kind: "video",
  mime: "video/mp4",
  score: 95
});

assert.equal(messages.length, 1);
assert.equal(messages[0].type, "current-context-updated");
assert.equal(messages[0].tabId, 42);
assert.equal(messages[0].reason, "media");

messages.length = 0;
context.addResource(42, {
  url: "https://cdn.example.com/silent.mp4",
  source: "dom",
  kind: "video",
  mime: "video/mp4",
  score: 90
}, false);

assert.equal(messages.length, 0);
