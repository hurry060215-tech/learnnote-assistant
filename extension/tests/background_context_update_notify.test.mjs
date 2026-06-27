import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const listeners = {};
function listener(name = "") {
  return {
    addListener(callback) {
      if (name) listeners[name] = callback;
    }
  };
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
      onRemoved: listener("tabRemoved"),
      onActivated: listener("tabActivated"),
      onUpdated: listener("tabUpdated"),
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

listeners.tabActivated({ tabId: 77 });
assert.equal(messages.length, 1);
assert.equal(messages[0].tabId, 77);
assert.equal(messages[0].reason, "tab-activated");

messages.length = 0;
listeners.tabUpdated(77, { status: "loading" });
assert.equal(messages.length, 1);
assert.equal(messages[0].tabId, 77);
assert.equal(messages[0].reason, "navigation");

messages.length = 0;
listeners.tabUpdated(77, { status: "complete" });
assert.equal(messages.length, 0);

const merged = context.mergePageContexts({ title: "Top", url: "https://course.example.com" }, [
  context.normalizePageForFrame({
    title: "Top",
    page_url: "https://course.example.com",
    browser_subtitles: [
      { start: 3, end: 5, text: " second cue " },
      { start: 0, end: 2, text: "first cue" }
    ]
  }, 0, {}),
  context.normalizePageForFrame({
    title: "Player",
    page_url: "https://player.example.com",
    browser_subtitles: [
      { start: 0, end: 2, text: "first cue" },
      { start: 6, end: 8, text: "iframe cue" }
    ]
  }, 2, {})
]);

assert.deepEqual(JSON.parse(JSON.stringify(merged.browser_subtitles)), [
  { start: 0, end: 2, text: "first cue" },
  { start: 3, end: 5, text: "second cue" },
  { start: 6, end: 8, text: "iframe cue" }
]);
