import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const messages = [];
const timers = [];

const context = {
  window: null,
  location: { href: "https://course.example.com/player/index.html" },
  document: { addEventListener() {} },
  navigator: {},
  Response: undefined,
  Blob: undefined,
  ArrayBuffer,
  MediaSource: undefined,
  SourceBuffer: undefined,
  URL,
  atob: value => Buffer.from(value, "base64").toString("binary"),
  setTimeout(callback) {
    timers.push(callback);
    return timers.length;
  },
  clearTimeout() {},
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

context.lessonPlayerConfig = {
  media: {
    hlsUrl: "/late-config/master.m3u8?token=global",
    mimeType: "application/vnd.apple.mpegurl"
  },
  playlist: [{
    videoUrl: "https://cdn.example.com/late-config/lesson.mp4?token=global",
    type: "video/mp4"
  }]
};

context.__lessonPlayerConfig = JSON.stringify({
  streams: {
    dashUrl: "https://cdn.example.com/late-config/manifest.mpd?token=global",
    mimeType: "application/dash+xml"
  }
});

const resources = messages.flatMap(message => message.resources || []);
const urls = new Set(resources.map(resource => resource.url));

assert.ok(urls.has("https://course.example.com/late-config/master.m3u8?token=global"));
assert.ok(urls.has("https://cdn.example.com/late-config/lesson.mp4?token=global"));
assert.ok(urls.has("https://cdn.example.com/late-config/manifest.mpd?token=global"));

const hls = resources.find(resource => resource.url.endsWith("/late-config/master.m3u8?token=global"));
const video = resources.find(resource => resource.url.endsWith("/late-config/lesson.mp4?token=global"));
const dash = resources.find(resource => resource.url.endsWith("/late-config/manifest.mpd?token=global"));

assert.equal(hls.source, "pageHookGlobal");
assert.equal(hls.kind, "hls");
assert.match(hls.label, /global lessonPlayerConfig/);
assert.equal(video.source, "pageHookGlobal");
assert.equal(video.kind, "video");
assert.equal(dash.source, "pageHookGlobal");
assert.equal(dash.kind, "dash");
