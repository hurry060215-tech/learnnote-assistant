// Actual Windows Edge + real isolated backend and synthetic H.264/AAC media.
// No extension, real site/account, external model or native permission prompt.
const assert = require("node:assert/strict");
const fs = require("node:fs"), os = require("node:os"), path = require("node:path");
const { spawn, execFileSync } = require("node:child_process");
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const deferred = () => { let resolve; const promise = new Promise(done => resolve = done); return { promise, resolve }; };
async function until(check, label, timeout = 20000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) { if (await check()) return; await delay(40); }
  throw new Error(`Timed out: ${label}`);
}
async function bounded(promise, label, timeout = 20000) {
  let timer;
  try {
    return await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`Timed out: ${label}`)), timeout);
    })]);
  } finally { clearTimeout(timer); }
}
function assertPlayer(snapshot, id, seconds) {
  assert.equal(snapshot.taskId, id, "Rendered player must belong to the expected task");
  assert.equal(new URL(snapshot.currentSrc).pathname, `/api/tasks/${id}/media`);
  assert.equal(snapshot.hidden, false); assert(snapshot.readyState >= 1);
  assert.equal(snapshot.paused, true, "Navigation and seeks must not autoplay");
  if (seconds !== undefined) assert(Math.abs(snapshot.currentTime - seconds) < .08, JSON.stringify(snapshot));
}
async function main() {
  const { chromium } = require("playwright");
  const out = path.resolve(process.argv[2] || "build/local-player-ui");
  fs.mkdirSync(out, { recursive: true });
  const data = fs.mkdtempSync(path.join(os.tmpdir(), "learnnote-local-player-"));
  const report = { ok: false, source_sha: execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim(),
    browser: "Microsoft Edge", synthetic_only: true, actual_http: true, actual_media: true,
    summary_provider: "deterministic fixture", media_checks: [], checks: [], screenshots: [], writes: [], errors: [], blocked_requests: [],
    not_tested: ["desktop native webview", "real sites/accounts", "extension permissions", "ASR", "external model quality"] };
  const releases = [];
  let backend, browser, page, fixture, failure, buffer = "";
  try {
    const env = {};
    for (const [key, value] of Object.entries(process.env)) if (/^(PATH|SYSTEMROOT|WINDIR|COMSPEC|PATHEXT|TEMP|TMP|LANG|LC_ALL)$/i.test(key)) env[key] = value;
    Object.assign(env, { PYTHONUTF8: "1", PYTHONUNBUFFERED: "1", PYTHONDONTWRITEBYTECODE: "1" });
    backend = spawn(process.env.LEARNNOTE_ACCEPTANCE_PYTHON || "python", [path.join(__dirname, "local-player-fixture.py"), "--data-dir", data],
      { cwd: path.resolve(__dirname, ".."), env, stdio: ["ignore", "pipe", "pipe"] });
    backend.on("error", error => failure = error);
    backend.on("exit", code => failure = new Error(`Fixture exited ${code}`));
    for (const stream of [backend.stdout, backend.stderr]) stream.on("data", chunk => {
      fs.appendFileSync(path.join(out, "backend.log"), chunk); buffer += chunk.toString();
      const lines = buffer.split(/\r?\n/); buffer = lines.pop();
      for (const line of lines) if (line.startsWith('{"fixture_origin":')) fixture = JSON.parse(line);
    });
    await until(async () => {
      if (failure) throw failure;
      if (!fixture) return false;
      try { return (await fetch(fixture.fixture_origin + "/health")).ok; } catch { return false; }
    }, "synthetic backend health", 90000);
    assert.equal(fixture.offline_network, true);
    assert.equal(fixture.media_frame_rate, 30);
    report.media_frame_rate = fixture.media_frame_rate;
    const base = fixture.fixture_origin, a = fixture.source_id, b = fixture.other_id;
    browser = await chromium.launch({ channel: "msedge", headless: true });
    report.browser_version = browser.version();
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce", serviceWorkers: "block" });
    await context.addInitScript(() => localStorage.setItem("learnnote.sidebar.collapsed", "true"));
    await context.route("**/*", route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin !== base) { report.blocked_requests.push(url.origin); return route.abort(); }
      return route.continue();
    });
    page = await context.newPage();
    page.setDefaultTimeout(20000);
    page.on("pageerror", error => report.errors.push(error.message));
    page.on("request", request => {
      const url = new URL(request.url());
      if (request.method() === "POST" && /\/(learn-range|rerun-from-media)$/.test(url.pathname))
        report.writes.push({ path: url.pathname, body: request.postDataJSON() });
    });
    const read = async route => {
      const response = await page.request.get(base + route); assert(response.ok(), await response.text()); return response.json();
    };
    const player = () => page.locator("#player").evaluate(el => ({ taskId: el.dataset.sourceTaskId, currentSrc: el.currentSrc,
      currentTime: el.currentTime, duration: el.duration, readyState: el.readyState, paused: el.paused, hidden: el.hidden }));
    const selected = async id => {
      await page.waitForFunction(id => document.querySelector("#document")?.dataset.readerSource === `task:${id}`, id);
      await until(async () => { const value = await player(); return value.taskId === id && value.readyState >= 1 && !value.hidden; }, "rendered local source");
      assertPlayer(await player(), id);
    };
    const go = async id => { await page.evaluate(id => { location.hash = `task/${id}`; }, id); await selected(id); };
    const seek = async seconds => {
      await page.locator("#player").evaluate((el, seconds) => { el.currentTime = seconds; }, seconds);
      await until(async () => Math.abs((await player()).currentTime - seconds) < .08, "local player seek");
    };
    const openRange = async () => {
      if (!await page.locator("#readerOptions").evaluate(el => el.open)) await page.locator("#readerOptions > summary").click();
      await page.locator("#moreTools").click(); await page.locator('[data-action="range"]').click();
      await page.locator("#rangeForm").waitFor();
    };
    const snapshot = async name => {
      const geometry = await page.evaluate(() => ({ overflow: document.documentElement.scrollWidth > innerWidth + 1,
        dialogs: [...document.querySelectorAll("dialog[open]")].map(el => { const r = el.getBoundingClientRect(); return { left: r.left, right: r.right, width: innerWidth }; }) }));
      assert(!geometry.overflow, JSON.stringify(geometry));
      for (const d of geometry.dialogs) assert(d.left >= 0 && d.right <= d.width + 1);
      const file = `${name}.png`; await page.screenshot({ path: path.join(out, file), animations: "disabled" }); report.screenshots.push(file);
    };
    const duration = async (label, id, expected) => {
      const task = (await read(`/api/tasks/${id}`)).task;
      const actual = { label, expected_seconds: expected, backend_seconds: task.media_integrity?.duration,
        learning_range: task.learning_range, player: await player() };
      report.media_checks.push(actual);
      assert(Math.abs(actual.backend_seconds - expected) < .15, JSON.stringify(actual));
      assert(Math.abs(actual.player.duration - expected) < .15, JSON.stringify(actual));
    };
    const complete = async id => {
      let task;
      await until(async () => { task = (await read(`/api/tasks/${id}`)).task; return ["success", "failed", "cancelled"].includes(task.status); }, "actual range processing", 90000);
      assert.equal(task.status, "success", JSON.stringify(task)); return task;
    };
    const createRange = async (start, end, sourceId) => {
      await page.locator("#rangeStart").fill(String(start)); await page.locator("#rangeEnd").fill(String(end));
      const response = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith(`/api/tasks/${sourceId}/learn-range`));
      await page.locator("#rangeForm button.primary").click();
      const reply = await response; assert.equal(reply.status(), 200, await reply.text());
      const sent = reply.request().postDataJSON();
      assert.equal(sent.start, start); assert.equal(sent.end, end);
      assert.equal(new URL(reply.url()).pathname, `/api/tasks/${sourceId}/learn-range`);
      const value = await reply.json(); await complete(value.task_id);
      await page.goto(`${base}/#task/${value.task_id}`); await selected(value.task_id); return value.task_id;
    };

    await page.goto(`${base}/#task/${a}`); await selected(a);
    if (!await page.locator("#sourceTranscript").evaluate(el => el.open)) await page.locator("#sourceTranscript > summary").click();
    await page.locator('#sourceContent [data-time="5.25"]').click();
    await until(async () => Math.abs((await player()).currentTime - 5.25) < .08, "actual transcript cue seek");
    assertPlayer(await player(), a, 5.25);
    await openRange(); assert.equal(await page.locator("#rangeStart").inputValue(), "5.25");
    const beforeDismiss = report.writes.length;
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#toolsDialog").evaluate(el => el.open), false);
    await openRange(); await page.locator("[data-close-tool]").click();
    assert.equal(report.writes.length, beforeDismiss, "Escape and Close before submission do not create a task");
    await openRange(); assert.equal(await page.locator("#rangeStart").inputValue(), "5.25");
    await seek(6.125); await page.locator('[data-action="range-position"]').click();
    assert.equal(await page.locator("#rangeStart").inputValue(), "6.125");
    for (const width of [1440, 390]) for (const theme of ["light", "dark"]) {
      await page.setViewportSize({ width, height: 900 }); await page.evaluate(theme => document.body.classList.toggle("dark", theme === "dark"), theme);
      await snapshot(`range-${theme}-${width}`);
    }
    await page.setViewportSize({ width: 1440, height: 1000 }); await page.evaluate(() => document.body.classList.remove("dark"));
    await page.locator("#rangeStart").fill("10"); await page.locator("#rangeEnd").fill("5");
    const beforeInvalid = report.writes.length; await page.locator("#rangeForm button.primary").click();
    await page.locator("#toolStatus").getByText(/结束位置必须晚于/).waitFor(); assert.equal(report.writes.length, beforeInvalid);
    report.checks.push("Actual cue seek, decimal current-position default/button and invalid custom bounds");
    const clip = await createRange(5.25, 15.75, a);
    const clipped = (await read(`/api/tasks/${clip}`)).task;
    assert.equal(clipped.source_task_id, a);
    assert.deepEqual(clipped.learning_range, { start: 5.25, end: 15.75, original_start: 5.25, original_end: 15.75 });
    await duration("selected-range", clip, 10.5);
    const cues = (await read(`/api/tasks/${clip}/transcript`)).segments;
    assert.deepEqual(cues.map(c => [c.start, c.end, c.text]), [[0, 5.25, "SYNTHETIC_SECOND"], [5.25, 10.5, "SYNTHETIC_THIRD"]]);
    await openRange(); assert.match(await page.locator("#toolBody").innerText(), /原视频 5.25–15.75 秒/);
    assert.equal(await page.locator("#rangeEnd").getAttribute("max"), "10.5");
    assert.match(await page.locator("#toolBody").innerText(), /编码媒体时长/);
    await page.locator("#rangeStart").fill("0"); await page.locator("#rangeEnd").fill("10.505");
    const beforePadding = report.writes.length;
    await page.locator("#rangeForm button.primary").click();
    assert.equal(await page.locator("#rangeEnd").evaluate(el => el.validity.rangeOverflow), true);
    assert.equal(report.writes.length, beforePadding, "Encoded padding cannot extend the logical parent range");
    await page.locator("#rangeEnd").fill("5.25");
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height:900 }); await snapshot(`nested-range-${width}`);
    }
    await page.setViewportSize({ width:1440, height:1000 });
    report.checks.push("Nested range max is the requested 10.5 seconds; measured encoded padding is disclosed and rejected");
    const nested = await createRange(0, 5.25, clip);
    await openRange();
    page.once("dialog", dialog => { assert.match(dialog.message(), /Synthetic local player A/); dialog.accept(); });
    const wholeReply = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith(`/api/tasks/${a}/rerun-from-media`));
    await page.locator('[data-action="learn-full-source"]').click();
    const wholeResponse = await wholeReply; assert.equal(wholeResponse.status(), 200, await wholeResponse.text());
    const whole = await wholeResponse.json(), wholeTask = await complete(whole.task_id);
    assert.deepEqual(wholeTask.learning_range, {}); assert.equal(wholeTask.source_task_id, a);
    await page.goto(`${base}/#task/${whole.task_id}`); await selected(whole.task_id);
    await duration("whole-source", whole.task_id, 20); await snapshot("whole-source-upgrade");
    report.checks.push("Rendered custom range and nested range use clip-local seconds; full upgrade resolves root A and real 20-second media");

    // Delay real media HTTP, not a fake player property. Metadata remains unavailable.
    for (const action of ["latest", "close", "switch"]) {
      const reached = deferred(), release = deferred(); releases.push(release.resolve);
      const pattern = `**/api/tasks/${a}/media`;
      await page.route(pattern, async route => { reached.resolve(); await release.promise; await route.continue().catch(() => {}); });
      // Start with the 5.25-second nested clip already loaded, then replace it
      // with the 20-second source. New seeks must not use old duration metadata.
      await page.goto(`${base}/#task/${nested}`); await selected(nested);
      await duration(`nested-before-${action}`, nested, 5.25);
      await page.evaluate(id => { location.hash = `task/${id}`; }, a); await bounded(reached.promise, "delayed media request");
      await page.locator('#sourceContent [data-time="5.25"]').waitFor({ state: "attached" });
      if (!await page.locator("#sourceTranscript").evaluate(el => el.open)) await page.locator("#sourceTranscript > summary").click();
      await page.locator('#sourceContent [data-time="5.25"]').click();
      assert.equal((await player()).readyState, 0);
      if (action === "latest") await page.locator('#sourceContent [data-time="10.5"]').click();
      if (action === "close") await page.locator("#closeSource").click();
      if (action === "switch") await go(b);
      release.resolve(); await page.unroute(pattern);
      if (action === "latest") { await selected(a); await until(async () => Math.abs((await player()).currentTime - 10.5) < .08, "newest metadata seek"); assertPlayer(await player(), a, 10.5); }
      if (action === "close") { await until(async () => (await player()).readyState >= 1, "metadata after Close"); assert.equal(await page.locator("#sourcePanel").isVisible(), false); assert.equal((await player()).currentTime, 0); assert.equal((await player()).paused, true); }
      if (action === "switch") { assertPlayer(await player(), b, 0); assert.match(await page.locator("#breadcrumb").innerText(), /player B/); }
      await snapshot(`metadata-${action}`);
    }
    report.checks.push("Real delayed metadata: latest citation wins; Close and source switch cancel pending seeks; no autoplay");

    // Keep A's ready player while B's edition is still loading. The B range
    // dialog must reject A's clock even before B replaces the media element.
    await go(a); await seek(12.5);
    const editionSeen = deferred(), editionRelease = deferred(); releases.push(editionRelease.resolve);
    const editionRoute = `**/api/tasks/editions/task/${b}`;
    await page.route(editionRoute, async route => { editionSeen.resolve(); await editionRelease.promise; await route.continue(); });
    await page.evaluate(id => { location.hash = `task/${id}`; }, b); await bounded(editionSeen.promise, "delayed edition request");
    await openRange(); assert.equal(await page.locator("#rangeStart").inputValue(), "0");
    assert.match(await page.locator("#toolBody").innerText(), /Synthetic local player B/);
    await page.locator('[data-action="range-position"]').click();
    await page.locator("#toolStatus").getByText(/未使用其他来源/).waitFor();
    await snapshot("source-B-rejects-stale-A-position");
    await page.locator("[data-close-tool]").click(); editionRelease.resolve(); await page.unroute(editionRoute); await selected(b);

    // Citation seek begins while transcript HTTP is pending. A subsequent
    // native player control seek must survive the old transcript completion.
    const transcriptSeen = deferred(), transcriptRelease = deferred(); releases.push(transcriptRelease.resolve);
    const transcriptRoute = `**/api/tasks/${a}/transcript`;
    await page.route(transcriptRoute, async route => { transcriptSeen.resolve(); await transcriptRelease.promise; await route.continue(); });
    await page.evaluate(id => { location.hash = `task/${id}`; }, a); await bounded(transcriptSeen.promise, "delayed transcript request");
    await selected(a); await page.locator('#document .time-link').filter({ hasText: "[00:05]" }).first().click();
    await until(async () => Math.abs((await player()).currentTime - 5) < .08, "citation seek while transcript is loading");
    await seek(12.5); transcriptRelease.resolve(); await page.unroute(transcriptRoute);
    await page.waitForFunction(() => document.querySelector("#sourcePanel").dataset.contentMode === "transcript");
    assertPlayer(await player(), a, 12.5); await snapshot("native-seek-survives-transcript-loading");
    report.checks.push("B refuses stale A clock; newer native seek survives delayed source transcript rendering");

    // A pending old request must not replace the newer source or create twice.
    await go(a); await openRange();
    const received = deferred(), releaseReply = deferred(); releases.push(releaseReply.resolve);
    const rangeRoute = `**/api/tasks/${a}/learn-range`;
    let postCount = 0, accepted;
    await page.route(rangeRoute, async route => {
      postCount++; const response = await route.fetch(); accepted = await response.json(); received.resolve();
      await releaseReply.promise; await route.fulfill({ response });
    });
    await page.locator("#rangeStart").fill("5.25"); await page.locator("#rangeEnd").fill("15.75");
    await page.locator("#rangeForm button.primary").click(); await bounded(received.promise, "accepted range request");
    await page.locator("#rangeForm").evaluate(form => form.requestSubmit());
    await page.locator("[data-close-tool]").click(); await go(b);
    const returned = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith(`/api/tasks/${a}/learn-range`));
    releaseReply.resolve(); await returned; await page.unroute(rangeRoute); await complete(accepted.task_id);
    await page.waitForTimeout(250); assert.equal(postCount, 1); assertPlayer(await player(), b, 0);
    assert.equal(await page.locator("#toolsDialog").evaluate(el => el.open), false);
    await snapshot("late-range-response-keeps-B");
    report.checks.push("Repeated submit creates once; late real response after Close/navigation cannot reopen or replace source B");
    assert.deepEqual(await read("/_fixture/originals"), fixture.source_artifacts);
    assert.deepEqual(report.blocked_requests, []); assert.deepEqual(report.errors, []);
    report.source_artifacts_unchanged = true; report.source_ids = { original: a, other: b, clip, nested, whole: whole.task_id };
    report.ok = true;
  } catch (error) {
    report.errors.push(error.stack || error.message); process.exitCode = 1;
    if (page && !page.isClosed()) {
      report.failure_state = await page.evaluate(() => {
        const player = document.querySelector("#player");
        return { hash: location.hash, title: document.querySelector("#breadcrumb")?.textContent,
          sourceKey: document.querySelector("#sourcePanel")?.dataset.sourceKey,
          player: player && { taskId: player.dataset.sourceTaskId, currentSrc: player.currentSrc,
            currentTime: player.currentTime, duration: player.duration, readyState: player.readyState, paused: player.paused } };
      }).catch(() => null);
      await page.screenshot({ path: path.join(out, "failure.png"), animations: "disabled" })
        .then(() => { report.failure_screenshot = "failure.png"; }).catch(() => {});
    }
  }
  finally {
    releases.forEach(release => release());
    if (browser) await browser.close();
    if (backend && backend.exitCode === null) {
      backend.kill(); await Promise.race([new Promise(resolve => backend.once("exit", resolve)), delay(5000)]);
      if (backend.exitCode === null && backend.signalCode === null) { backend.kill("SIGKILL"); await new Promise(resolve => backend.once("exit", resolve)); }
    }
    fs.rmSync(data, { recursive: true, force: true }); report.temporary_data_removed = !fs.existsSync(data);
    fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ ok: report.ok, checks: report.checks, out }));
  }
}
if (process.argv.includes("--self-test")) {
  const sample = { taskId: "source", currentSrc: "http://127.0.0.1:1/api/tasks/source/media", currentTime: 5.25, hidden: false, readyState: 1, paused: true };
  assertPlayer(sample, "source", 5.25);
  for (const change of [{ taskId: "other" }, { currentSrc: "http://127.0.0.1:1/api/tasks/other/media" }, { currentTime: 0 }, { paused: false }, { readyState: 0 }, { hidden: true }])
    assert.throws(() => assertPlayer({ ...sample, ...change }, "source", 5.25));
  console.log("Player acceptance assertions reject wrong source, media URL, time, autoplay and unloaded/hidden player; browser not launched");
} else main().catch(error => { console.error(error); process.exitCode = 1; });
