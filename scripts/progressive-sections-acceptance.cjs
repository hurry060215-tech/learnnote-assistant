// Windows Edge acceptance against the shipped reader served by a loopback backend.
// Task APIs and EventSource are synthetic fixtures. No model, media, source-file,
// or real artifact-publication behavior is exercised by this UI-only check.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { createHash } = require("node:crypto");

const TASK_ID = "progressive-sections-ui-fixture";
const SCENARIOS = [
  { name: "vision", kind: "vision_batch", title: "合成验收：渐进图文章节", first: "图文章节 00:00–00:10", second: "图文章节 00:10–00:20" },
  { name: "text", kind: "text_chunk", title: "合成验收：文字分段草稿", first: "文字分段 1", second: "文字分段 2" },
  { name: "enrichment", kind: "vision_batch", title: "合成验收：字幕原位补入图文", first: "图文章节 00:00–00:10", second: "图文章节 00:10–00:20" },
];
const SECOND_CLAIM = "Synthetic batch 2: the reference transcript says the square is blue.";
const TRANSCRIPT = [
  { start: 0, end: 10, text: "The circle is orange." },
  { start: 10, end: 20, text: "The square is blue." },
];
const FINAL_MARKER = "显式模拟成功后的最终样本";
const HOSTILE_TEXT = '<img src="fixture-hostile.png" onerror="window.__progressiveHostileExecuted=true"><script>window.__progressiveHostileExecuted=true</script>';
const digest = value => createHash("sha256").update(value).digest("hex");

function validateBase(value) {
  const base = new URL(value);
  assert(base.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(base.hostname), "Use a loopback HTTP backend");
  assert(!base.username && !base.password && !base.search && !base.hash, "The fixture base cannot contain credentials, a query, or a fragment");
  assert(["/", "/web/index.html"].includes(base.pathname), "Use the shipped default reader, not a substitute page");
  return base;
}

function batch(number, scenario) {
  const heading = number === 1 ? scenario.first : scenario.second;
  const claim = number === 1
    ? "Synthetic batch 1: the reference transcript says the circle is orange."
    : SECOND_CLAIM;
  // Long, explicitly synthetic paragraphs give the final section enough height
  // to scroll its repeated subheading above the viewport without hitting bottom.
  const paragraphs = Array.from({ length: 18 }, (_, index) =>
    `Synthetic reading spacer ${number}.${index + 1}. This text exists only to check reader position. It makes no claim about a real lesson, a model result, or verified facts.`);
  return `## ${heading}\n\n> 草稿 · 证据补充中 · 未完成最终校验 · 待最终来源检查\n\n### Core points\n\n${claim}\n\n${paragraphs.join("\n\n")}\n\n${number === 2 ? HOSTILE_TEXT : "Synthetic first-batch reference only."}`;
}

function partialText(withFirst, scenario) {
  return `# ${scenario.title}\n\n## 已生成的分段草稿\n\n> 证据补充中：以下批次已生成，后续批次、合并与最终检查尚未全部完成。未验证的内容已标记，请回源核对。\n\n${withFirst ? batch(1, scenario) + "\n\n" : ""}${batch(2, scenario)}\n`;
}

function createFixture(scenario) {
  let sequence = 0;
  let clock = Date.parse("2026-10-01T10:00:00Z");
  const fixture = {
    phase: "second-batch",
    retryCalls: 0,
    explicitSuccess: false,
    events: [],
    edition: { text: partialText(false, scenario), revision: "fixture-batch-2", edited: false },
    task: {
      id: TASK_ID, title: scenario.title, kind: "task", source_type: "local", mode: scenario.name === "text" ? "subtitle_only" : "visual",
      status: "running", phase: "summarizing", progress: 62,
      created_at: new Date(clock).toISOString(), updated_at: new Date(clock).toISOString(),
      summary_source: "partial-draft", transcript_path: "transcript.json", note_path: "draft.partial.md",
      message: `Synthetic fixture only: ${HOSTILE_TEXT}`,
      options: { content_mode: scenario.name === "text" ? "text" : "visual", visual_understanding: scenario.name !== "text", generate_questions: false },
      frame_grids: [{ start: 0, end: 10, url: `/api/tasks/${TASK_ID}/frames/synthetic-grid.png` }],
      artifact_status: { draft_available: true, partial_draft_available: true, transcript_ready: true },
    },
  };
  fixture.projection = () => {
    if (scenario.name !== "enrichment" || fixture.explicitSuccess) return { status: "unavailable", sections: [] };
    const outlines = TRANSCRIPT.map((cue, index) => ({ ...cue, id: `draft-time-${index * 10}`, kind: "temporal_outline",
      revision: digest(JSON.stringify(cue)), status: "draft", verified: false, summary_generated: false,
      source_cue_count: 1, heading_excerpt: cue.text, excerpts: [{ ...cue, source_cue_index: index }] }));
    const generated = (fixture.phase === "second-batch" ? [2] : [1, 2]).map(number => ({
      id: `vision-${number}`, kind: "vision_batch", status: "evidence_pending", verified: false,
      markdown: batch(number, scenario), revision: digest(batch(number, scenario)), start: (number - 1) * 10, end: number * 10,
      source_windows: [{ index: number - 1, start: (number - 1) * 10, end: number * 10 }],
    }));
    return { schema_version: 1, task_id: TASK_ID, task_updated_at: fixture.task.updated_at,
      status: "draft", reason: "ready", verified: false, attempt_id: "abcdef123456",
      source_revision: digest(JSON.stringify(TRANSCRIPT)), generation_revision: digest("synthetic-vision-run"),
      revision: digest(JSON.stringify([...outlines, ...generated])), sections: [...outlines, ...generated] };
  };
  function record(event, details = {}) {
    clock += 1000;
    fixture.task.updated_at = new Date(clock).toISOString();
    const entry = {
      event, event_id: ++sequence, task_id: TASK_ID, timestamp: fixture.task.updated_at,
      phase: fixture.task.phase, status: fixture.task.status, progress: fixture.task.progress,
      message: fixture.task.message, details,
    };
    fixture.events.push(entry);
    return entry;
  }
  const sectionDetails = count => ({
    schema_version: 1, kind: scenario.kind, section_id: `synthetic-${scenario.kind}-${count === 1 ? 2 : 1}`,
    revision: fixture.edition.revision, section_count: count, artifact: "draft.partial.md", verified: false,
  });
  fixture.initialEvent = record("partial_section_ready", sectionDetails(1));
  fixture.addEarlierBatch = () => {
    assert.equal(fixture.phase, "second-batch");
    fixture.phase = "both-batches";
    fixture.edition = { text: partialText(true, scenario), revision: "fixture-batches-1-2", edited: false };
    fixture.task.progress = 78;
    return record("partial_section_ready", sectionDetails(2));
  };
  fixture.progressOnly = () => {
    assert.equal(fixture.phase, "both-batches");
    fixture.task.progress = 81;
    return record("task_updated");
  };
  fixture.failMetadata = () => {
    assert.equal(fixture.phase, "both-batches");
    fixture.phase = "failed";
    Object.assign(fixture.task, {
      status: "failed", phase: "failed", failed_phase: "summarizing",
      error_code: "summary_unavailable", summary_source: "local-template",
    });
    fixture.task.artifact_status.failure_phase = "summarizing";
    return record("task_terminal");
  };
  fixture.retry = () => {
    assert.equal(fixture.phase, "failed");
    fixture.phase = "retry-running";
    fixture.retryCalls++;
    Object.assign(fixture.task, { status: "running", phase: "summarizing", summary_source: "partial-draft", progress: 82 });
    delete fixture.task.failed_phase;
    delete fixture.task.error_code;
    delete fixture.task.artifact_status.failure_phase;
    return record("task_updated");
  };
  fixture.completeSuccess = () => {
    assert.equal(fixture.phase, "retry-running");
    fixture.phase = "success";
    fixture.explicitSuccess = true;
    fixture.edition = {
      text: `# ${scenario.title}\n\n## ${FINAL_MARKER}\n\nThis is a synthetic final-edition fixture, released only by the test's explicit success transition. It does not establish that any real course fact has been verified.\n\n${SECOND_CLAIM}\n`,
      revision: "fixture-final-success", edited: false,
    };
    Object.assign(fixture.task, { status: "success", phase: "completed", progress: 100, summary_source: scenario.name === "text" ? "text-llm" : "vision-llm", note_path: "note.md" });
    fixture.task.artifact_status = { draft_available: false, partial_draft_available: false, transcript_ready: true };
    return record("task_terminal");
  };
  return fixture;
}

// Only the stream transport is replaced. The app still installs and invokes its
// production listeners, refreshes task metadata, loads editions, and renders DOM.
function installMockEventSource({ taskId }) {
  const streams = [];
  const deliveries = [];
  class FixtureEventSource extends EventTarget {
    constructor(url, options = {}) {
      super();
      this.url = new URL(url, location.href).href;
      const target = new URL(this.url);
      if (target.origin !== location.origin || target.pathname !== `/api/tasks/${taskId}/events/stream`)
        throw new Error("Unexpected fixture EventSource destination");
      this.readyState = 1;
      this.withCredentials = Boolean(options.withCredentials);
      streams.push(this);
    }
    close() { this.readyState = 2; }
  }
  for (const [name, value] of Object.entries({ CONNECTING: 0, OPEN: 1, CLOSED: 2 })) {
    FixtureEventSource[name] = value;
    FixtureEventSource.prototype[name] = value;
  }
  window.EventSource = FixtureEventSource;
  window.__progressiveFixture = {
    connections: () => streams.map(source => ({ url: source.url, readyState: source.readyState })),
    deliveries,
    emit(entry) {
      const active = streams.filter(source => source.readyState === 1);
      deliveries.push({ event: entry.event, event_id: entry.event_id, recipients: active.length });
      for (const source of active) source.dispatchEvent(new MessageEvent(entry.event, {
        lastEventId: String(entry.event_id), data: JSON.stringify(entry), origin: location.origin,
      }));
      return active.length;
    },
  };
}

async function selfTestScenario(scenario) {
  const FIRST_HEADING = scenario.first, SECOND_HEADING = scenario.second;
  const fixture = createFixture(scenario);
  const original = fixture.edition.text;
  const initialStamp = fixture.task.updated_at;
  assert(!original.includes(FIRST_HEADING));
  assert(original.includes(SECOND_CLAIM) && original.includes(HOSTILE_TEXT));
  assert.throws(() => fixture.completeSuccess());
  const earlier = fixture.addEarlierBatch();
  assert(fixture.task.updated_at > initialStamp);
  assert.equal(earlier.event, "partial_section_ready");
  assert.equal(earlier.details.verified, false);
  assert.equal(earlier.details.kind, scenario.kind);
  if (scenario.name === "text") assert(!fixture.edition.text.includes("图文章节"));
  assert(fixture.edition.text.indexOf(FIRST_HEADING) < fixture.edition.text.indexOf(SECOND_HEADING));
  assert.equal(fixture.edition.text.match(/### Core points/g).length, 2);
  const markdownSandbox = {};
  require("node:vm").runInNewContext(fs.readFileSync(path.join(__dirname, "..", "web", "markdown.js"), "utf8"), markdownSandbox);
  const html = markdownSandbox.LearnNoteMarkdown.markdownToHtml(fixture.edition.text);
  assert(html.includes('id="note-core-points"') && html.includes('id="note-core-points-2"'));
  assert(html.includes("&lt;img") && html.includes("&lt;script&gt;"));
  assert(!/<(?:img|script)\b/.test(html));
  const partialHash = digest(fixture.edition.text);
  fixture.progressOnly(); fixture.failMetadata();
  assert.equal(fixture.task.summary_source, "local-template");
  assert.equal(fixture.task.artifact_status.partial_draft_available, true);
  fixture.retry();
  assert.equal(digest(fixture.edition.text), partialHash);
  assert.equal(fixture.explicitSuccess, false);
  fixture.completeSuccess();
  assert(fixture.edition.text.includes(FINAL_MARKER));
  assert.equal(fixture.task.status, "success");
  assert.deepEqual(fixture.events.map(event => event.event_id), [1, 2, 3, 4, 5, 6]);
  for (let index = 1; index < fixture.events.length; index++)
    assert(fixture.events[index].timestamp > fixture.events[index - 1].timestamp);
  for (const value of ["https://example.com", "http://localhost.evil.invalid", "http://user:secret@localhost", "http://localhost/web/classic.html", "file:///tmp/index.html", "http://localhost/?fixture=1"])
    assert.throws(() => validateBase(value));
  assert.equal(validateBase("http://127.0.0.1:8765").origin, "http://127.0.0.1:8765");
  const sandbox = { window: {}, location: { href: "http://127.0.0.1:8765/", origin: "http://127.0.0.1:8765" }, URL, EventTarget, MessageEvent };
  require("node:vm").runInNewContext(`(${installMockEventSource.toString()})({ taskId: ${JSON.stringify(TASK_ID)} })`, sandbox);
  const source = new sandbox.window.EventSource(`/api/tasks/${TASK_ID}/events/stream?after=0`);
  const received = [];
  source.addEventListener("partial_section_ready", event => received.push([event.lastEventId, JSON.parse(event.data).details.verified]));
  assert.equal(sandbox.window.__progressiveFixture.emit(earlier), 1);
  assert.equal(sandbox.window.__progressiveFixture.emit(earlier), 1);
  assert.deepEqual(received, [["2", false], ["2", false]]);
  source.close();
  assert.equal(sandbox.window.__progressiveFixture.emit(earlier), 0);
  assert.throws(() => new sandbox.window.EventSource("https://example.com/stream"));
  console.log("PASS: synthetic transitions, monotonic IDs/timestamps, shipped Markdown heading IDs/escaping, explicit final boundary, and EventSource mock; no browser launched");
}

async function runScenario(scenario, out) {
  const FIRST_HEADING = scenario.first, SECOND_HEADING = scenario.second;
  fs.mkdirSync(out, { recursive: true });
  const report = {
    passed: false, scenario: scenario.name, kind: scenario.kind, browser: "Microsoft Edge", checks: [], screenshots: [], pageErrors: [], fixtureErrors: [], unexpectedRequests: [],
    scope: { web_assets: "shipped app from supplied loopback backend", task_apis: "synthetic route fulfillment", event_stream: "mocked EventSource", model_execution: false, factual_verification: false, backend_artifact_publication: false, native_webview_tested: false },
    requests: [], editionRequests: [], observations: {}, referenceTranscript: TRANSCRIPT,
  };
  let browser, page;
  const fixture = createFixture(scenario);
  async function screenshot(name, fullPage = false) {
    await page.screenshot({ path: path.join(out, name), animations: "disabled", fullPage });
    report.screenshots.push(name);
  }
  const settle = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  async function emit(entry) {
    assert.equal(await page.evaluate(event => window.__progressiveFixture.emit(event), entry), 1, "Exactly one active task stream must receive the fixture event");
  }
  async function waitEdition() {
    await page.waitForFunction(({ revision, source }) => document.getElementById("document")?.dataset.readerRevision === `${revision}:${source}:`, {
      revision: fixture.edition.revision, source: fixture.task.summary_source,
    });
    await settle();
  }
  async function assertNoFinal() {
    assert.equal(fixture.explicitSuccess, false);
    assert(!fixture.edition.text.includes(FINAL_MARKER));
    assert(!(await page.locator("#document").innerText()).includes(FINAL_MARKER));
    assert.notEqual(await page.locator("#taskStatus").getAttribute("data-status"), "success");
  }
  async function assertEscaped() {
    assert((await page.locator("#document").textContent()).includes(HOSTILE_TEXT), "Hostile Markdown must remain literal text");
    assert((await page.locator("#taskStatus .task-detail p").textContent()).includes(HOSTILE_TEXT), "Hostile task metadata must remain literal text");
    assert.equal(await page.locator('#document script, #document img[onerror], #taskStatus .task-detail img, #taskStatus .task-detail script').count(), 0);
    assert.equal(await page.evaluate(() => window.__progressiveHostileExecuted === true), false);
  }
  try {
    const base = validateBase(process.argv[2] || "http://127.0.0.1:8765");
    report.base = base.href;
    browser = await require("playwright").chromium.launch({ channel: "msedge", headless: true });
    report.browserVersion = browser.version();
    const context = await browser.newContext({ viewport: { width: 1440, height: 960 }, reducedMotion: "reduce", serviceWorkers: "block" });
    await context.addInitScript(installMockEventSource, { taskId: TASK_ID });
    await context.routeWebSocket("**/*", socket => { report.unexpectedRequests.push(`WebSocket ${new URL(socket.url()).pathname}`); socket.close(); });
    await context.route("**/*", async route => {
      const request = route.request();
      const url = new URL(request.url());
      const routeKey = `${request.method()} ${url.pathname}`;
      const json = value => route.fulfill({ json: value });
      try {
        if (url.origin !== base.origin) {
          report.unexpectedRequests.push(`External ${request.method()} ${url.origin}${url.pathname}`);
          return await route.abort("blockedbyclient");
        }
        if (request.method() === "GET" && (url.pathname === "/" || url.pathname.startsWith("/web/")))
          return await route.continue(); // Existing backend serves its own shipped assets; no fixture file server.
        report.requests.push(routeKey);
        const taskRoot = `/api/tasks/${TASK_ID}`;
        if (request.method() === "GET") {
          if (url.pathname === "/health") return await json({ ok: true, service: "learnnote", llm_model_configured: false, local_asr_available: false, model_provider_presets: [] });
          if (url.pathname === "/api/tasks") return await json({ tasks: [fixture.task] });
          if (url.pathname === taskRoot) return await json({ task: fixture.task });
          if (url.pathname === `${taskRoot}/events`) return await json({ events: fixture.events });
          if (url.pathname === `${taskRoot}/qa`) return await json({ items: [] });
          if (url.pathname === `${taskRoot}/transcript`) return await json({ segments: TRANSCRIPT });
          if (url.pathname === `${taskRoot}/partial-note`) return await json(fixture.projection());
          if (url.pathname === `${taskRoot}/frames/synthetic-grid.png`) return await route.fulfill({ contentType: "image/png", body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==", "base64") });
          if (url.pathname === `/api/tasks/editions/task/${TASK_ID}`) {
            report.editionRequests.push({ revision: fixture.edition.revision, status: fixture.task.status, summary_source: fixture.task.summary_source, updated_at: fixture.task.updated_at });
            return await json(fixture.edition);
          }
          if (url.pathname === `/api/personal/task/${TASK_ID}`) return await json({ annotations: [] });
          if (url.pathname === "/api/library/materials") return await json({ materials: [] });
          if (url.pathname === "/api/preferences") return await json({ task_options: { transcriber: "none", note_style: "study", note_template: "standard", summary_depth: "standard", local_ocr: false } });
          if (url.pathname === "/api/model/connection") return await json({ model: null, configured: false });
          if (url.pathname === "/api/model/route") return await json({ routes: [], blocking_reasons: [], data_leaving_device: [], offline_source_confirmed: true });
          if (url.pathname === "/api/connections") return await json({ openrouter: { connected: false } });
          if (url.pathname === "/api/assistant/skills") return await json({ skills: [], features: [] });
          if (url.pathname === "/api/assistant/history") return await json({ items: [] });
          if (url.pathname === "/api/update/status") return await json({ status: "up_to_date", preferences: { auto_check: false, auto_download: false } });
        }
        if (routeKey === "POST /api/study/activity") return await json({ ok: true });
        if (routeKey === `POST ${taskRoot}/retry-summary`) {
          fixture.retry();
          return await json({ task_id: TASK_ID, task: fixture.task });
        }
        report.unexpectedRequests.push(routeKey);
        return await route.fulfill({ status: 501, json: { detail: `Unexpected synthetic fixture request: ${routeKey}` } });
      } catch (error) {
        report.fixtureErrors.push(error.message);
        await route.abort("failed").catch(() => {});
      }
    });
    page = await context.newPage();
    page.setDefaultTimeout(15000);
    page.on("pageerror", error => report.pageErrors.push(error.message));
    page.on("dialog", dialog => { report.fixtureErrors.push(`Unexpected ${dialog.type()} dialog`); dialog.dismiss().catch(() => {}); });
    await page.goto(base.href, { waitUntil: "domcontentloaded" });
    await page.locator(`#notes [data-id="${TASK_ID}"]`).click();
    await waitEdition();
    await page.waitForFunction(() => window.__progressiveFixture.connections().some(source => source.readyState === 1));
    assert.equal(await page.locator("#taskStatus").getAttribute("data-status"), "running");
    assert((await page.locator("#document").innerText()).includes(SECOND_CLAIM));
    assert.equal(await page.getByRole("heading", { name: FIRST_HEADING, exact: true }).count(), 0);
    assert.equal(await page.locator('#taskStatus [data-stage="summary"]').getAttribute("data-state"), "active");
    await assertNoFinal();
    await assertEscaped();
    assert.match(await page.locator("#taskStatus").innerText(), /分段草稿可读/);
    if (scenario.name === "text") {
      assert(!(await page.locator("#document").innerText()).includes("图文章节"));
      assert.match(await page.locator("#document").innerText(), /待最终来源检查/);
    }
    const initialRefresh = page.waitForResponse(response => new URL(response.url()).pathname === "/api/tasks");
    await emit(fixture.initialEvent);
    await initialRefresh;
    await settle();
    await screenshot("01-running-batch-2.png");
    report.checks.push("Completed synthetic batch 2 is readable while task and summary stage remain running");

    if (scenario.name === "enrichment") {
      await page.evaluate(() => {
        const section = document.querySelector('[data-reader-section="draft-time-10"]');
        const excerpt = section.querySelector("li").lastChild;
        const selection = window.getSelection(), range = document.createRange();
        range.selectNodeContents(excerpt); selection.removeAllRanges(); selection.addRange(range);
        window.__sourceDraftProbe = { section, excerpt, selectionText: selection.toString(), anchor: selection.anchorNode, focus: selection.focusNode };
      });
      assert.match(await page.locator("#document").innerText(), /不是 AI 主题总结/);
    }

    // Use the actual root scroller. Core points initially has one occurrence;
    // an earlier batch will take its old occurrence-based Markdown heading ID.
    const before = await page.evaluate(({ heading, claim }) => {
      const nodes = [...document.querySelectorAll("#document h2,#document h3")];
      const section = nodes.find(node => node.textContent === heading);
      const core = nodes[nodes.indexOf(section) + 1];
      if (!section || core?.textContent !== "Core points") throw new Error("Missing fixture source-range heading");
      document.scrollingElement.scrollTop += core.getBoundingClientRect().top + 12;
      return { coreId: core.id, coreTop: core.getBoundingClientRect().top, sectionTop: section.getBoundingClientRect().top, scrollTop: document.scrollingElement.scrollTop,
        claimTop: [...document.querySelectorAll("#document p")].find(node => node.textContent === claim).getBoundingClientRect().top };
    }, { heading: SECOND_HEADING, claim: SECOND_CLAIM });
    assert(before.scrollTop > 0 && before.coreTop < 0, "The test must actually read below the repeated subheading");
    const requestsBeforeInsert = report.editionRequests.length;
    await emit(fixture.addEarlierBatch());
    await waitEdition();
    const after = await page.evaluate(({ heading, claim }) => {
      const nodes = [...document.querySelectorAll("#document h2,#document h3")];
      const section = nodes.find(node => node.textContent === heading);
      const core = nodes[nodes.indexOf(section) + 1];
      return { coreId: core.id, coreTop: core.getBoundingClientRect().top, sectionTop: section.getBoundingClientRect().top, scrollTop: document.scrollingElement.scrollTop,
        claimTop: [...document.querySelectorAll("#document p")].find(node => node.textContent === claim).getBoundingClientRect().top };
    }, { heading: SECOND_HEADING, claim: SECOND_CLAIM });
    assert(report.editionRequests.length > requestsBeforeInsert, "A ready event with a new updated_at must reload the edition");
    if (scenario.name === "enrichment") {
      assert.equal(after.coreId, before.coreId, "Independent source batches must retain stable, unique heading IDs");
      const stable = await page.evaluate(() => {
        const probe = window.__sourceDraftProbe, selection = window.getSelection();
        return probe.section === document.querySelector('[data-reader-section="draft-time-10"]') && probe.excerpt.isConnected
          && selection.anchorNode === probe.anchor && selection.focusNode === probe.focus && selection.toString() === probe.selectionText;
      });
      assert(stable, "A new visual batch must retain the original subtitle DOM and active selection");
      assert.equal(await page.locator('[data-reader-section="draft-time-0"] [data-reader-batch="vision-1"]').count(), 1);
      assert.equal(await page.locator('[data-reader-section="draft-time-10"] [data-reader-batch="vision-2"]').count(), 1);
      await page.locator('[data-reader-batch="vision-1"] > details > summary').click();
      assert.equal(await page.locator('[data-reader-batch="vision-1"] > details > img').getAttribute("src"), `/api/tasks/${TASK_ID}/frames/synthetic-grid.png`);
      report.checks.push("Source excerpts and active selection survive a newly inserted visual batch; exact-range owned image and source controls are available in place");
    } else assert.notEqual(after.coreId, before.coreId, "The earlier duplicate heading must take the original occurrence-based ID");
    assert(Math.abs(after.sectionTop - before.sectionTop) <= 3, `Source section jumped: ${JSON.stringify({ before, after })}`);
    assert(Math.abs(after.claimTop - before.claimTop) <= 3, "The same batch-2 passage must retain its viewport position");
    assert(after.scrollTop > before.scrollTop + 500, "Root scroll must compensate for the inserted earlier batch");
    assert.equal(await page.getByRole("heading", { name: "Core points", exact: true }).count(), 2);
    const order = await page.locator("#document h2").allTextContents();
    assert(order.indexOf(FIRST_HEADING) < order.indexOf(SECOND_HEADING));
    await assertNoFinal();
    report.observations.anchor = { before, after };
    await screenshot("02-earlier-batch-reading-position.png");
    report.checks.push("Earlier batch 1 arrives by partial_section_ready; edition reload preserves batch-2 position despite repeated Core points IDs");

    await page.evaluate(claim => {
      const element = document.getElementById("document");
      const passage = [...element.querySelectorAll("p")].find(node => node.textContent === claim);
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(passage);
      selection.removeAllRanges(); selection.addRange(range);
      const probe = { child: element.firstChild, passage, anchor: selection.anchorNode, focus: selection.focusNode, anchorOffset: selection.anchorOffset, focusOffset: selection.focusOffset, scrollTop: document.scrollingElement.scrollTop, mutations: 0 };
      probe.observer = new MutationObserver(records => { probe.mutations += records.length; });
      probe.observer.observe(element, { childList: true, subtree: true, characterData: true });
      window.__progressiveReaderProbe = probe;
    }, SECOND_CLAIM);
    async function assertStable(label) {
      await settle();
      const result = await page.evaluate(() => {
        const probe = window.__progressiveReaderProbe;
        const selection = window.getSelection();
        return { sameChild: document.getElementById("document").firstChild === probe.child, passageConnected: probe.passage.isConnected,
          sameSelection: selection.anchorNode === probe.anchor && selection.focusNode === probe.focus && selection.anchorOffset === probe.anchorOffset && selection.focusOffset === probe.focusOffset,
          text: selection.toString(), mutations: probe.mutations, scrollDelta: document.scrollingElement.scrollTop - probe.scrollTop };
      });
      assert(result.sameChild && result.passageConnected && result.sameSelection, `${label}: DOM/selection changed ${JSON.stringify(result)}`);
      assert.equal(result.text, SECOND_CLAIM, `${label}: selection text`);
      assert.equal(result.mutations, 0, `${label}: reader DOM was replaced`);
      assert(Math.abs(result.scrollDelta) <= 1, `${label}: scroll moved`);
      report.observations[label] = result;
    }
    const duplicate = fixture.events.find(event => event.event_id === 2);
    await emit(duplicate);
    await assertStable("duplicate_event");
    const requestsBeforeProgress = report.editionRequests.length;
    const progressResponse = page.waitForResponse(response => new URL(response.url()).pathname === `/api/tasks/editions/task/${TASK_ID}`);
    await emit(fixture.progressOnly());
    await progressResponse;
    await waitEdition();
    assert(report.editionRequests.length > requestsBeforeProgress, "A newer progress event must reload metadata and the unchanged edition");
    await assertStable("new_progress_same_revision");
    await page.evaluate(() => window.__progressiveReaderProbe.observer.disconnect());
    await screenshot("03-duplicate-event-selection.png");
    report.checks.push("Duplicate event and newer progress-only event preserve reader DOM, selection, and scroll");

    const partialHash = digest(fixture.edition.text);
    await emit(fixture.failMetadata());
    await waitEdition();
    assert.equal(await page.locator("#taskStatus").getAttribute("data-status"), "needs-summary");
    assert.match(await page.locator("#taskStatus").innerText(), /完整总结尚未完成.*分段仍以草稿保留/s);
    assert.equal(await page.locator("#document .transcript-draft").count(), 0, "Partial generated source chunks must not collapse into a transcript-only draft");
    assert.equal(await page.getByRole("heading", { name: "Core points", exact: true }).count(), 2);
    assert.match(await page.locator("#document").innerText(), /草稿 · 证据补充中 · 未完成最终校验 · 待最终来源检查/);
    await assertEscaped();
    await assertNoFinal();
    await page.evaluate(() => { window.getSelection().removeAllRanges(); window.scrollTo(0, 0); });
    await screenshot("04-failed-partial-chapters.png");
    report.checks.push("Failed local-template metadata retains generated source chunks when partial_draft_available is true; hostile text stays escaped");

    await page.locator('[data-task-action="retry-summary"]').click();
    await page.waitForFunction(() => document.getElementById("taskStatus")?.dataset.status === "running");
    await waitEdition();
    assert.equal(fixture.retryCalls, 1);
    assert.equal(digest(fixture.edition.text), partialHash);
    await assertNoFinal();
    await emit(fixture.events.at(-1));
    await settle();
    await emit(fixture.completeSuccess());
    await waitEdition();
    assert.equal(await page.locator("#taskStatus").getAttribute("data-status"), "success");
    await page.getByRole("heading", { name: FINAL_MARKER, exact: true }).waitFor();
    const finalWarning = await page.locator('#document [role="status"]').innerText();
    assert.match(finalWarning, /生成完成不代表逐条事实已验证/);
    assert.equal(await page.getByRole("heading", { name: FIRST_HEADING, exact: true }).count(), 0);
    assert.equal(await page.getByRole("heading", { name: SECOND_HEADING, exact: true }).count(), 0);
    report.observations.final = { revision: fixture.edition.revision, explicit_simulated_success: fixture.explicitSuccess, warning: finalWarning };
    await page.evaluate(() => window.scrollTo(0, 0));
    await screenshot("05-explicit-success-final-sample.png");
    report.checks.push("Final-edition sample appears only after explicit simulated success and retains the facts-not-fully-verified warning");
    report.stream = await page.evaluate(() => ({ connections: window.__progressiveFixture.connections(), deliveries: window.__progressiveFixture.deliveries }));
    assert.deepEqual(report.stream.deliveries.map(event => event.event_id), [1, 2, 2, 3, 4, 5, 6]);
    assert(report.stream.connections.every(source => source.readyState === 2), "Terminal success must close the task stream");
    assert.deepEqual(report.pageErrors, []);
    assert.deepEqual(report.fixtureErrors, []);
    assert.deepEqual(report.unexpectedRequests, []);
    report.passed = true;
  } catch (error) {
    report.failure = { message: error.message, stack: error.stack };
    if (page && !page.isClosed()) {
      await screenshot("failure.png").catch(failure => { report.screenshotFailure = failure.message; });
      report.readerTextOnFailure = await page.locator("#document").textContent({ timeout: 1000 }).catch(() => null);
    }
    throw error;
  } finally {
    report.fixtureState = { phase: fixture.phase, status: fixture.task.status, updated_at: fixture.task.updated_at, explicit_success: fixture.explicitSuccess, retry_calls: fixture.retryCalls };
    report.fixtureEvents = fixture.events.map(({ event, event_id, timestamp, details }) => ({ event, event_id, timestamp, details }));
    // Write before browser cleanup so launch failures and failed assertions also
    // leave a machine-readable report in the requested artifact directory.
    fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(report, null, 2) + "\n");
    await browser?.close();
  }
  console.log(JSON.stringify({ passed: report.passed, scenario: scenario.name, out, checks: report.checks }));
  return report;
}

async function selfTest() {
  for (const scenario of SCENARIOS) await selfTestScenario(scenario);
}

async function main() {
  const out = path.resolve(process.argv[3] || "build/progressive-sections-ui");
  fs.mkdirSync(out, { recursive: true });
  const report = { passed: false, scenarios: [] };
  try {
    for (const scenario of SCENARIOS) {
      const result = await runScenario(scenario, path.join(out, scenario.name));
      report.scenarios.push({ scenario: scenario.name, passed: result.passed, report: `${scenario.name}/report.json` });
    }
    report.passed = report.scenarios.every(scenario => scenario.passed);
  } finally {
    fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(report, null, 2) + "\n");
  }
}

if (require.main === module) {
  (process.argv.includes("--self-test") ? selfTest() : main()).catch(error => { console.error(error); process.exitCode = 1; });
}
