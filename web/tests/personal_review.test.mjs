import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const code = readFileSync(new URL("../personal-review.js", import.meta.url), "utf8");
const { installPersonalReview, personalReviewView } = await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);
const tick = () => new Promise(resolve => setImmediate(resolve));
const record = (changes = {}) => ({ status: "unmarked", context_revision: "context-1", note_revision: "note-1",
  review_revision: "absent", can_mark: true, source_scope: "reading_only", scope_detail: "仅有可读正文。",
  source_labels: [], checked_at: null, ...changes });

function fixture() {
  const elements = new Map();
  class Element {
    constructor() { this.dataset = {}; this.hidden = false; this.textContent = ""; this.disabled = false; }
    set innerHTML(html) { for (const match of html.matchAll(/id="([^"]+)"/g)) elements.set(match[1], new Element()); }
    querySelector(selector) { return elements.get(selector.slice(1)); }
    setAttribute(name, value) { this[name] = value; }
    after(node) { elements.set(node.id, node); }
  }
  const reader = new Element();
  reader.dataset = { readerSource: "material:first", sourceRevision: "note-1" };
  elements.set("document", reader);
  const document = { createElement: () => new Element(), getElementById: id => elements.get(id) };
  const state = { selected: { kind: "material", id: "first" }, epoch: 1, revision: "note-1", editing: false };
  const requests = [], events = new EventTarget();
  let ids = 0, refreshes = 0;
  const controller = installPersonalReview({ state, document, events, requestId: () => `request-${++ids}`,
    refreshNote: async () => { refreshes++; }, api: (url, options) => {
      let resolve, reject;
      const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
      requests.push({ url, options, resolve, reject }); return promise;
    },
  });
  const $ = id => elements.get(id);
  const render = (id, revision) => {
    state.epoch++; state.selected = { kind: "material", id }; state.revision = revision;
    reader.dataset = { readerSource: `material:${id}`, sourceRevision: revision };
    events.dispatchEvent(new Event("learnnote:selection"));
  };
  const load = async (value = record()) => {
    const pending = controller.load(); requests.at(-1).resolve(value); await pending;
  };
  return { state, reader, requests, events, controller, $, render, load, refreshes: () => refreshes };
}

test("reading only loads status; explicit clicks send version-bound actions once", async () => {
  const f = fixture(); await f.load();
  assert.equal(f.requests.length, 1); assert.equal(f.requests[0].options, undefined);
  assert.equal(f.$("personalReviewState").textContent, "尚未记录个人核对");
  const pending = f.$("markPersonalReview").onclick(); await f.$("markPersonalReview").onclick();
  await f.controller.load();
  assert.equal(f.requests.length, 2);
  assert.deepEqual(JSON.parse(f.requests[1].options.body), { action: "mark", expected_context_revision: "context-1",
    expected_review_revision: "absent", request_id: "request-1" });
  assert.equal(f.$("revokePersonalReview").disabled, true);
  f.requests[1].resolve(record({ status: "current", review_revision: "review-1" })); await pending;
  assert.equal(f.$("personalReviewState").textContent, "本人已核对");
  assert.equal(f.$("markPersonalReview").disabled, true);
  const revoke = f.$("revokePersonalReview").onclick();
  assert.equal(JSON.parse(f.requests[2].options.body).expected_review_revision, "review-1");
  f.requests[2].resolve(record({ status: "revoked", review_revision: "review-2" })); await revoke;
  assert.equal(f.$("personalReviewState").textContent, "已撤销个人核对");
});

test("current means the displayed whole-note revision; unavailable source still permits revoke", async () => {
  const f = fixture(); await f.load(record({ status: "current", note_revision: "new-note" }));
  assert.notEqual(f.$("personalReviewState").textContent, "本人已核对");
  assert.equal(f.$("personalReview").dataset.status, "mismatch");
  assert.equal(f.$("markPersonalReview").disabled, true);
  assert.equal(f.$("revokePersonalReview").disabled, false);
  await f.$("refreshPersonalReview").onclick(); assert.equal(f.refreshes(), 1);
  await f.load(record({ status: "stale", note_revision: null, context_revision: null, can_mark: false }));
  const revoke = f.$("revokePersonalReview").onclick();
  assert.equal(JSON.parse(f.requests.at(-1).options.body).expected_context_revision, "");
  f.requests.at(-1).resolve(record({ status: "revoked", note_revision: null })); await revoke;
  assert.equal(f.$("markPersonalReview").disabled, true);
});

test("stale and imported records need another explicit click; literal source labels remain text", async () => {
  for (const status of ["stale", "imported"]) {
    const f = fixture(); await f.load(record({ status, source_labels: ["<script>literal</script>"] }));
    assert.equal(f.requests.length, 1); assert.equal(f.$("markPersonalReview").disabled, false);
    assert.equal(f.$("markPersonalReview").textContent, "重新核对并记录");
    assert.equal(f.$("revokePersonalReview").hidden, false);
    assert.match(f.$("personalReviewSources").textContent, /<script>literal<\/script>/);
  }
});

test("conflict refetches and keeps feedback without automatically remarking changed context", async () => {
  const f = fixture(); await f.load();
  const mark = f.$("markPersonalReview").onclick();
  f.requests[1].reject(Object.assign(new Error("stale"), { status: 409 })); await tick();
  assert.equal(f.requests.length, 3); assert.equal(f.requests[2].options, undefined);
  f.requests[2].resolve(record({ status: "stale", context_revision: "context-2", review_revision: "review-2" })); await mark;
  assert.equal(f.$("markPersonalReview").disabled, false);
  assert.match(f.$("personalReviewFeedback").textContent, /本次操作未应用.*再明确点击/);
  await f.load(record({ status: "stale", context_revision: "context-2", review_revision: "review-2" }));
  assert.match(f.$("personalReviewFeedback").textContent, /本次操作未应用/);
  const retry = f.$("markPersonalReview").onclick();
  assert.equal(JSON.parse(f.requests[4].options.body).expected_context_revision, "context-2");
  assert.equal(JSON.parse(f.requests[4].options.body).request_id, "request-2");
  f.requests[4].resolve(record({ status: "current" })); await retry;
});

test("lost action response reads actual state instead of repeating a write", async () => {
  const f = fixture(); await f.load(); const pending = f.$("markPersonalReview").onclick();
  f.requests[1].reject(new Error("connection lost")); await tick();
  f.requests[2].resolve(record({ status: "current", review_revision: "saved" })); await pending;
  assert.equal(f.requests.filter(request => request.options).length, 1);
  assert.equal(f.$("personalReviewState").textContent, "本人已核对");
  assert.match(f.$("personalReviewFeedback").textContent, /未能确认操作结果/);
});

test("late selection, edition, editor and Close responses cannot repaint or unlock the new panel", async () => {
  for (const finish of [request => request.resolve(record({ status: "current" })), request => request.reject(new Error("obsolete"))]) {
    const f = fixture(); await f.load(); const pending = f.$("markPersonalReview").onclick();
    f.render("second", "note-2");
    const newest = f.controller.load();
    finish(f.requests[1]); await pending;
    assert.equal(f.$("markPersonalReview").disabled, true);
    assert.doesNotMatch(f.$("personalReviewFeedback").textContent, /obsolete|未能确认/);
    f.requests[2].resolve(record({ note_revision: "note-2" })); await newest;
    assert.equal(f.$("personalReviewState").textContent, "尚未记录个人核对");
    const read = f.controller.load(); f.state.editing = true; f.controller.reset();
    f.requests[3].resolve(record({ status: "current", note_revision: "note-2" })); await read;
    assert.equal(f.$("personalReview").hidden, true);
    f.state.editing = false; f.state.selected = null; f.events.dispatchEvent(new Event("learnnote:selection"));
    await f.controller.load(); assert.equal(f.requests.length, 4);
  }
});

test("overlapping reads and rendered-version changes reject an old current result", async () => {
  const f = fixture(), older = f.controller.load(), latest = f.controller.load();
  f.requests[1].resolve(record({ status: "revoked" })); await latest;
  f.requests[0].resolve(record({ status: "current" })); await older;
  assert.equal(f.$("personalReviewState").textContent, "已撤销个人核对");
  const read = f.controller.load(); f.state.revision = f.reader.dataset.sourceRevision = "note-2";
  f.events.dispatchEvent(new Event("learnnote:document")); await tick();
  f.requests[2].resolve(record({ status: "current" })); await read;
  f.requests[3].resolve(record({ status: "stale", note_revision: "note-2" })); await tick();
  assert.equal(f.$("personalReviewState").textContent, "核对记录已过期");
});

test("failed reads and partial/mismatched reader surfaces never permit a mark", async () => {
  const f = fixture(); const read = f.controller.load(); f.requests[0].reject(new Error("unavailable")); await read;
  assert.match(f.$("personalReviewFeedback").textContent, /暂不可读取/);
  assert.equal(f.$("markPersonalReview").disabled, true);
  f.reader.dataset.readerSource = "material:another"; await f.controller.load();
  assert.equal(f.requests.length, 1); assert.equal(f.$("personalReview").hidden, true);
  assert.equal(personalReviewView(record({ note_revision: "other" }), "note-1").mark, false);
});


test("details are opt-in and reset only for a changed reader; status remains read-only", async () => {
  const f = fixture(); await f.load();
  assert.equal(f.$("personalReviewDetails").open, false);
  f.$("personalReviewDetails").open = true;
  await f.load(); assert.equal(f.$("personalReviewDetails").open, true);
  f.render("second", "note-2");
  assert.equal(f.$("personalReviewDetails").open, false);
  assert.equal(f.requests.filter(request => request.options).length, 0);
  assert.match(code, /个人操作记录，不代表内容已被证实/);
});
