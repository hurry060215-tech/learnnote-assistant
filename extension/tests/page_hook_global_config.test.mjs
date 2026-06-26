import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const messages = [];
const encodedHls = "https%3A%2F%2Fcdn.example.com%2Fglobal%2Fmaster.m3u8%3Ftoken%3Dwindow";
const playInfo = {
  media: {
    hlsUrl: encodedHls,
    mimeType: "application/vnd.apple.mpegurl"
  },
  sources: [{
    videoUrl: "https://cdn.example.com/global/lesson.mp4?token=window",
    type: "video/mp4"
  }]
};
playInfo.self = playInfo;

const context = {
  window: null,
  location: { href: "https://course.example.com/player" },
  document: { addEventListener() {} },
  navigator: {},
  Response: class Response {},
  Blob,
  ArrayBuffer,
  URL,
  atob: value => Buffer.from(value, "base64").toString("binary"),
  __playInfo: playInfo,
  fetch: undefined,
  setTimeout() {
    return 0;
  },
  clearTimeout() {},
  console
};
Object.defineProperty(context, "playerConfig", {
  enumerable: true,
  get() {
    throw new Error("restricted getter");
  }
});
context.window = context;
context.window.addEventListener = () => {};
context.window.postMessage = message => messages.push(message);
context.window.HTMLMediaElement = function HTMLMediaElement() {};
context.window.HTMLMediaElement.prototype = {};

vm.createContext(context);
const hookCode = await readFile(new URL("../page_hook.js", import.meta.url), "utf8");
vm.runInContext(hookCode, context);

const resources = messages.flatMap(message => message.resources || []);
const hls = resources.find(resource => resource.url === "https://cdn.example.com/global/master.m3u8?token=window");
const video = resources.find(resource => resource.url === "https://cdn.example.com/global/lesson.mp4?token=window");

assert.ok(hls, "expected global playInfo object to expose encoded HLS URL");
assert.equal(hls.kind, "hls");
assert.equal(hls.source, "pageHookGlobal");
assert.match(hls.label, /global __playInfo/);

assert.ok(video, "expected global playInfo object to expose mp4 URL");
assert.equal(video.kind, "video");
assert.equal(video.source, "pageHookGlobal");
assert.match(video.label, /global __playInfo/);
