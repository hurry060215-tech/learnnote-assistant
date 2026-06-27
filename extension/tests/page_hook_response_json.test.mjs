import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const messages = [];

class FakeHeaders {
  get(name) {
    if (String(name).toLowerCase() === "content-type") return "application/json";
    if (String(name).toLowerCase() === "content-length") return "4096";
    return "";
  }
}

class FakeResponse {
  constructor(data) {
    this.data = data;
    this.url = "https://course.example.com/api/play";
    this.headers = new FakeHeaders();
    this.status = 200;
    this.body = null;
  }

  clone() {
    throw new Error("clone unavailable");
  }

  async json() {
    return this.data;
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
  URL,
  atob: value => Buffer.from(value, "base64").toString("binary"),
  fetch: async () => new FakeResponse({
    stream: {
      hlsUrl: "https%3A%2F%2Fcdn.example.com%2Fjson%2Fmaster.m3u8%3Ftoken%3Dfetch-json",
      mimeType: "application/vnd.apple.mpegurl"
    }
  }),
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

const response = await context.fetch("https://course.example.com/api/play");
const data = await response.json();

assert.equal(data.stream.mimeType, "application/vnd.apple.mpegurl");

const resources = messages.flatMap(message => message.resources || []);
const hls = resources.find(resource => resource.url === "https://cdn.example.com/json/master.m3u8?token=fetch-json");

assert.ok(hls, "expected Response.json() body to expose the encoded HLS URL");
assert.equal(hls.kind, "hls");
assert.equal(hls.source, "pageHookBody");
assert.match(hls.label, /fetch json/);
assert.equal(hls.request_type, "fetch");
assert.equal(hls.status_code, 200);
assert.equal(hls.content_length, 4096);
assert.equal(hls.initiator, "https://course.example.com/api/play");
assert.equal(hls.headers["content-type"], "application/json");
assert.equal(hls.headers["content-length"], "4096");
