// Microsoft Edge fixture for the real default application and storage panel.
// All assets come from this checkout and every API response is synthetic. No
// backend, user data directory, external website, or model provider is contacted.
// Run only in an authorized Windows Edge environment:
// node scripts/material-catalog-recovery-acceptance.cjs [loopback-origin] [output]
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path"), os = require("node:os");
const { createHash } = require("node:crypto");
const root = path.resolve(__dirname, "..");
const sha256 = value => createHash("sha256").update(value).digest("hex");
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
async function waitForFixture(promise) {
  let timer;
  try { await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("Synthetic request did not reach its expected state")), 15000); })]); }
  finally { clearTimeout(timer); }
}
const fixture = name => ({ name, mimeType: "application/vnd.sqlite3", buffer: Buffer.from(`SQLite format 3\0Synthetic fixture snapshot: ${name}`) });

async function main() {
  const { chromium } = require("playwright");
  const base = new URL(process.argv[2] || "http://127.0.0.1:18932");
  assert.equal(base.protocol, "http:");
  assert(["127.0.0.1", "localhost", "[::1]"].includes(base.hostname), "Only synthetic loopback origins are allowed");
  const out = path.resolve(process.argv[3] || fs.mkdtempSync(path.join(os.tmpdir(), "learnnote-catalog-recovery-")));
  fs.mkdirSync(out, { recursive: true });
  const report = { passed: false, browser: "Microsoft Edge", fixture_mode: "real_app_synthetic_api", checks: [], screenshots: [], errors: [], unexpected_requests: [], previews: [], applies: [], task_rebuilds: [] };
  const files = new Map(["chosen.sqlite3", "other.sqlite3", "unresolved.sqlite3", "empty.sqlite3", "invalid.sqlite3", "stale.sqlite3", "held.sqlite3", "partial.sqlite3"].map(name => [name, fixture(name)]));
  const holds = new Map();
  let catalogState = "missing", statusFails = false, restored = false, rebuildOutcome = "partial";
  const material = {
    material_id: "original-material-id", title: "所选快照里的资料 · gb18030", filename: "原始笔记.txt", source_type: "text", status: "ready", linked_task_id: "", anchor_count: 2,
    created_at: "2026-09-27T10:00:00Z", updated_at: "2026-09-28T10:00:00Z", stored_locally: true,
    metadata: { encoding: "gb18030", raw_sha256: "c".repeat(64), raw_file_saved: true },
  };
  const preview = file => ({
    snapshot_sha256: sha256(file.buffer), preview_token: sha256(`preview:${sha256(file.buffer)}`),
    recovery_scope: "material_catalog_only", can_apply: true, recoverable_count: 1, catalog: { state: catalogState },
    materials: [{ material_id: material.material_id, title: material.title, status: "recoverable", reason: "保留快照中的资料编号、gb18030 编码选择和原始关联。" }, { material_id: "video-alias", title: "视频资料", status: "excluded", reason: "视频资料登记需要原任务。" }], excluded_count: 1, unresolved: [], message: "所选快照已核对。",
  });
  let browser, page;
  async function screenshot(name) {
    await page.locator("#materialCatalogRecovery").scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(out, name), animations: "disabled", fullPage: true });
    report.screenshots.push(name);
  }
  async function openStorage() {
    await page.locator("#settings").click();
    await page.locator('[data-settings-section="storage"]').click();
    const details = page.locator('#settingsDialog [data-settings-page="storage"] details');
    if (!(await details.evaluate(element => element.open))) await details.locator("summary").click();
    await page.locator("#storageTools").click();
    await page.locator("#materialCatalogSnapshot").waitFor();
    await page.waitForFunction(() => !document.querySelector("#materialCatalogCheck").disabled);
  }
  async function choose(name) {
    await page.locator("#materialCatalogSnapshot").setInputFiles(files.get(name));
  }
  async function runPreview(name) {
    await choose(name); await page.locator("#materialCatalogPreview").click();
    await page.waitForFunction(() => !document.querySelector("#materialCatalogPreview").disabled);
  }
  function hold(name, phase) {
    const started = deferred(), released = deferred(), finished = deferred();
    const value = { started, released, finished };
    holds.set(`${phase}:${name}`, value); return value;
  }
  try {
    browser = await chromium.launch({ channel: "msedge", headless: true });
    report.browser_version = browser.version();
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce", serviceWorkers: "block" });
    context.on("page", p => { p.on("pageerror", error => report.errors.push(error.message)); });
    await context.routeWebSocket("**/*", socket => { report.unexpected_requests.push(`WebSocket ${socket.url()}`); socket.close(); });
    await context.route("**/*", async route => {
      const request = route.request(), url = new URL(request.url()), p = url.pathname, method = request.method();
      const json = (value, status = 200) => route.fulfill({ status, json: value });
      let held;
      try {
        assert.equal(url.origin, base.origin, "External request blocked");
        if (p === "/" || p.startsWith("/web/")) {
          assert.equal(method, "GET");
          const target = path.resolve(root, p === "/" ? "web/index.html" : decodeURIComponent(p.slice(1)));
          assert(target.startsWith(path.join(root, "web") + path.sep));
          assert(fs.statSync(target).isFile());
          return await route.fulfill({ body: fs.readFileSync(target), contentType: ({ ".html": "text/html", ".js": "application/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2" })[path.extname(target)] || "application/octet-stream" });
        }
        if (p === "/health" && method === "GET") return await json({ ok: true, service: "learnnote", app_version: "0.2.14", protocol_version: 1, llm_model_configured: false, model_provider_presets: [], assistant_capabilities: {} });
        if (p === "/api/tasks" && method === "GET") return await json({ tasks: [] });
        if (p === "/api/library/materials" && method === "GET") return await json({ materials: restored ? [material] : [] });
        if (p === "/api/preferences" && method === "GET") return await json({ task_options: { transcriber: "none", note_style: "study", note_template: "standard", summary_depth: "standard", local_ocr: false } });
        if (p === "/api/model/connection" && method === "GET") return await json({ model: null, configured: false });
        if (p === "/api/model/route" && method === "GET") return await json({ routes: [], blocking_reasons: [], data_leaving_device: [], offline_source_confirmed: true });
        if (p === "/api/connections" && method === "GET") return await json({ openrouter: { connected: false } });
        if (p === "/api/assistant/skills" && method === "GET") return await json({ skills: [], features: [] });
        if (p === "/api/assistant/history" && method === "GET") return await json({ items: [] });
        if (p === "/api/update/status" && method === "GET") return await json({ ok: true, status: "up_to_date", preferences: { auto_check: false, auto_download: false } });
        if (p === "/api/storage" && method === "GET") return await json({ data_dir: "Synthetic fixture only", upload_policy: {} });
        if (p === "/api/support/activation" && method === "GET") return await json({ enabled: false });
        if (p === "/api/support/preview" && method === "POST") return await json({ enabled: false, milestones: {}, error_categories: [] });
        if (p === "/api/library/rebuild" && method === "POST") {
          assert.equal(request.postData(), null, "Task rebuild cannot upload the selected document snapshot");
          const outcome = rebuildOutcome; report.task_rebuilds.push(outcome);
          held = holds.get("rebuild:tasks");
          if (held) { held.started.resolve(); await held.released.promise; }
          catalogState = outcome === "partial" ? "incomplete" : outcome === "blocked" ? "corrupt" : "healthy";
          return await json({ status: outcome, indexed: outcome === "blocked" ? 0 : 2, skipped: 0, catalog: { state: catalogState, recovery_required: catalogState !== "healthy" }, code: outcome === "blocked" ? "catalog_recovery_required" : undefined });
        }
        if (p === "/api/library/catalog/status" && method === "GET") return await json(statusFails ? { detail: { code: "catalog_status_failed", message: "模拟目录读取失败" } } : { state: catalogState, recovery_required: catalogState !== "healthy", orphaned_material_ids: catalogState === "healthy" ? [] : [material.material_id], message: "请从明确选择的快照恢复目录。" }, statusFails ? 503 : 200);
        if (["/api/library/catalog/recovery/preview", "/api/library/catalog/recovery/apply"].includes(p)) {
          assert.equal(method, "POST");
          const parsed = await new Request("http://fixture.invalid/", { method: "POST", headers: { "Content-Type": request.headers()["content-type"] }, body: request.postDataBuffer() }).formData();
          const uploaded = parsed.get("file"), file = files.get(uploaded?.name);
          assert(file, "Snapshot must be an explicitly selected synthetic file");
          assert(Buffer.from(await uploaded.arrayBuffer()).equals(file.buffer), "Snapshot bytes must remain unchanged");
          const phase = p.endsWith("/preview") ? "preview" : "apply";
          report[phase === "preview" ? "previews" : "applies"].push(file.name);
          held = holds.get(`${phase}:${file.name}`);
          if (held) { held.started.resolve(); await held.released.promise; }
          if (phase === "preview") {
            assert.equal(parsed.get("preview_token"), null);
            if (file.name === "invalid.sqlite3") return await json({ detail: { code: "catalog_snapshot_invalid", message: "所选快照不是有效的 SQLite 数据库。" } }, 400);
            const value = preview(file);
            if (file.name === "empty.sqlite3") Object.assign(value, { can_apply: false, recoverable_count: 0, materials: [], message: "快照没有可恢复资料。" });
            if (file.name === "unresolved.sqlite3") Object.assign(value, { can_apply: false, unresolved: [{ material_id: "missing-original", reason: "本机原文件缺失，无法恢复。" }], materials: [...value.materials, { material_id: "conflicting-id", title: "编码冲突资料", status: "unresolved", reason: "所选快照中的编码元数据冲突。" }] });
            return await json(value);
          }
          assert.equal(parsed.get("preview_token"), preview(file).preview_token, "Apply must match the selected snapshot preview");
          if (file.name === "stale.sqlite3") return await json({ detail: { code: "catalog_changed_preview_again", message: "预览后目录已变化，请重新预览。" } }, 409);
          restored = true; catalogState = file.name === "partial.sqlite3" ? "incomplete" : "healthy";
          return await json({ status: file.name === "partial.sqlite3" ? "partial" : "pass", restored_material_count: 1, restored_evidence_count: 2, rollback_snapshot_created: true, rollback_directory: "catalog-recovery-0123456789abcdef", unresolved: file.name === "partial.sqlite3" ? [{ material_id: "late-missing", reason: "原文件在预览后丢失。" }] : [], message: "已保留原资料编号和编码选择。" });
        }
        throw new Error(`Unexpected request: ${method} ${p}`);
      } catch (error) {
        report.unexpected_requests.push(`${method} ${p}: ${error.message}`);
        await route.abort("blockedbyclient").catch(() => {});
      } finally { held?.finished.resolve(); }
    });
    page = await context.newPage(); page.setDefaultTimeout(15000);
    await page.goto(base.href, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => document.querySelector("#welcome")?.dataset.ready === "true");
    assert.match(await page.title(), /LearnNote/);
    await openStorage();
    assert.match(await page.locator("#materialCatalogStatus").innerText(), /目录：缺失/);
    assert.equal(await page.locator("#materialCatalogSnapshot").inputValue(), "");
    assert(await page.locator("#materialCatalogApply").isDisabled());
    assert(await page.locator("#materialCatalogPreview").isDisabled());
    assert.equal(report.previews.length, 0); assert.equal(report.applies.length, 0);
    assert.equal(await page.locator("#restoreForm").count(), 1, "Task-only restore remains available separately");
    report.checks.push("Explicit file selection; opening checks status only; task restore preserved");

    for (const [state, label] of [["corrupt", "损坏"], ["incomplete", "不完整"], ["healthy", "正常"]]) {
      catalogState = state; await page.locator("#materialCatalogCheck").click();
      await page.waitForFunction(label => document.querySelector("#materialCatalogStatus").textContent.includes(`目录：${label}`), label);
    }
    statusFails = true; await page.locator("#materialCatalogCheck").click();
    await page.waitForFunction(() => document.querySelector("#materialCatalogStatus").textContent.includes("catalog_status_failed"));
    statusFails = false; catalogState = "missing"; await page.locator("#materialCatalogCheck").click();
    await page.waitForFunction(() => document.querySelector("#materialCatalogStatus").textContent.includes("目录：缺失"));
    report.checks.push("Missing, corrupt, incomplete, healthy and retryable status errors");

    await runPreview("chosen.sqlite3");
    const selectedBeforeRebuild = await page.locator("#materialCatalogSnapshot").inputValue();
    const heldRebuild = hold("tasks", "rebuild");
    await page.locator("#materialCatalogRebuildTasks").evaluate(button => { button.click(); button.click(); });
    await waitForFixture(heldRebuild.started.promise);
    assert(await page.locator("#materialCatalogPreview").isDisabled());
    assert(await page.locator("#materialCatalogApply").isDisabled());
    assert(await page.locator("#materialCatalogSnapshot").isDisabled());
    heldRebuild.released.resolve(); await waitForFixture(heldRebuild.finished.promise); holds.delete("rebuild:tasks");
    await page.waitForFunction(() => !document.querySelector("#materialCatalogRebuildTasks").disabled);
    assert.deepEqual(report.task_rebuilds, ["partial"]);
    assert.match(await page.locator("#materialCatalogProgress").innerText(), /仅部分完成，文档目录仍未恢复/);
    assert.match(await page.locator("#materialCatalogProgress").innerText(), /选择已有 SQLite 快照预览并恢复文档目录/);
    assert.match(await page.locator("#materialCatalogStatus").innerText(), /目录：不完整/);
    assert.equal(await page.locator("#materialCatalogSnapshot").inputValue(), selectedBeforeRebuild);
    assert.equal(await page.locator("#materialCatalogResults").innerText(), "");
    assert(await page.locator("#materialCatalogApply").isDisabled());
    assert.equal(report.applies.length, 0);
    await screenshot("task-rebuild-partial-desktop.png");
    rebuildOutcome = "blocked"; await runPreview("chosen.sqlite3"); await page.locator("#materialCatalogRebuildTasks").click();
    await page.waitForFunction(() => !document.querySelector("#materialCatalogRebuildTasks").disabled);
    assert.match(await page.locator("#materialCatalogProgress").innerText(), /重建受阻，文档目录未恢复/);
    assert.doesNotMatch(await page.locator("#materialCatalogProgress").innerText(), /恢复完成/);
    assert.match(await page.locator("#materialCatalogStatus").innerText(), /目录：损坏/);
    assert(await page.locator("#materialCatalogApply").isDisabled());
    assert.equal(await page.locator("#materialCatalogResults").innerText(), "");
    await screenshot("task-rebuild-blocked-desktop.png");
    report.checks.push("Task rebuild partial/blocked outcomes explain remaining document recovery, invalidate preview, preserve selection and prevent double submission");

    await runPreview("unresolved.sqlite3");
    assert(await page.locator("#materialCatalogApply").isDisabled());
    assert.match(await page.locator("#materialCatalogResults").innerText(), /编码元数据冲突/);
    assert.match(await page.locator("#materialCatalogResults").innerText(), /本机原文件缺失/);
    await screenshot("catalog-unresolved-desktop.png");
    await runPreview("empty.sqlite3"); assert(await page.locator("#materialCatalogApply").isDisabled());
    await runPreview("invalid.sqlite3"); assert.match(await page.locator("#materialCatalogProgress").innerText(), /catalog_snapshot_invalid/);
    assert.equal(report.applies.length, 0);
    report.checks.push("Unresolved item reasons, empty snapshots and structured invalid-snapshot errors forbid apply");

    const heldPreview = hold("held.sqlite3", "preview");
    await choose("held.sqlite3"); await page.locator("#materialCatalogPreview").click(); await waitForFixture(heldPreview.started.promise);
    assert(await page.locator("#materialCatalogRebuildTasks").isDisabled());
    await runPreview("other.sqlite3");
    const latest = await page.locator("#materialCatalogResults").innerText();
    heldPreview.released.resolve(); await waitForFixture(heldPreview.finished.promise);
    await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
    assert.equal(await page.locator("#materialCatalogResults").innerText(), latest);
    await choose("chosen.sqlite3"); assert(await page.locator("#materialCatalogApply").isDisabled());
    assert.equal(await page.locator("#materialCatalogResults").innerText(), "");
    report.checks.push("Reselection invalidates eligibility and ignores late preview responses");

    await runPreview("stale.sqlite3"); await page.locator("#materialCatalogApply").click();
    await page.waitForFunction(() => document.querySelector("#materialCatalogProgress").textContent.includes("catalog_changed_preview_again"));
    assert(await page.locator("#materialCatalogApply").isDisabled());
    assert.equal(await page.locator("#materialCatalogResults").innerText(), "");
    report.checks.push("Stale apply failure requires a fresh preview");

    await runPreview("chosen.sqlite3");
    assert.match(await page.locator("#materialCatalogResults").innerText(), /视频资料 · 不在恢复范围/);
    await screenshot("catalog-preview-desktop.png");
    const heldApply = hold("chosen.sqlite3", "apply"), beforeApply = report.applies.length;
    await page.locator("#materialCatalogApply").evaluate(button => { button.click(); button.click(); });
    await waitForFixture(heldApply.started.promise);
    assert(await page.locator("#materialCatalogSnapshot").isDisabled());
    assert(await page.locator("#materialCatalogRebuildTasks").isDisabled());
    heldApply.released.resolve(); await waitForFixture(heldApply.finished.promise);
    await page.waitForFunction(() => document.querySelector("#materialCatalogProgress").textContent.includes("恢复完成：1 份资料，2 条出处"));
    await page.waitForSelector('#notes [data-id="original-material-id"]');
    assert.equal(report.applies.length, beforeApply + 1);
    assert.match(await page.locator("#materialCatalogStatus").innerText(), /目录：正常/);
    assert.match(await page.locator("#materialCatalogResults").innerText(), /数据文件夹\/exports\/catalog-recovery-0123456789abcdef/);
    assert.equal(await page.locator("#materialCatalogResults a").count(), 0);
    assert(await page.locator("#materialCatalogApply").isDisabled());
    await screenshot("catalog-recovered-desktop.png");
    report.checks.push("Explicit apply preserves file/token; double-click sends once; rollback, healthy status and refreshed material list");

    const closedPreview = hold("held.sqlite3", "preview");
    await choose("held.sqlite3"); await page.locator("#materialCatalogPreview").click(); await waitForFixture(closedPreview.started.promise);
    await page.locator("#toolsDialog [data-close-tool]").click(); await openStorage();
    closedPreview.released.resolve(); await waitForFixture(closedPreview.finished.promise);
    await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
    assert.equal(await page.locator("#materialCatalogResults").innerText(), "");
    assert(await page.locator("#materialCatalogApply").isDisabled());
    report.checks.push("Closing and reopening cannot adopt an old preview");

    const closedRebuild = hold("tasks", "rebuild");
    await page.locator("#materialCatalogRebuildTasks").click(); await waitForFixture(closedRebuild.started.promise);
    await page.locator("#toolsDialog [data-close-tool]").click(); await openStorage();
    const freshProgress = await page.locator("#materialCatalogProgress").innerText();
    closedRebuild.released.resolve(); await waitForFixture(closedRebuild.finished.promise); holds.delete("rebuild:tasks");
    await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
    assert.equal(await page.locator("#materialCatalogProgress").innerText(), freshProgress);
    assert.equal(await page.locator("#materialCatalogResults").innerText(), "");
    report.checks.push("A late task rebuild cannot change the reopened recovery panel");

    await page.setViewportSize({ width: 390, height: 844 });
    await runPreview("partial.sqlite3"); await page.locator("#materialCatalogApply").click();
    await page.waitForFunction(() => document.querySelector("#materialCatalogProgress").textContent.includes("部分恢复完成"));
    assert.match(await page.locator("#materialCatalogResults").innerText(), /原文件在预览后丢失/);
    await screenshot("catalog-partial-mobile.png");
    assert(await page.locator("#toolsDialog").evaluate(element => element.scrollWidth <= element.clientWidth + 2), "Recovery panel must fit mobile dialog width");
    report.checks.push("Partial result retains reasons; narrow viewport remains usable");
    assert.deepEqual(report.errors, []); assert.deepEqual(report.unexpected_requests, []);
    report.passed = true;
  } finally {
    for (const held of holds.values()) held.released.resolve();
    fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(report, null, 2));
    if (browser) await browser.close();
  }
  process.stdout.write(JSON.stringify(report) + "\n");
}
if (process.argv.includes("--self-test")) {
  assert.equal(fixture("test.sqlite3").buffer.subarray(0, 16).toString(), "SQLite format 3\0");
  console.log("Catalog recovery Edge fixture loaded; browser run requires an authorized Edge environment.");
} else main().catch(error => { console.error(error); process.exitCode = 1; });
