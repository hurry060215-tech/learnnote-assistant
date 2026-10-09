import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import vm from "node:vm";
const load = async name => import("data:text/javascript;base64," + Buffer.from(readFileSync(new URL(`../${name}`, import.meta.url), "utf8")).toString("base64"));
const { claimTimelineModel, activeClaims, claimNoteTarget, createClaimTimeline } = await load("claim-timeline.js");
const { evidenceAnchor, claimEvidenceAnchor, citationAnchor } = await load("evidence-anchor.js");
const markdown = {};
vm.runInNewContext(readFileSync(new URL("../markdown.js", import.meta.url), "utf8"), markdown);
const text = "# 🧪 Repeat\r\n\r\n- **Repeated exact words.**\r\n- **Repeated exact words.**\r\n  Continued claim text.\r\n";
const points = Array.from(text), phrase = "**Repeated exact words.";
const first = points.join("").indexOf(phrase) - 1; // One astral character before the claim.
const second = first + Array.from("- **Repeated exact words.**\r\n").length;
const revision = createHash("sha256").update(text).digest("hex");
const snapshot = { kind: "task", taskId: "one", text, revision, epoch: 1, hasMap: true };
const evidence = [
  { evidence_id: "e-first", kind: "transcript", start: 0, end: 3, locator: "0-3s" },
  { evidence_id: "e-repeat", kind: "transcript", start: 10, end: 14, locator: "10-14s" },
  { evidence_id: "e-candidate", kind: "visual", start: 10, end: 12, locator: "10-12s", window_id: "two" },
];
const claim = (id, start, refs, candidates = [], verification = "direct") => ({ claim_id: id, text: phrase,
  source_span: { start, end: start + Array.from(phrase).length, unit: "unicode_codepoints" },
  evidence_ids: refs, candidate_evidence_ids: candidates, verification });
const map = { schema_version: 6, task_id: "one", source_revision: revision, source_revision_kind: "normalized_note_utf8_sha256", evidence,
  claims: [claim("first", first, ["e-first", "e-repeat"]), claim("second", second, [], ["e-candidate"], "located_only")] };
const copy = value => JSON.parse(JSON.stringify(value));

test("persisted Unicode spans and disjoint intervals distinguish repeated claims and clear gaps", () => {
  const model = claimTimelineModel(map, snapshot);
  assert(model);
  assert.deepEqual(activeClaims(model, 1).map(row => row.claim.claim_id), ["first"]);
  assert.deepEqual(activeClaims(model, 6), []);
  assert.deepEqual(activeClaims(model, 11).map(row => row.claim.claim_id), ["first", "second"]);
  assert.deepEqual(activeClaims(model, 12).map(row => row.claim.claim_id), ["first"]);
  assert.deepEqual(activeClaims(model, 14), []);
  assert.deepEqual(activeClaims(model, NaN), []);
  assert.equal(model.entries[1].targets[0].candidate, true);
});

test("candidate intervals never extend a directly supported claim's playback coverage", () => {
  const extra = copy(map); extra.claims[0].candidate_evidence_ids.push("e-candidate");
  extra.evidence[2].start = 5; extra.evidence[2].end = 6;
  assert.deepEqual(activeClaims(claimTimelineModel(extra, snapshot), 5.5).map(row => row.claim.claim_id), ["second"]);
});

test("non-BMP characters within formatted claims retain exact source units and block identity", () => {
  const original = "# Header 🚀\n\n- **A 🧪 claim has exact units.**\n\n```\nA 🧪 claim has exact units.\n```";
  const statement = "**A 🧪 claim has exact units.", start = Array.from(original.slice(0, original.indexOf("**A"))).length;
  const ownRevision = createHash("sha256").update(original).digest("hex");
  const own = { ...copy(map), source_revision: ownRevision, claims: [{ ...copy(map.claims[0]), text: statement,
    source_span: { start, end: start + Array.from(statement).length, unit: "unicode_codepoints" } }] };
  assert(claimTimelineModel(own, { taskId: "one", text: original, revision: ownRevision }));
  const html = markdown.LearnNoteMarkdown.markdownToHtml(original, { sourceOffsets: true });
  assert.equal((html.match(/data-note-start/g) || []).length, 1, "Only the prose list block may receive a claim marker");
  assert.match(html, new RegExp(`data-note-start="${start - 2}"`));
  own.claims[0].source_span.end++; assert.equal(claimTimelineModel(own, { taskId: "one", text: original, revision: ownRevision }), null);
});

test("stale, absent, ambiguous and malformed maps never receive synthetic identity", () => {
  assert.equal(claimTimelineModel(null, snapshot), null);
  for (const mutate of [
    value => value.task_id = "different", value => value.source_revision = "a".repeat(64),
    value => value.schema_version = 5, value => value.requires_rebuild = true,
    value => delete value.source_revision_kind, value => delete value.claims[0].source_span,
    value => value.claims[1].claim_id = "first", value => value.evidence.push(value.evidence[0]),
    value => value.claims[0].text = "Edited text.", value => value.claims[0].source_span.start++,
    value => value.claims[1].source_span = value.claims[0].source_span,
    value => value.claims[0].source_span.unit = "utf16", value => value.claims[0].evidence_ids.push("missing"),
    value => value.claims[1].verification = "direct", value => value.claims[0].verification = "located_only",
    value => value.evidence[0].end = -1, value => value.evidence[0].start = null,
  ]) { const bad = copy(map); mutate(bad); assert.equal(claimTimelineModel(bad, snapshot), null); }
  assert.equal(claimTimelineModel(map, { ...snapshot, text: text.replace("Repeat", "Edited"), revision: "b".repeat(64) }), null);
});

class Element {
  constructor(tag = "div") {
    this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.attributes = {}; this.classes = new Set();
    this.classList = { add: name => this.classes.add(name), remove: name => this.classes.delete(name), toggle: (name, value) => value ? this.classes.add(name) : this.classes.delete(name) };
    this.hidden = false; this.scrolls = 0;
  }
  set textContent(value) { this.value = String(value); this.replaceChildren(); }
  get textContent() { return (this.value || "") + this.children.map(child => child.textContent).join(""); }
  append(...items) { for (const item of items) { item.parent = this; this.children.push(item); } }
  replaceChildren(...items) { for (const child of this.children) child.parent = null; this.children = []; this.append(...items); }
  setAttribute(key, value) { this.attributes[key] = value; }
  removeAttribute(key) { delete this.attributes[key]; }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this); this.parent = null; }
  contains(node) { return node === this || this.children.some(child => child.contains(node)); }
  querySelectorAll() { return this.children.flatMap(child => [child, ...child.querySelectorAll()]).filter(child => child.dataset.noteStart !== undefined && child.dataset.noteEnd !== undefined); }
  getBoundingClientRect() { return { top: 1000, bottom: 1100 }; }
  getClientRects() { return [1]; }
  scrollIntoView() { this.scrolls++; }
}
function harness(readMap = async () => map) {
  const note = new Element(), container = new Element(), calls = [];
  const html = markdown.LearnNoteMarkdown.markdownToHtml(text, { sourceOffsets: true });
  for (const match of html.matchAll(/data-note-start="(\d+)" data-note-end="(\d+)"/g)) {
    const block = new Element(); block.dataset.noteStart = match[1]; block.dataset.noteEnd = match[2]; note.append(block);
  }
  const doc = { createElement: tag => new Element(tag), createTextNode: value => { const node = new Element(); node.textContent = value; return node; },
    activeElement: null, documentElement: { clientHeight: 500 }, getSelection: () => doc.selection };
  let current = snapshot;
  const timeline = createClaimTimeline({ note, container, readMap, current: value => value === current,
    timestamp: value => `${value}s`, onOpen: (target, taskId) => calls.push([target.evidence_id, taskId]), document: doc });
  return { timeline, note, container, doc, calls, invalidate: () => current = null };
}

test("renderer exposes codepoint offsets without changing default Markdown or matching text", () => {
  const h = harness();
  assert.equal(claimNoteTarget(h.note, map.claims[0]), h.note.children[0]);
  assert.equal(claimNoteTarget(h.note, map.claims[1]), h.note.children[1]);
  assert.equal(h.note.children[2].dataset.noteStart, String(Array.from(text.slice(0, text.indexOf("  Continued"))).length));
  assert.doesNotMatch(markdown.LearnNoteMarkdown.markdownToHtml(text), /data-note-/);
  h.note.append(h.note.children[0]); assert.equal(claimNoteTarget(h.note, map.claims[0]), null);
  const fenced = markdown.LearnNoteMarkdown.markdownToHtml("```\nRepeated exact words.\n```", { sourceOffsets: true });
  assert.doesNotMatch(fenced, /data-note-/);
});

test("playback highlights exact occurrences; scroll is opt-in and preserves keyboard/selection control", async () => {
  const h = harness(); await h.timeline.load(snapshot);
  const firstBlock = h.note.children[0], secondBlock = h.note.children[1], firstMarker = firstBlock.children[0];
  const follow = h.container.children[2].children[0];
  h.timeline.sync(1);
  assert(firstBlock.classes.has("note-claim-active")); assert(!secondBlock.classes.has("note-claim-active"));
  assert.equal(firstMarker.attributes["aria-current"], "true"); assert.equal(firstBlock.scrolls, 0);
  follow.checked = true; follow.onchange(); assert.equal(firstBlock.scrolls, 1);
  h.timeline.sync(6); assert(!firstBlock.classes.has("note-claim-active"));
  h.doc.activeElement = firstMarker; h.timeline.sync(11);
  assert(secondBlock.classes.has("note-claim-active")); assert.equal(firstBlock.scrolls, 1); assert.equal(h.doc.activeElement, firstMarker);
  assert.match(h.container.textContent, /仅定位 · 待核对/); assert.match(h.container.textContent, /候选来源/);
  h.timeline.sync(6); h.doc.activeElement = null; h.doc.selection = { isCollapsed: false, anchorNode: firstBlock };
  h.timeline.sync(11); assert.equal(firstBlock.scrolls, 1);
  h.timeline.sync(6); h.doc.selection = null; h.timeline.sync(11); assert.equal(firstBlock.scrolls, 2);
  h.timeline.sync(14); assert(!firstBlock.classes.has("note-claim-active")); assert(!secondBlock.classes.has("note-claim-active"));
});

test("claim clicks keep all disjoint sources and reject stale callbacks after edit or reset", async () => {
  const h = harness(); await h.timeline.load(snapshot);
  h.timeline.sync(11, { scroll: false });
  const list = h.container.children[3], firstRow = list.children[0];
  await firstRow.children[2].onclick(); assert.deepEqual(h.calls, [["e-repeat", "one"]]);
  const click = h.note.children[0].children[0].onclick;
  h.invalidate(); await click(); assert.equal(h.calls.length, 1);
  h.timeline.sync(1); assert(!h.note.children[0].classes.has("note-claim-active"));
  h.timeline.reset(); await click(); assert.equal(h.calls.length, 1); assert.equal(h.container.hidden, true);
});

test("playback does not remove the source button under keyboard focus", async () => {
  const h = harness(); await h.timeline.load(snapshot); h.timeline.sync(11);
  const list = h.container.children[3], button = list.children[0].children[1];
  h.doc.activeElement = button; h.timeline.sync(6);
  assert(list.contains(button)); assert.equal(h.doc.activeElement, button);
  assert.match(h.container.textContent, /保留当前键盘操作/);
  assert(!h.note.children[0].classes.has("note-claim-active"));
  h.doc.activeElement = null; list.onfocusout(); await new Promise(resolve => queueMicrotask(resolve));
  assert.equal(list.children.length, 0); assert.match(h.container.textContent, /没有精确匹配/);
});

test("missing note targets stay unavailable rather than highlighting identical prose elsewhere", async () => {
  const h = harness(); h.note.children[1].dataset.noteStart = "999";
  await h.timeline.load(snapshot); h.timeline.sync(11);
  assert.equal(h.note.children[1].children.length, 0);
  assert.match(h.container.textContent, /笔记定位标记缺失/);
});

test("late map success/failure after navigation and reordered reloads cannot replace the new reader", async () => {
  for (const fail of [false, true]) {
    let resolve, reject;
    const h = harness(() => new Promise((yes, no) => { resolve = yes; reject = no; }));
    const pending = h.timeline.load(snapshot); h.invalidate(); h.timeline.reset();
    if (fail) reject(new Error("late")); else resolve(map);
    await pending; assert.equal(h.container.children.length, 0); assert.equal(h.note.children[0].children.length, 0);
  }
  const pending = [], h = harness(() => new Promise(resolve => pending.push(resolve)));
  const older = h.timeline.load(snapshot), latest = h.timeline.load(snapshot);
  pending[1](map); await latest;
  pending[0](null); await older;
  assert.equal(h.note.children[0].children.length, 1); assert.doesNotMatch(h.container.textContent, /已停用/);
});

test("no media is needed to select a claim; unavailable maps leave the note and source readable", async () => {
  const h = harness(); await h.timeline.load(snapshot);
  await h.note.children[0].children[0].onclick(); assert.deepEqual(h.calls, [["e-first", "one"]]);
  h.timeline.sync(1, { scroll: false }); assert(h.note.children[0].classes.has("note-claim-active"));
  await h.timeline.load({ ...snapshot, revision: "f".repeat(64) }); // Simulates a reader revision no longer current.
  assert.equal(h.note.children[0].children.length, 0);
  const missing = harness(async () => null); await missing.timeline.load(snapshot);
  assert.match(missing.container.textContent, /已停用/); assert.equal(missing.note.children.length, 3);
});

test("claims, cards and question citations resolve the same canonical source without title/URL guesses", () => {
  const items = [{ kind: "task", id: "one", title: "Same" }, { kind: "task", id: "other", title: "Same" }, { kind: "material", id: "doc" }];
  assert.equal(claimEvidenceAnchor(evidence[1], "one", items).source, items[0]);
  assert.equal(evidenceAnchor({ task_id: "one", locator: "10-14s" }, items).source, items[0]);
  assert.equal(citationAnchor({ source_kind: "task", source_id: "one", start: 10, end: 14 }, null, items).source, items[0]);
  assert.equal(citationAnchor({ start: 10 }, items[0], items).source, items[0]);
  assert.equal(citationAnchor({ source_kind: "task", start: 10 }, items[0], items), null);
  assert.equal(citationAnchor({ source_kind: "task", source_id: "missing", start: 10, title: "Same" }, null, items), null);
  assert.equal(citationAnchor({ start: -1 }, items[0], items), null);
  assert.equal(citationAnchor({ start: 10, end: 2 }, items[0], items), null);
  assert.equal(evidenceAnchor({ task_id: "one", metadata: { material_id: "doc" } }, items), null);
  assert.equal(evidenceAnchor({ task_id: "one" }, [...items, items[0]]), null);
  assert.equal(claimEvidenceAnchor({ kind: "document", evidence_id: "doc-source", material_id: "missing" }, "one", items), null);
});


function navigationHarness() {
  const desk = readFileSync(new URL("../desk.js", import.meta.url), "utf8"), calls = [], requests = new Map();
  const one = { kind: "task", id: "one" }, two = { kind: "task", id: "two" };
  const state = { epoch: 1, selected: one, items: [one, two], editing: false };
  let allow = true, finishOpen;
  const context = vm.createContext({ state, evidenceAnchor, claimEvidenceAnchor, citationAnchor, guard: () => allow,
    api: path => new Promise((resolve, reject) => requests.set(path, { resolve, reject })),
    openItem: item => { calls.push(["item", item.id]); state.selected = item; state.epoch++; return new Promise(resolve => finishOpen = resolve); },
    openSource: async (seconds, item, target) => calls.push(["source", item.id, seconds, target.windowId || ""]),
  });
  vm.runInContext(desk.slice(desk.indexOf("let evidenceRequest = 0;"), desk.indexOf("async function drawReview()")), context);
  return { context, calls, requests, state, one, two, deny: () => allow = false, finishOpen: () => finishOpen() };
}

test("shared production navigation routes claims/cards/QA through one anchor without reopening the same reader", async () => {
  const h = navigationHarness();
  await h.context.openClaimEvidence(evidence[2], "one");
  await h.context.openCitation({ source_kind: "task", source_id: "one", start: 10, end: 12, window_id: "two" });
  const card = h.context.openEvidence("canonical");
  h.requests.get("/api/knowledge/evidence/canonical").resolve({ evidence: { evidence_id: "canonical", task_id: "one", metadata: { start: 10, end: 12, window_id: "two" } } });
  await card;
  assert.deepEqual(h.calls, Array.from({ length: 3 }, () => ["source", "one", 10, "two"]));
  h.state.editing = true; h.deny(); await h.context.openCitation({ start: 2 }, h.one);
  assert.equal(h.calls.length, 3, "A refused dirty-reader guard must block even same-source navigation");
});

test("canonical lookups reject missing/wrong IDs, ignore obsolete errors and cannot overtake a newer citation", async () => {
  const h = navigationHarness();
  for (const result of [{ evidence: {} }, { evidence: { evidence_id: "wrong", task_id: "one" } }]) {
    const pending = h.context.openEvidence("exact"); h.requests.get("/api/knowledge/evidence/exact").resolve(result);
    await assert.rejects(pending, /出处索引不一致/);
  }
  const older = h.context.openEvidence("old");
  await h.context.openCitation({ start: 10 }, h.one);
  h.requests.get("/api/knowledge/evidence/old").reject(new Error("obsolete network error")); await older;
  assert.equal(h.calls.length, 1);
  const abandoned = h.context.openEvidence("abandoned"); h.state.epoch++;
  h.requests.get("/api/knowledge/evidence/abandoned").resolve({ evidence: { evidence_id: "abandoned", task_id: "two", locator: "0-3s" } });
  await abandoned; assert.equal(h.calls.length, 1);
});

test("a manual round trip during source loading invalidates the old seek even when the source ID matches again", async () => {
  const h = navigationHarness();
  const pending = h.context.openCitation({ source_kind: "task", source_id: "two", start: 10 });
  h.state.selected = h.one; h.state.epoch++;
  h.state.selected = h.two; h.state.epoch++;
  h.finishOpen(); await pending;
  assert.deepEqual(h.calls, [["item", "two"]]);
});


test("closing the production source panel cancels an outstanding canonical lookup", async () => {
  const h = navigationHarness(), nodes = new Map();
  const $ = id => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
  $("player").pause = () => {};
  Object.assign(h.context, { $, sourceRequest: 0, sourceCueCleanup: null, sourceCueRender: null, sourceWindowRender: null,
    claimTimeline: { clearActive() {} }, document: { body: new Element() } });
  const desk = readFileSync(new URL("../desk.js", import.meta.url), "utf8");
  vm.runInContext(desk.slice(desk.indexOf("function closeSource("), desk.indexOf("let inlineSourceRequest")), h.context);
  const pending = h.context.openEvidence("closed"); h.context.closeSource();
  h.requests.get("/api/knowledge/evidence/closed").resolve({ evidence: { evidence_id: "closed", task_id: "one", locator: "10-12s" } });
  await pending; assert.deepEqual(h.calls, []); assert.equal($("sourcePanel").hidden, true);
});
