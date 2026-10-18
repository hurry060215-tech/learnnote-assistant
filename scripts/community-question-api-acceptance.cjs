// Real isolated APIs/disk and shipped browser UI; a held completion test double
// replaces only the existing completion seam. No provider or course site calls.
const assert = require("node:assert/strict");
const fs = require("node:fs"), os = require("node:os"), path = require("node:path");
const { spawn } = require("node:child_process");
const { completedAction, cleanupFixture } = require("./course-upgrade-fixture-helpers.cjs");
const { bounded } = require("./range-platform-browser-acceptance.cjs");
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
async function until(check, label, timeout = 20000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { if (await check()) return; await delay(50); }
  throw new Error(`Timed out: ${label}`);
}
function browserLaunchOptions(executablePath) {
  return executablePath ? { executablePath, headless: true } : { channel: "msedge", headless: true };
}
async function navigateHome(page) {
  await page.evaluate(() => { location.hash = ""; });
  await page.locator("#welcome #homeUrlForm").waitFor({ state: "visible" });
  assert(await page.evaluate(() => location.hash === "" && document.getElementById("reading").hidden
    && !document.getElementById("toolsDialog").open), "Home navigation must hide the reader and dismiss the transient dialog");
}
function answerViewportState(dialog) {
  const frame = dialog.getBoundingClientRect(), header = dialog.querySelector(":scope > header").getBoundingClientRect();
  const label = dialog.querySelector("#communityQuestionResult h3"), answer = dialog.querySelector("#communityQuestionResult .answer");
  const visible = node => {
    if (!node) return false;
    const rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 && rect.top >= Math.max(0, frame.top, header.bottom)
      && rect.bottom <= Math.min(innerHeight, frame.bottom) && rect.left >= Math.max(0, frame.left)
      && rect.right <= Math.min(innerWidth, frame.right);
  };
  return { label_visible: visible(label), answer_visible: visible(answer),
    unverified_label: Boolean(label?.textContent.includes("整体未经事实验证")) };
}
function pagingViewportState(dialog) {
  const frame = dialog.getBoundingClientRect(), header = dialog.querySelector(":scope > header").getBoundingClientRect();
  const status = dialog.querySelector("#communityPageStatus"), controls = status?.nextElementSibling;
  const visible = node => {
    if (!node) return false;
    const box = node.getBoundingClientRect();
    return box.width > 0 && box.height > 0 && box.top >= Math.max(0, frame.top, header.bottom)
      && box.bottom <= Math.min(innerHeight, frame.bottom) && box.left >= Math.max(0, frame.left)
      && box.right <= Math.min(innerWidth, frame.right);
  };
  return { status_visible: visible(status), controls_visible: visible(controls) };
}
async function unexpectedDialog(dialog, report) {
  report.errors.push(`Unexpected ${dialog.type()} dialog: ${dialog.message()}`);
  try { await dialog.dismiss(); } catch (error) { report.errors.push(`Dialog dismissal failed: ${error.message}`); }
}
async function withHeldPreview(page, url, action) {
  const held = deferred(), started = deferred(), settled = deferred();
  let intercepted = false, installed = false, upstreamError, settleError, primaryError;
  const handler = async route => {
    if (intercepted) return route.continue(); intercepted = true;
    try {
      let response;
      try { response = await route.fetch(); } catch (error) { upstreamError = error; return; }
      started.resolve(); await held.promise;
      try { await route.fulfill({ response }); }
      catch (error) { if (!route.request().failure()?.errorText?.includes("ERR_ABORTED")) settleError = error; }
    } finally { started.resolve(); settled.resolve(); }
  };
  try {
    await page.route(url, handler); installed = true;
    return await action(async () => {
      await bounded(started.promise, "held actual preview response", 15000);
      if (upstreamError) throw upstreamError;
    });
  } catch (error) { primaryError = error; throw error; }
  finally {
    held.resolve();
    // Removing an in-flight Playwright handler may continue its route. Settle first.
    await cleanupFixture({ settle: async () => {
      if (intercepted) await bounded(settled.promise, "obsolete preview discarded", 15000);
      if (settleError) throw settleError;
    }, route: () => installed && page.unroute(url, handler) }, primaryError);
  }
}
async function stopFixtureProcess(backend, timeout = 5000) {
  if (!backend || backend.exitCode !== null || backend.signalCode) return;
  const exited = new Promise(resolve => backend.once("exit", resolve));
  backend.kill(); await bounded(exited, "fixture process exit", timeout);
}
async function finishFixture({ browser, backend, out, report, write = fs.writeFileSync }, primaryError) {
  let failure = primaryError;
  try {
    await cleanupFixture({ browser: async () => {
      await bounded(Promise.resolve().then(() => browser?.close()), "browser close", 10000); report.cleanup.browser_closed = true;
    }, backend: async () => { await stopFixtureProcess(backend); report.cleanup.backend_stopped = true; } }, failure);
  } catch (error) { failure ||= error; report.cleanup_error = String(error); }
  if (failure) report.passed = false;
  if (failure?.cleanupErrors) report.cleanup_errors = failure.cleanupErrors.map(error => String(error));
  try { write(path.join(out, "report.json"), JSON.stringify(report, null, 2)); }
  catch (error) { if (failure) failure.reportError = error; else failure = error; }
  if (failure) throw failure;
}
async function exerciseCommunityPaging({ page, base, task, fixture, api, open, expand, capture, readState, report }) {
  // Only this already-isolated synthetic task is seeded, via the shipped import API.
  const initial = await api(task + "/community-context");
  assert.equal(initial.items.length, 2);
  await api("/api/study/community/settings", { method: "PUT", data: { enabled: true } });
  await api(task + "/community-context", { method: "POST", data: { items: Array.from({ length: 499 }, (_, index) => ({ text: `合成分页观点 ${index + 1}，只用于本机测试。` })) } });
  const beforeCalls = (await readState()).count;
  const rows = () => page.locator("#communityRows blockquote");
  const count = text => page.locator("#communityPageStatus").getByText(text);
  async function first() { await open(); await count(/1–500.*501|1–500.*502/).waitFor(); }
  async function advance() { await page.locator("#communityNext").focus(); await page.keyboard.press("Enter"); }
  async function expectedConfirm(action, message) {
    const listeners = page.listeners("dialog"); page.removeAllListeners("dialog");
    const decision = deferred();
    const handler = async dialog => {
      try { assert.equal(dialog.type(), "confirm"); assert.equal(dialog.message(), message); await dialog.accept(); decision.resolve(); }
      catch (error) { await dialog.dismiss(); decision.resolve(error); }
    };
    page.on("dialog", handler);
    try { await action(); const error = await bounded(decision.promise, "explicit synthetic delete confirmation", 10000); if (error) throw error; }
    finally { page.off("dialog", handler); for (const listener of listeners) page.on("dialog", listener); }
  }
  await first(); assert.equal(await rows().count(), 500);
  await page.locator("#communityText").fill("保留的未提交合成观点");
  await expand(); await page.locator("#communityQuestionText").fill("仅本页的合成问题");
  await page.locator(`[data-opinion-id="${fixture.item_ids[0]}"]`).check();
  await page.locator("#communityQuestionPreview").click(); await page.locator("#communityQuestionConsent").waitFor();
  await page.locator("#communityQuestionConsent").check();
  await capture("paging-first", "#communityPageStatus");
  await advance(); await count(/501–501.*501/).waitFor();
  assert.equal(await rows().count(), 1);
  assert.equal(await page.locator("#communityQuestionConsent").count(), 0);
  assert.equal(await page.locator("#communityQuestionText").inputValue(), "");
  assert.equal(await page.locator("[data-opinion-id]:checked").count(), 0);
  assert.equal(await page.locator("#communityText").inputValue(), "保留的未提交合成观点");
  assert(await page.locator("#communityNext").isDisabled());
  assert(await page.locator("#communityPageStatus").evaluate(node => document.activeElement === node));
  const lastId = await page.locator("#communityRows [data-item-id]").getAttribute("data-item-id");
  assert.deepEqual(await page.locator("#toolsDialog").evaluate(pagingViewportState), { status_visible: true, controls_visible: true });
  await capture("paging-501", "#communityPageStatus");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator("#communityPrevious").focus(); await page.keyboard.press("Enter"); await count(/1–500.*501/).waitFor();
  assert.deepEqual(await page.locator("#toolsDialog").evaluate(pagingViewportState), { status_visible: true, controls_visible: true });
  assert(await page.locator("#communityPageStatus").evaluate(node => document.activeElement === node));
  await advance(); await count(/501–501.*501/).waitFor();
  assert.deepEqual(await page.locator("#toolsDialog").evaluate(pagingViewportState), { status_visible: true, controls_visible: true });
  assert(await page.locator("#communityPageStatus").evaluate(node => document.activeElement === node));
  await capture("paging-keyboard-390", "#communityPageStatus", { widths: [390] });
  await expand(); await page.locator("#communityQuestionText").fill("第501条的独立合成问题");
  await page.locator(`[data-opinion-id="${lastId}"]`).check();
  const reviewedResponse = await completedAction(page, "POST", base + task + "/qa/preview", () => page.locator("#communityQuestionPreview").click());
  const reviewed = await reviewedResponse.json();
  assert.deepEqual(reviewed.selected_item_ids, [lastId]);
  assert.equal(reviewed.limits.opinion_items, 20); assert.equal(reviewed.limits.opinion_characters, 20000);
  assert.equal(reviewed.limits.original_source_items, 24); assert.equal(reviewed.limits.original_source_characters, 12000);
  await page.locator("#communityPrevious").focus(); await page.keyboard.press("Enter"); await count(/1–500.*501/).waitFor();
  assert.equal(await page.locator("#communityQuestionConsent").count(), 0);
  assert.equal((await api(task + "/community-context/export")).items.length, 501);
  // Failed mutations retain the page and leave a working explicit refresh.
  for (const action of ["toggle", "delete", "clear", "import"]) {
    const url = action === "toggle" ? `${base}/api/study/community/settings` : `${base}${task}/community-context**`;
    const method = action === "toggle" ? "PUT" : action === "import" ? "POST" : "DELETE";
    const failure = `Synthetic ${action} unavailable`;
    const reject = route => route.request().method() === method
      ? route.fulfill({ status: action === "delete" ? 404 : 503, contentType: "application/json", body: JSON.stringify({ detail: { message: failure } }) }) : route.continue();
    await page.route(url, reject);
    try {
      if (action === "toggle") await page.locator('[data-action="toggle-community"]').click();
      if (action === "delete") await expectedConfirm(() => page.locator("#communityRows [data-item-id]").first().click(), "删除这条社区观点？");
      if (action === "clear") await expectedConfirm(() => page.locator('[data-action="clear-community"]').click(), "清空当前任务的社区观点？");
      if (action === "import") { await page.locator("#communityText").fill("合成失败导入"); await page.locator("#communityForm button").click(); }
      await count(new RegExp(`${failure}.*刷新列表`)).waitFor();
      assert.deepEqual(await page.locator("#toolsDialog").evaluate(pagingViewportState), { status_visible: true, controls_visible: true });
      assert(await page.locator("#communityPageStatus").evaluate(node => document.activeElement === node));
      assert.equal(await rows().count(), 500); assert(!(await page.locator("#communityRefresh").isDisabled()));
    } finally { await page.unroute(url, reject); }
    await page.locator("#communityRefresh").click(); await count(/1–500.*501/).waitFor();
  }
  // An outside insert invalidates the current cursor; no implicit retry or merge.
  await api(task + "/community-context", { method: "POST", data: { items: [{ text: "另一请求保存的合成观点" }] } });
  await advance(); await count(/已变化.*刷新列表/).waitFor();
  assert.equal(await rows().count(), 0); assert(await page.locator("#communityNext").isDisabled());
  await capture("paging-stale", "#communityPageStatus");
  await page.locator("#communityRefresh").click(); await count(/1–500.*502/).waitFor();
  // Held real page responses cannot resurrect after close, home navigation or layer revocation.
  for (const action of ["close", "navigation", "disable"]) {
    await withHeldPreview(page, `${base}${task}/community-context/page?**`, async started => {
      await advance(); await started();
      if (action === "close") await page.locator("[data-close-tool]").click();
      if (action === "navigation") await navigateHome(page);
      if (action === "disable") { await page.locator('[data-action="toggle-community"]').click(); await page.locator('[data-action="toggle-community"][data-enabled="false"]').waitFor(); }
    });
    if (action === "disable") {
      assert.equal(await page.locator("#communityQuestionForm").count(), 0);
      await capture("paging-disabled", "#communityPageStatus");
      await page.locator('[data-action="toggle-community"]').click(); await count(/1–500.*502/).waitFor();
    } else {
      assert.equal(await page.locator("#toolsDialog").evaluate(node => node.open), false);
      if (action === "navigation") { await page.goto(`${base}/#task/${fixture.task_id}`); await page.locator("#document h1").waitFor(); }
      await first();
    }
  }
  await advance(); await count(/501–502.*502/).waitFor();
  await expectedConfirm(() => page.locator(`#communityRows [data-item-id="${lastId}"]`).click(), "删除这条社区观点？");
  await count(/1–500.*501/).waitFor();
  assert(!(await api(task + "/community-context/export")).items.some(item => item.item_id === lastId));
  await page.locator("#communityText").fill("从分页窗口新保存的合成观点"); await page.locator("#communityForm button").click();
  await count(/1–500.*502/).waitFor();
  assert.equal((await api(task + "/community-context/export")).items.length, 502);
  assert.equal((await readState()).count, beforeCalls, "Paging and exact previews do not call a model");
  await expectedConfirm(() => page.locator('[data-action="clear-community"]').click(), "清空当前任务的社区观点？");
  await count(/尚未保存/).waitFor(); assert.equal(await rows().count(), 0);
  assert.equal(await page.locator("#communityQuestionForm").count(), 0);
  await capture("paging-empty", "#communityPageStatus");
  report.checks.push("Actual bounded paging:501 accessible/selectable/deletable, unchanged QA budgets, page-local consent reset, keyboard Previous/Next, preserved import draft, full export, all mutation failures recover, stale409 explicit refresh, late close/navigation/revocation guards, save and empty states; no added model call");
}

async function main() {
  const { chromium } = require("playwright");
  const out = path.resolve(process.argv[2] || "build/community-question-ui"); fs.mkdirSync(out, { recursive: true });
  const data = fs.mkdtempSync(path.join(os.tmpdir(), "learnnote-opinion-qa-"));
  const report = { passed: false, synthetic_only: true, actual_http: true, actual_disk: true, provider_called: false,
    browser: process.env.LEARNNOTE_ACCEPTANCE_BROWSER || "Microsoft Edge", fixture_data_dir: data, cleanup: {}, screenshots: [], checks: [], errors: [], external_requests: [] };
  let backend, browser, page, fixture, processFailure, primaryError, stdout = "";
  try {
    const env = {};
    for (const [key, value] of Object.entries(process.env)) if (/^(PATH|SYSTEMROOT|WINDIR|COMSPEC|PATHEXT|TEMP|TMP|LANG|LC_ALL)$/i.test(key)) env[key] = value;
    Object.assign(env, { PYTHONUTF8: "1", PYTHONUNBUFFERED: "1", PYTHONDONTWRITEBYTECODE: "1" });
    backend = spawn(process.env.LEARNNOTE_ACCEPTANCE_PYTHON || "python", [path.join(__dirname, "selected-opinion-qa-fixture.py"), "--data-dir", data],
      { cwd: path.resolve(__dirname, ".."), env, stdio: ["ignore", "pipe", "pipe"] });
    backend.on("error", error => { processFailure = error; });
    backend.on("exit", code => { processFailure = new Error(`Fixture exited ${code}`); });
    backend.stderr.on("data", chunk => fs.appendFileSync(path.join(out, "backend.log"), chunk));
    backend.stdout.on("data", chunk => {
      fs.appendFileSync(path.join(out, "backend.log"), chunk); stdout += chunk.toString();
      const lines = stdout.split(/\r?\n/); stdout = lines.pop();
      for (const line of lines) if (line.startsWith('{"fixture_origin":')) fixture = JSON.parse(line);
    });
    await until(async () => { if (processFailure) throw processFailure; if (!fixture) return false;
      try { return (await fetch(fixture.fixture_origin + "/health")).ok; } catch { return false; }
    }, "isolated fixture health", 60000);
    assert.equal(fixture.offline_network, true);
    const base = fixture.fixture_origin, task = `/api/tasks/${fixture.task_id}`;
    browser = await chromium.launch(browserLaunchOptions(process.env.LEARNNOTE_ACCEPTANCE_BROWSER));
    report.browser_version = browser.version();
    const context = await browser.newContext({ viewport: { width: 1280, height: 1000 }, reducedMotion: "reduce", serviceWorkers: "block" });
    await context.addInitScript(() => localStorage.setItem("learnnote.sidebar.collapsed", "true"));
    await context.routeWebSocket("**/*", socket => { report.external_requests.push(`WebSocket ${socket.url()}`); socket.close(); });
    await context.route("**/*", route => {
      if (new URL(route.request().url()).origin !== base) { report.external_requests.push(route.request().url()); return route.abort(); }
      return route.continue();
    });
    page = await context.newPage(); page.on("pageerror", error => report.errors.push(error.message)); page.on("dialog", dialog => unexpectedDialog(dialog, report));
    const api = async (url, options) => {
      const response = await page.request.fetch(base + url, options);
      assert(response.ok(), `${url}: ${response.status()} ${await response.text()}`); return response.json();
    };
    async function reset() {
      await until(async () => {
        const response = await page.request.post(base + "/_fixture/reset");
        if (response.status() === 409) return false;
        assert(response.ok(), `Fixture reset failed: ${response.status()}`); return true;
      }, "prior request fully drained before fixture reset");
    }
    const readState = () => api("/_fixture/state"), mutate = (action, extra = {}) => api("/_fixture/mutate", { method: "POST", data: { action, ...extra } });
    const seen = { previews: [], sends: [], deletes: [] };
    page.on("request", request => {
      if (request.url().endsWith("/qa/preview") && request.method() === "POST") seen.previews.push(request.postDataJSON());
      if (request.url().endsWith("/qa/stream") && request.method() === "POST") seen.sends.push(request.postDataJSON());
      if (request.method() === "DELETE") seen.deletes.push(new URL(request.url()).pathname);
    });
    const choices = () => page.locator("#communityQuestionForm [data-opinion-id]");
    async function open() {
      if (await page.locator("#toolsDialog").evaluate(node => node.open)) await page.locator("[data-close-tool]").click();
      if (!(await page.locator("#readerOptions").evaluate(node => node.open))) await page.locator("#readerOptions > summary").click();
      await page.locator("#moreTools").click(); await page.locator('[data-action="community"]').click();
      await page.locator('[data-action="toggle-community"]').waitFor();
    }
    async function expand() {
      await page.locator("#communityQuestionForm").locator("..").locator(":scope > summary").click();
      await page.waitForFunction(() => document.querySelector("#communityQuestionRoute")?.textContent.includes("已保存的接收方"));
    }
    async function choose(question = "What do these opinions suggest? <img src=x onerror=alert(1)>") {
      await page.locator("#communityQuestionText").fill(question); await page.locator(`[data-opinion-id="${fixture.item_ids[0]}"]`).check();
    }
    async function preview(question) {
      await choose(question);
      const response = await completedAction(page, "POST", base + task + "/qa/preview", () => page.locator("#communityQuestionPreview").click());
      const value = await response.json(); await page.locator("#communityQuestionConsent").waitFor(); return value;
    }
    async function confirm() { await page.locator("#communityQuestionConsent").check(); await page.locator("#communityQuestionSend").click(); }
    async function capture(name, target, { widths = [1280, 390], answerBody = false } = {}) {
      for (const width of widths) for (const theme of ["light", "dark"]) {
        await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
        await page.evaluate(theme => document.body.classList.toggle("dark", theme === "dark"), theme);
        await page.locator(target).scrollIntoViewIfNeeded();
        const geometry = await page.locator("#toolsDialog").evaluate(node => {
          const box = node.getBoundingClientRect(); return { left: box.left, right: box.right, width: innerWidth,
            overflow: node.scrollWidth > node.clientWidth + 1, controls: [...node.querySelectorAll(".section-review button,.section-review .tool-choice")]
              .filter(item => item.getBoundingClientRect().height).map(item => item.getBoundingClientRect().height) };
        });
        assert(!geometry.overflow && geometry.left >= 0 && geometry.right <= geometry.width + 1, JSON.stringify(geometry));
        assert(geometry.controls.every(height => height >= 44));
        if (name.startsWith("paging-")) {
          assert.deepEqual(await page.locator("#toolsDialog").evaluate(pagingViewportState), { status_visible: true, controls_visible: true });
        }
        if (answerBody) {
          const visible = await page.locator("#toolsDialog").evaluate(answerViewportState);
          assert(visible.label_visible && visible.answer_visible && visible.unverified_label, JSON.stringify(visible));
        }
        const filename = `${name}-${theme}-${width}.png`; await page.screenshot({ path: path.join(out, filename), animations: "disabled" }); report.screenshots.push(filename);
      }
      await page.setViewportSize({ width: 1280, height: 1000 }); await page.evaluate(() => document.body.classList.remove("dark"));
    }
    await api("/api/study/community/settings", { method: "PUT", data: { enabled: false } });
    await page.goto(`${base}/#task/${fixture.task_id}`); await page.locator("#document h1").waitFor(); await open();
    assert.equal(await page.locator("#communityQuestionForm").count(), 0); assert.equal((await readState()).count, 0);
    await page.locator('[data-action="toggle-community"]').click(); await page.locator("#communityQuestionForm").waitFor({ state: "attached" }); await expand();
    assert.equal(await choices().count(), fixture.item_ids.length); assert.equal(await page.locator("#communityQuestionForm [data-opinion-id]:checked").count(), 0);
    assert.equal(seen.previews.length, 0); assert.equal(seen.sends.length, 0); await capture("select", "#communityQuestionText");
    const reviewed = await preview(); assert.equal((await readState()).count, 0); assert.equal(seen.sends.length, 0);
    assert.equal(reviewed.can_submit, true); assert.equal(reviewed.opinions.length, 1);
    assert.equal(reviewed.opinions[0].item_id, seen.previews.at(-1).selected_item_ids[0]);
    const unselected = (await api(task + "/community-context")).items.filter(item => !reviewed.selected_item_ids.includes(item.item_id));
    assert(unselected.length > 0); for (const item of unselected) assert(!JSON.stringify(reviewed.messages).includes(item.text));
    assert.equal(await page.locator("#communityQuestionConsent").isChecked(), false); assert(await page.locator("#communityQuestionSend").isDisabled());
    assert.equal(await page.locator("#communityQuestionReview img,#communityQuestionReview script").count(), 0);
    assert(await page.locator("#communityQuestionReview h3").evaluate(node => document.activeElement === node));
    for (const title of ["本次选择的独立观点（非事实证据）", "实际完整发送内容（系统要求与用户内容）"])
      await page.locator("#communityQuestionReview summary").filter({ hasText: title }).click();
    assert.match(await page.locator("#communityQuestionReview").innerText(), /采集方式未记录|原始出处未核实/);
    await capture("review", "#communityQuestionReview h3"); await capture("consent", "#communityQuestionConsent");
    await page.locator("#communityQuestionConsent").focus(); await page.keyboard.press("Space"); assert(!(await page.locator("#communityQuestionSend").isDisabled()));
    await page.keyboard.press("Tab"); assert(await page.locator("#communityQuestionSend").evaluate(node => document.activeElement === node));
    await page.keyboard.press("Shift+Tab"); assert(await page.locator("#communityQuestionConsent").evaluate(node => document.activeElement === node));
    await page.locator("#communityQuestionCancel").click(); assert.equal(await page.locator("#communityQuestionConsent").count(), 0); assert.equal((await readState()).count, 0);
    for (const action of ["escape", "back", "close"]) {
      await preview(); await page.locator("#communityQuestionConsent").check();
      if (action === "escape") await page.keyboard.press("Escape");
      else await page.locator(action === "back" ? "[data-tool-back]" : "[data-close-tool]").click();
      await open(); await expand(); assert.equal(await page.locator("#communityQuestionConsent").count(), 0);
      assert.equal(await page.locator("#communityQuestionText").inputValue(), ""); assert.equal((await readState()).count, 0);
    }
    assert.equal(seen.deletes.length, 0);
    report.checks.push("Default off; exact selection local preview has zero completions; literal recipient/messages/origins; unchecked consent, keyboard focus and Close/Back/Escape/Cancel with no token DELETE");
    // Delay a real local preview response; no fabricated payload or provider transport.
    const previewUrl = base + task + "/qa/preview";
    const latestValue = await withHeldPreview(page, previewUrl, async waitStarted => {
      await choose("Delayed first question"); await page.locator("#communityQuestionPreview").click(); await waitStarted();
      await choose("Newer question");
      const latest = await completedAction(page, "POST", previewUrl, () => page.locator("#communityQuestionPreview").click());
      return latest.json();
    });
    await page.locator("#communityQuestionConsent").waitFor(); assert.match(await page.locator("#communityQuestionReview").innerText(), /Newer question/);
    assert.doesNotMatch(await page.locator("#communityQuestionReview").innerText(), /Delayed first question/);
    await page.locator("#communityQuestionConsent").check();
    await page.locator("#communityQuestionSend").evaluate(button => { button.click(); button.click(); });
    await until(async () => (await readState()).count === 1, "one approved held completion");
    assert.equal(seen.sends.length, 1); const sent = seen.sends.at(-1);
    assert.equal(sent.question, latestValue.question); assert.equal(sent.skill_id, "note.qa"); assert.equal(sent.options, undefined);
    assert.deepEqual(sent.selected_opinions.selected_item_ids, latestValue.selected_item_ids);
    assert.equal(sent.selected_opinions.confirm_send, true);
    assert.deepEqual((await readState()).calls[0].messages, latestValue.messages);
    assert.equal(await page.locator("#communityQuestionResult").innerText(), "");
    await api("/_fixture/release", { method: "POST" });
    await page.locator("#communityQuestionResult h3").waitFor();
    assert.match(await page.locator("#communityQuestionResult").innerText(), /整体未经事实验证/);
    assert.equal(await page.locator("#communityQuestionResult button,#communityQuestionResult a,#communityQuestionResult img").count(), 0);
    await capture("answer", "#communityQuestionResult h3");
    await capture("answer-body", "#communityQuestionResult .answer", { widths: [390], answerBody: true });
    assert.equal((await api(task + "/qa")).items.length, 0);
    const completedState = await readState();
    assert.equal(completedState.persistence.original_artifacts_unchanged, true);
    assert.equal(completedState.persistence.no_history_or_run_files, true);
    assert.equal(completedState.persistence.no_mixed_output_persisted, true);
    const stored = await page.evaluate(() => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }));
    assert.doesNotMatch(stored, /Newer question|Mixed answer|REDACTED|opinion_id/);
    report.checks.push("Reordered actual previews stay task-scoped; double confirmation reaches one held existing execution; exact approved messages arrive; final-only unverified result has no save/evidence action or QA history/browser draft");
    // In-flight real completion is released only after UI invalidation.
    for (const action of ["cancel", "escape", "close", "back", "question", "settings", "navigation"]) {
      await reset(); await open(); await expand(); await preview(`Cancel ${action}`); await confirm();
      await until(async () => (await readState()).count === 1, `held completion ${action}`);
      if (action === "cancel") await page.locator("#communityQuestionCancel").click();
      if (action === "escape") await page.keyboard.press("Escape");
      if (action === "close" || action === "back") await page.locator(action === "close" ? "[data-close-tool]" : "[data-tool-back]").click();
      if (action === "question") await page.locator("#communityQuestionText").fill("Changed while waiting");
      if (action === "settings") await page.evaluate(() => window.dispatchEvent(new Event("learnnote:settings")));
      if (action === "navigation") await navigateHome(page);
      await api("/_fixture/release", { method: "POST" });
      if (action === "navigation") { await page.goto(`${base}/#task/${fixture.task_id}`); await page.locator("#document h1").waitFor(); }
      await open(); await expand(); assert.equal(await page.locator("#communityQuestionResult").innerText(), "");
      assert.equal(await page.locator("#communityQuestionConsent").count(), 0); assert.equal((await api(task + "/qa")).items.length, 0);
    }
    report.checks.push("Real held stream cancellation survives Cancel/Escape/Close/Back/question/model settings/navigation; late final result never resurrects and history stays empty");
    // Actual server-side revocation after preview, before and during completion.
    for (const action of ["delete_opinion", "disable", "source_change", "model_change"]) {
      for (const phase of ["preview", "completion"]) {
        await reset(); await page.goto(`${base}/#task/${fixture.task_id}`); await page.locator("#document h1").waitFor();
        await open(); await expand(); const review = await preview(`Revocation ${action} ${phase}`);
        if (phase === "completion") { await confirm(); await until(async () => (await readState()).count === 1, "held revoked completion"); }
        await mutate(action, { item_id: review.selected_item_ids[0] });
        if (phase === "preview") await confirm(); else await api("/_fixture/release", { method: "POST" });
        await page.locator("#communityQuestionStatus").getByText(/重新预览|来源已变化|接收方已变化|无法|已失效|不存在|已关闭/).waitFor();
        assert.equal(await page.locator("#communityQuestionResult").innerText(), "");
        assert.equal((await readState()).count, phase === "preview" ? 0 : 1);
        assert.equal((await api(task + "/qa")).items.length, 0);
      }
    }
    const final = await readState(); report.persistence = final.persistence;
    assert.equal(final.persistence?.no_history_or_run_files, true, JSON.stringify(final.persistence));
    assert.equal(final.persistence?.no_mixed_output_persisted, true, JSON.stringify(final.persistence));
    report.checks.push("Actual server revocation: item deletion, layer disable, source bytes and saved model mutations reject preview admission and held final completion; persistence families unchanged");
    await exerciseCommunityPaging({ page, base, task, fixture, api, open, expand, capture, readState, report });
    assert.deepEqual(report.errors, []); assert.deepEqual(report.external_requests, []); report.passed = true;
  } catch (error) {
    primaryError = error; report.error = String(error.stack || error);
    if (page && !page.isClosed()) {
      try { await page.screenshot({ path: path.join(out, "failure.png"), animations: "disabled" }); report.screenshots.push("failure.png"); }
      catch (captureError) { report.failure_capture_error = String(captureError); }
    }
  }
  finally { await finishFixture({ browser, backend, out, report }, primaryError); }

  if (primaryError) throw primaryError;
}
if (require.main === module) main().catch(error => { console.error(error); process.exitCode = 1; });
module.exports = { exerciseCommunityPaging, pagingViewportState, until, browserLaunchOptions, navigateHome, answerViewportState, unexpectedDialog, withHeldPreview, stopFixtureProcess, finishFixture };
