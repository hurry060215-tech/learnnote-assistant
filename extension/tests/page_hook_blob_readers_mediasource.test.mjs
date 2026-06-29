import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const messages = [];

class FakeHeaders {
  constructor(headers = {}) {
    this.headers = new Map(Object.entries(headers).map(([key, value]) => [key.toLowerCase(), value]));
  }

  get(name) {
    return this.headers.get(String(name).toLowerCase()) || "";
  }
}

class FakeResponse {
  constructor(body, options = {}) {
    this.body = body;
    this.url = options.url || "";
    this.headers = new FakeHeaders(options.headers || {});
  }

  async blob() {
    return new Blob([this.body], { type: this.headers.get("content-type") });
  }
}

class FakeSourceBuffer {
  appendBuffer(buffer) {
    this.buffer = buffer;
  }
}

class FakeMediaSource {
  constructor() {
    this.readyState = "open";
  }

  addSourceBuffer() {
    return new FakeSourceBuffer();
  }
}

const context = {
  window: null,
  location: { href: "https://course.example.com/player" },
  document: { addEventListener() {} },
  navigator: {},
  Response: FakeResponse,
  Blob,
  ArrayBuffer,
  Uint8Array,
  MediaSource: FakeMediaSource,
  SourceBuffer: FakeSourceBuffer,
  URL: class extends URL {
    static createObjectURL(value) {
      if (value instanceof FakeMediaSource) return "blob:https://course.example.com/blob-reader-mse-1";
      return "blob:https://course.example.com/blob-1";
    }

    static revokeObjectURL() {}
  },
  setTimeout,
  clearTimeout,
  console,
};
context.window = context;
context.window.addEventListener = () => {};
context.window.postMessage = message => messages.push(message);
context.window.HTMLMediaElement = function HTMLMediaElement() {};
context.window.HTMLMediaElement.prototype = {};

vm.createContext(context);
const hookCode = await readFile(new URL("../page_hook.js", import.meta.url), "utf8");
vm.runInContext(hookCode, context);

const response = new context.Response(new Uint8Array([1, 2, 3]).buffer, {
  url: "https://cdn.example.com/blob-reader/lesson.mp4?token=abc",
  headers: { "content-type": "video/mp4" },
});
const blob = await response.blob();
const buffer = await blob.arrayBuffer();
const mediaSource = new context.MediaSource();
const blobUrl = context.URL.createObjectURL(mediaSource);
const sourceBuffer = mediaSource.addSourceBuffer("video/mp4");
sourceBuffer.appendBuffer(buffer);

const resources = messages.flatMap(message => message.resources || []);
const mapped = resources.find(resource => resource.blob_url === blobUrl);

assert.equal(blobUrl, "blob:https://course.example.com/blob-reader-mse-1");
assert.ok(mapped, "expected page hook to map Blob.arrayBuffer() MSE chunks to the original media URL");
assert.equal(mapped.url, "https://cdn.example.com/blob-reader/lesson.mp4?token=abc");
assert.equal(mapped.kind, "video");
assert.equal(mapped.source, "pageHookMediaSource");
assert.equal(mapped.playback_match, "blob-source");
