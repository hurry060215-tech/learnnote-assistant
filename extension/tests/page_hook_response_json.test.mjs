import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const messages = [];

class FakeHeaders {
  constructor(values = {}) {
    this.values = values;
  }

  get(name) {
    const lower = String(name).toLowerCase();
    if (this.values[lower] !== undefined) return this.values[lower];
    if (lower === "content-type") return "application/json";
    if (lower === "content-length") return "4096";
    return "";
  }

  forEach(callback) {
    const values = Object.keys(this.values).length ? this.values : {
      "content-type": "application/json",
      "content-length": "4096"
    };
    for (const [name, value] of Object.entries(values)) callback(value, name);
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

class FakeRequest {
  constructor(url, options = {}) {
    this.url = url;
    this.method = options.method || "GET";
    this.bodyText = String(options.body || "");
    this.headers = new FakeHeaders(Object.fromEntries(
      Object.entries(options.headers || {}).map(([name, value]) => [String(name).toLowerCase(), String(value)])
    ));
  }

  clone() {
    const bodyText = this.bodyText;
    return {
      text: async () => bodyText
    };
  }
}

const context = {
  window: null,
  location: { href: "https://course.example.com/player" },
  document: { addEventListener() {} },
  navigator: { userAgent: "Chrome Lesson UA" },
  Response: FakeResponse,
  Blob,
  ArrayBuffer,
  URL,
  atob: value => Buffer.from(value, "base64").toString("binary"),
  Request: FakeRequest,
  fetch: async input => {
    assert.equal(input instanceof FakeRequest, true);
    assert.equal(input.bodyText, "lesson=77&token=request-body");
    return new FakeResponse({
    stream: {
      hlsUrl: "https%3A%2F%2Fcdn.example.com%2Fjson%2Fmaster.m3u8%3Ftoken%3Dfetch-json",
      mimeType: "application/vnd.apple.mpegurl"
    },
    chaoxing: {
      objectid: "https%3A%2F%2Fcdn.example.com%2Fchaoxing%2Fmaster.m3u8%3Ftoken%3Dobject",
      dtoken: "/api/ananas/video?id=42&dtoken=abc",
      path: "/ananas/status/objectid-path?flag=normal",
      uri: "/vod/play?id=uri-json&token=ok",
      mediaType: "video/mp4"
    },
    ordinary: {
      path: "/ordinary/page"
    },
    generic: {
      data: "/api/playback/get?id=77&token=generic",
      mimeType: "video/mp4"
    },
    splitAv: {
      videoUrl: "https://cdn.example.com/dash/video-only.mp4?token=v",
      audioUrl: "https://cdn.example.com/dash/audio-only.m4a?token=a",
      videoMime: "video/mp4",
      audioMime: "audio/mp4"
    },
    splitEndpointAv: {
      videoUrl: "/api/video/stream?id=42&token=v",
      audioUrl: "/api/audio/stream?id=42&token=a",
      videoMime: "video/mp4",
      audioMime: "audio/mp4"
    },
    ambiguousSplitAv: {
      videoUrl: "/api/video/stream?id=720&token=v",
      backupUrl: "/api/video/stream?id=480&token=v",
      audioUrl: "/api/audio/unrelated?id=ad&token=a",
      videoMime: "video/mp4",
      audioMime: "audio/mp4"
    },
    bareAlias: {
      backup: "/backup?id=json-backup&token=ok",
      main: "/main?id=json-main&token=ok",
      mimeType: "video/mp4"
    },
    genericAudioEndpoint: {
      source: "/api/audio/backup?id=42&token=b"
    }
  });
  },
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

const request = new context.Request("https://course.example.com/api/play", {
  method: "POST",
  headers: {
    Accept: "application/json",
    "Content-Type": "application/x-www-form-urlencoded",
    Authorization: "Bearer fetch-token",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "X-Requested-With": "XMLHttpRequest",
    Cookie: "secret=bad"
  },
  body: "lesson=77&token=request-body"
});
const response = await context.fetch(request);
const data = await response.json();

assert.equal(data.stream.mimeType, "application/vnd.apple.mpegurl");

const resources = messages.flatMap(message => message.resources || []);
const hls = resources.find(resource => resource.url === "https://cdn.example.com/json/master.m3u8?token=fetch-json");
const objectHls = resources.find(resource => resource.url === "https://cdn.example.com/chaoxing/master.m3u8?token=object");
const dtokenVideo = resources.find(resource => resource.url === "https://course.example.com/api/ananas/video?id=42&dtoken=abc");
const pathVideo = resources.find(resource => resource.url === "https://course.example.com/ananas/status/objectid-path?flag=normal");
const uriVideo = resources.find(resource => resource.url === "https://course.example.com/vod/play?id=uri-json&token=ok");
const ordinaryPath = resources.find(resource => resource.url === "https://course.example.com/ordinary/page");
const genericVideo = resources.find(resource => resource.url === "https://course.example.com/api/playback/get?id=77&token=generic");
const splitVideo = resources.find(resource => resource.url === "https://cdn.example.com/dash/video-only.mp4?token=v");
const splitAudio = resources.find(resource => resource.url === "https://cdn.example.com/dash/audio-only.m4a?token=a");
const endpointSplitVideo = resources.find(resource => resource.url === "https://course.example.com/api/video/stream?id=42&token=v");
const endpointSplitAudio = resources.find(resource => resource.url === "https://course.example.com/api/audio/stream?id=42&token=a");
const ambiguousVideo = resources.find(resource => resource.url === "https://course.example.com/api/video/stream?id=720&token=v");
const ambiguousBackup = resources.find(resource => resource.url === "https://course.example.com/api/video/stream?id=480&token=v");
const ambiguousAudio = resources.find(resource => resource.url === "https://course.example.com/api/audio/unrelated?id=ad&token=a");
const bareBackupEndpoint = resources.find(resource => resource.url === "https://course.example.com/backup?id=json-backup&token=ok");
const bareMainEndpoint = resources.find(resource => resource.url === "https://course.example.com/main?id=json-main&token=ok");
const genericAudioEndpoint = resources.find(resource => resource.url === "https://course.example.com/api/audio/backup?id=42&token=b");

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
assert.equal(hls.request_headers.Accept, "application/json");
assert.equal(hls.request_headers["Content-Type"], "application/x-www-form-urlencoded");
assert.equal(hls.request_headers.Authorization, "Bearer fetch-token");
assert.equal(hls.request_headers["User-Agent"], "Chrome Lesson UA");
assert.equal(hls.request_headers["Sec-Fetch-Dest"], "empty");
assert.equal(hls.request_headers["Sec-Fetch-Mode"], "cors");
assert.equal(hls.request_headers["Sec-Fetch-Site"], "same-origin");
assert.equal(hls.request_headers["X-Requested-With"], "XMLHttpRequest");
assert.equal(hls.request_headers.Cookie, undefined);
assert.equal(hls.method, "POST");
assert.equal(hls.request_body.type, "text");
assert.equal(hls.request_body.content, "lesson=77&token=request-body");

assert.ok(objectHls, "expected Chaoxing-style objectid field to expose encoded HLS URL");
assert.equal(objectHls.kind, "hls");
assert.equal(objectHls.source, "pageHookBody");
assert.match(objectHls.label, /fetch json/);

assert.ok(dtokenVideo, "expected Chaoxing-style dtoken field with video context to expose extensionless video endpoint");
assert.equal(dtokenVideo.kind, "video");
assert.equal(dtokenVideo.mime, "video/mp4");
assert.equal(dtokenVideo.request_headers.Cookie, undefined);

assert.ok(pathVideo, "expected Chaoxing-style path field with video context to expose extensionless video endpoint");
assert.equal(pathVideo.kind, "video");
assert.equal(pathVideo.mime, "video/mp4");

assert.ok(uriVideo, "expected uri field with video context to expose extensionless video endpoint");
assert.equal(uriVideo.kind, "video");
assert.equal(uriVideo.mime, "video/mp4");

assert.equal(ordinaryPath, undefined, "expected ordinary path field without media context to stay out of media candidates");

assert.ok(genericVideo, "expected generic JSON data field with sibling mimeType to expose extensionless video endpoint");
assert.equal(genericVideo.kind, "video");
assert.equal(genericVideo.mime, "video/mp4");
assert.match(genericVideo.label, /fetch json/);
assert.equal(genericVideo.request_headers.Cookie, undefined);

assert.ok(splitVideo, "expected split AV JSON to expose the video-only URL");
assert.equal(splitVideo.kind, "video");
assert.equal(splitVideo.audio_url, "https://cdn.example.com/dash/audio-only.m4a?token=a");
assert.equal(splitVideo.audio_mime, "audio/mp4");
assert.match(splitVideo.label, /\+ audio/);

assert.ok(splitAudio, "expected split AV JSON to retain the audio-only resource as evidence");
assert.equal(splitAudio.kind, "audio");
assert.equal(splitAudio.mime, "audio/mp4");

assert.ok(endpointSplitVideo, "expected extensionless split AV video endpoint to be detected");
assert.equal(endpointSplitVideo.kind, "video");
assert.equal(endpointSplitVideo.audio_url, "https://course.example.com/api/audio/stream?id=42&token=a");
assert.equal(endpointSplitVideo.audio_mime, "audio/mp4");

assert.ok(endpointSplitAudio, "expected extensionless split AV audio endpoint to be detected");
assert.equal(endpointSplitAudio.kind, "audio");

assert.ok(ambiguousVideo, "expected first ambiguous video endpoint to be detected");
assert.ok(ambiguousBackup, "expected second ambiguous video endpoint to be detected");
assert.ok(ambiguousAudio, "expected ambiguous audio endpoint to remain as evidence");
assert.equal(ambiguousVideo.audio_url || "", "");
assert.equal(ambiguousBackup.audio_url || "", "");

assert.ok(bareBackupEndpoint, "expected bare backup field with sibling MIME to be detected");
assert.equal(bareBackupEndpoint.kind, "video");
assert.equal(bareBackupEndpoint.mime, "video/mp4");

assert.ok(bareMainEndpoint, "expected bare main field with sibling MIME to be detected");
assert.equal(bareMainEndpoint.kind, "video");
assert.equal(bareMainEndpoint.mime, "video/mp4");

assert.ok(genericAudioEndpoint, "expected generic source field with audio endpoint URL to be detected");
assert.equal(genericAudioEndpoint.kind, "audio");
