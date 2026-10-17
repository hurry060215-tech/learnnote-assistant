import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../community-question.js", import.meta.url), "utf8");
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const event = () => ({ preventDefault() {}, stopPropagation() {} });
const recipient = { base_url: "http://127.0.0.1:19877/v1", model: "synthetic-model" };
const items = ["a", "b"].map(id => ({ item_id: id.repeat(32), text: `<img src=x onerror=alert(1)> Opinion ${id}`, kind: "comment", timestamp_seconds: null }));
const original_sources = [{ source_id: "E1", text: "Literal original subtitle", start: 0, end: 5 }];
const preview = (overrides = {}) => ({ preview_id: "c".repeat(64), fingerprint: "d".repeat(64), question: "REDACTED exact question", selected_item_ids: [items[0].item_id],
  connection: recipient, original_sources, opinions: [items[0]], messages: [{ role: "user", content: "<script>Actual exact outbound text</script>" }],
  limits: { compatibility_attempts: 2 }, coverage: { sources: 1 }, expires_in_seconds: 300, warning: "One answer; bounded compatibility attempts may cost extra.", can_submit: true, persisted: false, ...overrides });
const answer = (overrides = {}) => ({ answer: "<img src=x> Mixed answer [E1]", source: "selected-opinions-unverified", fact_verified: false, evidence_eligible: false, persisted: false,
  citations: [], original_sources, opinions: [items[0]], ...overrides });
function harness(moduleSource = source) {
  const nodes = [], calls = [], requests = [], streams = [], timers = new Map(), listeners = new Map();
  let generation = 1, timerId = 0;
  class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.listeners = new Map(); this.checked = false; this.disabled = false; this.value = ""; this.textContent = ""; nodes.push(this); }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    addEventListener(name, fn) { const list = this.listeners.get(name) || []; list.push(fn); this.listeners.set(name, list); }
    dispatch(name) { return Promise.all((this.listeners.get(name) || []).map(fn => fn(event()))); }
    setAttribute() {}
    focus(options) { this.focusOptions = options; this.focused = true; }
    scrollIntoView() { this.scrolled = true; }
    close() { this.open = false; this.dispatch("close"); }
  }
  const root = new Element("div"), dialog = new Element("dialog"); dialog.open = true;
  const state = { epoch: 1, selected: { id: "task/a", kind: "task", source_identity: { id: "first" }, control_generation: "first", status: "success" } };
  const h = { root, dialog, state, nodes, calls, requests, streams, timers, route: recipient };
  const context = vm.createContext({ document: { createElement: tag => new Element(tag) },
    window: { addEventListener(name, fn) { listeners.set(name, fn); } }, AbortController,
    setTimeout(fn) { const id = ++timerId; timers.set(id, fn); return id; }, clearTimeout(id) { timers.delete(id); },
    api: async (path, options) => {
      calls.push({ path, options });
      if (path === "/api/model/connection") return h.heldModel ? h.heldModel.promise : { configured: true, model: h.route };
      const work = deferred(); requests.push(work); return work.promise;
    },
    assistantStream: async (path, body, options) => { const work = deferred(); streams.push({ ...work, path, body, options }); return work.promise; },
  });
  vm.runInContext(moduleSource.replace(/^import .*;\r?\n/gm, "").replace("export function", "function"), context);
  const controller = context.installCommunityQuestion({ state, dialog, generation: () => generation });
  h.$ = id => nodes.findLast(node => node.id === id);
  h.text = (node = root) => [node.textContent, ...node.children.map(child => h.text(child))].join("\n");
  h.open = (community = { enabled: true, items }) => controller.mount(root, state.selected, community);
  h.question = async text => { h.$("communityQuestionText").value = text; await h.$("communityQuestionText").dispatch("input"); };
  h.choices = () => nodes.filter(node => node.dataset.opinionId).slice(-2);
  h.select = async (index = 0) => { h.choices()[index].checked = true; await h.choices()[index].dispatch("change"); };
  h.submit = () => h.$("communityQuestionForm").dispatch("submit");
  h.prepare = async () => { await h.question("Private question"); await h.select(); const work = h.submit(); requests.at(-1).resolve(preview()); await work; };
  h.consent = async () => { h.$("communityQuestionConsent").checked = true; await h.$("communityQuestionConsent").dispatch("change"); };
  h.send = () => h.$("communityQuestionSend").dispatch("click");
  h.cancel = () => h.$("communityQuestionCancel").dispatch("click");
  h.change = async name => {
    if (name === "question") return h.question("New question");
    if (name === "selection") return h.select(1);
    if (name === "settings") return listeners.get("learnnote:settings")();
    if (name === "source") { state.selected.source_identity.id = "second"; return listeners.get("learnnote:metadata")(); }
    if (name === "metadata_same") return listeners.get("learnnote:metadata")();
    if (name === "navigate") { state.epoch++; state.selected = { kind: "task", id: "other" }; return listeners.get("learnnote:navigation")(); }
    if (name === "home") { state.epoch++; state.selected = null; return listeners.get("learnnote:navigation")(); }
    if (name === "escape") { await dialog.dispatch("cancel"); dialog.close(); return; }
    if (name === "close") { dialog.close(); return; }
    if (name === "collapse") { const section = root.children.at(-1); section.open = false; return section.dispatch("toggle"); }
    if (name === "cancel") return h.cancel();
    controller.invalidate(); generation++; // Back, another tool, deleting an item or disabling the layer.
  };
  h.dispose = () => controller.invalidate();
  return h;
}

test("disabled layer and no saved items have no question UI or reads", async () => {
  for (const community of [{ enabled: false, items }, { enabled: true, items: [] }]) {
    const h = harness(); await h.open(community); assert.equal(h.calls.length, 0); assert.equal(h.$("communityQuestionForm"), undefined);
  }
});
test("fresh selectors, explicit question and local-only exact preview; literal data and focus", async () => {
  for (const newline of ["\n", "\r\n"]) {
    const h = harness(source.replace(/\r?\n/g, newline)); await h.open();
    assert(h.choices().every(input => !input.checked)); assert.equal(h.requests.length, 0); assert(h.$("communityQuestionPreview").disabled);
    await h.select(); await h.question("  Private question  "); assert(h.choices().every(input => !input.checked));
    await h.select(); const work = h.submit(); await h.submit(); assert.equal(h.requests.length, 1);
    const request = h.calls.at(-1); assert.equal(request.path, "/api/tasks/task%2Fa/qa/preview");
    assert.deepEqual(JSON.parse(request.options.body), { question: "Private question", selected_item_ids: [items[0].item_id], ...recipient });
    h.requests[0].resolve(preview()); await work;
    assert.equal(h.streams.length, 0); assert.equal(h.$("communityQuestionConsent").checked, false); assert(h.$("communityQuestionSend").disabled);
    assert.match(h.text(h.$("communityQuestionReview")), /REDACTED exact question/); assert.match(h.text(), /Actual exact outbound text/);
    assert.equal(h.nodes.some(node => "innerHTML" in node), false); assert(h.$("communityQuestionReview").children[0].focused);
    assert.deepEqual({ ...h.$("communityQuestionReview").children[0].focusOptions }, { preventScroll: true });
    await h.send(); assert.equal(h.streams.length, 0); h.dispose();
  }
});
test("exact redacted question sends only after new consent and renders one wholly unverified literal answer", async () => {
  const h = harness(); await h.open(); await h.prepare(); await h.consent(); const work = h.send(); await new Promise(setImmediate); await h.send();
  assert.equal(h.streams.length, 1); const stream = h.streams[0];
  assert.deepEqual(JSON.parse(JSON.stringify(stream.body)), { question: preview().question, skill_id: "note.qa", selected_opinions: { preview_id: preview().preview_id,
    fingerprint: preview().fingerprint, selected_item_ids: [items[0].item_id], ...recipient, confirm_send: true } });
  assert.equal(stream.options.onDelta, undefined); assert.equal(stream.path, "/api/tasks/task%2Fa/qa/stream");
  stream.resolve(answer()); await work;
  assert.match(h.text(h.$("communityQuestionResult")), /整体未经事实验证/); assert.match(h.text(), /<img src=x> Mixed answer \[E1\]/);
  assert(h.choices().every(input => !input.checked)); assert(h.$("communityQuestionPreview").disabled);
  assert(h.nodes.filter(node => node.tag === "button").every(node => !/保存|证据/.test(node.textContent)));
  await h.prepare(); assert.equal(h.$("communityQuestionConsent").checked, false); assert.equal(h.streams.length, 1); h.dispose();
});
for (const change of ["question", "selection", "settings", "source", "navigate", "home", "escape", "close", "collapse", "cancel", "back", "delete", "disable"]) {
  test(`${change} aborts held preview/stream and rejects late success/status/error`, async () => {
    for (const phase of ["preview", "stream"]) for (const reject of [false, true]) {
      const h = harness(); await h.open();
      let work, request, signal;
      if (phase === "preview") { await h.question("question"); await h.select(); work = h.submit(); request = h.requests[0]; signal = h.calls.at(-1).options.signal; }
      else { await h.prepare(); await h.consent(); work = h.send(); await new Promise(setImmediate); request = h.streams[0]; signal = request.options.signal; }
      await h.change(change); const before = h.$("communityQuestionStatus").textContent;
      assert(signal.aborted, `${change}/${phase} aborts fetch`);
      if (phase === "stream") request.options.onStatus("stale success");
      if (reject) request.reject(Error("Stale failure")); else request.resolve(phase === "preview" ? preview() : answer());
      await work;
      assert.equal(h.$("communityQuestionStatus").textContent, before);
      assert.equal(h.$("communityQuestionReview").children.length, 0); assert.equal(h.$("communityQuestionResult").children.length, 0); h.dispose();
    }
  });
}
test("reordered previews and late saved-model reads cannot revive old scope", async () => {
  const h = harness(); await h.open(); await h.question("first"); await h.select(); const first = h.submit();
  await h.question("second"); await h.select(); const second = h.submit();
  h.requests[1].resolve(preview({ question: "Latest" })); await second; h.requests[0].resolve(preview({ question: "STALE" })); await first;
  assert.match(h.text(h.$("communityQuestionReview")), /Latest/); assert.doesNotMatch(h.text(h.$("communityQuestionReview")), /STALE/);
  await h.consent(); h.heldModel = deferred(); const sending = h.send(); await h.change("source"); h.heldModel.resolve({ configured: true, model: recipient }); await sending;
  assert.equal(h.streams.length, 0); h.dispose();
});
test("expiry and model recheck require fresh preview, never automatically send", async () => {
  const h = harness(); await h.open(); await h.prepare(); await h.consent(); [...h.timers.values()][0](); await h.send(); assert.equal(h.streams.length, 0);
  await h.prepare(); await h.consent(); h.route = { ...recipient, model: "different" }; await h.send();
  assert.equal(h.streams.length, 0); assert.match(h.text(), /接收方已变化/); h.dispose();
});
test("unavailable context, wrong recipient, selection and output envelope fail closed", async () => {
  for (const value of [preview({ can_submit: false }), preview({ can_submit: "false" }), preview({ can_submit: 1 }), preview({ expires_in_seconds: Infinity }), preview({ expires_in_seconds: "300" }), preview({ expires_in_seconds: 301 }), preview({ connection: { ...recipient, model: "wrong" } }), preview({ selected_item_ids: [items[1].item_id] }), preview({ opinions: items }), preview({ persisted: true }), preview({ preview_id: null })]) {
    const h = harness(); await h.open(); await h.question("question"); await h.select(); const work = h.submit(); h.requests[0].resolve(value); await work;
    assert.equal(h.$("communityQuestionConsent"), undefined); assert.equal(h.streams.length, 0); h.dispose();
  }
  for (const patch of [{ source: "llm" }, { fact_verified: true }, { persisted: true }, { evidence_eligible: true }, { citations: [{ id: "E1" }] }, { opinions: items }, { original_sources: [] }]) {
    const h = harness(); await h.open(); await h.prepare(); await h.consent(); const work = h.send(); await new Promise(setImmediate); h.streams[0].resolve(answer(patch)); await work;
    assert.equal(h.$("communityQuestionResult").children.length, 0); assert.match(h.text(), /已丢弃/); h.dispose();
  }
});
test("same metadata preserves current approval; no persistence or alternate route is reachable", async () => {
  const h = harness(); await h.open(); await h.prepare(); await h.change("metadata_same"); assert(h.$("communityQuestionReview").children.length);
  assert.doesNotMatch(source, /localStorage|sessionStorage|localThreads|createDraftStore|renderMessage|openEvidence|DELETE/);
  assert(h.calls.every(call => /\/api\/model\/connection$|\/qa\/preview$/.test(call.path))); h.dispose();
});

test("untimed original text and saved opinion timestamps use truthful literal labels", async () => {
  const h = harness(); await h.open(); await h.question("question"); await h.select(); const work = h.submit();
  h.requests[0].resolve(preview({ original_sources: [{ ...original_sources[0], start: null, end: null }], opinions: [{ ...items[0], timestamp_seconds: 12, origin_label: "已关联来源，采集方式未记录" }] })); await work;
  const text = h.text(h.$("communityQuestionReview"));
  assert.match(text, /未标注时间的原始文本/); assert.match(text, /12 秒（保存的时间标记，未核实）/);
  assert.match(text, /已关联来源，采集方式未记录/); assert.doesNotMatch(text, /null–null/); h.dispose();
});
