import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(new URL("../desk.js", import.meta.url), "utf8");
function harness() {
  class Element {
    constructor() { this.children = []; this.dataset = {}; this.hidden = false; this.scrolls = 0; this.classes = new Set(); this.classList = {add: name => this.classes.add(name)}; }
    set textContent(value) { this.value = String(value); this.children = []; }
    get textContent() { return this.value || this.children.map(child => child.textContent).join(""); }
    append(...nodes) { this.children.push(...nodes); }
    replaceChildren(...nodes) { this.value = ""; this.children = nodes; }
    querySelector() { return this.children.find(child => child.classes.has("active")); }
    scrollIntoView() { this.scrolls++; }
  }
  const nodes = new Map(), $ = id => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
  const a = {kind: "task", id: "a", title: "Course A"}, b = {kind: "task", id: "b", title: "Course B"};
  const state = {selected: a, items: [a, b], epoch: 1};
  const pending = new Map();
  const context = vm.createContext({state, $, notice: () => {}, window: {scrollY: 10, scrollTo() {}}, timestamp: value => `${value}s`,
    document: {createElement: () => new Element(), createTextNode: value => { const node = new Element(); node.textContent = value; return node; }},
    api: path => new Promise((resolve, reject) => pending.set(path, {resolve, reject})),
    openItem: async item => { state.selected = item; state.epoch++; },
  });
  const start = source.indexOf("let inlineSourceRequest =");
  const functionStart = source.indexOf("async function openInlineSource(");
  vm.runInContext(source.slice(start >= 0 ? start : functionStart, source.indexOf("async function openSource(", functionStart)), context);
  return {context, $, a, b, pending};
}

{
  const h = harness();
  const first = h.context.openInlineSource(1, h.a);
  const second = h.context.openInlineSource(2, h.b);
  await new Promise(resolve => setImmediate(resolve));
  h.pending.get("/api/tasks/b/transcript").resolve({segments: [{start: 2, end: 3, text: "ONLY COURSE B"}]});
  await second;
  h.pending.get("/api/tasks/a/transcript").resolve({segments: [{start: 1, end: 2, text: "STALE COURSE A"}]});
  await first;
  assert.doesNotMatch(h.$("inlineSourceContent").textContent, /STALE COURSE A/, "An older source response must never enter the newer source view");
  assert.match(h.$("inlineSourceMeta").textContent, /Course B/);
}

for (const fail of [false, true]) {
  const h = harness(), pending = h.context.openInlineSource(1, h.a);
  h.$("backToSummary").onclick();
  const before = h.$("inlineSourceMeta").textContent;
  if (fail) h.pending.get("/api/tasks/a/transcript").reject(new Error("OLD ERROR"));
  else h.pending.get("/api/tasks/a/transcript").resolve({segments: [{start: 1, end: 2, text: "OLD TEXT"}]});
  await pending;
  assert.equal(h.$("inlineSourceView").hidden, true);
  assert.equal(h.$("inlineSourceMeta").textContent, before, "Leaving the source view invalidates late success and failure responses");
  assert.equal(h.$("inlineSourceView").scrolls, 0);
}
console.log("Inline source navigation rejects reordered replies and responses after return to note");
