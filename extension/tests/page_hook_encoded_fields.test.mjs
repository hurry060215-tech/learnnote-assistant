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

  clone() {
    return new FakeResponse(this.body, {
      url: this.url,
      headers: Object.fromEntries(this.headers.headers),
    });
  }

  async text() {
    return this.body;
  }
}

const encodedHls = "https%3A%2F%2Fcdn.example.com%2Fsecure%2Flesson.m3u8%3Ftoken%3Dabc";
const doubleEncodedHls = encodeURIComponent(encodeURIComponent("https://cdn.example.com/secure/backup.m3u8?token=double"));
const packedVideo = Buffer.from("https://cdn.example.com/video/lesson.mp4?sign=ok", "utf8").toString("base64");
const escapedHls = String.raw`https:\u002F\u002Fcdn.example.com\u002Fsecure\u002Fescaped.m3u8\u003Ftoken\u003Djs\u0026uid\u003D1`;
const escapedVideo = String.raw`https:\/\/cdn.example.com\/video\/escaped.mp4\x3Fsign\x3Dhex`;
const escapedPayload = String.raw`https:\/\/cdn.example.com\/secure\/payload.m3u8\x3Ftoken\x3Dpayload`;

const context = {
  window: null,
  location: { href: "https://course.example.com/player" },
  document: { addEventListener() {} },
  navigator: {},
  Response: FakeResponse,
  Blob,
  ArrayBuffer,
  URL,
  atob: value => Buffer.from(value, "base64").toString("binary"),
  fetch: async () => new FakeResponse(
    JSON.stringify({
      playInfo: { hls: encodedHls, backupHlsUrl: doubleEncodedHls, videoUrl: packedVideo, escapedHls, escapedVideo },
      payload: escapedPayload,
    }),
    {
      url: "https://course.example.com/api/play",
      headers: { "content-type": "application/json" },
    },
  ),
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

await context.fetch("https://course.example.com/api/play");
await new Promise(resolve => setTimeout(resolve, 20));

const resources = messages.flatMap(message => message.resources || []);
const urls = new Set(resources.map(resource => resource.url));

assert.ok(urls.has("https://cdn.example.com/secure/lesson.m3u8?token=abc"));
assert.ok(urls.has("https://cdn.example.com/secure/backup.m3u8?token=double"));
assert.ok(urls.has("https://cdn.example.com/video/lesson.mp4?sign=ok"));
assert.ok(urls.has("https://cdn.example.com/secure/escaped.m3u8?token=js&uid=1"));
assert.ok(urls.has("https://cdn.example.com/video/escaped.mp4?sign=hex"));
assert.ok(urls.has("https://cdn.example.com/secure/payload.m3u8?token=payload"));
