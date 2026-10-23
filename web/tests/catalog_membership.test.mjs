import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import test from "node:test";
const desk = readFileSync(new URL("../desk.js", import.meta.url), "utf8");
const tools = readFileSync(new URL("../desk-tools.js", import.meta.url), "utf8");

test("pinned documents outside loaded pages remain available without polling each ID repeatedly", async () => {
  const requests = [], state = { pinned: new Set(["material:old"]), materialBrowser: { query: "" } };
  const context = vm.createContext({ state, api: async path => { requests.push(path); return { material: { material_id: "old", title: "Old document", linked_task_id: "" } }; } });
  vm.runInContext(desk.slice(desk.indexOf("async function loadPinnedMaterials("), desk.indexOf("async function refreshLibrary(")), context);
  assert.equal((await context.loadPinnedMaterials([]))[0].material_id, "old");
  await context.loadPinnedMaterials([]); assert.equal(requests.length, 1);
  state.materialBrowser.query = "different"; assert.equal((await context.loadPinnedMaterials([])).length, 0);
  state.materialBrowser.query = "old"; assert.equal((await context.loadPinnedMaterials([])).length, 1);
});

test("editing a course keeps explicitly selected sources that are outside the current library page", () => {
  const source = { id: "old", kind: "material", title: "Older source" }, state = { items: [{ id: "new", kind: "material", title: "New source" }] };
  const context = vm.createContext({ state, course: { sources: [source] }, esc: String,
    form: { querySelectorAll: () => [{ dataset: { source: "old", kind: "material" } }] } });
  vm.runInContext(tools.slice(tools.indexOf("  function selectItems("), tools.indexOf("  async function saveCourse(")), context);
  assert.match(context.selectItems([source]), /data-source="old" data-kind="material" checked/);
  const start = tools.indexOf('        const checked = [...form.querySelectorAll("[data-source]:checked")]');
  vm.runInContext(tools.slice(start, tools.indexOf("        const selected = new Map", start)) + ";globalThis.selectedSources=checked;", context);
  assert.deepEqual(JSON.parse(JSON.stringify(context.selectedSources)), [source]);
});
