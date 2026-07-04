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

class FakeDPlayer {
  constructor(options) {
    this.options = options;
  }

  switchVideo(video) {
    this.video = video;
    return "dplayer-switched";
  }
}

class FakeArtPlayer {
  constructor(options) {
    this.options = options;
  }
}

class FakeXgPlayer {
  constructor(options) {
    this.options = options;
  }

  switchUrl(source) {
    this.source = source;
    return "xg-switched";
  }
}

class FakePlyr {
  constructor(target, options = {}) {
    this.target = target;
    this.options = options;
    this._source = null;
  }

  get source() {
    return this._source;
  }

  set source(value) {
    this._source = value;
  }
}

function fakeJwplayer() {
  return {
    setup(options) {
      this.options = options;
      return "jw-setup";
    },
    load(playlist) {
      this.playlist = playlist;
      return "jw-load";
    }
  };
}

function fakeFlvCreatePlayer(mediaDataSource) {
  return {
    mediaDataSource,
    load(source) {
      this.loadedSource = source;
      return "flv-load";
    }
  };
}

function fakeMpegtsCreatePlayer(mediaDataSource) {
  return {
    mediaDataSource,
    switchUrl(source) {
      this.source = source;
      return "mpegts-switch";
    }
  };
}

const context = {
  window: null,
  location: { href: "https://course.example.com/player/index.html" },
  document: { addEventListener() {} },
  navigator: {},
  Hls: FakeHls,
  dashjs: { MediaPlayer: fakeDashMediaPlayer },
  shaka: { Player: FakeShakaPlayer },
  DPlayer: FakeDPlayer,
  Artplayer: FakeArtPlayer,
  xgplayer: { Player: FakeXgPlayer },
  Plyr: FakePlyr,
  jwplayer: fakeJwplayer,
  flvjs: { createPlayer: fakeFlvCreatePlayer },
  mpegts: { createPlayer: fakeMpegtsCreatePlayer },
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

const dplayer = new context.DPlayer({ video: { url: "/dplayer/lesson.mp4?token=1", type: "auto" } });
assert.equal(dplayer.options.video.url, "/dplayer/lesson.mp4?token=1");
assert.equal(dplayer.switchVideo({ url: "/dplayer/next.flv?token=2" }), "dplayer-switched");

const art = new context.Artplayer({ url: "/artplayer/course.m3u8?token=3" });
assert.equal(art.options.url, "/artplayer/course.m3u8?token=3");

const xg = new context.xgplayer.Player({ source: { src: "/xgplayer/stream.mpd?token=4" } });
assert.equal(xg.options.source.src, "/xgplayer/stream.mpd?token=4");
assert.equal(xg.switchUrl("/xgplayer/backup.m3u8?token=5"), "xg-switched");

const plyr = new context.Plyr("#course-video", {
  source: {
    type: "video",
    sources: [{ src: "/plyr/constructor.mp4?token=12", type: "video/mp4" }]
  }
});
plyr.source = {
  type: "video",
  sources: [
    { src: "/plyr/master.m3u8?token=13", type: "application/vnd.apple.mpegurl" },
    { src: "/plyr/fallback.mp4?token=14", type: "video/mp4" }
  ]
};

const jw = context.jwplayer("lesson-player");
assert.equal(jw.setup({ playlist: [{ file: "/jwplayer/lesson.mp4?token=6" }] }), "jw-setup");
assert.equal(jw.load([{ sources: [{ file: "/jwplayer/master.m3u8?token=7" }] }]), "jw-load");

const flv = context.flvjs.createPlayer({ type: "flv", url: "/flv/live?id=8" });
assert.equal(flv.mediaDataSource.url, "/flv/live?id=8");
assert.equal(flv.load({ backupUrl: "/flv/backup.flv?token=9" }), "flv-load");

const mpegts = context.mpegts.createPlayer({
  type: "mse",
  isLive: true,
  streamUrl: "/mpegts/live?id=10",
  segments: [{ url: "/mpegts/segment-001.m4s?token=seg" }]
});
assert.equal(mpegts.mediaDataSource.streamUrl, "/mpegts/live?id=10");
assert.equal(mpegts.switchUrl("/mpegts/backup.m3u8?token=11"), "mpegts-switch");

const resources = messages.flatMap(message => message.resources || []);
const urls = new Set(resources.map(resource => resource.url));
const labels = new Set(resources.map(resource => resource.label));

assert.ok(urls.has("https://course.example.com/media/course/master.m3u8?token=1"));
assert.ok(urls.has("https://cdn.example.com/dash/manifest.mpd?sig=1"));
assert.ok(urls.has("https://course.example.com/dash/lesson.mpd"));
assert.ok(urls.has("https://cdn.example.com/shaka/stream.mpd"));
assert.ok(urls.has("https://course.example.com/dplayer/lesson.mp4?token=1"));
assert.ok(urls.has("https://course.example.com/dplayer/next.flv?token=2"));
assert.ok(urls.has("https://course.example.com/artplayer/course.m3u8?token=3"));
assert.ok(urls.has("https://course.example.com/xgplayer/stream.mpd?token=4"));
assert.ok(urls.has("https://course.example.com/xgplayer/backup.m3u8?token=5"));
assert.ok(urls.has("https://course.example.com/plyr/constructor.mp4?token=12"));
assert.ok(urls.has("https://course.example.com/plyr/master.m3u8?token=13"));
assert.ok(urls.has("https://course.example.com/plyr/fallback.mp4?token=14"));
assert.ok(urls.has("https://course.example.com/jwplayer/lesson.mp4?token=6"));
assert.ok(urls.has("https://course.example.com/jwplayer/master.m3u8?token=7"));
assert.ok(urls.has("https://course.example.com/flv/live?id=8"));
assert.ok(urls.has("https://course.example.com/flv/backup.flv?token=9"));
assert.ok(urls.has("https://course.example.com/mpegts/live?id=10"));
assert.ok(urls.has("https://course.example.com/mpegts/segment-001.m4s?token=seg"));
assert.ok(urls.has("https://course.example.com/mpegts/backup.m3u8?token=11"));
assert.ok(labels.has("hls.js loadSource"));
assert.ok(labels.has("dash.js initialize"));
assert.ok(labels.has("dash.js attachSource"));
assert.ok(labels.has("shaka Player.load"));
assert.ok(labels.has("DPlayer constructor"));
assert.ok(labels.has("DPlayer constructor switchVideo"));
assert.ok(labels.has("ArtPlayer constructor"));
assert.ok(labels.has("xgplayer Player constructor"));
assert.ok(labels.has("xgplayer Player constructor switchUrl"));
assert.ok(labels.has("Plyr constructor"));
assert.ok(labels.has("Plyr source"));
assert.ok(labels.has("jwplayer setup"));
assert.ok(labels.has("jwplayer load"));
assert.ok(labels.has("flv.js createPlayer"));
assert.ok(labels.has("flv.js load"));
assert.ok(labels.has("mpegts.js createPlayer"));
assert.ok(labels.has("mpegts.js switchUrl"));

for (const resource of resources) {
  assert.equal(resource.source, "pageHookPlayer");
  assert.ok(["hls", "dash", "video", "fragment"].includes(resource.kind));
  const minScore = resource.kind === "hls" || resource.kind === "dash" ? 99 : resource.kind === "video" ? 92 : 64;
  assert.ok(resource.score >= minScore);
}
