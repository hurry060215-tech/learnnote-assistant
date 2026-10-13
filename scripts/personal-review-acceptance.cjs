// Actual Microsoft Edge, HTTP and disk. The fixture is a fresh local workspace;
// all notes are synthetic and the backend's existing offline guard blocks models.
// node scripts/personal-review-acceptance.cjs [output-directory]
const assert = require("node:assert/strict");
const fs = require("node:fs"), os = require("node:os"), path = require("node:path");
const { createHash } = require("node:crypto");
const { spawn } = require("node:child_process");
const { chromium } = require("playwright");
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
async function until(check, label, timeout = 15000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { if (await check()) return; await delay(50); }
  throw new Error(`Timed out: ${label}`);
}

(async () => {
  const out = path.resolve(process.argv[2] || "build/personal-review-ui");
  fs.mkdirSync(out, { recursive: true });
  const data = fs.mkdtempSync(path.join(os.tmpdir(), "learnnote-personal-review-"));
  const report = { ok: false, browser: "Microsoft Edge", actual_http: true, actual_disk: true,
    synthetic_only: true, checks: [], screenshots: [], errors: [], blocked_requests: [], action_requests: [] };
  let browser, backend, fixture, backendFailure, buffer = "";
  const releaseOnExit = [];
  try {
    const env = {};
    for (const [key, value] of Object.entries(process.env))
      if (/^(PATH|SYSTEMROOT|WINDIR|COMSPEC|PATHEXT|TEMP|TMP|LANG|LC_ALL)$/i.test(key)) env[key] = value;
    Object.assign(env, { PYTHONUTF8: "1", PYTHONUNBUFFERED: "1", PYTHONDONTWRITEBYTECODE: "1" });
    // Reuse the established empty-workspace bootstrap and offline network guard.
    // No model server exists and this test never requests an assistant/model action.
    backend = spawn(process.env.LEARNNOTE_ACCEPTANCE_PYTHON || "python", [
      path.join(__dirname, "assistant-runs-fixture.py"), "--data-dir", data,
      "--model-base", "http://127.0.0.1:1/v1",
    ], { cwd: path.resolve(__dirname, ".."), env, stdio: ["ignore", "pipe", "pipe"] });
    backend.on("error", error => { backendFailure = error; });
    backend.on("exit", code => { backendFailure = new Error(`Fixture exited ${code}`); });
    for (const stream of [backend.stdout, backend.stderr]) stream.on("data", chunk => {
      fs.appendFileSync(path.join(out, "backend.log"), chunk); buffer += chunk.toString();
      const lines = buffer.split(/\r?\n/); buffer = lines.pop();
      for (const line of lines) if (line.startsWith('{"fixture_origin":')) fixture = JSON.parse(line);
    });
    await until(async () => {
      if (backendFailure) throw backendFailure;
      if (!fixture) return false;
      try { return (await fetch(fixture.fixture_origin + "/health")).ok; } catch { return false; }
    }, "isolated fixture health", 60000);
    assert.equal(fixture.offline_network, true);
    const base = fixture.fixture_origin;
    assert.equal(new URL(base).hostname, "127.0.0.1");
    browser = await chromium.launch({ channel: "msedge", headless: true });
    report.browser_version = browser.version();
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce", serviceWorkers: "block" });
    await context.addInitScript(() => localStorage.setItem("learnnote.sidebar.collapsed", "true"));
    await context.route("**/*", route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin !== base) { report.blocked_requests.push(url.origin); return route.abort(); }
      if (request.method() === "POST" && url.pathname.endsWith("/personal-review")) {
        const value = request.postDataJSON();
        assert.match(value.request_id, /^[a-f0-9-]{36}$/);
        report.action_requests.push({ action: value.action, path: url.pathname });
      }
      return route.continue();
    });
    const page = await context.newPage();
    page.on("pageerror", error => report.errors.push(error.message));
    const original = Buffer.from("# 个人核对验收\n\n这份完整笔记仅用于本地验收。\n\n## 核对边界\n\n数字与结论仍需结合来源判断。点击个人核对只保存操作记录。\n", "utf8");
    const imported = await page.request.post(base + "/api/library/materials/import", { multipart: {
      file: { name: "personal-review-synthetic.md", mimeType: "text/markdown", buffer: original }, encoding: "utf-8",
    } });
    assert.equal(imported.status(), 200, await imported.text());
    const id = (await imported.json()).material.material_id;
    assert.match(id, /^[a-f0-9]{32}$/);
    const endpoint = `${base}/api/tasks/editions/material/${id}`, reviewEndpoint = endpoint + "/personal-review";
    const key = createHash("sha256").update(`material:${id}`).digest("hex");
    const recordPath = path.join(data, "personal-reviews", key + ".json");
    const originalPath = path.join(data, "materials", id, "personal-review-synthetic.md");
    const read = async url => { const response = await page.request.get(url); assert.equal(response.status(), 200, await response.text()); return response.json(); };
    const diskRecord = () => JSON.parse(fs.readFileSync(recordPath, "utf8"));
    const ready = status => page.waitForFunction(expected => {
      const panel = document.querySelector("#personalReview");
      return panel && !panel.hidden && panel.dataset.status === expected && panel.getAttribute("aria-busy") === "false";
    }, status);
    const clickAction = async (selector, expectedStatus = 200) => {
      const response = page.waitForResponse(r => r.url() === reviewEndpoint && r.request().method() === "POST");
      await page.locator(selector).click();
      const result = await response; assert.equal(result.status(), expectedStatus, await result.text()); return result.json();
    };
    async function screenshots(state) {
      for (const theme of ["light", "dark"]) for (const width of [1440, 390]) {
        await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
        await page.evaluate(value => { document.body.classList.toggle("dark", value === "dark"); }, theme);
        await page.locator("#personalReview").scrollIntoViewIfNeeded();
        const geometry = await page.locator("#personalReview").evaluate(panel => {
          const box = panel.getBoundingClientRect(), reader = document.querySelector("#document").getBoundingClientRect();
          return { left: box.left, right: box.right, width: innerWidth,
            leftInset: Math.abs(box.left - reader.left), rightInset: Math.abs(box.right - reader.right),
            overflow: document.documentElement.scrollWidth > innerWidth + 1 };
        });
        assert(!geometry.overflow && geometry.left >= 0 && geometry.right <= geometry.width + 1, JSON.stringify(geometry));
        assert(geometry.leftInset <= 1 && geometry.rightInset <= 1, "Panel should share the reading column");
        const name = `${state}-${theme}-${width}.png`;
        await page.screenshot({ path: path.join(out, name), animations: "disabled" }); report.screenshots.push(name);
      }
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.evaluate(() => document.body.classList.remove("dark"));
    }

    await page.goto(`${base}/#material/${id}`); await ready("unmarked");
    assert.equal(fs.existsSync(recordPath), false);
    assert.equal(report.action_requests.length, 0);
    assert.match(await page.locator("#personalReview").innerText(), /当前整篇笔记 · 本机个人核对/);
    const readerBefore = await page.locator("#document").innerText();
    const first = await clickAction("#markPersonalReview"); await ready("current");
    assert.equal(first.status, "current"); assert.equal(diskRecord().state, "marked");
    assert.equal(await page.locator("#personalReviewState").innerText(), "本人已核对");
    assert.equal(await page.locator("#document").innerText(), readerBefore);
    assert.deepEqual(fs.readFileSync(originalPath), original);
    assert.equal(await page.locator("#markPersonalReview").isDisabled(), true);
    report.checks.push("explicit mark writes disk without rewriting note/source or hiding warnings");
    await screenshots("current");

    await page.locator("#edit").click(); assert.equal(await page.locator("#personalReview").isVisible(), false);
    const firstEdition = await read(endpoint);
    await page.locator("#noteText").fill(firstEdition.text + "\n\n新保存的个人修改。\n");
    const saved = page.waitForResponse(r => r.url() === endpoint && r.request().method() === "PUT");
    await page.locator("#save").click(); assert.equal((await saved).status(), 200); await ready("stale");
    assert.equal((await read(reviewEndpoint)).status, "stale"); assert.equal(diskRecord().state, "marked");
    await screenshots("stale");
    const beforeCancel = fs.readFileSync(recordPath);
    await page.locator("#edit").click(); await page.locator("#noteText").fill("Unsaved synthetic draft.");
    page.once("dialog", dialog => dialog.accept()); await page.locator("#discard").click(); await ready("stale");
    assert.deepEqual(fs.readFileSync(recordPath), beforeCancel);
    assert.doesNotMatch(await page.locator("#document").innerText(), /Unsaved synthetic draft/);
    report.checks.push("saving an edition invalidates; editing/preview/cancel cannot mark unsaved text");

    await clickAction("#markPersonalReview"); await ready("current");
    const backup = await read(base + "/api/study/backup");
    assert.equal(backup.personal.personal_reviews.find(item => item.key === key).value.state, "marked");
    await clickAction("#revokePersonalReview"); await ready("revoked"); assert.equal(diskRecord().state, "revoked");
    // Simulate a fresh local review store using only this test-owned record.
    fs.unlinkSync(recordPath);
    const restored = await page.request.post(base + "/api/study/backup/restore", { data: backup });
    assert.equal(restored.status(), 200, await restored.text());
    assert.equal((await restored.json()).merge.restored_personal_reviews, 1);
    await page.locator("#refreshPersonalReview").click(); await ready("imported");
    assert.equal(diskRecord().state, "imported");
    await screenshots("imported");
    report.checks.push("revoke persists; restored mark stays imported until another explicit click");

    // Hold the real POST before it reaches the server, then make a real external
    // edition save. The server must reject the old context without auto-retry.
    const entered = deferred(), release = deferred(); releaseOnExit.push(release.resolve);
    let hold = true;
    await page.route(reviewEndpoint, async route => {
      if (hold && route.request().method() === "POST") {
        hold = false; entered.resolve(); await release.promise;
      }
      await route.fallback();
    });
    const conflict = clickAction("#markPersonalReview", 409);
    await Promise.race([entered.promise, conflict]);
    const edition = await read(endpoint);
    const external = await page.request.put(endpoint, { data: { text: edition.text + "\n另一页面保存的版本。\n", revision: edition.revision } });
    assert.equal(external.status(), 200); release.resolve(); await conflict;
    await page.waitForFunction(() => document.querySelector("#personalReviewFeedback").textContent.includes("本次操作未应用")
      && document.querySelector("#personalReview").getAttribute("aria-busy") === "false");
    assert.equal(await page.locator("#markPersonalReview").isDisabled(), true);
    assert.equal(diskRecord().state, "imported");
    await page.locator("#refreshPersonalReview").click(); await ready("imported");
    assert.match(await page.locator("#document").innerText(), /另一页面保存的版本/);
    const posts = report.action_requests.length;
    await clickAction("#markPersonalReview"); await ready("current");
    assert.equal(report.action_requests.length, posts + 1);
    report.checks.push("real context conflict refetches, preserves explicit feedback, requires fresh click");

    // An unavailable source context still exposes the old record and revoke.
    // The browser keeps the last rendered note, while this test's edition file
    // is temporarily made unreadable as an edition, then restored byte-for-byte.
    const editionPath = path.join(data, "user-editions", key + ".json");
    const editionBytes = fs.readFileSync(editionPath);
    fs.writeFileSync(editionPath, "invalid synthetic edition");
    try {
      await page.locator("#refreshPersonalReview").click(); await ready("stale");
      assert.equal(await page.locator("#markPersonalReview").isDisabled(), true);
      assert.equal(await page.locator("#revokePersonalReview").isEnabled(), true);
      await clickAction("#revokePersonalReview"); await ready("revoked");
      assert.equal(diskRecord().state, "revoked");
    } finally { fs.writeFileSync(editionPath, editionBytes); }
    await page.reload(); await ready("revoked");
    assert.deepEqual(fs.readFileSync(originalPath), original);
    report.checks.push("unavailable edition keeps revoke; refresh reflects persisted revoked state");
    await page.locator("#source").click(); await page.locator("#closeSource").click();
    assert.equal(await page.locator("#personalReviewState").innerText(), "已撤销个人核对");
    await page.evaluate(() => { location.hash = ""; });
    await page.locator("#welcome").waitFor(); assert.equal(await page.locator("#personalReview").isVisible(), false);
    await page.evaluate(value => { location.hash = `material/${value}`; }, id); await ready("revoked");
    report.checks.push("source Close, home navigation and reopening never mark automatically");
    assert.deepEqual(report.errors, []); assert.deepEqual(report.blocked_requests, []);
    report.ok = true;
  } catch (error) { report.errors.push(error.stack || error.message); process.exitCode = 1; }
  finally {
    for (const release of releaseOnExit) release();
    if (browser) await browser.close();
    if (backend && backend.exitCode === null) {
      backend.kill(); await Promise.race([new Promise(resolve => backend.once("exit", resolve)), delay(5000)]);
      if (backend.exitCode === null && backend.signalCode === null) { backend.kill("SIGKILL"); await new Promise(resolve => backend.once("exit", resolve)); }
    }
    fs.rmSync(data, { recursive: true, force: true }); report.temporary_data_removed = !fs.existsSync(data);
    fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(report, null, 2));
  }
})();
