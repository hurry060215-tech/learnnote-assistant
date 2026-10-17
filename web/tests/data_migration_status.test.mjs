import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const source = readFileSync(new URL("../data-migration-status.js", import.meta.url), "utf8");
const { migrationOutcome, createMigrationStatus, installMigrationStatus } = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
const result = status => ({ ok: true, status, source: "C:\\Synthetic\\old", path: "D:\\Synthetic\\new", receipt: "C:\\Synthetic\\app\\receipt.json" });
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
assert.equal(migrationOutcome({ ok: true, status: "none" }), null);
assert.match(migrationOutcome(result("complete")).message, /已校验.*已提交/);
assert.match(migrationOutcome(result("failed")).message, /仍保留原配置/);
assert.match(migrationOutcome(result("incomplete")).message, /尚不能确认/);
assert.match(migrationOutcome(result("scheduled")).message, /尚不能确认/);
for (const status of ["complete", "failed", "incomplete", "scheduled"]) {
  const value = { ...result(status), message: "<literal native message>" }, outcome = migrationOutcome(value);
  assert.equal(outcome.message, value.message); assert.deepEqual(JSON.parse(outcome.record), { status, source: value.source, path: value.path, receipt: value.receipt, message: value.message });
}
for (const value of [{ ok: true, status: "complete" }, { ok: true, status: "copying" }, { ok: false, status: "complete" }, null]) assert.throws(() => migrationOutcome(value));
{
  const renders = [], api = {}, controller = createMigrationStatus({ bridge: () => api, render: value => renders.push(value) });
  await controller.refresh(); assert.equal(renders.at(-1), null);
  api.data_migration_status = async () => result("scheduled"); await controller.refresh(); assert.equal(renders.at(-1).status, "scheduled");
  api.data_migration_status = async () => { throw Error("read failed"); }; await controller.refresh();
  assert.equal(renders.at(-1).status, "unknown"); assert.match(renders.at(-1).message, /read failed/); assert.equal(renders.at(-1).record, "");
  api.data_migration_status = async () => ({ ok: false, status: "incomplete", message: "保留新旧目录，不要合并。" }); await controller.refresh();
  assert.match(renders.at(-1).message, /保留新旧目录，不要合并。/);
}
{
  const old = deferred(), renders = [], api = { data_migration_status: () => old.promise };
  const controller = createMigrationStatus({ bridge: () => api, render: value => renders.push(value) });
  const pending = controller.refresh(); api.data_migration_status = async () => result("failed"); await controller.refresh();
  old.resolve(result("complete")); await pending; assert.equal(renders.at(-1).status, "failed", "An older complete receipt cannot replace newer failed state");
  const held = deferred(); api.data_migration_status = () => held.promise; const stale = controller.refresh(); delete api.data_migration_status;
  await controller.refresh(); held.reject(Error("old failure")); await stale; assert.equal(renders.at(-1), null);
}
{
  const nodes = new Map(), element = { dataset: {}, querySelector(key) { if (!nodes.has(key)) nodes.set(key, { setAttribute() {} }); return nodes.get(key); } };
  const api = { data_migration_status: async () => ({ ...result("failed"), message: "<img src=x> literal failure" }) };
  const reader = installMigrationStatus({ element, bridge: () => api }); await reader.refresh();
  assert.equal(element.hidden, false); assert.equal(element.dataset.status, "failed"); assert.equal(nodes.get("[data-migration-outcome]").textContent, "<img src=x> literal failure");
  assert.equal(nodes.get("details").hidden, false); assert.match(nodes.get("pre").textContent, /receipt.json/);
  api.data_migration_status = async () => ({ ok: true, status: "none" }); await reader.refresh(); assert.equal(element.hidden, true); assert.equal(nodes.get("pre").textContent, "");
}
const settings = readFileSync(new URL("../desk-settings.js", import.meta.url), "utf8");
assert.match(settings, /async function load\(\) \{\s+migrationStatus.refresh\(\)/);
assert.match(settings, /installMigrationStatus\(\{ element: \$\("settingsMigrationOutcome"\) \}\)/);
assert(!source.includes("apply_data_directory")); assert(!source.includes("restart_application"));
console.log("Migration outcome: optional read-only bridge, literal receipt guidance, reconciled completion, scheduled/unknown boundaries, latest-read wins and safe view passed");
