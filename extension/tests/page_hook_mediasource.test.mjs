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

  async arrayBuffer() {
    return this.body;
  }
}

class FakeSourceBuffer {
  appendBuffer(buffer) {
    this.buffer = buffer;
  }

  appendBufferAsync(buffer) {
    this.asyncBuffer = buffer;
    return Promise.resolve("async-appended");
  }

  changeType(type) {
    this.changedType = type;
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
  MediaSource: FakeMediaSource,
  SourceBuffer: FakeSourceBuffer,
  URL: class extends URL {
    static mediaSourceCount = 0;

    static createObjectURL(value) {
      if (value instanceof FakeMediaSource) {
        this.mediaSourceCount += 1;
        return `blob:https://course.example.com/mse-${this.mediaSourceCount}`;
      }
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
  url: "https://cdn.example.com/mse/lesson.mp4?token=abc",
  headers: { "content-type": "video/mp4" },
});
const buffer = await response.arrayBuffer();
const mediaSource = new context.MediaSource();
const blobUrl = context.URL.createObjectURL(mediaSource);
const sourceBuffer = mediaSource.addSourceBuffer("video/mp4");
sourceBuffer.appendBuffer(buffer);

const resources = messages.flatMap(message => message.resources || []);
const mapped = resources.find(resource => resource.blob_url === blobUrl);

assert.equal(blobUrl, "blob:https://course.example.com/mse-1");
assert.ok(mapped, "expected page hook to map the MediaSource blob URL to the original media URL");
assert.equal(mapped.url, "https://cdn.example.com/mse/lesson.mp4?token=abc");
assert.equal(mapped.kind, "video");
assert.equal(mapped.source, "pageHookMediaSource");
assert.equal(mapped.playback_match, "blob-source");

const extensionlessResponse = new context.Response(new Uint8Array([0, 0, 0, 24, 102, 116, 121, 112]).buffer, {
  url: "https://cdn.example.com/api/playback/getVideo?id=42&token=abc",
  headers: {
    "content-type": "application/octet-stream",
    "content-length": "8388608",
    "accept-ranges": "bytes"
  },
});
const extensionlessBuffer = await extensionlessResponse.arrayBuffer();
const extensionlessMediaSource = new context.MediaSource();
const extensionlessBlobUrl = context.URL.createObjectURL(extensionlessMediaSource);
const extensionlessSourceBuffer = extensionlessMediaSource.addSourceBuffer("video/mp4");
extensionlessSourceBuffer.appendBuffer(extensionlessBuffer);

const updatedResources = messages.flatMap(message => message.resources || []);
const extensionlessMapped = updatedResources.find(resource => resource.blob_url === extensionlessBlobUrl);

assert.ok(extensionlessMapped, "expected extensionless binary playback response to map through MediaSource");
assert.equal(extensionlessMapped.url, "https://cdn.example.com/api/playback/getVideo?id=42&token=abc");
assert.equal(extensionlessMapped.kind, "video");
assert.equal(extensionlessMapped.mime, "application/octet-stream");
assert.equal(extensionlessMapped.content_length, 8388608);
assert.equal(extensionlessMapped.headers["accept-ranges"], "bytes");

const asyncMediaSource = new context.MediaSource();
const asyncBlobUrl = context.URL.createObjectURL(asyncMediaSource);
const asyncSourceBuffer = asyncMediaSource.addSourceBuffer("video/mp4");
asyncSourceBuffer.changeType("audio/mp4");
assert.equal(
  await asyncSourceBuffer.appendBufferAsync(new Uint8Array([73, 68, 51, 4, 0, 0, 0, 0]).buffer),
  "async-appended"
);

const asyncResources = messages.flatMap(message => message.resources || []);
const asyncMapped = asyncResources.find(resource => resource.blob_url === asyncBlobUrl);

assert.ok(asyncMapped, "expected appendBufferAsync without response meta to emit MSE append evidence");
assert.equal(asyncMapped.source, "pageHookMediaSourceAppend");
assert.equal(asyncMapped.kind, "audio");
assert.equal(asyncMapped.mime, "audio/mp4");
assert.equal(asyncMapped.mse_append_mime, "audio/mp4");
assert.equal(asyncMapped.label, "MSE appendBufferAsync");
