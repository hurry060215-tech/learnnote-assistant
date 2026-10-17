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
    const keys = { "[data-progressive-reader]": "progressiveReader", "[data-reader-groups]": "readerGroups", "[data-reader-section]": "readerSection", "[data-reader-batch]": "readerBatch" };
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

test("literal chapter counts update metadata without replacing prose or implying verified truth", () => {
  const h = harness(), one = outline("one", 0, 10), item = batch("vision-one", 0, 10);
  item.evidence_status = { schema_version: 1, method: "literal_prose", claim_count: 5, matching_count: 2, review_count: 3 };
  h.reader.render(projection([one, item]), task, {});
  const node = h.element.querySelector("[data-reader-batch]"), body = node.children[2];
  assert.match(node.children[0].textContent, /2\/5 条正文结论与原文字面匹配/);
  assert.match(node.children[0].textContent, /未完成最终校验/);
  item.evidence_status = { ...item.evidence_status, matching_count: 3, review_count: 2 };
  h.reader.render(projection([one, item]), task, {});
  assert.equal(h.element.querySelector("[data-reader-batch]"), node); assert.equal(node.children[2], body);
  assert.equal(h.rendered.length, 1); assert.match(node.children[0].textContent, /3\/5/);
  for (const invalid of [{ matching_count: 8 }, { matching_count: true }, { schema_version: 9 }, { method: "model_verified" }]) {
    h.reader.render(projection([one, { ...item, evidence_status: { ...item.evidence_status, ...invalid } }]), task, {});
    assert.match(node.children[0].textContent, /证据补充中/);
  }
});

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
  for (const nativeAnchoring of [false, true, "layout"]) {
    const h = harness(), one = outline("one", 0, 10), two = outline("two", 20, 30);
    h.reader.render(projection([one, two, batch("second", 20, 30)]), task, {});
    const section = h.element.querySelectorAll("[data-reader-section]")[1];
    h.doc.selected = section.children[1].children[0].children[1];
    let documentY = 1000, pending = false;
    section.getBoundingClientRect = () => {
      if (pending) { h.scroller.scrollTop += 150; pending = false; }
      return { top: documentY - h.scroller.scrollTop };
    };
    const create = h.doc.createElement;
    h.doc.createElement = tag => {
      if (tag === "article") {
        documentY += 150;
        if (nativeAnchoring === true) h.scroller.scrollTop += 150;
        else if (nativeAnchoring === "layout") pending = true;
      }
      return create(tag);
    };
    h.reader.render(projection([one, two, batch("first", 0, 10), batch("second", 20, 30)]), task, {});
    assert.equal(h.scroller.scrollTop, 650, `native anchoring: ${nativeAnchoring}`);
    assert.equal(section.getBoundingClientRect().top, 500);
  }
});

test("changed source rebuilds sections without applying the old source anchor offset", () => {
  const h = harness(), original = projection([outline("one", 0, 10), batch("first", 0, 10)]);
  h.reader.render(original, task, {});
  const section = h.element.querySelector("[data-reader-section]");
  h.doc.selected = section.children[1].children[0].children[1];
  section.getBoundingClientRect = () => { throw new Error("An old source anchor must not be measured"); };
  h.scroller.scrollTop = 700;
  h.reader.render({ ...original, source_revision: hash("f") }, task, {});
  assert(!section.isConnected);
  assert.equal(h.scroller.scrollTop, 700);
});

test("a removed selected batch retains the original no-anchor fallback", () => {
  const h = harness(), one = outline("one", 0, 10);
  h.reader.render(projection([one, batch("first", 0, 10)]), task, {});
  const oldBatch = h.element.querySelector("[data-reader-batch]");
  h.doc.selected = oldBatch; h.scroller.scrollTop = 700;
  h.reader.render(projection([one]), task, {});
  assert(!oldBatch.isConnected);
  assert.equal(h.scroller.scrollTop, 700);
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

// Use the actual consumer as well as the section renderer: a rejected pair must
// not clear the live shell before the selected refresh lane can reconcile it.
const { default: vm } = await import("node:vm");
const desk = fs.readFileSync(new URL("../desk.js", import.meta.url), "utf8");
const imported = name => import(`data:text/javascript;base64,${Buffer.from(fs.readFileSync(new URL(`../${name}`, import.meta.url), "utf8")).toString("base64")}`);
const { renderEditionStable } = await imported("reader-progress.js");
const { claimMapVersion } = await imported("claim-timeline.js");
const { localMediaSource } = await imported("local-player.js");
function editionHarness() {
  const h = harness(), pending = [], nodes = new Map([["document", h.element]]);
  const state = { epoch: 1, selected: { ...task, control_generation: hash("9"), control_retry_count: 0,
    options: { visual_understanding: true }, artifact_status: { partial_draft_available: true }, summary_source: "partial-draft",
    source_identity: { source: "owned" }, note_path: "draft.partial.md", transcript_path: "transcript.json" } };
  let bodyWrites = 0;
  Object.defineProperty(h.element, "innerHTML", { set() { bodyWrites++; h.element.replaceChildren(); h.doc.selected = null; h.doc.activeElement = null; } });
  const $ = id => { if (id === "reviewNoteSources") return null; if (!nodes.has(id)) nodes.set(id, { dataset: {} }); return nodes.get(id); };
  const context = vm.createContext({ state, $, localMediaSource, renderStatus() {}, CustomEvent, AbortController, document: h.doc, sectionReader: h.reader, renderEditionStable, claimMapVersion,
    api: path => new Promise(resolve => pending.push({ path, resolve })), sourcePath: () => "/edition",
    LearnNoteMarkdown: { configure() {}, markdownToHtml: text => text }, taskAsset: value => value,
    claimTimeline: { reset() {} }, loadClaimTimeline() {}, esc: value => value, canOcrMaterial: () => false,
    mountMaterialOcr() {}, collapseSourceReviews() {}, decorateSourceTimes() {}, window: h.doc.defaultView, Event });
  vm.runInContext(desk.slice(desk.indexOf("function selectedSnapshot()"), desk.indexOf("async function openItem(")), context);
  vm.runInContext("let editionRequest = 0;" + desk.slice(desk.indexOf("async function loadEdition("), desk.indexOf("function decorateSourceTimes(")), context);
  const edition = { revision: hash("f"), text: "# Exact retained draft", edited: false };
  const payload = projection([outline("one", 0, 10), batch("first", 0, 10)]);
  const load = async (next = payload, value = edition, mutate = () => {}) => {
    const result = context.loadEdition(state.epoch); mutate();
    const responses = pending.splice(0); responses[0].resolve(value); responses[1]?.resolve(next);
    return await result;
  };
  return { ...h, state, context, edition, payload, load, pending, bodyWrites: () => bodyWrites };
}

test("ready timestamp conflicts retain the exact accepted body, selection, focus and scroll before any consumer writes", async () => {
  for (const timestamp of ["t0", "t2"]) {
    const h = editionHarness(); await h.load();
    const chapter = h.element.querySelector("[data-reader-section]"), batch = h.element.querySelector("[data-reader-batch]");
    h.doc.selected = batch.children[2]; h.doc.activeElement = batch.children[1].children[1]; h.scroller.scrollTop = 712;
    const focus = h.doc.activeElement, selected = h.doc.selected, text = h.state.text, edition = h.state.edition;
    h.state.selected = { ...h.state.selected, status: "cancelled" };
    assert.equal(await h.load({ ...h.payload, task_updated_at: timestamp }), "projection_conflict");
    assert.equal(h.bodyWrites(), 0); assert.equal(h.state.edition, edition); assert.equal(h.state.text, text);
    assert.equal(h.element.querySelector("[data-reader-section]"), chapter); assert.equal(h.element.querySelector("[data-reader-batch]"), batch);
    assert(chapter.isConnected); assert.equal(h.doc.selected, selected); assert.equal(h.doc.activeElement, focus); assert.equal(h.scroller.scrollTop, 712);
    assert.equal(h.state.selected.status, "cancelled");
    await h.load(); assert.equal(h.element.querySelector("[data-reader-batch]"), batch, "A later consistent pair reconciles without remounting");
  }
});

test("ready-conflict retention rejects changed provenance, content, edits and unproven unavailable responses", async () => {
  const mutations = [
    h => { h.state.selected.id = "other"; }, h => { h.state.selected.control_generation = hash("8"); },
    h => { h.state.selected.control_generation = undefined; }, h => { h.state.selected.control_generation = "invalid"; },
    h => { h.state.selected.control_retry_count++; }, h => { h.state.selected.retry_count = 1; },
    h => { h.state.selected.source_identity = { source: "other" }; }, h => { h.state.selected.transcript_path = "other.json"; },
    h => { h.state.selected.note_path = "edited.md"; }, h => { h.state.selected.options.model = "different"; },
    h => { h.state.selected.page_url = "https://example.test/changed"; },
    h => { h.state.selected.learning_range = { start: 1, end: 10 }; }, h => { h.state.selected.range_media_ready = true; },
    h => { h.state.selected.media_path = "new.mp4"; }, h => { h.state.selected.source_media_path = "new-source.mp4"; },
    h => { h.state.selected.source_task_id = "other-source"; }, h => { h.state.selected.media_integrity = { sha256: hash("7") }; },
    h => { h.state.selected.frame_grids = [{ url: "different" }]; }, h => { h.state.selected.title = "Different title"; },
    h => { h.state.selected.summary_source = "local-template"; }, h => { h.state.selected.status = "success"; },
    h => { h.edition.revision = hash("1"); }, h => { h.edition.text = "Different draft"; }, h => { h.edition.edited = true; },
    h => { h.payload.attempt_id = "123456abcdef"; }, h => { h.payload.source_revision = hash("1"); },
    h => { h.payload.generation_revision = hash("1"); }, h => { h.payload.revision = hash("1"); },
    h => { h.payload.sections[1].markdown = "Changed bytes with an unchanged claimed hash"; },
    h => { h.payload.reason = "snapshot_changed"; h.payload.status = "unavailable"; },
    h => { h.element.children[0].remove(); },
  ];
  for (const mutate of mutations) {
    const h = editionHarness(); await h.load();
    assert.equal(await h.load({ ...h.payload, task_updated_at: "t0" }), "projection_conflict");
    mutate(h); const attached = Boolean(h.element.children[0]);
    assert.notEqual(await h.load({ ...h.payload, task_updated_at: "t0" }), "projection_conflict", mutate.toString());
    if (attached) assert.equal(h.bodyWrites(), 1, mutate.toString());
  }
});

test("pending conflicts still obey source, epoch, generation and editing admission guards", async () => {
  for (const mutate of [h => h.state.epoch++, h => { h.state.editing = true; },
    h => { h.state.selected = { ...h.state.selected, control_generation: "new" }; },
    h => { h.state.selected = { ...h.state.selected, id: "new" }; }]) {
    const h = editionHarness(); await h.load(); const shell = h.element.children[0];
    assert.equal(await h.load({ ...h.payload, task_updated_at: "t0" }, h.edition, () => mutate(h)), undefined);
    assert.equal(h.element.children[0], shell); assert.equal(h.bodyWrites(), 0);
  }
});

test("actual cancelled selected lane reconciles an older ready pair without remounting the live section reader", async () => {
  const h = editionHarness(); await h.load();
  const chapter = h.element.querySelector("[data-reader-section]"), batch = h.element.querySelector("[data-reader-batch]");
  h.doc.selected = batch.children[2]; h.doc.activeElement = chapter.children[1].children[0].children[0]; h.scroller.scrollTop = 719;
  const selected = h.doc.selected, focus = h.doc.activeElement, cancelled = { ...h.state.selected, status: "cancelled", updated_at: "t2" };
  const pending = h.context.refreshSelectedTask();
  for (const timestamp of ["t1", "t2"]) {
    const target = h.pending.shift(); assert.equal(target.path, `/api/tasks/${task.id}`); target.resolve({ task: cancelled });
    await new Promise(resolve => setImmediate(resolve)); assert.equal(h.state.selected.status, "cancelled");
    const pair = h.pending.splice(0); assert.equal(pair.length, 2);
    pair[0].resolve(h.edition); pair[1].resolve({ ...h.payload, task_updated_at: timestamp });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(h.element.querySelector("[data-reader-section]"), chapter); assert.equal(h.element.querySelector("[data-reader-batch]"), batch);
    assert.equal(h.doc.selected, selected); assert.equal(h.doc.activeElement, focus); assert.equal(h.scroller.scrollTop, 719);
    assert.equal(h.bodyWrites(), 0);
  }
  await pending; assert.equal(h.pending.length, 0); assert.equal(h.state.selectedRefresh.promise, null);
  assert.equal(h.reader.retainableSnapshot({ ...h.payload, task_updated_at: "t1" }, cancelled, h.edition), true);
});
