import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const source = await readFile(new URL("../background.js", import.meta.url), "utf8");
const tab = { id: 7, url: "https://course.example.com/lesson" };
const page = { page_url: tab.url, resources: [], browser_subtitles: [] };

function harness({ revokeDuringPairing = false, revokeBeforeRetry = false, granted = true } = {}) {
  let epoch = 0;
  let listener;
  let pairingCalls = 0;
  const sent = [];
  const context = {
    URL, Date, Map, console,
    captureEpoch: () => epoch,
    activateCapture() {},
    clearCaptureLog() { epoch += 1; },
    tabForMessage: async () => tab,
    collectPageData: async () => page,
    loadCaptureLog: async () => ({ resources: [] }),
    mergeAndRankResources: resources => resources || [],
    buildSourceIdentity: () => ({}),
    sourceIdentityMatches: () => true,
    bestPageTitle: () => "Test lesson",
    cookiePartitionKeysForContext: async () => [],
    cookieUrlsForContext: () => [],
    cookiesForUrls: async () => [],
    resourceByTab: new Map(), pageStateByTab: new Map(), activeCaptureUntilByTab: new Map(),
    biliSubtitleCache: new Map(), biliSubtitleRequests: new Map(),
    pairingHeaders: async () => {
      pairingCalls += 1;
      if (revokeDuringPairing) await context.revokeSitePermissionCaches("https://*.example.com/*");
      return {};
    },
    fetch: async (url, options) => {
      sent.push({ url, options });
      return { ok: !revokeBeforeRetry, status: revokeBeforeRetry ? 503 : 200, json: async () => ({ task_id: "task1", report: { ready: true } }) };
    },
    setTimeout(callback) {
      if (revokeBeforeRetry) context.revokeSitePermissionCaches("https://*.example.com/*").then(callback);
      else callback();
    },
    chrome: {
      permissions: { contains: async () => granted },
      tabs: { query: async () => [tab] },
      runtime: { sendMessage: async () => {}, onMessage: { addListener(callback) { listener = callback; } } }
    }
  };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf("function backendErrorMessage("), source.indexOf("function mediaKindFromMime(")), context);
  vm.runInContext(source.slice(source.indexOf("function normalizePermissionOrigin("), source.indexOf("chrome.permissions?.onRemoved")), context);
  vm.runInContext(source.slice(source.indexOf("chrome.runtime.onMessage.addListener((message, sender, sendResponse)")), context);
  return {
    context, sent,
    get pairingCalls() { return pairingCalls; },
    send(type) { return new Promise(resolve => listener({ type, page, resource: { url: "https://cdn.example.com/video.mp4" }, resources: [] }, {}, resolve)); }
  };
}

const patterns = harness();
assert.equal(patterns.context.normalizePermissionOrigin("https://*.example.com/*"), "https://*.example.com/*");
assert.equal(patterns.context.permissionPatternMatchesUrl("https://*.example.com/*", tab.url), true);
assert.equal(patterns.context.permissionPatternMatchesUrl("https://*.example.com/*", "https://example.com:8443/lesson"), true);
assert.equal(patterns.context.permissionPatternMatchesUrl("https://*.example.com/*", "https://example.com.evil.test/lesson"), false);
assert.equal(patterns.context.permissionPatternMatchesUrl("https://*.example.com/*", "http://course.example.com/lesson"), false);
assert.equal(patterns.context.normalizePermissionOrigin("https://*example.com/*"), "");

for (const type of ["start-current-task", "preflight-current-resource", "preflight-current-page"]) {
  const allowed = harness();
  assert.equal((await allowed.send(type)).error, undefined, `${type}: granted handoff succeeds`);
  assert.equal(allowed.sent.length, 1);
  const denied = harness({ granted: false });
  assert.equal((await denied.send(type)).code, "site_permission_required");
  assert.equal(denied.sent.length, 0);
  assert.equal(denied.pairingCalls, 0);
  const revoked = harness({ revokeDuringPairing: true });
  assert.equal((await revoked.send(type)).code, "site_permission_required", `${type}: pairing must not revive a revoked capture`);
  assert.equal(revoked.sent.length, 0);
}
const retry = harness({ revokeBeforeRetry: true });
assert.equal((await retry.send("start-current-task")).code, "site_permission_required");
assert.equal(retry.sent.length, 1, "a failed handoff must not retry after revocation, even when the site is granted again");
console.log("Wildcard revocation and permission epochs block task/preflight pairing and retry races");
