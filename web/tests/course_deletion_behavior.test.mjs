import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../desk-tools.js", import.meta.url), "utf8");
const code = source.slice(source.indexOf("  const deletionReason ="), source.indexOf("  async function studySettings("));
const cancelAction = source.match(/"cancel-delete-course": (.+),\n/)[1];
const deferred = () => { let resolve, reject; const promise = new Promise((done, fail) => { resolve = done; reject = fail; }); return { promise, resolve, reject }; };
const snapshot = () => ({ course_id: "course-a", title: "Course A", revision: 3, snapshot: "a".repeat(64), unlinked: [], tasks: [
  { task_id: "delete-me", title: "Delete me", eligible: true },
  { task_id: "keep-me", title: "Keep me", eligible: true },
  { task_id: "shared", title: "Shared", eligible: false, reason: "shared_task" },
] });
function harness() {
  let nodes, inputs;
  const calls = [], response = deferred(), preview = deferred(), refreshed = deferred();
  let holdPreview = false, holdRefresh = false;
  function reset() {
    nodes = new Map(); inputs = [];
    nodes.set("toolBody", { set innerHTML(html) {
      for (const match of html.matchAll(/<input[^>]*data-delete-course-task="([^"]+)"[^>]*>/g)) inputs.push({ dataset: { deleteCourseTask: match[1] }, checked: false, disabled: / disabled/.test(match[0]) });
      for (const [, id] of html.matchAll(/ id="([^"]+)"/g)) nodes.set(id, { textContent: "", disabled: false });
    } });
  }
  reset();
  const context = vm.createContext({ console,
    $: id => nodes.get(id), esc: value => String(value),
    dialog: { querySelectorAll: selector => selector.includes(":checked") ? inputs.filter(input => input.checked) : [...inputs.filter(input => !input.disabled), nodes.get("confirmCourseDeletion")] },
    guard: () => true, state: { selected: { kind: "task", id: "delete-me" } },
    request: (path, options) => { calls.push({ kind: "delete", path, body: JSON.parse(options.body) }); return response.promise; },
    api: async path => { calls.push({ kind: "preview", path }); return holdPreview ? preview.promise : snapshot(); },
    refresh: async () => { calls.push({ kind: "refresh" }); if (holdRefresh) await refreshed.promise; },
    ctx: { showHome: () => calls.push({ kind: "home" }) },
    status: text => calls.push({ kind: "status", text }),
    openCourse: id => calls.push({ kind: "open", id }), reset,
  });
  vm.runInContext(`let generation = 0, course = { id: "course-a" }, courseDeletion = null, backAction;
    function show() { generation++; reset(); return generation; }
    async function listCourses() { generation++; globalThis.listed = true; }
    ${code}
    globalThis.review = reviewCourseDeletion; globalThis.confirm = confirmCourseDeletion; globalThis.count = updateCourseDeletionCount;
    globalThis.cancel = ${cancelAction}; globalThis.dismiss = () => { generation++; course = { id: "new-course" }; };`, context);
  return { context, calls, response, preview, refreshed, input: id => inputs.find(input => input.dataset.deleteCourseTask === id),
    text: id => nodes.get(id)?.textContent, holdPreview: () => { holdPreview = true; }, holdRefresh: () => { holdRefresh = true; } };
}
const flush = () => new Promise(done => setImmediate(done));

test("real deletion review defaults to keeping children and cancellation sends no delete", async () => {
  const h = harness(); await h.context.review();
  assert.equal(h.input("delete-me").checked, false);
  assert.equal(h.input("shared").disabled, true);
  assert.match(h.text("courseDeletionCount"), /0 个子任务/);
  assert.match(h.text("confirmCourseDeletion"), /保留全部任务/);
  h.context.cancel();
  assert.deepEqual(h.calls.map(call => call.kind), ["preview", "open"]);
  assert.equal(h.calls[1].id, "course-a");
});

test("real confirmation counts exactly the chosen children and suppresses repeated submission", async () => {
  const h = harness(); await h.context.review(); h.input("delete-me").checked = true; h.context.count();
  assert.match(h.text("confirmCourseDeletion"), /1 个子任务/);
  const pending = h.context.confirm(); await h.context.confirm();
  const request = h.calls.find(call => call.kind === "delete");
  assert.deepEqual(request.body, { confirm: "delete_course", revision: 3, snapshot: "a".repeat(64), task_ids: ["delete-me"] });
  assert.equal(h.calls.filter(call => call.kind === "delete").length, 1);
  h.response.resolve({ deleted: true, deleted_task_ids: ["delete-me"] }); await pending;
  assert.ok(h.calls.some(call => call.kind === "home")); assert.ok(h.context.listed);
  assert.match(h.calls.at(-1).text, /删除了 1 个子任务/);
});

test("default confirmation submits no child IDs", async () => {
  const h = harness(); await h.context.review(); const pending = h.context.confirm();
  assert.deepEqual(h.calls.find(call => call.kind === "delete").body.task_ids, []);
  h.response.resolve({ deleted: true, deleted_task_ids: [] }); await pending;
  assert.ok(!h.calls.some(call => call.kind === "home"));
});

test("stale review cannot submit and a late preview cannot replace newer navigation", async () => {
  const h = harness(); h.holdPreview(); const pending = h.context.review();
  h.context.dismiss(); h.preview.resolve(snapshot()); await pending; await h.context.confirm();
  assert.equal(h.input("delete-me"), undefined); assert.ok(!h.calls.some(call => call.kind === "delete"));
});

test("late delete completion refreshes data without reopening or clearing a newer screen", async () => {
  const h = harness(); await h.context.review(); h.input("delete-me").checked = true; h.holdRefresh();
  const pending = h.context.confirm(); h.response.resolve({ deleted: true, deleted_task_ids: ["delete-me"] }); await flush();
  h.context.dismiss(); h.context.state.selected = { kind: "task", id: "new-selection" }; h.refreshed.resolve(); await pending;
  assert.ok(h.calls.some(call => call.kind === "refresh")); assert.ok(!h.calls.some(call => call.kind === "home")); assert.ok(!h.context.listed);
});

test("partial cleanup keeps the review open, clears selections and names actual outcomes", async () => {
  const h = harness(); await h.context.review(); h.input("delete-me").checked = true; h.input("keep-me").checked = true;
  const pending = h.context.confirm(); h.response.resolve({ deleted: false, deleted_task_ids: ["delete-me"], task_outcomes: [
    { task_id: "delete-me", deleted: true }, { task_id: "keep-me", deleted: false, error: "task_index_cleanup_failed" },
  ] }); await pending;
  assert.ok(!h.context.listed); assert.equal(h.input("keep-me").checked, false);
  assert.match(h.calls.at(-1).text, /课程仍保留.*Delete me：已删除.*Keep me：清理未完成/);
});

test("rejected stale confirmation leaves choices reviewable and preserves protected controls", async () => {
  const h = harness(); await h.context.review(); h.input("delete-me").checked = true;
  const pending = h.context.confirm(); h.response.reject(new Error("课程已变化")); await assert.rejects(pending, /课程已变化/);
  assert.equal(h.input("delete-me").disabled, false); assert.equal(h.input("shared").disabled, true); assert.ok(!h.context.listed);
});

test("a failed library refresh cannot hide a confirmed deletion or invite a duplicate delete", async () => {
  const h = harness(); await h.context.review(); h.input("delete-me").checked = true; h.holdRefresh();
  const pending = h.context.confirm(); h.response.resolve({ deleted: true, deleted_task_ids: ["delete-me"] }); await flush();
  h.refreshed.reject(new Error("Offline")); await pending;
  assert.ok(h.context.listed); assert.match(h.calls.at(-1).text, /课程已删除.*删除了 1 个子任务.*暂未刷新/);
  await h.context.confirm(); assert.equal(h.calls.filter(call => call.kind === "delete").length, 1);
});
