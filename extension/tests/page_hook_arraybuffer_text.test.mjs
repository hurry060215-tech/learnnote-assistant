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
    this.status = options.status || 200;
  }

  async arrayBuffer() {
    return this.body;
  }

  async bytes() {
    return new Uint8Array(this.body);
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
  TextDecoder,
  URL,
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

const encoder = new TextEncoder();
const jsonResponse = new context.Response(
  encoder.encode(JSON.stringify({
    videoUrl: "https://cdn.example.com/arraybuffer/lesson.mp4?token=json-buffer"
  })).buffer,
  {
    url: "https://course.example.com/api/play-json-buffer",
    headers: { "content-type": "application/octet-stream" }
  }
);
await jsonResponse.arrayBuffer();

const hlsResponse = new context.Response(
  encoder.encode("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1200000\nlesson_720.m3u8\n").buffer,
  {
    url: "https://course.example.com/api/playlist-buffer",
    headers: { "content-type": "application/octet-stream" }
  }
);
await hlsResponse.bytes();

const mp4Bytes = new Uint8Array(32);
mp4Bytes.set([0, 0, 0, 24, 102, 116, 121, 112, 105, 115, 111, 109]);
const binaryResponse = new context.Response(mp4Bytes.buffer, {
  url: "https://course.example.com/api/binary-video",
  headers: { "content-type": "application/octet-stream" }
});
await binaryResponse.arrayBuffer();

const resources = messages.flatMap(message => message.resources || []);
const jsonVideo = resources.find(resource => resource.url === "https://cdn.example.com/arraybuffer/lesson.mp4?token=json-buffer");
const hlsManifest = resources.find(resource => resource.url === "https://course.example.com/api/playlist-buffer");
const binaryFalsePositive = resources.find(resource => resource.url === "https://course.example.com/api/binary-video");

assert.ok(jsonVideo, "expected arrayBuffer JSON payload to expose the media URL");
assert.equal(jsonVideo.kind, "video");
assert.equal(jsonVideo.source, "pageHookBody");
assert.match(jsonVideo.label, /fetch arrayBuffer/);

assert.ok(hlsManifest, "expected bytes() text manifest payload to expose the response URL as HLS");
assert.equal(hlsManifest.kind, "hls");
assert.equal(hlsManifest.mime, "application/vnd.apple.mpegurl");
assert.match(hlsManifest.label, /fetch bytes manifest/);

assert.equal(binaryFalsePositive, undefined, "expected MP4 binary payload to skip text URL extraction");
