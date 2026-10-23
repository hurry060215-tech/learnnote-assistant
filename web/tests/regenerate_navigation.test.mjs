import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";
const source = fs.readFileSync(new URL("../desk.js", import.meta.url), "utf8");
const handler = source.slice(source.indexOf('$("regenerate").onclick ='), source.indexOf("function readRoute() {"));
test("regeneration creates once but only its current navigation intent can open the result", async () => {
  for (const navigation of ["same", "other", "home", "away-back", "settings"]) {
    let resolve; const held = new Promise(yes => resolve = yes), nodes = new Map(), requests = [], opened = [], notices = [];
    const $ = id => { if (!nodes.has(id)) nodes.set(id, {}); return nodes.get(id); };
    const state = { selected: { id: "a", kind: "task", transcript_path: "a.json" }, epoch: 1, routeEpoch: 0 };
    const context = vm.createContext({ state, $, guard: () => true, confirm: () => true, options: () => ({}),
      api: (path, options) => { requests.push({ path, options }); return held; },
      openItem: async item => opened.push(item.id), refresh: async () => {}, notice: message => notices.push(message), failure: error => { throw error; } });
    vm.runInContext(handler, context); const pending = $("regenerate").onclick();
    if (navigation === "other") { state.epoch++; state.selected = { id: "b", kind: "task" }; }
    if (navigation === "home") { state.epoch++; state.selected = null; }
    if (navigation === "away-back") state.epoch += 2;
    if (navigation === "settings") state.routeEpoch++;
    resolve({ task_id: "a-new", task: { id: "a-new" } }); await pending;
    assert.equal(requests.length, 1); assert.equal(requests[0].path, "/api/tasks/a/retry-summary");
    assert.deepEqual(opened, navigation === "same" ? ["a-new"] : []);
    assert.equal(notices.length, navigation === "same" ? 0 : 1); assert.equal($("regenerate").disabled, false);
  }
});
