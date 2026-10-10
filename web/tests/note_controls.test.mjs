import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const code = readFileSync(new URL("../desk-note-controls.js", import.meta.url), "utf8");
const { normalizeOutline, createOutlineControls, formatNoteText, installNoteEditor } =
  await import("data:text/javascript;base64," + Buffer.from(code).toString("base64"));

class Element {
  constructor() {
    this.attributes = {}; this.events = {}; this.children = []; this.hidden = false;
    this.value = ""; this.textContent = ""; this.disabled = false;
    this.style = { setProperty: (key, value) => this.style[key] = value };
  }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  getAttribute(key) { return this.attributes[key]; }
  addEventListener(key, fn) { (this.events[key] ||= []).push(fn); }
  fire(key, event = {}) { for (const fn of this.events[key] || []) fn({ preventDefault() {}, ...event }); }
  focus() { this.focused = true; }
  setPointerCapture() {}
  setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; }
  getBoundingClientRect() { return { width: parseFloat(this.style.width) || 540 }; }
  append(child) { this.children.push(child); child.parent = this; }
  before(child) { this.parent.children.splice(this.parent.children.indexOf(this), 0, child); child.parent = this.parent; }
  set innerHTML(value) {
    this.html = value; this.children = [];
    for (const match of value.matchAll(/id="([^"]+)"/g)) { const child = new Element(); child.id = match[1]; this.append(child); }
  }
  get innerHTML() { return this.html || ""; }
  querySelector(selector) {
    return this.children.find(child => selector.startsWith("#") ? child.id === selector.slice(1) : child.className === selector.slice(1))
      || this.children.map(child => child.querySelector(selector)).find(Boolean);
  }
}
function outlineHarness(saved) {
  const values = new Map(saved === undefined ? [] : [["learnnote.outline.preferences", saved]]);
  globalThis.localStorage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) };
  globalThis.innerWidth = 1440;
  globalThis.window = new Element();
  const classes = new Set();
  globalThis.document = { createElement: () => new Element(), body: { classList: { add: name => classes.add(name), remove: name => classes.delete(name) } } };
  const dialog = new Element(); dialog.id = "outlineDialog";
  const tree = new Element(); tree.className = "outline-tree"; dialog.append(tree);
  const controls = createOutlineControls(dialog); controls.mount();
  return { dialog, controls, values, classes, node: id => dialog.querySelector(`#${id}`) };
}
test("TOC settings recover malformed storage and clamp unsupported values", () => {
  assert.deepEqual(normalizeOutline(), { width: 540, size: 14, gap: 4 });
  assert.deepEqual(normalizeOutline({ width: 10000, size: 1, gap: -2 }), { width: 980, size: 12, gap: 0 });
  assert.equal(outlineHarness("broken json").dialog.style.width, "540px");
});
test("TOC density and font changes apply immediately, persist, and reset", () => {
  const h = outlineHarness();
  h.node("outlineGap").value = "0"; h.node("outlineGap").oninput();
  h.node("outlineSize").value = "18"; h.node("outlineSize").oninput();
  assert.equal(h.dialog.style["--outline-gap"], "0px");
  assert.equal(h.dialog.style["--outline-padding"], "4px");
  const reopened = outlineHarness(h.values.get("learnnote.outline.preferences"));
  assert.equal(reopened.dialog.style["--outline-size"], "18px");
  assert.equal(reopened.node("outlineGap").value, 0);
  reopened.node("resetOutline").onclick();
  assert.deepEqual(JSON.parse(reopened.values.get("learnnote.outline.preferences")), { width: 540, size: 14, gap: 4 });
});
test("horizontal drag follows centered edge, persists on cancellation, and releases state", () => {
  const h = outlineHarness(), handle = h.node("outlineResize");
  handle.fire("pointerdown", { button: 2, clientX: 900 });
  handle.fire("pointermove", { clientX: 920 });
  assert.equal(h.dialog.style.width, "540px");
  handle.fire("pointerdown", { button: 0, clientX: 900, pointerId: 1 });
  handle.fire("pointermove", { clientX: 980 });
  assert.equal(h.dialog.style.width, "700px");
  assert(h.classes.has("resizing-outline"));
  handle.fire("pointercancel");
  assert.equal(h.classes.size, 0);
  assert.equal(JSON.parse(h.values.get("learnnote.outline.preferences")).width, 700);
  handle.fire("pointermove", { clientX: 1200 });
  assert.equal(h.dialog.style.width, "700px");
});
test("keyboard resize and narrow viewports remain bounded without losing desktop width", () => {
  const h = outlineHarness(), handle = h.node("outlineResize");
  handle.fire("keydown", { key: "ArrowRight" });
  assert.equal(h.dialog.style.width, "564px");
  handle.fire("keydown", { key: "End" });
  assert.equal(h.dialog.style.width, "980px");
  globalThis.innerWidth = 390; window.fire("resize");
  assert.equal(h.dialog.style.width, "362px");
  assert.equal(handle.getAttribute("aria-valuemax"), "362");
  globalThis.innerWidth = 1440; window.fire("resize");
  assert.equal(h.dialog.style.width, "980px");
  handle.fire("dblclick"); assert.equal(h.dialog.style.width, "540px");
});

const deferred = () => { let resolve, reject; const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; }); return { promise, resolve, reject }; };
function editorHarness() {
  const nodes = new Map(), $ = id => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
  $("notePreview").hidden = true;
  const state = { selected: { id: "summary-one", kind: "task" }, epoch: 1, editing: false, text: "# Original\n\n## Summary\n\nOriginal text.", revision: "r1" };
  const calls = [], notices = [], pending = [], renders = [];
  let discardAllowed = true;
  installNoteEditor({ state, $, guard: () => discardAllowed, notice: value => notices.push(value), renderNote: () => renders.push(state.text), renderMarkdown: text => `<p>${text}</p>`,
    saveNote: (selected, body) => { calls.push({ selected, body }); const request = deferred(); pending.push(request); return request.promise; } });
  return { $, state, calls, notices, pending, renders, disallowDiscard: () => { discardAllowed = false; } };
}
test("repeated Edit preserves the current draft and preview returns to that draft", () => {
  const h = editorHarness(); h.$("edit").onclick();
  h.$("noteText").value = "Unsaved summary";
  h.$("toggleNotePreview").onclick();
  assert.match(h.$("notePreview").innerHTML, /Unsaved summary/);
  h.$("edit").onclick();
  assert.equal(h.$("noteText").value, "Unsaved summary");
  assert.equal(h.$("noteText").hidden, false);
  h.disallowDiscard(); h.$("discard").onclick(); assert.equal(h.state.editing, true);
});
test("save posts the summary edition revision and exits only after success", async () => {
  const h = editorHarness(); h.$("edit").onclick(); h.$("noteText").value = "Revised";
  const saving = h.$("save").onclick(); await h.$("save").onclick();
  assert.equal(h.calls.length, 1); assert.equal(h.state.editing, true);
  assert.deepEqual(h.calls[0].body, { text: "Revised", revision: "r1" });
  h.pending[0].resolve({ text: "Revised", revision: "r2" }); await saving;
  assert.equal(h.state.editing, false); assert.equal(h.state.revision, "r2");
  assert.deepEqual(h.renders, ["Revised"]); assert.equal(h.$("document").hidden, false);
});
test("typing during a delayed save survives and the next save uses the new revision", async () => {
  const h = editorHarness(); h.$("edit").onclick(); h.$("noteText").value = "First edit";
  const saving = h.$("save").onclick(); h.$("noteText").value = "A later edit";
  h.$("discard").onclick(); assert.equal(h.state.editing, true);
  h.pending[0].resolve({ text: "First edit", revision: "r2" }); await saving;
  assert.equal(h.state.editing, true); assert.equal(h.$("noteText").value, "A later edit");
  assert.match(h.$("saveStatus").textContent, /仍待保存/);
  const next = h.$("save").onclick(); assert.equal(h.calls[1].body.revision, "r2");
  h.pending[1].resolve({ text: "A later edit", revision: "r3" }); await next;
  assert.equal(h.state.text, "A later edit");
});
test("save failure retains draft; a late response cannot overwrite another note", async () => {
  const h = editorHarness(); h.$("edit").onclick(); h.$("noteText").value = "Unsaved";
  const failure = h.$("save").onclick(); h.pending[0].reject(new Error("Conflict: reload before saving")); await failure;
  assert.equal(h.$("noteText").value, "Unsaved"); assert.equal(h.state.revision, "r1"); assert.equal(h.$("save").disabled, false);
  const retry = h.$("save").onclick(); h.state.epoch++; h.state.selected = { id: "other", kind: "material" }; h.state.text = "Other note";
  h.pending[1].resolve({ text: "Unsaved", revision: "r2" }); await retry;
  assert.equal(h.state.text, "Other note"); assert.equal(h.state.revision, "r1"); assert.equal(h.renders.length, 0);
});
test("discarding newer typing after a delayed save returns to the saved revision", async () => {
  const h = editorHarness(); h.$("edit").onclick(); h.$("noteText").value = "Saved revision";
  const saving = h.$("save").onclick(); h.$("noteText").value = "Later unsaved text";
  h.pending[0].resolve({ text: "Saved revision", revision: "r2", edited: true }); await saving;
  h.$("discard").onclick();
  assert.deepEqual(h.renders, ["Saved revision"]);
  assert.equal(h.state.edition.edited, true);
  assert.equal(h.state.editing, false);
  assert.equal(h.$("document").hidden, false);
});
test("formatting changes selected Markdown without losing surrounding text or Unicode", () => {
  assert.deepEqual(formatNoteText("前文 重点 后文", 3, 5, "bold"), { text: "前文 **重点** 后文", start: 3, end: 9 });
  assert.equal(formatNoteText("标题\n正文\n尾段", 0, 2, "heading").text, "## 标题\n正文\n尾段");
  assert.equal(formatNoteText("## 标题\n正文", 0, 5, "heading").text, "标题\n正文");
  assert.equal(formatNoteText("第一项\n第二项\n\n尾段", 0, 8, "list").text, "- 第一项\n- 第二项\n\n尾段");
});
