import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../desk-tools.js", import.meta.url), "utf8");
const start = source.indexOf('    "rebuild-material": async () => {');
const action = source.slice(start, source.indexOf("    regenerate:", start)).trim().replace(/^"rebuild-material": /, "").replace(/,$/, "");
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };

function harness() {
  const response = deferred(), refreshDone = deferred(), opened = deferred();
  const state = { selected: { kind: "material", id: "original" } }, calls = [];
  const context = vm.createContext({ state,
    current: () => ({ ...state.selected }),
    api: (path, options) => { calls.push([path, options.method]); return response.promise; },
    refresh: () => { calls.push("refresh"); return refreshDone.promise; },
    openItem: item => { assert.equal(typeof item, "object", "desk openItem accepts a source object"); calls.push([item.kind, item.id]); return opened.promise; },
    notice: text => calls.push(text), more: () => calls.push("more"),
  });
  vm.runInContext(`let generation = 1; globalThis.rebuild = ${action}; globalThis.dismiss = () => generation++;`, context);
  return { context, state, calls, response, refreshDone, opened };
}
const tick = () => new Promise(done => setImmediate(done));

test("material repair refreshes the selected document and reports restored anchors", async () => {
  const h = harness(), pending = h.context.rebuild();
  h.response.resolve({ material: { anchor_count: 2 } }); h.refreshDone.resolve(); h.opened.resolve();
  await pending;
  assert.deepEqual(h.calls.slice(0, 3), [["/api/library/materials/original/rebuild", "POST"], "refresh", ["material", "original"]]);
  assert.match(h.calls[3], /2 条出处/); assert.equal(h.calls[4], "more");
});

test("late material repair cannot reopen tools or navigate away from a newer source", async () => {
  for (const phase of ["refresh", "open"]) {
    const h = harness(), pending = h.context.rebuild();
    h.response.resolve({ material: { anchor_count: 2 } });
    if (phase === "open") { h.refreshDone.resolve(); await tick(); }
    h.state.selected = { kind: "task", id: "new-video" };
    h.context.dismiss(); h.refreshDone.resolve(); h.opened.resolve();
    await pending;
    assert.ok(!h.calls.includes("more"));
    assert.ok(!h.calls.some(value => typeof value === "string" && value.includes("条出处")));
    if (phase === "refresh") assert.equal(h.calls.length, 2);
  }
});
