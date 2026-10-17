// Actual local media → batch scheduler/cache → partial API/SSE → shipped Edge reader.
const assert = require("node:assert/strict"), fs = require("node:fs"), os = require("node:os"), path = require("node:path");
const { spawn, execFile } = require("node:child_process");
const { edgeLaunchOptions, createStartupParser, observeNativeSse, networkLocation,
  recordFailureDiagnostics, finishAcceptance, observeReadingMetadata } = require("./progressive-slo-api-acceptance.cjs");
const visualProse = "Reference paragraph 1: This deterministic response describes the supplied synthetic image and caption window. It is an unverified draft, retained only for this bounded continuation test.";
const captionText = "Synthetic source: the first window shows a generated test pattern.";
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, label, timeout = 30000) {
  const end = performance.now() + timeout;
  while (performance.now() < end) { const value = await check(); if (value) return value; await delay(30); }
  throw new Error("Timed out: " + label);
}
function boundedDiagnostic(report, key, value) {
  const rows = report[key] ||= [];
  if (rows.length < 64) rows.push(value);
  else report[key + "_dropped"] = (report[key + "_dropped"] || 0) + 1;
}
function visibleStageStates(rows) {
  for (const key of ["queue", "download", "transcript", "frames", "vision", "merge", "verify"]) {
    const row = rows.find(value => value.stage === key);
    assert(row && row.text && [row.top, row.bottom, row.left, row.right, row.width, row.height].every(Number.isFinite)
      && row.top >= 0 && row.bottom <= row.height && row.left >= 0 && row.right <= row.width
      && row.bottom > row.top && row.right > row.left, `Visible stage ${key}`);
  }
  for (const [key, expected] of Object.entries({ frames: "done", vision: "stopped", merge: "pending", verify: "pending" }))
    assert.equal(rows.find(value => value.stage === key).state, expected, `Actual terminal stage ${key}`);
}
function captureStageNavigation(expected) {
  const selected = globalThis.referenceReadingMetadata, reader = document.getElementById("document");
  const panel = document.getElementById("taskStatus");
  if (!/^[a-f0-9]{64}$/.test(expected.generation || "") || selected?.error
      || selected?.event?.id !== expected.task_id || selected.event.kind !== "task"
      || selected.event.control_generation !== expected.generation
      || location.hash !== `#task/${expected.task_id}` || reader?.dataset.readerSource !== `task:${expected.task_id}`
      || reader.dataset.readerRevision !== expected.reader_revision || panel?.dataset.status !== "cancelled")
    throw new Error("Stage navigation requires the current cancelled task, generation and reader revision");
  const progress = [...panel.querySelectorAll("details.task-progress-details")]
    .filter(node => node.dataset.taskProgress === expected.task_id);
  const timeline = progress.length === 1 && progress[0].querySelector(".task-timeline");
  if (!panel.isConnected || panel.hidden || !progress[0]?.open || !timeline?.isConnected || !panel.contains(timeline))
    throw new Error("Stage navigation requires one connected open current task timeline");
  const ids = globalThis.visualStageNodes ||= new WeakMap();
  if (!ids.has(timeline)) ids.set(timeline, globalThis.visualStageNodeNext = (globalThis.visualStageNodeNext || 0) + 1);
  const snapshot = () => ({ node_id: ids.get(timeline), connected: timeline.isConnected,
    in_panel: panel.contains(timeline), scroll_top: document.scrollingElement.scrollTop,
    top: timeline.getBoundingClientRect().top, browser_monotonic_ms: performance.now() });
  const before = snapshot();
  // Resolve and scroll in one browser call: status refresh can replace a
  // transported locator handle before its evaluate callback starts.
  if (expected.scroll) timeline.scrollIntoView({ block: "center", behavior: "instant" });
  const after = snapshot(), nodes = [...timeline.querySelectorAll("li")];
  if (nodes.length > 16) throw new Error("Unexpected stage row count");
  const rows = nodes.map(node => {
    const rect = node.getBoundingClientRect();
    return { stage: node.dataset.stage, state: node.dataset.state, text: node.innerText,
      top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right, width: innerWidth, height: innerHeight };
  });
  return { selected_metadata: { ...selected.event }, route: location.hash, reader_source: reader.dataset.readerSource,
    reader_revision: reader.dataset.readerRevision, before, after, rows };
}
async function stopOwnedFixture(child, script, data, grace = 5000) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  assert(Number.isSafeInteger(child.pid) && child.pid > 0 && child.spawnargs.includes(script)
    && child.spawnargs.includes("--data-dir") && child.spawnargs.includes(data), "Cleanup requires the exact owned fixture launch");
  const exited = () => child.exitCode !== null || child.signalCode !== null;
  if (child.stdin?.writable) child.stdin.write("shutdown\n", () => {});
  const deadline = performance.now() + grace;
  while (!exited() && performance.now() < deadline) await delay(25);
  if (exited()) return;
  if (process.platform === "win32") {
    await new Promise((resolve, reject) => execFile("taskkill", ["/PID", String(child.pid), "/T", "/F"],
      { windowsHide: true, timeout: 10000 }, error => error ? reject(error) : resolve()));
  } else {
    try { process.kill(-child.pid, "SIGKILL"); } catch (error) { if (error.code !== "ESRCH") throw error; }
  }
  await until(exited, "owned fixture process-tree exit", 10000);
}
function visualEventDetail(event) {
  if (event.eventName !== "partial_section_ready") return null;
  const value = JSON.parse(event.data).details;
  assert(value?.schema_version === 1 && value.kind === "vision_batch" && value.verified === false, "Native visual event must remain an unverified batch");
  assert(/^vision-[a-f0-9]{24}$/.test(value.section_id) && /^[a-f0-9]{64}$/.test(value.revision), "Invalid native visual section identity");
  assert(Number.isInteger(value.section_count) && value.section_count > 0 && value.section_count <= 80, "Invalid native visual section count");
  return { request_id: event.requestId, id: event.eventId, section_id: value.section_id,
    revision: value.revision, section_count: value.section_count, verified: false };
}
function visualEventMatches(detail, native, projection, persisted) {
  return native.task_id === projection.task_id && native.event === "partial_section_ready"
    && native.request_id === detail.request_id && native.id === detail.id
    && persisted.verified === false && detail.verified === false && projection.verified === false
    && detail.revision === persisted.revision && persisted.projection_revision === projection.revision
    && persisted.attempt_id === projection.attempt_id && persisted.source_revision === projection.source_revision
    && persisted.generation_revision === projection.generation_revision
    && detail.section_count === persisted.section_ids.length && persisted.section_ids.includes(detail.section_id)
    && projection.sections.some(section => section.id === detail.section_id && section.kind === "vision_batch");
}
function retainedViewport(value) {
  return Boolean(value && ["same_task", "same_chapter", "same_batch", "same_prose", "same_selection", "connected", "visible", "unobscured"].every(key => value[key] === true)
    && [value.before_top, value.top, value.bottom, value.left, value.right, value.viewport?.height, value.viewport?.width].every(Number.isFinite)
    && Math.abs(value.top - value.before_top) <= 2 && value.top >= 0 && value.bottom <= value.viewport.height
    && value.left >= 0 && value.right <= value.viewport.width && value.right > value.left && value.bottom > value.top);
}
function rememberVisibleBatch(element, expected) {
  const reader = document.getElementById("document"), chapter = element.closest("[data-reader-section]");
  if (location.hash !== `#task/${expected.task_id}` || reader.dataset.readerSource !== `task:${expected.task_id}`
      || !element.isConnected || !reader.contains(element) || !chapter?.isConnected
      || element.dataset.readerBatch !== expected.batch_id) throw new Error("Wrong visual reading source or batch");
  const matches = [...element.querySelectorAll(":scope > div > p")].filter(node => node.innerText === expected.text);
  if (matches.length !== 1) throw new Error("Expected one exact deterministic body paragraph");
  const paragraph = matches[0];
  paragraph.scrollIntoView({ block: "center", behavior: "instant" });
  const selection = document.getSelection(), range = document.createRange();
  range.selectNodeContents(paragraph); selection.removeAllRanges(); selection.addRange(range);
  globalThis.visualReadingAnchor = { batch: element, body: paragraph.parentElement, paragraph, chapter,
    source: reader.dataset.readerSource, route: location.hash, prose: expected.text,
    selection: selection.toString(), anchor_node: selection.anchorNode, focus_node: selection.focusNode,
    anchor_offset: selection.anchorOffset, focus_offset: selection.focusOffset, top: paragraph.getBoundingClientRect().top };
  return true;
}
function captureReadableCaption(expected) {
  const reader = document.getElementById("document");
  if (location.hash !== `#task/${expected.task_id}` || reader?.dataset.readerSource !== `task:${expected.task_id}`
      || !/^[a-z0-9-]+$/.test(expected.section_id)) throw new Error("Wrong caption reading source");
  const section = reader.querySelector(`[data-reader-section="${expected.section_id}"]`);
  const textOf = node => [...node.childNodes].filter(child => child.nodeType === 3).map(child => child.textContent).join("").trim();
  const matches = [...(section?.querySelectorAll(":scope > ul > li") || [])].filter(node => textOf(node) === expected.text);
  if (matches.length !== 1 || !matches[0].isConnected || !reader.contains(section)) throw new Error("Expected one exact source caption excerpt");
  const node = matches[0]; node.scrollIntoView({ block: "center", behavior: "instant" });
  const rect = node.getBoundingClientRect();
  for (let item = node; item; item = item.parentElement) {
    const style = getComputedStyle(item);
    if (style.display === "none" || style.visibility !== "visible" || Number(style.opacity) === 0) throw new Error("Caption excerpt is hidden");
  }
  const hit = document.elementFromPoint((rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2);
  if (![rect.top, rect.bottom, rect.left, rect.right, innerWidth, innerHeight].every(Number.isFinite)
      || rect.top < 0 || rect.bottom > innerHeight || rect.left < 0 || rect.right > innerWidth
      || rect.bottom <= rect.top || rect.right <= rect.left || !(hit && (hit === node || node.contains(hit))))
    throw new Error("Caption excerpt is not readable in the viewport");
  return { reader_source: reader.dataset.readerSource, reader_revision: reader.dataset.readerRevision,
    section_id: section.dataset.readerSection, text: textOf(node), rendered_text: node.innerText,
    top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right, viewport: { width: innerWidth, height: innerHeight } };
}
function inspectVisibleBatch() {
  const anchor = globalThis.visualReadingAnchor, node = anchor.paragraph, rect = node.getBoundingClientRect();
  const reader = document.getElementById("document"), selected = document.getSelection();
  let visible = node.isConnected;
  for (let item = node; item; item = item.parentElement) {
    const style = getComputedStyle(item);
    if (style.display === "none" || style.visibility !== "visible" || Number(style.opacity) === 0) visible = false;
  }
  const hit = document.elementFromPoint((rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2);
  return { same_task: reader.dataset.readerSource === anchor.source && location.hash === anchor.route, same_chapter: anchor.chapter.isConnected && reader.contains(anchor.chapter),
    same_batch: anchor.batch.isConnected && anchor.chapter.contains(anchor.batch), same_prose: node.innerText === anchor.prose && node.parentElement === anchor.body && anchor.body.parentElement === anchor.batch
      && [...anchor.batch.querySelectorAll(":scope > div > p")].includes(node),
    same_selection: selected.toString() === anchor.selection && selected.anchorNode === anchor.anchor_node && selected.focusNode === anchor.focus_node
      && selected.anchorOffset === anchor.anchor_offset && selected.focusOffset === anchor.focus_offset && node.contains(selected.anchorNode), connected: node.isConnected,
    visible, unobscured: Boolean(hit && (node === hit || node.contains(hit))), before_top: anchor.top,
    top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right,
    viewport: { width: innerWidth, height: innerHeight }, reader_source: reader.dataset.readerSource,
    reader_revision: reader.dataset.readerRevision, prose: node.innerText.slice(0, 400), batch_id: anchor.batch.dataset.readerBatch };
}
async function main(output = "build/progressive-visual-ui") {
  const { chromium } = require("playwright"), out = path.resolve(output);
  fs.mkdirSync(out, { recursive: true });
  const data = fs.mkdtempSync(path.join(os.tmpdir(), "learnnote-visual-join-"));
  const report = { passed: false, errors: [], external_requests: [], native_sse: [], visual_events: [], screenshots: [],
    scope: { input: "Owned 36-second 320x180 2fps audio/video with complete embedded SRT; actual FFmpeg/transcript/grid preparation",
      substitute: "Only OpenAI chat Completions.create returns held deterministic unverified visual prose",
      actual: "HTTP upload, queue, real batch scheduling/cache, partial callback, persisted projection, native SSE and Edge reader",
      excluded: "Provider quality/latency, semantic verification, ASR, download, automatic update checks, 80-row caption SLO" } };
  let child, browser, context, page, base, fixture, startupError, primaryError, bytes = 0, releaseDelayed;
  const save = () => fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(report, null, 2));
  const api = async (route, options) => {
    const response = await page.request.fetch(base + route, options);
    assert(response.ok(), `${route}: ${response.status()} ${await response.text()}`); return response.json();
  };
  const state = id => api(`/_fixture/tasks/${id}`);
  async function held(id, count = 2) {
    return until(async () => { const value = await state(id);
      assert(!["failed", "cancelled"].includes(value.status), JSON.stringify(value));
      return value.active_completions === 2 && value.calls.length === count ? value : null;
    }, "actual held completion workers");
  }
  async function stopBackend() {
    releaseDelayed?.();
    await stopOwnedFixture(child, path.join(__dirname, "progressive-visual-fixture.py"), data);
  }
  async function capture(name) { await page.screenshot({ path: path.join(out, name), animations: "disabled" }); report.screenshots.push(name); }
  async function upload(variant) {
    const media = await page.request.get(base + "/_fixture/media/" + variant); assert(media.ok());
    const result = await api("/api/tasks/from-local", { method: "POST", multipart: {
      title: "Visual join browser " + variant, options: JSON.stringify(fixture.options),
      file: { name: `synthetic-${variant}.mp4`, mimeType: "video/mp4", buffer: await media.body() } } });
    report.current_task_id = result.task_id; save(); return result.task_id;
  }
  async function open(id) {
    await page.evaluate(id => { location.hash = `#task/${id}`; }, id);
    await page.locator(`#document[data-reader-source="task:${id}"] [data-reader-section]`).waitFor({ state: "visible" });
  }
  async function projectionAfter(id, count) {
    const projection = await until(async () => { const value = await api(`/api/tasks/${id}/partial-note`);
      return value.sections.filter(s => s.kind === "vision_batch").length === count ? value : null;
    }, "actual persisted visual projection");
    assert.equal(projection.verified, false);
    const persisted = (await state(id)).partial;
    const event = await until(() => report.visual_events.find(detail => detail.section_count === count
      && report.native_sse.some(native => visualEventMatches(detail, native, projection, persisted))), "task-bound native revision event");
    assert(projection.sections.some(section => section.id === event.section_id));
    await page.locator(`#document[data-reader-source="task:${id}"] [data-reader-batch="${event.section_id}"]`).waitFor({ state: "visible" });
    return { projection, persisted, native_event: event };
  }
  async function captionGeometry(id, projection, text) {
    assert.equal(projection.task_id, id); assert.equal(projection.verified, false);
    const section = projection.sections.find(section => section.kind === "temporal_outline" && section.excerpts.some(excerpt => excerpt.text === text));
    assert(section, "Expected owned caption text in actual projection");
    return page.evaluate(captureReadableCaption, { task_id: id, section_id: section.id, text });
  }
  async function cancel(id) {
    const started = performance.now(); await api(`/api/tasks/${id}/cancel`, { method: "POST" });
    const value = await until(async () => { const current = await state(id);
      return current.status === "cancelled" && current.active_completions === 0 && current.queue?.callback_finished ? current : null;
    }, "queue and all in-flight completion workers drain");
    const seconds = (performance.now() - started) / 1000;
    assert(seconds < 2, `Cancellation/drain took ${seconds}s`); return { seconds, state: value };
  }
  try {
    save();
    const env = {};
    for (const [key, value] of Object.entries(process.env)) if (/^(PATH|SYSTEMROOT|WINDIR|COMSPEC|PATHEXT|TEMP|TMP|LANG|LC_ALL)$/i.test(key)) env[key] = value;
    Object.assign(env, { PYTHONUTF8: "1", PYTHONUNBUFFERED: "1", PYTHONDONTWRITEBYTECODE: "1" });
    child = spawn(process.env.LEARNNOTE_ACCEPTANCE_PYTHON || "python", [path.join(__dirname, "progressive-visual-fixture.py"), "--data-dir", data],
      { cwd: path.resolve(__dirname, ".."), env, detached: process.platform !== "win32", stdio: ["pipe", "pipe", "pipe"] });
    child.stdin.on("error", error => { if (!primaryError) startupError = error; });
    child.on("error", error => { startupError = error; }); child.on("exit", code => { startupError = new Error(`Visual fixture exited ${code}`); });
    const parser = createStartupParser(value => { fixture = value; }, error => { startupError = error; });
    for (const stream of [child.stdout, child.stderr]) stream.on("data", chunk => { try {
      const remaining = Math.max(0, 1024 * 1024 - bytes); if (remaining) fs.appendFileSync(path.join(out, "backend.log"), chunk.subarray(0, remaining));
      bytes += chunk.length; report.backend_log_truncated = bytes > 1024 * 1024;
      if (stream === child.stdout) parser(chunk);
    } catch (error) { startupError = error; } });
    await until(async () => { if (startupError) throw startupError; if (!fixture) return false;
      try { return (await fetch(fixture.fixture_origin + "/health")).ok; } catch { return false; }
    }, "owned visual fixture startup", 60000);
    assert.equal(fixture.offline_network, true); base = fixture.fixture_origin;
    const launch = edgeLaunchOptions(process.env.LEARNNOTE_ACCEPTANCE_BROWSER);
    browser = await chromium.launch(launch);
    context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce", serviceWorkers: "block" });
    await context.addInitScript(() => localStorage.setItem("learnnote.sidebar.collapsed", "true"));
    await context.addInitScript(observeReadingMetadata);
    await context.route("**/*", route => {
      if (new URL(route.request().url()).origin !== base) { boundedDiagnostic(report, "external_requests", networkLocation(route.request().url())); return route.abort(); }
      return route.continue();
    });
    page = await context.newPage(); page.on("pageerror", error => boundedDiagnostic(report, "errors", error.message));
    const cdp = await context.newCDPSession(page); const stop = observeNativeSse(cdp, report, base); page.once("close", stop);
    cdp.on("Network.eventSourceMessageReceived", event => { try {
      const value = visualEventDetail(event); if (value) { assert(report.visual_events.length < 80); report.visual_events.push(value); }
    } catch (error) { boundedDiagnostic(report, "errors", error.message); } });
    await cdp.send("Network.enable"); await page.goto(base);
    report.browser_identity = { executable: launch.executablePath, evidence: "owned canonical launch path", version: browser.version(),
      ...await page.evaluate(() => ({ user_agent: navigator.userAgent, brands: navigator.userAgentData?.brands || [] })) };
    const id = await upload("a"); report.initial = await held(id); assert(report.initial.grid_count >= 4);
    assert.equal(report.initial.transcript.source, "embedded-subtitle");
    await open(id);
    await until(() => report.native_sse.some(event => event.task_id === id && event.event === "draft_ready"), "real caption draft SSE");
    assert.equal(await page.locator("[data-reader-batch]").count(), 0);
    report.caption_projection = await api(`/api/tasks/${id}/partial-note`);
    report.caption_geometry = await captionGeometry(id, report.caption_projection, captionText);
    await capture("caption-draft.png");
    await api(`/_fixture/tasks/${id}/release/2`, { method: "POST" }); report.second = await projectionAfter(id, 1);
    await held(id, 3);
    const second = page.locator("[data-reader-batch]").filter({ hasText: "Synthetic visual batch 2" });
    await second.evaluate(rememberVisibleBatch, { task_id: id, batch_id: report.second.native_event.section_id, text: visualProse });
    report.before_insertion = await page.evaluate(inspectVisibleBatch);
    assert(retainedViewport(report.before_insertion), JSON.stringify(report.before_insertion)); await capture("batch-2-readable.png");
    await api(`/_fixture/tasks/${id}/release/1`, { method: "POST" }); report.joined = await projectionAfter(id, 2);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    report.after_insertion = await page.evaluate(inspectVisibleBatch);
    assert(retainedViewport(report.after_insertion), JSON.stringify(report.after_insertion)); await capture("earlier-batch-inserted.png");
    assert.equal(report.joined.projection.attempt_id, report.caption_projection.attempt_id);
    assert.equal(report.joined.projection.source_revision, report.caption_projection.source_revision);
    assert.equal(report.joined.projection.generation_revision, report.second.projection.generation_revision);
    report.before_cancel = await held(id, 4); report.cancelled = await cancel(id);
    assert.deepEqual(report.cancelled.state.hashes, report.before_cancel.hashes);
    assert.deepEqual(report.cancelled.state.assets, report.before_cancel.assets);
    assert.equal(report.cancelled.state.calls.length, report.before_cancel.calls.length);
    await page.waitForFunction(() => document.getElementById("taskStatus")?.dataset.status === "cancelled");
    await page.waitForFunction(() => document.getElementById("readerMetadata").textContent.includes("已停止"));
    assert.doesNotMatch(await page.locator("#readerMetadata").innerText(), /等待总结|正在准备内容/);
    report.cancelled_geometry = await page.evaluate(inspectVisibleBatch); assert(retainedViewport(report.cancelled_geometry));
    report.stage_dom_text = await page.locator(".task-timeline").innerText();
    assert(report.cancelled.state.events.some(event => event.event === "stage_timing" && event.phase === "frames" && event.status === "completed"));
    assert(report.cancelled.state.events.some(event => event.event === "stage_timing" && event.phase === "vision" && event.status === "cancelled"));
    await capture("cancelled-retained-visual.png");
    const progress = page.locator("details.task-progress-details").first();
    if (!await progress.evaluate(node => node.open)) await progress.locator(":scope > summary").click();
    const stageSource = { task_id: id, generation: report.cancelled.state.generation, reader_revision: report.cancelled_geometry.reader_revision };
    report.stage_navigation = await page.evaluate(captureStageNavigation, { ...stageSource, scroll: true });
    report.stage_geometry = report.stage_navigation.rows;
    visibleStageStates(report.stage_geometry);
    report.stage_before_capture = await page.evaluate(captureStageNavigation, stageSource);
    visibleStageStates(report.stage_before_capture.rows);
    await capture("actual-stage-states.png");
    const figures = second.locator("details").first();
    await figures.locator("summary").click();
    const image = figures.locator("img").first();
    await image.evaluate(node => node.scrollIntoView({ block: "center", behavior: "instant" }));
    await until(() => image.evaluate(node => node.complete && node.naturalWidth > 0), "actual task-owned source grid loads");
    await image.waitFor({ state: "visible" });
    report.source_grid = await image.evaluate(node => { const rect = node.getBoundingClientRect();
      return { src: node.getAttribute("src"), width: node.naturalWidth, height: node.naturalHeight,
        top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right, viewport_width: innerWidth, viewport_height: innerHeight }; });
    assert(report.source_grid.top >= 0 && report.source_grid.bottom <= report.source_grid.viewport_height
      && report.source_grid.left >= 0 && report.source_grid.right <= report.source_grid.viewport_width, "Actual source grid is in the viewport");
    assert(new URL(report.source_grid.src, base).pathname.startsWith(`/api/tasks/${id}/assets/`));
    await capture("retained-source-grid.png"); await figures.locator("summary").click();
    await page.setViewportSize({ width: 390, height: 844 });
    await second.evaluate(rememberVisibleBatch, { task_id: id, batch_id: report.second.native_event.section_id, text: visualProse });
    report.mobile_geometry = await page.evaluate(inspectVisibleBatch);
    assert(retainedViewport(report.mobile_geometry), JSON.stringify(report.mobile_geometry));
    await capture("cancelled-retained-visual-mobile.png");
    await page.setViewportSize({ width: 1440, height: 1000 });
    const other = await upload("b"); report.changed_initial = await held(other);
    await page.evaluate(() => { location.hash = ""; });
    await page.waitForFunction(() => !document.getElementById("welcome").hidden);
    let delayed, fulfilled = false, delayedError, heldOnce = false;
    const delayedUrl = base + `/api/tasks/${id}/partial-note`;
    await page.route(delayedUrl, async route => {
      if (heldOnce) return route.fallback();
      heldOnce = true;
      try {
        const response = await route.fetch(); assert(response.ok());
        delayed = await response.json(); await new Promise(resolve => { releaseDelayed = resolve; });
        await route.fulfill({ response }); fulfilled = true;
      } catch (error) { delayedError = error; }
    });
    await page.evaluate(id => { location.hash = `#task/${id}`; }, id);
    await until(() => { if (delayedError) throw delayedError; return delayed; }, "held actual old-source projection response");
    await open(other); report.changed_projection = await api(`/api/tasks/${other}/partial-note`);
    assert.notEqual(report.changed_projection.source_revision, report.caption_projection.source_revision);
    assert.notEqual(report.changed_projection.attempt_id, report.caption_projection.attempt_id);
    releaseDelayed(); await until(() => { if (delayedError) throw delayedError; return fulfilled; }, "delayed actual response delivered"); releaseDelayed = null; await page.unroute(delayedUrl);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.equal(await page.locator("#document").getAttribute("data-reader-source"), "task:" + other);
    assert.equal(await page.locator("[data-reader-batch]").count(), 0);
    assert.match(await page.locator("#document").innerText(), /Changed source:/);
    report.delayed_old_response = { task_id: delayed.task_id, attempt_id: delayed.attempt_id, source_revision: delayed.source_revision, revision: delayed.revision };
    report.changed_caption_geometry = await captionGeometry(other, report.changed_projection, "Changed source: " + captionText);
    await capture("changed-source-rejects-delayed-old-draft.png");
    report.changed_cancelled = await cancel(other);
    const original = await state(id); assert.deepEqual(original.hashes, report.cancelled.state.hashes); assert.deepEqual(original.assets, report.cancelled.state.assets);
    report.fixture_state = await api("/_fixture/state"); assert.deepEqual(report.fixture_state.forbidden_attempts, []);
    assert.deepEqual(report.external_requests, []); assert.deepEqual(report.errors, []);
    report.passed = true;
  } catch (error) {
    primaryError = error; report.failure = error.stack || error.message;
    if (page && base) await recordFailureDiagnostics(report, {
      fixture_threads: () => api("/_fixture/diagnostics"),
      screenshot: async () => { await page.screenshot({ path: path.join(out, "failure.png"), timeout: 3000 }); return "failure.png"; },
      page: () => page.evaluate(() => ({ hash: location.hash, reader_source: document.getElementById("document")?.dataset.readerSource,
        reader_revision: document.getElementById("document")?.dataset.readerRevision, status: document.getElementById("taskStatus")?.dataset.status })),
      fixture: () => api("/_fixture/state"), task: () => report.current_task_id ? state(report.current_task_id) : null,
    });
  } finally { releaseDelayed?.(); await finishAcceptance({ save, closeBrowser: async () => { if (browser) await browser.close(); }, stopBackend }, report, primaryError); }
  if (primaryError) throw primaryError;
}
module.exports = { visualProse, captionText, captureReadableCaption, boundedDiagnostic, visibleStageStates, captureStageNavigation, stopOwnedFixture, visualEventDetail, visualEventMatches, retainedViewport, rememberVisibleBatch, inspectVisibleBatch };
if (require.main === module) main(process.argv[2]).catch(error => { console.error(error); process.exitCode = 1; });
