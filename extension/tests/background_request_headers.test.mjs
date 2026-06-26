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
    url: "https://cdn.example.com/api/player?id=abc",
    type: "xmlhttprequest"
  }, "application/octet-stream"),
  "unknown"
);
assert.ok(
  context.scoreKind("https://cdn.example.com/playback?id=abc", "webRequest", "video") >= 95,
  "expected extensionless browser media requests to rank like video candidates"
);
