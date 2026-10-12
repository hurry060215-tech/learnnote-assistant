import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";

const source = readFileSync(new URL("../desk.js", import.meta.url), "utf8");
const handler = source.slice(source.indexOf('$("reviewContent").onclick = async e => {'), source.indexOf('window.addEventListener("beforeunload"'));
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return {promise, resolve, reject}; };
{
  let onClose, disposed = 0;
  const dialog = {open: true, addEventListener: (_name, listener) => { onClose = listener; }};
  const context = vm.createContext({$: () => dialog});
  vm.runInContext(source.slice(source.indexOf("let reviewSession ="), source.indexOf("let evidenceRequest =")), context);
  context.dispose = () => { disposed++; };
  vm.runInContext("reviewSession = 2; reviewQuiz = {dispose};", context);
  onClose();
  assert.equal(vm.runInContext("reviewSession", context), 2, "Delayed close event preserves a newer open session");
  assert.equal(disposed, 0);
  dialog.open = false; onClose(); assert.equal(disposed, 1);
}
function harness() {
  const pending = deferred(), posts = [], dialog = {open: true}, content = {}, state = {cards: [{card_id: "one"}]};
  let controls = [], key = 0, draws = 0;
  content.querySelectorAll = () => controls;
  const context = vm.createContext({state, reviewSession: 1, reviewRender: 1,
    $: id => id === "reviewContent" ? content : dialog,
    crypto: {randomUUID: () => `key-${++key}`},
    api: async (path, options) => { posts.push(JSON.parse(options.body)); return posts.length === 1 ? pending.promise : {card: {}}; },
    notice() {}, failure() {}, drawReview() { draws++; }, openEvidence() {},
  });
  vm.runInContext(handler, context);
  const render = () => {
    controls = [1, 2, 3, 4].map(rating => ({dataset: {rating: String(rating)}, disabled: false}));
    controls.push({id: "editReviewCard", disabled: false}, {id: "deleteReviewCard", disabled: false}, {id: "editorSubmit", disabled: false});
  };
  render();
  return {context, state, pending, posts, dialog, controls: () => controls, draws: () => draws,
    reopen() { context.reviewSession++; context.reviewRender++; render(); },
    click(rating = 3) { const button = controls[rating - 1]; return content.onclick({target: {closest: () => button}}); },
  };
}

{
  const h = harness(); const first = h.click(3);
  assert(h.controls().every(control => control.disabled), "Rating submission also disables conflicting edits and deletion");
  await h.click(4); assert.equal(h.posts.length, 1);
  h.reopen(); // New GET still contained the same card before the old POST finished.
  h.pending.resolve({card: {}}); await first;
  assert.equal(h.draws(), 0, "Old response must not shift or redraw the reopened session");
  assert.equal(h.state.reviewSubmission.key, "key-1", "Same visible card retains the uncertain/confirmed old submission identity");
  await h.click(4);
  assert.deepEqual(h.posts[1], h.posts[0], "Reopened same-card retry cannot create another FSRS review or change the rating");
  assert.equal(h.state.reviewSubmission, null);
  assert.equal(h.draws(), 1);
  assert.equal(h.state.cards.length, 0);
}
{
  const h = harness(); const first = h.click(); h.pending.reject(Error("response lost")); await first;
  assert(h.controls().every(control => !control.disabled));
  await h.click(2); assert.deepEqual(h.posts[1], h.posts[0]);
}
{
  const h = harness(); const first = h.click(3);
  h.reopen(); h.pending.resolve({card: {}}); await first;
  h.state.cards = [{card_id: "one", reps: 1, last_reviewed_at: "2026-10-09T10:00:00+00:00"}];
  await h.click(2);
  assert.notEqual(h.posts[1].idempotency_key, h.posts[0].idempotency_key, "A later due review with an advanced FSRS snapshot gets its own key");
  assert.equal(h.posts[1].rating, 2);
}
console.log("Pending FSRS ratings block edits and retain submission identity through close/reopen and lost replies");
