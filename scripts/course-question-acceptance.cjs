// Synthetic Windows Edge acceptance for the shipped reader. All app assets and
// API responses are intercepted; no backend, media site or model is contacted.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");

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
function answer(course) {
  const results = evidence.filter(item => course.sources.some(source => source.kind === (item.task_id ? "task" : "material") && source.id === (item.task_id || item.metadata.material_id)));
  return { answer: results.length ? results.map(item => item.text).join("\n") : "这门课程没有可用原文证据。", grounded: Boolean(results.length),
    citations: results.map(item => ({ evidence_id: item.evidence_id, title: item.title, locator: item.locator, source_kind: item.task_id ? "task" : "material", source_id: item.task_id || item.metadata.material_id, start: item.metadata.start ?? null, end: item.metadata.end ?? null })),
    results, retrieval_method: "lexical", scope: { kind: "course", id: course.id, title: course.title, revision: course.revision } };
}
function deferred() { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; }
async function bounded(promise) {
  let timer;
  try { return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("Synthetic request did not start")), 15000); })]); }
  finally { clearTimeout(timer); }
}

async function main() {
  const { chromium } = require("playwright");
  const base = new URL(process.argv[2] || "http://127.0.0.1:18930");
  assert(["127.0.0.1", "localhost", "[::1]"].includes(base.hostname));
  assert.equal(base.protocol, "http:");
  const out = process.argv[3] || fs.mkdtempSync(path.join(os.tmpdir(), "learnnote-course-question-"));
  fs.mkdirSync(out, { recursive: true });
  const report = { passed: false, synthetic_fixture: true, backend_tested: false, native_webview_tested: false, browser: "Microsoft Edge", checks: [], requests: [], screenshots: [], errors: [], unexpectedRequests: [] };
  const courses = makeCourses(), holds = new Map(), asks = [];
  let browser, page;
  const health = { ok: true, service: "learnnote", app_version: "0.2.14", backend_version: "0.2.14", protocol_version: 1, llm_model_configured: false, local_asr_available: false, default_llm_model: "", model_provider_presets: [], assistant_capabilities: {}, upload_policy: {} };
  function hold(question) {
    const entry = { started: deferred(), release: deferred() };
    holds.set(question, entry);
    return entry;
  }
  async function settle() { await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))); }
  async function release(entry, question) {
    const response = page.waitForResponse(response => response.request().method() === "POST" && response.url().endsWith("/ask") && response.request().postDataJSON().question === question);
    entry.release.resolve(); await response; await settle();
  }
  async function screenshot(name) {
    await page.screenshot({ path: path.join(out, name), animations: "disabled", fullPage: true });
    report.screenshots.push(name);
  }
  async function open(courseId = "course-a") {
    await page.locator("#moreTools").click();
    await page.locator('#toolBody [data-action="courses"]').click();
    await page.locator(`[data-course="${courseId}"]`).click();
    await page.locator('[data-action="course-question"]').click();
    await page.waitForFunction(() => document.querySelector("#courseQuestionSubmit")?.disabled === false);
    assert.equal(await page.locator("#courseQuestionScope").inputValue(), courseId);
  }
  async function choose(courseId) {
    await page.locator("#courseQuestionScope").selectOption(courseId);
    await page.waitForFunction(id => document.querySelector("#courseQuestionScope").value === id && !document.querySelector("#courseQuestionSubmit").disabled, courseId);
  }
  async function ask(question) {
    await page.locator("#courseQuestionText").fill(question);
    await page.locator("#courseQuestionSubmit").click();
  }
  async function result(marker) { await page.waitForFunction(marker => document.querySelector("#courseQuestionResult")?.textContent.includes(marker), marker); }
  async function close() { await page.locator("#toolsDialog [data-close-tool]").click(); await page.waitForFunction(() => !document.querySelector("#toolsDialog").open); }
  try {
    browser = await chromium.launch({ channel: "msedge", headless: true });
    const context = await browser.newContext({ viewport: { width: 1536, height: 1024 }, reducedMotion: "reduce", serviceWorkers: "block" });
    await context.routeWebSocket("**/*", socket => { report.unexpectedRequests.push(`WebSocket ${socket.url()}`); socket.close(); });
    await context.route("**/*", async route => {
      const request = route.request(), url = new URL(request.url()), pathname = url.pathname;
      const json = (value, status = 200) => route.fulfill({ status, json: value });
      try {
        if (url.origin !== base.origin) { report.unexpectedRequests.push(`${request.method()} ${url.origin}${pathname}`); return route.abort("blockedbyclient"); }
        if (pathname === "/" || pathname.startsWith("/web/")) {
          assert.equal(request.method(), "GET");
          const target = path.resolve(root, pathname === "/" ? "web/index.html" : decodeURIComponent(pathname.slice(1)));
          assert(target.startsWith(path.join(root, "web") + path.sep));
          assert(fs.statSync(target).isFile());
          return route.fulfill({ body: fs.readFileSync(target), contentType: { ".html": "text/html", ".js": "application/javascript", ".css": "text/css", ".png": "image/png", ".svg": "image/svg+xml", ".woff2": "font/woff2" }[path.extname(target)] || "application/octet-stream" });
        }
        report.requests.push(`${request.method()} ${pathname}`);
        if (request.method() === "GET") {
          if (pathname === "/health") return json(health);
          if (pathname === "/api/tasks") return json({ tasks });
          if (pathname === "/api/library/materials") return json({ materials });
          if (pathname === "/api/preferences") return json({ task_options: { transcriber: "none", note_style: "study", note_template: "standard", summary_depth: "standard", local_ocr: false } });
          if (pathname === "/api/model/connection") return json({ model: null, configured: false });
          if (pathname === "/api/model/route") return json({ routes: [], blocking_reasons: [], data_leaving_device: [], offline_source_confirmed: true });
          if (pathname === "/api/connections") return json({ openrouter: { connected: false } });
          if (pathname === "/api/assistant/skills") return json({ skills: [], features: [] });
          if (pathname === "/api/assistant/history") return json({ items: [] });
          if (pathname === "/api/update/status") return json({ status: "up_to_date", preferences: { auto_check: false, auto_download: false } });
          if (pathname === "/api/courses") return json({ courses });
          if (/^\/api\/personal\/(material|task)\/[^/]+$/.test(pathname)) return json({ annotations: [] });
          const course = pathname.match(/^\/api\/courses\/([^/]+)$/);
          if (course) { const selected = courses.find(item => item.id === course[1]); return json(selected ? { course: selected, episodes: [] } : { detail: "课程不存在或已删除" }, selected ? 200 : 404); }
          const edition = pathname.match(/^\/api\/tasks\/editions\/(material|task)\/([^/]+)$/);
          if (edition) { const selected = edition[1] === "task" ? tasks.find(item => item.id === edition[2]) : materials.find(item => item.material_id === edition[2]); assert(selected); return json({ text: `# ${selected.title}\n\nSynthetic reader text with local source evidence.`, revision: "fixture", edited: false }); }
          const materialRead = pathname.match(/^\/api\/library\/materials\/([^/]+)(?:\/(content|anchors))?$/);
          if (materialRead) {
            const selected = materials.find(item => item.material_id === materialRead[1]); assert(selected);
            const anchors = evidence.filter(item => item.metadata.material_id === selected.material_id);
            return json(materialRead[2] === "content" ? { material_id: selected.material_id, text: anchors.map(item => item.text).join("\n") } : materialRead[2] === "anchors" ? { anchors } : { material: selected });
          }
          const source = pathname.match(/^\/api\/knowledge\/evidence\/([^/]+)$/);
          if (source) { const selected = evidence.find(item => item.evidence_id === decodeURIComponent(source[1])); assert(selected); return json({ evidence: selected }); }
          if (pathname === "/api/tasks/video-a") return json({ task: tasks[0] });
          if (pathname === "/api/tasks/video-a/events") return json({ events: [] });
          if (pathname === "/api/tasks/video-a/transcript") return json({ segments: [{ start: 0, end: 5, text: "Earlier original introduction." }, { start: 12, end: 18, text: evidence[0].text }] });
        }
        if (pathname === "/api/study/activity" && request.method() === "POST") return json({ ok: true });
        const questionRoute = pathname.match(/^\/api\/courses\/([^/]+)\/ask$/);
        if (questionRoute && request.method() === "POST") {
          const payload = request.postDataJSON(), selected = courses.find(item => item.id === questionRoute[1]);
          assert.deepEqual(Object.keys(payload).sort(), ["limit", "mode", "question", "revision"]);
          assert.equal(payload.limit, 6); assert.equal(payload.mode, "lexical"); assert.equal(typeof payload.question, "string"); assert(Number.isInteger(payload.revision) && payload.revision >= 1);
          asks.push({ course_id: questionRoute[1], ...payload });
          if (!selected) return json({ detail: "课程不存在或已删除" }, 404);
          if (payload.revision !== selected.revision) return json({ detail: "课程来源已变化，请重新选择课程" }, 409);
          const value = answer(selected), pending = holds.get(payload.question);
          if (pending) { pending.started.resolve(); await pending.release.promise; holds.delete(payload.question); }
          return json(value);
        }
        report.unexpectedRequests.push(`${request.method()} ${pathname}`);
        return json({ detail: `Unexpected fixture request: ${pathname}` }, 501);
      } catch (error) {
        if (/Target page, context or browser has been closed/.test(error.message)) return;
        report.errors.push(`Fixture route: ${error.message}`); await route.abort("failed").catch(() => {});
      }
    });
    page = await context.newPage(); page.setDefaultTimeout(15000);
    page.on("pageerror", error => report.errors.push(error.message));
    page.on("dialog", dialog => dialog.dismiss());
    await page.goto(base.href);
    await page.locator('#welcome[data-ready="true"]').waitFor();
    await page.locator('#notes [data-id="document-a"]').click();
    await open();
    assert.match(await page.locator("#toolBody").innerText(), /本地原文摘录，不使用 AI 综合生成答案/);
    await ask("concept"); await result("ALPHA");
    assert.doesNotMatch(await page.locator("#courseQuestionResult").innerText(), /BETA/);
    assert.equal(await page.locator("[data-course-evidence]").count(), 2);
    assert.equal(await page.locator('[data-course-evidence="video-a-quote"]').getAttribute("data-start"), "12");
    await screenshot("01-course-excerpts.png");
    await page.locator('[data-course-evidence="document-a-quote"]').click();
    await page.locator('#sourceContent .source-evidence-target[data-evidence-id="document-a-quote"]').waitFor();
    assert.match(await page.locator("#sourceContent").innerText(), /ALPHA original document/);
    await screenshot("02-document-source.png");
    await page.locator("#closeSource").click();
    await open(); await ask("video concept"); await result("ALPHA");
    await page.locator('[data-course-evidence="video-a-quote"]').click();
    await page.locator('#sourceContent .cue.active[data-time="12"]').waitFor();
    assert.match(await page.locator("#sourceContent .cue.active").innerText(), /ALPHA original transcript/);
    assert.equal(await page.locator("#player").isVisible(), false);
    await screenshot("03-video-timestamp.png"); await page.locator("#closeSource").click();
    report.checks.push("selectable course entry, local excerpt labeling, document evidence and video timestamp navigation");

    await open(); await choose("course-b"); await ask("concept"); await result("BETA");
    assert.doesNotMatch(await page.locator("#courseQuestionResult").innerText(), /ALPHA/);
    await choose("course-empty"); await ask("empty concept"); await result("没有可用原文证据");
    assert.equal(await page.locator("[data-course-evidence]").count(), 0);
    await screenshot("04-empty-course.png");
    report.checks.push("switching courses clears old answers and empty courses have no global fallback");

    await choose("course-a"); courses[0].revision++;
    await ask("stale membership"); await page.waitForFunction(() => document.querySelector("#toolStatus").textContent.includes("课程来源已变化"));
    assert.equal(await page.locator("#courseQuestionSubmit").isDisabled(), true);
    await page.locator("#courseQuestionReload").click(); await page.waitForFunction(() => !document.querySelector("#courseQuestionSubmit").disabled);
    await ask("refreshed membership"); await result("ALPHA"); assert.equal(asks.at(-1).revision, courses[0].revision);
    await choose("course-b"); const removed = courses.splice(1, 1)[0];
    await ask("deleted course"); await page.waitForFunction(() => document.querySelector("#toolStatus").textContent.includes("课程不存在或已删除"));
    assert.equal(await page.locator("#courseQuestionSubmit").isDisabled(), true);
    assert.equal(await page.locator("#courseQuestionResult").innerText(), ""); courses.splice(1, 0, removed);
    await screenshot("05-scope-unavailable.png");
    report.checks.push("409 stale revision and 404 deleted course remain scoped and require refreshing membership");

    await choose("course-a");
    const repeated = hold("repeated submit"), before = asks.length;
    await ask("repeated submit"); await bounded(repeated.started.promise);
    await page.locator("#courseQuestionForm").evaluate(form => { form.requestSubmit(); form.requestSubmit(); });
    await settle(); assert.equal(asks.length, before + 1);
    await choose("course-b"); await ask("new course while old pending"); await result("BETA");
    await release(repeated, "repeated submit");
    assert.doesNotMatch(await page.locator("#courseQuestionResult").innerText(), /ALPHA/);
    report.checks.push("repeated submission is ignored and a delayed old-course answer cannot replace the selected course");

    for (const action of ["close", "escape", "back", "navigate", "home"]) {
      await choose("course-a");
      const question = `late ${action}`, pending = hold(question);
      await ask(question); await bounded(pending.started.promise);
      if (action === "close") await close();
      else if (action === "escape") await page.keyboard.press("Escape");
      else if (action === "back") await page.locator("#toolsDialog [data-tool-back]").click();
      else await page.evaluate(hash => { location.hash = hash; }, action === "home" ? "" : "#material/document-b");
      if (action === "back") await page.locator("[data-course]").first().waitFor();
      else await page.waitForFunction(() => !document.querySelector("#toolsDialog").open);
      const status = await page.locator("#toolStatus").textContent();
      await release(pending, question);
      assert.equal(await page.locator("#toolStatus").textContent(), status);
      assert.equal(await page.locator("#courseQuestionResult").count() ? await page.locator("#courseQuestionResult").innerText() : "", "");
      if (action === "back") await close();
      if (action === "home") { await page.locator("#welcome").waitFor(); await page.locator('#notes [data-id="document-a"]').click(); }
      await open();
    }
    report.checks.push("late responses after Close, Escape, Back, newer source navigation and Home cannot repaint or reopen a dialog");
    await page.setViewportSize({ width: 390, height: 844 });
    await ask("mobile concept"); await result("ALPHA");
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await screenshot("06-course-mobile.png");
    assert(asks.every(item => item.mode === "lexical"));
    assert(!report.requests.some(item => /\/api\/(assistant\/(route|chat)|knowledge\/(ask|search))/.test(item)));
    assert.deepEqual(report.unexpectedRequests, []); assert.deepEqual(report.errors, []);
    report.passed = true;
  } catch (error) {
    report.failure = error.stack || String(error);
    if (page && !page.isClosed()) await screenshot("failure.png").catch(() => {});
    throw error;
  } finally {
    for (const pending of holds.values()) pending.release.resolve();
    report.asks = asks;
    fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(report, null, 2));
    await browser?.close();
    console.log(JSON.stringify({ passed: report.passed, out, checks: report.checks }));
  }
}

if (process.argv.includes("--self-test")) {
  assert.deepEqual(answer(makeCourses()[0]).citations.map(item => item.source_id), ["video-a", "document-a"]);
  assert.deepEqual(answer(makeCourses()[1]).citations.map(item => item.source_id), ["document-b"]);
  assert.equal(answer(makeCourses()[2]).grounded, false);
  console.log("Course question synthetic fixture loaded; browser flow requires isolated Windows Edge CI");
} else main().catch(error => { console.error(error); process.exitCode = 1; });
