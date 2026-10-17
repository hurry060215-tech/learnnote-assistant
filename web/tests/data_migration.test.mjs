import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const source = readFileSync(new URL("../data-migration.js", import.meta.url), "utf8");
const { migrationPreview, createDataMigration, installDataMigration } = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
const plan = (token = "review-1") => ({ ok: true, preview: true, token, source: "C:\\Synthetic\\数据", path: "D:\\Synthetic\\新目录", file_count: 12, byte_count: 2048,
  changes: [{ file: "tasks/fixture/task.json", field: "media_path", before: "C:\\Synthetic\\数据\\tasks\\fixture\\video.mp4", after: "D:\\Synthetic\\新目录\\tasks\\fixture\\video.mp4" }],
  excluded: [{ path: "secrets", reason: "credentials" }], external_references: [{ file: "tasks/fixture/task.json", field: "external", value: "E:\\Synthetic\\outside.mp4", reason: "outside_source" }] });
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
function harness(overrides = {}) {
  const calls = [], renders = [], api = {
    choose_data_directory: async (...args) => { calls.push(["preview", ...args]); return plan(); },
    apply_data_directory: async (...args) => { calls.push(["apply", ...args]); return { ok: true, restarting: true, message: "scheduled" }; },
    restart_application: () => { throw Error("Legacy restart must never run"); }, ...overrides,
  };
  const controller = createDataMigration({ bridge: () => api, render: state => renders.push(state) });
  return { controller, api, calls, renders, last: () => renders.at(-1) };
}
{
  const h = harness(); await h.controller.confirm(); assert.equal(h.calls.length, 0);
  await h.controller.start(); assert.equal(h.last().phase, "preview"); assert.deepEqual(h.calls, [["preview", true]]);
  assert.deepEqual(h.last().plan, plan()); assert.match(h.last().message, /尚未复制/);
  assert.equal(h.controller.cancel(), true); await h.controller.confirm(); assert.equal(h.calls.length, 1);
  await h.controller.start(); await h.controller.confirm(); await h.controller.confirm(); await h.controller.start();
  assert.deepEqual(h.calls, [["preview", true], ["preview", true], ["apply", "review-1"]]);
  assert.equal(h.last().phase, "restarting"); assert.match(h.last().message, /尚不能确认复制完成/); assert.equal(h.controller.cancel(), false);
}
{
  const held = deferred(), h = harness({ choose_data_directory: () => held.promise });
  const pending = h.controller.start(); assert.equal(h.last().phase, "selecting"); h.controller.cancel(); held.resolve(plan()); await pending;
  assert.equal(h.last().phase, "closed"); await h.controller.confirm(); assert.deepEqual(h.calls, []);
}
{
  const old = deferred(), h = harness({ choose_data_directory: () => old.promise });
  const first = h.controller.start(); h.api.choose_data_directory = async () => plan("new-token");
  await h.controller.start(); old.resolve(plan("old-token")); await first;
  assert.equal(h.last().plan.token, "new-token"); await h.controller.confirm(); assert.deepEqual(h.calls, [["apply", "new-token"]]);
}
{
  const old = deferred(), h = harness({ choose_data_directory: () => old.promise });
  const first = h.controller.start(); h.controller.cancel(); h.api.choose_data_directory = async () => plan("fresh"); await h.controller.start();
  old.reject(Error("stale failure")); await first; assert.equal(h.last().phase, "preview"); assert.equal(h.last().plan.token, "fresh");
}
for (const result of [{ ok: false, code: "destination_conflict", message: "目标目录已发生变化，不能覆盖。" }, { ok: true }, null]) {
  const h = harness({ apply_data_directory: async token => { h.calls.push(["apply", token]); return result; } });
  await h.controller.start(); await h.controller.confirm(); assert.equal(h.last().phase, "error"); assert.equal(h.last().plan, null);
  assert(!h.renders.some(state => state.phase === "restarting")); await h.controller.confirm(); assert.equal(h.calls.filter(call => call[0] === "apply").length, 1);
  await h.controller.start(); assert.equal(h.last().phase, "preview");
}
{
  const applying = deferred(), h = harness({ apply_data_directory: token => { h.calls.push(["apply", token]); return applying.promise; } });
  await h.controller.start(); const pending = h.controller.confirm(); assert.equal(h.last().phase, "applying");
  assert.equal(h.controller.cancel(), false); await h.controller.confirm(); await h.controller.start();
  assert.deepEqual(h.calls, [["preview", true], ["apply", "review-1"]]);
  applying.reject(Error("bridge disconnected")); await pending; assert.equal(h.last().phase, "error"); assert.match(h.last().message, /重新预览/);
}
for (const result of [{ cancelled: true }, { ok: true, unchanged: true }]) {
  const h = harness({ choose_data_directory: async () => result }); await h.controller.start(); await h.controller.confirm();
  assert.equal(h.calls.length, 0); assert.equal(h.last().phase, result.cancelled ? "closed" : "unchanged");
}
for (const invalid of [null, {}, { ...plan(), preview: false }, { ...plan(), token: "" }, { ...plan(), path: "" }, { ...plan(), file_count: -1 },
  { ...plan(), byte_count: Infinity }, { ...plan(), excluded: null }, { ...plan(), external_references: null }, { ...plan(), changes: [{ file: "x", field: "y" }] }]) {
  assert.throws(() => migrationPreview(invalid));
  const h = harness({ choose_data_directory: async () => invalid }); await h.controller.start(); await h.controller.confirm();
  assert.equal(h.last().phase, "error"); assert.equal(h.calls.length, 0);
}
{
  const original = plan(), reviewed = migrationPreview(original); original.changes[0].after = "mutated";
  assert.notEqual(reviewed.changes[0].after, "mutated", "Preview snapshot must not follow later bridge object mutations");
  const renders = [], c = createDataMigration({ bridge: () => null, render: state => renders.push(state) });
  await c.start(); assert.equal(renders.at(-1).phase, "error"); assert.match(renders.at(-1).message, /桌面客户端/);
}
{
  let blocked = true, applied = 0;
  const states = [], controller = createDataMigration({ bridge: () => ({ choose_data_directory: async () => plan(), apply_data_directory: async () => { applied++; return { ok: true, restarting: true }; } }),
    render: state => states.push(state), beforeConfirm: () => blocked ? "unsaved edits" : "" });
  await controller.start(); await controller.confirm(); assert.equal(applied, 0); assert.equal(controller.phase, "preview"); assert.equal(states.at(-1).message, "unsaved edits");
  blocked = false; await controller.confirm(); assert.equal(applied, 1);
}
// Small lifecycle double, not a replacement for the actual Edge screenshots.
class Element extends EventTarget {
  constructor(doc) { super(); this.doc = doc; this.nodes = new Map(); this.dataset = {}; this.attributes = {}; this.open = false; this.disabled = false; }
  querySelector(key) { if (!this.nodes.has(key)) this.nodes.set(key, new Element(this.doc)); return this.nodes.get(key); }
  setAttribute(key, value) { this.attributes[key] = value; }
  focus() { this.doc.activeElement = this; }
  showModal() { this.open = true; }
  close() { if (!this.open) return; this.open = false; queueMicrotask(() => this.dispatchEvent(new Event("close"))); }
}
{
  const doc = { createElement() { const node = new Element(doc); doc.dialog = node; return node; }, body: { append() {} } };
  const button = new Element(doc), settingsDialog = new Element(doc); settingsDialog.open = true;
  let mode = "cancelled", applyCount = 0, held;
  const api = { choose_data_directory: async () => mode === "cancelled" ? { cancelled: true } : plan(),
    apply_data_directory: async () => { applyCount++; return held.promise; } };
  const c = installDataMigration({ button, settingsDialog, document: doc, bridge: () => api });
  await button.onclick(); assert.equal(button.disabled, false); assert.equal(doc.dialog.open, false);
  mode = "preview"; await button.onclick(); const find = selector => doc.dialog.querySelector(selector);
  assert.equal(doc.dialog.open, true); assert.equal(find("[data-migration-source]").textContent, plan().source);
  assert.equal(find("[data-migration-changes]").querySelector("pre").textContent, JSON.stringify(plan().changes, null, 2));
  assert.equal(doc.activeElement, find("[data-migration-close]"));
  const escape = new Event("cancel", { cancelable: true }); doc.dialog.dispatchEvent(escape);
  assert(escape.defaultPrevented); assert.equal(c.phase, "closed"); assert.equal(doc.activeElement, button); assert.equal(applyCount, 0);
  // An older native close event must not cancel the newly opened dialog.
  await button.onclick(); await Promise.resolve(); assert.equal(c.phase, "preview");
  held = deferred(); const pending = find("[data-migration-confirm]").onclick();
  assert.equal(find("[data-migration-cancel]").disabled, true); assert.equal(find("[data-migration-confirm]").disabled, true);
  doc.dialog.dispatchEvent(new Event("cancel", { cancelable: true })); assert.equal(doc.dialog.open, true); assert.equal(applyCount, 1);
  held.resolve({ ok: false, message: "destination conflict" }); await pending;
  assert.equal(find("[data-migration-confirm]").hidden, true); assert.equal(find("[data-migration-retry]").hidden, false);
  assert.equal(doc.activeElement, find("#dataMigrationStatus"));
  await find("[data-migration-retry]").onclick(); assert.equal(c.phase, "preview");
  settingsDialog.close(); await Promise.resolve(); assert.equal(c.phase, "closed"); assert.equal(button.disabled, false);
}
// Real browser gate verifies rendering/focus. This guard ties its entry to the
// shipped settings control and prevents quietly restoring the legacy apply path.
const settings = readFileSync(new URL("../desk-settings.js", import.meta.url), "utf8");
assert.match(settings, /import \{ installDataMigration \} from "\/web\/data-migration.js"/);
assert.match(settings, /installDataMigration\(\{ button: \$\("changeSettingsFolder"\), settingsDialog: dialog, beforeConfirm:/);
assert(!settings.includes("choose_data_directory(true)")); assert(!source.includes("restart_application"));
assert.match(source, /\.textContent = JSON.stringify\(values, null, 2\)/);
assert.match(source, /event.preventDefault\(\); dismiss\(\)/);
console.log("Migration preview: read-only selection, exact plan, cancel, latest request, one-use confirmation, conflict, bridge failure and truthful restart passed");
