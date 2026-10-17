import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
const settings = readFileSync(new URL("../desk-settings.js", import.meta.url), "utf8");
const statusSource = readFileSync(new URL("../data-migration-status.js", import.meta.url), "utf8");
const { createMigrationStatus } = await import("data:text/javascript;base64," + Buffer.from(statusSource).toString("base64"));
const loadSource = settings.slice(settings.indexOf("  let loadGeneration = 0;"), settings.indexOf("  const oldProviderChange"));
const openSource = settings.slice(settings.indexOf('  const oldOpen = $("settings").onclick;'), settings.indexOf('  $("savePreferences").textContent = "保存模型连接";'));
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const nodes = new Map(), $ = id => { if (!nodes.has(id)) nodes.set(id, { value: "", textContent: "" }); return nodes.get(id); };
const requests = [], statusReads = [], preferenceReads = [], renders = [];
const migrationStatus = createMigrationStatus({ bridge: () => ({ data_migration_status() {
  requests.push("native-status"); const read = deferred(); statusReads.push(read); return read.promise;
} }), render: value => renders.push(value) });
$("settings").onclick = () => requests.push("dialog-open");
const context = vm.createContext({ $, migrationStatus, state: { health: { data_paths: { root: "C:\\Synthetic\\current" } }, processing: {} },
  api(path) { requests.push(path); const read = deferred(); preferenceReads.push(read); return read.promise; },
  processingSections: [], panes: {}, pref: {}, appearance() {}, fill() {}, saved() {}, dirty() { return false; }, loadModelRoute() {},
  location: { origin: "http://127.0.0.1:8765" },
});
vm.runInContext(loadSource + openSource, context);
const initial = vm.runInContext("load()", context);
assert.deepEqual(requests, ["native-status", "/api/preferences"], "Native receipt reading begins before the asynchronous preferences API");
statusReads[0].resolve({ ok: true, status: "failed", message: "原配置已核实保留。" }); await Promise.resolve(); await Promise.resolve();
assert.equal(renders.at(-1).message, "原配置已核实保留。", "A slow preferences response must not delay migration failure visibility");
preferenceReads[0].reject(Error("preferences unavailable")); await initial;
assert.equal(renders.at(-1).status, "failed"); assert.equal($("settingsDataRoot").textContent, "C:\\Synthetic\\current");
$("settings").onclick(); $("settings").onclick();
assert.deepEqual(requests.slice(2), ["dialog-open", "native-status", "/api/preferences", "dialog-open", "native-status", "/api/preferences"]);
statusReads[2].resolve({ ok: true, status: "scheduled", message: "尚无完成记录。" }); await Promise.resolve(); await Promise.resolve();
statusReads[1].resolve({ ok: true, status: "complete", source: "old", path: "new", receipt: "receipt", message: "旧响应" });
await Promise.resolve(); await Promise.resolve(); assert.equal(renders.at(-1).status, "scheduled", "Older settings-open status cannot replace the newest receipt");
for (const read of preferenceReads.slice(1)) read.resolve({ task_options: {} }); await Promise.resolve(); await Promise.resolve();
const installation = settings.indexOf('const migrationStatus = installMigrationStatus('), initialLoad = settings.lastIndexOf('  load();');
assert(installation >= 0 && installation < initialLoad, "The status reader must exist before installation invokes load");
assert.match(settings.slice(initialLoad), /^  load\(\);\s*\}/);
assert(!statusSource.includes("<textarea"), "Read-only receipt display must not participate in settings dirty tracking");
console.log("Migration settings loader: installed-before-load, native read before preferences, API failure isolation, every-open refresh and stale response ordering passed");
