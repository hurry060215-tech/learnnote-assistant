import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

function selectorMatches(element, selector) {
  const item = selector.trim();
  if (item === "*") return true;
  const attrMatch = item.match(/^([a-z0-9-]+)\[([a-z0-9-]+)\]$/i);
  if (attrMatch) {
    return element.tagName.toLowerCase() === attrMatch[1].toLowerCase() && Boolean(element[attrMatch[2]]);
  }
  if (item.startsWith(".")) {
    return (element.className || "").split(/\s+/).includes(item.slice(1));
  }
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
    this.src = options.src || "";
    this.currentSrc = options.currentSrc || "";
    this.type = options.type || "";
    this.kind = options.kind || "";
    this.srclang = options.srclang || "";
    this.label = options.label || "";
    this.currentTime = options.currentTime || 0;
    this.duration = options.duration || 0;
    this.paused = options.paused ?? true;
    this.ended = options.ended ?? false;
    this.readyState = options.readyState || 0;
    this.videoWidth = options.videoWidth || 0;
    this.videoHeight = options.videoHeight || 0;
    this.clientWidth = options.clientWidth || 0;
    this.clientHeight = options.clientHeight || 0;
    this.textTracks = options.textTracks || [];
    this.shadowRoot = null;
    this.listeners = [];
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

  addEventListener(name) {
    this.listeners.push(name);
  }
}

class FakeRoot {
  constructor(children = [], textContent = "") {
    this.nodeType = 11;
    this.children = children;
    this.textContent = textContent;
  }

  querySelectorAll(selector) {
    return collectDescendants(this, selector);
  }
}

const hiddenTrack = {
  mode: "disabled",
  get cues() {
    return this.mode === "hidden" ? [
      { startTime: 0, endTime: 2.5, text: "Welcome to the lesson" },
      { startTime: 2.5, endTime: 5, text: "Shadow DOM caption cue" }
    ] : [];
  },
  get activeCues() {
    return [];
  }
};

const video = new FakeElement("video", {
  currentSrc: "https://cdn.example.com/api/current?id=shadow&token=1",
  currentTime: 42,
  duration: 600,
  paused: false,
  readyState: 4,
  videoWidth: 1280,
  videoHeight: 720,
  textTracks: [
    hiddenTrack
  ]
}, [
  new FakeElement("source", {
    src: "https://cdn.example.com/shadow/playlist.m3u8?token=1",
    type: "application/vnd.apple.mpegurl"
  }),
  new FakeElement("track", {
    src: "https://cdn.example.com/shadow/captions.vtt",
    kind: "subtitles",
    srclang: "zh",
    label: "Chinese"
  })
]);

const title = new FakeElement("h1", { textContent: "Shadow lesson title" });
const iframe = new FakeElement("iframe", { src: "https://course.example.com/player?video=shadow" });
const overlayCaption = new FakeElement("div", {
  className: "xgplayer-subtitle captions-layer",
  textContent: "Visible overlay caption"
});
const shadowRoot = new FakeRoot([title, video, iframe, overlayCaption], "Shadow lesson title\nChapter 3 notes");
const host = new FakeElement("learn-player");
host.shadowRoot = shadowRoot;
const html = new FakeElement("html", {}, [host]);

let messageListener = null;
const observedRoots = [];
const context = {
  console,
  URL,
  Node: { ELEMENT_NODE: 1 },
  location: { href: "https://course.example.com/lesson" },
  document: {
    title: "Course page",
    readyState: "complete",
    documentElement: html,
    body: { innerText: "Visible page text" },
    querySelectorAll(selector) {
      return collectDescendants({ children: [html] }, selector);
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
    constructor(callback) {
      this.callback = callback;
    }

    observe(root) {
      observedRoots.push(root);
    }
  },
  performance: {
    getEntriesByType() {
      return [
        {
          name: "https://cdn.example.com/api/play?id=shadow",
          initiatorType: "video",
          encodedBodySize: 7340032,
          transferSize: 7341200
        }
      ];
    }
  },
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

let response = null;
messageListener({ type: "collect-page-data" }, {}, data => {
  response = data;
});

const urls = new Set(response.resources.map(item => item.url));

assert.equal(response.active_video.src, "https://cdn.example.com/api/current?id=shadow&token=1");
assert.equal(response.active_video.paused, false);
assert.equal(hiddenTrack.mode, "hidden");
assert.deepEqual(JSON.parse(JSON.stringify(response.browser_subtitles)), [
  { start: 0, end: 2.5, text: "Welcome to the lesson" },
  { start: 2.5, end: 5, text: "Shadow DOM caption cue" },
  { start: 40.5, end: 46.5, text: "Visible overlay caption" }
]);
assert.ok(urls.has("https://cdn.example.com/api/current?id=shadow&token=1"));
assert.ok(urls.has("https://cdn.example.com/shadow/playlist.m3u8?token=1"));
assert.ok(urls.has("https://cdn.example.com/shadow/captions.vtt"));
assert.ok(urls.has("https://course.example.com/player?video=shadow"));
const activeVideoResource = response.resources.find(item => item.url === "https://cdn.example.com/api/current?id=shadow&token=1");
assert.equal(activeVideoResource.kind, "video");
assert.equal(activeVideoResource.mime, "video/mp4");
assert.equal(activeVideoResource.source, "activeVideo");
const extensionless = response.resources.find(item => item.url === "https://cdn.example.com/api/play?id=shadow");
assert.equal(extensionless.kind, "video");
assert.equal(extensionless.source, "performance");
assert.equal(extensionless.request_type, "video");
assert.equal(extensionless.content_length, 7340032);
assert.match(response.page_text, /Shadow lesson title/);
assert.ok(observedRoots.includes(shadowRoot), "expected open shadow roots to be observed for later media mutations");
