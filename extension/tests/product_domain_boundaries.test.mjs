import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import { installExtensionScriptLoader } from "./helpers/script-loader.mjs";
import { cookiePort, domainSnapshot, fixturePageUrl } from "./helpers/product-domain-scenarios.mjs";

const context = vm.createContext({ URL, URLSearchParams, TextEncoder, TextDecoder, Uint8Array, ArrayBuffer, atob, Date });
installExtensionScriptLoader(context);
context.importScripts("capture-classification.js", "source-identity.js", "request-context.js", "cookie-context.js", "backend-transport.js", "content-media-hints.js");
for (const name of ["LearnNoteSourceIdentity", "LearnNoteRequestContext", "LearnNoteCookieContext", "LearnNoteBackendTransport", "LearnNoteContentMediaHints"]) assert.ok(Object.isFrozen(context[name]), name);
assert.equal(context.chrome, undefined);
assert.equal(context.fetch, undefined);
assert.equal(context.document, undefined);
let cookieReads = 0;
const cookieAdapter = context.LearnNoteCookieContext.createCookieContext({ getCookies() { cookieReads++; return cookiePort(); } });
let pageUrl = fixturePageUrl;
const hints = context.LearnNoteContentMediaHints.createMediaHints({ getPageUrl: () => pageUrl });
assert.equal(cookieReads, 0, "constructing a domain must not start capture or read cookies");
const actual = await domainSnapshot({ identity: context.LearnNoteSourceIdentity, request: context.LearnNoteRequestContext, cookies: { ...context.LearnNoteCookieContext, ...cookieAdapter }, hints });
const expected = JSON.parse(await readFile(new URL("./fixtures/product-domain-snapshot-v1.json", import.meta.url), "utf8"));
assert.equal(expected.baseline, "b590e55169cebd4ca34a7312b16fef1aa3ecec01");
assert.deepEqual(JSON.parse(JSON.stringify(actual)), expected.snapshot);
pageUrl = "https://new.example.test/other/player";
assert.equal(hints.absoluteUrl("../media.mp4"), "https://new.example.test/media.mp4", "navigation reads the current injected URL rather than a stale factory snapshot");
assert.equal(context.LearnNoteCaptureClassification.isSubtitleEndpointUrl("/captions", pageUrl), true);
assert.equal(context.LearnNoteCaptureClassification.isClearlyNonMediaAssetUrl("/cover.png", pageUrl), true);
assert.equal(context.LearnNoteCaptureClassification.inferManifestUrl("/master.m3u8/segment.ts", pageUrl), "https://new.example.test/master.m3u8");
assert.equal(context.LearnNoteRequestContext.requestBodyFromRaw([{ bytes: new Uint8Array(65537).buffer }]), null);
assert.equal(context.LearnNoteRequestContext.requestBodyFromFormData({ field: "x".repeat(65537) }), null);
assert.deepEqual(JSON.parse(JSON.stringify(context.LearnNoteRequestContext.safePersistedRequestBody({ method: "POST", kind: "video", request_body: { type: "bytes", content: "fixture" } }))), { type: "dropped", reason: "too_large_or_binary" });
assert.deepEqual(JSON.parse(JSON.stringify(await context.LearnNoteCookieContext.createCookieContext({ getCookies: () => ({ getAll: async () => { throw Error("denied"); } }) }).cookiesForUrls([fixturePageUrl]))), []);

const requests = [], waits = [], writes = [];
let now = 1000, hasFetch = true, pairing = {}, responseCode = 200;
const transport = context.LearnNoteBackendTransport.createBackendTransport({
  getStorage: () => ({ local: {
    async get(key) { return Array.isArray(key) ? { backendUrl: "https://remote.example.test" } : { pairingTokens: pairing }; },
    async set(value) { writes.push(value); pairing = value.pairingTokens; }
  } }),
  fetch: async (url, options) => {
    requests.push({ url, options });
    if (url.endsWith("/api/pairing/issue")) return { ok: true, json: async () => ({ token: "synthetic-token", expires_at: 100 }) };
    return { ok: responseCode < 400, status: responseCode, json: async () => responseCode < 400 ? { ok: true, extension_connected: true, protocol_version: 1 } : { detail: { message: "fixture rejection" } } };
  },
  hasFetch: () => hasFetch,
  getExtensionVersion: () => "0.0.0-fixture",
  now: () => now,
  setTimeout: (resolve, delay) => { waits.push(delay); resolve(); return 0; },
  clearTimeout() {}, createAbortController: () => null,
  defaultBackendUrl: "http://127.0.0.1:8765", protocolVersion: 1
});
assert.equal(requests.length, 0, "transport construction must not pair or send a heartbeat");
assert.equal(await transport.storedBackendUrl(), "http://127.0.0.1:8765");
const result = await transport.postJsonWithRetry("http://127.0.0.1:8765/api/tasks", { fixture: true }, "fallback");
assert.equal(result.ok, true);
assert.equal(writes.length, 1);
assert.equal(requests.length, 2);
assert.equal(requests[1].options.headers["X-LearnNote-Pairing"], "synthetic-token");
assert.equal(requests[1].options.body, '{"fixture":true}');
await transport.pairingHeaders("http://127.0.0.1:8765/", {});
assert.equal(requests.length, 2, "valid cached pairing is reused for the same backend only");
now = 90000;
await transport.pairingHeaders("http://127.0.0.1:8765", {});
assert.equal(requests.length, 3, "pairing refresh retains the existing 15-second margin");
now = 1000; responseCode = 503;
let permissionChecks = 0;
const before = requests.length;
const blocked = await transport.postJsonWithRetry("http://127.0.0.1:8765/api/tasks", {}, "fallback", 2, () => ++permissionChecks === 2 ? { ok: false, code: "site_permission_required" } : null);
assert.equal(blocked.code, "site_permission_required");
assert.equal(requests.length, before + 1, "revocation before retry prevents a second POST");
assert.equal(permissionChecks, 2);
assert.equal(waits.at(-1), 250);
responseCode = 422;
const failed = await transport.postJsonWithRetry("http://127.0.0.1:8765/api/tasks", {}, "fallback");
assert.equal(failed.error, "fixture rejection");
assert.equal(failed.status, 422);
hasFetch = false;
const prior = requests.length;
assert.equal(await transport.sendBackendHeartbeat("http://127.0.0.1:8765"), false);
assert.equal(requests.length, prior);
console.log("Product-domain baseline snapshot, pure inputs, adapter failure and permission/retry boundaries pass");
