import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const messages = [];

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
  Blob,
  ArrayBuffer,
  Uint8Array,
  MediaSource: FakeMediaSource,
  SourceBuffer: FakeSourceBuffer,
  URL: class extends URL {
    static createObjectURL(value) {
      if (value instanceof FakeMediaSource) return "blob:https://course.example.com/raw-mse-1";
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

const mediaSource = new context.MediaSource();
const blobUrl = context.URL.createObjectURL(mediaSource);
const sourceBuffer = mediaSource.addSourceBuffer("video/mp4; codecs=\"avc1.64001f\"");
const initSegment = new Uint8Array([0, 0, 0, 24, 102, 116, 121, 112, 105, 115, 111, 109]);
sourceBuffer.appendBuffer(initSegment);

const resources = messages.flatMap(message => message.resources || []);
const mapped = resources.find(resource => resource.url === blobUrl);

assert.equal(blobUrl, "blob:https://course.example.com/raw-mse-1");
assert.ok(mapped, "expected raw appendBuffer to produce non-downloadable MSE evidence");
assert.equal(mapped.source, "pageHookMediaSourceAppend");
assert.equal(mapped.kind, "video");
assert.equal(mapped.blob_url, blobUrl);
assert.equal(mapped.playback_match, "blob-source");
assert.equal(mapped.mse_append_count, 1);
assert.equal(mapped.mse_append_total_bytes, initSegment.byteLength);
assert.equal(mapped.mse_append_magic, "ftyp");
assert.equal(mapped.mse_append_mime, "video/mp4; codecs=\"avc1.64001f\"");
assert.equal(mapped.mse_append_detected_kind, "video");
