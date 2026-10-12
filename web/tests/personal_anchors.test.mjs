import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const code = readFileSync(new URL("../personal-anchors.js", import.meta.url), "utf8");
const { installAnnotationAnchors, annotationStatusMessage } = await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);
const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };

function pickerFixture() {
  const elements = new Map();
  class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.listeners = {}; this.disabled = false; this.value = ""; }
    set innerHTML(_value) {
      for (const id of ["annotationAnchorKind", "annotationAnchorTarget", "annotationAnchorEnd", "annotationAnchorEndLabel", "applyAnnotationAnchor", "annotationAnchorStatus"]) elements.set(id, new Element(id));
      elements.get("annotationAnchorKind").value = "claim";
    }
    append(child) { this.children.push(child); if (!this.value) this.value = child.value; }
    replaceChildren() { this.children = []; this.value = ""; }
    get options() { return this.children; }
    setAttribute(name, value) { this[name] = value; }
    querySelector(selector) { return elements.get(selector.slice(1)); }
    addEventListener(name, fn) { this.listeners[name] = fn; }
  }
  for (const id of ["annotationForm", "annotationQuote"]) elements.set(id, new Element(id));
  const document = { createElement: tag => new Element(tag), getElementById: id => elements.get(id) };
  const state = { selected: { kind: "task", id: "first" }, annotationEditingAnchor: {}, annotationQuote: "  Exact user quote\r\n", annotationQuoteReanchored: true };
  const requests = [];
  const picker = installAnnotationAnchors({ state, document, notice() {}, api: (url, init) => { const d = deferred(); requests.push({ url, init, ...d }); return d.promise; } });
  const element = elements.get("annotationForm").children[0];
  const toggle = open => { element.open = open; element.listeners.toggle(); };
  return { picker, state, requests, elements, element, toggle };
}

const target = (kind, id) => ({ label: "<literal> cafe\u0301 🧭", anchor: { kind, source_task_id: id, claim_id: "claim-exact", target_hash: "literal-hash", source_revision: "literal-revision" } });

test("picker stores only the selected exact source and preserves quote text", async () => {
  const f = pickerFixture(); f.toggle(true);
  f.requests[0].resolve({ targets: [target("claim", "first")] }); await tick();
  assert.equal(f.elements.get("annotationAnchorTarget").options[0].textContent, "<literal> cafe\u0301 🧭");
  f.elements.get("applyAnnotationAnchor").onclick();
  assert.deepEqual(f.state.annotationEditingAnchor, target("claim", "first").anchor);
  assert.equal(f.state.annotationQuote, "  Exact user quote\r\n");
  assert.equal(f.state.annotationQuoteReanchored, false);
});

test("abandoned selection and closed picker ignore late source lookups", async () => {
  const f = pickerFixture(); f.toggle(true);
  f.state.selected = { kind: "task", id: "next" }; f.picker.reset();
  f.requests[0].resolve({ targets: [target("claim", "first")] }); await tick();
  assert.equal(f.elements.get("annotationAnchorTarget").options.length, 0);
  f.toggle(true); f.toggle(false);
  f.requests[1].resolve({ targets: [target("claim", "next")] }); await tick();
  assert.equal(f.elements.get("annotationAnchorTarget").options.length, 0);
  assert.deepEqual(f.state.annotationEditingAnchor, {});
});

test("unavailable target stays visible and reopening retries", async () => {
  const f = pickerFixture(); f.toggle(true);
  f.requests[0].reject(new Error("unavailable")); await tick();
  assert.equal(f.elements.get("applyAnnotationAnchor").disabled, true);
  assert.match(f.elements.get("annotationAnchorStatus").textContent, /稍后重新打开以重试/);
  f.toggle(false); f.toggle(true);
  f.requests[1].resolve({ targets: [target("claim", "first")] }); await tick();
  assert.equal(f.elements.get("applyAnnotationAnchor").disabled, false);
  assert.match(annotationStatusMessage({ anchor_status: { resolution: "orphaned", reason: "ambiguous_target" } }), /多个相同来源/);
});

async function intervalFixture() {
  const f = pickerFixture(); f.toggle(true);
  const cues = [0, 1, 2].map(index => ({ label: `Cue ${index}`, anchor: { kind: "transcript", source_task_id: "first",
    evidence_id: `task-first-transcript-0000${index}`, source_revision: "current", target_hash: `hash-${index}`, start: index, end: index + 2 } }));
  f.requests[0].resolve({ targets: [...cues, target("claim", "first")] }); await tick();
  const kind = f.elements.get("annotationAnchorKind"), select = f.elements.get("annotationAnchorTarget"), end = f.elements.get("annotationAnchorEnd");
  kind.value = "transcript"; kind.onchange(); end.value = "2"; end.onchange();
  return { ...f, kind, select, end, cues, apply: f.elements.get("applyAnnotationAnchor"),
    anchor: { ...cues[0].anchor, end: 4, evidence_id: "synthetic-range", cues: cues.map(cue => cue.anchor) } };
}

test("adjacent subtitle selection awaits the server interval and preserves literal quote", async () => {
  const f = await intervalFixture();
  assert.equal(f.end.hidden, false); assert.equal(f.end.options.length, 3);
  const pending = f.apply.onclick(); await f.apply.onclick();
  assert.equal(f.requests.length, 2); assert.equal(f.state.annotationAnchorLoading, true);
  assert.deepEqual(f.state.annotationEditingAnchor, {});
  assert.equal(f.requests[1].url, "/api/personal/task/first/transcript-interval");
  assert.deepEqual(JSON.parse(f.requests[1].init.body), { first_evidence_id: f.cues[0].anchor.evidence_id,
    last_evidence_id: f.cues[2].anchor.evidence_id, source_revision: "current" });
  f.requests[1].resolve({ anchor: f.anchor }); await pending;
  assert.deepEqual(f.state.annotationEditingAnchor, f.anchor);
  assert.equal(f.state.annotationQuote, "  Exact user quote\r\n");
  assert.equal(f.state.annotationQuoteReanchored, false);
  assert.equal(f.state.annotationAnchorLoading, false);
});

test("changed endpoints, kind, closure and source discard late interval responses", async () => {
  for (const change of [f => { f.select.value = "1"; f.select.onchange(); },
    f => { f.end.value = "1"; f.end.onchange(); },
    f => { f.kind.value = "claim"; f.kind.onchange(); },
    f => f.toggle(false), f => { f.state.selected = { kind: "task", id: "next" }; f.picker.reset(); }]) {
    const f = await intervalFixture(); const pending = f.apply.onclick(); change(f);
    f.requests[1].resolve({ anchor: f.anchor }); await pending;
    assert.deepEqual(f.state.annotationEditingAnchor, {});
    assert.equal(f.state.annotationAnchorLoading, false);
    assert.equal(f.state.annotationQuoteReanchored, true);
  }
});

test("stale interval keeps the existing anchor and enables a reviewed retry", async () => {
  const f = await intervalFixture(), existing = target("claim", "first").anchor;
  f.state.annotationEditingAnchor = existing;
  const pending = f.apply.onclick(); f.requests[1].reject(new Error("annotation_anchor_stale")); await pending;
  assert.deepEqual(f.state.annotationEditingAnchor, existing);
  assert.equal(f.state.annotationQuote, "  Exact user quote\r\n");
  assert.equal(f.state.annotationAnchorLoading, false); assert.equal(f.apply.disabled, false);
  assert.match(f.elements.get("annotationAnchorStatus").textContent, /重新打开并选择/);
  f.select.value = "1"; f.select.onchange();
  assert.deepEqual(f.end.options.map(option => option.value), ["1", "2"]);
  await f.apply.onclick();
  assert.deepEqual(f.state.annotationEditingAnchor, f.cues[1].anchor);
  assert.equal(f.requests.length, 2);
});

test("a superseded interval error cannot unlock or replace a newer selection", async () => {
  const f = await intervalFixture(), old = f.apply.onclick();
  f.end.value = "1"; f.end.onchange();
  assert.match(f.elements.get("annotationAnchorStatus").textContent, /选定并关联后保存/);
  const latest = f.apply.onclick();
  f.requests[1].reject(new Error("obsolete error")); await old;
  assert.equal(f.apply.disabled, true); assert.equal(f.state.annotationAnchorLoading, true);
  assert.deepEqual(f.state.annotationEditingAnchor, {});
  const current = { ...f.anchor, end: 3, cues: f.anchor.cues.slice(0, 2) };
  f.requests[2].resolve({ anchor: current }); await latest;
  assert.deepEqual(f.state.annotationEditingAnchor, current);
  assert.equal(f.state.annotationAnchorLoading, false);
});

function formFixture() {
  const desk = readFileSync(new URL("../desk.js", import.meta.url), "utf8");
  const elements = Object.fromEntries(["annotationForm", "annotationText", "annotationQuote", "saveAnnotation", "cancelAnnotationEdit"].map(id => [id, { value: "", disabled: false }]));
  const controls = [elements.annotationText, elements.saveAnnotation, elements.cancelAnnotationEdit];
  elements.annotationForm.querySelectorAll = () => controls;
  elements.annotationText.value = "\n  User code 🧭\n\n";
  const state = { epoch: 1, selected: { kind: "task", id: "first" }, annotationEditingId: "", annotationEditingAnchor: {},
    annotationQuote: " literal quote ", annotationRevision: "", annotationRequestId: "", annotationSaving: false };
  const requests = [], notices = [];
  const context = vm.createContext({ state, $: id => elements[id], crypto: { randomUUID: () => "one-retry-id" },
    api: (url, init) => { const d = deferred(); requests.push({ url, payload: JSON.parse(init.body), ...d }); return d.promise; },
    personalAnchorPicker: { reset() {} }, loadAnnotations: async () => {}, notice: text => notices.push(text), failure: error => notices.push(error.message),
  });
  vm.runInContext(desk.slice(desk.indexOf('$("annotationForm").onsubmit ='), desk.indexOf('$("captureAnnotationQuote").onclick =')), context);
  const submit = () => elements.annotationForm.onsubmit({ preventDefault() {}, submitter: elements.saveAnnotation });
  return { state, elements, controls, requests, notices, submit };
}

test("saving while interval verification is pending keeps the draft without submitting an old anchor", async () => {
  const f = formFixture(); f.state.annotationAnchorLoading = true;
  await f.submit();
  assert.equal(f.requests.length, 0);
  assert.equal(f.elements.annotationText.value, "\n  User code 🧭\n\n");
  assert.match(f.notices[0], /正在核对字幕区间/);
});

test("double submit is suppressed and lost response retries one identity without changing text", async () => {
  const f = formFixture(); const first = f.submit(); await f.submit();
  assert.equal(f.requests.length, 1);
  assert.ok(f.controls.every(control => control.disabled));
  f.requests[0].reject(new Error("network interrupted")); await first;
  assert.equal(f.elements.annotationText.value, "\n  User code 🧭\n\n");
  assert.ok(f.controls.every(control => !control.disabled));
  const retry = f.submit();
  assert.deepEqual(f.requests[1].payload, f.requests[0].payload);
  f.requests[1].resolve({ annotation: {} }); await retry;
  assert.equal(f.elements.annotationText.value, "");
  assert.equal(f.state.annotationRequestId, "");
});

test("stale edit retains the draft, while an old source save cannot clear a new source", async () => {
  const f = formFixture(); f.state.annotationEditingId = "existing"; f.state.annotationRevision = "old-revision";
  const save = f.submit();
  assert.equal(f.requests[0].payload.revision, "old-revision");
  f.requests[0].reject(new Error("annotation_revision_conflict")); await save;
  assert.equal(f.elements.annotationText.value, "\n  User code 🧭\n\n");
  assert.match(f.notices[0], /其他页面修改/);
  const older = f.submit(); f.state.epoch++; f.state.selected = { kind: "task", id: "next" };
  f.elements.annotationText.value = "New source draft.";
  f.requests[1].resolve({ annotation: {} }); await older;
  assert.equal(f.elements.annotationText.value, "New source draft.");
});

test("a rejected save from the previous source does not announce an obsolete error", async () => {
  const f = formFixture(); const old = f.submit();
  f.state.epoch++; f.state.selected = { kind: "task", id: "next" };
  f.elements.annotationText.value = "New source draft.";
  f.requests[0].reject(new Error("annotation_revision_conflict")); await old;
  assert.deepEqual(f.notices, []);
  assert.equal(f.elements.annotationText.value, "New source draft.");
  assert.equal(f.state.annotationSaving, false);
});

test("the existing localization engine skips literal personal-content nodes", () => {
  const text = "\r\n  完成后打开笔记 cafe\u0301 🧭\r\n";
  const node = { nodeValue: text, parentElement: { closest: selector => selector.includes("[data-user-content]") ? {} : null } };
  const context = {};
  vm.runInNewContext(readFileSync(new URL("../i18n.js", import.meta.url), "utf8"), context);
  const document = { body: {}, querySelectorAll: () => [{ contains: () => true }],
    createTreeWalker: () => { let first = true; return { nextNode: () => first ? (first = false, node) : null }; } };
  context.LearnNoteI18n.applyStatic(document, "en-US");
  assert.equal(node.nodeValue, text);
  context.LearnNoteI18n.applyStatic(document, "zh-CN");
  assert.equal(node.nodeValue, text);
});
