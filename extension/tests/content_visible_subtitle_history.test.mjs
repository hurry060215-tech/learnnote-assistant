import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

function selectorMatches(element, selector) {
  const item = selector.trim();
  if (item === "*") return true;
  return element.tagName.toLowerCase() === item.toLowerCase();
}

function collectDescendants(root, selector) {
  const selectors = selector.split(",");
  const results = [];

  function visit(node) {
    for (const child of node.children || []) {
      if (selectors.some(item => selectorMatches(child, item))) results.push(child);
      visit(child);
    }
  }

  visit(root);
  return results;
}

class FakeElement {
  constructor(tagName, options = {}, children = []) {
    this.tagName = tagName.toUpperCase();
    this.nodeType = 1;
    this.children = children;
    this.className = options.className || "";
    this.id = options.id || "";
    this.textContent = options.textContent || "";
    this.currentSrc = options.currentSrc || "";
    this.currentTime = options.currentTime || 0;
    this.duration = options.duration || 0;
    this.paused = options.paused ?? true;
    this.ended = options.ended ?? false;
    this.readyState = options.readyState || 0;
    this.videoWidth = options.videoWidth || 0;
    this.videoHeight = options.videoHeight || 0;
    this.textTracks = options.textTracks || [];
    this.shadowRoot = null;
  }

  getAttribute(name) {
    return this[name] || "";
  }

  querySelectorAll(selector) {
    return collectDescendants(this, selector);
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }

  matches(selector) {
    return selector.split(",").some(item => selectorMatches(this, item));
  }

  addEventListener() {}
}

const video = new FakeElement("video", {
  currentSrc: "https://cdn.example.com/dom-subtitle/lesson.mp4",
  currentTime: 12,
  duration: 120,
  paused: false,
  readyState: 4,
  videoWidth: 1280,
  videoHeight: 720,
});
const overlay = new FakeElement("div", {
  className: "player-subtitle caption-layer",
  textContent: "first visible caption",
});
const html = new FakeElement("html", {}, [video, overlay]);

let messageListener = null;
const context = {
  console,
  URL,
  Node: { ELEMENT_NODE: 1 },
  location: { href: "https://course.example.com/dom-subtitle" },
  document: {
    title: "DOM subtitle lesson",
    readyState: "complete",
    documentElement: html,
    body: { innerText: "Course body" },
    querySelectorAll(selector) {
      return collectDescendants({ children: [html] }, selector);
    },
    addEventListener() {},
  },
  window: null,
  chrome: {
    runtime: {
      onMessage: {
        addListener(listener) {
          messageListener = listener;
        },
      },
      sendMessage() {
        return Promise.resolve();
      },
    },
  },
  MutationObserver: class {
    observe() {}
  },
  performance: {
    getEntriesByType() {
      return [];
    },
  },
  setTimeout() {
    return 0;
  },
  clearTimeout() {},
  setInterval() {
    return 0;
  },
};

context.window = context;
context.window.addEventListener = () => {};
context.window.postMessage = () => {};

vm.createContext(context);
const contentCode = await readFile(new URL("../content.js", import.meta.url), "utf8");
vm.runInContext(contentCode, context);

let first = null;
messageListener({ type: "collect-page-data" }, {}, data => {
  first = data;
});

video.currentTime = 18;
overlay.textContent = "second visible caption";

let second = null;
messageListener({ type: "collect-page-data" }, {}, data => {
  second = data;
});

assert.deepEqual(JSON.parse(JSON.stringify(first.browser_subtitles)), [
  { start: 10.5, end: 16.5, text: "first visible caption" },
]);
assert.deepEqual(JSON.parse(JSON.stringify(second.browser_subtitles)), [
  { start: 10.5, end: 16.5, text: "first visible caption" },
  { start: 16.5, end: 22.5, text: "second visible caption" },
]);
