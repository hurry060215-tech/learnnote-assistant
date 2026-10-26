// Actual Windows Edge, shipped workspace/settings menu and a synthetic native
// bridge. No desktop exit/copy/config write, real user paths, server, or model.
// Run in the authorized hosted Windows visual job; do not bypass local denials.
const assert = require("node:assert/strict");
const { fixtureTaskCatalog, fixtureMaterialPage } = require('./library-browser-fixture.cjs');
const fs = require("node:fs"), path = require("node:path");
const { execFileSync } = require("node:child_process");
const { cleanupFixture } = require("./course-upgrade-fixture-helpers.cjs");
const ROOT = path.resolve(__dirname, ".."), BASE = "http://127.0.0.1:18943";
const PLAN = { ok: true, preview: true, token: "synthetic-review", source: "C:\\Synthetic\\LearnNote\\学习资料与逐字稿", path: "D:\\Synthetic\\LearnNote\\新的学习资料目录",
  file_count: 12, byte_count: 4194304,
  changes: [{ file: "tasks/synthetic/task.json", field: "media_path", before: "C:\\Synthetic\\LearnNote\\学习资料与逐字稿\\tasks\\synthetic\\video.mp4", after: "D:\\Synthetic\\LearnNote\\新的学习资料目录\\tasks\\synthetic\\video.mp4" },
    { file: "library.sqlite3", field: "materials.raw_path", before: "<literal-synthetic-path>", after: "<literal-mapped-path>" }],
  excluded: [{ path: "secrets", reason: "系统凭据不会复制" }, { path: "logs", reason: "运行日志不在迁移范围" }],
  external_references: [{ file: "tasks/synthetic/task.json", field: "source_media_path", value: "E:\\Synthetic\\outside\\external-source.mp4", reason: "outside_source" }] };
function installBridge(plan) {
  window.__migrationFixture = { mode: "preview", applyMode: "success", outcome: "none", calls: [], release: null };
  const control = window.__migrationFixture;
  window.pywebview = { api: {
    data_migration_status: async () => {
      control.calls.push({ method: "status-read" });
      return { ok: true, status: control.outcome, source: plan.source, path: plan.path, receipt: "C:\\Synthetic\\app\\receipt.json", message: {
        none: "", complete: "复制已校验，配置已切换到目标目录。原目录和原配置备份仍保留。",
        failed: "迁移未激活，仍保留原配置。请查看记录，处理原因后选择新的空目录重新预览。",
        incomplete: "迁移或配置状态尚未确认。请保留新旧目录与原配置备份，查看记录后再决定恢复或重新预览。",
        scheduled: "迁移已安排，尚无完成记录。请保留原目录；不要在无法确认结果时重复操作。",
      }[control.outcome] };
    },
    choose_data_directory: async preview => {
      control.calls.push({ method: "preview", preview });
      const mode = control.mode; control.mode = "preview";
      if (mode === "held-preview") await new Promise(resolve => { control.release = resolve; });
      if (mode === "cancelled") return { cancelled: true };
      if (mode === "preview-conflict") return { ok: false, code: "destination_conflict", message: "目标目录不是空目录，请选择其他目录。" };
      return JSON.parse(JSON.stringify(plan));
    },
    apply_data_directory: async token => {
      control.calls.push({ method: "apply", token });
      if (control.applyMode === "held-apply") await new Promise(resolve => { control.release = resolve; });
      if (control.applyMode === "conflict") return { ok: false, code: "destination_conflict", message: "目标目录在预览后发生变化，不能覆盖。" };
      return { ok: true, restarting: true, message: "Synthetic restart scheduled; no files copied." };
    },
    restart_application: async () => { control.calls.push({ method: "legacy-restart" }); throw Error("Legacy restart is forbidden"); },
  } };
}
function syntheticResponse(pathname, search = '') {
  return {
    "/health": { ok: true, service: "learnnote", app_version: "0.2.15", backend_version: "0.2.15", protocol_version: 1, llm_model_configured: false, local_asr_available: false, model_provider_presets: [], assistant_capabilities: {}, data_paths: { root: PLAN.source } },
    "/api/tasks": { tasks: [] }, "/api/tasks/catalog": fixtureTaskCatalog([]),
    "/api/library/materials": fixtureMaterialPage([], search),
    "/api/preferences": { task_options: { transcriber: "none", note_style: "study", note_template: "standard", summary_depth: "standard", local_ocr: false } },
    "/api/model/connection": { model: null, configured: false },
    "/api/model/route": { routes: [], blocking_reasons: [], data_leaving_device: [], offline_source_confirmed: true },
    "/api/connections": { openrouter: { connected: false } }, "/api/assistant/skills": { skills: [], features: [] },
    "/api/assistant/history": { items: [] }, "/api/update/status": { ok: true, status: "up_to_date", preferences: { auto_check: false, auto_download: false } },
    "/api/support/activation": { enabled: false }, "/api/courses": { courses: [] },
  }[pathname];
}
// A viewport resize can land before the app's resize listener updates ARIA.
// Wait for that real state to settle before deciding whether a menu click opens
// or closes the current layout. Do not force classes, handlers, or visibility.
function migrationSidebarReady() {
  const sidebar = document.querySelector("#sidebar"), menu = document.querySelector("#menu");
  if (!sidebar || typeof menu?.onclick !== "function") return false;
  const expanded = matchMedia("(max-width: 760px)").matches
    ? document.body.classList.contains("menu-open") : !document.body.classList.contains("sidebar-collapsed");
  return menu.getAttribute("aria-expanded") === String(expanded) && sidebar.inert === !expanded;
}
async function openMigrationSettings(page) {
  await page.waitForFunction(() => Boolean(window.LearnNoteSettings) && Boolean(document.querySelector("#homeUrlForm")) && !document.querySelector("#welcome").hidden);
  await page.waitForFunction(migrationSidebarReady);
  if (await page.evaluate(() => document.body.classList.contains("focus-reading") || document.querySelector("#menu").getAttribute("aria-expanded") !== "true")) await page.locator("#menu").click();
  await page.waitForFunction(() => {
    const settings = document.querySelector("#settings"), bounds = settings?.getBoundingClientRect();
    return !document.querySelector("#sidebar").inert && document.querySelector("#menu").getAttribute("aria-expanded") === "true" &&
      bounds?.width > 0 && bounds.left >= 0 && bounds.right <= innerWidth + 1;
  });
  await page.locator("#settings").click(); await page.locator('[data-settings-section="storage"]').click();
}
function migrationModalFocusIsSafe(state) {
  const inside = state.insideModal && !state.rootFallback;
  const chrome = !state.insideModal && !state.documentHasFocus && state.rootFallback && ["BODY", "HTML"].includes(state.activeTag);
  return state.open && state.modal && state.settingsOpen && state.openDialogs === 2 && state.phase === "preview"
    && state.backgroundVisible && !state.backgroundDisabled && state.backgroundFocusRefused && (inside || chrome);
}
async function checkMigrationModalFocus(page, report, width, dark) {
  const dialog = page.locator("#dataMigrationDialog");
  async function observe(key) {
    const state = await dialog.evaluate(node => {
      const active = document.activeElement, background = document.querySelector("#settingsDialog [data-close]"), rect = background.getBoundingClientRect();
      const state = { activeTag: active?.tagName, activeId: active?.id || "", documentHasFocus: document.hasFocus(),
        insideModal: node.contains(active), rootFallback: active === document.body || active === document.documentElement,
        open: node.open, modal: node.matches(":modal"), settingsOpen: document.querySelector("#settingsDialog").open,
        openDialogs: document.querySelectorAll("dialog[open]").length, phase: node.dataset.phase,
        backgroundVisible: rect.width > 0 && rect.height > 0 && rect.left >= 0 && rect.top >= 0 && rect.right <= innerWidth + 1 && rect.bottom <= innerHeight + 1,
        backgroundDisabled: background.disabled };
      background.focus({ preventScroll: true });
      state.backgroundFocusRefused = document.activeElement !== background;
      return state;
    });
    (report.native_modal_focus ||= []).push({ width, dark, key, ...state });
    assert(migrationModalFocusIsSafe(state), `Native migration modal focus/background contract: ${JSON.stringify(state)}`);
    return state;
  }
  const before = await page.evaluate(() => JSON.stringify(window.__migrationFixture.calls));
  for (let i = 0; i < 10; i++) {
    await page.keyboard.press("Tab"); const state = await observe("Tab");
    // Browser chrome is a valid native Tab destination; reverse navigation must
    // return to the modal without enabling the underlying settings controls.
    if (!state.insideModal) {
      await page.keyboard.press("Shift+Tab"); const returned = await observe("Shift+Tab");
      assert(returned.insideModal && returned.documentHasFocus, "Reverse Tab must return from browser chrome to migration modal");
    }
  }
  assert.equal(await page.evaluate(() => JSON.stringify(window.__migrationFixture.calls)), before, "Keyboard navigation must not activate background preview or migration");
}
async function main() {
  const out = path.resolve(process.argv[2] || "build/data-migration-ui"); fs.mkdirSync(out, { recursive: true });
  const report = { passed: false, source_sha: execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim(), browser: "Microsoft Edge",
    fixture_mode: "shipped_app_synthetic_native_bridge", backend_tested: false, native_webview_tested: false, actual_migration_tested: false,
    checks: [], screenshots: [], errors: [], unexpected_requests: [], bridge_calls: [],
    not_tested: ["native folder dialog", "desktop process exit", "actual file copying and configuration commit", "real credentials", "native webview"] };
  const save = () => fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(report, null, 2));
  const check = text => { report.checks.push(text); save(); };
  let browser, page, context, primaryError;
  save();
  try {
    assert.equal(process.platform, "win32", "Run this actual Edge fixture in the authorized hosted Windows visual job");
    const { chromium } = require("playwright");
    browser = await chromium.launch({ channel: "msedge", headless: true }); report.browser_version = browser.version();
    context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce", serviceWorkers: "block" });
    await context.addInitScript(installBridge, PLAN);
    await context.routeWebSocket("**/*", socket => { report.unexpected_requests.push(`WebSocket ${socket.url()}`); socket.close(); });
    await context.route("**/*", async route => {
      const request = route.request(), url = new URL(request.url());
      try {
        assert.equal(url.origin, BASE, "External request blocked"); assert.equal(request.method(), "GET", "Only synthetic reads are expected");
        if (url.pathname === "/" || url.pathname.startsWith("/web/")) {
          const target = path.resolve(ROOT, url.pathname === "/" ? "web/index.html" : decodeURIComponent(url.pathname.slice(1)));
          assert(target.startsWith(path.join(ROOT, "web") + path.sep)); assert(fs.statSync(target).isFile());
          return await route.fulfill({ body: fs.readFileSync(target), contentType: ({ ".html": "text/html", ".js": "application/javascript", ".css": "text/css", ".png": "image/png", ".svg": "image/svg+xml", ".woff2": "font/woff2" })[path.extname(target)] || "application/octet-stream" });
        }
        const response = syntheticResponse(url.pathname, url.search); assert(response, `Unexpected route: ${url.pathname}`);
        return await route.fulfill({ json: response });
      } catch (error) { report.unexpected_requests.push(`${request.method()} ${url.pathname}: ${error.message}`); await route.abort("blockedbyclient").catch(() => {}); }
    });
    page = await context.newPage(); page.setDefaultTimeout(15000);
    page.on("pageerror", error => { report.errors.push(error.message); save(); });
    page.on("dialog", dialog => { report.errors.push(`Unexpected browser dialog: ${dialog.type()}`); dialog.dismiss(); });
    const calls = () => page.evaluate(() => window.__migrationFixture.calls);
    const count = async method => (await calls()).filter(call => call.method === method).length;
    const phase = value => page.waitForFunction(value => document.querySelector("#dataMigrationDialog")?.dataset.phase === value, value);
    const openSettings = () => openMigrationSettings(page);
    async function openPreview() { await page.locator("#changeSettingsFolder").click(); await phase("preview"); }
    async function snapshot(name, target = "#dataMigrationHeading") {
      if (target === "#dataMigrationHeading") await page.locator("#dataMigrationDialog").evaluate(el => { el.scrollTop = 0; });
      await page.locator(target).scrollIntoViewIfNeeded();
      const geometry = await page.locator("#dataMigrationDialog").evaluate(el => { const r = el.getBoundingClientRect(); return { left: r.left, right: r.right, center: r.left + r.width / 2, width: innerWidth, overflow: el.scrollWidth > el.clientWidth + 1, pageOverflow: document.documentElement.scrollWidth > innerWidth + 1 }; });
      assert(!geometry.overflow && !geometry.pageOverflow, JSON.stringify(geometry)); assert(geometry.left >= 0 && geometry.right <= geometry.width + 1); assert(Math.abs(geometry.center - geometry.width / 2) < 2);
      await page.screenshot({ path: path.join(out, name + ".png"), animations: "disabled" }); report.screenshots.push(name + ".png"); save();
    }
    await page.goto(BASE); await openSettings(); const rootBefore = await page.locator("#settingsDataRoot").textContent();
    await page.setViewportSize({ width: 390, height: 900 });
    for (const outcome of ["failed", "incomplete", "scheduled", "complete"]) {
      await page.keyboard.press("Escape"); await page.evaluate(outcome => window.__migrationFixture.outcome = outcome, outcome); await openSettings();
      await page.waitForFunction(outcome => document.querySelector("#settingsMigrationOutcome")?.dataset.status === outcome, outcome);
      const panel = page.locator("#settingsMigrationOutcome");
      const expected = await page.evaluate(async () => (await window.pywebview.api.data_migration_status()).message);
      assert.equal(await panel.locator("[data-migration-outcome]").textContent(), expected);
      await panel.locator("summary").click(); await panel.scrollIntoViewIfNeeded();
      assert.match(await panel.locator("pre").textContent(), /receipt.json/);
      assert(await panel.evaluate(el => el.scrollWidth <= el.clientWidth + 1));
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      assert.equal(await page.locator("#settingsDataRoot").textContent(), rootBefore);
      const name = `mobile-last-migration-${outcome}.png`; await page.screenshot({ path: path.join(out, name), animations: "disabled" }); report.screenshots.push(name); save();
    }
    assert.equal(await count("apply"), 0); check("Read-only last migration outcome refreshes on settings open: failed, incomplete, scheduled and native-reconciled complete are shown literally with receipt paths; no config/root changes");
    await page.keyboard.press("Escape"); await page.evaluate(() => window.__migrationFixture.outcome = "none"); await page.setViewportSize({ width: 1440, height: 1000 }); await openSettings();
    await page.waitForFunction(() => document.querySelector("#settingsMigrationOutcome").hidden);
    await openPreview(); assert.equal(await count("apply"), 0);
    assert.equal(await page.locator("[data-migration-source]").textContent(), PLAN.source); assert.equal(await page.locator("[data-migration-target]").textContent(), PLAN.path);
    assert.match(await page.locator("[data-migration-count]").textContent(), /12 个文件.*4,194,304 字节/);
    for (const [selector, rows] of [["changes", PLAN.changes], ["excluded", PLAN.excluded], ["external", PLAN.external_references]]) {
      const details = page.locator(`[data-migration-${selector}]`); await details.locator("summary").click();
      assert.equal(await details.locator("pre").textContent(), JSON.stringify(rows, null, 2));
      assert.equal(await details.locator("literal-synthetic-path,img,script").count(), 0);
      await snapshot(`desktop-exact-${selector}`, `[data-migration-${selector}] summary`);
      await details.locator("summary").click();
    }
    await page.locator("[data-migration-cancel]").click(); assert.equal(await count("apply"), 0);
    await page.waitForFunction(() => document.activeElement?.id === "changeSettingsFolder"); assert.equal(await page.locator("#settingsDataRoot").textContent(), rootBefore);
    check("Real settings menu opens read-only preview; source, target, exact counts and complete literal records match native plan; Cancel keeps current root and restores focus");
    await page.locator('[data-settings-section="notes"]').click();
    const originalPrompt = await page.locator("#prefCustom").inputValue(); await page.locator("#prefCustom").fill("Synthetic unsaved preference");
    await page.locator('[data-settings-section="storage"]').click(); await openPreview(); await page.locator("[data-migration-confirm]").click();
    assert.equal(await count("apply"), 0); assert.match(await page.locator("#dataMigrationStatus").textContent(), /请先保存未完成的编辑与设置/);
    await snapshot("unsaved-settings-blocked", "#dataMigrationStatus"); await page.locator("[data-migration-cancel]").click();
    await page.locator('[data-settings-section="notes"]').click(); await page.locator("#prefCustom").fill(originalPrompt);
    await page.locator('[data-settings-section="storage"]').click();
    check("Unsaved settings block native apply without discarding the draft");
    for (const width of [1280, 1440, 768, 390]) for (const dark of [false, true]) {
      await page.setViewportSize({ width, height: 900 });
      await page.evaluate(dark => document.body.classList.toggle("dark", dark), dark);
      await openPreview();
      assert.equal(await page.locator("#dataMigrationDialog").getAttribute("aria-labelledby"), "dataMigrationHeading");
      await page.waitForFunction(() => document.activeElement?.matches("[data-migration-close]"));
      await checkMigrationModalFocus(page, report, width, dark);
      assert.equal(await page.locator("#dataMigrationDialog").evaluate(el => getComputedStyle(el).animationName), "none");
      await snapshot(`${width}-${dark ? "dark" : "light"}-preview`);
      await snapshot(`${width}-${dark ? "dark" : "light"}-confirm`, "[data-migration-confirm]");
      const actions = await page.locator("#dataMigrationDialog button:visible").evaluateAll(elements => elements.map(el => el.getBoundingClientRect().height)); assert(actions.every(height => height >= 44));
      await page.keyboard.press("Escape"); await page.waitForFunction(() => !document.querySelector("#dataMigrationDialog").open && document.activeElement?.id === "changeSettingsFolder");
    }
    assert.equal(await count("apply"), 0); check("1280/1440/768/390 light/dark previews and confirmation captured; centered, no overflow, 44px actions, native modal/background isolation, Escape return and reduced motion");
    // Re-enter through the real mobile drawer; no forced off-screen settings clicks.
    await page.keyboard.press("Escape"); await openSettings();
    await page.evaluate(() => window.__migrationFixture.mode = "held-preview"); await page.locator("#changeSettingsFolder").click(); await phase("selecting");
    await page.keyboard.press("Escape"); await page.evaluate(() => window.__migrationFixture.release());
    await page.waitForFunction(() => !document.querySelector("#dataMigrationDialog").open && !document.querySelector("#changeSettingsFolder").disabled);
    await openPreview(); await page.keyboard.press("Escape"); assert.equal(await count("apply"), 0);
    check("Pending native preview cancelled with Escape cannot reopen or apply a stale plan; fresh preview still works through the real mobile menu");
    await page.evaluate(() => window.__migrationFixture.mode = "preview-conflict"); await page.locator("#changeSettingsFolder").click(); await phase("error");
    await snapshot("mobile-preview-conflict", "#dataMigrationStatus"); assert.equal(await page.locator("[data-migration-confirm]").isVisible(), false);
    await page.locator("[data-migration-retry]").click(); await phase("preview");
    await page.evaluate(() => window.__migrationFixture.applyMode = "conflict"); await page.locator("[data-migration-confirm]").click(); await phase("error");
    assert.equal(await count("apply"), 1); assert.match(await page.locator("#dataMigrationStatus").textContent(), /目标目录在预览后发生变化/);
    assert.equal(await page.locator("[data-migration-confirm]").isVisible(), false); assert.equal(await page.locator("#settingsDataRoot").textContent(), rootBefore);
    await snapshot("mobile-apply-conflict", "#dataMigrationStatus"); check("Preview/apply conflicts show errors, never completion or root replacement; failed apply requires a fresh preview");
    await page.locator("[data-migration-retry]").click(); await phase("preview");
    await page.evaluate(() => window.__migrationFixture.applyMode = "held-apply"); await page.locator("[data-migration-confirm]").click(); await phase("applying");
    await page.keyboard.press("Escape"); assert.equal(await page.locator("#dataMigrationDialog").evaluate(el => el.open), true);
    assert.equal(await page.locator("[data-migration-cancel]").isDisabled(), true); assert.equal(await page.locator("[data-migration-confirm]").isDisabled(), true);
    await snapshot("mobile-confirmation-pending", "#dataMigrationStatus"); await page.evaluate(() => window.__migrationFixture.release()); await phase("restarting");
    assert.equal(await count("apply"), 2); assert.equal(await count("legacy-restart"), 0);
    assert.match(await page.locator("#dataMigrationStatus").textContent(), /尚不能确认复制完成/); assert.equal(await page.locator("#settingsDataRoot").textContent(), rootBefore);
    await snapshot("mobile-migration-scheduled", "#dataMigrationStatus"); check("Explicit confirmation calls only apply_data_directory(token), blocks duplicate apply and dismiss while scheduling, and never claims completed copy");
    report.bridge_calls = await calls(); assert(report.bridge_calls.filter(call => call.method === "preview").every(call => call.preview === true));
    assert(report.bridge_calls.filter(call => call.method === "apply").every(call => call.token === PLAN.token));
    assert.deepEqual(report.errors, []); assert.deepEqual(report.unexpected_requests, []); report.passed = true;
  } catch (error) {
    primaryError = error;
    report.errors.push(error.stack || error.message);
    if (page) {
      report.bridge_calls = await page.evaluate(() => window.__migrationFixture?.calls || []).catch(() => []);
      report.sidebar_at_failure = await page.evaluate(() => ({ width: innerWidth,
        compact: matchMedia("(max-width: 760px)").matches, classes: document.body.className,
        expanded: document.querySelector("#menu")?.getAttribute("aria-expanded"), inert: document.querySelector("#sidebar")?.inert })).catch(() => null);
    }
    if (page) await page.screenshot({ path: path.join(out, "failure.png"), animations: "disabled" }).then(() => report.screenshots.push("failure.png")).catch(() => {});
    throw error;
  } finally {
    await cleanupFixture({ report: save, context: () => context?.close(), browser: () => browser?.close() }, primaryError);
  }
  console.log(`PASS: migration preview/cancel/confirm/conflict, exact disclosures, mobile menu and accessibility; ${report.screenshots.length} screenshots at ${out}`);
}
if (require.main === module) main().catch(error => { console.error(error); process.exitCode = 1; });
module.exports = { PLAN, installBridge, syntheticResponse, migrationSidebarReady, openMigrationSettings, migrationModalFocusIsSafe };
