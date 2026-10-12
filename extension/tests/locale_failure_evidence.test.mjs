import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import vm from "node:vm";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const {readinessSnapshot, writeFailureEvidence} = require("../../scripts/extension-locale-visual-acceptance.cjs");
const card = {hidden: true, getBoundingClientRect: () => ({toJSON: () => ({width: 0, height: 0})})};
const sandbox = vm.createContext({
  document: {readyState: "complete", documentElement: {lang: "en"}, scripts: [{src: "http://127.0.0.1:1234/extension/sidepanel.js"}],
    querySelector: selector => selector === "#sourcePreviewCard" ? card : null},
  getComputedStyle: () => ({display: "none", visibility: "visible"})
});
const snapshot = () => vm.runInContext(`(${readinessSnapshot.toString()})()`, sandbox);
assert.equal(snapshot().fixture_installed, false);
assert.equal(snapshot().panel_api_installed, false);
sandbox.__localeFixture = {health: "loading", startup: {permissions_reads: 1, storage_reads: 1, health_requests: 1},
  sent: [{type: "get-current-context"}], context: {page: {browser_subtitles: [{text: "fixture"}]}}};
sandbox.chrome = {runtime: {sendMessage() {}}, storage: {local: {}}};
sandbox.__learnnoteSidepanel = {getState: () => ({clientConnected: false, currentContext: null})};
assert.equal(snapshot().extension_api, true);
assert.equal(snapshot().fixture_cues, 1);
assert.equal(snapshot().context_requests, 1);
assert.equal(snapshot().collected_context, false);
assert.equal(snapshot().preview.hidden, true);

const directory = fs.mkdtempSync(path.join(os.tmpdir(), "learnnote-locale-failure-"));
try {
  const error = new Error("Original 12000ms preview timeout");
  const item = {locale: "en-US", width: 768, zoom: 100};
  const args = {out: directory, sourceSha: "a".repeat(40), item, phase: "source-preview", errors: ["sidepanel script error"],
    failedRequests: [{url: "http://127.0.0.1:1234/extension/i18n.js", error: "net::ERR_FAILED"}],
    badResponses: [{url: "http://127.0.0.1:1234/extension/sidepanel.js", status: 503}], error};
  await writeFailureEvidence({...args, page: {
    evaluate: async () => snapshot(),
    screenshot: async () => { throw Error("Screenshot renderer unavailable"); }
  }});
  let evidence = JSON.parse(fs.readFileSync(path.join(directory, "failure.json"), "utf8"));
  assert.deepEqual(evidence.case, item);
  assert.equal(evidence.phase, "source-preview");
  assert.equal(evidence.error.message, error.message);
  assert.equal(evidence.error.stack, error.stack);
  assert.deepEqual(evidence.page_errors, args.errors);
  assert.deepEqual(evidence.failed_requests, args.failedRequests);
  assert.deepEqual(evidence.bad_responses, args.badResponses);
  assert.equal(evidence.readiness.fixture_startup.storage_reads, 1);
  assert.equal(evidence.readiness.collected_context, false);
  assert.equal(evidence.screenshot_error, "Screenshot renderer unavailable");

  await writeFailureEvidence({...args, page: {
    evaluate: async () => { throw Error("Page closed"); },
    screenshot: async () => { throw Error("Page closed"); }
  }});
  evidence = JSON.parse(fs.readFileSync(path.join(directory, "failure.json"), "utf8"));
  assert.equal(evidence.error.message, error.message, "Diagnostic failure cannot replace the acceptance failure");
  assert.equal(evidence.readiness_error, "Page closed");
  assert.equal(evidence.screenshot_error, "Page closed");
} finally { fs.rmSync(directory, {recursive: true, force: true}); }
console.log("Locale failure evidence retains case, phase, startup state, page/asset errors and original failure when diagnostics are unavailable; no browser launched.");
