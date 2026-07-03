import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const performanceEntries = Array.from({ length: 70 }, (_, index) => ({
  name: `https://cdn.example.com/noise/master-${index}.m3u8`,
  initiatorType: "fetch",
  encodedBodySize: 2048,
  transferSize: 4096
}));

let messageListener = null;
const context = {
  console,
  URL,
  Node: { ELEMENT_NODE: 1 },
  location: { href: "https://course.example.com/lesson" },
  document: {
    title: "Priority lesson",
    readyState: "complete",
    documentElement: {
      querySelectorAll() {
        return [];
      }
    },
    body: { innerText: "" },
    querySelectorAll() {
      return [];
    },
    addEventListener() {}
  },
  window: null,
  chrome: {
    runtime: {
      onMessage: {
        addListener(listener) {
          messageListener = listener;
        }
      },
      sendMessage() {
        return Promise.resolve();
      }
    }
  },
  MutationObserver: class {
    observe() {}
  },
  performance: {
    getEntriesByType(type) {
      return type === "resource" ? performanceEntries : [];
    }
  },
  atob: value => Buffer.from(value, "base64").toString("binary"),
  setTimeout() {
    return 0;
  },
  clearTimeout() {},
  setInterval() {
    return 0;
  }
};

context.window = context;
context.window.addEventListener = () => {};
context.window.postMessage = () => {};

vm.createContext(context);
const contentCode = await readFile(new URL("../content.js", import.meta.url), "utf8");
vm.runInContext(contentCode, context);

context.rememberHookResource({
  url: "https://cdn.example.com/current/video/init-0001.m4s",
  source: "pageHookMediaSource",
  kind: "fragment",
  label: "current MSE fragment",
  score: 20,
  is_main_video: true,
  playback_match: "blob-source",
  blob_url: "blob:https://course.example.com/current"
});

let response = null;
messageListener({ type: "collect-page-data" }, {}, data => {
  response = data;
});

assert.equal(response.resources.length, 60);
assert.equal(response.resources[0].url, "https://cdn.example.com/current/video/init-0001.m4s");
assert.equal(response.resources[0].playback_match, "blob-source");
assert.equal(response.resources[0].is_main_video, true);
assert.ok(
  response.resources.some(item => item.url === "https://cdn.example.com/current/video/init-0001.m4s"),
  "expected current playback match to survive the 60-resource truncation"
);
