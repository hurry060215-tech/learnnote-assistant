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

class FakeReadableStream {
  constructor(chunks = []) {
    this.chunks = [...chunks];
  }

  getReader() {
    return {
      read: async () => {
        if (!this.chunks.length) return { done: true };
        return { done: false, value: this.chunks.shift() };
      },
    };
  }
}

class FakeResponse {
  constructor(chunks, options = {}) {
    this.url = options.url || "";
    this.headers = new FakeHeaders(options.headers || {});
    this.body = new FakeReadableStream(chunks);
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
  location: { href: "https://course.example.com/polyfill-player" },
  document: { addEventListener() {} },
  navigator: {},
  Response: FakeResponse,
  Blob,
  ArrayBuffer,
  Uint8Array,
  ReadableStream: FakeReadableStream,
  MediaSource: FakeMediaSource,
  SourceBuffer: FakeSourceBuffer,
  fetch: async () => new FakeResponse([new Uint8Array([4, 5, 6])], {
    url: "https://cdn.example.com/polyfill/lesson.mp4?token=abc",
    headers: { "content-type": "video/mp4" },
  }),
  URL: class extends URL {
    static createObjectURL(value) {
      if (value instanceof FakeMediaSource) return "blob:https://course.example.com/custom-stream";
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

const response = await context.fetch("https://cdn.example.com/polyfill/lesson.mp4?token=abc");
const reader = response.body.getReader();
const mediaSource = new context.MediaSource();
const blobUrl = context.URL.createObjectURL(mediaSource);
const sourceBuffer = mediaSource.addSourceBuffer("video/mp4");
const chunk = await reader.read();
sourceBuffer.appendBuffer(chunk.value);

const resources = messages.flatMap(message => message.resources || []);
const mapped = resources.find(resource => resource.blob_url === blobUrl);

assert.ok(mapped, "expected instance-wrapped stream reader chunks to map to the original media URL");
assert.equal(mapped.url, "https://cdn.example.com/polyfill/lesson.mp4?token=abc");
assert.equal(mapped.kind, "video");
assert.equal(mapped.source, "pageHookMediaSource");
assert.equal(mapped.playback_match, "blob-source");
