// Windows Edge acceptance for the default reader's local batch importer.
// Every HTTP response, including app assets, comes from this fixture. No backend,
// external media, model provider, or genuine user file is contacted or uploaded.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const { createHash } = require("node:crypto");

const MiB = 1024 ** 2;
const GiB = 1024 ** 3;
const root = path.resolve(__dirname, "..");
const sha256 = bytes => createHash("sha256").update(bytes).digest("hex");
const canonical = value => Array.isArray(value) ? value.map(canonical)
  : value && typeof value === "object" ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;
const videoKey = upload => {
  // Match the local-task dedup boundary: bytes plus processing options, while
  // credentials do not create a different processing result.
  const { llm_api_key, ...options } = upload.options || {};
  return `${sha256(upload.bytes)}:${JSON.stringify(canonical(options))}`;
};
const fixtureFile = (name, text = `Synthetic fixture: ${name}\n`) => ({
  name,
  mimeType: name.endsWith(".mp4") ? "video/mp4" : "text/plain",
  buffer: Buffer.isBuffer(text) ? text : Buffer.from(text),
});
async function waitForFixture(promise, label) {
  let timer;
  try {
    await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`Timed out waiting for ${label}`)), 15000);
    })]);
  } finally { clearTimeout(timer); }
}

// Node's multipart parser preserves binary bytes and Unicode filenames; avoid
// string-splitting multipart bodies or substituting browser-decoded document text.
async function multipart(request) {
  assert.equal(request.method(), "POST");
  const body = request.postDataBuffer();
  assert(body, "File submission must have a request body");
  const parsed = await new Request("http://fixture.invalid/", {
    method: "POST",
    headers: { "Content-Type": request.headers()["content-type"] },
    body,
  }).formData();
  const file = parsed.get("file");
  assert(file && typeof file.arrayBuffer === "function", "Submit an actual file");
  return {
    name: file.name,
    bytes: Buffer.from(await file.arrayBuffer()),
    encoding: parsed.get("encoding"),
    options: parsed.has("options") ? JSON.parse(parsed.get("options")) : null,
  };
}

(async () => {
  const base = new URL(process.argv[2] || "http://127.0.0.1:18930");
  assert(["127.0.0.1", "localhost", "[::1]"].includes(base.hostname));
  assert.equal(base.protocol, "http:");
  const out = process.argv[3] || fs.mkdtempSync(path.join(os.tmpdir(), "learnnote-material-batch-"));
  fs.mkdirSync(out, { recursive: true });
  const report = { passed: false, browser: "Microsoft Edge", checks: [], screenshots: [], requests: [], errors: [], unexpectedRequests: [] };
  let browser, page;
  const holds = new Map();
  const expectedFiles = new Map();
  const previews = [];
  const imports = [];
  const videos = [];
  const materials = new Map();
  const materialsByHash = new Map();
  const materialContents = new Map();
  const tasks = new Map();
  const tasksByFingerprint = new Map();
  const importedByName = new Map();
  const attempts = new Map();
  const previewAttempts = new Map();
  const health = {
    ok: true, service: "learnnote", app_version: "0.2.14", backend_version: "0.2.14",
    protocol_version: 1, llm_model_configured: false, local_asr_available: false,
    default_llm_model: "", model_provider_presets: [], assistant_capabilities: {},
    upload_policy: { schema_version: 1, max_video_bytes: 4 * GiB, max_concurrent_upload_bytes: 4 * GiB, min_free_bytes: 0 },
  };
  function register(...files) {
    for (const file of files) {
      if (!expectedFiles.has(file.name)) expectedFiles.set(file.name, []);
      expectedFiles.get(file.name).push(file.buffer);
    }
    return files;
  }
  function hold(endpoint, name) {
    let release, started, finished;
    const entry = {
      key: `${endpoint}:${name}`,
      released: new Promise(resolve => { release = resolve; }),
      started: new Promise(resolve => { started = resolve; }),
      finished: new Promise(resolve => { finished = resolve; }),
      release, markStarted: started, markFinished: finished,
    };
    holds.set(entry.key, entry);
    return entry;
  }
  function held(endpoint, name) {
    const entry = holds.get(`${endpoint}:${name}`);
    if (!entry) return;
    entry.markStarted();
    return entry;
  }
  function material(upload) {
    const digest = sha256(upload.bytes);
    const existing = materialsByHash.get(digest);
    if (existing) {
      importedByName.set(upload.name, existing);
      return { ...existing, deduplicated: true };
    }
    const suffix = path.extname(upload.name).toLowerCase();
    const sourceType = ({ ".txt": "text", ".md": "markdown", ".markdown": "markdown", ".html": "html", ".htm": "html", ".pdf": "pdf" })[suffix];
    const value = {
      material_id: `material-${materials.size + 1}`, schema_version: 1, title: upload.name,
      filename: upload.name, source_type: sourceType, stored_locally: true,
      content_type: sourceType === "pdf" ? "application/pdf" : "text/plain",
      source_uri: "", sha256: digest, byte_size: upload.bytes.length,
      status: "ready", linked_task_id: "", anchor_count: 0, evidence_ids: [], owns_evidence: false,
      created_at: "2026-09-25T10:00:00Z", updated_at: "2026-09-25T10:00:00Z",
      metadata: { original_filename: upload.name, raw_sha256: digest, raw_file_saved: true, encoding: sourceType === "pdf" ? "" : upload.encoding || "utf-8", encoding_source: sourceType === "pdf" ? "pypdf" : "user-selected", encoding_confidence: "high" },
      deduplicated: false,
    };
    materials.set(value.material_id, value);
    materialsByHash.set(digest, value);
    materialContents.set(value.material_id, sourceType === "pdf" ? "Synthetic PDF original text." : new TextDecoder(upload.encoding || "utf-8").decode(upload.bytes));
    importedByName.set(upload.name, value);
    return value;
  }
  async function screenshot(name) {
    await page.screenshot({ path: path.join(out, name), animations: "disabled", fullPage: true });
    report.screenshots.push(name);
  }
  async function openFiles() {
    if (!(await page.locator("#createDialog").evaluate(el => el.open))) await page.locator("#newNote").click();
    await page.locator('[data-input="file"]').click();
    await page.waitForFunction(() => !document.querySelector("#file").disabled);
  }
  async function close() {
    await page.locator("#createDialog [data-close]").click();
    await page.waitForFunction(() => !document.querySelector("#createDialog").open);
  }
  async function statuses(expected) {
    await page.waitForFunction(expected => {
      const rows = [...document.querySelectorAll("#materialBatchItems > li")];
      return rows.length === expected.length && rows.every((row, i) => expected[i].split("|").includes(row.dataset.status));
    }, expected);
    await noPendingWork();
  }
  const rowNames = () => page.locator("#materialBatchItems > li").allTextContents();
  async function choose(files) {
    await page.waitForFunction(() => !document.querySelector("#file").disabled);
    register(...files);
    await page.locator("#file").setInputFiles(files);
  }
  const count = (rows, name) => rows.filter(row => row.name === name).length;
  async function noPendingWork() {
    await page.waitForFunction(() => !document.querySelector("#file").disabled
      && document.querySelector("#materialBatchCancel").hidden
      && !document.querySelector('#materialBatchItems > li:is([data-status="preflighting"], [data-status="submitting"])'));
    // Allow promise continuations and one render to expose an accidentally sent
    // next file; deferred responses, rather than timing delays, drive each race.
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  }
  try {
    browser = await chromium.launch({ channel: "msedge", headless: true });
    const context = await browser.newContext({ viewport: { width: 1536, height: 1024 }, reducedMotion: "reduce", serviceWorkers: "block" });
    context.on("page", p => p.on("pageerror", e => report.errors.push(e.message)));
    await context.routeWebSocket("**/*", socket => {
      report.unexpectedRequests.push(`WebSocket ${socket.url()}`);
      socket.close();
    });
    await context.route("**/*", async route => {
      const request = route.request();
      const url = new URL(request.url());
      const pathname = url.pathname;
      const json = (value, status = 200) => route.fulfill({ status, json: value });
      let activeHold;
      try {
        if (url.origin !== base.origin) {
          report.unexpectedRequests.push(`${request.method()} ${url.origin}${pathname}`);
          return route.abort("blockedbyclient");
        }
        if (pathname === "/" || pathname.startsWith("/web/")) {
          assert.equal(request.method(), "GET");
          const relative = pathname === "/" ? "web/index.html" : decodeURIComponent(pathname.slice(1));
          const target = path.resolve(root, relative);
          assert(target.startsWith(path.join(root, "web") + path.sep));
          assert(fs.statSync(target).isFile(), `Missing fixture asset: ${relative}`);
          const contentType = { ".html": "text/html", ".js": "application/javascript", ".css": "text/css", ".png": "image/png", ".svg": "image/svg+xml", ".woff2": "font/woff2" }[path.extname(target)] || "application/octet-stream";
          return route.fulfill({ body: fs.readFileSync(target), contentType });
        }
        report.requests.push(`${request.method()} ${pathname}`);
        if (pathname === "/health") return json(health);
        if (pathname === "/api/tasks" && request.method() === "GET") return json({ tasks: [...tasks.values()] });
        if (pathname === "/api/library/materials" && request.method() === "GET") return json({ materials: [...materials.values()] });
        if (pathname === "/api/preferences" && request.method() === "GET") return json({ task_options: { transcriber: "none", note_style: "study", note_template: "standard", summary_depth: "standard", local_ocr: false } });
        if (pathname === "/api/model/connection" && request.method() === "GET") return json({ model: null, configured: false });
        if (pathname === "/api/model/route" && request.method() === "GET") return json({ routes: [], blocking_reasons: [], data_leaving_device: [], offline_source_confirmed: true });
        if (pathname === "/api/connections" && request.method() === "GET") return json({ openrouter: { connected: false } });
        if (pathname === "/api/assistant/skills" && request.method() === "GET") return json({ skills: [], features: [] });
        if (pathname === "/api/assistant/history" && request.method() === "GET") return json({ items: [] });
        if (pathname === "/api/update/status" && request.method() === "GET") return json({ status: "up_to_date", preferences: { auto_check: false, auto_download: false } });
        if (pathname === "/api/study/activity" && request.method() === "POST") return json({ ok: true });
        if (/^\/api\/personal\/(material|task)\/[^/]+$/.test(pathname) && request.method() === "GET") return json({ annotations: [] });
        const materialRead = pathname.match(/^\/api\/library\/materials\/([^/]+)(?:\/(content|anchors))?$/);
        if (materialRead && request.method() === "GET") {
          const id = decodeURIComponent(materialRead[1]);
          assert(materials.has(id), `Unknown fixture material: ${id}`);
          if (materialRead[2] === "content") return json({ material_id: id, text: materialContents.get(id) });
          if (materialRead[2] === "anchors") return json({ anchors: [] });
          return json({ material: materials.get(id) });
        }
        const edition = pathname.match(/^\/api\/tasks\/editions\/(material|task)\/([^/]+)$/);
        if (edition && request.method() === "GET") {
          const item = (edition[1] === "material" ? materials : tasks).get(decodeURIComponent(edition[2]));
          assert(item, `Unknown fixture edition: ${pathname}`);
          return json({ text: `# ${item.title}\n\nSynthetic local material, preserved for reading.`, revision: "fixture", edited: false });
        }
        const task = pathname.match(/^\/api\/tasks\/([^/]+)$/);
        if (task && request.method() === "GET" && tasks.has(task[1])) return json({ task: tasks.get(task[1]) });
        if (/^\/api\/tasks\/[^/]+\/events$/.test(pathname) && request.method() === "GET") return json({ events: [] });
        if (/^\/api\/tasks\/[^/]+\/transcript$/.test(pathname) && request.method() === "GET") return json({ segments: [] });
        if (["/api/library/materials/preview", "/api/library/materials/import", "/api/tasks/from-local"].includes(pathname)) {
          const upload = await multipart(request);
          assert(expectedFiles.has(upload.name), `Unexpected file: ${upload.name}`);
          assert(expectedFiles.get(upload.name).some(bytes => upload.bytes.equals(bytes)), `Preserve raw bytes: ${upload.name}`);
          const record = { name: upload.name, bytes: upload.bytes.length, sha256: sha256(upload.bytes), encoding: upload.encoding, options: upload.options };
          if (pathname.endsWith("/preview")) {
            previews.push(record);
            const attempt = (previewAttempts.get(upload.name) || 0) + 1;
            previewAttempts.set(upload.name, attempt);
            activeHold = held("preview", upload.name);
            await activeHold?.released;
            if (upload.name === "preview-retry.txt" && attempt === 1) return await json({ detail: "Synthetic preflight unavailable; retry this file." }, 503);
            return await json({ schema_version: 1, filename: upload.name, byte_size: upload.bytes.length, estimated_storage_bytes: upload.bytes.length * 3, page_count: upload.name.endsWith(".pdf") ? 1 : null, source_type: path.extname(upload.name).slice(1), encoding: upload.encoding || "utf-8", route: "local_text_extraction", ocr_required: false, preview: "Synthetic preview", saved: false, external_transmission: false });
          }
          if (pathname.endsWith("/import")) {
            imports.push(record);
            const attempt = (attempts.get(upload.name) || 0) + 1;
            attempts.set(upload.name, attempt);
            activeHold = held("import", upload.name);
            await activeHold?.released;
            if (upload.name === "retry.txt" && attempt === 1) return await json({ detail: "Synthetic temporary upload failure." }, 503);
            const result = material(upload);
            record.material_id = result.material_id;
            record.deduplicated = result.deduplicated;
            return await json({ material: result });
          }
          videos.push(record);
          activeHold = held("video", upload.name);
          await activeHold?.released;
          const fingerprint = videoKey(upload);
          const deduplicated = tasksByFingerprint.has(fingerprint);
          const task = tasksByFingerprint.get(fingerprint) || { id: `video-${tasks.size + 1}`, title: upload.name, status: "success", phase: "completed", source_type: "local", mode: "local", summary_source: "subtitle-extract", options: upload.options, source_identity: { media_sha256: record.sha256 }, media_integrity: { sha256: record.sha256 }, created_at: "2026-09-25T10:00:00Z", updated_at: "2026-09-25T10:00:00Z" };
          tasksByFingerprint.set(fingerprint, task);
          tasks.set(task.id, task);
          record.task_id = task.id;
          record.deduplicated = deduplicated;
          return await json({ task_id: task.id, task, deduplicated });
        }
        report.unexpectedRequests.push(`${request.method()} ${pathname}`);
        return json({ detail: `Unexpected fixture request: ${pathname}` }, 501);
      } catch (error) {
        // Closing/replacing a batch may abort the held fetch. Its late fixture
        // response is deliberately harmless; assertions still guard the UI.
        if (request.failure()?.errorText === "net::ERR_ABORTED" || /route is already handled|Target page, context or browser has been closed/.test(error.message)) return;
        report.errors.push(`Fixture route: ${error.message}`);
        await route.abort("failed").catch(() => {});
      } finally {
        if (activeHold) {
          holds.delete(activeHold.key);
          activeHold.markFinished();
        }
      }
    });
    page = await context.newPage();
    page.setDefaultTimeout(15000);
    page.on("dialog", dialog => dialog.dismiss());
    await page.goto(base.href);
    await page.locator('#welcome[data-ready="true"]').waitFor();
    await openFiles();
    assert.equal(await page.locator("#file").getAttribute("multiple"), "");
    assert.equal(await page.locator("#materialBatchSummary").getAttribute("role"), "status");

    // Independent success/failure outcomes and a deduplicated server result.
    const existingFile = fixtureFile("already-imported.pdf", "%PDF-1.4\nSynthetic fixture only\n%%EOF\n");
    const existingId = material({ name: "original-existing.pdf", bytes: existingFile.buffer, encoding: "" }).material_id;
    await choose([fixtureFile("第一份资料.md", "# 原始字节\n\n保留 UTF-8。\n"), fixtureFile("retry.txt"), existingFile]);
    await statuses(["ready", "ready", "ready"]);
    await page.locator("#materialEncoding").selectOption("utf-8");
    await statuses(["ready", "ready", "ready"]);
    await screenshot("01-preflight-desktop.png");
    await page.locator("#createSubmit").click();
    await statuses(["success", "failed", "success"]);
    assert(await page.locator("#createDialog").evaluate(el => el.open), "Multi-file imports remain reviewable");
    assert.equal(await page.locator("[data-batch-open]").count(), 2);
    assert.match(await page.locator("#materialBatchSummary").innerText(), /2\s*\/\s*3/);
    assert.equal(await page.locator('#materialBatchItems > li[data-status="failed"]').count(), 1);
    await screenshot("02-partial-success.png");
    await page.locator("#createSubmit").click();
    await statuses(["success", "success", "success"]);
    assert.deepEqual(imports.map(row => row.name), ["第一份资料.md", "retry.txt", "already-imported.pdf", "retry.txt"]);
    assert(imports.every(row => row.encoding === (row.name.endsWith(".pdf") ? "" : "utf-8")));
    assert.equal(materials.size, 3, "Deduplicated results reuse the returned material identity");
    assert.equal(importedByName.get(existingFile.name).material_id, existingId);
    assert.equal(imports.find(row => row.name === existingFile.name).deduplicated, true);
    await page.locator('[data-batch-open="2"]').click();
    await page.waitForFunction(() => location.hash.startsWith("#material/"));
    assert.match(await page.locator("#breadcrumb").innerText(), /original-existing/);
    report.checks.push("mixed results, deduplicated server result, retry skips known successes, per-item open");
    if (await page.locator("#createDialog").evaluate(el => el.open)) await close();

    // Names and metadata cannot substitute for byte identity: all three files
    // reach the backend, including equal-size files sharing the same filename.
    await openFiles();
    const hashStart = imports.length;
    await choose([fixtureFile("same-name.txt", "Bytes A\n"), fixtureFile("same-name.txt", "Bytes B\n"), fixtureFile("renamed-copy.txt", "Bytes A\n")]);
    await statuses(["ready", "ready", "ready"]);
    await page.locator("#createSubmit").click();
    await statuses(["success", "success", "success"]);
    const hashResults = imports.slice(hashStart);
    assert.equal(hashResults.length, 3);
    assert.notEqual(hashResults[0].sha256, hashResults[1].sha256);
    assert.notEqual(hashResults[0].material_id, hashResults[1].material_id);
    assert.equal(hashResults[0].sha256, hashResults[2].sha256);
    assert.equal(hashResults[0].material_id, hashResults[2].material_id);
    assert.equal(hashResults[2].deduplicated, true);
    report.checks.push("SHA-256 dedup accepts renamed identical bytes and distinguishes equal-size same-name files");
    await close();

    // Preflight retry leaves already validated neighbours alone.
    await openFiles();
    await choose([fixtureFile("preview-retry.txt"), fixtureFile("preview-stable.md")]);
    await statuses(["failed|invalid", "ready"]);
    await page.locator("#materialBatchRetryPreview").click();
    await statuses(["ready", "ready"]);
    assert.equal(count(previews, "preview-retry.txt"), 2);
    assert.equal(count(previews, "preview-stable.md"), 1);
    report.checks.push("retry failed preflight without repeating ready files");
    await close();

    // Use a real DataTransfer drop on the visible drop target, not setInputFiles.
    await openFiles();
    const dropFiles = register(fixtureFile("dropped.md"), fixtureFile("unsupported.exe", "not executable"));
    await page.locator("#fileDrop").evaluate((target, files) => {
      const transfer = new DataTransfer();
      for (const file of files) transfer.items.add(new File([new Uint8Array(file.bytes)], file.name, { type: file.mimeType }));
      target.dispatchEvent(new DragEvent("dragenter", { bubbles: true, cancelable: true, dataTransfer: transfer }));
      target.dispatchEvent(new DragEvent("dragover", { bubbles: true, cancelable: true, dataTransfer: transfer }));
      target.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: transfer }));
    }, dropFiles.map(file => ({ name: file.name, mimeType: file.mimeType, bytes: [...file.buffer] })));
    await statuses(["ready", "invalid"]);
    assert((await rowNames())[0].includes("dropped.md"));
    await page.locator("#createSubmit").click();
    await statuses(["success", "invalid"]);
    assert.equal(count(imports, "dropped.md"), 1);
    assert.equal(count(imports, "unsupported.exe"), 0);
    await page.setViewportSize({ width: 390, height: 844 });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await screenshot("03-drop-mobile.png");
    await page.setViewportSize({ width: 1536, height: 1024 });
    report.checks.push("actual drag/drop, invalid file isolation, narrow-screen layout");
    await close();

    // Cancel after the first request starts but before it returns.
    await openFiles();
    await choose([fixtureFile("cancel-first.md"), fixtureFile("cancel-unsent.md")]);
    await statuses(["ready", "ready"]);
    const cancelHold = hold("import", "cancel-first.md");
    await page.locator("#createSubmit").click();
    await waitForFixture(cancelHold.started, "cancel upload to start");
    await page.locator("#materialBatchCancel").click();
    cancelHold.release();
    await waitForFixture(cancelHold.finished, "cancel upload response");
    await noPendingWork();
    assert.equal(count(imports, "cancel-first.md"), 1);
    assert.equal(count(imports, "cancel-unsent.md"), 0, "Cancellation stops the next upload");
    assert(await page.locator("#createDialog").evaluate(el => el.open));
    await screenshot("04-cancel-unsent.png");
    report.checks.push("cancellation during deferred upload prevents the next file");
    await close();

    // A replaced selection must not be overwritten by an older preflight.
    await openFiles();
    const stalePreview = hold("preview", "stale-preview.md");
    await choose([fixtureFile("stale-preview.md")]);
    await waitForFixture(stalePreview.started, "stale preflight to start");
    await choose([fixtureFile("new-selection.md")]);
    await statuses(["ready"]);
    stalePreview.release();
    await waitForFixture(stalePreview.finished, "stale preflight response");
    await noPendingWork();
    assert((await rowNames())[0].includes("new-selection.md"));
    assert(!(await rowNames()).join(" ").includes("stale-preview.md"));
    report.checks.push("new selection ignores stale preflight completion");
    await close();

    // Closing a single-file import cannot reopen a result. Reopening keeps the
    // already submitted file visible and guards replacement until it settles.
    await openFiles();
    await choose([fixtureFile("dismissed-upload.md")]);
    await statuses(["ready"]);
    const dismissed = hold("import", "dismissed-upload.md");
    const beforeDismissHash = new URL(page.url()).hash;
    await page.locator("#createSubmit").click();
    await waitForFixture(dismissed.started, "dismissed upload to start");
    await close();
    await page.locator("#newNote").click();
    assert(await page.locator("#file").isDisabled());
    assert((await rowNames())[0].includes("dismissed-upload.md"));
    dismissed.release();
    await waitForFixture(dismissed.finished, "dismissed upload response");
    await noPendingWork();
    await page.waitForFunction(() => !document.querySelector("#file").disabled);
    assert(await page.locator("#createDialog").evaluate(el => el.open));
    assert.equal(new URL(page.url()).hash, beforeDismissHash);
    await choose([fixtureFile("after-reopen.md")]);
    await statuses(["ready"]);
    assert((await rowNames())[0].includes("after-reopen.md"));
    assert.equal(count(imports, "after-reopen.md"), 0);
    await screenshot("05-dismiss-and-reopen.png");
    report.checks.push("dismissal and reopen protect new selection and reader navigation");
    await close();

    // Synthetic undecodable media keeps duration unknown. Subtitle selection is
    // snapshotted and sent intact; no model or ASR request is allowed by routing.
    await openFiles();
    const videoBytes = Buffer.from([0, 1, 2, 3, 255]);
    await choose([fixtureFile("unknown-duration.mp4", videoBytes), fixtureFile("renamed-video.mp4", videoBytes), fixtureFile("video-companion.md")]);
    await statuses(["ready", "ready", "ready"]);
    await page.locator('[name="contentMode"][value="subtitles"]').check();
    await page.waitForFunction(() => /时长.*(?:未知|无法|未能|不可|尚未)|(?:未知|无法|未能|不可|尚未).*时长/.test(document.querySelector("#materialBatchItems").textContent));
    const videoText = (await rowNames())[0];
    assert.doesNotMatch(videoText, /NaN|Infinity|\b0:00\b/);
    assert.match(await page.locator("#materialBatchRoute").innerText(), /字幕/);
    await screenshot("06-unknown-duration-subtitles.png");
    await page.locator("#createSubmit").click();
    await statuses(["success", "success", "success"]);
    assert.equal(videos.length, 2);
    for (const video of videos) {
      assert.equal(video.options.content_mode, "subtitles");
      assert.equal(video.options.visual_understanding, false);
      assert.equal(video.options.local_ocr, false);
    }
    assert.equal(videos[0].task_id, videos[1].task_id);
    assert.equal(videos[1].deduplicated, true);
    assert.equal(tasks.size, 1);
    assert.equal(count(previews, "unknown-duration.mp4"), 0);
    assert.equal(count(previews, "renamed-video.mp4"), 0);
    report.checks.push("unknown duration is honest, subtitle-only options survive submission, and duplicate video results are reused");
    await close();

    // Test front-end limits using synthetic File.size metadata. No multi-GiB
    // allocation or upload occurs; real byte-limit enforcement belongs to API tests.
    await openFiles();
    const validationBefore = previews.length + imports.length + videos.length;
    await choose(Array.from({ length: 21 }, (_, i) => fixtureFile(`over-count-${i}.md`)));
    await page.waitForFunction(() => document.querySelector("#createSubmit").disabled);
    assert.match(await page.locator("#fileInput").innerText() + await page.locator("#createStatus").innerText(), /20/);
    assert.equal(previews.length + imports.length + videos.length, validationBefore);
    for (const files of [
      [{ name: "oversize-document.txt", size: 32 * MiB + 1 }],
      [{ name: "oversize-video.mp4", size: 4 * GiB + 1 }],
      [{ name: "total-first.mp4", size: 3 * GiB }, { name: "total-second.mp4", size: 3 * GiB }],
    ]) {
      await page.locator("#file").evaluate((input, files) => {
        const transfer = new DataTransfer();
        for (const file of files) transfer.items.add(new File(["synthetic size fixture"], file.name));
        input.files = transfer.files;
        files.forEach((file, i) => Object.defineProperty(input.files[i], "size", { value: file.size }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }, files);
      await page.waitForFunction(() => document.querySelector("#createSubmit").disabled);
      await noPendingWork();
      assert.equal(previews.length + imports.length + videos.length, validationBefore);
    }
    await screenshot("07-batch-limits.png");
    report.checks.push("20-file, 32-MiB document, default video, and 4-GiB total guards (synthetic size metadata)");
    await close();

    // A server-advertised lower video limit must win over the 4-GiB default.
    health.upload_policy.max_video_bytes = 2 * MiB;
    await page.goto(base.href);
    await page.locator('#welcome[data-ready="true"]').waitFor();
    await openFiles();
    await page.locator("#file").evaluate(input => {
      const transfer = new DataTransfer();
      transfer.items.add(new File(["synthetic policy fixture"], "server-limit.mp4"));
      input.files = transfer.files;
      Object.defineProperty(input.files[0], "size", { value: 2 * 1024 ** 2 + 1 });
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await statuses(["invalid"]);
    assert(await page.locator("#createSubmit").isDisabled());
    assert.match((await rowNames())[0], /2\.00 MiB.*上限/);
    assert.equal(previews.length + imports.length + videos.length, validationBefore);
    report.checks.push("health-advertised video limit overrides the default (synthetic size metadata)");
    await close();

    // Single-file compatibility and non-UTF-8 byte preservation.
    await openFiles();
    await choose([fixtureFile("原始编码.txt", Buffer.from([0xd6, 0xd0, 0xce, 0xc4, 0x0d, 0x0a]))]);
    await statuses(["ready"]);
    await page.locator("#materialEncoding").selectOption("gb18030");
    await statuses(["ready"]);
    await page.locator("#createSubmit").click();
    await page.waitForFunction(() => !document.querySelector("#createDialog").open);
    await page.waitForFunction(() => document.querySelector("#breadcrumb").textContent.includes("原始编码.txt"));
    assert.equal(imports.at(-1).encoding, "gb18030");
    await page.waitForFunction(() => document.querySelector("#document").textContent.includes("原始编码"));
    await page.locator("#source").click();
    await page.waitForFunction(() => document.querySelector("#sourceContent").textContent.includes("中文"));
    await screenshot("08-single-file-reader.png");
    report.checks.push("single-file success opens reader/source and preserves selected encoding and raw bytes");
    assert.deepEqual(report.unexpectedRequests, []);
    assert.deepEqual(report.errors, []);
    report.passed = true;
  } catch (error) {
    report.failure = error.stack || String(error);
    if (page && !page.isClosed()) await screenshot("failure.png").catch(() => {});
    throw error;
  } finally {
    for (const entry of holds.values()) entry.release();
    report.previews = previews;
    report.imports = imports;
    report.videos = videos;
    fs.writeFileSync(path.join(out, "result.json"), JSON.stringify(report, null, 2));
    await browser?.close();
    console.log(JSON.stringify({ passed: report.passed, out, checks: report.checks }));
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
