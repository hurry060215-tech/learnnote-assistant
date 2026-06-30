import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const messages = [];

class FakeHeaders {
  get(name) {
    if (String(name).toLowerCase() === "content-type") return "application/json";
    return "";
  }
}

class FakeResponse {
  constructor(data) {
    this.data = data;
    this.url = "https://course.example.com/api/wrapped-play";
    this.headers = new FakeHeaders();
    this.body = null;
  }

  clone() {
    throw new Error("clone unavailable");
  }

  async json() {
    return this.data;
  }
}

const wrappedJson = encodeURIComponent(JSON.stringify({
  payload: {
    hlsUrl: "https://cdn.example.com/wrapped/master.m3u8?token=nested",
    mimeType: "application/vnd.apple.mpegurl"
  }
}));
const packedJson = Buffer.from(JSON.stringify({
  playInfo: {
    videoUrl: "/api/media/file?id=42&token=abc",
    mimeType: "video/mp4"
  }
}, null, 2), "utf8").toString("base64");
const mediaKeyWrappedJson = JSON.stringify({
  mediaData: {
    playInfo: JSON.stringify({
      streams: {
        hlsUrl: "/hls/media-key/master.m3u8?token=wrapped",
        mimeType: "application/vnd.apple.mpegurl"
      }
    })
  }
});

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
  fetch: async () => new FakeResponse({ code: 0, data: wrappedJson, packed: packedJson, playInfo: mediaKeyWrappedJson }),
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

const response = await context.fetch("https://course.example.com/api/wrapped-play");
const data = await response.json();

assert.equal(data.code, 0);

const resources = messages.flatMap(message => message.resources || []);
const hls = resources.find(resource => resource.url === "https://cdn.example.com/wrapped/master.m3u8?token=nested");
const video = resources.find(resource => resource.url === "https://course.example.com/api/media/file?id=42&token=abc");
const mediaKeyHls = resources.find(resource => resource.url === "https://course.example.com/hls/media-key/master.m3u8?token=wrapped");

assert.ok(hls, "expected nested encoded JSON string to expose the HLS URL");
assert.equal(hls.kind, "hls");
assert.equal(hls.source, "pageHookBody");
assert.match(hls.label, /nested data/);
assert.ok(video, "expected nested base64 JSON string to expose the extensionless video endpoint");
assert.equal(video.kind, "video");
assert.equal(video.source, "pageHookBody");
assert.match(video.label, /nested packed/);
assert.ok(mediaKeyHls, "expected nested JSON inside a media-named field to expose HLS URL");
assert.equal(mediaKeyHls.kind, "hls");
assert.equal(mediaKeyHls.source, "pageHookBody");
assert.match(mediaKeyHls.label, /nested playInfo/);
