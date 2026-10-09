import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";

const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return {promise, resolve, reject}; };
const question = {available: true, question: "____ are numerical representations.", question_revision: "a".repeat(64), source_evidence_ids: ["original"]};
function harness({get = async () => question, answer = async () => ({attempt: {correct: false, expected_answer: "Word vectors", source_evidence_ids: ["original"]}})} = {}) {
  class Element {
    constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.attributes = {}; this.textContent = ""; this.value = ""; this.isConnected = true; }
    append(...nodes) { this.children.push(...nodes); }
    insertBefore(node, before) { this.children.splice(this.children.indexOf(before), 0, node); }
    setAttribute(name, value) { this.attributes[name] = value; }
  }
  const document = {createElement: tag => new Element(tag)}, calls = [], sourceCalls = [], states = [];
  let current = true, key = 0;
  const context = vm.createContext({document, crypto: {randomUUID: () => `key-${++key}`}});
  vm.runInContext(readFileSync(new URL("../study-quiz.js", import.meta.url), "utf8"), context);
  const container = new Element("div");
  const controller = context.LearnNoteQuiz.mount({container, cardId: "card", request: async (path, options) => {
    const body = options ? JSON.parse(options.body) : null; calls.push({path, body});
    return path.endsWith("/quiz") ? get() : path.endsWith("/answer") ? answer(body) : {};
  }, isCurrent: () => current, onSource: id => sourceCalls.push(id), onQuestionState: value => states.push(value)});
  const root = container.children[0], find = tag => {
    const walk = node => node.tagName === tag.toUpperCase() ? node : node.children.map(walk).find(Boolean);
    return walk(root);
  };
  return {controller, root, calls, sourceCalls, states, find, navigate: () => { current = false; }, submit: () => find("form").onsubmit({preventDefault() {}})};
}

{
  const h = harness(); await h.controller.ready;
  assert.deepEqual(h.calls.map(call => call.path), ["/api/study/activity", "/api/study/cards/card/quiz"]);
  assert.equal(h.calls[0].body.kind, "reading");
  assert.equal(h.calls.filter(call => call.path.endsWith("/answer")).length, 0, "A viewed card is not an answer attempt");
  h.find("input").value = "Wrong"; await h.submit();
  assert.match(h.root.children.find(node => node.attributes.role === "status").textContent, /未匹配原文/);
  assert.equal(h.find("input").disabled, true);
  h.root.children.at(-1).onclick(); assert.deepEqual(h.sourceCalls, ["original"]);
  await h.submit(); assert.equal(h.calls.filter(call => call.path.endsWith("/answer")).length, 1);
}
{
  const pending = deferred(), h = harness({answer: () => pending.promise}); await h.controller.ready;
  h.find("input").value = "Word vectors";
  const first = h.submit(); await h.submit();
  assert.equal(h.calls.filter(call => call.path.endsWith("/answer")).length, 1, "Repeated submit while pending is ignored");
  h.controller.dispose(); const before = h.root.children.find(node => node.attributes.role === "status").textContent;
  pending.resolve({attempt: {correct: true, expected_answer: "Word vectors", source_evidence_ids: ["original"]}}); await first;
  assert.equal(h.root.children.find(node => node.attributes.role === "status").textContent, before, "Closed dialog cannot be updated by a late submission");
  assert.deepEqual(h.states, [true]);
}
{
  let attempt = 0; const bodies = [];
  const h = harness({answer: async body => { bodies.push(body); if (++attempt === 1) throw Error("Response lost"); return {attempt: {correct: true, expected_answer: "Word vectors"}}; }});
  await h.controller.ready; h.find("input").value = "Word vectors"; await h.submit();
  assert.equal(h.find("input").disabled, true, "Uncertain submission keeps the original answer frozen");
  await h.submit(); assert.deepEqual(bodies[0], bodies[1], "Retry uses exactly the same idempotency key and answer");
}
for (const action of ["dispose", "navigate", "reveal"]) {
  const pending = deferred(), h = harness({get: () => pending.promise});
  if (action === "navigate") h.navigate(); else h.controller[action]();
  pending.resolve(question); await h.controller.ready;
  assert.equal(h.find("form"), undefined, `${action} prevents a late question from appearing`);
  assert.equal(h.calls.filter(call => call.path.endsWith("/answer")).length, 0);
}
{
  const h = harness(); await h.controller.ready; h.find("input").value = "Word vectors"; h.controller.reveal(); await h.submit();
  assert.equal(h.calls.filter(call => call.path.endsWith("/answer")).length, 0, "Answer reveal/skip never creates a scored answer");
}
{
  const h = harness({get: async () => ({available: false})}); await h.controller.ready;
  assert.equal(h.find("form"), undefined); assert.match(h.root.children.at(-1).textContent, /不计客观正确率/);
}
console.log("Objective cloze keeps views, submissions, retries, reveal, source navigation and stale UI responses separate");
