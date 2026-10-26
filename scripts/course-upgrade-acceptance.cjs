// Production frontend with synthetic HTTP fixtures. No backend, platform or model
// is contacted. Use the separate API/offline tests for backend behavior.
const assert = require("node:assert/strict");
const { fixtureTaskCatalog, fixtureMaterialPage } = require('./library-browser-fixture.cjs');
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const { completedAction, retryCourseReady, openChildReady, cleanupFixture } = require("./course-upgrade-fixture-helpers.cjs");

const root = path.resolve(__dirname, "..");
const date = "2026-10-09T10:00:00Z";
const material = (id, title) => ({ material_id: id, title, filename: `${id}.txt`, source_type: "text", status: "ready", linked_task_id: "", anchor_count: 1, created_at: date, updated_at: date, metadata: { encoding: "utf-8" } });
const materials = [material("document-a", "课程 A 原始文档"), material("document-b", "课程 B 独立文档")];
const tasks = [{ id: "video-a", title: "课程 A 原始字幕", status: "success", phase: "completed", summary_source: "subtitle-extract", transcript_path: "transcript.json", mode: "subtitle_only", options: {}, created_at: date, updated_at: date }];
const evidence = [
  { evidence_id: "video-a-quote", title: tasks[0].title, locator: "12-18s", source_type: "transcript", task_id: "video-a", text: "ALPHA original transcript concept at twelve seconds.", metadata: { start: 12, end: 18 } },
  { evidence_id: "document-a-quote", title: materials[0].title, locator: "第 2 段", source_type: "text", task_id: "", text: "ALPHA original document concept, preserved verbatim.", metadata: { material_id: "document-a" } },
  { evidence_id: "document-b-quote", title: materials[1].title, locator: "第 1 段", source_type: "text", task_id: "", text: "BETA independent document concept; course B only.", metadata: { material_id: "document-b" } },
];
const makeCourses = () => [
  { id: "course-a", title: "课程 A · 混合来源", revision: 3, paused: false, sources: [{ kind: "task", id: "video-a", title: tasks[0].title }, { kind: "material", id: "document-a", title: materials[0].title }] },
  { id: "course-b", title: "课程 B · 独立来源", revision: 7, paused: false, sources: [{ kind: "material", id: "document-b", title: materials[1].title }] },
  { id: "course-empty", title: "空课程", revision: 1, paused: false, sources: [] },
];

function deferred() { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; }
async function until(check, label) {
  const end = Date.now() + 15000;
  while (Date.now() < end) { if (check()) return; await new Promise(done => setTimeout(done, 40)); }
  throw new Error(`Timed out: ${label}`);
}
async function bounded(promise) {
  let timer;
  try { return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("Synthetic request did not start")), 15000); })]); }
  finally { clearTimeout(timer); }
}
function childEventStream(method, url, headers, fixtureTasks) {
  if (method !== "GET" || url.pathname !== "/api/tasks/visual-child/events/stream") return null;
  assert.equal(url.search, "?after=0"); assert.equal(headers["last-event-id"] || "", "");
  const child = fixtureTasks.find(task => task.id === "visual-child");
  assert(child, "Child stream requested before upgrade admission");
  assert.equal(child.status, "queued"); assert.equal(child.mode, "video"); assert.equal(child.source_task_id, "video-a");
  // A queued fixture has no progress events. Do not fabricate completion or
  // advance the cursor; the production hub closes this finite idle stream.
  return { contentType: "text/event-stream", headers: { "Cache-Control": "no-cache, no-transform" }, body: ": heartbeat\n\n" };
}
function queuedVisualChild(source) {
  return { id: "visual-child", source_type: "current_page", title: source.title, page_url: source.page_url || "",
    status: "queued", phase: "queued", progress: 0, mode: "video", awaiting_confirmation: false, error_code: "", checkpoint: "",
    summary_source: "", summary_warning: "", transcript_path: "", note_path: "", media_path: "", source_media_path: "",
    audio_path: "", subtitle_path: "", visual_index_path: "", frame_grids: [], visual_windows: [], source_task_id: source.id,
    options: { content_mode: "visual", visual_understanding: true }, created_at: date, updated_at: date };
}
function admitVisualChild(source, episode, fixtureTasks) {
  const task = queuedVisualChild(source);
  if (!fixtureTasks.some(item => item.id === task.id)) fixtureTasks.push(task);
  episode.upgrades = [{ task_id: task.id, status: "queued" }]; episode.caption_upgrade_available = false;
  return task;
}
function fixtureEdition(selected) {
  return { text: selected.status === "queued" && !selected.note_path ? "" : `# ${selected.title}\n\nSynthetic reader text with local source evidence.`, revision: "fixture", edited: false };
}
async function main() {
  const { chromium } = require("playwright");
  const base = new URL(process.argv[2] || "http://127.0.0.1:18940");
  assert(["127.0.0.1", "localhost", "[::1]"].includes(base.hostname)); assert.equal(base.protocol, "http:");
  const out = process.argv[3] || fs.mkdtempSync(path.join(os.tmpdir(), "learnnote-course-upgrade-")); fs.mkdirSync(out, { recursive: true });
  const report = { passed: false, synthetic_fixture: true, backend_tested: false, native_webview_tested: false, checks: [], screenshots: [], requests: [], errors: [], unexpectedRequests: [] };
  const courses = makeCourses(), calls = [], reviews = new Map();
  const episode = { episode_id: "caption-episode", position: 0, source_kind: "task", task_id: "video-a", generation: "1".repeat(64), title: tasks[0].title,
    status: "failed", retryable: true, retry_kind: "summary", content_mode: "text", caption_upgrade_available: true, upgrades: [] };
  let selectedModel = { base_url: "http://127.0.0.1:19877/v1", model: "synthetic-vision" }, holdPreview = null, holdUpgrade = null;
  const health = { ok: true, service: "learnnote", app_version: "0.2.14", backend_version: "0.2.14", protocol_version: 1, llm_model_configured: false, local_asr_available: false, default_llm_model: "", model_provider_presets: [], assistant_capabilities: {}, upload_policy: {} };
  let browser, primaryError;
  try {
    browser = await chromium.launch({ ...(process.platform === "win32" ? { channel: "msedge" } : { executablePath: process.env.CHROMIUM_PATH || "/usr/bin/chromium" }), headless: true });
    report.browser = browser.version(); report.platform = process.platform;
    const context = await browser.newContext({ viewport: { width: 1280, height: 960 }, reducedMotion: "reduce", serviceWorkers: "block" });
    await context.routeWebSocket("**/*", socket => { report.unexpectedRequests.push(`WebSocket ${socket.url()}`); socket.close(); });
    await context.route("**/*", async route => {
      const request = route.request(), url = new URL(request.url()), pathname = url.pathname;
      const json = (value, status = 200) => route.fulfill({ status, json: value });
      try {
        if (url.origin !== base.origin) { report.unexpectedRequests.push(`${request.method()} ${url.origin}${pathname}`); return route.abort("blockedbyclient"); }
        if (pathname === "/" || pathname.startsWith("/web/")) {
          const target = path.resolve(root, pathname === "/" ? "web/index.html" : decodeURIComponent(pathname.slice(1)));
          assert(target.startsWith(path.join(root, "web") + path.sep));
          return route.fulfill({ body: fs.readFileSync(target), contentType: { ".html": "text/html", ".js": "application/javascript", ".css": "text/css", ".png": "image/png" }[path.extname(target)] || "application/octet-stream" });
        }
        report.requests.push(`${request.method()} ${pathname}`);
        if (request.method() === "GET") {
          const stream = childEventStream(request.method(), url, request.headers(), tasks);
          if (stream) return route.fulfill(stream);
          if (pathname === "/health") return json(health);
          if (pathname === "/api/tasks") return json({ tasks });
          if (pathname === "/api/tasks/catalog") return json(fixtureTaskCatalog(tasks));
          if (pathname === "/api/library/materials") return json(fixtureMaterialPage(materials, url.search));
          if (pathname === "/api/preferences") return json({ task_options: { transcriber: "none", note_style: "study", note_template: "standard", summary_depth: "standard", local_ocr: false } });
          if (pathname === "/api/model/connection") return json({ model: selectedModel, configured: true });
          if (pathname === "/api/model/route") return json({ routes: [], blocking_reasons: [], data_leaving_device: [], offline_source_confirmed: true });
          if (pathname === "/api/connections") return json({ openrouter: { connected: false } });
          if (pathname === "/api/assistant/skills") return json({ skills: [], features: [] });
          if (pathname === "/api/assistant/history") return json({ items: [] });
          if (pathname === "/api/update/status") return json({ status: "up_to_date", preferences: { auto_check: false, auto_download: false } });
          if (pathname === "/api/courses") return json({ courses });
          if (/^\/api\/personal\/(material|task)\/[^/]+$/.test(pathname)) return json({ annotations: [] });
          const course = pathname.match(/^\/api\/courses\/([^/]+)$/);
          if (course) { const selected = courses.find(item => item.id === course[1]); return json(selected ? { course: selected, episodes: selected.id === "course-a" ? [episode] : [] } : { detail: "课程不存在或已删除" }, selected ? 200 : 404); }
          const personalReview = pathname.match(/^\/api\/tasks\/editions\/(material|task)\/([^/]+)\/personal-review$/);
          if (personalReview) {
            const selected = personalReview[1] === "task" ? tasks.find(item => item.id === personalReview[2]) : materials.find(item => item.material_id === personalReview[2]);
            assert(selected, `Unknown fixture review source: ${pathname}`);
            return json({ status: "unmarked", context_revision: null, note_revision: "fixture", review_revision: "0".repeat(64),
              can_mark: false, source_scope: "reading_only", scope_detail: "此合成场景不执行个人核对操作。", checked_at: null, source_labels: [] });
          }
          const edition = pathname.match(/^\/api\/tasks\/editions\/(material|task)\/([^/]+)$/);
          if (edition) { const selected = edition[1] === "task" ? tasks.find(item => item.id === edition[2]) : materials.find(item => item.material_id === edition[2]); assert(selected); return json(fixtureEdition(selected)); }
          const materialRead = pathname.match(/^\/api\/library\/materials\/([^/]+)(?:\/(content|anchors))?$/);
          if (materialRead) {
            const selected = materials.find(item => item.material_id === materialRead[1]); assert(selected);
            const anchors = evidence.filter(item => item.metadata.material_id === selected.material_id);
            return json(materialRead[2] === "content" ? { material_id: selected.material_id, text: anchors.map(item => item.text).join("\n") } : materialRead[2] === "anchors" ? { anchors } : { material: selected });
          }
          const source = pathname.match(/^\/api\/knowledge\/evidence\/([^/]+)$/);
          if (source) { const selected = evidence.find(item => item.evidence_id === decodeURIComponent(source[1])); assert(selected); return json({ evidence: selected }); }
          const taskMatch = pathname.match(/^\/api\/tasks\/([^/]+)$/);
          if (taskMatch) return json({ task: tasks.find(item => item.id === taskMatch[1]) });
          if (pathname === "/api/tasks/visual-child/events") return json({ events: [] });
          if (pathname === "/api/tasks/video-a/events") return json({ events: [] });
          if (pathname === "/api/tasks/video-a/transcript") return json({ segments: [{ start: 0, end: 5, text: "Earlier original introduction." }, { start: 12, end: 18, text: evidence[0].text }] });
        }

        if (pathname === "/api/study/activity" && request.method() === "POST") return json({ ok: true });
        const action = pathname.match(/^\/api\/courses\/([^/]+)\/episodes\/([^/]+)\/(retry|upgrade-preview|upgrade)(?:\/([^/]+))?$/);
        if (action) {
          assert.equal(action[1], "course-a"); assert.equal(action[2], episode.episode_id);
          const payload = request.method() === "DELETE" ? null : request.postDataJSON(); calls.push({ action: action[3], method: request.method(), payload });
          if (request.method() === "DELETE") { reviews.delete(action[4]); return json({ cancelled: true }); }
          if (action[3] === "retry") {
            assert.equal(payload.revision, courses[0].revision); assert.equal(payload.task_id, "video-a"); assert.equal(payload.generation, episode.generation);
            assert.equal(payload.options.content_mode, "text"); assert.equal(payload.options.visual_understanding, false); assert.equal(payload.options.local_ocr, false);
            return json({ task_id: "video-a", task: tasks[0] });
          }
          if (action[3] === "upgrade-preview") {
            assert.equal(payload.revision, courses[0].revision); assert.equal(payload.base_url, selectedModel.base_url); assert.equal(payload.model, selectedModel.model);
            assert.equal(payload.options.content_mode, "visual"); assert.equal(payload.options.visual_understanding, true); assert.equal(payload.options.use_saved_connection, true);
            assert(!("llm_api_key" in payload.options)); assert(!("llm_base_url" in payload.options)); assert(!("llm_model" in payload.options));
            const preview_id = "preview-" + calls.length;
            const value = { preview_id, fingerprint: "a".repeat(64), source_task_id: "video-a", episode_id: episode.episode_id,
              page_url: "https://example.test/course?p=2&source=synthetic", title: "Synthetic caption source", model_source: { title: "Synthetic caption source", url: "https://example.test/course?p=2&source=synthetic" }, connection: { ...selectedModel }, resource_budget_mb: 512,
              options: { max_frame_count: 900, frame_interval: 20, vision_batch_size: 4, ...payload.options }, warning: "无法访问、DRM 或预算不足时会停止，不绕过访问控制。" };
            reviews.set(preview_id, value);
            if (holdPreview) { const held = holdPreview; holdPreview = null; held.preview_id = preview_id; held.started.resolve(); await held.release.promise; }
            return json(value);
          }
          assert.deepEqual(Object.keys(payload).sort(), ["confirm_download", "fingerprint", "preview_id", "share_images"]);
          assert.equal(payload.confirm_download, true); assert.equal(payload.share_images, true); assert(reviews.has(payload.preview_id));
          if (holdUpgrade) { const held = holdUpgrade; holdUpgrade = null; held.started.resolve(); await held.release.promise; }
          const task = admitVisualChild(tasks[0], episode, tasks);
          return json({ task_id: task.id, task, source_task_id: "video-a", episode_id: episode.episode_id, deduplicated: false });
        }
        report.unexpectedRequests.push(`${request.method()} ${pathname}`); return json({ detail: "Unexpected fixture request" }, 501);
      } catch (error) { report.errors.push(`Fixture route: ${error.message}`); await route.abort("failed").catch(() => {}); }
    });
    const page = await context.newPage(); page.setDefaultTimeout(15000);
    page.on("pageerror", error => report.errors.push(error.message)); page.on("dialog", dialog => dialog.accept());
    const count = action => calls.filter(call => call.action === action && call.method === "POST").length;
    const prefix = `${base.origin}/api/courses/course-a/episodes/${episode.episode_id}`;
    async function open() {
      if (await page.locator("#toolsDialog").evaluate(el => el.open)) await page.locator("[data-close-tool]").click();
      if (!(await page.locator("#readerOptions").evaluate(el => el.open))) await page.locator("#readerOptions > summary").click();
      await page.locator("#moreTools").click(); await page.locator('[data-action="courses"]').click();
      await page.locator('[data-course="course-a"]').click(); await page.locator("[data-upgrade-episode]").waitFor();
    }
    async function review() {
      const response = await completedAction(page, "POST", prefix + "/upgrade-preview", () => page.locator("[data-upgrade-episode]").click());
      await page.locator("#courseUpgradeConfirm").waitFor(); return response.json();
    }
    async function consent() { await page.locator("#courseUpgradeDownload").check(); await page.locator("#courseUpgradeShare").check(); }
    async function screenshot(name) {
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      const geometry = await page.locator(".course-upgrade").evaluate(el => { const r = el.getBoundingClientRect(); return { left: r.left, right: r.right, scrollWidth: el.scrollWidth, width: el.clientWidth, viewport: innerWidth }; });
      assert(geometry.left >= 0 && geometry.right <= geometry.viewport + 1); assert(geometry.scrollWidth <= geometry.width + 1);
      await page.screenshot({ path: path.join(out, name), animations: "disabled" }); report.screenshots.push({ name, geometry });
    }
    await page.goto(base.href); await page.locator('#welcome[data-ready="true"]').waitFor();
    await page.locator('#notes [data-id="document-a"]').click(); await open();
    await retryCourseReady(page, { url: prefix + "/retry", retrySelector: "[data-retry-episode]", readySelector: "[data-upgrade-episode]", title: courses[0].title });
    assert.equal(count("retry"), 1); report.checks.push("Course-bound summary retry uses original task/generation and text-only options");
    const cancelledReview = await review(); assert.equal(count("upgrade"), 0); assert(await page.locator("#courseUpgradeConfirm").isDisabled());
    assert(!(await page.locator("#courseUpgradeDownload").isChecked())); assert(!(await page.locator("#courseUpgradeShare").isChecked()));
    assert.match(await page.locator("#toolBody").innerText(), /512 MB/); assert.match(await page.locator("#toolBody").innerText(), /字幕文本、上方模型来源标题与网址/);
    await page.locator("#courseUpgradeDownload").check(); assert(await page.locator("#courseUpgradeConfirm").isDisabled());
    await screenshot("01-upgrade-review-desktop.png");
    await page.setViewportSize({ width: 390, height: 844 }); await screenshot("02-upgrade-review-mobile.png");
    await page.evaluate(() => document.body.classList.add("dark")); await screenshot("03-upgrade-review-dark.png");
    const cancelled = await completedAction(page, "DELETE", `${prefix}/upgrade-preview/${cancelledReview.preview_id}`, () => page.locator("#courseUpgradeCancel").click());
    assert.equal((await cancelled.json()).cancelled, true); assert(!reviews.has(cancelledReview.preview_id));
    await page.locator("#courseUpgradeConfirm").waitFor({ state: "detached" });
    await page.locator("[data-upgrade-episode]").waitFor(); assert.equal(count("upgrade"), 0);
    await review(); assert(!(await page.locator("#courseUpgradeDownload").isChecked())); await consent();
    const initialModel = selectedModel; selectedModel = { ...selectedModel, model: "changed-model" };
    await page.locator("#courseUpgradeConfirm").click(); await page.locator("#toolStatus").getByText(/设置已变化/).waitFor(); assert.equal(count("upgrade"), 0); selectedModel = initialModel;
    report.checks.push("Source URL, fresh budget and full model payload disclosure; unchecked separate consents; cancel and saved-route change prevent submission");
    await page.setViewportSize({ width: 1280, height: 960 }); await page.evaluate(() => document.body.classList.remove("dark"));
    for (const dismiss of ["close", "escape", "back", "navigation"]) {
      await open(); const held = { started: deferred(), release: deferred() }; holdPreview = held;
      await page.locator("[data-upgrade-episode]").click(); await bounded(held.started.promise);
      if (dismiss === "close") await page.locator("[data-close-tool]").click();
      if (dismiss === "escape") await page.keyboard.press("Escape");
      if (dismiss === "back") await page.locator("[data-tool-back]").click();
      if (dismiss === "navigation") await page.evaluate(() => window.dispatchEvent(new Event("learnnote:navigation")));
      const discarded = await completedAction(page, "DELETE", `${prefix}/upgrade-preview/${held.preview_id}`, () => held.release.resolve());
      assert.equal((await discarded.json()).cancelled, true); assert(!reviews.has(held.preview_id));
      await page.locator("#courseUpgradeConfirm").waitFor({ state: "detached" });
      assert.equal(count("upgrade"), 0);
    }
    report.checks.push("Delayed previews are discarded after Close, Escape, Back and source navigation");
    await open(); await review(); await consent(); const original = JSON.stringify(tasks[0]), courseSources = JSON.stringify(courses[0].sources);
    const held = { started: deferred(), release: deferred() }; holdUpgrade = held;
    await page.locator("#courseUpgradeConfirm").evaluate(button => { button.click(); button.click(); }); await bounded(held.started.promise); assert.equal(count("upgrade"), 1);
    held.release.resolve(); await page.locator("#courseUpgradeOpen").waitFor();
    await page.locator("#courseUpgradeReturn").click(); await page.locator('[data-open-upgrade="visual-child"]').waitFor();
    assert.equal(await page.locator("[data-upgrade-episode]").count(), 0);
    assert.equal(JSON.stringify(tasks[0]), original); assert.equal(JSON.stringify(courses[0].sources), courseSources);
    await openChildReady(page, { base: base.origin, id: "visual-child", title: tasks[0].title });
    await page.locator('#document[data-reader-source="task:visual-child"]').getByText("笔记准备好后会显示在这里，你可以先查看处理进度。", { exact: true }).waitFor();
    await until(() => report.requests.includes("GET /api/tasks/visual-child/events/stream"), "linked child event stream");
    report.checks.push("Repeated confirmation creates one linked child; original task and course source remain unchanged; linked child opens");
    assert.deepEqual(report.errors, []); assert.deepEqual(report.unexpectedRequests, []); report.passed = true;
  } catch (error) { primaryError = error; throw error; }
  finally { await cleanupFixture({ report: () => fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(report, null, 2)), browser: () => browser?.close() }, primaryError); }
  console.log(JSON.stringify(report, null, 2));
}
module.exports = { childEventStream, queuedVisualChild, admitVisualChild, fixtureEdition };
if (require.main === module) main().catch(error => { console.error(error); process.exitCode = 1; });
