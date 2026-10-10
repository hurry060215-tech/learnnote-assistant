import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import test from "node:test";
const source = readFileSync(new URL("../desk.js", import.meta.url), "utf8");
function harness() {
  const selected = { id: "task-a", kind: "task", updated_at: "t1", status: "running", summary_source: "partial-draft",
    options: { visual_understanding: true }, artifact_status: { partial_draft_available: true } };
  const state = { selected, epoch: 1, editing: false }, pending = [], applied = [], ordinary = [];
  const nodes = new Map();
  const $ = id => { if (!nodes.has(id)) nodes.set(id, { dataset: {}, querySelector: () => null }); return nodes.get(id); };
  const context = vm.createContext({ state, $, document: { scrollingElement: {} }, timestamp: value => value,
    LearnNoteMarkdown: { configure() {}, markdownToHtml: value => value }, taskAsset: () => "", openSource() {}, failure() {}, decorateSourceTimes() {},
    sourcePath: value => `/editions/${value.id}`, api: path => new Promise((resolve, reject) => pending.push({ path, resolve, reject })),
    createSectionReader: () => ({ render: (projection, task, edition) => { applied.push({ projection, task, edition }); return !!projection?.accepted && !edition.edited; }, clear() {} }),
    renderEditionStable: (...args) => ordinary.push(args), renderNote() {},
  });
  vm.runInContext(source.slice(source.indexOf("let editionRequest ="), source.indexOf("function renderNote()")), context);
  const complete = (start, revision, accepted = true, edited = false) => {
    pending[start].resolve({ revision, text: revision, edited });
    pending[start + 1].resolve({ accepted });
  };
  return { context, state, pending, applied, ordinary, $, complete };
}

test("same-selection overlapping reads only apply the most recent edition and projection", async () => {
  const h = harness(), first = h.context.loadEdition(1), second = h.context.loadEdition(1);
  h.complete(2, "new"); await second; h.complete(0, "old"); await first;
  assert.equal(h.state.text, "new"); assert.equal(h.applied.length, 1);
  assert.equal(h.$("document").dataset.readerRevision, "new:partial-draft:");
});

test("navigation, editing, or refreshed metadata rejects an older draft response", async () => {
  for (const mutate of [h => h.state.epoch++, h => { h.state.editing = true; },
    h => { h.state.selected = { ...h.state.selected, updated_at: "t2" }; }]) {
    const h = harness(), request = h.context.loadEdition(1); mutate(h); h.complete(0, "stale"); await request;
    assert.equal(h.applied.length, 0); assert.equal(h.ordinary.length, 0);
  }
});

test("edited editions and unavailable projection use the saved Markdown; same revision still replaces progressive DOM", async () => {
  for (const edited of [false, true]) {
    const h = harness(); h.$("document").dataset.readerRevision = "same:partial-draft:";
    h.$("document").querySelector = () => ({});
    const request = h.context.loadEdition(1); h.complete(0, "same", edited, edited); await request;
    assert.equal(h.ordinary.length, 1);
    assert.equal(h.$("document").dataset.readerRevision, undefined);
    assert.equal(h.state.text, "same");
  }
});

test("projection endpoint failure does not discard the readable saved edition", async () => {
  const h = harness(), request = h.context.loadEdition(1);
  h.pending[0].resolve({ revision: "fallback", text: "saved" }); h.pending[1].reject(new Error("unavailable")); await request;
  assert.equal(h.state.text, "saved"); assert.equal(h.ordinary.length, 1);
});
