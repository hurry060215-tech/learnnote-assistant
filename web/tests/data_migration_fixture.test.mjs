import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
const require = createRequire(import.meta.url);
const { PLAN, installBridge, syntheticResponse } = require("../../scripts/data-migration-visual-acceptance.cjs");
assert.equal(PLAN.preview, true); assert.equal(PLAN.file_count, 12); assert(PLAN.changes.length && PLAN.excluded.length && PLAN.external_references.length);
assert.equal(syntheticResponse("/api/tasks").tasks.length, 0); assert.equal(syntheticResponse("/api/model/connection").configured, false);
assert.equal(syntheticResponse("/api/unknown"), undefined);
const previous = globalThis.window;
try {
  globalThis.window = {};
  installBridge(PLAN);
  const api = window.pywebview.api, fixture = window.__migrationFixture;
  assert.equal((await api.data_migration_status()).status, "none");
  fixture.outcome = "failed"; const failed = await api.data_migration_status(); assert.equal(failed.status, "failed"); assert.match(failed.message, /仍保留原配置/);
  fixture.outcome = "scheduled"; assert.match((await api.data_migration_status()).message, /尚无完成记录/);
  fixture.calls = [];
  const value = await api.choose_data_directory(true); assert.deepEqual(value, PLAN); assert.notEqual(value, PLAN);
  assert.deepEqual(fixture.calls, [{ method: "preview", preview: true }]);
  fixture.mode = "held-preview"; let resolved = false;
  const held = api.choose_data_directory(true).then(() => resolved = true); await Promise.resolve(); assert.equal(resolved, false);
  fixture.release(); await held; assert.equal(resolved, true);
  fixture.mode = "preview-conflict"; assert.equal((await api.choose_data_directory(true)).ok, false);
  fixture.applyMode = "conflict"; assert.equal((await api.apply_data_directory(PLAN.token)).ok, false);
  fixture.applyMode = "held-apply"; resolved = false;
  const applied = api.apply_data_directory(PLAN.token).then(result => { resolved = true; return result; });
  await Promise.resolve(); assert.equal(resolved, false); fixture.release(); assert.equal((await applied).restarting, true);
  assert(!fixture.calls.some(call => call.method === "legacy-restart"));
} finally { if (previous === undefined) delete globalThis.window; else globalThis.window = previous; }
const script = readFileSync(new URL("../../scripts/data-migration-visual-acceptance.cjs", import.meta.url), "utf8");
const workflow = readFileSync(new URL("../../.github/workflows/ui-visual.yml", import.meta.url), "utf8");
assert.match(script, /channel: "msedge"/); assert.match(script, /process.platform, "win32"/);
assert.match(script, /\[1280, 1440, 768, 390\]/); assert.match(script, /await page\.screenshot/);
assert.match(script, /#menu/); assert.match(script, /#settings/); assert.match(script, /reducedMotion: "reduce"/);
assert.match(script, /mobile-last-migration-/);
assert.match(workflow, /node scripts\/data-migration-visual-acceptance.cjs build\/data-migration-ui/);
for (const checkout of [workflow.replace(/\r\n/g, "\n"), workflow.replace(/\r?\n/g, "\r\n")]) {
  assert.match(checkout, /            build\/data-migration-ui\r?\n/);
} assert.match(workflow, /retention-days: 14/);
console.log("Migration hosted fixture contract: isolated bridge, held requests, conflicts, shipped menu, Edge matrix and artifact retention passed (browser execution not claimed)");

const { migrationModalFocusIsSafe } = require("../../scripts/data-migration-visual-acceptance.cjs");
const focus = { insideModal: true, rootFallback: false, documentHasFocus: true, activeTag: "BUTTON", open: true, modal: true,
  settingsOpen: true, openDialogs: 2, phase: "preview", backgroundVisible: true, backgroundDisabled: false, backgroundFocusRefused: true };
assert(migrationModalFocusIsSafe(focus));
const chrome = { ...focus, insideModal: false, rootFallback: true, documentHasFocus: false, activeTag: "BODY" };
assert(migrationModalFocusIsSafe(chrome));
for (const change of [{ insideModal: false }, { rootFallback: true }, { open: false }, { modal: false }, { settingsOpen: false },
  { openDialogs: 1 }, { openDialogs: 3 }, { phase: "applying" }, { backgroundVisible: false }, { backgroundDisabled: true }, { backgroundFocusRefused: false }]) {
  assert(!migrationModalFocusIsSafe({ ...focus, ...change }), JSON.stringify(change));
}
assert(!migrationModalFocusIsSafe({ ...chrome, documentHasFocus: true }));
assert(!migrationModalFocusIsSafe({ ...chrome, activeTag: "BUTTON" }));
assert.match(script, /Keyboard navigation must not activate background preview or migration/);
assert.match(script, /Reverse Tab must return from browser chrome/);

assert.match(script, /cleanupFixture\(\{ report: save, context: \(\) => context\?\.close\(\), browser: \(\) => browser\?\.close\(\) \}, primaryError\)/);
const { cleanupFixture } = require("../../scripts/course-upgrade-fixture-helpers.cjs");
const primary = Error("original migration failure"), cleanupOrder = [];
await cleanupFixture(Object.fromEntries(["report", "context", "browser"].map(label => [label, () => { cleanupOrder.push(label); throw Error(label); }])), primary);
assert.deepEqual(cleanupOrder, ["report", "context", "browser"]); assert.equal(primary.message, "original migration failure"); assert.equal(primary.cleanupErrors.length, 3);
