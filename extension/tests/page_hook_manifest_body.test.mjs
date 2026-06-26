import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const messages = [];

class FakeHeaders {
  get(name) {
    const lower = String(name || "").toLowerCase();
    if (lower === "content-type") return "application/octet-stream";
    if (lower === "content-length") return "96";
    return "";
  }
}

class FakeResponse {
  constructor(url = "https://course.example.com/api/play?lesson=1") {
    this.url = url;
    this.headers = new FakeHeaders();
    this.body = null;
  }

  clone() {
    return new FakeResponse(this.url);
  }

  async text() {
    return "#EXTM3U\n#EXT-X-VERSION:3\n#EXTINF:4.000,\nsegment-000.ts\n";
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
  fetch: async () => new FakeResponse(),
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

await context.fetch("https://course.example.com/api/play?lesson=1");
await new Promise(resolve => setTimeout(resolve, 0));

const resources = messages.flatMap(message => message.resources || []);
const hls = resources.find(resource => resource.url === "https://course.example.com/api/play?lesson=1");

assert.ok(hls, "expected octet-stream extensionless manifest body to expose response URL as HLS");
assert.equal(hls.kind, "hls");
assert.equal(hls.source, "pageHookBody");
assert.match(hls.label, /fetch body manifest|fetch text manifest/);
