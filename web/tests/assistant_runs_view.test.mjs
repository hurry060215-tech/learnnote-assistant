import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import { testDom } from "./fixtures/assistant-test-dom.mjs";
const code = readFileSync(new URL("../assistant-runs.js", import.meta.url), "utf8").replace(/^import .*;\r?\n/gm, "").replace("export function", "function");
function setup() {
  const dom = testDom(), calls = [], reports = [];
  let hooks;
  const controller = { active: null, busy: false, open() { calls.push(["open"]); }, close() { calls.push(["close"]); },
    start(...args) { calls.push(["start", ...args]); }, cancel() { calls.push(["cancel"]); }, approve() { calls.push(["approve"]); },
    continue() { calls.push(["continue"]); }, refresh() { calls.push(["refresh"]); }, async list() { return { runs: [] }; } };
  const state = { selected: { kind: "task", id: "synthetic", title: "Synthetic title" }, revision: "a".repeat(64), editing: false };
  vm.runInNewContext(`${code}\ninstallAssistantRuns(ctx);`, { document: dom.document, window: { confirm: () => true }, api() { throw Error("Unexpected direct API"); },
    createAssistantRunController(value) { hooks = value; return controller; },
    ctx: { state, options: () => ({}), openItem: async () => {}, notice: text => reports.push(text) } });
  const dialog = dom.document.getElementById("assistantRunsDialog");
  return { ...dom, calls, controller, state, reports, dialog, hooks, $: selector => dialog.querySelector(selector),
    render(value) { controller.active = value; hooks.render(value); },
    async open() { await dom.document.getElementById("assistantRuns").fire("click"); } };
}

test("launch requires fresh explicit sharing choice and preserves common dialog styles", async () => {
  const h = setup(); h.$("[data-run-share]").checked = true; await h.open();
  assert.equal(h.$("[data-run-share]").checked, false); assert.equal(h.dialog.className, "tools-dialog");
  h.$("[data-run-question]").value = "Synthetic request";
  await h.$("[data-run-start]").fire("click");
  assert.deepEqual(h.calls.at(-1), ["start", "Synthetic request", false]);
});

test("model results and actual diffs remain literal text; download is only for completed receipts", async () => {
  const h = setup(), hostile = '<img src=x onerror="bad()">';
  const value = { id: "run", version: 3, status: "awaiting_approval", source: { id: hostile, revision: "a".repeat(64) },
    reason: hostile, steps: [{ tool: "read_note", status: "completed", result: { text: hostile, truncated: true } }],
    pending_operation: { preview: { diff: hostile } }, artifact_operation_id: "must-not-download" };
  const writes = h.htmlWrites.length; h.render(value);
  assert.equal(h.htmlWrites.length, writes); assert.match(h.$("[data-run-card]").textContent, /onerror/);
  assert.match(h.$("[data-run-card]").textContent, /不能视为已读完整/); assert.equal(h.$("[data-run-card]").querySelector("a"), null);
  assert.equal(h.$("[data-run-share]").disabled, true); assert.equal(h.$("[data-run-share]").checked, true);
  await h.$("[data-run-approve]").fire("click"); assert.deepEqual(h.calls.at(-1), ["approve"]);
  h.render({ ...value, pending_operation: null, status: "completed", artifact_operation_id: "safe-export" });
  assert.equal(h.$("[data-run-card]").querySelector("a").href, "/api/assistant/operations/safe-export/artifact");
  assert.equal(h.$("[data-run-share]").disabled, false); assert.equal(h.$("[data-run-share]").checked, false);
});

test("cancel and close remain enabled during a pending decision", async () => {
  const h = setup(); await h.open(); h.controller.busy = true; h.hooks.busyChanged(true);
  assert.equal(h.$("[data-run-start]").disabled, true); assert.equal(h.$("[data-run-cancel]").disabled, false);
  await h.$("[data-run-cancel]").fire("click"); assert.deepEqual(h.calls.at(-1), ["cancel"]);
  await h.$("[data-run-close]").fire("click"); assert.deepEqual(h.calls.at(-1), ["close"]);
  assert.equal(h.reports.length, 1);
});
