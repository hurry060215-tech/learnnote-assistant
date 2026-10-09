import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const load = async name => import("data:text/javascript;base64," + Buffer.from(readFileSync(new URL(`../${name}`, import.meta.url), "utf8")).toString("base64"));
const { sourceWindow, createSourceWindowView, renderMaterialSource, highlightMaterialSource } = await load("evidence-source-view.js");
const { taskAsset } = await load("desk-api.js");
const { evidenceAnchor } = await load("evidence-anchor.js");
class Element {
  constructor() { this.children = []; this.dataset = {}; this.style = {}; this.classes = new Set(); this.classList = { add: value => this.classes.add(value) }; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; this.value = ""; }
  set textContent(value) { this.value = String(value); this.children = []; }
  get textContent() { return this.value || this.children.map(item => item.textContent).join(""); }
  scrollIntoView() { this.scrolled = true; }
}
globalThis.document = { createElement: () => new Element(), createTextNode: value => { const item = new Element(); item.textContent = value; return item; } };
globalThis.location = { origin: "http://127.0.0.1" };
const source = { kind: "task", id: "episode", visual_windows: [
  { id: "first", start: 0, end: 10, grid_url: "/api/tasks/episode/assets/first.jpg" },
  { id: "second", start: 10, end: 20, grid_url: "/api/tasks/episode/assets/second.jpg" },
] };

test("window references use exact identity and timestamp overlap without arbitrary fallback", () => {
  assert.equal(sourceWindow(source, 0, "second").id, "second");
  assert.equal(sourceWindow(source, 10).id, "second");
  assert.equal(sourceWindow(source, 30), null);
  assert.equal(sourceWindow(source, Infinity), null);
  assert.equal(sourceWindow(source, 2, "missing"), null);
  assert.equal(sourceWindow({ ...source, visual_windows: [...source.visual_windows, source.visual_windows[0]] }, 0, "first"), null);
  assert.equal(sourceWindow({ kind: "material", visual_windows: source.visual_windows }, 0), null);
});

test("playback updates one safe local frame and exact missing windows are disclosed", () => {
  const container = new Element(), sought = [];
  const render = createSourceWindowView({ container, source, asset: taskAsset, timestamp: value => `${value}s`, onSeek: value => sought.push(value) });
  render(1); const first = container.children[0];
  assert.equal(first.dataset.windowId, "first"); assert.equal(first.children[0].src, "/api/tasks/episode/assets/first.jpg");
  render(2); assert.equal(container.children[0], first);
  render(15); assert.equal(container.children.length, 1); assert.equal(container.children[0].dataset.windowId, "second");
  container.children[0].children[1].children[0].onclick(); assert.deepEqual(sought, [10]);
  render(30); assert.equal(container.hidden, true);
  render(0, "missing"); assert.equal(container.hidden, false); assert.match(container.textContent, /暂不可用/);
  const foreign = createSourceWindowView({ container, source: { ...source, visual_windows: [{ ...source.visual_windows[0], grid_url: "/api/tasks/other/assets/frame.jpg" }] }, asset: taskAsset, timestamp: String, onSeek() {} });
  foreign(0, "first"); assert.equal(container.children.length, 0); assert.match(container.textContent, /暂不可用/);
});

test("document navigation selects the canonical ID while retaining the complete original", () => {
  const container = new Element(), original = "# Original\n\n  code spacing\n\nMissing index paragraph stays readable.";
  const anchors = [{ evidence_id: "one", locator: "page 1", text: "Same text" }, { evidence_id: "two", locator: "page 2", text: "Same text" }];
  renderMaterialSource(container, original, anchors);
  assert.equal(highlightMaterialSource(container, "two"), true);
  assert.equal(container.children[0].dataset.evidenceId, "two"); assert.match(container.children[0].textContent, /page 2/);
  assert.equal(container.children[2].textContent, original);
  assert.equal(highlightMaterialSource(container, "missing"), false); assert.equal(container.children[0].hidden, true);
  assert.equal(container.children[2].textContent, original);
});

test("latest card reference wins even when an older lookup replies first", async () => {
  const desk = readFileSync(new URL("../desk.js", import.meta.url), "utf8"), calls = [], requests = new Map();
  const state = { epoch: 1, selected: null, items: [{ kind: "material", id: "a" }, { kind: "task", id: "b" }] };
  const context = vm.createContext({ state, evidenceAnchor, guard: () => true,
    api: path => new Promise(resolve => requests.set(path, resolve)),
    openItem: async item => { calls.push(["item", item.id]); state.selected = item; state.epoch++; },
    openSource: async (seconds, item, target) => { calls.push(["source", item.id, seconds, target.evidenceId, target.windowId]); },
  });
  vm.runInContext(desk.slice(desk.indexOf("let evidenceRequest = 0;"), desk.indexOf("async function drawReview()")), context);
  const older = context.openEvidence("old"), latest = context.openEvidence("new");
  requests.get("/api/knowledge/evidence/old")({ evidence: { metadata: { material_id: "a" }, locator: "page 1" } });
  await older; assert.deepEqual(calls, []);
  requests.get("/api/knowledge/evidence/new")({ evidence: { evidence_id: "new", task_id: "b", locator: "10-20s", metadata: { window_id: "second" } } });
  await latest; assert.deepEqual(calls, [["item", "b"], ["source", "b", 10, "new", "second"]]);
  const abandoned = context.openEvidence("abandoned"); state.epoch++;
  requests.get("/api/knowledge/evidence/abandoned")({ evidence: { metadata: { material_id: "a" } } });
  await abandoned; assert.equal(calls.length, 2);
});

test("mistake backlinks use the same canonical resolver and explain a missing source", async () => {
  const tools = readFileSync(new URL("../desk-tools.js", import.meta.url), "utf8");
  const block = tools.slice(tools.indexOf("    if (dashboard?.mistakes?.length) {"), tools.indexOf("    backAction = courseId"));
  for (const missing of [false, true]) {
    const body = new Element(), calls = [], notices = [];
    const context = vm.createContext({ document, $: () => body,
      dashboard: { mistakes: [{ question: "Question", answer: "Answer", source_evidence_ids: ["canonical-id"] }] },
      dialog: { close: () => calls.push("closed") }, notice: text => notices.push(text),
      ctx: { openEvidence: async id => { calls.push(id); if (missing) throw new Error("Source no longer exists"); } },
    });
    vm.runInContext(block, context);
    await body.children[0].children[1].children[1].onclick();
    assert.deepEqual(calls, ["closed", "canonical-id"]);
    assert.deepEqual(notices, missing ? ["Source no longer exists"] : []);
  }
});
