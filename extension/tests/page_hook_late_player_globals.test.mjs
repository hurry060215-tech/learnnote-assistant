import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const messages = [];

class LateHls {
  loadSource(source) {
    this.source = source;
    return "late-hls-loaded";
  }
}

class LateDPlayer {
  constructor(options) {
    this.options = options;
  }

  switchVideo(video) {
    this.video = video;
    return "late-dplayer-switched";
  }
}

const lateFlvjs = {
  createPlayer(mediaDataSource) {
    return {
      mediaDataSource,
      setUrl(source) {
        this.source = source;
        return "late-flv-set-url";
      }
    };
  }
};

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
  setTimeout(callback) {
    timers.push(callback);
    return timers.length;
  },
  clearTimeout() {},
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

context.Hls = LateHls;
const hls = new context.Hls();
assert.equal(hls.loadSource("/late/master.m3u8?token=1"), "late-hls-loaded");

context.DPlayer = LateDPlayer;
const dplayer = new context.DPlayer({ video: { url: "/late/lesson.mp4?token=2" } });
assert.equal(dplayer.options.video.url, "/late/lesson.mp4?token=2");
assert.equal(dplayer.switchVideo({ url: "/late/next.flv?token=3" }), "late-dplayer-switched");

context.flvjs = lateFlvjs;
const flv = context.flvjs.createPlayer({ type: "flv", url: "/late/live?id=4" });
assert.equal(flv.mediaDataSource.url, "/late/live?id=4");
assert.equal(flv.setUrl("/late/live-backup.flv?token=5"), "late-flv-set-url");

const resources = messages.flatMap(message => message.resources || []);
const urls = new Set(resources.map(resource => resource.url));
const labels = new Set(resources.map(resource => resource.label));

assert.ok(urls.has("https://course.example.com/late/master.m3u8?token=1"));
assert.ok(urls.has("https://course.example.com/late/lesson.mp4?token=2"));
assert.ok(urls.has("https://course.example.com/late/next.flv?token=3"));
assert.ok(urls.has("https://course.example.com/late/live?id=4"));
assert.ok(urls.has("https://course.example.com/late/live-backup.flv?token=5"));
assert.ok(labels.has("hls.js loadSource"));
assert.ok(labels.has("DPlayer constructor"));
assert.ok(labels.has("DPlayer constructor switchVideo"));
assert.ok(labels.has("flv.js createPlayer"));
assert.ok(labels.has("flv.js setUrl"));

for (const resource of resources) {
  assert.equal(resource.source, "pageHookPlayer");
  assert.ok(["hls", "video"].includes(resource.kind));
}
