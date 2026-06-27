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
  chrome: {
    webRequest: {
      onBeforeSendHeaders: listener(),
      onHeadersReceived: listener(),
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

const cookieUrls = context.cookieUrlsForContext(
  {
    page_url: "https://course.example.com/top",
    active_video: { src: "blob:https://course.example.com/active" }
  },
  { url: "https://course.example.com/tab" },
  [
    {
      url: "https://cdn.example.com/live/master.m3u8",
      page_url: "https://course.example.com/frame-page",
      frame_url: "https://player.example.com/embed/1",
      initiator: "https://player.example.com",
      blob_url: "blob:https://course.example.com/active",
      request_headers: {
        Referer: "https://player.example.com/embed/1?lesson=42",
        Origin: "https://course.example.com"
      }
    }
  ]
);

assert.deepEqual(Array.from(cookieUrls), [
  "https://course.example.com/top",
  "https://course.example.com/tab",
  "https://course.example.com",
  "https://cdn.example.com/live/master.m3u8",
  "https://course.example.com/frame-page",
  "https://player.example.com/embed/1",
  "https://player.example.com",
  "https://player.example.com/embed/1?lesson=42"
]);
