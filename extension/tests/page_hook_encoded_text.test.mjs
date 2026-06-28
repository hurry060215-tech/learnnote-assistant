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

  clone() {
    return new FakeResponse(this.body, {
      url: this.url,
      headers: Object.fromEntries(this.headers.headers),
      status: this.status,
    });
  }

  async text() {
    return this.body;
  }
}

const encodedHls = "https%3A%2F%2Fcdn.example.com%2Fsecure%2Flesson.m3u8%3Ftoken%3Dabc%26uid%3D1";
const doubleEncodedVideo = encodeURIComponent(encodeURIComponent("https://cdn.example.com/secure/double.mp4?token=twice"));

const context = {
  window: null,
  location: { href: "https://course.example.com/lesson/index.html" },
  document: { addEventListener() {} },
  navigator: {},
  Response: FakeResponse,
  Blob,
  ArrayBuffer,
  URL,
  atob: value => Buffer.from(value, "base64").toString("binary"),
  fetch: async () => new FakeResponse(
    `<a href="/player?objectid=${encodedHls}">open player</a><script>load(https://cdn.example.com/plain/naked.m3u8?token=naked); window.__encoded='${doubleEncodedVideo}';</script>`,
    {
      url: "https://course.example.com/lesson/index.html",
      headers: { "content-type": "text/html" },
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

await context.fetch("https://course.example.com/lesson/index.html");
await new Promise(resolve => setTimeout(resolve, 20));

const resources = messages.flatMap(message => message.resources || []);
const hls = resources.find(resource => resource.url === "https://cdn.example.com/secure/lesson.m3u8?token=abc&uid=1");
const nakedHls = resources.find(resource => resource.url === "https://cdn.example.com/plain/naked.m3u8?token=naked");
const doubleVideo = resources.find(resource => resource.url === "https://cdn.example.com/secure/double.mp4?token=twice");
const malformedEncodedUrls = resources.filter(resource => /\/https%3A%2F%2F/i.test(resource.url));

assert.ok(hls, "expected page hook to decode encoded media URL from plain HTML text");
assert.equal(hls.kind, "hls");
assert.equal(hls.mime, "application/vnd.apple.mpegurl");
assert.equal(hls.source, "pageHookBody");
assert.match(hls.label, /encoded url/);
assert.equal(hls.request_type, "fetch");
assert.equal(hls.status_code, 200);

assert.ok(nakedHls, "expected page hook to trim trailing JS punctuation from plain media URL");
assert.equal(nakedHls.kind, "hls");
assert.equal(nakedHls.source, "pageHookBody");
assert.equal(nakedHls.request_type, "fetch");

assert.ok(doubleVideo, "expected page hook to decode double-encoded media URL from plain HTML text");
assert.equal(doubleVideo.kind, "video");
assert.equal(doubleVideo.source, "pageHookBody");
assert.match(doubleVideo.label, /encoded url/);

assert.equal(malformedEncodedUrls.length, 0, "expected page hook to normalize encoded absolute media URLs before URL resolution");
