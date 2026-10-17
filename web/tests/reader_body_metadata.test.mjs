// Actual edition admission, Markdown body rendering, and metadata projection.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import test from "node:test";
const source = name => readFileSync(new URL(`../${name}`, import.meta.url), "utf8");
const imported = name => import(`data:text/javascript;base64,${Buffer.from(source(name)).toString("base64")}`);
const { renderEditionStable } = await imported("reader-progress.js");
const { claimMapVersion } = await imported("claim-timeline.js");
const desk = source("desk.js"), product = source("desk-product.js");
function harness() {
  let scroll = 1292, html = "", writes = 0, claims = 0, reviews = 0, progressive = false, projected = false;
  const node = () => ({ tagName: "H2", textContent: "Reading outline", isConnected: true,
    getBoundingClientRect: () => ({ top: 1431.625 - scroll, bottom: 1466.625 - scroll }) });
  let heading = node();
  const selection = { anchorNode: null, focusNode: null, anchorOffset: 0, focusOffset: 0 };
  const document = { activeElement: null };
  const reader = { dataset: {}, isConnected: true, hidden: false, querySelector: () => projected ? {} : null,
    querySelectorAll: () => [heading], get innerHTML() { return html; }, set innerHTML(value) {
      writes++; heading.isConnected = false; heading = node(); html = value;
      selection.anchorNode = selection.focusNode = null; document.activeElement = null;
    } };
  const scroller = { ownerDocument: document, get scrollTop() { return scroll; }, set scrollTop(value) { scroll = value; } };
  document.scrollingElement = scroller;
  const state = { epoch: 72, editing: false, selected: { id: "owned", kind: "task", title: "Reference source", status: "running",
    summary_source: "", updated_at: "one", control_generation: "generation-one", options: {}, transcript_path: "retained.json" },
    personalReview: { load() { reviews++; }, reset() {} } };
  let edition = { text: "# Reference source\n\n## Reading outline\n\nRetained literal caption.", revision: "same-content", edited: false };
  const pending = [], listeners = {}, nodes = new Map([["document", reader]]);
  const $ = id => { if (id === "reviewNoteSources") return null; if (!nodes.has(id)) nodes.set(id, { dataset: {} }); return nodes.get(id); };
  const context = vm.createContext({ state, claimMapVersion, $, document, readerNav: {}, timestamp: () => "3:00",
    api: route => new Promise(resolve => pending.push(() => resolve(route.endsWith("/partial-note") ? { actualProjection: true } : { ...edition }))),
    sourcePath: selected => `/edition/${selected.kind}/${selected.id}`, LearnNoteMarkdown: { configure() {}, markdownToHtml: text => `<main>${text}</main>` },
    taskAsset: value => value, renderEditionStable, sectionReader: { clear() { projected = false; }, render() { if (progressive) projected = true; return progressive; } },
    claimTimeline: { reset() {} }, loadClaimTimeline() { claims++; }, esc: value => value, canOcrMaterial: () => false,
    mountMaterialOcr() {}, collapseSourceReviews() {}, decorateSourceTimes() {},
    window: { dispatchEvent() {}, addEventListener: (name, callback) => { listeners[name] = callback; } }, Event });
  vm.runInContext('let editionRequest = 0;' + desk.slice(desk.indexOf("async function loadEdition("), desk.indexOf("function decorateSourceTimes(")), context);
  vm.runInContext(product.slice(product.indexOf("  function updateReadingContext() {"), product.indexOf('  $("sourceFrames").onclick =')), context);
  const flush = async promise => { for (const resolve of pending.splice(0)) resolve(); await promise; };
  return { context, state, reader, document, selection, scroller, $, flush,
    load: () => flush(context.loadEdition(state.epoch)), heading: () => heading, writes: () => writes,
    claims: () => claims, reviews: () => reviews, setEdition: value => { edition = { ...edition, ...value }; },
    setProgressive: value => { progressive = value; },
    metadata: () => listeners["learnnote:metadata"]({ detail: { id: state.selected.id, kind: state.selected.kind, epoch: state.epoch } }),
    select() { selection.anchorNode = selection.focusNode = heading; selection.anchorOffset = 2; selection.focusOffset = 8; document.activeElement = heading; } };
}

test("same-content empty and transcript-draft metadata preserve actual body, selection, focus and user scroll", async () => {
  for (const initial of ["", "transcript-draft"]) {
    const h = harness(); h.state.selected.summary_source = initial; await h.load(); h.select();
    const node = h.heading(), html = h.reader.innerHTML, selected = { ...h.selection }, focus = h.document.activeElement;
    h.scroller.scrollTop += 120;
    h.state.selected = { ...h.state.selected, summary_source: initial ? "" : "transcript-draft", updated_at: "two" };
    h.metadata(); await h.load();
    assert.equal(h.writes(), 1, "Metadata-only arrival must not rewrite identical Markdown HTML");
    assert.equal(h.reader.innerHTML, html); assert.equal(h.heading(), node); assert.equal(node.isConnected, true);
    assert.deepEqual(h.selection, selected); assert.equal(h.document.activeElement, focus); assert.equal(h.scroller.scrollTop, 1412);
    assert.equal(h.$("readerMetadata").textContent, "字幕已取得 · 等待总结");
    assert.equal(h.claims(), 2); assert.equal(h.reviews(), 1, "Evidence and review refresh still run without replacing prose");
    h.state.selected = { ...h.state.selected, status: "cancelled", updated_at: "three" }; h.metadata(); await h.load();
    assert.equal(h.$("readerMetadata").textContent, "已停止 · 字幕已保留");
    assert.equal(h.heading(), node); assert.equal(h.writes(), 1); assert.equal(h.document.activeElement, focus);
  }
});

test("genuine revisions, source changes and other summary modes still render", async () => {
  for (const mutate of [h => h.setEdition({ revision: "new-content", text: "# Revised source" }),
    h => { h.state.selected = { ...h.state.selected, id: "other" }; },
    ...["local-template", "subtitle-extract", "text-llm", "partial-draft"].map(summary_source => h => { h.state.selected = { ...h.state.selected, summary_source }; })]) {
    const h = harness(); await h.load(); h.select(); const old = h.heading(); mutate(h); await h.load();
    assert.equal(h.writes(), 2); assert.equal(old.isConnected, false); assert.notEqual(h.heading(), old);
    if (h.state.selected.summary_source === "local-template") assert.match(h.reader.innerHTML, /字幕摘录/);
    if (h.state.selected.summary_source === "text-llm") assert.match(h.reader.innerHTML, /生成完成不代表逐条事实已验证/);
  }
});

test("material summary-source and OCR revision keys remain distinct", async () => {
  for (const mutate of [h => { h.state.selected.summary_source = "transcript-draft"; },
    h => { h.state.selected.metadata.source_revision = "ocr-two"; }]) {
    const h = harness(); h.state.selected = { ...h.state.selected, kind: "material", metadata: { ocr_performed: true, source_revision: "ocr-one" } };
    await h.load(); mutate(h); await h.load(); assert.equal(h.writes(), 2);
  }
});

test("progressive entry and exit keep their existing projection boundary", async () => {
  const h = harness(); await h.load();
  h.state.selected = { ...h.state.selected, summary_source: "transcript-draft", options: { visual_understanding: true }, artifact_status: { draft_available: true } };
  h.setProgressive(true); await h.load();
  assert.equal(h.reader.dataset.readerRevision, "same-content:transcript-draft:");
  assert.equal(h.writes(), 1);
  h.setProgressive(false); await h.load(); assert.equal(h.writes(), 2, "Leaving progressive DOM must rebuild the Markdown reader");
});

test("pending same-content metadata loads still reject changed source, generation, evidence, epoch and editing", async () => {
  for (const mutate of [h => h.state.epoch++, h => { h.state.editing = true; },
    h => { h.state.selected = { ...h.state.selected, id: "other" }; },
    h => { h.state.selected = { ...h.state.selected, kind: "material" }; },
    h => { h.state.selected = { ...h.state.selected, control_generation: "generation-two" }; },
    h => { h.state.selected = { ...h.state.selected, claim_evidence: { path: "new-evidence.json" } }; }]) {
    const h = harness(); await h.load(); h.select(); const node = h.heading();
    h.state.selected = { ...h.state.selected, summary_source: "transcript-draft", updated_at: "two" };
    const loading = h.context.loadEdition(h.state.epoch); mutate(h); await h.flush(loading);
    assert.equal(h.writes(), 1); assert.equal(h.heading(), node); assert.equal(h.document.activeElement, node);
    assert.equal(h.reviews(), 0, "A rejected response cannot refresh an obsolete source");
  }
});
