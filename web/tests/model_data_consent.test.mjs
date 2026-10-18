import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../model-data-consent.js", import.meta.url), "utf8");
function harness() {
  const nodes = [], listeners = new Map();
  const make = tag => {
    const handlers = new Map(), element = { tag, textContent: "", children: [], checked: false, disabled: false,
      append(...items) { this.children.push(...items); }, setAttribute() {},
      addEventListener(name, fn) { handlers.set(name, fn); },
      dispatch(name) { handlers.get(name)?.({ preventDefault() {} }); },
      showModal() { this.open = true; }, close() { this.open = false; this.dispatch("close"); },
      remove() { this.removed = true; }, focus(options) { this.focusOptions = options; this.focused = true; },
    }; nodes.push(element); return element;
  };
  const doc = { createElement: make, createTextNode: text => ({ textContent: text }), body: make("body") };
  const events = { addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: name => listeners.delete(name) };
  const context = vm.createContext({ URL, document: doc, window: events, fetch: () => { throw Error("No sends from review"); } });
  vm.runInContext(source.replace("export function", "function"), context);
  const find = id => nodes.find(node => node.id === id);
  const button = label => nodes.find(node => node.tag === "button" && node.textContent === label);
  const task = { id: "fixture", model_data_preview: { fingerprint: "review-v1", mode: "video", title: "<img src=x onerror=alert(1)>",
    source_url: "https://source.invalid/video?p=2", context_available: true, context_excerpt: "Actual reviewed excerpt",
    fallback_available: true, captured_page_text: "Captured full page", captured_subtitles: "Captured captions",
    page_text_limit: 50000, subtitle_text_limit: 10000 } };
  const options = { content_mode: "text", transcriber: "groq", llm_base_url: "https://viewer:secret@models.invalid/v1?token=hidden", llm_model: "fixture" };
  return { review: extra => context.reviewTaskModelData({ task, options, ...extra }), nodes, find, button, listeners, task, options };
}

test("review discloses actual metadata, separate scopes and conditional audio without sending", async () => {
  const h = harness(), result = h.review();
  const text = h.nodes.map(node => node.textContent).join("\n");
  assert.match(text, /models\.invalid.*fixture/);
  assert.match(text, /没有可验证字幕.*音频.*models\.invalid/);
  assert.match(text, /来源标题：<img src=x onerror=alert\(1\)>/);
  assert.match(text, /来源页面链接：https:\/\/source\.invalid/);
  assert.match(text, /Actual reviewed excerpt/);
  assert.doesNotMatch(text, /viewer|secret|token=hidden/);
  assert(h.nodes.every(node => !node.innerHTML), "Captured data remains text, never HTML");
  assert.equal(h.find("allowModelPageContext").checked, false);
  assert.equal(h.find("allowPageTextFallback").checked, false);
  assert.equal(h.button("同意并开始").disabled, true);
  const heading = h.find("modelDataConsentTitle");
  assert.equal(heading.tabIndex, -1); assert.equal(heading.focused, true);
  assert.equal(heading.focusOptions.preventScroll, true);
  assert.equal(h.nodes.find(node => node.tag === "dialog").scrollTop, 0);
  assert.equal(h.button("同意并开始").focused, undefined);
  h.button("取消").onclick(); assert.equal(await result, null);
});

test("context permission never implies full-page fallback and every new review resets choices", async () => {
  const h = harness(), result = h.review();
  h.find("allowModelPageContext").checked = true;
  h.find("modelDataConsent").checked = true; h.find("modelDataConsent").onchange();
  h.button("同意并开始").onclick();
  assert.deepEqual(JSON.parse(JSON.stringify(await result)), { allow_model_page_context: true, allow_page_text_fallback: false, review_fingerprint: "review-v1" });
  const next = harness(), pending = next.review();
  assert.equal(next.find("allowModelPageContext").checked, false);
  next.find("allowPageTextFallback").checked = true; next.find("modelDataConsent").checked = true;
  next.button("同意并开始").onclick();
  assert.deepEqual(JSON.parse(JSON.stringify(await pending)), { allow_model_page_context: false, allow_page_text_fallback: true, review_fingerprint: "review-v1" });
});

test("Escape, navigation and stale task/model settings cannot approve a send", async () => {
  for (const action of ["escape", "navigation", "stale"]) {
    const h = harness(), result = h.review({ isCurrent: () => action !== "stale" });
    if (action === "escape") h.nodes.find(node => node.tag === "dialog").dispatch("cancel");
    if (action === "navigation") h.listeners.get("learnnote:navigation")();
    if (action === "stale") {
      h.find("modelDataConsent").checked = true; h.button("同意并开始").onclick();
      assert(h.nodes.some(node => node.textContent.includes("设置已改变")));
      assert.equal(h.button("同意并开始").disabled, true);
      h.button("取消").onclick();
    }
    assert.equal(await result, null);
  }
});

test("explicit page-text and no-model tasks do not require an unrelated video flag", async () => {
  const h = harness(); h.task.model_data_preview.mode = "page_text";
  h.task.model_data_preview.context_available = h.task.model_data_preview.fallback_available = false;
  const result = h.review();
  assert.equal(h.find("allowModelPageContext"), undefined); assert.equal(h.find("allowPageTextFallback"), undefined);
  assert(h.nodes.some(node => node.textContent.includes("本次明确使用页面文本")));
  h.find("modelDataConsent").checked = true; h.button("同意并开始").onclick();
  assert.deepEqual(JSON.parse(JSON.stringify(await result)), { allow_model_page_context: false, allow_page_text_fallback: false, review_fingerprint: "review-v1" });
  const local = harness(); local.options.content_mode = "subtitles";
  assert.deepEqual(JSON.parse(JSON.stringify(await local.review())), { allow_model_page_context: false, allow_page_text_fallback: false, review_fingerprint: "review-v1" });
  assert.equal(local.nodes.length, 1);
});

test("actual desk start handler submits only after renewed review, bound to current options", async () => {
  const desk = readFileSync(new URL("../desk.js", import.meta.url), "utf8");
  const handler = desk.slice(desk.indexOf('$("taskStatus").onclick ='), desk.indexOf('$("settings").onclick ='));
  for (const scopes of [null, { allow_model_page_context: true, allow_page_text_fallback: false, review_fingerprint: "review-v1" }]) {
    const target = {}, calls = [], options = { content_mode: "text", transcriber: "groq" };
    const state = { selected: { id: "task-fixture" }, taskAction: null, health: { default_llm_base_url: "https://models.invalid/v1", default_llm_model: "fixture" } };
    const context = vm.createContext({ URLSearchParams, state, $: () => target, renderStatus() {}, options: () => ({ ...options }),
      api: async (...args) => calls.push(args), refresh: async () => {}, refreshSelectedTask: async () => {}, failure: error => { throw error; },
      reviewTaskModelData: async request => { assert.equal(request.isCurrent(), true); assert.equal(request.options.llm_model, "fixture"); return scopes; } });
    vm.runInContext("let editionRequest = 0;"
      + desk.slice(desk.indexOf("function selectedSourceCurrent("), desk.indexOf("function selectedSnapshotCurrent("))
      + desk.slice(desk.indexOf("function readerSnapshotSource("), desk.indexOf("async function adoptSelectedSnapshot("))
      + handler, context);
    await target.onclick({ target: { closest: () => ({ dataset: { taskAction: "start" } }) } });
    assert.equal(calls.length, scopes ? 1 : 0);
    if (scopes) {
      assert.equal(calls[0][0], "/api/tasks/task-fixture/start?allow_model_page_context=true&allow_page_text_fallback=false&review_fingerprint=review-v1");
      assert.equal(JSON.parse(calls[0][1].body).llm_base_url, "https://models.invalid/v1");
    }
  }
});


test("classic disclosure refreshes recipient and conditional audio before submission", () => {
  const classic = readFileSync(new URL("../editorial.js", import.meta.url), "utf8");
  const body = classic.slice(classic.indexOf("  function renderModelDisclosure()"), classic.indexOf("  function renderDraft("));
  const callbacks = new Map(), notice = { textContent: "" }, options = { llm_base_url: "https://first.invalid/v1", llm_model: "first", transcriber: "faster-whisper" };
  const context = vm.createContext({ URL, q: () => notice, readOptions: () => options, selectedPurpose: () => null, lastHealthData: {},
    document: { addEventListener: (name, fn) => callbacks.set(name, fn) } });
  vm.runInContext(body + classic.split("\n").filter(line => /document.addEventListener.*renderModelDisclosure/.test(line)).join("\n"), context);
  callbacks.get("change")(); assert.match(notice.textContent, /first\.invalid.*first/);
  options.llm_base_url = "https://user:secret@second.invalid/v1?token=hidden"; options.llm_model = "second"; options.transcriber = "groq";
  callbacks.get("input")();
  assert.match(notice.textContent, /second\.invalid.*second.*音频.*second\.invalid/);
  assert.doesNotMatch(notice.textContent, /first\.invalid|secret|hidden/);
  assert.match(notice.textContent, /不授权额外页面上下文或页面全文兜底/);
});
