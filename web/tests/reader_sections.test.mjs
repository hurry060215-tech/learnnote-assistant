import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
const source = fs.readFileSync(new URL("../reader-sections.js", import.meta.url), "utf8");
const { sectionPlan, createSectionReader } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const hash = letter => letter.repeat(64);
const task = { id: "synthetic", kind: "task", status: "running", title: "Synthetic", updated_at: "t1", frame_grids: [] };
const outline = (id, start, end) => ({ id, start, end, kind: "temporal_outline", status: "draft", verified: false,
  summary_generated: false, revision: hash("a"), excerpts: [{ start, end, text: `Literal <script>source ${id}</script>` }] });
const batch = (id, start, end, windows = [{ index: 0, start, end }]) => ({ id, start, end, kind: "vision_batch",
  status: "evidence_pending", verified: false, revision: hash("b"), markdown: `Draft ${id}`, source_windows: windows });
const projection = sections => ({ schema_version: 1, task_id: task.id, task_updated_at: task.updated_at, status: "draft", reason: "ready",
  verified: false, attempt_id: "abcdef123456", source_revision: hash("c"), revision: hash("d"), generation_revision: hash("e"), sections });

test("source-window overlap attaches once; sparse gaps and touching endpoints are not matches", () => {
  const source = [outline("one", 0, 10), outline("gap", 20, 30), outline("two", 40, 50)];
  const wide = batch("wide", 0, 50, [{ index: 0, start: 0, end: 10 }, { index: 3, start: 40, end: 50 }]);
  const plan = sectionPlan(projection([...source, wide, batch("outside", 10, 20)]), task, {});
  assert.equal(plan.outlines[0].batches[0].spans, 2);
  assert.equal(plan.outlines[1].batches.length, 0);
  assert.equal(plan.outlines[2].batches.length, 0);
  assert.equal(plan.unmatched[0].id, "outside");
});

test("wrong task, snapshot, generation, malformed sections, edits and final notes reject progressive projection", () => {
  const good = projection([outline("one", 0, 10), batch("vision-one", 0, 10)]);
  for (const update of [{ task_id: "another" }, { task_updated_at: "t0" }, { verified: true }, { reason: "source_mismatch" },
    { status: "unavailable" }, { schema_version: 2 }, { attempt_id: "bad" }, { generation_revision: "" },
    { sections: [good.sections[0], good.sections[0]] }, { sections: [{ ...good.sections[0], end: NaN }] },
    { sections: [good.sections[0], { ...good.sections[1], source_windows: [{ index: 0, start: 100, end: 110 }] }] },
    { sections: [good.sections[0], { ...good.sections[1], kind: "text_chunk" }] }]) {
    assert.equal(sectionPlan({ ...good, ...update }, task, {}), null, JSON.stringify(update));
  }
  assert.equal(sectionPlan(good, task, { edited: true }), null);
  assert.equal(sectionPlan(good, { ...task, status: "success" }, {}), null);
  assert.ok(sectionPlan(projection([outline("one", 0, 10)]), task, {}));
});

class Element {
  constructor(tag, doc) { this.tagName = tag.toUpperCase(); this.ownerDocument = doc; this.children = []; this.dataset = {}; this.parentElement = null; this.value = ""; this.events = {}; this.writes = 0; }
  get textContent() { return this.value + this.children.map(child => child.textContent).join(""); }
  set textContent(value) { this.writes++; this.value = String(value); this.replaceChildren(); }
  append(...nodes) { for (const node of nodes) this.insertBefore(node, null); }
  insertBefore(node, before) { node.remove(); const index = before ? this.children.indexOf(before) : this.children.length; this.children.splice(index, 0, node); node.parentElement = this; this.writes++; }
  remove() { if (!this.parentElement) return; const parent = this.parentElement; parent.children.splice(parent.children.indexOf(this), 1); parent.writes++; this.parentElement = null; }
  replaceChildren(...nodes) { for (const child of [...this.children]) child.remove(); this.append(...nodes); }
  get isConnected() { return Boolean(this.root || this.parentElement?.isConnected); }
  contains(node) { return this === node || this.children.some(child => child.contains(node)); }
  setAttribute(key, value) { this[key] = value; }
  addEventListener(key, callback) { this.events[key] = callback; }
  querySelectorAll(selector) {
    const keys = { "[data-reader-groups]": "readerGroups", "[data-reader-section]": "readerSection", "[data-reader-batch]": "readerBatch" };
    const matches = node => selector.split(",").some(part => keys[part.trim()] in node.dataset);
    return this.children.flatMap(child => [...(matches(child) ? [child] : []), ...child.querySelectorAll(selector)]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0]; }
  getBoundingClientRect() { return { top: this.top || 0, bottom: (this.top || 0) + 20 }; }
}
function harness() {
  const notices = [], rendered = [], opened = [];
  const doc = { createElement: tag => new Element(tag, doc), createTextNode: text => { const node = new Element("text", doc); node.textContent = text; return node; },
    defaultView: { dispatchEvent: event => notices.push(event.type) }, getSelection: () => ({ anchorNode: doc.selected }) };
  const element = doc.createElement("main"); element.root = true;
  const scroller = { scrollTop: 500, ownerDocument: doc }; doc.scrollingElement = scroller;
  const reader = createSectionReader({ element, scroller, timestamp: value => String(value),
    renderMarkdown: (node, text) => { rendered.push(text); node.textContent = text; }, decorate: () => {}, openSource: value => opened.push(value),
    asset: (url, id) => typeof url === "string" && url.startsWith(`/api/tasks/${id}/frames/`) ? url : "" });
  return { reader, element, scroller, doc, rendered, opened, notices };
}

test("new visual batches keep source and existing batch nodes; replay has no mutation", () => {
  const h = harness(), one = outline("one", 0, 10), two = outline("two", 20, 30);
  h.reader.render(projection([one, two, batch("second", 20, 30)]), task, {});
  const [sourceOne, sourceTwo] = h.element.querySelectorAll("[data-reader-section]");
  const oldBatch = h.element.querySelector("[data-reader-batch]");
  const selected = sourceTwo.children[1].children[0].children[1]; h.doc.selected = selected;
  const next = projection([one, two, batch("first", 0, 10), batch("second", 20, 30)]);
  h.reader.render(next, task, {});
  assert.equal(h.element.querySelectorAll("[data-reader-section]")[0], sourceOne);
  assert.equal(h.element.querySelectorAll("[data-reader-section]")[1], sourceTwo);
  assert.equal(h.element.querySelectorAll("[data-reader-batch]")[1], oldBatch);
  assert(selected.isConnected);
  assert.equal(h.rendered.length, 2);
  const all = node => [node, ...node.children.flatMap(all)];
  const before = all(h.element).map(node => [node, node.writes]);
  h.reader.render(next, task, {});
  assert(before.every(([node, writes]) => node.writes === writes));
  assert.equal(h.rendered.length, 2);
  assert.equal(h.notices.length, 2);
  sourceOne.children[1].children[0].children[0].events.click();
  assert.deepEqual(h.opened, [0]);
});

test("new attempts remove old sections, generation changes retain only the same source outline", () => {
  const h = harness(), original = projection([outline("one", 0, 10), batch("first", 0, 10)]);
  h.reader.render(original, task, {});
  const section = h.element.querySelector("[data-reader-section]"), oldBatch = h.element.querySelector("[data-reader-batch]");
  h.reader.render({ ...original, generation_revision: hash("f"), sections: [original.sections[0]] }, task, {});
  assert.equal(h.element.querySelector("[data-reader-section]"), section); assert(!oldBatch.isConnected);
  h.reader.render({ ...original, attempt_id: "123456abcdef" }, task, {});
  assert(!section.isConnected);
});

test("scroll compensation respects both native scroll anchoring and browsers without it", () => {
  for (const nativeAnchoring of [false, true]) {
    const h = harness(), one = outline("one", 0, 10), two = outline("two", 20, 30);
    h.reader.render(projection([one, two, batch("second", 20, 30)]), task, {});
    const section = h.element.querySelectorAll("[data-reader-section]")[1];
    h.doc.selected = section.children[1].children[0].children[1];
    let documentY = 1000;
    section.getBoundingClientRect = () => ({ top: documentY - h.scroller.scrollTop });
    const create = h.doc.createElement;
    h.doc.createElement = tag => {
      if (tag === "article") { documentY += 150; if (nativeAnchoring) h.scroller.scrollTop += 150; }
      return create(tag);
    };
    h.reader.render(projection([one, two, batch("first", 0, 10), batch("second", 20, 30)]), task, {});
    assert.equal(h.scroller.scrollTop, 650, `native anchoring: ${nativeAnchoring}`);
    assert.equal(section.getBoundingClientRect().top, 500);
  }
});

test("only exact task-owned grids supplement evidence; unrelated and external assets are excluded", () => {
  const h = harness();
  const mediaTask = { ...task, frame_grids: [{ start: 0, end: 10, url: "/api/tasks/synthetic/frames/good.jpg" },
    { start: 1, end: 10, url: "/api/tasks/synthetic/frames/wrong-time.jpg" },
    { start: 0, end: 10, url: "https://example.com/outside.jpg" },
    { start: 0, end: 10, url: "/api/tasks/other/frames/cross-task.jpg" }] };
  h.reader.render(projection([outline("one", 0, 10), batch("first", 0, 10)]), mediaTask, {});
  const details = h.element.querySelector("[data-reader-batch]").children.at(-1);
  assert.equal(details.tagName, "DETAILS"); assert.equal(details.children.length, 2);
  assert.equal(details.children[1].src, "/api/tasks/synthetic/frames/good.jpg");
  assert.equal(details.children[1].loading, "lazy");
});
