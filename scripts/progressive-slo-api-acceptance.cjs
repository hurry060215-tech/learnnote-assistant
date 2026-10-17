// Hosted Edge acceptance: real HTTP, persisted queue/draft, native SSE and reader.
// Only complete reference captions and the held final-summary adapter are synthetic.
const assert = require("node:assert/strict");
const fs = require("node:fs"), os = require("node:os"), path = require("node:path");
const { spawn } = require("node:child_process");
const { cleanupFixture } = require("./course-upgrade-fixture-helpers.cjs");
const DURATIONS = [5, 30, 60, 180], REPETITIONS = 20;
const OPTIONS = { content_mode: "text", visual_understanding: false, local_ocr: false,
  llm_api_key: "", use_saved_connection: false, llm_base_url: "http://127.0.0.1:9/v1", llm_model: "slo-reference" };
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
function edgeExecutable(value) { return typeof value === "string" && /^msedge(?:\.exe)?$/i.test(value.split(/[\\/]/).pop()); }
function edgeLaunchOptions(configured, filesystem = fs) {
  const candidates = configured ? [configured] : [
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  ];
  const selected = candidates.find(candidate => filesystem.existsSync(candidate));
  assert(selected, "Microsoft Edge executable not found; configure LEARNNOTE_ACCEPTANCE_BROWSER explicitly");
  const executablePath = filesystem.realpathSync(selected);
  assert(filesystem.statSync(executablePath).isFile(), "Microsoft Edge executable must be a file");
  assert(edgeExecutable(executablePath), "This acceptance gate requires a canonical Microsoft Edge executable");
  return { executablePath, headless: true };
}
function networkLocation(value) {
  const url = new URL(value);
  return { origin: url.origin, path: url.pathname.slice(0, 256) };
}
function streamIdentity(value, origin) {
  const url = new URL(value), match = /^\/api\/tasks\/([A-Za-z0-9_-]{1,128})\/events\/stream$/.exec(url.pathname);
  if (url.origin !== origin || url.username || url.password || url.hash || !match) return null;
  const entries = [...url.searchParams];
  if (entries.length !== 1 || entries[0][0] !== "after" || !/^\d+$/.test(entries[0][1])) return null;
  return { task_id: match[1], ...networkLocation(value) };
}
function nativeSseRecord(event, requests) {
  const source = requests.get(event.requestId);
  assert(source, "Native SSE has no current task-stream request binding");
  let payload;
  try { payload = JSON.parse(event.data); } catch { throw new Error("Malformed native SSE JSON"); }
  assert(payload && typeof payload === "object" && !Array.isArray(payload), "Malformed native SSE payload");
  assert(typeof event.eventName === "string" && /^[A-Za-z0-9_-]{1,80}$/.test(event.eventName), "Malformed native SSE event name");
  const id = Number(event.eventId);
  assert(Number.isSafeInteger(id) && id > 0 && String(id) === event.eventId, "Malformed native SSE event ID");
  if (Object.hasOwn(payload, "task_id")) assert(payload.task_id === source.task_id, "Conflicting native SSE task identity");
  if (Object.hasOwn(payload, "event_id")) assert(payload.event_id === id, "Conflicting native SSE event ID");
  if (Object.hasOwn(payload, "event")) assert(payload.event === event.eventName, "Conflicting native SSE event name");
  return { ...source, request_id: event.requestId, event: event.eventName, id: event.eventId };
}
function boundedRecord(report, key, value, limit = 256) {
  const rows = report[key] ||= [];
  if (rows.length === limit) { rows.shift(); report[key + "_dropped"] = (report[key + "_dropped"] || 0) + 1; }
  rows.push(value);
}
function observeNativeSse(cdp, report, origin) {
  const requests = new Map(), listeners = [];
  function on(name, callback) {
    const guarded = event => { try { callback(event); } catch (error) { boundedRecord(report, "errors", error.message, 64); } };
    cdp.on(name, guarded); listeners.push([name, guarded]);
  }
  on("Network.requestWillBeSent", event => {
    requests.delete(event.requestId);
    const source = streamIdentity(event.request.url, origin);
    if (source) requests.set(event.requestId, source);
    const location = networkLocation(event.request.url);
    if (location.origin === origin && location.path.startsWith("/api/")) boundedRecord(report, "network", {
      event: "request", request_id: event.requestId, method: event.request.method, resource_type: event.type, ...location });
  });
  on("Network.responseReceived", event => {
    const location = networkLocation(event.response.url);
    if (location.origin === origin && location.path.startsWith("/api/")) boundedRecord(report, "network", {
      event: "response", request_id: event.requestId, status: event.response.status, mime_type: event.response.mimeType, ...location });
  });
  on("Network.eventSourceMessageReceived", event => boundedRecord(report, "native_sse", nativeSseRecord(event, requests), 8192));
  on("Network.loadingFailed", event => {
    const source = requests.get(event.requestId);
    if (source) boundedRecord(report, "network", { event: "stream_failed", request_id: event.requestId, ...source,
      canceled: Boolean(event.canceled), error: /^[A-Za-z0-9_:]+$/.test(event.errorText) ? event.errorText : "unclassified_failure" });
    requests.delete(event.requestId);
  });
  on("Network.loadingFinished", event => requests.delete(event.requestId));
  function stop() { requests.clear(); for (const [name, listener] of listeners) cdp.off(name, listener); }
  on("close", stop);
  return stop;
}
async function recordFailureDiagnostics(report, operations, timeout = 5000) {
  report.failure_diagnostics = {};
  for (const [name, operation] of Object.entries(operations)) {
    let timer;
    try {
      report.failure_diagnostics[name] = await Promise.race([Promise.resolve().then(operation),
        new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("Diagnostic timed out")), timeout); })]);
    } catch (error) { (report.diagnostic_errors ||= []).push({ operation: name, error: error.message.slice(0, 250) }); }
    finally { clearTimeout(timer); }
  }
}
function p95(values) { return [...values].sort((a, b) => a - b)[Math.ceil(values.length * .95) - 1]; }
function summarize(samples) {
  return DURATIONS.map(minutes => {
    const rows = samples.filter(row => row.minutes === minutes);
    const complete = rows.length === REPETITIONS && new Set(rows.map(row => row.repetition)).size === REPETITIONS
      && rows.every(row => Number.isInteger(row.repetition) && row.repetition >= 1 && row.repetition <= REPETITIONS
        && row.status === "pass" && [row.first_outline_seconds, row.after_transcript_visible_ack_seconds].every(value => Number.isFinite(value) && value >= 0));
    const latency = complete ? p95(rows.map(row => row.first_outline_seconds)) : null;
    const after = complete ? Math.max(...rows.map(row => row.after_transcript_visible_ack_seconds)) : null;
    return { minutes, planned_samples: REPETITIONS, recorded_samples: rows.length, complete,
      first_outline_p95_seconds: latency, after_transcript_max_seconds: after,
      passed: complete && latency <= 10 && after <= 5 };
  });
}
function readableGeometry(value) {
  return Boolean(value && value.source_matches && value.warning_present && [value.heading, value.excerpt].every(rect =>
    rect && rect.visible && rect.unobscured && [rect.top, rect.left, rect.right, rect.bottom, rect.width, rect.height].every(Number.isFinite)
    && rect.width > 0 && rect.height > 0 && rect.top >= 0 && rect.left >= 0
    && rect.bottom <= value.viewport.height && rect.right <= value.viewport.width));
}
function outlineGeometry(element) {
  const siblings = []; for (let next = element.nextElementSibling; next && next.tagName !== "H2"; next = next.nextElementSibling) siblings.push(next);
  const excerpt = siblings.find(next => next.tagName === "UL")?.querySelector("li");
  function geometry(node) {
    if (!node) return null;
    const rect = node.getBoundingClientRect(); let visible = true;
    for (let ancestor = node; ancestor; ancestor = ancestor.parentElement) {
      const style = getComputedStyle(ancestor);
      if (style.display === "none" || style.visibility !== "visible" || Number(style.opacity) <= 0) visible = false;
    }
    const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    return { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right, width: rect.width, height: rect.height,
      visible, unobscured: Boolean(hit && (hit === node || node.contains(hit))) };
  }
  return { heading: geometry(element), excerpt: geometry(excerpt), viewport: { width: innerWidth, height: innerHeight },
    source_matches: Boolean(excerpt?.innerText.includes("Reference lesson source statement at 0 seconds.")),
    warning_present: siblings.some(next => next.tagName === "BLOCKQUOTE" && next.innerText.includes("不是 AI 主题总结")) };
}
function captionRequest(minutes, serial) {
  const duration = minutes * 60;
  return { mode: "subtitle_only", title: `SLO reference ${minutes}m ${serial}`, page_url: "https://example.test/reference",
    handoff_id: `slo-reference-${minutes}-${serial}`, options: OPTIONS, active_video: { duration },
    browser_subtitles: Array.from({ length: duration / 30 }, (_, i) => ({ start: i * 30, end: (i + 1) * 30,
      text: `Reference lesson source statement at ${i * 30} seconds.` })) };
}
async function until(check, label, timeout = 30000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { const value = await check(); if (value) return value; await delay(25); }
  throw new Error(`Timed out: ${label}`);
}
function createStartupParser(accept, fail) {
  let buffer = "";
  return chunk => {
    try {
      buffer += chunk.toString();
      const lines = buffer.split(/\r?\n/); buffer = lines.pop();
      if (buffer.length > 65536) throw new Error("Fixture startup line exceeds bound");
      for (const line of lines) if (line.startsWith('{"fixture_origin":')) accept(JSON.parse(line));
    } catch (error) { fail(error); }
  };
}
function saveCheckpoint(save, primaryError) {
  try { save(); }
  catch (error) {
    if (!primaryError) throw error;
    primaryError.checkpointErrors = [...(primaryError.checkpointErrors || []), error];
  }
}
async function finishAcceptance({ closeBrowser, stopBackend, save }, report, primaryError) {
  if (primaryError) report.passed = false;
  const cleanup = new Error("Acceptance cleanup failed");
  await cleanupFixture({ browser: closeBrowser, backend: stopBackend }, cleanup);
  const errors = cleanup.cleanupErrors || [];
  if (errors.length) { report.passed = false; report.cleanup_errors = errors.map(error => error.message); }
  try { save(); } catch (error) { errors.push(error); report.passed = false; }
  if (primaryError) { if (errors.length) primaryError.cleanupErrors = errors; return; }
  if (errors.length) throw new AggregateError(errors, "Acceptance cleanup failed");
}
async function main(output = "build/progressive-slo-ui") {
  const { chromium } = require("playwright");
  const out = path.resolve(output); fs.mkdirSync(out, { recursive: true });
  const data = fs.mkdtempSync(path.join(os.tmpdir(), "learnnote-progressive-slo-"));
  const report = { passed: false, planned_samples: 80, samples: [], summary: [], screenshots: [], errors: [], external_requests: [], native_sse: [],
    scope: { complete_reference_captions: true, final_summary: "deterministic adapter held until browser observation",
      measure: "Explicit /start submission through actual reader outline heading and source excerpt in viewport, including harness scroll and two animation frames",
      post_transcript: "Same-backend-clock upper bound through browser visibility acknowledgement, including local ACK transport",
      excluded: ["automatic release checks (fixture update preferences disabled)", "application boot", "source capture and deferred confirmation", "ASR", "media download", "vision", "provider latency", "semantic chapter quality", "fact verification", "queue contention"],
      warmth: "Fresh task/artifacts each sample; same initialized backend/browser context. OS/HTTP caches not forced cold; first task identified separately." } };
  let backend, browser, context, page, base, fixture, primaryError, stopObserving, logBytes = 0;
  const save = () => { report.summary = summarize(report.samples); fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(report, null, 2)); };
  async function stopBackend() {
    if (!backend || backend.exitCode !== null || backend.signalCode !== null) return;
    const child = backend;
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("Owned fixture did not exit after kill")), 10000);
      child.once("exit", () => { clearTimeout(timer); resolve(); }); child.kill("SIGKILL");
    });
  }
  async function startBackend(resume = false) {
    fixture = null;
    let failure;
    const env = {};
    for (const [key, value] of Object.entries(process.env))
      if (/^(PATH|SYSTEMROOT|WINDIR|COMSPEC|PATHEXT|TEMP|TMP|LANG|LC_ALL)$/i.test(key)) env[key] = value;
    Object.assign(env, { PYTHONUTF8: "1", PYTHONUNBUFFERED: "1", PYTHONDONTWRITEBYTECODE: "1" });
    backend = spawn(process.env.LEARNNOTE_ACCEPTANCE_PYTHON || "python", [path.join(__dirname, "progressive-slo-fixture.py"), "--data-dir", data, ...(resume ? ["--resume"] : [])],
      { cwd: path.resolve(__dirname, ".."), env, stdio: ["ignore", "pipe", "pipe"] });
    backend.on("error", error => { failure = error; });
    backend.on("exit", code => { failure = new Error(`Fixture exited ${code}`); });
    const parseStartup = createStartupParser(value => { fixture = value; }, error => { failure = error; });
    for (const stream of [backend.stdout, backend.stderr]) stream.on("data", chunk => {
      try {
        const remaining = Math.max(0, 1024 * 1024 - logBytes);
        if (remaining) fs.appendFileSync(path.join(out, "backend.log"), chunk.subarray(0, remaining));
        logBytes += chunk.length; report.backend_log_truncated = logBytes > 1024 * 1024;
        if (stream === backend.stdout) parseStartup(chunk);
      } catch (error) { failure = error; }
    });
    await until(async () => { if (failure) throw failure; if (!fixture) return false;
      try { return (await fetch(fixture.fixture_origin + "/health")).ok; } catch { return false; }
    }, "isolated fixture startup", 60000);
    assert.equal(fixture.offline_network, true); base = fixture.fixture_origin;
  }
  async function newPage() {
    stopObserving?.();
    page = await context.newPage(); page.on("pageerror", error => boundedRecord(report, "errors", error.message, 64));
    const cdp = await context.newCDPSession(page);
    stopObserving = observeNativeSse(cdp, report, base);
    page.once("close", stopObserving);
    await cdp.send("Network.enable");
  }
  const api = async (route, options) => {
    const response = await page.request.fetch(base + route, options);
    assert(response.ok(), `${route}: ${response.status()} ${await response.text()}`); return response.json();
  };
  const snapshot = id => api(`/_fixture/tasks/${id}`);
  async function capture(name) { await page.screenshot({ path: path.join(out, name), animations: "disabled" }); report.screenshots.push(name); }
  async function prepare(minutes, serial, record) {
    report.current_task_id = null;
    const result = await api("/api/tasks/from-current-page?defer=true", { method: "POST", data: captionRequest(minutes, serial) });
    const id = result.task_id;
    report.current_task_id = id; if (record) record.task_id = id; save();
    await page.goto(base + "/#task/" + id);
    await page.locator(`#document[data-reader-source="task:${id}"]`).waitFor({ state: "visible" });
    await until(() => report.native_sse.some(event => event.task_id === id && event.event === "task_created"), "native SSE connected before submission");
    assert.equal(await page.locator("#document h2").filter({ hasText: "按时间段的阅读提纲" }).count(), 0);
    if (!report.settings_startup) {
      const response = await until(() => report.network?.find(event => event.event === "response"
        && event.path === "/api/update/status" && event.status === 200), "normal settings startup response");
      const state = await api("/_fixture/state");
      assert.equal(state.update_preferences.auto_check, false); assert.equal(state.update_preferences.auto_download, false);
      assert.deepEqual(state.forbidden_attempts, []);
      report.settings_startup = { response, update_preferences: state.update_preferences, forbidden_attempts: state.forbidden_attempts };
    }
    return id;
  }
  async function submit(id, suffix = "start") {
    await page.evaluate(({ id, suffix, options }) => {
      window.sloStart = performance.now(); window.sloSubmission = { pending: true };
      // Do not await background-response completion before measuring the draft.
      fetch(`/api/tasks/${id}/${suffix}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(options) })
        .then(async response => { window.sloSubmission = { pending: false, status: response.status, body: await response.text() }; })
        .catch(error => { window.sloSubmission = { pending: false, error: error.message }; });
    }, { id, suffix, options: OPTIONS });
  }
  async function readerGeometry(id) {
    const heading = page.locator(`#document[data-reader-source="task:${id}"] h2`).filter({ hasText: "按时间段的阅读提纲" });
    await heading.waitFor({ state: "visible", timeout: 30000 });
    await heading.evaluate(async element => {
      element.scrollIntoView({ block: "start", behavior: "instant" });
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    });
    const geometry = await heading.evaluate(outlineGeometry);
    assert(readableGeometry(geometry), JSON.stringify(geometry));
    return geometry;
  }
  async function visible(id, minutes = 5) {
    const geometry = await readerGeometry(id);
    const measured = { geometry, first_outline_seconds: await page.evaluate(() => (performance.now() - window.sloStart) / 1000) };
    const state = await api(`/_fixture/tasks/${id}/visible`, { method: "POST" });
    const nativeDraft = await until(() => report.native_sse.find(event => event.task_id === id && event.event === "draft_ready" && Number(event.id) > 0), "actual native draft_ready SSE");
    assert.equal(state.status, "running"); assert.equal(state.waiting, true);
    assert.equal(Object.keys(state.hashes).length, 3);
    assert.deepEqual(state.source_coverage, { duration: minutes * 60, cue_count: minutes * 2,
      first_start: 0, last_end: minutes * 60, reference_cues_complete: true,
      section_count: minutes / 5, final_section_end: minutes * 60 });
    return { ...measured, after_transcript_visible_ack_seconds: state.after_transcript_visible_ack_seconds, phases: state.stages, source_coverage: state.source_coverage, native_draft_event: nativeDraft, state };
  }
  async function release(id, checkResponse = true) {
    await api(`/_fixture/tasks/${id}/release`, { method: "POST" });
    await until(async () => { const state = await snapshot(id); return state.status === "success" && state.queue?.callback_finished && !state.waiting; }, "completed reference task");
    if (checkResponse) {
      await page.waitForFunction(() => window.sloSubmission && !window.sloSubmission.pending);
      assert.equal((await page.evaluate(() => window.sloSubmission)).status, 200);
    }
  }
  try {
    save(); await startBackend();
    const launchOptions = edgeLaunchOptions(process.env.LEARNNOTE_ACCEPTANCE_BROWSER);
    browser = await chromium.launch(launchOptions);
    report.browser_version = browser.version(); report.platform = process.platform;
    context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce", serviceWorkers: "block" });
    await context.addInitScript(() => localStorage.setItem("learnnote.sidebar.collapsed", "true"));
    await context.route("**/*", route => {
      if (new URL(route.request().url()).origin !== base) { boundedRecord(report, "external_requests", networkLocation(route.request().url())); return route.abort(); }
      return route.continue();
    });
    await newPage();
    report.browser_identity = { configured_executable: process.env.LEARNNOTE_ACCEPTANCE_BROWSER || null,
      executable: launchOptions.executablePath, executable_evidence: "canonical path passed to chromium.launch",
      instance_version: browser.version(),
      ...await page.evaluate(() => ({ user_agent: navigator.userAgent, brands: navigator.userAgentData?.brands || [] })) };
    for (const minutes of DURATIONS) for (let repetition = 1; repetition <= REPETITIONS; repetition++) {
      const row = { minutes, repetition, index: report.samples.length + 1, first_task_in_initialized_runtime: report.samples.length === 0, status: "pending" };
      report.samples.push(row); save(); const started = performance.now(); let sampleError;
      try {
        row.task_id = await prepare(minutes, repetition, row); await submit(row.task_id);
        const result = await visible(row.task_id, minutes); delete result.state; Object.assign(row, result);
        if (repetition === 1) await capture(`outline-${minutes}m.png`);
        if (row.index === 1) {
          const documentNode = page.locator("#document"), previous = await documentNode.evaluate(node => node.style.opacity);
          try {
            await documentNode.evaluate(node => { node.style.opacity = "0"; });
            const hidden = await documentNode.locator("h2").filter({ hasText: "按时间段的阅读提纲" }).evaluate(outlineGeometry);
            assert.equal(readableGeometry(hidden), false, "Invisible ancestor must fail actual browser readability");
            report.ancestor_opacity_negative = hidden;
          } finally { await documentNode.evaluate((node, value) => { node.style.opacity = value; }, previous); }
        }
        await release(row.task_id); row.status = "pass";
      } catch (error) { sampleError = error; row.status = "fail"; row.error = error.message; row.observation_elapsed_seconds = (performance.now() - started) / 1000; throw error; }
      finally { saveCheckpoint(save, sampleError); }
    }
    const id = await prepare(5, "lifecycle"); await submit(id);
    const before = (await visible(id)).state; await capture("draft-before-cancel.png");
    const cancelStart = performance.now(); await api(`/api/tasks/${id}/cancel`, { method: "POST" });
    const cancelled = await until(async () => { const state = await snapshot(id);
      return state.status === "cancelled" && !state.waiting && state.queue?.callback_finished ? state : null;
    }, "cancellation acknowledged and callback drained");
    const cancelSeconds = (performance.now() - cancelStart) / 1000;
    assert(cancelSeconds <= 2, `Cancel/drain took ${cancelSeconds}s`);
    assert.deepEqual(cancelled.hashes, before.hashes); assert.equal(cancelled.continuation_calls, before.continuation_calls);
    await page.locator('#taskStatus[data-status="cancelled"]').waitFor();
    const cancelledGeometry = await readerGeometry(id); await capture("draft-after-cancel.png");
    await submit(id, "retry-summary");
    const retry = await until(async () => { const state = await snapshot(id); return state.waiting ? state : null; }, "explicit summary retry held");
    assert.deepEqual(retry.hashes, before.hashes); assert.notEqual(retry.generation, before.generation);
    report.before_restart_fixture_state = await api("/_fixture/state");
    assert.deepEqual(report.before_restart_fixture_state.forbidden_attempts, []);
    const previousPid = fixture.worker_pid; await page.close(); await stopBackend(); await startBackend(true); await newPage();
    await page.goto(base + "/#task/" + id);
    const recovered = await until(async () => { const state = await snapshot(id); return state.waiting ? state : null; }, "fresh process recovered held summary");
    await page.locator(`#document[data-reader-source="task:${id}"] h2`).filter({ hasText: "按时间段的阅读提纲" }).waitFor();
    assert.deepEqual(recovered.hashes, before.hashes); assert.equal(recovered.generation, retry.generation);
    assert.equal(recovered.queue.sequence, retry.queue.sequence); assert.equal(recovered.queue.generation, retry.queue.generation);
    const startup = await api("/_fixture/state"); assert.equal(startup.startup_recovery.recovered, 1); assert.equal(startup.startup_recovery.waiting_for_context, 0);
    const recoveredGeometry = await readerGeometry(id);
    await capture("draft-after-restart.png"); await page.setViewportSize({ width: 390, height: 844 });
    const recoveredMobileGeometry = await readerGeometry(id); await capture("draft-after-restart-mobile.png");
    await release(id, false); const completed = await snapshot(id); assert.deepEqual(completed.hashes, before.hashes);
    report.lifecycle = { task_id: id, cancelled_geometry: cancelledGeometry, recovered_geometry: recoveredGeometry, recovered_mobile_geometry: recoveredMobileGeometry, cancel_and_drain_seconds: cancelSeconds, original_hashes: before.hashes, cancelled, retry, recovered,
      completed, previous_pid: previousPid, new_pid: fixture.worker_pid, startup_recovery: startup.startup_recovery,
      scope: "Same persisted identity and accepted retry intent; source/draft bytes retained. Computation may rerun; no checkpoint-reuse claim." };
    report.fixture_state = await api("/_fixture/state"); assert.deepEqual(report.fixture_state.forbidden_attempts, []);
    assert.deepEqual(report.errors, []); assert.deepEqual(report.external_requests, []);
    assert(summarize(report.samples).every(row => row.passed), "Full 80-sample SLO matrix must pass without filtering failures or slow samples");
    report.passed = true;
  } catch (error) {
    primaryError = error; report.failure = error.stack;
    if (page && !page.isClosed()) await recordFailureDiagnostics(report, {
      screenshot: async () => {
        await page.screenshot({ path: path.join(out, "failure.png"), animations: "disabled", timeout: 5000 });
        report.screenshots.push("failure.png"); return "failure.png";
      },
      page: () => page.evaluate(() => ({ path: location.pathname, hash: location.hash,
        ready_state: document.readyState, visibility: document.visibilityState,
        reader_source: document.getElementById("document")?.dataset.readerSource || null,
        task_status: document.getElementById("taskStatus")?.dataset.status || null,
        headings: Array.from(document.querySelectorAll("#document h1,#document h2")).slice(0, 8).map(node => node.innerText.slice(0, 120)) })),
      fixture: async () => (await page.request.get(base + "/_fixture/state", { timeout: 3000 })).json(),
      task: async () => report.current_task_id
        ? (await page.request.get(base + "/_fixture/tasks/" + report.current_task_id, { timeout: 3000 })).json() : null,
    });
  }
  finally {
    await finishAcceptance({ save, closeBrowser: async () => { if (browser) await browser.close(); }, stopBackend }, report, primaryError);
  }
  if (primaryError) throw primaryError;
}
module.exports = { DURATIONS, REPETITIONS, OPTIONS, p95, summarize, readableGeometry, captionRequest, createStartupParser, finishAcceptance, saveCheckpoint, outlineGeometry, edgeExecutable, edgeLaunchOptions, networkLocation, streamIdentity, nativeSseRecord, observeNativeSse, recordFailureDiagnostics };
if (require.main === module) main(process.argv[2]).catch(error => { console.error(error); process.exitCode = 1; });
