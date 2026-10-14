import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../section-review.js", import.meta.url), "utf8");
const defer = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const route = { base_url: "http://127.0.0.1:19877/v1", model: "synthetic" };
const revision = "a".repeat(64), fingerprint = "b".repeat(64);
const preview = (extra = {}) => ({ task_id: "task-one", revision, section_id: "chapter-one", offset: 0,
  fingerprint, preview_id: "synthetic-preview-token", connection: route, can_submit: true,
  claims: [{ claim_alias: "C1", text: "<Literal claim>" }], evidence: [{ source_alias: "E1", text: "<Literal source>", locator: "0-10s" }],
  coverage: { claim_count: 13, selected_claims: 12, candidate_sources: 2, selected_sources: 1, source_truncated: true, literal_matches: 0, next_offset: 12 },
  warning: "One request; fees unknown; a gateway may forward", ...extra });
const result = (extra = {}) => ({ ...preview(), judgments: [{ claim_alias: "C1", verdict: "insufficient", reason: "<Model reason>", citations: [{ source_alias: "E1", quote: "<Literal source>" }] }], usage: null, ...extra });

function harness() {
  const nodes = new Map(), events = new Map(), calls = [], requests = [];
  let generation = 0;
  class Element {
    constructor(tag = "div") { this.tag = tag; this.children = []; this.listeners = new Map(); this.value = ""; this.disabled = false; this.checked = false; this.textContent = ""; }
    set id(value) { this._id = value; nodes.set(value, this); }
    get id() { return this._id; }
    set innerHTML(value) { this.html = value; for (const [, id] of value.matchAll(/id="([^"]+)"/g)) { const node = new Element(); node.id = id; } if (nodes.has("sectionReviewChapter")) nodes.get("sectionReviewChapter").value = "chapter-one"; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    addEventListener(name, fn) { this.listeners.set(name, fn); }
    close() { this.open = false; }
  }
  const $ = id => nodes.get(id), dialog = new Element(), state = { epoch: 1, revision, selected: { kind: "task", id: "task-one" } };
  const h = { $, state, dialog, calls, requests, configured: true };
  const context = vm.createContext({ document: { getElementById: $, createElement: tag => new Element(tag), createTextNode: text => ({ textContent: text, children: [] }) },
    window: { addEventListener: (name, fn) => events.set(name, fn) },
    esc: value => String(value).replaceAll("<", "&lt;").replaceAll(">", "&gt;"),
    api: async (path, options) => {
      calls.push({ path, options });
      if (options?.method === "POST") { const waiting = defer(); requests.push(waiting); return waiting.promise; }
      if (path === "/api/model/connection") return { configured: h.configured, model: route };
      if (h.failed) throw new Error("Synthetic read error");
      return { sections: [{ id: "chapter-one", title: "<Chapter one>" }, { id: "chapter-two", title: "Chapter two" }] };
    } });
  vm.runInContext(source.replace(/^import .*;\r?\n/, "").replace("export function", "function"), context);
  const show = () => { generation++; dialog.open = true; nodes.set("toolBody", new Element()); nodes.set("toolStatus", new Element()); return generation; };
  h.open = context.installSectionReview({ state, dialog, show, status: value => { $("toolStatus").textContent = value; }, generation: () => generation });
  h.prepare = () => $("sectionReviewPrepare").listeners.get("click")();
  h.check = () => { $("sectionReviewConsent").checked = true; $("sectionReviewConsent").listeners.get("change")(); };
  h.confirm = () => $("sectionReviewSend").listeners.get("click")();
  h.chapter = () => { $("sectionReviewChapter").value = "chapter-two"; $("sectionReviewChapter").listeners.get("change")(); };
  h.close = () => { generation++; dialog.close(); };
  h.escape = () => { dialog.listeners.get("cancel")(); dialog.close(); };
  h.navigate = () => { state.epoch++; events.get("learnnote:navigation")(); };
  h.settings = () => events.get("learnnote:settings")();
  h.revision = () => { state.revision = "c".repeat(64); };
  h.otherTool = show;
  return h;
}
const text = element => [element.textContent, ...(element.children || []).map(text)].filter(Boolean).join(" ");
const tick = async () => { await Promise.resolve(); await Promise.resolve(); };
async function prepared(h, value = preview()) { const work = h.prepare(); h.requests.at(-1).resolve(value); await work; }

{
  const h = harness(); await h.open(); assert.equal(h.requests.length, 0);
  assert.match(h.$("toolBody").html, /&lt;Chapter one&gt;/);
  assert.match(h.$("toolBody").html, /不会自动处理下一批/); assert.match(h.$("toolBody").html, /远端可能继续处理或计费/);
  await prepared(h); assert.equal(h.$("sectionReviewSend").disabled, true);
  assert.match(text(h.$("sectionReviewPreview")), /<Literal source>/);
  assert.match(text(h.$("sectionReviewPreview")), /部分原文因预算未纳入/);
  assert.deepEqual(JSON.parse(h.calls.find(x => x.options).options.body), { revision, section_id: "chapter-one", offset: 0, ...route });
  await h.confirm(); assert.equal(h.requests.length, 1);
  h.check(); const work = h.confirm(); await tick(); await h.confirm(); await h.prepare();
  assert.equal(h.requests.length, 2, "Double clicks cannot dispatch another call");
  assert.equal(h.$("sectionReviewPrepare").disabled, true);
  assert.deepEqual(JSON.parse(h.calls.at(-1).options.body), { preview_id: "synthetic-preview-token", fingerprint, share_source: true });
  h.requests.at(-1).resolve(result()); await work;
  assert.match(text(h.$("sectionReviewResult")), /本次原文不足以判断/);
  assert.match(text(h.$("sectionReviewResult")), /<Model reason>/);
  assert.match(text(h.$("sectionReviewResult")), /金额未知/);
  assert.equal(h.requests.length, 2, "No automatic next batch");
  const next = h.$("sectionReviewResult").children.find(item => item.tag === "button");
  next.listeners.get("click")(); await tick(); assert.equal(h.requests.length, 3);
  assert.equal(JSON.parse(h.calls.at(-1).options.body).offset, 12);
  h.requests.at(-1).resolve(preview({ offset: 12 })); await tick();
  assert.equal(h.$("sectionReviewSend").disabled, true, "Next batch requires new consent");
}
for (const change of ["chapter", "close", "escape", "navigate", "settings", "revision", "otherTool"]) {
  for (const phase of ["preview", "confirm"]) {
    const h = harness(); await h.open();
    if (phase === "confirm") { await prepared(h); h.check(); }
    const work = phase === "preview" ? h.prepare() : h.confirm();
    const oldResults = h.$("sectionReviewResult"); h[change](); const status = h.$("toolStatus").textContent;
    h.requests.at(-1).resolve(phase === "preview" ? preview() : result()); await work;
    assert.equal(oldResults.children.length, 0, `${change}/${phase}: stale result suppressed`);
    assert.equal(h.$("toolStatus").textContent, status, `${change}/${phase}: stale status suppressed`);
  }
}
for (const phase of ["preview", "confirm"]) {
  const h = harness(); await h.open();
  if (phase === "confirm") { await prepared(h); h.check(); }
  const old = phase === "preview" ? h.prepare() : h.confirm();
  h.close(); await h.open(); assert.equal(h.$("sectionReviewPrepare").disabled, true);
  h.requests.at(-1).resolve(phase === "preview" ? preview() : result()); await old;
  assert.equal(h.$("sectionReviewPrepare").disabled, false, "Reopened dialog unlocks when prior request settles");
  assert.equal(h.$("sectionReviewResult").children.length, 0);
}
for (const phase of ["preview", "confirm"]) {
  const h = harness(); await h.open();
  if (phase === "confirm") { await prepared(h); h.check(); }
  const work = phase === "preview" ? h.prepare() : h.confirm();
  h.requests.at(-1).reject(new Error("Synthetic timeout; remote billing unknown")); await work;
  assert.equal(h.requests.length, phase === "preview" ? 1 : 2);
  assert.equal(h.$("sectionReviewPrepare").disabled, false);
  assert.match(h.$("toolStatus").textContent, /Synthetic timeout/);
}
for (const changes of [{ task_id: "foreign" }, { revision: "c".repeat(64) }, { section_id: "foreign" }, { connection: { ...route, model: "changed" } }]) {
  const h = harness(); await h.open(); await prepared(h, preview(changes));
  assert.equal(h.$("sectionReviewPreview").children.length, 0);
  assert.equal(h.$("sectionReviewSend"), undefined);
}
for (const flag of ["failed", "configured"]) {
  const h = harness(); h[flag] = flag === "failed"; await h.open();
  assert.equal(h.requests.length, 0); assert.doesNotMatch(text(h.$("toolBody")), /正在读取/);
}
for (const field of ["edition", "editing"]) {
  const h = harness(); await h.open(); h.state[field] = field === "edition" ? { edited: true } : true;
  const calls = h.calls.length; await h.open(); assert.equal(h.calls.length, calls);
}
console.log("Chapter review: explicit consent, bounded manual batches, safe text, stale responses, and dialog races passed.");
