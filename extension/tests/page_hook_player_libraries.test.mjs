import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const messages = [];

class FakeHls {
  loadSource(source) {
    this.source = source;
    return "hls-loaded";
  }
}

function fakeDashMediaPlayer() {
  return {
    create() {
      return {
        attachSource(source) {
          this.attachedSource = source;
          return "dash-attached";
        },
        initialize(view, source) {
          this.view = view;
          this.initialSource = source;
          return "dash-initialized";
        }
      };
    }
  };
}

class FakeShakaPlayer {
  load(uri) {
    this.uri = uri;
    return "shaka-loaded";
  }
}

const context = {
  window: null,
  location: { href: "https://course.example.com/player/index.html" },
  document: { addEventListener() {} },
  navigator: {},
  Hls: FakeHls,
  dashjs: { MediaPlayer: fakeDashMediaPlayer },
  shaka: { Player: FakeShakaPlayer },
  Response: undefined,
  Blob: undefined,
  ArrayBuffer,
  MediaSource: undefined,
  SourceBuffer: undefined,
  URL,
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

const hls = new context.Hls();
assert.equal(hls.loadSource("/media/course/master.m3u8?token=1"), "hls-loaded");
assert.equal(hls.source, "/media/course/master.m3u8?token=1");

const dashPlayer = context.dashjs.MediaPlayer().create();
assert.equal(dashPlayer.initialize({}, "https://cdn.example.com/dash/manifest.mpd?sig=1", true), "dash-initialized");
assert.equal(dashPlayer.attachSource({ src: "/dash/lesson.mpd" }), "dash-attached");

const shaka = new context.shaka.Player();
assert.equal(shaka.load("https://cdn.example.com/shaka/stream.mpd"), "shaka-loaded");

const resources = messages.flatMap(message => message.resources || []);
const urls = new Set(resources.map(resource => resource.url));
const labels = new Set(resources.map(resource => resource.label));

assert.ok(urls.has("https://course.example.com/media/course/master.m3u8?token=1"));
assert.ok(urls.has("https://cdn.example.com/dash/manifest.mpd?sig=1"));
assert.ok(urls.has("https://course.example.com/dash/lesson.mpd"));
assert.ok(urls.has("https://cdn.example.com/shaka/stream.mpd"));
assert.ok(labels.has("hls.js loadSource"));
assert.ok(labels.has("dash.js initialize"));
assert.ok(labels.has("dash.js attachSource"));
assert.ok(labels.has("shaka Player.load"));

for (const resource of resources) {
  assert.equal(resource.source, "pageHookPlayer");
  assert.ok(resource.kind === "hls" || resource.kind === "dash");
  assert.ok(resource.score >= 99);
}
