import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import vm from "node:vm";
import {createHash} from "node:crypto";
import {createRequire} from "node:module";
const require = createRequire(import.meta.url);
const {FIXTURE, installFixtures, matrix} = require("../../scripts/extension-locale-visual-acceptance.cjs");
const {STORE_FIXTURE, STORE_COPY, artworkHtml, fileEvidence, verifyStoreCandidates} = require("../../scripts/extension-store-visual-fixtures.cjs");

async function fixtureReplies(fixture, locale) {
  let realFetches = 0;
  const sandbox = {URL, Response, location: {href: "http://127.0.0.1:1234/extension/sidepanel.html", origin: "http://127.0.0.1:1234"}, fetch: () => { realFetches += 1; throw Error("No real fetch allowed in offline test"); }};
  vm.createContext(sandbox);
  vm.runInContext(`(${installFixtures.toString()})(${JSON.stringify({fixture, locale, catalog: {}})})`, sandbox);
  sandbox.__localeFixture.connect();
  const health = await (await sandbox.fetch("http://127.0.0.1:8765/health")).json();
  const note = await (await sandbox.fetch("http://127.0.0.1:8765/api/tasks/locale-fixture/note")).text();
  const transcript = await (await sandbox.fetch("http://127.0.0.1:8765/api/tasks/locale-fixture/transcript")).json();
  const context = await sandbox.chrome.runtime.sendMessage({type: "get-current-context"});
  await assert.rejects(() => sandbox.fetch("https://example.com/private"), /Unexpected external request/);
  assert.equal(realFetches, 0);
  return JSON.parse(JSON.stringify({health, note, transcript, context}));
}

assert.equal(matrix().length, 18);
const stress = await fixtureReplies(FIXTURE, "en-US");
assert.equal(stress.health.default_llm_model, "Synthetic-long-model-name-for-layout-acceptance");
assert.equal(stress.note, FIXTURE.note);
assert.equal(stress.transcript.segments.length, 12);
assert.equal(stress.transcript.segments[0].text, `${FIXTURE.subtitle} 1`);
assert.deepEqual(stress.context.page.chapters, [{title: "原文章节一", start: 0, end: 60}, {title: "原文章节二", start: 60, end: 120}]);
const before = JSON.stringify(STORE_FIXTURE);
const english = await fixtureReplies(STORE_FIXTURE, "en-US");
const chinese = await fixtureReplies(STORE_FIXTURE, "zh-CN");
assert.deepEqual(english, chinese, "Switching UI language must preserve all authored course content");
assert.equal(JSON.stringify(STORE_FIXTURE), before);
assert.equal(english.note, STORE_FIXTURE.note);
assert.equal(english.health.default_llm_model, "Demo model (simulated)");
assert.deepEqual(english.transcript.segments, STORE_FIXTURE.cues);

// PNG dimensions/hash validation is independent of browser rendering. The header
// below is only test data; it is never emitted as a screenshot or accepted image.
function pngHeader(width, height) {
  const bytes = Buffer.alloc(24);
  Buffer.from([137,80,78,71,13,10,26,10]).copy(bytes);
  bytes.write("IHDR", 12); bytes.writeUInt32BE(width, 16); bytes.writeUInt32BE(height, 20);
  return bytes;
}
const source = pngHeader(576, 320), result = pngHeader(576, 400);
assert.throws(() => artworkHtml("en-US", "summary", source, pngHeader(576, 900)), /legible/);
for (const locale of Object.keys(STORE_COPY)) for (const state of ["summary", "transcript"]) {
  const html = artworkHtml(locale, state, source, result);
  assert(html.includes(STORE_COPY[locale].disclosure));
  assert(html.includes("data:image/png;base64,"));
  assert(!html.includes("Synthetic-long-model-name") && !html.includes("用户笔记保持原文"));
  assert(!/<script|https?:\/\//.test(html), "Artwork must not request scripts or remote assets");
}
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "learnnote-store-fixtures-"));
try {
  const assets = [];
  for (const locale of Object.keys(STORE_COPY)) for (const state of ["summary", "transcript"]) {
    const filename = `store-${locale}-${state}-1280x800.png`, bytes = pngHeader(1280, 800);
    fs.writeFileSync(path.join(temporary, filename), bytes);
    const evidence = fileEvidence(filename, bytes);
    const captures = [`store-source-${locale}.png`, `store-result-${locale}-${state}.png`, `store-full-panel-${locale}-${state}.png`].map(name => {
      fs.writeFileSync(path.join(temporary, name), source);
      return fileEvidence(name, source);
    });
    assets.push({...evidence, locale, state, original_title: STORE_FIXTURE.title, disclosure: STORE_COPY[locale].disclosure, captures});
  }
  const manifest = {status: "candidate-unreviewed", source_sha: "a".repeat(40), fixture_id: STORE_FIXTURE.id, fixture_sha256: createHash("sha256").update(JSON.stringify(STORE_FIXTURE)).digest("hex"), synthetic_data: true, model_called: false, native_extension_installation_tested: false, original_content_identical_across_locales: true, assets};
  const report = {source_sha: manifest.source_sha, passed: true, cases: matrix(), store_candidates: assets.map(asset => asset.filename)};
  fs.writeFileSync(path.join(temporary, "store-candidates.json"), JSON.stringify(manifest));
  fs.writeFileSync(path.join(temporary, "report.json"), JSON.stringify(report));
  assert.equal(verifyStoreCandidates(temporary).assets, 4);
  const assetPath = path.join(temporary, assets[0].filename);
  fs.appendFileSync(assetPath, "changed after capture");
  assert.throws(() => verifyStoreCandidates(temporary), /sha256/);
  fs.writeFileSync(assetPath, pngHeader(1280, 800));
  report.source_sha = "b".repeat(40);
  fs.writeFileSync(path.join(temporary, "report.json"), JSON.stringify(report));
  assert.throws(() => verifyStoreCandidates(temporary));
  report.source_sha = manifest.source_sha; report.passed = false;
  fs.writeFileSync(path.join(temporary, "report.json"), JSON.stringify(report));
  assert.throws(() => verifyStoreCandidates(temporary), /must pass/);
} finally { fs.rmSync(temporary, {recursive: true, force: true}); }
console.log("Store fixtures: original-language content, isolated stress fixtures, truthful artwork, and artifact provenance checks passed (no browser launched).");
