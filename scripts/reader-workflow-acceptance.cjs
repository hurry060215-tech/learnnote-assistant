// Deterministic UI regression: generated summaries, honest progress, and sidebar navigation.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
// Synthetic bound endpoint transport only. The real binding/locking contract is
// covered by backend tests; this scenario executes the shipped reader in Edge.
async function verifyBoundCaptionPreview(browser, baseUrl, out) {
  const base = new URL(baseUrl), id = "bound-caption-ui-fixture", otherId = "bound-caption-other";
  assert(base.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(base.hostname));
  assert(!base.username && !base.password && !base.search && !base.hash && ["/", "/web/index.html"].includes(base.pathname));
  const digest = text => require("node:crypto").createHash("sha256").update(text).digest("hex");
  const stamp = "2026-10-18T04:00:00Z", generation = "a".repeat(64);
  const initial = { id, kind: "task", title: "合成验收：绑定字幕草稿", status: "running", phase: "transcribing",
    control_generation: generation, retry_count: 0, source_identity: {}, source_task_id: "", learning_range: {},
    transcript_path: "transcript.json", note_path: "", summary_source: "", options: {}, created_at: stamp, updated_at: stamp };
  const other = { ...initial, id: otherId, title: "合成验收：另一个位置", status: "success", summary_source: "text-llm" };
  const text = "# 合成验收：绑定字幕草稿\n\n> 字幕摘录草稿；不是模型总结，也不代表事实已核验。\n\n" +
    Array.from({ length: 28 }, (_, i) => `## Reading section ${i + 1}\n\nSynthetic caption paragraph ${i + 1} preserves a readable position and selected prose.\n\n- \`00:${String(i).padStart(2, "0")}\` Synthetic timestamp excerpt.`).join("\n\n");
  const empty = { text: "", revision: digest(""), edited: false }, edition = { text, revision: digest(text), edited: false };
  const envelope = { ...edition, reader_snapshot: { schema_version: 1, task_id: id, control_generation: generation,
    retry_count: 0, attempt_id: "a1b2c3d4e5f6", publication_sequence: 2, body_revision: edition.revision,
    source_revision: "b".repeat(64), task_updated_at: stamp, title: initial.title, status: "running", artifact: "draft.md",
    summary_source: "transcript-draft", summary_generated: false, verified: false, provisional: true } };
  const report = { passed: false, transport: "Synthetic bound endpoint and EventSource; shipped reader/assets in Microsoft Edge",
    backend_binding_proven: false, installed_windows_latency_proven: false, cases: [], pageErrors: [], unexpectedRequests: [], cleanupErrors: [] };
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce", serviceWorkers: "block" });
  let page, task, published, holdSelected, holdSnapshot, holdEdition, selectedHolds = [], listHolds = [], snapshotHolds = [], editionHolds = [];
  let fastReads = 0, sourceReads = 0, reviewReads = 0, closing = false, primaryError;
  const hold = (route, queue, value) => new Promise(resolve => queue.push(async (cancel = false) => {
    try {
      if (cancel) await route.abort("aborted");
      else if (!route.request().failure()) await route.fulfill({ json: typeof value === "function" ? value() : value });
    }
    finally { resolve(); }
  }));
  const release = async queue => { for (const finish of queue.splice(0)) await finish(); };
  try {
    await context.addInitScript(({ id }) => {
      const streams = []; let sequence = 0;
      window.__captionDocumentEvents = 0;
      window.addEventListener("learnnote:document", () => window.__captionDocumentEvents++);
      window.EventSource = class extends EventTarget {
        constructor(value) {
          super(); const url = new URL(value, location.href);
          if (url.origin !== location.origin || url.pathname !== `/api/tasks/${id}/events/stream`
              || [...url.searchParams.keys()].join() !== "after" || !/^\d+$/.test(url.searchParams.get("after")))
            throw new Error("Unexpected caption fixture stream");
          this.closed = false; streams.push(this);
        }
        close() { this.closed = true; }
      };
      window.__emitCaption = name => {
        const active = streams.filter(stream => !stream.closed);
        for (const stream of active) stream.dispatchEvent(new MessageEvent(name, { lastEventId: String(++sequence), data: "{}" }));
        return active.length;
      };
    }, { id });
    await context.routeWebSocket("**/*", socket => { report.unexpectedRequests.push("WebSocket"); socket.close(); });
    await context.route("**/*", async route => {
      const request = route.request(), url = new URL(request.url()), pathname = url.pathname;
      const json = value => route.fulfill({ json: value });
      if (closing) return route.abort("aborted");
      try {
        if (url.origin !== base.origin) { report.unexpectedRequests.push(`External ${url.origin}${pathname}`); return await route.abort("blockedbyclient"); }
        if (request.method() === "GET") {
          if ((pathname === "/" || pathname.startsWith("/web/")) && (!url.search || /^\?v=[A-Za-z0-9-]+$/.test(url.search)
              || (pathname === "/web/learning-spaces.js" && url.search === "?v=0.2.15"))) return await route.continue();
          if (pathname === `/api/tasks/editions/task/${id}`) {
            if (url.search) {
              assert.equal(url.search, `?reader_snapshot=true&expected_generation=${generation}`, "Only the exact bound reader query is allowed");
              fastReads++; return await (holdSnapshot ? hold(route, snapshotHolds, envelope) : json(envelope));
            }
            return await (holdEdition ? hold(route, editionHolds, () => edition) : json(published ? edition : empty));
          }
          if (pathname === `/api/tasks/${id}` && !url.search)
            return await (holdSelected ? hold(route, selectedHolds, () => ({ task })) : json({ task }));
          if (pathname === "/api/model/route" && url.search === "?transcriber=faster-whisper&whisper_model=small&visual_understanding=true")
            return await json({ routes: [], blocking_reasons: [], data_leaving_device: [], offline_source_confirmed: true });
          if (pathname === "/api/library/materials" && url.search === "?limit=1000") return await json({ materials: [] });
          if ([id, otherId].some(value => pathname === `/api/tasks/${value}/events`) && url.search === "?limit=500") return await json({ events: [] });
          if (!url.search) {
            if (pathname === "/api/tasks") return await (holdSelected ? hold(route, listHolds, () => ({ tasks: [task, other] })) : json({ tasks: [task, other] }));
            if (pathname === `/api/tasks/editions/task/${otherId}`) return await json({ text: "# Other route", revision: digest("# Other route"), edited: true });
            if (pathname.endsWith("/personal-review") && [id, otherId].some(value => pathname === `/api/tasks/editions/task/${value}/personal-review`)) {
              reviewReads++; return await json({ status: "unmarked", note_revision: published ? edition.revision : empty.revision,
                review_revision: "0".repeat(64), can_mark: false, source_scope: "reading_only", source_labels: [] });
            }
            if ([id, otherId].some(value => pathname === `/api/personal/task/${value}`)) return await json({ annotations: [] });
            if ([id, otherId].some(value => pathname === `/api/tasks/${value}/qa`) || pathname === "/api/assistant/history") return await json({ items: [] });
            if (["claims", "transcript", "media"].some(value => pathname === `/api/tasks/${id}/${value}`)) {
              sourceReads++; report.unexpectedRequests.push(pathname); return await route.fulfill({ status: 409, json: { detail: "Source access is outside this reader scenario" } });
            }
            const startup = {
              "/health": { ok: true, model_provider_presets: [] }, "/api/model/connection": { model: null, configured: false },
              "/api/connections": { openrouter: { connected: false } }, "/api/assistant/skills": { skills: [], features: [] },
              "/api/preferences": { task_options: { transcriber: "none", whisper_model: "small", content_mode: "text", note_style: "study", note_template: "standard", summary_depth: "standard", local_ocr: false, visual_understanding: false } },
              "/api/update/status": { status: "up_to_date", preferences: { auto_check: false, auto_download: false } },
            };
            if (Object.hasOwn(startup, pathname)) return await json(startup[pathname]);
          }
        }
        if (request.method() === "POST" && pathname === "/api/study/activity" && !url.search) {
          const body = request.postDataJSON(); assert.equal(body.kind, "reading"); assert([`task:${id}`, `task:${otherId}`].includes(body.source_id));
          return await json({ ok: true });
        }
        report.unexpectedRequests.push(`${request.method()} ${pathname}${url.search}`);
        return await route.fulfill({ status: 501, json: { detail: "Unexpected caption fixture request" } });
      } catch (error) { report.unexpectedRequests.push(error.message); await route.abort("failed").catch(() => {}); }
    });
    page = await context.newPage(); page.setDefaultTimeout(15000);
    page.on("pageerror", error => report.pageErrors.push(error.message));
    const settle = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const emit = async name => assert.equal(await page.evaluate(value => window.__emitCaption(value), name), 1);
    async function reset() {
      task = { ...initial }; published = holdSelected = holdSnapshot = holdEdition = false;
      await page.goto("about:blank"); // Force a new document, even when the preceding route has the same fragment.
      await page.goto(`${base.origin}/#task/${id}`, { waitUntil: "domcontentloaded" });
      await page.waitForFunction(id => document.getElementById("document").dataset.readerSource === `task:${id}`, id); await settle();
    }
    async function preview() {
      holdSelected = true;
      const docs = await page.evaluate(() => window.__captionDocumentEvents), sources = sourceReads, reviews = reviewReads;
      await emit("draft_ready");
      await page.waitForFunction(() => document.getElementById("document").textContent.includes("Synthetic caption paragraph 28"));
      assert(selectedHolds.length > 0, "Draft is readable before the selected GET is released");
      assert.equal(await page.evaluate(() => window.__captionDocumentEvents), docs);
      for (const key of ["noteActions", "readerStrip", "annotations", "aiAssistant"])
        assert.equal(await page.locator(`#${key}`).evaluate(node => node.inert), true, key);
      assert.equal(await page.locator("#document .time-link").count(), 0);
      assert.equal(sourceReads, sources); assert.equal(reviewReads, reviews);
      await page.evaluate(() => { document.getElementById("edit").click(); document.getElementById("source").click(); });
      assert.equal(await page.locator("#editor").isVisible(), false); assert.equal(await page.locator("#sourcePanel").isVisible(), false);
      const count = fastReads; for (let i = 0; i < 12; i++) await emit("task_updated"); await settle();
      assert.equal(fastReads, count, "Accepted preview is not refetched during an event burst");
      return docs;
    }
    for (const selection of ["prose", "timestamp"]) {
      await reset(); const docs = await preview();
      if (selection === "prose") await page.screenshot({ path: path.join(out, "bound-caption-preview.png"), animations: "disabled" });
      const before = await page.evaluate(kind => {
        const node = kind === "timestamp" ? document.querySelectorAll("#document code")[12] : document.querySelectorAll("#document p")[12];
        window.__captionAnchor = kind === "timestamp" ? node.parentElement : node;
        node.scrollIntoView({ block: "center" }); const range = document.createRange();
        range.setStart(node.firstChild, 1); range.setEnd(node.firstChild, Math.min(20, node.firstChild.length));
        const selected = getSelection(); selected.removeAllRanges(); selected.addRange(range);
        return { text: String(selected), top: window.__captionAnchor.getBoundingClientRect().top };
      }, selection);
      const emptyRead = page.waitForResponse(response => new URL(response.url()).pathname === `/api/tasks/editions/task/${id}` && !new URL(response.url()).search);
      holdSelected = false; await release(selectedHolds); await release(listHolds); await emptyRead; await settle();
      assert.equal(await page.locator("#noteActions").evaluate(node => node.inert), true, "Exact provisional empty pair remains actionless");
      assert.equal(await page.evaluate(() => window.__captionDocumentEvents), docs);
      task = { ...task, note_path: "draft.md", summary_source: "transcript-draft", updated_at: "2026-10-18T04:00:01Z" }; published = true;
      await emit("task_updated");
      await page.waitForFunction(() => !document.getElementById("noteActions").inert && document.querySelector("#document .time-link")); await settle();
      const after = await page.evaluate(() => ({ connected: window.__captionAnchor.isConnected, text: String(getSelection()),
        top: window.__captionAnchor.getBoundingClientRect().top, docs: window.__captionDocumentEvents }));
      assert(after.connected, "Unchanged source/body retains the anchor node"); assert.equal(after.text, before.text);
      assert(Math.abs(after.top - before.top) < 2, "Unchanged source/body retains the reading position"); assert.equal(after.docs, docs + 1);
      report.cases.push({ name: `same-source-${selection}`, before, after });
      if (selection === "prose") await page.screenshot({ path: path.join(out, "bound-caption-reconciled.png"), animations: "disabled" });
    }
    await reset(); await preview();
    task = { ...task, transcript_path: "enriched-transcript.json", note_path: "draft.md", summary_source: "transcript-draft" };
    holdEdition = true; holdSelected = false; const enrichedRead = page.waitForRequest(request => new URL(request.url()).pathname === `/api/tasks/editions/task/${id}` && !new URL(request.url()).search);
    await release(selectedHolds); await release(listHolds); await enrichedRead;
    await page.waitForFunction(() => document.getElementById("document").textContent.includes("正在同步正文"));
    assert(!(await page.locator("#document").textContent()).includes("Synthetic caption paragraph"), "Changed source retires preview before edition completion");
    await page.screenshot({ path: path.join(out, "bound-caption-source-retired.png"), animations: "disabled" });
    holdEdition = false; await release(editionHolds); await settle(); report.cases.push({ name: "source-enrichment-retired", selection_preservation_claimed: false });
    await reset();
    await page.locator(`#notes [data-id="${otherId}"]`).click(); await page.waitForFunction(() => document.getElementById("document").textContent.includes("Other route"));
    holdEdition = true;
    await page.locator(`#notes [data-id="${id}"]`).click(); await preview();
    report.cases.push({ name: "previous-personal-edition-does-not-block-new-draft" });
    holdEdition = holdSelected = false; await release(editionHolds); await release(selectedHolds); await release(listHolds); await settle();
    await reset(); holdSelected = holdSnapshot = true;
    const fastRequest = page.waitForRequest(request => new URL(request.url()).searchParams.get("reader_snapshot") === "true");
    await emit("draft_ready"); await fastRequest;
    await page.locator(`#notes [data-id="${otherId}"]`).click(); await page.waitForFunction(() => document.getElementById("document").textContent.includes("Other route"));
    await page.locator(`#notes [data-id="${id}"]`).click(); await page.waitForFunction(id => document.getElementById("document").dataset.readerSource === `task:${id}`, id);
    holdSnapshot = holdSelected = false; await release(snapshotHolds); await release(selectedHolds); await release(listHolds); await settle();
    assert(!(await page.locator("#document").textContent()).includes("Synthetic caption paragraph"), "Away/back rejects an earlier fast response");
    assert.equal(await page.locator("#noteActions").evaluate(node => node.inert), false); report.cases.push({ name: "away-back-rejects-old-preview" });
    assert.deepEqual(report.pageErrors, []); assert.deepEqual(report.unexpectedRequests, []); report.passed = true;
  } catch (error) { primaryError = error; report.error = error.stack || error.message; }
  finally {
    closing = true;
    for (const queue of [selectedHolds, listHolds, snapshotHolds, editionHolds]) for (const finish of queue.splice(0)) {
      try { await finish(true); } catch (error) { report.cleanupErrors.push(error.message); if (!primaryError) primaryError = error; }
    }
    try { await context.close(); } catch (error) { report.cleanupErrors.push(error.message); if (!primaryError) primaryError = error; }
    report.passed = report.passed && !primaryError;
    try { fs.writeFileSync(path.join(out, "bound-caption-result.json"), JSON.stringify(report, null, 2)); }
    catch (error) { if (!primaryError) primaryError = error; }
  }
  if (primaryError) throw primaryError;
  return report;
}

(async () => {
  const base = process.argv[2] || "http://127.0.0.1:18930";
  const out =
    process.argv[3] ||
    fs.mkdtempSync(path.join(os.tmpdir(), "learnnote-reader-"));
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const p = await browser.newPage({
    viewport: { width: 1536, height: 1024 },
    reducedMotion: "reduce",
  });
  const errors = [],
    mediaRequests = [];
  p.on("pageerror", (e) => errors.push(e.message));
  p.on("request", (r) => {
    if (/\/api\/tasks\/[^/]+\/media$/.test(r.url()))
      mediaRequests.push(r.url());
  });
  const tasks = [
    {
      id: "summary-good",
      title: "阅读验收示例：如何判断旅程的价值",
      status: "success",
      phase: "completed",
      summary_source: "llm",
      transcript_path: "transcript.json",
      mode: "subtitle_only",
    },
    {
      id: "summary-retry",
      title: "总结失败后，继续使用已有字幕",
      status: "failed",
      phase: "failed",
      failed_phase: "summarizing",
      error_code: "summary_unavailable",
      summary_source: "local-template",
      transcript_path: "transcript.json",
    },
    {
      id: "waiting",
      title: "浏览器已交接，尚未开始",
      status: "queued",
      phase: "queued",
      awaiting_confirmation: true,
    },
    {
      id: "download-timed",
      title: "下载与媒体准备分别计时",
      status: "success",
      phase: "completed",
      summary_source: "llm",
      transcript_path: "transcript.json",
    },
    {
      id: "legacy-media-only",
      title: "旧任务只有媒体准备记录",
      status: "success",
      phase: "completed",
      summary_source: "llm",
      transcript_path: "transcript.json",
    },
    {
      id: "detailed-stage-timings",
      title: "当前尝试的各阶段实测时间",
      status: "success",
      phase: "completed",
      summary_source: "llm",
      transcript_path: "transcript.json",
    },
  ].map((t) => ({
    created_at: "2026-09-08T10:00:00Z",
    updated_at: "2026-09-08T10:01:00Z",
    options: {},
    kind: "task",
    ...t,
  }));
  const summary =
    "# 阅读验收示例：如何判断旅程的价值\n\n## 核心结论\n\n这是一份用于检查界面的示例笔记。评价旅行体验，可以分别考察抵达过程、住宿条件和实际活动，避免用价格替代具体判断（[00:53 – 01:00]）。\n\n- **交通与时间**：记录所需时间和换乘步骤。\n- **住宿体验**：区分可核实的设施信息与个人感受。\n- **价格构成**：说明哪些服务包含在价格中。\n\n## 内容大纲\n\n1. 旅程如何抵达目的地\n2. 酒店提供了什么\n3. 哪些体验值得关注\n\n## 旅程与体验\n\n对旅行的理解来自具体经历。笔记应当围绕几个完整主题进行组织，保留重要事实和必要的例子，而不是逐句重复字幕。\n\n## 核对来源\n\n遇到不确定的数字或描述，应回到原始字幕查看上下文。";
  const event = (phase, status, ms) => ({
    event: "stage_timing",
    timestamp: "2026-09-08T10:00:01Z",
    phase,
    status,
    details: { duration_ms: ms },
  });
  let retryCalls = 0;
  await p.route("**/api/tasks", (r) => r.fulfill({ json: { tasks } }));
  await p.route("**/api/library/materials?*", (r) =>
    r.fulfill({ json: { materials: [] } }),
  );
  await p.route("**/api/tasks/*", (r) => {
    const id = new URL(r.request().url()).pathname.split("/").at(-1);
    return tasks.some((t) => t.id === id)
      ? r.fulfill({ json: { task: tasks.find((t) => t.id === id) } })
      : r.continue();
  });
  await p.route("**/api/tasks/*/events?*", (r) => {
    const id = new URL(r.request().url()).pathname.split("/").at(-2);
    if (id === "detailed-stage-timings") {
      return r.fulfill({ json: { events: [
        {event: "pipeline_attempt_started", phase: "pipeline", status: "running", details: {attempt_id: "timing-fixture"}},
        ...Object.entries({queue: 3000, download: 23000, media: 1000, transcript: 7000,
          frames: 11000, vision: 13000, merge: 2000, verify: 1000, visual: 12000, summary: 20000})
          .map(([stage, duration]) => event(stage, "completed", duration)),
      ] } });
    }
    const mediaEvents = id === "download-timed"
      ? [event("download", "completed", 23000), event("media", "completed", 1000)]
      : id === "legacy-media-only"
        ? [event("media", "completed", 1000)]
        : [event("download", "skipped", 0), event("media", "skipped", 0)];
    return r.fulfill({
      json: {
        events: [
          event("subtitle_probe", "completed", 2300),
          ...mediaEvents,
          event("transcript", "completed", 120),
          event("visual", "skipped", 0),
          event(
            "summary",
            r.request().url().includes("retry") ? "failed" : "completed",
            9200,
          ),
        ],
      },
    });
  });
  await p.route("**/api/tasks/editions/task/*", (r) =>
    r.fulfill({
      json: {
        text: r.request().url().endsWith("waiting")
          ? ""
          : r.request().url().endsWith("summary-retry")
            ? "# 字幕摘录\n\n## 原始字幕\n这是尚未总结的字幕。"
            : summary,
        revision: "fixture",
        edited: false,
      },
    }),
  );
  await p.route("**/api/personal/task/*", (r) =>
    r.fulfill({ json: { annotations: [] } }),
  );
  await p.route("**/api/tasks/*/transcript", (r) =>
    r.fulfill({
      json: {
        segments: [
          { start: 0, end: 4, text: "这是可核对的原始字幕。" },
          { start: 53, end: 60, text: "这里是时间引用对应的原始字幕。" },
        ],
      },
    }),
  );
  await p.route("**/api/tasks/summary-retry/retry-summary", (r) => {
    retryCalls++;
    assert.equal(r.request().method(), "POST");
    return r.fulfill({ json: { task_id: "summary-retry" } });
  });
  let workflowError;
  try {
    await p.goto(base);
    await p.waitForSelector(".recent-note");
    assert.equal(await p.locator(".recent-note > svg").count(), 0);
    assert.equal(await p.locator("#navigateBack").isVisible(), false);
    await p.locator("#collapseSidebar").click();
    assert.equal(await p.locator("#sidebar").isVisible(), false);
    await p.reload();
    assert.equal(await p.locator("#sidebar").isVisible(), false);
    await p.locator("#menu").click();
    assert.equal(await p.locator("#sidebar").isVisible(), true);
    await p.screenshot({
      path: path.join(out, "home.png"),
      animations: "disabled",
    });
    await p.locator('[data-recent="0"]').click();
    await p.waitForFunction(
      () =>
        ["download", "media"].every(key =>
          document.querySelector(`[data-stage="${key}"]`)?.dataset.state === "skipped"),
    );
    assert.match(await p.locator("#document").innerText(), /核心结论/);
    assert.equal(await p.locator(".task-progress-details").evaluate(el => el.open), false);
    await p.locator(".task-progress-details > summary").click();
    assert.match(await p.locator("#taskStatus").innerText(), /无需下载/);
    assert.equal(await p.locator('#taskStatus [data-stage="download"] small').innerText(), "无需下载");
    assert.equal(await p.locator('#taskStatus [data-stage="media"] small').innerText(), "无需准备媒体");
    assert.equal(
      await p
        .locator("#navigateBack")
        .evaluate((el) => getComputedStyle(el).cursor),
      "pointer",
    );
    await p.screenshot({
      path: path.join(out, "reader.png"),
      animations: "disabled",
    });
    await p
      .getByRole("button", { name: "查看这一处字幕上下文 [00:53 – 01:00]", exact: true })
      .click();
    await p
      .locator('.cue.active[data-time="53"]')
      .waitFor({ state: "visible" });
    assert.equal(await p.locator("#player").isVisible(), false);
    await p.locator("#closeSource").click();
    await p.locator('[data-task-action="diagnostics"]').click();
    await p.locator(".processing-records").waitFor({ state: "visible" });
    await p.getByText("诊断详情与安全报告", { exact: true }).click();
    assert(await p.getByRole("button", { name: "预览安全诊断报告", exact: true }).isVisible());
    assert.equal(await p.locator('#toolsDialog a[href*="/exports/diagnostics"], #toolsDialog a[href*="events?limit=2000"]').count(), 0);
    await p.screenshot({
      path: path.join(out, "processing-log.png"),
      animations: "disabled",
    });
    await p.locator("[data-close-tool]").click();
    await p.locator("#source").click();
    assert.equal(await p.locator("#player").isVisible(), false);
    await p.locator(".cue").first().waitFor({ state: "visible" });
    assert.match(await p.locator("#sourceContent").innerText(), /原始字幕/);
    assert.equal(mediaRequests.length, 0);
    await p.locator("#closeSource").click();
    await p.locator("#openOutline").click();
    assert.equal(await p.locator("[data-heading]").count(), 4);
    await p.locator('[data-heading="1"]').click();
    await p.locator('#notes [data-id="summary-retry"]').click();
    await p.locator(".transcript-draft").waitFor({ state: "visible" });
    assert.equal(
      await p.locator(".transcript-draft").getAttribute("open"),
      null,
    );
    await p.locator('[data-task-action="retry-summary"]').click();
    assert.equal(retryCalls, 1);
    await p.locator('#notes [data-id="waiting"]').click();
    assert.match(await p.locator("#taskStatus").innerText(), /还没有开始处理/);
    assert.equal(
      await p.locator('#taskStatus [data-stage][data-state="done"]').count(),
      0,
    );
    await p.screenshot({
      path: path.join(out, "confirmation.png"),
      animations: "disabled",
    });
    for (const id of ["download-timed", "legacy-media-only"]) {
      await p.locator(`#notes [data-id="${id}"]`).click();
      await p.waitForFunction(id =>
        document.querySelector(`[data-task-progress="${id}"] [data-stage="media"] small`)?.textContent === "已完成 · 1 秒", id);
      const timeline = p.locator(`[data-task-progress="${id}"]`);
      assert.equal(await timeline.evaluate(el => el.open), false);
      await timeline.locator("summary").click();
      const download = timeline.locator('[data-stage="download"]');
      const media = timeline.locator('[data-stage="media"]');
      assert.equal(await download.locator("strong").innerText(), "获取视频");
      assert.equal(await media.locator("strong").innerText(), "准备媒体");
      assert.equal(await media.getAttribute("data-state"), "done");
      assert.equal(await media.locator("small").innerText(), "已完成 · 1 秒");
      assert.equal(await download.getAttribute("data-state"), id === "download-timed" ? "done" : "pending");
      assert.equal(await download.locator("small").innerText(), id === "download-timed" ? "已完成 · 23 秒" : "未记录");
      await p.screenshot({path: path.join(out, `${id}.png`), animations: "disabled"});
    }
    await p.locator('#notes [data-id="detailed-stage-timings"]').click();
    await p.waitForFunction(() =>
      document.querySelector('[data-task-progress="detailed-stage-timings"] [data-stage="verify"] small')?.textContent === "已完成 · 1 秒");
    const detailed = p.locator('[data-task-progress="detailed-stage-timings"]');
    await detailed.locator("summary").click();
    for (const [stage, seconds] of Object.entries({queue: 3, download: 23, transcript: 7,
      frames: 11, vision: 13, merge: 2, verify: 1, visual: 12, summary: 20})) {
      const row = detailed.locator(`[data-stage="${stage}"]`);
      assert.equal(await row.getAttribute("data-state"), "done");
      assert.equal(await row.locator("small").innerText(), `已完成 · ${seconds} 秒`);
    }
    assert.equal(await detailed.locator('[data-stage="verify"] strong').innerText(), "本地输出/来源检查");
    assert.equal(await detailed.locator('[data-stage="visual"] strong').innerText(), "画面准备（合计）");
    assert.equal(await detailed.locator('[data-stage="summary"] strong').innerText(), "生成笔记（合计）");
    assert.match(await detailed.innerText(), /不代表事实已核验/);
    assert.match(await detailed.innerText(), /请勿相加/);
    await p.screenshot({path: path.join(out, "detailed-stage-timings.png"), animations: "disabled"});
    await p.setViewportSize({ width: 390, height: 844 });
    await p.locator("#menu").click();
    await p.locator('#notes [data-id="summary-good"]').click();
    assert.equal(await p.locator("#sidebar").evaluate((el) => el.inert), true);
    assert(
      await p.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    );
    await p.screenshot({
      path: path.join(out, "reader-mobile.png"),
      animations: "disabled",
    });
    assert.deepEqual(errors, []);
    const boundCaption = await verifyBoundCaptionPreview(browser, base, out);
    fs.writeFileSync(
      path.join(out, "result.json"),
      JSON.stringify(
        {
          passed: true,
          retryCalls,
          bound_caption: { passed: boundCaption.passed, report: "bound-caption-result.json" },
          mediaRequests,
          errors,
          timing_cases: ["subtitle-skipped", "download-timed", "legacy-media-only", "detailed-stage-timings"],
          viewports: ["1536x1024", "390x844"],
        },
        null,
        2,
      ),
    );
    console.log(JSON.stringify({ passed: true, out }));
  } catch (error) { workflowError = error; throw error; }
  finally {
    try { await browser.close(); }
    catch (error) { if (!workflowError) throw error; console.error("Reader browser cleanup failed:", error.message); }
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
