import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const messages = [];

class FakeHeaders {
  constructor(values = {}) {
    this.values = Object.fromEntries(Object.entries(values).map(([key, value]) => [key.toLowerCase(), value]));
  }

  get(name) {
    return this.values[String(name || "").toLowerCase()] || "";
  }
}

class FakeResponse {
  constructor({ url = "", body = "", headers = {} } = {}) {
    this.url = url;
    this.value = body;
    this.headers = new FakeHeaders(headers);
    this.status = 200;
    this.body = null;
  }

  clone() {
    return new FakeResponse({
      url: this.url,
      body: this.value,
      headers: this.headers.values
    });
  }

  async text() {
    return this.value;
  }

  async blob() {
    return new Blob([this.value || "cached media"], { type: this.headers.get("content-type") || "video/mp4" });
  }

  async arrayBuffer() {
    return new TextEncoder().encode(this.value || "cached media").buffer;
  }
}

class FakeCache {
  constructor() {
    this.items = new Map();
  }

  key(request) {
    return typeof request === "string" ? request : request?.url || "";
  }

  async put(request, response) {
    this.items.set(this.key(request), response);
  }

  async match(request) {
    return this.items.get(this.key(request)) || null;
  }

  async matchAll() {
    return [...this.items.values()];
  }

  async add(request) {
    this.items.set(this.key(request), new FakeResponse({ url: this.key(request), headers: { "content-type": "video/mp4" } }));
  }

  async addAll(requests) {
    for (const request of requests || []) await this.add(request);
  }
}

const cache = new FakeCache();
const manifestBody = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1200000\nlesson_720.m3u8\n";

const context = {
  window: null,
  location: { href: "https://course.example.com/player" },
  document: { addEventListener() {} },
  navigator: {},
  Response: FakeResponse,
  Cache: FakeCache,
  caches: {
    open: async () => cache,
    match: async request => cache.match(request)
  },
  Blob,
  ArrayBuffer,
  TextEncoder,
  URL,
  atob: value => Buffer.from(value, "base64").toString("binary"),
  fetch: async () => new FakeResponse({ url: "https://course.example.com/api/play-cache", body: manifestBody, headers: { "content-type": "application/octet-stream" } }),
  setTimeout,
  clearTimeout,
  console
};
context.window = context;
context.window.addEventListener = () => {};
context.window.postMessage = message => messages.push(message);
context.window.HTMLMediaElement = function HTMLMediaElement() {};
context.window.HTMLMediaElement.prototype = {};

vm.createContext(context);
const hookCode = await readFile(new URL("../page_hook.js", import.meta.url), "utf8");
vm.runInContext(hookCode, context);

const opened = await context.caches.open("lesson-cache");
const manifestResponse = new FakeResponse({
  url: "",
  body: manifestBody,
  headers: {
    "content-type": "application/octet-stream",
    "content-length": String(manifestBody.length)
  }
});
await opened.put("https://course.example.com/api/play-cache", manifestResponse);
await new Promise(resolve => setTimeout(resolve, 0));

let resources = messages.flatMap(message => message.resources || []);
const manifest = resources.find(resource => resource.url === "https://course.example.com/api/play-cache");
assert.ok(manifest, "expected cache.put manifest body to expose the cache request URL");
assert.equal(manifest.kind, "hls");
assert.equal(manifest.source, "pageHookCache");

const mediaResponse = new FakeResponse({
  url: "",
  body: "cached mp4 bytes",
  headers: { "content-type": "video/mp4" }
});
await opened.put("https://cdn.example.com/cache/lesson.mp4?token=cached", mediaResponse);
const cachedMedia = await opened.match("https://cdn.example.com/cache/lesson.mp4?token=cached");
await cachedMedia.blob();

const cachedViaStorage = await context.caches.match("https://cdn.example.com/cache/lesson.mp4?token=cached");
await cachedViaStorage.arrayBuffer();

resources = messages.flatMap(message => message.resources || []);
const cachedBlobSource = resources.find(resource =>
  resource.url === "https://cdn.example.com/cache/lesson.mp4?token=cached" &&
  resource.source === "pageHookBlob"
);
assert.ok(cachedBlobSource, "expected cache.match response blob to map back to the cached media URL");
assert.equal(cachedBlobSource.kind, "video");
assert.ok(
  resources.some(resource =>
    resource.url === "https://cdn.example.com/cache/lesson.mp4?token=cached" &&
    resource.source === "pageHookCache" &&
    /storage match|cache match/.test(resource.label)
  ),
  "expected CacheStorage.match to expose cached media responses"
);
