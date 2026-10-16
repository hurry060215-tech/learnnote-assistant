import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
const retrySource = readFileSync(new URL("../course-episode-retry.js", import.meta.url), "utf8");
const source = readFileSync(new URL("../course-episodes.js", import.meta.url), "utf8");
const defer = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const event = () => ({ stopPropagation() {} });
const route = { base_url: "http://127.0.0.1:19877/v1", model: "synthetic-vision" };
const originalCourse = { id: "course/one", revision: 3, paused: false };
const originalEpisode = { episode_id: "episode/one", task_id: "caption-one", generation: "gen-one", retryable: true, retry_kind: "summary", caption_upgrade_available: true, title: "<Caption source>" };
const basePath = "/api/courses/course%2Fone/episodes/episode%2Fone";
const preview = () => ({ preview_id: "review/one", fingerprint: "a".repeat(64), source_task_id: "caption-one", episode_id: "episode/one", page_url: "https://example.test/watch?p=2&title=<safe>", title: "<Source>", connection: route, model_source: { title: "<Masked source>", url: "https://example.test/watch?p=2&token=[redacted]" }, resource_budget_mb: 240, warning: "Permission required", options: { max_frame_count: 900, frame_interval: 20, vision_batch_size: 4 } });
const accepted = () => ({ task_id: "visual-child", task: { id: "visual-child", status: "queued" }, source_task_id: "caption-one", episode_id: "episode/one", deduplicated: false });
function harness() {
  const nodes = new Map(), windowEvents = new Map(), calls = [], posts = [], opened = [], messages = [];
  let generation = 0, installed;
  class Element {
    constructor() { this.listeners = new Map(); this.checked = false; this.disabled = false; this.open = true; }
    set innerHTML(html) { this.html = html; for (const [, id, rest] of html.matchAll(/id="([^"]+)"([^>]*)/g)) { const el = new Element(); el.disabled = /disabled/.test(rest); nodes.set(id, el); } }
    addEventListener(name, fn) { if (!this.listeners.has(name)) this.listeners.set(name, []); this.listeners.get(name).push(fn); }
    async emit(name) { for (const fn of this.listeners.get(name) || []) await fn(event()); }
    close() { this.open = false; void this.emit("close"); }
  }
  const $ = id => nodes.get(id), dialog = new Element(), state = { epoch: 1 };
  const h = { $, calls, posts, opened, messages, dialog, state, route: { ...route }, configured: true, allow: true, confirm: true,
    course: { ...originalCourse }, episode: { ...originalEpisode }, options: { resource_budget_mb: 240, content_mode: "auto", visual_understanding: true, local_ocr: true, llm_api_key: "synthetic-key", llm_model: "draft", llm_base_url: "https://example.test/draft" } };
  const context = vm.createContext({ document: { getElementById: $ }, window: { addEventListener: (name, fn) => { if (!windowEvents.has(name)) windowEvents.set(name, []); windowEvents.get(name).push(fn); } },
    confirm: text => { messages.push(text); return h.confirm; },
    esc: value => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;"),
    api: async (path, options) => {
      calls.push({ path, method: options?.method || "GET", body: options?.body ? JSON.parse(options.body) : null });
      if (options?.method === "POST") { const held = defer(); posts.push({ path, ...held }); return held.promise; }
      if (options?.method === "DELETE") return { deleted: true };
      if (path === "/api/model/connection") { if (h.holdRoute) return h.holdRoute.promise; return { configured: h.configured, model: h.route }; }
      if (path.startsWith("/api/tasks/")) return { task: { id: decodeURIComponent(path.split("/").at(-1)) } };
      throw new Error("Unexpected API " + path);
    } });
  vm.runInContext(retrySource.replace(/^import .*;\r?\n/gm, "").replaceAll("export ", "") + source.replace(/^import .*;\r?\n/gm, "").replaceAll("export function", "function").replaceAll("snapshot(", "episodeScope(").replaceAll("endpoint(", "episodeEndpoint("), context);
  function show() { installed?.invalidate(); generation++; dialog.open = true; nodes.clear(); nodes.set("toolBody", new Element()); return generation; }
  const args = { state, dialog, show, generation: () => generation,
    status: text => messages.push(text), options: () => h.options, guard: () => h.allow,
    refresh: async () => { calls.push({ path: "refresh" }); if (h.holdRefresh) await h.holdRefresh.promise; },
    openCourse: async id => { calls.push({ path: "openCourse", id }); show(); }, openItem: async item => opened.push(item) };
  installed = context.installCourseEpisodes(args);
  const retry = context.installCourseRetry(args);
  show();
  h.retry = () => retry(h.course, h.episode); h.review = () => installed.review(h.course, h.episode);
  h.check = async id => { $(id).checked = true; await $(id).emit("change"); };
  h.submit = () => $("courseUpgradeConfirm").emit("click"); h.cancel = () => $("courseUpgradeCancel").emit("click");
  h.close = () => { generation++; dialog.close(); }; h.escape = () => { void dialog.emit("cancel"); dialog.close(); };
  h.other = () => show(); h.navigate = () => { state.epoch++; windowEvents.get("learnnote:navigation").forEach(fn => fn()); };
  h.settings = () => windowEvents.get("learnnote:settings").forEach(fn => fn()); h.html = () => $("toolBody").html;
  h.actions = () => context.episodeActionsHtml(h.episode, h.course.paused); h.linked = installed.openLinked;
  return h;
}
const tick = async () => { for (let n = 0; n < 8; n++) await Promise.resolve(); };
async function reviewed(h, value = preview()) { const work = h.review(); await tick(); h.posts.at(-1).resolve(value); await work; }
async function consent(h) { await h.check("courseUpgradeDownload"); await h.check("courseUpgradeShare"); }

test("retry captures immutable identity and forces caption text-only options", async () => {
  const h = harness(), work = h.retry();
  h.course.id = "different"; h.course.revision = 9; h.episode.task_id = "other"; h.options.resource_budget_mb = 800;
  assert.equal(h.posts[0].path, `${basePath}/retry`);
  assert.deepEqual(h.calls[0].body, { revision: 3, task_id: "caption-one", generation: "gen-one", options: { ...h.options, resource_budget_mb: 240, content_mode: "text", visual_understanding: false, local_ocr: false } });
  h.posts[0].resolve({}); await work;
  assert.equal(h.calls.at(-1).id, "course/one"); assert.match(h.messages[0], /不重新下载视频/);
});
test("retry double-click, paused, guard, cancel and stale refresh do not continue", async () => {
  const h = harness(), work = h.retry(); await h.retry(); assert.equal(h.posts.length, 1);
  h.close(); h.posts[0].resolve({}); await work; assert.equal(h.calls.length, 1);
  for (const condition of ["paused", "guard", "cancel"]) {
    const h = harness(); if (condition === "paused") h.course.paused = true; if (condition === "guard") h.allow = false; if (condition === "cancel") h.confirm = false;
    await h.retry().catch(error => assert.match(error.message, /暂停/)); assert.equal(h.posts.length, 0);
  }
  const late = harness(); late.holdRefresh = defer(); const pending = late.retry(); late.posts[0].resolve({}); await tick();
  late.other(); late.holdRefresh.resolve(); await pending; assert(!late.calls.some(call => call.path === "openCourse"));
});
test("upgrade requires separate fresh download and vision consents and exact saved route", async () => {
  const h = harness(); await reviewed(h);
  const body = h.calls.find(call => call.method === "POST").body;
  assert.equal(body.revision, 3); assert.equal(body.base_url, route.base_url); assert.equal(body.model, route.model);
  assert.equal(body.options.use_saved_connection, true); assert.equal(body.options.content_mode, "visual");
  assert(!("llm_api_key" in body.options)); assert(!("llm_model" in body.options)); assert(!("llm_base_url" in body.options));
  assert.match(h.html(), /240 MB/); assert.match(h.html(), /下载流量可能超过/); assert.match(h.html(), /抽帧上限 900 帧/); assert.match(h.html(), /每批最多 4 张画面网格/); assert.match(h.html(), /字幕文本、上方模型来源标题与网址/); assert.match(h.html(), /&lt;Source&gt;/); assert.match(h.html(), /&lt;Masked source&gt;/); assert.match(h.html(), /token=\[redacted\]/); assert.match(h.html(), /下载来源网址/); assert.match(h.html(), /发送给模型的来源网址/); assert.match(h.html(), /title=&lt;safe&gt;/);
  assert(!h.$("courseUpgradeDownload").checked); assert(!h.$("courseUpgradeShare").checked);
  await h.submit(); await h.check("courseUpgradeDownload"); await h.submit(); assert.equal(h.posts.length, 1);
  await h.check("courseUpgradeShare"); const work = h.submit(); await tick(); await h.submit();
  assert.equal(h.posts.length, 2); assert.deepEqual(h.calls.at(-1).body, { preview_id: "review/one", fingerprint: "a".repeat(64), confirm_download: true, share_images: true });
  h.posts[1].resolve(accepted()); await work; assert.match(h.html(), /原字幕笔记与课程分集仍保留/);
  await h.$("courseUpgradeOpen").emit("click"); assert.equal(h.opened[0].id, "visual-child"); assert.equal(h.course.id, "course/one"); assert.equal(h.episode.task_id, "caption-one");
});
for (const action of ["close", "escape", "other", "navigate", "settings"]) {
  test(`${action} invalidates an outstanding preview and suppresses late responses`, async () => {
    const h = harness(), work = h.review(); await tick(); h[action](); if (action === "navigate") assert.equal(h.dialog.open, false); const html = h.html(), messages = h.messages.length;
    h.posts[0].resolve(preview()); await work; assert.equal(h.html(), html); assert.equal(h.messages.length, messages);
    assert(h.calls.some(call => call.method === "DELETE" && call.path === `${basePath}/upgrade-preview/review%2Fone`));
  });
  test(`${action} after route recheck cannot submit a stale confirmation`, async () => {
    const h = harness(); await reviewed(h); await consent(h); h.holdRoute = defer(); const work = h.submit();
    h[action](); h.holdRoute.resolve({ configured: true, model: route }); await work; assert.equal(h.posts.length, 1);
    assert(h.calls.some(call => call.method === "DELETE"));
  });
}
test("cancel invalidates review and stale controls cannot resubmit; reopening resets both consents", async () => {
  const h = harness(); await reviewed(h); await consent(h); const stale = h.$("courseUpgradeConfirm");
  await h.cancel(); await stale.emit("click"); assert.equal(h.posts.length, 1);
  assert.equal(h.calls.find(call => call.method === "DELETE").path, `${basePath}/upgrade-preview/review%2Fone`);
  await reviewed(h); assert(!h.$("courseUpgradeDownload").checked); assert(!h.$("courseUpgradeShare").checked);
});
for (const mutate of [h => h.route = { ...route, model: "changed" }, h => h.options.resource_budget_mb++]) {
  test("changed route or options blocks confirmation and invalidates preview", async () => {
    const h = harness(); await reviewed(h); await consent(h); mutate(h); await h.submit();
    assert.equal(h.posts.length, 1); assert(h.calls.some(call => call.method === "DELETE")); assert.match(h.messages.at(-1), /设置已变化/);
  });
}
test("no configured model, paused course and mismatched preview fail closed", async () => {
  const h = harness(); h.configured = false; await h.review(); assert.equal(h.posts.length, 0);
  const wrong = harness(); await reviewed(wrong, { ...preview(), source_task_id: "unrelated" }); assert(!wrong.$("courseUpgradeConfirm")); assert(wrong.calls.some(call => call.method === "DELETE"));
  const paused = harness(); paused.course.paused = true; await assert.rejects(paused.review(), /暂停/); assert.equal(paused.posts.length, 0);
});
test("failed submit does not auto-retry and reopening cannot repeat an in-flight submission", async () => {
  const h = harness(); await reviewed(h); await consent(h); const work = h.submit(); await tick(); h.close();
  await h.review(); assert.equal(h.posts.length, 2); h.posts[1].reject(new Error("Uncertain response")); await work;
  const next = h.review(); await tick(); assert.equal(h.posts.length, 3); h.posts[2].resolve(preview()); await next;
  await consent(h); const failed = h.submit(); await tick(); h.posts[3].reject(new Error("Denied")); await failed;
  assert.match(h.messages.at(-1), /不会自动重试/); await h.submit(); assert.equal(h.posts.length, 4);
});
test("course row separates text retry, visual upgrade and original linked children", () => {
  const h = harness(); h.episode.upgrades = [{ task_id: 'child"<', status: "queued" }];
  assert.match(h.actions(), /重试字幕总结/); assert.match(h.actions(), /补充画面笔记/); assert.match(h.actions(), /data-open-upgrade="child&quot;&lt;"/);
  h.course.paused = true; assert.match(h.actions(), /data-upgrade-episode="episode\/one" disabled/);
});
console.log("Course episode identity, text retry, consent and stale lifecycle tests passed");
for (const action of ["close", "other", "navigate"]) test(`${action} suppresses a late accepted upgrade without reopening or refreshing another view`, async () => {
  const h = harness(); await reviewed(h); await consent(h); const oldBody = h.$("toolBody"), work = h.submit(); await tick();
  h[action](); const messages = h.messages.length; h.posts[1].resolve(accepted()); await work;
  assert(!oldBody.html.includes('id="courseUpgradeOpen"')); assert.equal(h.messages.length, messages);
  assert(!h.calls.some(call => call.path === "refresh")); assert.equal(h.opened.length, 0);
});
test("upgrade confirmation and return navigation retain the captured course and episode identity", async () => {
  const h = harness(); await reviewed(h); h.course.id = "new-course"; h.episode.task_id = "new-task"; h.episode.episode_id = "new-episode";
  await consent(h); const work = h.submit(); await tick(); assert.equal(h.posts[1].path, `${basePath}/upgrade`);
  h.posts[1].resolve(accepted()); await work; await h.$("courseUpgradeReturn").emit("click"); assert.equal(h.calls.at(-1).id, "course/one");
});
test("review refuses missing exact model-bound source metadata instead of guessing from download URL", async () => {
  const h = harness(), value = preview(); delete value.model_source; await reviewed(h, value);
  assert(!h.$("courseUpgradeConfirm")); assert(h.calls.some(call => call.method === "DELETE")); assert.equal(h.posts.length, 1);
});
