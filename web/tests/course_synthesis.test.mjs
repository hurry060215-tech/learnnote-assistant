import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
const source = readFileSync(new URL("../course-synthesis.js", import.meta.url), "utf8");
const questionModule = readFileSync(new URL("../course-question.js", import.meta.url), "utf8");
assert.match(questionModule, /AI 综合（先预览与确认）/);
const defer = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const course = { id: "course/one", title: "<Course>", revision: 2 };
const other = { id: "other", title: "Other", revision: 3 };
const route = { model: "synthetic", base_url: "http://127.0.0.1:19877/v1" };
const citation = { evidence_id: "original/video", source_alias: "E1", source_kind: "task", source_id: "video", title: "<Source>", locator: "12-18s", start: 12, end: 18, episode_ids: ["stable"] };
const preview = (selected = course) => ({ scope: { kind: "course", ...selected }, connection: route, question: "<Gradient>", mode: "question", fingerprint: "a".repeat(64), preview_id: "safe-preview-token", can_submit: true,
  coverage: { selected_anchors: 1, selected_characters: 30, eligible_anchors: 1, eligible_characters: 30, all_eligible_included: true }, members: [{ title: "Missing", position: 1, status: "missing", eligible: 0, excluded: 0, missing: 1 }], evidence: [{ ...citation, text: "<Literal source>" }], warning: "One request; fees unknown; gateway may forward" });
const result = (selected = course) => ({ scope: { kind: "course", ...selected }, fingerprint: "a".repeat(64), request_count: 1, status: "answer", claims: [{ kind: "synthesis", text: "<AI interpretation>", supports: [{ quote: "<Literal source>", citation }] }], usage: { total_tokens: null }, warning: "Review synthesis" });
const event = () => ({ preventDefault() {}, stopPropagation() {} });
function harness() {
  const nodes = new Map(), events = new Map(), calls = [], requests = [], opened = [];
  let generation = 0;
  class Element {
    constructor(tag = "div") { this.tag = tag; this.listeners = new Map(); this.children = []; this.dataset = {}; this.textContent = ""; this.value = ""; this.checked = false; this.disabled = false; }
    set id(id) { this._id = id; nodes.set(id, this); }
    get id() { return this._id; }
    set innerHTML(html) { this.html = html; for (const [, id] of html.matchAll(/id="([^"]+)"/g)) { const node = new Element(); node.id = id; } }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    addEventListener(name, fn) { this.listeners.set(name, fn); }
    close() { this.open = false; }
  }
  const $ = id => nodes.get(id), dialog = new Element(), state = { epoch: 1 };
  const h = { $, dialog, state, calls, requests, opened, route, configured: true, courses: [course, other] };
  const context = vm.createContext({ document: { getElementById: $, createElement: tag => new Element(tag), createTextNode: text => ({ textContent: text }) }, window: { addEventListener: (name, fn) => events.set(name, fn) },
    esc: value => String(value).replaceAll("<", "&lt;").replaceAll(">", "&gt;"),
    api: async (path, options) => {
      calls.push({ path, options });
      if (options?.method === "POST") { const pending = defer(); requests.push(pending); return pending.promise; }
      if (path === "/api/model/connection") return { configured: h.configured, model: h.route };
      if (path === "/api/courses") return { courses: h.courses };
      const selected = h.courses.find(x => path === `/api/courses/${encodeURIComponent(x.id)}`); if (!selected) throw new Error("Missing course"); return { course: selected };
    } });
  vm.runInContext(source.replace(/^import .*;\r?\n/, "").replace("export function", "function"), context);
  const show = () => { generation++; dialog.open = true; nodes.set("toolBody", new Element()); nodes.set("toolStatus", new Element()); return generation; };
  const open = context.installCourseSynthesis({ state, dialog, show, status: text => { $("toolStatus").textContent = text; }, generation: () => generation, openEvidence: async id => opened.push(id), notice() {} });
  h.open = (selected = course) => open(selected, "Gradient");
  h.submit = () => $("courseSynthesisForm").listeners.get("submit")(event());
  h.confirm = () => $("courseSynthesisConfirm").listeners.get("click")(event());
  h.check = () => { $("courseSynthesisConsent").checked = true; $("courseSynthesisConsent").listeners.get("change")(event()); };
  h.changeQuestion = () => { $("courseSynthesisQuestion").value = "Changed"; $("courseSynthesisQuestion").listeners.get("input")(event()); };
  h.changeMode = () => { $("courseSynthesisMode").value = "summary"; $("courseSynthesisMode").listeners.get("change")(event()); };
  h.choose = id => { $("courseSynthesisScope").value = id; return $("courseSynthesisScope").listeners.get("change")(event()); };
  h.close = () => { generation++; dialog.close(); };
  h.escape = () => { dialog.listeners.get("cancel")(); dialog.close(); };
  h.navigate = () => { state.epoch++; events.get("learnnote:navigation")(); };
  h.settings = () => events.get("learnnote:settings")();
  h.otherTool = () => show();
  return h;
}
const tick = async () => { await Promise.resolve(); await Promise.resolve(); };
const text = element => [element.textContent, ...element.children?.map(text) || []].filter(Boolean).join(" ");
async function prepared(h) { const work = h.submit(); h.requests.at(-1).resolve(preview()); await work; }
{
  const h = harness(); await h.open();
  assert.equal(h.requests.length, 0); assert.match(h.$("toolBody").html, /&lt;Course&gt;/);
  assert.match(h.$("toolBody").html, /金额未知/); assert.match(h.$("toolBody").html, /关闭仅隐藏/);
  await prepared(h); const post = JSON.parse(h.calls.find(x => x.options)?.options.body);
  assert.deepEqual(post, { question: "Gradient", revision: 2, mode: "question", base_url: route.base_url, model: "synthetic" });
  assert(!("share_source" in post)); assert.equal(h.$("courseSynthesisConfirm").disabled, true);
  await h.confirm(); assert.equal(h.requests.length, 1, "Unchecked consent cannot submit");
  assert.match(text(h.$("courseSynthesisReview")), /<Literal source>/);
  assert.match(text(h.$("courseSynthesisReview")), /Missing/);
  h.check(); const work = h.confirm(); await tick(); await h.confirm();
  assert.equal(h.requests.length, 2); assert.equal(h.$("courseSynthesisPreview").disabled, true);
  assert.deepEqual(JSON.parse(h.calls.at(-1).options.body), { preview_id: "safe-preview-token", fingerprint: "a".repeat(64), share_source: true });
  h.requests[1].resolve(result()); await work;
  const rendered = text(h.$("courseSynthesisResult")); assert.match(rendered, /<AI interpretation>/); assert.match(rendered, /AI 综合 · 待核对/); assert.match(rendered, /金额未知/);
  const link = h.$("courseSynthesisResult").children[1].children.find(x => x.tag === "button");
  await link.listeners.get("click")(event()); assert.deepEqual(h.opened, [citation.evidence_id]); assert.equal(h.dialog.open, false);
}
for (const change of ["changeQuestion", "changeMode", "settings", "close", "escape", "navigate", "otherTool"]) {
  for (const phase of ["preview", "answer"]) {
    const h = harness(); await h.open();
    if (phase === "answer") { await prepared(h); h.check(); }
    const work = phase === "preview" ? h.submit() : h.confirm(); await tick();
    const oldReview = h.$("courseSynthesisReview"), oldResults = h.$("courseSynthesisResult"); h[change]();
    const status = h.$("toolStatus").textContent;
    h.requests.at(-1).resolve(phase === "preview" ? preview() : result()); await work;
    assert.equal(oldResults.children.length, 0, `${change}/${phase}: stale result suppressed`);
    if (phase === "preview") assert.equal(oldReview.children.length, 0);
    assert.equal(h.$("toolStatus").textContent, status, `${change}/${phase}: no stale status`);
  }
}
{
  const h = harness(); await h.open(); await prepared(h); h.check(); const stale = h.$("courseSynthesisConfirm");
  await h.choose(other.id); await stale.listeners.get("click")(event()); assert.equal(h.requests.length, 1);
  const work = h.submit(); h.requests[1].resolve(preview(other)); await work; assert.match(text(h.$("courseSynthesisReview")), /<Literal source>/);
}
{
  const h = harness(); await h.open(); await prepared(h); h.check(); h.route = { ...route, model: "changed" };
  await h.confirm(); assert.equal(h.requests.length, 1, "Saved route change prevents final POST"); assert.match(h.$("toolStatus").textContent, /模型已变化/);
}
{
  const h = harness(); await h.open(); await prepared(h); h.check(); const work = h.confirm(); await tick();
  h.close(); await h.open(); await h.submit(); assert.equal(h.requests.length, 2, "Reopening cannot repeat pending model request");
  h.requests[1].resolve(result()); await work; assert.equal(h.$("courseSynthesisResult").children.length, 0); assert.equal(h.$("courseSynthesisPreview").disabled, false);
}
for (const reason of ["course_summary_overflow", "course_evidence_insufficient"]) {
  const h = harness(); await h.open(); const work = h.submit(); h.requests[0].resolve({ ...preview(), can_submit: false, preview_id: null, blocking_reason: reason }); await work;
  assert.equal(h.$("courseSynthesisConfirm"), undefined); assert.equal(h.requests.length, 1);
}
{
  const h = harness(); await h.open(); await prepared(h); h.check(); const work = h.confirm(); await tick();
  h.requests[1].reject(new Error("Local waiting timeout; remote cost unknown")); await work;
  assert.match(h.$("toolStatus").textContent, /不会自动重试/); assert.equal(h.requests.length, 2); assert.equal(h.$("courseSynthesisReview").children.length, 0);
}
console.log("Course synthesis consent, escaped text, exact route, single submission and stale navigation contracts passed");
