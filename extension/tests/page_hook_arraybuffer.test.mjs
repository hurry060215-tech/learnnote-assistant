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

  async blob() {
    return new Blob([this.body], { type: this.headers.get("content-type") });
  }
}

let blobCounter = 0;
const context = {
  window: null,
  location: { href: "https://course.example.com/player" },
  document: { addEventListener() {} },
  navigator: {},
  Response: FakeResponse,
  Blob,
  ArrayBuffer,
  URL: class extends URL {
    static createObjectURL() {
      blobCounter += 1;
      return `blob:https://course.example.com/${blobCounter}`;
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
  url: "https://cdn.example.com/lesson.mp4?token=abc",
  headers: { "content-type": "video/mp4" },
});
const buffer = await response.arrayBuffer();
const blob = new context.Blob([buffer], { type: "video/mp4" });
const blobUrl = context.URL.createObjectURL(blob);

const resources = messages.flatMap(message => message.resources || []);
const mapped = resources.find(resource => resource.blob_url === blobUrl);

assert.equal(blobUrl, "blob:https://course.example.com/1");
assert.ok(mapped, "expected page hook to map the object URL to the original media URL");
assert.equal(mapped.url, "https://cdn.example.com/lesson.mp4?token=abc");
assert.equal(mapped.kind, "video");
assert.equal(mapped.playback_match, "blob-source");
