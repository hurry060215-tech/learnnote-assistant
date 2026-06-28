import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const messages = [];

class Element {
  constructor(tagName = "") {
    this.tagName = tagName;
    this.attributes = new Map();
    this.parentElement = null;
  }

  setAttribute(name, value) {
    this.attributes.set(String(name).toLowerCase(), String(value));
    return undefined;
  }

  getAttribute(name) {
    return this.attributes.get(String(name).toLowerCase()) || "";
  }
}

class HTMLMediaElement extends Element {
  constructor(tagName) {
    super(tagName);
    this.children = [];
    this._src = "";
    this._currentSrc = "";
  }

  get src() {
    return this._src;
  }

  set src(value) {
    this._src = String(value);
  }

  get currentSrc() {
    return this._currentSrc || this._src;
  }

  set currentSrc(value) {
    this._currentSrc = String(value);
  }

  appendSource(source) {
    source.parentElement = this;
    this.children.push(source);
  }

  querySelectorAll(selector) {
    if (selector === "source[src]") return this.children.filter(child => child.getAttribute("src"));
    return [];
  }

  load() {
    return "loaded";
  }
}

class HTMLVideoElement extends HTMLMediaElement {
  constructor() {
    super("VIDEO");
  }
}

class HTMLSourceElement extends Element {
  constructor() {
    super("SOURCE");
    this._src = "";
  }

  get src() {
    return this._src;
  }

  set src(value) {
    this._src = String(value);
  }
}

const context = {
  window: null,
  location: { href: "https://course.example.com/player/index.html" },
  document: { addEventListener() {} },
  navigator: {},
  Element,
  HTMLMediaElement,
  HTMLVideoElement,
  HTMLAudioElement: undefined,
  HTMLSourceElement,
  Response: undefined,
  Blob: undefined,
  ArrayBuffer,
  MediaSource: undefined,
  SourceBuffer: undefined,
  URL,
  setTimeout,
  clearTimeout,
  console,
};

context.window = context;
context.window.addEventListener = () => {};
context.window.postMessage = message => messages.push(message);

vm.createContext(context);
const hookCode = await readFile(new URL("../page_hook.js", import.meta.url), "utf8");
vm.runInContext(hookCode, context);

const directVideo = new context.HTMLVideoElement();
directVideo.src = "https://cdn.example.com/playback?id=src-assignment&token=1";

const directSource = new context.HTMLSourceElement();
directSource.setAttribute("src", "/media/source-only.mp4?token=source-direct");

const video = new context.HTMLVideoElement();
video.src = "https://cdn.example.com/playback?id=load-source&token=2";
video.setAttribute("src", "/media/lesson-direct.mp4?token=set-attribute");

const source = new context.HTMLSourceElement();
video.appendSource(source);
source.setAttribute("src", "/hls/master.m3u8?token=source-attribute");
source.src = "/dash/manifest.mpd?token=source-property";

assert.equal(video.load(), "loaded");

const resources = messages.flatMap(message => message.resources || []);
const byUrl = new Map(resources.map(resource => [resource.url, resource]));
const labels = new Set(resources.map(resource => resource.label));

assert.equal(
  byUrl.get("https://cdn.example.com/playback?id=src-assignment&token=1")?.kind,
  "video",
  "expected extensionless video.src assignment to use video-element fallback kind"
);
assert.equal(
  byUrl.get("https://cdn.example.com/playback?id=load-source&token=2")?.kind,
  "video",
  "expected video.load() to inspect the current media src"
);
assert.equal(
  byUrl.get("https://course.example.com/media/lesson-direct.mp4?token=set-attribute")?.kind,
  "video"
);
assert.equal(
  byUrl.get("https://course.example.com/media/source-only.mp4?token=source-direct")?.kind,
  "video"
);
assert.equal(
  byUrl.get("https://course.example.com/hls/master.m3u8?token=source-attribute")?.kind,
  "hls"
);
assert.equal(
  byUrl.get("https://course.example.com/dash/manifest.mpd?token=source-property")?.kind,
  "dash"
);

assert.ok(labels.has("HTMLMediaElement src"));
assert.ok(labels.has("video setAttribute src"));
assert.ok(labels.has("source setAttribute src"));
assert.ok(labels.has("HTMLSourceElement src"));
assert.ok(labels.has("HTMLMediaElement load"));

for (const resource of resources) {
  assert.equal(resource.source, "pageHookPlayer");
  assert.ok(resource.score >= (resource.kind === "video" ? 92 : 99));
}
