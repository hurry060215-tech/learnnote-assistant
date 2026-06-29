import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

function listener() {
  return { addListener() {} };
}

const context = {
  console,
  Date,
  URL,
  URLSearchParams,
  chrome: {
    webRequest: {
      onBeforeSendHeaders: listener(),
      onBeforeRequest: listener(),
      onHeadersReceived: listener(),
      onBeforeRedirect: listener(),
      onCompleted: listener(),
      onErrorOccurred: listener()
    },
    tabs: {
      onRemoved: listener(),
      onUpdated: listener(),
      query() {}
    },
    action: { onClicked: listener() },
    runtime: { onMessage: listener() },
    webNavigation: { getAllFrames() {} },
    sidePanel: { open() {} },
    scripting: { executeScript() {} },
    cookies: { getAll() {} }
  }
};

vm.createContext(context);
const backgroundCode = await readFile(new URL("../background.js", import.meta.url), "utf8");
vm.runInContext(backgroundCode, context);

const headers = context.normalizeRequestHeaders([
  { name: "Referer", value: "https://course.example.com/lesson\r\nX-Bad: nope" },
  { name: "Origin", value: "https://course.example.com" },
  { name: "User-Agent", value: "Chrome Test UA" },
  { name: "Accept-Language", value: "zh-CN,zh;q=0.9" },
  { name: "Content-Type", value: "application/x-www-form-urlencoded" },
  { name: "Range", value: "bytes=0-" },
  { name: "Sec-Fetch-Dest", value: "video" },
  { name: "Sec-Fetch-Mode", value: "no-cors" },
  { name: "Sec-Fetch-Site", value: "same-site" },
  { name: "Sec-CH-UA", value: '"Chromium";v="126"' },
  { name: "Sec-CH-UA-Mobile", value: "?0" },
  { name: "Sec-CH-UA-Platform", value: '"Windows"' },
  { name: "X-Requested-With", value: "XMLHttpRequest" },
  { name: "Cookie", value: "bad=1" },
  { name: "Authorization", value: "Bearer bad" }
]);

assert.equal(headers.Referer, "https://course.example.com/lesson X-Bad: nope");
assert.equal(headers.Origin, "https://course.example.com");
assert.equal(headers["User-Agent"], "Chrome Test UA");
assert.equal(headers["Accept-Language"], "zh-CN,zh;q=0.9");
assert.equal(headers["Content-Type"], "application/x-www-form-urlencoded");
assert.equal(headers.Range, "bytes=0-");
assert.equal(headers["Sec-Fetch-Dest"], "video");
assert.equal(headers["Sec-Fetch-Mode"], "no-cors");
assert.equal(headers["Sec-Fetch-Site"], "same-site");
assert.equal(headers["Sec-CH-UA"], '"Chromium";v="126"');
assert.equal(headers["Sec-CH-UA-Mobile"], "?0");
assert.equal(headers["Sec-CH-UA-Platform"], '"Windows"');
assert.equal(headers["X-Requested-With"], "XMLHttpRequest");
assert.equal(headers.Cookie, undefined);
assert.equal(headers.Authorization, undefined);

assert.equal(
  context.classifyCompletedRequest({
    url: "https://cdn.example.com/playback?id=abc",
    type: "media"
  }, "application/octet-stream"),
  "video"
);
assert.equal(
  context.classifyCompletedRequest({
    url: "https://cdn.example.com/live/lesson.flv?token=abc",
    type: "xmlhttprequest"
  }, ""),
  "video"
);
assert.equal(
  context.classifyCompletedRequest({
    url: "https://cdn.example.com/api/player?id=abc",
    type: "xmlhttprequest"
  }, "application/octet-stream"),
  "unknown"
);
assert.equal(
  context.classifyCompletedRequest(
    {
      url: "https://cdn.example.com/api/playback/getVideo?id=abc",
      type: "xmlhttprequest"
    },
    "application/octet-stream",
    {},
    { "content-length": "8388608" }
  ),
  "video"
);
assert.equal(
  context.classifyCompletedRequest(
    {
      url: "https://cdn.example.com/api/download?id=abc",
      type: "xmlhttprequest"
    },
    "application/octet-stream",
    {},
    { "content-disposition": "attachment; filename*=UTF-8''lesson%20download.mp4" }
  ),
  "video"
);
assert.equal(
  context.classifyCompletedRequest(
    {
      url: "https://cdn.example.com/api/range?id=abc",
      type: "xmlhttprequest"
    },
    "application/octet-stream",
    { Range: "bytes=0-" },
    { "content-range": "bytes 0-1048575/8388608" }
  ),
  "video"
);
assert.ok(
  context.scoreKind("https://cdn.example.com/playback?id=abc", "webRequest", "video") >= 95,
  "expected extensionless browser media requests to rank like video candidates"
);
assert.deepEqual(Array.from(context.inferSiblingManifestUrls("https://cdn.example.com/live/seg-001.ts?token=abc")), [
  "https://cdn.example.com/live/index.m3u8?token=abc",
  "https://cdn.example.com/live/playlist.m3u8?token=abc",
  "https://cdn.example.com/live/master.m3u8?token=abc"
]);
assert.deepEqual(Array.from(context.inferSiblingManifestUrls("https://cdn.example.com/dash/chunk-001.m4s?token=abc")), [
  "https://cdn.example.com/dash/manifest.mpd?token=abc",
  "https://cdn.example.com/dash/index.mpd?token=abc",
  "https://cdn.example.com/dash/master.m3u8?token=abc",
  "https://cdn.example.com/dash/index.m3u8?token=abc"
]);

const hinted = context.withPlaybackHints(
  {
    url: "https://cdn.example.com/playback?id=abc",
    source: "webRequest",
    kind: "video",
    score: 80,
    frame_id: 9,
    initiator: "https://course.example.com",
    time_stamp: Date.now() - 5000,
    request_headers: {
      Range: "bytes=800000-"
    }
  },
  {
    page_url: "https://course.example.com/lesson/1",
    active_video: {
      src: "blob:https://course.example.com/active",
      paused: false,
      current_time: 420,
      duration: 1800,
      frame_id: 9
    }
  }
);

assert.equal(hinted.playback_match, "range-near-playhead");
assert.equal(hinted.is_main_video, true);
assert.equal(hinted.current_time, 420);
assert.ok(hinted.score >= 100, "expected recent range media requests near the active playhead to be top-ranked");

const manifestHinted = context.withPlaybackHints(
  {
    url: "https://cdn.example.com/live/master.m3u8?token=abc",
    source: "webRequest",
    kind: "hls",
    score: 100,
    frame_id: 9,
    initiator: "https://course.example.com",
    time_stamp: Date.now() - 4000
  },
  {
    page_url: "https://course.example.com/lesson/1",
    active_video: {
      src: "blob:https://course.example.com/active",
      paused: false,
      current_time: 420,
      duration: 1800,
      frame_id: 9
    }
  }
);

assert.equal(manifestHinted.playback_match, "manifest-near-playhead");
assert.equal(manifestHinted.is_main_video, true);
assert.equal(manifestHinted.current_time, 420);

const sortedCandidates = [
  {
    url: "https://cdn.example.com/archive.mp4",
    source: "webRequest",
    kind: "video",
    score: 100,
    time_stamp: Date.now() - 1000
  },
  manifestHinted,
  {
    url: "https://cdn.example.com/subtitles.vtt",
    source: "webRequest",
    kind: "subtitle",
    score: 100,
    time_stamp: Date.now()
  }
].sort(context.compareResourceCandidates);

assert.equal(sortedCandidates[0].url, manifestHinted.url);

const preservedResources = context.mergeAndRankResources(
  [
    {
      url: "https://cdn.example.com/manual.mp4",
      source: "webRequest",
      kind: "video",
      score: 100,
      time_stamp: Date.now() - 1000
    },
    {
      url: "https://cdn.example.com/live/manual.m3u8",
      source: "webRequest",
      kind: "hls",
      score: 100,
      frame_id: 9,
      initiator: "https://course.example.com",
      time_stamp: Date.now() - 1000
    }
  ],
  {
    page_url: "https://course.example.com/lesson/1",
    active_video: {
      src: "blob:https://course.example.com/active",
      paused: false,
      current_time: 420,
      frame_id: 9
    }
  },
  { id: 501 },
  { preserveOrder: true }
);

assert.equal(preservedResources[0].url, "https://cdn.example.com/manual.mp4");
assert.equal(preservedResources[1].playback_match, "manifest-near-playhead");

context.addResource(502, {
  url: "https://cdn.example.com/archive.mp4",
  source: "webRequest",
  kind: "video",
  score: 100,
  time_stamp: Date.now() - 1000
}, false);
context.addResource(502, {
  url: "https://cdn.example.com/live/cached.m3u8",
  source: "webRequest",
  kind: "hls",
  score: 100,
  frame_id: 9,
  initiator: "https://course.example.com",
  time_stamp: Date.now() - 1000
}, false);

const cachedResources = context.mergeAndRankResources(
  undefined,
  {
    page_url: "https://course.example.com/lesson/1",
    active_video: {
      src: "blob:https://course.example.com/active",
      paused: false,
      current_time: 420,
      frame_id: 9
    }
  },
  { id: 502 }
);

assert.equal(cachedResources[0].url, "https://cdn.example.com/live/cached.m3u8");
assert.equal(cachedResources[0].playback_match, "manifest-near-playhead");

context.recordResponseMedia({
  requestId: "local-preview",
  tabId: 177,
  url: "http://127.0.0.1:8765/api/tasks/task-1/media",
  type: "media",
  method: "GET",
  statusCode: 206,
  responseHeaders: [
    { name: "Content-Type", value: "video/mp4" },
    { name: "Content-Range", value: "bytes 0-1048575/8388608" }
  ]
});

context.recordResponseMedia({
  requestId: "local-export-media",
  tabId: 178,
  url: "http://localhost:8765/api/tasks/task-1/exports/media",
  type: "media",
  method: "GET",
  statusCode: 200,
  responseHeaders: [
    { name: "Content-Type", value: "video/mp4" },
    { name: "Content-Length", value: "8388608" }
  ]
});

assert.equal(vm.runInContext("resourceByTab.get(177)", context), undefined);
assert.equal(vm.runInContext("resourceByTab.get(178)", context), undefined);

context.rememberRequestHeaders({
  requestId: "api-play-hls",
  url: "https://course.example.com/api/play?lesson=42",
  type: "xmlhttprequest",
  requestHeaders: [
    { name: "Referer", value: "https://course.example.com/lesson" },
    { name: "Origin", value: "https://course.example.com" },
    { name: "User-Agent", value: "Chrome Playback UA" }
  ]
});
context.recordResponseMedia({
  requestId: "api-play-hls",
  tabId: 16,
  url: "https://course.example.com/api/play?lesson=42",
  type: "xmlhttprequest",
  method: "GET",
  statusCode: 200,
  frameId: 0,
  documentUrl: "https://course.example.com/lesson",
  initiator: "https://course.example.com",
  timeStamp: Date.now(),
  responseHeaders: [
    { name: "Content-Type", value: "application/vnd.apple.mpegurl" },
    { name: "Location", value: "https://media.example.net/redirected/master.m3u8" },
    { name: "Content-Location", value: "/relative/master.m3u8" }
  ]
}, context.peekRequestHeaders("api-play-hls"));

const apiPlayResources = vm.runInContext("resourceByTab.get(16)", context);
assert.equal(apiPlayResources.length, 2);
const apiPlayEndpoint = apiPlayResources.find(item => item.url === "https://course.example.com/api/play?lesson=42");
const apiPlayFinal = apiPlayResources.find(item => item.url === "https://media.example.net/redirected/master.m3u8");
assert.equal(apiPlayEndpoint.kind, "hls");
assert.equal(apiPlayEndpoint.request_headers.Referer, "https://course.example.com/lesson");
assert.equal(apiPlayEndpoint.request_headers.Origin, "https://course.example.com");
assert.equal(apiPlayEndpoint.request_headers["User-Agent"], "Chrome Playback UA");
assert.equal(apiPlayEndpoint.headers.location, "https://media.example.net/redirected/master.m3u8");
assert.equal(apiPlayEndpoint.headers["content-location"], "/relative/master.m3u8");
assert.equal(apiPlayEndpoint.resolved_url, "https://media.example.net/redirected/master.m3u8");
assert.equal(apiPlayFinal.kind, "hls");
assert.equal(apiPlayFinal.source, "webRequestResolved");
assert.equal(apiPlayFinal.request_headers.Referer, "https://course.example.com/lesson");
assert.equal(apiPlayFinal.playback_match, "resolved-final-url");
const apiPlayRanked = context.mergeAndRankResources(apiPlayResources, {}, {});
assert.equal(apiPlayRanked[0].url, "https://media.example.net/redirected/master.m3u8");

context.rememberRequestBody({
  requestId: "post-json-play-api",
  url: "https://course.example.com/api/play",
  type: "xmlhttprequest",
  method: "POST",
  requestBody: {
    formData: {
      lesson: ["42"],
      token: ["ok"]
    }
  }
});
context.rememberRequestHeaders({
  requestId: "post-json-play-api",
  url: "https://course.example.com/api/play",
  type: "xmlhttprequest",
  method: "POST",
  requestHeaders: [
    { name: "Referer", value: "https://course.example.com/lesson" },
    { name: "Origin", value: "https://course.example.com" },
    { name: "User-Agent", value: "Chrome Playback UA" },
    { name: "Content-Type", value: "application/x-www-form-urlencoded" },
    { name: "X-Requested-With", value: "XMLHttpRequest" }
  ]
});
context.recordResponseMedia({
  requestId: "post-json-play-api",
  tabId: 164,
  url: "https://course.example.com/api/play",
  type: "xmlhttprequest",
  method: "POST",
  statusCode: 200,
  frameId: 0,
  documentUrl: "https://course.example.com/lesson",
  initiator: "https://course.example.com",
  timeStamp: Date.now(),
  responseHeaders: [
    { name: "Content-Type", value: "application/json" }
  ]
}, context.peekRequestHeaders("post-json-play-api"), context.peekRequestBody("post-json-play-api"));

const postPlayResources = vm.runInContext("resourceByTab.get(164)", context);
assert.equal(postPlayResources.length, 1);
assert.equal(postPlayResources[0].method, "POST");
assert.equal(postPlayResources[0].request_headers["Content-Type"], "application/x-www-form-urlencoded");
assert.equal(postPlayResources[0].request_body.type, "form");
assert.equal(postPlayResources[0].request_body.content, "lesson=42&token=ok");

context.rememberRequestHeaders({
  requestId: "redirect-play-hls",
  url: "https://course.example.com/api/play/redirect?lesson=42",
  type: "xmlhttprequest",
  requestHeaders: [
    { name: "Referer", value: "https://course.example.com/lesson" },
    { name: "Origin", value: "https://course.example.com" },
    { name: "User-Agent", value: "Chrome Playback UA" }
  ]
});
context.recordRedirectMedia({
  requestId: "redirect-play-hls",
  tabId: 162,
  url: "https://course.example.com/api/play/redirect?lesson=42",
  redirectUrl: "https://media.example.net/tmp/master.m3u8?sig=abc",
  type: "xmlhttprequest",
  method: "GET",
  statusCode: 302,
  frameId: 0,
  documentUrl: "https://course.example.com/lesson",
  initiator: "https://course.example.com",
  timeStamp: Date.now(),
  responseHeaders: [
    { name: "Location", value: "https://media.example.net/tmp/master.m3u8?sig=abc" }
  ]
}, context.peekRequestHeaders("redirect-play-hls"));

const redirectPlayResources = vm.runInContext("resourceByTab.get(162)", context);
assert.equal(redirectPlayResources.length, 2);
const redirectEndpoint = redirectPlayResources.find(item => item.url === "https://course.example.com/api/play/redirect?lesson=42");
const redirectFinal = redirectPlayResources.find(item => item.url === "https://media.example.net/tmp/master.m3u8?sig=abc");
assert.equal(redirectEndpoint.kind, "hls");
assert.equal(redirectEndpoint.resolved_url, "https://media.example.net/tmp/master.m3u8?sig=abc");
assert.equal(redirectEndpoint.headers.location, "https://media.example.net/tmp/master.m3u8?sig=abc");
assert.equal(redirectEndpoint.request_headers.Referer, "https://course.example.com/lesson");
assert.equal(redirectEndpoint.request_headers.Origin, "https://course.example.com");
assert.equal(redirectEndpoint.label, "HLS redirect");
assert.equal(redirectFinal.kind, "hls");
assert.equal(redirectFinal.source, "webRequestResolved");
assert.equal(redirectFinal.request_headers.Referer, "https://course.example.com/lesson");
assert.equal(redirectFinal.playback_match, "resolved-final-url");
const redirectRanked = context.mergeAndRankResources(redirectPlayResources, {}, {});
assert.equal(redirectRanked[0].url, "https://media.example.net/tmp/master.m3u8?sig=abc");

context.rememberRequestHeaders({
  requestId: "download-api-video",
  url: "https://course.example.com/api/download?id=42",
  type: "xmlhttprequest",
  requestHeaders: [
    { name: "Referer", value: "https://course.example.com/lesson" },
    { name: "Origin", value: "https://course.example.com" },
    { name: "User-Agent", value: "Chrome Playback UA" }
  ]
});
context.recordResponseMedia({
  requestId: "download-api-video",
  tabId: 161,
  url: "https://course.example.com/api/download?id=42",
  type: "xmlhttprequest",
  method: "GET",
  statusCode: 200,
  frameId: 0,
  documentUrl: "https://course.example.com/lesson",
  initiator: "https://course.example.com",
  timeStamp: Date.now(),
  responseHeaders: [
    { name: "Content-Type", value: "application/octet-stream" },
    { name: "Content-Disposition", value: "attachment; filename*=UTF-8''lesson%20download.mp4" },
    { name: "Content-Length", value: "8388608" }
  ]
}, context.peekRequestHeaders("download-api-video"));

const downloadApiResources = vm.runInContext("resourceByTab.get(161)", context);
assert.equal(downloadApiResources.length, 1);
assert.equal(downloadApiResources[0].kind, "video");
assert.equal(downloadApiResources[0].headers["content-disposition"], "attachment; filename*=UTF-8''lesson%20download.mp4");
assert.equal(downloadApiResources[0].content_length, 8388608);
assert.equal(downloadApiResources[0].request_headers.Referer, "https://course.example.com/lesson");
assert.equal(downloadApiResources[0].request_headers.Origin, "https://course.example.com");

context.rememberRequestHeaders({
  requestId: "large-binary-playback-api",
  url: "https://course.example.com/api/playback/getVideo?id=42",
  type: "xmlhttprequest",
  requestHeaders: [
    { name: "Referer", value: "https://course.example.com/lesson" },
    { name: "Origin", value: "https://course.example.com" },
    { name: "User-Agent", value: "Chrome Playback UA" },
    { name: "X-Requested-With", value: "XMLHttpRequest" }
  ]
});
context.recordResponseMedia({
  requestId: "large-binary-playback-api",
  tabId: 163,
  url: "https://course.example.com/api/playback/getVideo?id=42",
  type: "xmlhttprequest",
  method: "GET",
  statusCode: 200,
  frameId: 2,
  documentUrl: "https://course.example.com/lesson",
  initiator: "https://course.example.com",
  timeStamp: Date.now(),
  responseHeaders: [
    { name: "Content-Type", value: "application/octet-stream" },
    { name: "Content-Length", value: "8388608" }
  ]
}, context.peekRequestHeaders("large-binary-playback-api"));

const largeBinaryResources = vm.runInContext("resourceByTab.get(163)", context);
assert.equal(largeBinaryResources.length, 1);
assert.equal(largeBinaryResources[0].kind, "video");
assert.equal(largeBinaryResources[0].content_length, 8388608);
assert.equal(largeBinaryResources[0].request_headers.Referer, "https://course.example.com/lesson");
assert.equal(largeBinaryResources[0].request_headers["X-Requested-With"], "XMLHttpRequest");
assert.equal(largeBinaryResources[0].label, "VIDEO");

context.rememberRequestHeaders({
  requestId: "streaming-1",
  url: "https://cdn.example.com/live/play?id=long",
  type: "media",
  requestHeaders: [
    { name: "Range", value: "bytes=0-" },
    { name: "Referer", value: "https://course.example.com/lesson" }
  ]
});
context.recordResponseMedia({
  requestId: "streaming-1",
  tabId: 17,
  url: "https://cdn.example.com/live/play?id=long",
  type: "media",
  method: "GET",
  statusCode: 206,
  frameId: 4,
  documentUrl: "https://course.example.com/player",
  initiator: "https://course.example.com",
  timeStamp: Date.now(),
  responseHeaders: [
    { name: "Content-Type", value: "application/octet-stream" },
    { name: "Content-Range", value: "bytes 0-1048575/8388608" },
    { name: "Accept-Ranges", value: "bytes" }
  ]
}, context.peekRequestHeaders("streaming-1"));

const earlyResources = vm.runInContext("resourceByTab.get(17)", context);
assert.equal(earlyResources.length, 1);
assert.equal(earlyResources[0].kind, "video");
assert.equal(earlyResources[0].status_code, 206);
assert.equal(earlyResources[0].request_headers.Range, "bytes=0-");
assert.equal(earlyResources[0].headers["content-range"], "bytes 0-1048575/8388608");

context.rememberRequestHeaders({
  requestId: "xhr-stream-1",
  url: "https://cdn.example.com/api/chunk?id=xhr",
  type: "xmlhttprequest",
  requestHeaders: [
    { name: "Range", value: "bytes=1048576-" },
    { name: "Referer", value: "https://course.example.com/lesson" },
    { name: "Accept", value: "*/*" }
  ]
});
context.recordResponseMedia({
  requestId: "xhr-stream-1",
  tabId: 18,
  url: "https://cdn.example.com/api/chunk?id=xhr",
  type: "xmlhttprequest",
  method: "GET",
  statusCode: 206,
  frameId: 4,
  documentUrl: "https://course.example.com/player",
  initiator: "https://course.example.com",
  timeStamp: Date.now(),
  responseHeaders: [
    { name: "Content-Type", value: "application/octet-stream" },
    { name: "Content-Range", value: "bytes 1048576-2097151/8388608" }
  ]
}, context.peekRequestHeaders("xhr-stream-1"));

const xhrResources = vm.runInContext("resourceByTab.get(18)", context);
assert.equal(xhrResources.length, 1);
assert.equal(xhrResources[0].kind, "video");
assert.equal(xhrResources[0].request_type, "xmlhttprequest");
assert.equal(xhrResources[0].request_headers.Range, "bytes=1048576-");
assert.equal(xhrResources[0].headers["content-range"], "bytes 1048576-2097151/8388608");

context.rememberRequestHeaders({
  requestId: "opaque-video-fetch",
  url: "https://cdn.example.com/opaque/9fa31b7c",
  type: "fetch",
  requestHeaders: [
    { name: "Accept", value: "video/mp4,video/*;q=0.9,*/*;q=0.1" },
    { name: "Sec-Fetch-Dest", value: "video" },
    { name: "Referer", value: "https://course.example.com/lesson" }
  ]
});
context.recordResponseMedia({
  requestId: "opaque-video-fetch",
  tabId: 181,
  url: "https://cdn.example.com/opaque/9fa31b7c",
  type: "fetch",
  method: "GET",
  statusCode: 200,
  frameId: 4,
  documentUrl: "https://course.example.com/player",
  initiator: "https://course.example.com",
  timeStamp: Date.now(),
  responseHeaders: [
    { name: "Content-Type", value: "application/octet-stream" },
    { name: "Content-Length", value: "5242880" }
  ]
}, context.peekRequestHeaders("opaque-video-fetch"));

const opaqueVideoResources = vm.runInContext("resourceByTab.get(181)", context);
assert.equal(opaqueVideoResources.length, 1);
assert.equal(opaqueVideoResources[0].kind, "video");
assert.equal(opaqueVideoResources[0].request_type, "fetch");
assert.equal(opaqueVideoResources[0].request_headers.Accept, "video/mp4,video/*;q=0.9,*/*;q=0.1");
assert.equal(opaqueVideoResources[0].request_headers["Sec-Fetch-Dest"], "video");
assert.equal(opaqueVideoResources[0].content_length, 5242880);

context.addResource(19, {
  url: "https://cdn.example.com/hls/segment-0001.ts?token=abc",
  source: "webRequest",
  kind: "fragment",
  mime: "video/mp2t",
  score: 25,
  request_headers: {
    Referer: "https://course.example.com/lesson",
    Range: "bytes=0-"
  }
}, false);
const fragmentResources = vm.runInContext("resourceByTab.get(19)", context);
const guessedManifest = fragmentResources.find(item => item.url === "https://cdn.example.com/hls/master.m3u8?token=abc");
assert.ok(guessedManifest, "expected same-directory HLS manifest guesses for plain .ts segments");
assert.equal(guessedManifest.source, "manifest-guess");
assert.equal(guessedManifest.kind, "hls");
assert.equal(guessedManifest.playback_match, "inferred-from-fragment");
assert.equal(guessedManifest.request_headers.Referer, "https://course.example.com/lesson");
assert.ok(guessedManifest.score <= 72, "manifest guesses must stay below verified direct candidates");

const cookieUrls = context.cookieUrlsForContext(
  {
    page_url: "https://course.example.com/top",
    active_video: {
      src: "blob:https://course.example.com/active",
      frame_url: "https://player.example.com/embed/active"
    },
    frames: [
      { frame_id: 0, page_url: "https://course.example.com/top" },
      { frame_id: 7, page_url: "https://player.example.com/embed/1" },
      { frame_id: 9, page_url: "about:blank" }
    ]
  },
  { url: "https://course.example.com/tab" },
  [
    {
      url: "https://cdn.example.com/live/master.m3u8",
      resolved_url: "https://resolved-media.example.org/final/master.m3u8?token=abc",
      page_url: "https://course.example.com/frame-page",
      frame_url: "https://player.example.com/embed/1",
      initiator: "https://player.example.com",
      blob_url: "blob:https://course.example.com/active",
      request_headers: {
        Referer: "https://player.example.com/embed/1?lesson=42",
        Origin: "https://course.example.com"
      },
      headers: {
        Location: "https://media.example.net/redirected/master.m3u8",
        "content-location": "/relative/media.mp4"
      }
    }
  ]
);

assert.deepEqual(Array.from(cookieUrls), [
  "https://course.example.com/top",
  "https://course.example.com/tab",
  "https://course.example.com",
  "https://player.example.com/embed/active",
  "https://player.example.com/embed/1",
  "https://cdn.example.com/live/master.m3u8",
  "https://resolved-media.example.org/final/master.m3u8?token=abc",
  "https://course.example.com/frame-page",
  "https://player.example.com",
  "https://player.example.com/embed/1?lesson=42",
  "https://media.example.net/redirected/master.m3u8"
]);
