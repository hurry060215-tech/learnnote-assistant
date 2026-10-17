// Actual asynchronous edition admission + stable renderer; synthetic layout only.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import test from "node:test";
const read = name => fs.readFileSync(new URL(`../${name}`, import.meta.url), "utf8");
const { renderEditionStable } = await import(`data:text/javascript;base64,${Buffer.from(read("reader-progress.js")).toString("base64")}`);
const desk = read("desk.js");
function harness() {
  let scroll = 1000, y = 1140, renders = 0;
  const scroller = { ownerDocument: {}, get scrollTop() { return scroll; }, set scrollTop(value) { scroll = value; } };
  scroller.ownerDocument.scrollingElement = scroller;
  const node = () => ({ tagName: "H2", textContent: "Reading outline", isConnected: true,
    getBoundingClientRect: () => ({ top: y - scroll, bottom: y - scroll + 35 }),
    scrollIntoView() { if (this.isConnected) scroll = y - 140; } });
  let heading = node();
  const reader = { isConnected: true, hidden: false,
    dataset: { readerSource: "task:a", readerRevision: "before::", sourceRevision: "before" },
    querySelector: () => null, querySelectorAll: () => [heading] };
  const task = { kind: "task", id: "a", status: "running", summary_source: "transcript-draft", updated_at: "one", options: {} };
  const state = { epoch: 1, selected: task, editing: false }, pending = [];
  const context = vm.createContext({ claimMapVersion: task => JSON.stringify([task?.control_generation, task?.control_retry_count, task?.updated_at]), state, $: id => id === "document" ? reader : { dataset: {} },
    api: () => new Promise(resolve => pending.push(resolve)), sourcePath: selected => `/edition/${selected.id}`,
    LearnNoteMarkdown: { configure() {} }, taskAsset: value => value, sectionReader: { render: () => false },
    renderEditionStable, document: { scrollingElement: scroller }, loadClaimTimeline() {},
    renderNote() {
      renders++; heading.isConnected = false; heading = node();
      // Native anchoring preserves the passage while an earlier section grows.
      y += 1187; scroll += 1187;
    } });
  vm.runInContext('let editionRequest = 0;' + desk.slice(desk.indexOf("async function loadEdition("), desk.indexOf("function renderNote()")), context);
  const edition = revision => ({ text: `Edition ${revision}`, revision });
  return { context, state, reader, scroller, pending, edition, heading: () => heading, renders: () => renders };
}

test("a delayed production edition response preserves the user's current passage and exposes obsolete node handles", async () => {
  const h = harness(), waiting = h.context.loadEdition(1), oldNode = h.heading();
  h.scroller.scrollTop += 200; // A newer user scroll while HTTP is unresolved.
  const before = oldNode.getBoundingClientRect().top;
  h.pending[0](h.edition("after")); await waiting;
  assert.equal(h.renders(), 1); assert.equal(h.heading().getBoundingClientRect().top, before);
  assert.equal(h.scroller.scrollTop, 2387);
  assert.equal(oldNode.isConnected, false); assert.notEqual(h.heading(), oldNode);
  oldNode.scrollIntoView();
  assert.equal(h.scroller.scrollTop, 2387, "A detached handle cannot establish scrolling of the current reader");
  assert.equal(h.reader.dataset.readerSource, "task:a");
  assert.equal(h.reader.dataset.readerRevision, "after::");
});

test("late edition responses cannot render after newer navigation, task generation or editing", async () => {
  for (const mutate of [h => h.state.epoch++, h => { h.state.selected = { ...h.state.selected, id: "b" }; },
    h => { h.state.selected = { ...h.state.selected, updated_at: "new-generation" }; },
    h => { h.state.selected = { ...h.state.selected, control_generation: "new-attempt" }; },
    h => { h.state.selected = { ...h.state.selected, control_retry_count: 2 }; }, h => { h.state.editing = true; }]) {
    const h = harness(), waiting = h.context.loadEdition(1), oldNode = h.heading(); mutate(h);
    h.scroller.scrollTop = 200;
    h.pending[0](h.edition("obsolete")); await waiting;
    assert.equal(h.renders(), 0); assert.equal(h.heading(), oldNode); assert.equal(h.scroller.scrollTop, 200);
  }
});

test("newer edition request wins and unchanged revision preserves DOM and scroll", async () => {
  const h = harness(), first = h.context.loadEdition(1), second = h.context.loadEdition(1), node = h.heading();
  h.pending[1](h.edition("before")); await second;
  h.pending[0](h.edition("obsolete")); await first;
  assert.equal(h.renders(), 0); assert.equal(h.heading(), node); assert.equal(h.scroller.scrollTop, 1000);
});
