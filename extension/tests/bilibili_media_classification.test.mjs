import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

function listener() {
  return { addListener() {} };
}

const backgroundContext = {
  console,
  URL,
  chrome: {
    webRequest: {
      onBeforeSendHeaders: listener(),
      onHeadersReceived: listener(),
      onBeforeRedirect: listener(),
      onCompleted: listener(),
      onErrorOccurred: listener(),
    },
    tabs: { onRemoved: listener(), onUpdated: listener(), query() {} },
    action: { onClicked: listener() },
    runtime: { onMessage: listener() },
    webNavigation: { getAllFrames() {} },
    sidePanel: { open() {} },
    scripting: { executeScript() {} },
    cookies: { getAll() {} },
  },
};

vm.createContext(backgroundContext);
vm.runInContext(
  await readFile(new URL("../background.js", import.meta.url), "utf8"),
  backgroundContext,
);

const m4s = "https://xy-v6-bilivideo.com/upgcxcode/audio-track.m4s?deadline=1";
assert.equal(backgroundContext.classify(m4s, "audio/mp4"), "audio");
assert.equal(backgroundContext.classify(m4s, "video/mp4"), "video");
assert.equal(backgroundContext.classify(m4s, ""), "fragment");
assert.equal(
  backgroundContext.classify(
    "https://i2.hdslb.com/bfs/archive/example.jpg@336w_190h_1c_!web-video-rcmd-cover.avi",
    "video/mp4",
  ),
  "unknown",
);

let messageListener = null;
const contentContext = {
  console,
  URL,
  Node: { ELEMENT_NODE: 1 },
  location: { href: "https://www.bilibili.com/video/BV1xx411c7mD/" },
  document: {
    title: "Bilibili classification",
    readyState: "complete",
    documentElement: { querySelectorAll() { return []; } },
    body: { innerText: "" },
    querySelectorAll() { return []; },
    addEventListener() {},
  },
  window: null,
  chrome: {
    runtime: {
      onMessage: {
        addListener(listenerFn) {
          messageListener = listenerFn;
        },
      },
      sendMessage() {
        return Promise.resolve();
      },
    },
  },
  MutationObserver: class { observe() {} },
  performance: { getEntriesByType() { return []; }, now() { return 0; } },
  atob: value => Buffer.from(value, "base64").toString("binary"),
  setTimeout() { return 0; },
  clearTimeout() {},
  setInterval() { return 0; },
};
contentContext.window = contentContext;
contentContext.window.addEventListener = () => {};
contentContext.window.postMessage = () => {};

vm.createContext(contentContext);
vm.runInContext(
  await readFile(new URL("../content.js", import.meta.url), "utf8"),
  contentContext,
);

assert.ok(messageListener);
assert.equal(contentContext.classify(m4s, "audio/mp4"), "audio");
assert.equal(contentContext.classify(m4s, "video/mp4"), "video");
assert.equal(contentContext.looksLikeMediaValue("audio/mp4", "script"), false);
assert.equal(
  contentContext.classify("https://s1.hdslb.com/bfs/static/jinkela/video/video.07dc20e5.js", "video/mp4"),
  "unknown",
);
