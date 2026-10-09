import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import { installExtensionScriptLoader } from "./helpers/script-loader.mjs";

const listener = () => ({ addListener() {} });
const context = vm.createContext({
  URL,
  chrome: {
    webRequest: Object.fromEntries([
      "onBeforeSendHeaders", "onBeforeRequest", "onHeadersReceived",
      "onBeforeRedirect", "onCompleted", "onErrorOccurred"
    ].map(name => [name, listener()])),
    tabs: { onRemoved: listener(), onUpdated: listener() },
    action: { onClicked: listener() },
    runtime: { onMessage: listener() }
  }
});
installExtensionScriptLoader(context);
vm.runInContext(await readFile(new URL("../background.js", import.meta.url), "utf8"), context);

const ordinaryHeaders = {
  Referer: "https://lesson.invalid/course",
  Origin: "https://lesson.invalid",
  Accept: "application/vnd.apple.mpegurl",
  Range: "bytes=0-",
  "User-Agent": "Offline fixture"
};
const requestHeaders = Object.freeze({
  ...ordinaryHeaders,
  Authorization: "Bearer SENTINEL_UPPER",
  authorization: "Bearer SENTINEL_LOWER",
  aUtHoRiZaTiOn: "Bearer SENTINEL_MIXED"
});
const headerSnapshot = JSON.stringify(requestHeaders);
let tabId = 1;
const resources = id => vm.runInContext(`resourceByTab.get(${id}) || []`, context);
const cases = [
  ["https://media.invalid/play", "https://media.invalid/master.m3u8", true],
  ["https://MEDIA.invalid:443/play", "https://media.invalid/master.m3u8", true],
  ["http://media.invalid/play", "http://media.invalid:80/master.m3u8", true],
  ["https://media.invalid:8443/play", "https://media.invalid:8443/master.m3u8", true],
  ["https://media.invalid/play", "https://cdn.invalid/master.m3u8", false],
  ["https://media.invalid/play", "https://cdn.media.invalid/master.m3u8", false],
  ["https://media.invalid/play", "http://media.invalid/master.m3u8", false],
  ["http://media.invalid/play", "https://media.invalid/master.m3u8", false],
  ["https://media.invalid/play", "https://media.invalid:8443/master.m3u8", false],
  ["", "https://media.invalid/master.m3u8", false],
  ["/play", "https://media.invalid/master.m3u8", false],
  ["not a URL", "https://media.invalid/master.m3u8", false],
  ["https:///media.invalid/play", "https://media.invalid/master.m3u8", false],
  ["https://media.invalid:bad/play", "https://media.invalid/master.m3u8", false],
  ["https://fixture@media.invalid/play", "https://media.invalid/master.m3u8", false],
  ["https://media.invalid/play", "https://fixture@media.invalid/master.m3u8", false],
  ["https://media.invalid:\n443/play", "https://media.invalid/master.m3u8", false],
  ["blob:https://media.invalid/play", "https://media.invalid/master.m3u8", false],
  ["https://media.invalid/play", "https://media.invalid:bad/master.m3u8", false],
  ["https://media.invalid/play", "/master.m3u8", false],
  ["https://media.invalid/play", "https:///media.invalid/master.m3u8", false],
  ["https://media.invalid/play", "data:application/vnd.apple.mpegurl,master.m3u8", false]
];
for (const [url, resolvedUrl, keepAuthorization] of cases) {
  const resource = Object.freeze({ url, resolved_url: resolvedUrl, request_headers: requestHeaders });
  const original = JSON.stringify(resource);
  context.addResolvedMediaResource(tabId, resource);
  const candidate = resources(tabId++).find(item => item.url === resolvedUrl);
  assert.ok(candidate, `Missing resolved candidate for ${url} -> ${resolvedUrl}`);
  assert.deepEqual({ ...candidate.request_headers }, keepAuthorization ? requestHeaders : ordinaryHeaders);
  assert.equal(JSON.stringify(resource), original);
  assert.equal(JSON.stringify(requestHeaders), headerSnapshot);
  assert.notEqual(candidate.request_headers, requestHeaders);
}

for (const record of [context.recordResponseMedia, context.recordRedirectMedia]) {
  const sourceUrl = "https://lesson.invalid/api/play";
  const targetUrl = "https://cdn.invalid/master.m3u8";
  record({
    tabId, url: sourceUrl, redirectUrl: targetUrl, type: "media", method: "GET",
    responseHeaders: [{ name: "Location", value: targetUrl }]
  }, requestHeaders);
  const captured = resources(tabId++);
  assert.deepEqual({ ...captured.find(item => item.url === sourceUrl).request_headers }, requestHeaders);
  assert.deepEqual({ ...captured.find(item => item.url === targetUrl).request_headers }, ordinaryHeaders);
}

for (const url of [
  "https://media.invalid/master.m3u8/segment.ts",
  "https://media.invalid/video/segment.m4s"
]) {
  context.addResource(tabId, { url, request_headers: requestHeaders }, false);
  const captured = resources(tabId++);
  assert.ok(captured.length > 1);
  for (const item of captured) assert.deepEqual({ ...item.request_headers }, requestHeaders);
}
assert.equal(JSON.stringify(requestHeaders), headerSnapshot);
console.log("Resolved media Authorization stays within its original HTTP origin; source evidence is unchanged");
