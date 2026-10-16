import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";
import { readFileSync } from "node:fs";
const source = readFileSync(new URL("../course-episode-retry.js", import.meta.url), "utf8");
const defer = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
function harness() {
  const calls = [], messages = [], response = defer(), refreshed = defer(), events = new Map(); let generation = 0;
  const state = { epoch: 1 }, dialog = { open: true }, course = { id: "course/a", revision: 2, paused: false };
  const episode = { episode_id: "episode/a", task_id: "caption", generation: "owned-generation", retryable: true, retry_kind: "summary" };
  const h = { calls, messages, response, refreshed, state, dialog, course, episode, allow: true, confirm: true, holdRefresh: false,
    options: { content_mode: "visual", visual_understanding: true, local_ocr: true, resource_budget_mb: 240 } };
  const context = vm.createContext({ window: { addEventListener: (name, fn) => events.set(name, fn) }, confirm: text => { messages.push(text); return h.confirm; },
    api: async (path, options) => { calls.push({ path, body: JSON.parse(options.body) }); return response.promise; } });
  vm.runInContext(source.replace(/^import .*;\r?\n/gm, "").replaceAll("export ", ""), context);
  const retry = context.installCourseRetry({ state, dialog, generation: () => generation, options: () => h.options, guard: () => h.allow,
    status: text => messages.push(text), refresh: async () => { calls.push({ path: "refresh" }); if (h.holdRefresh) await refreshed.promise; },
    openCourse: async id => calls.push({ path: "openCourse", id }) });
  h.retry = () => retry(course, episode); h.other = () => generation++; h.navigate = () => events.get("learnnote:navigation")();
  return h;
}
const tick = async () => { for (let n = 0; n < 6; n++) await Promise.resolve(); };
test("caption retry captures course revision, task and generation and sends text-only options", async () => {
  const h = harness(), work = h.retry(); h.course.id = "other"; h.episode.task_id = "other"; h.options.resource_budget_mb = 900;
  assert.equal(h.calls[0].path, "/api/courses/course%2Fa/episodes/episode%2Fa/retry");
  assert.deepEqual(h.calls[0].body, { revision: 2, task_id: "caption", generation: "owned-generation", options: { content_mode: "text", visual_understanding: false, local_ocr: false, resource_budget_mb: 240 } });
  assert.match(h.messages[0], /不重新下载视频/); h.response.resolve({}); await work; assert.equal(h.calls.at(-1).id, "course/a");
});
test("media retry preserves current processing options while duplicate clicks coalesce", async () => {
  const h = harness(); h.episode.retry_kind = "media"; const work = h.retry(); await h.retry(); assert.equal(h.calls.length, 1);
  assert.deepEqual(h.calls[0].body.options, h.options); h.response.resolve({}); await work;
});
for (const action of ["other", "navigate", "close"]) test(`${action} suppresses late retry refresh and navigation`, async () => {
  const h = harness(), work = h.retry(); if (action === "close") h.dialog.open = false; else h[action](); h.response.resolve({}); await work; assert.equal(h.calls.length, 1);
});
test("a newer view while library refresh is pending cannot reopen the old course", async () => {
  const h = harness(); h.holdRefresh = true; const work = h.retry(); h.response.resolve({}); await tick(); h.other(); h.refreshed.resolve(); await work;
  assert.deepEqual(h.calls.map(call => call.path), ["/api/courses/course%2Fa/episodes/episode%2Fa/retry", "refresh"]);
});
test("guard, paused course and user cancellation prevent retry", async () => {
  const h = harness(); h.allow = false; await h.retry(); h.allow = true; h.confirm = false; await h.retry();
  h.course.paused = true; await assert.rejects(h.retry(), /暂停/); assert.equal(h.calls.length, 0);
});
test("rejected retry reports failure without automatically retrying", async () => {
  const h = harness(), work = h.retry(); h.response.reject(new Error("generation changed")); await work;
  assert.match(h.messages.at(-1), /不会自动重试/); assert.equal(h.calls.length, 1);
});
