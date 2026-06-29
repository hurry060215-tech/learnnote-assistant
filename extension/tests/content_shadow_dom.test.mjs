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
  listeners: [],
  get cues() {
    return this.mode === "hidden" ? [
      { startTime: 0, endTime: 2.5, text: "Welcome to the lesson" },
      { startTime: 2.5, endTime: 5, text: "Shadow DOM caption cue" }
    ] : [];
  },
  get activeCues() {
    return [];
  },
  addEventListener(name) {
    this.listeners.push(name);
  }
};

const textTrackList = [hiddenTrack];
textTrackList.listeners = [];
textTrackList.addEventListener = function addEventListener(name) {
  this.listeners.push(name);
};

const video = new FakeElement("video", {
  currentSrc: "https://cdn.example.com/api/current?id=shadow&token=1",
  currentTime: 42,
  duration: 600,
  paused: false,
  readyState: 4,
  videoWidth: 1280,
  videoHeight: 720,
  textTracks: textTrackList
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
let windowMessageListener = null;
const observedRoots = [];
const observeOptions = [];
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

    observe(root, options) {
      observedRoots.push(root);
      observeOptions.push(options);
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
context.window.addEventListener = (name, listener) => {
  if (name === "message") {
    windowMessageListener = listener;
    context.__learnNoteWindowMessageListener = listener;
  }
};
context.window.postMessage = () => {};

vm.createContext(context);
const contentCode = await readFile(new URL("../content.js", import.meta.url), "utf8");
vm.runInContext(contentCode, context);

context.__learnNoteHookEventData = {
  source: "learnnote-page-hook",
  resources: [{
    url: "https://course.example.com/api/post-play",
    source: "pageHookBody",
    kind: "hls",
    mime: "application/vnd.apple.mpegurl",
    score: 96,
    method: "POST",
    request_type: "fetch",
    request_headers: { "Content-Type": "application/x-www-form-urlencoded" },
    request_body: { type: "text", content: "lesson=shadow&token=ok" }
  }, {
    url: "https://cdn.example.com/api/play?id=shadow",
    source: "pageHookBody",
    kind: "video",
    mime: "video/mp4",
    score: 70,
    method: "POST",
    request_type: "fetch",
    request_headers: { "Content-Type": "application/json" },
    request_body: { type: "text", content: "{\"lesson\":\"shadow\"}" }
  }]
};
assert.ok(windowMessageListener, "expected content script to install page hook bridge");
vm.runInContext("__learnNoteWindowMessageListener({ source: window, data: __learnNoteHookEventData })", context);

let response = null;
messageListener({ type: "collect-page-data" }, {}, data => {
  response = data;
});

const urls = new Set(response.resources.map(item => item.url));

assert.equal(response.active_video.src, "https://cdn.example.com/api/current?id=shadow&token=1");
assert.equal(response.active_video.paused, false);
assert.equal(hiddenTrack.mode, "hidden");
assert.ok(hiddenTrack.listeners.includes("cuechange"), "expected subtitle cue changes to trigger page context refreshes");
assert.ok(textTrackList.listeners.includes("addtrack"), "expected newly loaded subtitle tracks to be watched");
assert.ok(textTrackList.listeners.includes("change"), "expected subtitle track mode changes to refresh context");
assert.deepEqual(JSON.parse(JSON.stringify(response.browser_subtitles)), [
  { start: 0, end: 2.5, text: "Welcome to the lesson" },
  { start: 2.5, end: 5, text: "Shadow DOM caption cue" },
  { start: 40.5, end: 46.5, text: "Visible overlay caption" }
]);
assert.ok(urls.has("https://cdn.example.com/api/current?id=shadow&token=1"));
assert.ok(urls.has("https://cdn.example.com/shadow/playlist.m3u8?token=1"));
assert.ok(urls.has("https://cdn.example.com/shadow/captions.vtt"));
assert.ok(urls.has("https://course.example.com/player?video=shadow"));
const hookPostResource = response.resources.find(item => item.url === "https://course.example.com/api/post-play");
assert.ok(hookPostResource, `expected page hook POST resource, got ${JSON.stringify(response.resources.map(item => [item.url, item.source, item.kind, item.score]).slice(0, 12))}`);
assert.equal(hookPostResource.method, "POST");
assert.equal(hookPostResource.request_type, "fetch");
assert.equal(hookPostResource.request_headers["Content-Type"], "application/x-www-form-urlencoded");
assert.equal(hookPostResource.request_body.content, "lesson=shadow&token=ok");
const activeVideoResource = response.resources.find(item => item.url === "https://cdn.example.com/api/current?id=shadow&token=1");
assert.equal(activeVideoResource.kind, "video");
assert.equal(activeVideoResource.mime, "video/mp4");
assert.equal(activeVideoResource.source, "activeVideo");
const extensionless = response.resources.find(item => item.url === "https://cdn.example.com/api/play?id=shadow");
assert.equal(extensionless.kind, "video");
assert.equal(extensionless.source, "pageHookBody");
assert.equal(extensionless.request_type, "fetch");
assert.equal(extensionless.content_length, 7340032);
assert.equal(extensionless.method, "POST");
assert.equal(extensionless.request_headers["Content-Type"], "application/json");
assert.equal(extensionless.request_body.content, "{\"lesson\":\"shadow\"}");
assert.match(response.page_text, /Shadow lesson title/);
assert.ok(observedRoots.includes(shadowRoot), "expected open shadow roots to be observed for later media mutations");
assert.ok(observeOptions.some(options => options?.characterData), "expected subtitle DOM text changes to refresh context");
