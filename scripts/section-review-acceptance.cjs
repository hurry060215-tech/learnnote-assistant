// Actual browser, isolated real backend, and one local synthetic provider.
// LEARNNOTE_ACCEPTANCE_BROWSER selects an installed Chromium path; default is Edge.
const assert = require("node:assert/strict");
const fs = require("node:fs"), os = require("node:os"), path = require("node:path");
const { spawn } = require("node:child_process");
const { createHash } = require("node:crypto");
const { chromium } = require("playwright");
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, label, timeout = 20000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { if (await check()) return; await delay(50); }
  throw new Error(`Timed out: ${label}`);
}
(async () => {
  const out = path.resolve(process.argv[2] || "build/section-review-ui"); fs.mkdirSync(out, { recursive: true });
  const data = fs.mkdtempSync(path.join(os.tmpdir(), "learnnote-section-review-"));
  const report = { ok: false, synthetic_only: true, actual_http: true, actual_disk: true,
    browser: process.env.LEARNNOTE_ACCEPTANCE_BROWSER || "Microsoft Edge", checks: [], screenshots: [], errors: [], external_requests: [] };
  let backend, browser, fixture, failure, buffer = "";
  try {
    const env = {};
    for (const [key, value] of Object.entries(process.env))
      if (/^(PATH|SYSTEMROOT|WINDIR|COMSPEC|PATHEXT|TEMP|TMP|LANG|LC_ALL)$/i.test(key)) env[key] = value;
    Object.assign(env, { PYTHONUTF8: "1", PYTHONUNBUFFERED: "1", PYTHONDONTWRITEBYTECODE: "1" });
    backend = spawn(process.env.LEARNNOTE_ACCEPTANCE_PYTHON || "python", [path.join(__dirname, "section-review-fixture.py"), "--data-dir", data],
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
    const mode = async value => assert((await page.request.post(base + "/_fixture/mode/" + value)).ok());
    function hashes() {
      const output = {};
      for (const id of [fixture.task_id, fixture.partial_task_id]) for (const name of fs.readdirSync(path.join(data, "tasks", id))) {
        const file = path.join(data, "tasks", id, name);
        if (fs.statSync(file).isFile()) output[`${id}/${name}`] = createHash("sha256").update(fs.readFileSync(file)).digest("hex");
      }
      return output;
    }
    const originals = hashes();
    async function open() {
      await page.locator("#readerOptions > summary").click(); await page.locator("#moreTools").click();
      await page.locator('[data-action="section-review"]').click(); await page.locator("#sectionReviewChapter").waitFor();
      const options = await page.locator("#sectionReviewChapter option").all();
      await page.locator("#sectionReviewChapter").selectOption(await options.at(-1).getAttribute("value"));
    }
    async function preview() { await page.locator("#sectionReviewPrepare").click(); await page.locator("#sectionReviewConsent").waitFor(); }
    async function send() { await page.locator("#sectionReviewConsent").check(); await page.locator("#sectionReviewSend").click(); }
    async function capture(name, position = "top") {
      for (const theme of ["light", "dark"]) for (const width of [1280, 1440, 768, 390]) {
        await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
        await page.evaluate(theme => { document.body.classList.toggle("dark", theme === "dark"); }, theme);
        if (position === "top") await page.locator("#toolsDialog").evaluate(node => { node.scrollTop = 0; });
        else await page.locator(position).first().scrollIntoViewIfNeeded();
        const geometry = await page.locator("#toolsDialog").evaluate(node => {
          const box = node.getBoundingClientRect();
          return { left: box.left, right: box.right, width: innerWidth, overflow: node.scrollWidth > node.clientWidth + 1,
            controls: [...node.querySelectorAll(".section-review button, .section-review select")].map(item => ({ height: item.getBoundingClientRect().height })) };
        });
        assert(!geometry.overflow && geometry.left >= 0 && geometry.right <= geometry.width + 1, JSON.stringify(geometry));
        assert(geometry.controls.every(item => item.height >= 44), "New controls retain 44px targets");
        const filename = `${name}-${theme}-${width}.png`;
        await page.screenshot({ path: path.join(out, filename), animations: "disabled" }); report.screenshots.push(filename);
      }
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.evaluate(() => document.body.classList.remove("dark"));
    }
    await page.goto(`${base}/#task/${fixture.task_id}`); await page.locator("#document h1").waitFor();
    const noteBefore = await page.locator("#document").innerText();
    await open(); await capture("ready"); assert.equal((await readState()).calls, 0);
    await preview(); assert.equal((await readState()).calls, 0);
    assert.equal(await page.locator("#sectionReviewSend").isDisabled(), true);
    await capture("preview");
    await page.locator("#sectionReviewPreview details > summary").click();
    await capture("source-preview", "#sectionReviewPreview details");
    await capture("consent", "#sectionReviewSend");
    await send(); await until(async () => (await page.locator("#sectionReviewResult details").count()) === 12, "12 model opinions");
    assert.equal((await readState()).calls, 1);
    assert.match(await page.locator("#sectionReviewResult").innerText(), /模型判断支持/);
    assert.match(await page.locator("#sectionReviewResult").innerText(), /模型判断矛盾/);
    assert.match(await page.locator("#sectionReviewResult").innerText(), /本次原文不足以判断/);
    await capture("result", "#sectionReviewResult");
    await page.locator("#sectionReviewResult details").first().locator("summary").click();
    await capture("quotation", "#sectionReviewResult details");
    assert.equal((await readState()).calls, 1, "Results do not auto-run the remaining batch");
    await page.getByRole("button", { name: "预览下一批（需另行确认）", exact: true }).click();
    await page.locator("#sectionReviewConsent").waitFor();
    assert.equal(await page.locator("#sectionReviewConsent").isChecked(), false);
    assert.equal((await readState()).calls, 1); report.checks.push("Exact preview and fresh consent for each bounded request; no automatic next batch");
    await mode("reject"); await send();
    await page.waitForFunction(() => document.querySelector("#toolStatus").textContent.includes("未自动重试"));
    await capture("rejected"); assert.equal((await readState()).calls, 2);
    await mode("delay"); await preview(); await send(); await until(async () => (await readState()).calls === 3, "pending provider request");
    await page.locator("[data-close-tool]").click(); await open();
    assert.equal(await page.locator("#sectionReviewPrepare").isDisabled(), true);
    await mode("release"); await until(async () => !(await page.locator("#sectionReviewPrepare").isDisabled()), "reopened dialog enabled");
    assert.equal(await page.locator("#sectionReviewResult details").count(), 0);
    await page.keyboard.press("Escape"); assert.equal(await page.locator("#toolsDialog").evaluate(node => node.open), false);
    await open(); await page.locator("[data-tool-back]").click(); await page.locator('[data-action="section-review"]').click();
    await page.locator("#sectionReviewPrepare").waitFor(); await page.locator("[data-close-tool]").click();
    assert.equal(await page.locator("#document").innerText(), noteBefore); assert.deepEqual(hashes(), originals);
    report.checks.push("Rejected response has no retry; close/reopen suppresses stale results and unlocks; Escape/back/close work; original artifacts unchanged");
    await page.goto(`${base}/#task/${fixture.partial_task_id}`); await page.locator("#document h1").waitFor();
    const partial = await page.locator("#document").innerText(); assert.match(partial, /字面匹配/); assert.doesNotMatch(partial, /【待核对/);
    assert.match(partial, /未完成最终校验/);
    await page.screenshot({ path: path.join(out, "partial-reading.png"), animations: "disabled" }); report.screenshots.push("partial-reading.png");
    await mode("normal"); await open(); await preview(); assert.equal((await readState()).calls, 3);
    await page.keyboard.press("Escape");
    report.checks.push("Partial draft uses one chapter boundary; review opens for actual current-attempt draft without calling model");
    assert.deepEqual(report.errors, []); assert.deepEqual(report.external_requests, []);
    report.ok = true;
  } finally {
    fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(report, null, 2));
    await browser?.close(); backend?.kill();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
