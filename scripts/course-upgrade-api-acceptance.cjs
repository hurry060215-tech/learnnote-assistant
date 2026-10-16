// Actual browser and real course APIs on isolated disk data. The fixture holds
// every processing admission: no media download or model request is performed.
// LEARNNOTE_ACCEPTANCE_BROWSER selects an installed Chromium path; default is Edge.
const assert = require("node:assert/strict");
const fs = require("node:fs"), os = require("node:os"), path = require("node:path");
const { spawn } = require("node:child_process");
const { createHash } = require("node:crypto");
const { chromium } = require("playwright");
const { completedAction, retryCourseReady, openChildReady, cleanupFixture } = require("./course-upgrade-fixture-helpers.cjs");
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, label, timeout = 20000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { if (await check()) return; await delay(50); }
  throw new Error(`Timed out: ${label}`);
}
(async () => {
  const out = path.resolve(process.argv[2] || "build/course-upgrade-ui"); fs.mkdirSync(out, { recursive: true });
  const data = fs.mkdtempSync(path.join(os.tmpdir(), "learnnote-course-upgrade-"));
  const report = { ok: false, synthetic_only: true, actual_http: true, actual_disk: true,
    browser: process.env.LEARNNOTE_ACCEPTANCE_BROWSER || "Microsoft Edge", checks: [], screenshots: [], errors: [], external_requests: [] };
  let backend, browser, fixture, failure, primaryError, buffer = "";
  try {
    const env = {};
    for (const [key, value] of Object.entries(process.env))
      if (/^(PATH|SYSTEMROOT|WINDIR|COMSPEC|PATHEXT|TEMP|TMP|LANG|LC_ALL)$/i.test(key)) env[key] = value;
    Object.assign(env, { PYTHONUTF8: "1", PYTHONUNBUFFERED: "1", PYTHONDONTWRITEBYTECODE: "1" });
    backend = spawn(process.env.LEARNNOTE_ACCEPTANCE_PYTHON || "python", [path.join(__dirname, "course-upgrade-fixture.py"), "--data-dir", data],
      { cwd: path.resolve(__dirname, ".."), env, stdio: ["ignore", "pipe", "pipe"] });
    backend.on("error", error => { failure = error; });
    backend.on("exit", code => { failure = new Error(`Fixture exited ${code}`); });
    for (const stream of [backend.stdout, backend.stderr]) stream.on("data", chunk => {
      fs.appendFileSync(path.join(out, "backend.log"), chunk); buffer += chunk.toString();
      const lines = buffer.split(/\r?\n/); buffer = lines.pop();
      for (const line of lines) if (line.startsWith('{"fixture_origin":')) fixture = JSON.parse(line);
    });
    await until(async () => { if (failure) throw failure; if (!fixture) return false;
      try { return (await fetch(fixture.fixture_origin + "/health")).ok; } catch { return false; }
    }, "isolated fixture health", 60000);
    assert.equal(fixture.offline_network, true);
    const base = fixture.fixture_origin;
    browser = await chromium.launch(process.env.LEARNNOTE_ACCEPTANCE_BROWSER
      ? { executablePath: process.env.LEARNNOTE_ACCEPTANCE_BROWSER, headless: true, args: ["--no-sandbox"] }
      : { channel: "msedge", headless: true });
    report.browser_version = browser.version();
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce", serviceWorkers: "block" });
    await context.addInitScript(() => localStorage.setItem("learnnote.sidebar.collapsed", "true"));
    await context.route("**/*", route => {
      if (new URL(route.request().url()).origin !== base) { report.external_requests.push(route.request().url()); return route.abort(); }
      return route.continue();
    });
    const page = await context.newPage(); page.on("pageerror", error => report.errors.push(error.message));
    const readState = async () => (await page.request.get(base + "/_fixture/state")).json();
    const api = async (route, options) => {
      const response = await page.request.fetch(base + route, options);
      assert(response.ok(), `${route}: ${response.status()} ${await response.text()}`); return response.json();
    };
    const prefix = `/api/courses/${fixture.course_id}/episodes/${fixture.episode_id}`;
    function hashes(id) {
      return Object.fromEntries(["transcript.json", "note.md"].map(name => [name, createHash("sha256").update(fs.readFileSync(path.join(data, "tasks", id, name))).digest("hex")]));
    }
    const originals = hashes(fixture.task_id), retryOriginals = hashes(fixture.retry_task_id);
    const sourceBefore = fs.readFileSync(path.join(data, "tasks", fixture.task_id, "task.json"), "utf8");
    const courseBefore = (await api(`/api/courses/${fixture.course_id}`)).course;
    const seen = { previews: [], confirmations: [], deletes: 0, retry: [] };
    page.on("request", request => {
      if (request.url().endsWith("/upgrade-preview") && request.method() === "POST") seen.previews.push(request.postDataJSON());
      if (request.url().endsWith("/upgrade") && request.method() === "POST") seen.confirmations.push(request.postDataJSON());
      if (request.url().includes("/upgrade-preview/") && request.method() === "DELETE") seen.deletes++;
      if (request.url().endsWith("/retry") && request.method() === "POST") seen.retry.push(request.postDataJSON());
    });
    page.on("dialog", dialog => dialog.accept());
    async function open() {
      if (await page.locator("#toolsDialog").evaluate(el => el.open)) await page.locator("[data-close-tool]").click();
      if (!(await page.locator("#readerOptions").evaluate(el => el.open))) await page.locator("#readerOptions > summary").click();
      await page.locator("#moreTools").click(); await page.locator('[data-action="courses"]').click();
      await page.locator(`[data-course="${fixture.course_id}"]`).click();
      await page.locator(`[data-open-source="0"]`).waitFor();
    }
    async function preview() {
      const result = await completedAction(page, "POST", base + prefix + "/upgrade-preview", () => page.locator(`[data-upgrade-episode="${fixture.episode_id}"]`).click());
      const review = await result.json(); await page.locator("#courseUpgradeConfirm").waitFor();
      for (const [label, value] of [["下载来源网址：", review.page_url], ["发送给模型的来源标题：", review.model_source.title], ["发送给模型的来源网址：", review.model_source.url]])
        assert.equal(await page.locator(".course-upgrade p").filter({ hasText: label }).locator(".answer").innerText(), value || "（空）");
      return review;
    }
    async function consent() { await page.locator("#courseUpgradeDownload").check(); await page.locator("#courseUpgradeShare").check(); }
    async function capture(name, footer = false) {
      for (const theme of ["light", "dark"]) for (const width of [1280, 1440, 768, 390]) {
        await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
        await page.evaluate(theme => document.body.classList.toggle("dark", theme === "dark"), theme);
        if (footer) await page.locator("#courseUpgradeConfirm").scrollIntoViewIfNeeded();
        else await page.locator("#toolsDialog").evaluate(node => node.scrollTop = 0);
        const geometry = await page.locator("#toolsDialog").evaluate(node => {
          const box = node.getBoundingClientRect(); return { left: box.left, right: box.right, width: innerWidth,
            overflow: node.scrollWidth > node.clientWidth + 1,
            controls: [...node.querySelectorAll(".course-upgrade button, .course-upgrade .tool-choice")].map(item => item.getBoundingClientRect().height),
            textAlign: getComputedStyle(node.querySelector(".course-upgrade p")).textAlign };
        });
        assert(!geometry.overflow && geometry.left >= 0 && geometry.right <= geometry.width + 1, JSON.stringify(geometry));
        assert(geometry.controls.every(height => height >= 44)); assert(["left", "start"].includes(geometry.textAlign));
        const filename = `${name}-${theme}-${width}.png`; await page.screenshot({ path: path.join(out, filename), animations: "disabled" }); report.screenshots.push(filename);
      }
      await page.setViewportSize({ width: 1440, height: 1000 }); await page.evaluate(() => document.body.classList.remove("dark"));
    }
    await page.goto(`${base}/#task/${fixture.task_id}`); await page.locator("#document h1").waitFor();
    await open(); const cancelledReview = await preview(); assert.equal((await readState()).admissions.length, 0);
    assert(!(await page.locator("#courseUpgradeDownload").isChecked())); assert(!(await page.locator("#courseUpgradeShare").isChecked()));
    assert(await page.locator("#courseUpgradeConfirm").isDisabled());
    const disclosure = await page.locator("#toolBody").innerText();
    assert.match(disclosure, /www.bilibili.com.*p=1/); assert.match(disclosure, /媒体\/处理预算/); assert.match(disclosure, /下载流量可能超过/);
    assert.match(disclosure, /字幕文本、上方模型来源标题与网址/); assert.match(disclosure, /synthetic-vision/); assert.match(disclosure, /发送给模型的来源标题/); assert.match(disclosure, /发送给模型的来源网址/);
    await capture("review"); await page.locator("#courseUpgradeDownload").check(); assert(await page.locator("#courseUpgradeConfirm").isDisabled()); await capture("consent", true);
    const cancelled = await completedAction(page, "DELETE", `${base}${prefix}/upgrade-preview/${cancelledReview.preview_id}`, () => page.locator("#courseUpgradeCancel").click());
    assert.equal((await cancelled.json()).cancelled, true);
    await page.locator("#courseUpgradeConfirm").waitFor({ state: "detached" });
    await page.locator(`[data-upgrade-episode="${fixture.episode_id}"]`).waitFor(); assert.equal((await readState()).admissions.length, 0);
    for (const close of ["escape", "back", "close"]) {
      const dismissed = await preview(); await consent();
      const response = await completedAction(page, "DELETE", `${base}${prefix}/upgrade-preview/${dismissed.preview_id}`, async () => {
        if (close === "escape") await page.keyboard.press("Escape");
        if (close === "back") await page.locator("[data-tool-back]").click();
        if (close === "close") await page.locator("[data-close-tool]").click();
      });
      assert.equal((await response.json()).cancelled, true);
      await open(); await page.locator("#courseUpgradeConfirm").waitFor({ state: "detached" }); assert.equal((await readState()).admissions.length, 0);
    }
    await preview(); await consent(); await api("/_fixture/selection/changed", { method: "POST" });
    await page.locator("#courseUpgradeConfirm").click(); await page.locator("#toolStatus").getByText(/设置已变化/).waitFor();
    assert.equal(seen.confirmations.length, 0); await api("/_fixture/selection/normal", { method: "POST" });
    report.checks.push("Real preview exposes source, saved model, media budget caveat and full model payload; cancel/Escape/back/close invalidate consent; changed model blocks submit");
    await open(); await preview(); await consent();
    const current = (await api(`/api/courses/${fixture.course_id}`)).course;
    await api(`/api/courses/${fixture.course_id}`, { method: "PUT", data: { paused: true, title: current.title, sources: current.sources, revision: current.revision } });
    await page.locator("#courseUpgradeConfirm").click(); await page.locator("#toolStatus").getByText(/不会自动重试/).waitFor();
    assert.equal((await readState()).admissions.length, 0);
    const paused = (await api(`/api/courses/${fixture.course_id}`)).course;
    await api(`/api/courses/${fixture.course_id}`, { method: "PUT", data: { title: paused.title, sources: paused.sources, paused: false, revision: paused.revision } });
    await open(); await preview(); assert(!(await page.locator("#courseUpgradeShare").isChecked())); await consent();
    const submittedBefore = seen.confirmations.length;
    await page.locator("#courseUpgradeConfirm").evaluate(button => { button.click(); button.click(); });
    await page.locator("#courseUpgradeOpen").waitFor(); assert.equal(seen.confirmations.length, submittedBefore + 1);
    let snapshot = await readState(); assert.equal(snapshot.admissions.length, 1);
    const admission = snapshot.admissions[0], child = await api(`/api/tasks/${admission.task_id}`);
    assert.equal(admission.processor, "process_current_page_task"); assert.equal(admission.captions, 1); assert.equal(admission.cookies, 0); assert.equal(admission.resources, 0); assert.equal(admission.page_text, "");
    assert.equal(child.task.source_task_id, fixture.task_id); assert.equal(child.task.status, "queued"); assert.notEqual(child.task.id, fixture.task_id);
    const childDir = path.join(data, "tasks", child.task.id), reviewed = JSON.parse(fs.readFileSync(path.join(childDir, "course-upgrade-review.json"), "utf8"));
    assert.equal(reviewed.caption_sha256, createHash("sha256").update(fs.readFileSync(path.join(childDir, "course-upgrade-captions.json"))).digest("hex"));
    assert.equal(reviewed.source_task_id, fixture.task_id); assert.equal(reviewed.episode_id, fixture.episode_id);
    assert.equal(reviewed.download_confirmed, true); assert.equal(reviewed.image_sharing_confirmed, true);
    assert.equal(child.task.title, JSON.parse(sourceBefore).title);
    assert.deepEqual(hashes(fixture.task_id), originals); assert.equal(fs.readFileSync(path.join(data, "tasks", fixture.task_id, "task.json"), "utf8"), sourceBefore);
    const after = (await api(`/api/courses/${fixture.course_id}`)).course; assert.deepEqual(after.sources, courseBefore.sources);
    assert.equal((await api(`/api/courses/${fixture.course_id}`)).episodes[0].caption_upgrade_available, false);
    const replay = await api(`${prefix}/upgrade`, { method: "POST", data: seen.confirmations.at(-1) });
    assert.equal(replay.task_id, child.task.id); assert.equal(replay.deduplicated, true); assert.equal((await readState()).admissions.length, 1);
    await page.locator("#courseUpgradeReturn").click(); await page.locator(`[data-open-upgrade="${child.task.id}"]`).waitFor();
    await openChildReady(page, { base, id: child.task.id, title: child.task.title });
    report.checks.push("Paused/stale review rejected; repeated click and same-token replay admit one linked child with reviewed caption hash; source title/caption/note/task manifest and course membership stay unchanged");
    await page.goto(`${base}/#task/${fixture.task_id}`); await page.locator("#document h1").waitFor(); await open();
    await retryCourseReady(page, { url: `${base}/api/courses/${fixture.course_id}/episodes/${fixture.retry_episode_id}/retry`,
      retrySelector: `[data-retry-episode="${fixture.retry_episode_id}"]`, readySelector: '[data-open-source="0"]', title: courseBefore.title });
    await until(async () => (await readState()).admissions.length === 2, "caption summary retry admitted");
    assert.equal(seen.retry.length, 1); assert.equal(seen.retry[0].task_id, fixture.retry_task_id); assert.equal(seen.retry[0].options.content_mode, "text"); assert.equal(seen.retry[0].options.visual_understanding, false);
    snapshot = await readState(); assert.equal(snapshot.admissions[1].processor, "process_saved_transcript_task"); assert.equal(snapshot.admissions[1].queue_kind, "summary");
    assert.deepEqual(hashes(fixture.retry_task_id), retryOriginals); assert.equal(snapshot.processing_executed, false);
    report.checks.push("Actual caption summary retry dispatches saved transcript processing while preserving source artifacts; all processing boundaries stay deferred");
    assert.deepEqual(report.errors, []); assert.deepEqual(report.external_requests, []); report.ok = true;
  } catch (error) { primaryError = error; throw error; }
  finally { await cleanupFixture({ report: () => fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(report, null, 2)),
    browser: () => browser?.close(), backend: () => backend?.kill() }, primaryError); }
})().catch(error => { console.error(error); process.exitCode = 1; });
