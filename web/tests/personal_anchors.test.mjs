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
      for (const id of ["annotationAnchorKind", "annotationAnchorTarget", "applyAnnotationAnchor", "annotationAnchorStatus"]) elements.set(id, new Element(id));
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
  const picker = installAnnotationAnchors({ state, document, notice() {}, api: url => { const d = deferred(); requests.push({ url, ...d }); return d.promise; } });
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
