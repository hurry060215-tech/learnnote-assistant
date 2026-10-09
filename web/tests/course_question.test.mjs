import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(new URL("../course-question.js", import.meta.url), "utf8");
const tools = readFileSync(new URL("../desk-tools.js", import.meta.url), "utf8");
assert.match(tools, /installCourseQuestion\(/);
assert.match(tools, /askCourse\.dataset\.action = "course-question"/);
assert.match(tools, /courseTools\.dataset\.action = "courses"/);
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const courses = [{ id: "course/one", title: "<Local course>", revision: 3, sources: [] }, { id: "other", title: "Other course", revision: 7, sources: [] }];
const citation = { evidence_id: "evidence/video", title: "<Original video>", locator: "00:12–00:18", source_kind: "task", source_id: "video", start: 12, end: 18 };
const answer = (course = courses[0], overrides = {}) => ({ answer: "<Local original excerpt>", grounded: true, citations: [citation], results: [], retrieval_method: "lexical", scope: { kind: "course", id: course.id, title: course.title, revision: course.revision }, ...overrides });
const event = () => ({ preventDefault() {}, stopPropagation() {} });

function harness(moduleSource = source) {
  const nodes = new Map(), calls = [], requests = [], loads = [], opened = [], notices = [], windowEvents = new Map();
  let generation = 0;
  class Element {
    constructor(tag = "div") { this.tag = tag; this.listeners = new Map(); this.children = []; this.dataset = {}; this.disabled = false; this.value = ""; this.textContent = ""; }
    set innerHTML(html) { this.html = html; for (const [, id] of html.matchAll(/id="([^"]+)"/g)) nodes.set(id, new Element()); }
    addEventListener(name, fn) { this.listeners.set(name, fn); }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    close() { this.open = false; }
  }
  const dialog = new Element(), state = { epoch: 1, selected: { kind: "material", id: "original" } };
  const $ = id => nodes.get(id);
  const h = { $, state, dialog, calls, requests, loads, opened, notices, courses: structuredClone(courses), deferLoads: false, deferList: null };
  const context = vm.createContext({
    document: { getElementById: $, createElement: tag => new Element(tag) },
    window: { addEventListener: (name, fn) => windowEvents.set(name, fn) },
    esc: text => String(text).replaceAll("<", "&lt;").replaceAll(">", "&gt;"),
    api: async (path, options) => {
      calls.push({ path, options });
      if (options?.method === "POST") { const work = deferred(); requests.push(work); return work.promise; }
      if (path === "/api/courses") return h.deferList ? h.deferList.promise : { courses: h.courses };
      if (h.deferLoads) { const work = deferred(); loads.push(work); return work.promise; }
      const selected = h.courses.find(item => path === `/api/courses/${encodeURIComponent(item.id)}`);
      if (!selected) throw new Error("课程不存在或已删除");
      return { course: structuredClone(selected) };
    },
  });
  vm.runInContext(moduleSource.replace(/^import .*;\r?\n/, "").replace("export function", "function"), context);
  const show = () => { generation++; dialog.open = true; nodes.set("toolBody", new Element()); nodes.set("toolStatus", new Element()); return generation; };
  h.open = initial => context.installOpen(initial);
  context.installOpen = context.installCourseQuestion({ state, dialog, show, generation: () => generation,
    status: text => { $("toolStatus").textContent = text; }, notice: text => notices.push(text),
    openEvidence: async id => { opened.push(id); if (h.evidenceError) throw h.evidenceError; },
  });
  h.submit = () => $("courseQuestionForm").listeners.get("submit")(event());
  h.choose = id => { $("courseQuestionScope").value = id; return $("courseQuestionScope").listeners.get("change")(event()); };
  h.reload = () => $("courseQuestionReload").listeners.get("click")(event());
  h.close = () => { generation++; dialog.close(); };
  h.escape = () => { dialog.listeners.get("cancel")(); dialog.close(); };
  h.navigate = () => { state.epoch++; state.selected = { kind: "task", id: "new" }; windowEvents.get("learnnote:navigation")(); };
  h.home = () => { state.epoch++; state.selected = null; windowEvents.get("learnnote:navigation")(); };
  h.otherTool = () => { show(); $("toolStatus").textContent = "Newer tool"; };
  return h;
}

for (const newline of ["\n", "\r\n"]) {
  const h = harness(source.replace(/\r?\n/g, newline));
  await h.open(courses[0]);
  assert.match(h.$("toolBody").html, /&lt;Local course&gt;/);
  assert.match(h.$("toolBody").html, /本地原文摘录，不使用 AI 综合生成答案/);
  assert.equal(h.$("courseQuestionScope").value, courses[0].id);
  assert.match(h.$("courseQuestionScopeHint").textContent, /<Local course>/);
  assert.equal(h.requests.length, 0);
}
{
  const h = harness(); await h.open(courses[0]);
  await h.submit(); assert.equal(h.requests.length, 0, "Whitespace/empty question cannot trigger retrieval");
  h.$("courseQuestionText").value = "  concept  ";
  const work = h.submit(); await h.submit();
  assert.equal(h.requests.length, 1); assert.equal(h.$("courseQuestionSubmit").disabled, true);
  assert.equal(h.calls.at(-1).path, "/api/courses/course%2Fone/ask");
  assert.deepEqual(JSON.parse(h.calls.at(-1).options.body), { question: "concept", revision: 3, limit: 6, mode: "lexical" });
  h.requests[0].resolve(answer()); await work;
  const [text, link] = h.$("courseQuestionResult").children;
  assert.equal(text.textContent, "<Local original excerpt>", "Answer is text, never HTML");
  assert.equal(link.textContent, "核对原文：<Original video> · 00:12–00:18");
  assert.deepEqual({ ...link.dataset }, { courseEvidence: citation.evidence_id, sourceKind: "task", sourceId: "video", locator: citation.locator, start: "12", end: "18" });
  await link.listeners.get("click")(event());
  assert.deepEqual(h.opened, [citation.evidence_id]); assert.equal(h.dialog.open, false);
}
for (const leave of ["close", "escape", "navigate", "home", "otherTool"]) {
  for (const reject of [false, true]) {
    const h = harness(); await h.open(courses[0]); h.$("courseQuestionText").value = "concept";
    const work = h.submit(); const oldResult = h.$("courseQuestionResult"); h[leave]();
    if (["navigate", "home"].includes(leave)) assert.equal(h.dialog.open, false);
    const status = h.$("toolStatus").textContent;
    if (reject) h.requests[0].reject(new Error("Stale failure")); else h.requests[0].resolve(answer());
    await work;
    assert.deepEqual(oldResult.children, [], `${leave}: late answer discarded`);
    assert.equal(h.$("toolStatus").textContent, status, `${leave}: late error discarded`);
    assert.deepEqual(h.opened, []);
  }
}
{
  const h = harness(); await h.open(courses[0]); h.$("courseQuestionText").value = "concept";
  const old = h.submit(); await h.choose(courses[1].id); const latest = h.submit();
  h.requests[1].resolve(answer(courses[1], { answer: "Other course only" })); await latest;
  h.requests[0].resolve(answer()); await old;
  assert.equal(h.$("courseQuestionResult").children[0].textContent, "Other course only");
  assert.equal(h.requests.length, 2); assert.equal(h.$("courseQuestionSubmit").disabled, false);
}
{
  const h = harness(); await h.open(courses[0]); h.$("courseQuestionText").value = "concept";
  const work = h.submit(); h.close(); await h.open(courses[0]); h.$("courseQuestionText").value = "concept";
  await h.submit(); assert.equal(h.requests.length, 1, "Closing/reopening cannot duplicate an outstanding lookup");
  h.requests[0].resolve(answer()); await work;
  assert.deepEqual(h.$("courseQuestionResult").children, []);
  assert.equal(h.$("courseQuestionSubmit").disabled, false, "Reopened form becomes usable once the old lookup ends");
}
for (const error of [new Error("课程来源已变化 (409)"), new Error("课程不存在或已删除 (404)"), new Error("Offline")]) {
  const h = harness(); await h.open(courses[0]); h.$("courseQuestionText").value = "concept";
  const work = h.submit(); h.requests[0].reject(error); await work;
  assert.match(h.$("toolStatus").textContent, /刷新课程范围/);
  assert.equal(h.$("courseQuestionSubmit").disabled, true); await h.submit(); assert.equal(h.requests.length, 1);
  h.courses[0].revision++; await h.reload(); const retry = h.submit();
  assert.equal(JSON.parse(h.calls.at(-1).options.body).revision, 4);
  h.requests[1].resolve(answer(h.courses[0])); await retry;
  assert.equal(h.$("courseQuestionSubmit").disabled, false);
  assert(h.calls.every(call => call.path.startsWith("/api/courses")), "Never fall back to global or unscoped search");
}
for (const scope of [{ kind: "course", id: "other", revision: 3 }, { kind: "course", id: courses[0].id, revision: 99 }, undefined]) {
  const h = harness(); await h.open(courses[0]); h.$("courseQuestionText").value = "concept";
  const work = h.submit(); h.requests[0].resolve(answer(courses[0], { scope })); await work;
  assert.deepEqual(h.$("courseQuestionResult").children, []); assert.equal(h.$("courseQuestionSubmit").disabled, true);
}
{
  const h = harness(); await h.open(courses[0]); h.$("courseQuestionText").value = "not found";
  const work = h.submit(); h.requests[0].resolve(answer(courses[0], { answer: "", grounded: false, citations: [] })); await work;
  assert.match(h.$("courseQuestionResult").children[0].textContent, /没有找到匹配原文/);
  assert.equal(h.$("courseQuestionResult").children.length, 1); assert.match(h.$("toolStatus").textContent, /没有足够/);
}
{
  const h = harness(); h.courses = []; await h.open(courses[0]);
  assert.equal(h.$("courseQuestionScope").value, ""); assert.equal(h.$("courseQuestionSubmit").disabled, true);
  assert.match(h.$("toolStatus").textContent, /还没有课程/);
}
for (const revision of [undefined, null, 0, -1, 1.5, "3"]) {
  const h = harness(); h.courses[0].revision = revision; await h.open(courses[0]);
  h.$("courseQuestionText").value = "concept"; await h.submit();
  assert.equal(h.requests.length, 0, "Missing/invalid course revision cannot submit a scope");
  assert.equal(h.$("courseQuestionSubmit").disabled, true);
}
{
  const h = harness(); await h.open({ id: "deleted" });
  assert.equal(h.$("courseQuestionScope").value, "", "A deleted initial course must not fall back to the first course");
  assert.equal(h.$("courseQuestionSubmit").disabled, true);
}
{
  const h = harness(); await h.open(courses[0]); h.$("courseQuestionText").value = "concept";
  const work = h.submit(); h.requests[0].resolve(answer()); await work;
  const oldLink = h.$("courseQuestionResult").children[1];
  await h.choose(courses[1].id); await oldLink.listeners.get("click")(event());
  assert.deepEqual(h.opened, [], "A detached old-course citation cannot navigate the reader");
}
{
  const h = harness(); await h.open(courses[0]); h.deferLoads = true;
  const old = h.choose(courses[1].id), latest = h.choose(courses[0].id);
  h.loads[1].resolve({ course: courses[0] }); await latest;
  h.loads[0].resolve({ course: courses[1] }); await old;
  assert.match(h.$("courseQuestionScopeHint").textContent, /<Local course>/);
}
for (const reject of [false, true]) {
  const h = harness(); h.deferList = deferred(); const open = h.open(courses[0]); h.navigate();
  if (reject) h.deferList.reject(new Error("Late list failure")); else h.deferList.resolve({ courses });
  await open; assert.equal(h.$("courseQuestionForm"), undefined); assert.equal(h.dialog.open, false);
}
console.log("Course questions keep revision-bound local evidence, source links and safe scope/navigation races");
