import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import fixture from "../../scripts/progressive-slo-api-acceptance.cjs";
const { DURATIONS, REPETITIONS, p95, summarize, captionRequest, readableGeometry } = fixture;
function complete() { return DURATIONS.flatMap(minutes => Array.from({ length: REPETITIONS }, (_, index) =>
  ({ minutes, repetition: index + 1, status: "pass", first_outline_seconds: 1, after_transcript_visible_ack_seconds: .5 }))); }
function geometry() { return { source_matches: true, warning_present: true, viewport: { width: 1440, height: 1000 },
  heading: { top: 100, bottom: 140, left: 100, right: 600, width: 500, height: 40, visible: true, unobscured: true },
  excerpt: { top: 220, bottom: 250, left: 100, right: 600, width: 500, height: 30, visible: true, unobscured: true } }; }

test("complete matrix uses nearest-rank p95 and retains every slow sample", () => {
  assert.equal(p95(Array.from({ length: 20 }, (_, i) => i + 1)), 19);
  assert(summarize(complete()).every(row => row.passed));
  const rows = complete(); rows[0].first_outline_seconds = 100; rows[1].first_outline_seconds = 50;
  const summary = summarize(rows)[0]; assert.equal(summary.complete, true); assert.equal(summary.first_outline_p95_seconds, 50); assert.equal(summary.passed, false);
  rows[1].first_outline_seconds = 1; rows[2].after_transcript_visible_ack_seconds = 5.01;
  assert.equal(summarize(rows)[0].passed, false, "Every transcript-to-visible upper bound must meet five seconds");
});
test("missing, failed, pending, duplicated and invalid samples cannot become eligible by filtering", () => {
  const missing = complete(); missing.shift(); assert.equal(summarize(missing)[0].first_outline_p95_seconds, null);
  for (const patch of [{ status: "fail" }, { status: "pending" }, { repetition: 2 }, { repetition: 0 }, { repetition: 21 },
    { first_outline_seconds: Infinity }, { first_outline_seconds: NaN }, { first_outline_seconds: -1 },
    { after_transcript_visible_ack_seconds: undefined }, { after_transcript_visible_ack_seconds: -1 }]) {
    const rows = complete(); Object.assign(rows[0], patch); const summary = summarize(rows)[0];
    assert.equal(summary.complete, false, JSON.stringify(patch)); assert.equal(summary.passed, false); assert.equal(summary.first_outline_p95_seconds, null);
  }
  const excess = complete(); excess.push({ ...excess[0] }); assert.equal(summarize(excess)[0].complete, false);
});
test("reference cues cover every declared duration continuously with no media or private source context", () => {
  for (const minutes of DURATIONS) {
    const request = captionRequest(minutes, 1), cues = request.browser_subtitles;
    assert.equal(request.mode, "subtitle_only"); assert.equal(request.active_video.duration, minutes * 60);
    assert.equal(cues[0].start, 0); assert.equal(cues.at(-1).end, minutes * 60);
    cues.forEach((cue, index) => { assert.equal(cue.start, index * 30); assert.equal(cue.end, (index + 1) * 30); assert.match(cue.text, /^Reference lesson source/); });
    assert.equal(request.page_text, undefined); assert.equal(request.cookies, undefined); assert.equal(request.resources, undefined);
    assert.equal(request.options.llm_api_key, ""); assert.equal(request.options.visual_understanding, false);
  }
});
test("readability requires visible unoccluded heading and literal source excerpt inside viewport", () => {
  assert.equal(readableGeometry(geometry()), true);
  for (const part of ["heading", "excerpt"]) for (const patch of [{ width: 0 }, { height: 0 }, { top: -1 }, { left: -1 },
    { bottom: 1001 }, { right: 1441 }, { visible: false }, { unobscured: false }, { top: NaN }]) {
    const value = geometry(); Object.assign(value[part], patch); assert.equal(readableGeometry(value), false);
  }
  for (const field of ["source_matches", "warning_present"]) { const value = geometry(); value[field] = false; assert.equal(readableGeometry(value), false); }
  const absent = geometry(); absent.excerpt = null; assert.equal(readableGeometry(absent), false);
});
test("harness preserves actual native SSE and checks drained cancellation before retry and process recovery", () => {
  const source = fs.readFileSync(new URL("../../scripts/progressive-slo-api-acceptance.cjs", import.meta.url), "utf8");
  assert.match(source, /Network\.eventSourceMessageReceived/); assert.match(source, /event === "draft_ready"/);
  assert.doesNotMatch(source, /route\.fulfill|window\.EventSource\s*=|addInitScript\([\s\S]*?new EventSource/);
  assert.match(source, /state\.status === "cancelled" && !state\.waiting && state\.queue\?\.callback_finished/);
  assert(source.indexOf('"cancellation acknowledged and callback drained"') < source.indexOf('submit(id, "retry-summary")'));
  assert.match(source, /assert\.deepEqual\(completed\.hashes, before\.hashes\)/);
  assert.match(source, /assert\.equal\(recovered\.generation, retry\.generation\)/);
  assert.match(source, /report\.samples\.push\(row\); save\(\)/);
});

test("startup parser handles split stdout and reports malformed JSON without uncaught callback errors", () => {
  const accepted = [], failures = [], parse = fixture.createStartupParser(value => accepted.push(value), error => failures.push(error));
  parse(Buffer.from('ordinary stdout\n{"fixture_ori'));
  parse(Buffer.from('gin":"http://127.0.0.1:1234","offline_network":true}\n'));
  assert.deepEqual(accepted, [{ fixture_origin: "http://127.0.0.1:1234", offline_network: true }]);
  assert.deepEqual(failures, []);
  assert.doesNotThrow(() => parse(Buffer.from('{"fixture_origin":bad}\n'))); assert.equal(failures.length, 1);
  const source = fs.readFileSync(new URL("../../scripts/progressive-slo-api-acceptance.cjs", import.meta.url), "utf8");
  assert.match(source, /if \(stream === backend\.stdout\) parseStartup\(chunk\)/, "stderr cannot corrupt stdout startup framing");
  parse(Buffer.from("x".repeat(65537))); assert.equal(failures.length, 2);
});
test("all cleanup actions run, primary errors survive, and cleanup failures cannot leave a passing report", async () => {
  for (const failing of ["browser", "backend", "report"]) {
    for (const withPrimary of [true, false]) {
      const calls = [], report = { passed: true }, primary = withPrimary ? new Error("primary failure") : undefined;
      const action = name => async () => { calls.push(name); if (name === failing) throw new Error(name + " failed"); };
      const run = () => fixture.finishAcceptance({ closeBrowser: action("browser"), stopBackend: action("backend"),
        save: () => { calls.push("report"); if (failing === "report") throw new Error("report failed"); } }, report, primary);
      if (primary) { await run(); assert.equal(primary.message, "primary failure"); assert.equal(primary.cleanupErrors.length, 1); }
      else await assert.rejects(run, AggregateError);
      assert.deepEqual(calls, ["browser", "backend", "report"]); assert.equal(report.passed, false);
    }
  }
});

test("failed sample remains primary when its checkpoint write also fails", () => {
  const primary = new Error("outline geometry failed"), row = {};
  assert.throws(() => {
    let sampleError;
    try { throw primary; }
    catch (error) { sampleError = error; row.status = "fail"; row.error = error.message; throw error; }
    finally { fixture.saveCheckpoint(() => { throw new Error("disk full"); }, sampleError); }
  }, error => error === primary);
  assert.equal(row.error, "outline geometry failed"); assert.equal(primary.checkpointErrors[0].message, "disk full");
  assert.throws(() => fixture.saveCheckpoint(() => { throw new Error("disk full"); }), /disk full/);
});

test("DOM measurement rejects invisible ancestors despite a visible child box and hit target", async () => {
  const vm = await import("node:vm");
  const rect = { top: 100, bottom: 140, left: 100, right: 600, width: 500, height: 40 };
  const parent = { opacity: "0" }, excerpt = { parentElement: parent, getBoundingClientRect: () => rect,
    innerText: "Reference lesson source statement at 0 seconds.", contains: () => true };
  const list = { tagName: "UL", querySelector: () => excerpt }, warning = { tagName: "BLOCKQUOTE", innerText: "不是 AI 主题总结", nextElementSibling: list };
  const heading = { parentElement: parent, getBoundingClientRect: () => rect, nextElementSibling: warning, contains: () => true };
  const context = vm.createContext({ innerWidth: 1440, innerHeight: 1000, document: { elementFromPoint: () => excerpt },
    getComputedStyle: node => ({ display: "block", visibility: "visible", opacity: node.opacity || "1" }) });
  const measure = vm.runInContext(`(${fixture.outlineGeometry.toString()})`, context);
  assert.equal(readableGeometry(measure(heading)), false);
  parent.opacity = "1"; assert.equal(readableGeometry(measure(heading)), true);
  excerpt.innerText = ""; excerpt.textContent = "Reference lesson source statement at 0 seconds.";
  assert.equal(readableGeometry(measure(heading)), false, "Hidden DOM text is not rendered source text");
});

test("owned Edge launch uses the validated canonical file without command-line telemetry or added flags", () => {
  const first = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
  const second = "C:/Program Files/Microsoft/Edge/Application/msedge.exe";
  const canonical = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
  const io = { existsSync: value => value === first, realpathSync: value => { assert.equal(value, first); return canonical; },
    statSync: value => { assert.equal(value, canonical); return { isFile: () => true }; } };
  assert.deepEqual(fixture.edgeLaunchOptions(undefined, io), { executablePath: canonical, headless: true });
  assert.deepEqual(fixture.edgeLaunchOptions(undefined, { existsSync: value => value === second,
    realpathSync: value => value, statSync: () => ({ isFile: () => true }) }), { executablePath: second, headless: true });
  const source = fs.readFileSync(new URL("../../scripts/progressive-slo-api-acceptance.cjs", import.meta.url), "utf8");
  assert.match(source, /browser = await chromium\.launch\(launchOptions\)/);
  assert.match(source, /executable: launchOptions\.executablePath/);
  assert.match(source, /instance_version: browser\.version\(\)/);
  assert.match(source, /user_agent: navigator\.userAgent/);
  assert.doesNotMatch(source, /getBrowserCommandLine|enable-automation|newBrowserCDPSession/);
});

test("explicit Edge override is validated and cannot fall back to a different installed browser", () => {
  const explicit = "D:/Browsers/Edge/msedge.exe", requested = [];
  const io = { existsSync: value => { requested.push(value); return value === explicit; }, realpathSync: value => value,
    statSync: () => ({ isFile: () => true }) };
  assert.deepEqual(fixture.edgeLaunchOptions(explicit, io), { executablePath: explicit, headless: true });
  assert.deepEqual(requested, [explicit]);
  requested.length = 0;
  assert.throws(() => fixture.edgeLaunchOptions("D:/missing/msedge.exe", io), /not found/);
  assert.deepEqual(requested, ["D:/missing/msedge.exe"]);
});

test("missing files, directories and non-Edge canonical targets fail before launch", () => {
  assert.throws(() => fixture.edgeLaunchOptions(undefined, { existsSync: () => false }), /not found/);
  const io = { existsSync: () => true, realpathSync: value => value, statSync: () => ({ isFile: () => true }) };
  assert.throws(() => fixture.edgeLaunchOptions("D:/msedge.exe", { ...io, statSync: () => ({ isFile: () => false }) }), /must be a file/);
  assert.throws(() => fixture.edgeLaunchOptions("D:/msedge.exe", { ...io, realpathSync: () => "D:/chrome.exe" }), /canonical Microsoft Edge/);
  assert.throws(() => fixture.edgeLaunchOptions("D:/chrome.exe", io), /canonical Microsoft Edge/);
  assert(fixture.edgeExecutable("C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"));
  assert(fixture.edgeExecutable("/opt/microsoft/msedge/msedge"));
  for (const value of [undefined, "chrome.exe", "/usr/bin/chromium", "/tmp/not-msedge", "msedge.exe --fake"])
    assert.equal(fixture.edgeExecutable(value), false);
});

test("SSE identity binds only the exact same-origin task stream and expected cursor query", () => {
  const base = "http://127.0.0.1:4444", route = "/api/tasks/task-01/events/stream";
  assert.deepEqual(fixture.streamIdentity(base + route + "?after=0", base), { task_id: "task-01", origin: base, path: route });
  for (const url of ["http://127.0.0.1:4445" + route + "?after=0", "https://example.test" + route + "?after=0",
    base + route, base + route + "?after=-1", base + route + "?after=1&token=secret", base + route + "?after=1&after=2",
    base + route + "?after=0#other", base + "/api/tasks/task-01/events?after=0", base + route + "/?after=0",
    base + "/api/tasks/bad%2Fid/events/stream?after=0", "http://user:secret@127.0.0.1:4444" + route + "?after=0"])
    assert.equal(fixture.streamIdentity(url, base), null, url);
});

test("native SSE retains real event identity without requiring an invented task_id field", () => {
  const source = { task_id: "task-01", origin: "http://127.0.0.1:4444", path: "/api/tasks/task-01/events/stream" };
  const requests = new Map([["native-request", source]]);
  const event = { requestId: "native-request", eventName: "task_created", eventId: "13", data: JSON.stringify({ event: "task_created", event_id: 13 }) };
  assert.deepEqual(fixture.nativeSseRecord(event, requests), { ...source, request_id: "native-request", event: "task_created", id: "13" });
  assert.equal(fixture.nativeSseRecord({ ...event, data: JSON.stringify({ task_id: "task-01" }) }, requests).task_id, "task-01");
  for (const data of [{ task_id: "wrong-task" }, { task_id: null }, { event_id: 14 }, { event_id: "13" }, { event: "draft_ready" }, null, []])
    assert.throws(() => fixture.nativeSseRecord({ ...event, data: JSON.stringify(data) }, requests));
  assert.throws(() => fixture.nativeSseRecord({ ...event, data: "secret malformed payload" }, requests), error => {
    assert.equal(error.message, "Malformed native SSE JSON"); return true;
  });
  for (const eventId of ["0", "-1", "01", "NaN", "9007199254740992", 13])
    assert.throws(() => fixture.nativeSseRecord({ ...event, eventId }, requests));
  for (const eventName of [undefined, null, "", "bad name", "x".repeat(81)])
    assert.throws(() => fixture.nativeSseRecord({ ...event, eventName, data: "{}" }, requests), /Malformed native SSE event name/);
  assert.throws(() => fixture.nativeSseRecord({ ...event, requestId: "obsolete" }, requests), /no current task-stream/);
});

test("native observer rejects wrong or obsolete request mappings across completion and session replacement", async () => {
  const { EventEmitter } = await import("node:events"), base = "http://127.0.0.1:4444", report = {};
  const cdp = new EventEmitter(), stop = fixture.observeNativeSse(cdp, report, base);
  const request = (task, id = "request", origin = base) => cdp.emit("Network.requestWillBeSent", { requestId: id,
    type: "EventSource", request: { method: "GET", url: origin + `/api/tasks/${task}/events/stream?after=0`, headers: { Authorization: "secret" } } });
  const emit = (id = "request", data = {}) => cdp.emit("Network.eventSourceMessageReceived", {
    requestId: id, eventName: "task_created", eventId: "1", data: JSON.stringify(data) });
  request("right"); emit(); assert.equal(report.native_sse[0].task_id, "right");
  request("other"); emit(); assert.equal(report.native_sse[1].task_id, "other");
  assert.equal(report.native_sse.filter(event => event.task_id === "right").length, 1);
  request("right", "request", "https://example.test"); emit(); assert.equal(report.native_sse.length, 2);
  for (const end of ["Network.loadingFinished", "Network.loadingFailed"]) {
    request("right"); cdp.emit(end, { requestId: "request", canceled: true, errorText: "net::ERR_ABORTED" }); emit();
    assert.equal(report.native_sse.length, 2);
  }
  request("right"); emit("request", { task_id: "conflict" }); assert.equal(report.native_sse.length, 2);
  cdp.emit("Network.responseReceived", { requestId: "request", response: {
    url: base + "/api/tasks/right/events/stream?after=0", status: 200, mimeType: "text/event-stream", headers: { Secret: "private" } } });
  assert(report.network.some(event => event.status === 200 && event.mime_type === "text/event-stream"));
  assert(report.network.some(event => event.event === "stream_failed" && event.error === "net::ERR_ABORTED"));
  assert.equal(report.errors.length, 4); assert.doesNotMatch(JSON.stringify(report), /secret|private|Authorization|\?after/);
  cdp.emit("close"); assert.equal(cdp.eventNames().length, 0); emit(); assert.equal(report.native_sse.length, 2);
  stop();
  const replacement = new EventEmitter(); fixture.observeNativeSse(replacement, report, base);
  replacement.emit("Network.eventSourceMessageReceived", { requestId: "request", eventName: "task_created", eventId: "1", data: "{}" });
  assert.equal(report.native_sse.length, 2); assert.equal(report.errors.length, 5);
  replacement.emit("close");
});

test("network diagnostics omit query values and credentials and bound retained records", async () => {
  assert.deepEqual(fixture.networkLocation("https://user:secret@example.test/route?token=secret#secret"), { origin: "https://example.test", path: "/route" });
  assert.equal(fixture.networkLocation("https://example.test/" + "x".repeat(500)).path.length, 256);
  const { EventEmitter } = await import("node:events"), cdp = new EventEmitter(), report = {};
  const stop = fixture.observeNativeSse(cdp, report, "https://example.test");
  for (let index = 0; index < 300; index++) cdp.emit("Network.requestWillBeSent", { requestId: String(index), type: "Fetch",
    request: { method: "GET", url: "https://example.test/api/update/status?token=secret" } });
  assert.equal(report.network.length, 256); assert.equal(report.network_dropped, 44);
  assert.equal(report.network[0].request_id, "44"); assert.doesNotMatch(JSON.stringify(report), /secret|token/); stop();
  const source = fs.readFileSync(new URL("../../scripts/progressive-slo-api-acceptance.cjs", import.meta.url), "utf8");
  assert.match(source, /boundedRecord\(report, "native_sse", nativeSseRecord\(event, requests\), 8192\)/);
  assert.match(source, /page\.once\("close", stopObserving\)/);
  assert(source.indexOf("stopObserving?.();") < source.indexOf("page = await context.newPage()"));
});

test("optional failure diagnostics are deadline-bounded and cannot replace the primary error or skip cleanup", async () => {
  const calls = [], primary = new Error("original stream assertion"), report = { passed: true, failure: primary.stack };
  await fixture.recordFailureDiagnostics(report, {
    screenshot: () => { calls.push("screenshot"); throw new Error("capture failed"); },
    stalled: () => new Promise(() => {}),
    page: () => { calls.push("page"); return { ready_state: "complete" }; },
  }, 10);
  assert.deepEqual(calls, ["screenshot", "page"]);
  assert.deepEqual(report.failure_diagnostics, { page: { ready_state: "complete" } });
  assert.deepEqual(report.diagnostic_errors.map(row => row.operation), ["screenshot", "stalled"]);
  assert.equal(report.diagnostic_errors[1].error, "Diagnostic timed out");
  await fixture.finishAcceptance({ closeBrowser: async () => calls.push("browser"), stopBackend: async () => calls.push("backend"),
    save: () => calls.push("save") }, report, primary);
  assert.equal(report.failure, primary.stack); assert.equal(report.passed, false);
  assert.deepEqual(calls.slice(-3), ["browser", "backend", "save"]);
});

test("accepted identity is checkpointed before preparation can fail and failure capture is viewport-bounded", () => {
  const source = fs.readFileSync(new URL("../../scripts/progressive-slo-api-acceptance.cjs", import.meta.url), "utf8");
  const prepare = source.slice(source.indexOf("async function prepare("), source.indexOf("async function submit("));
  assert(prepare.indexOf("report.current_task_id = id; if (record) record.task_id = id; save();") < prepare.indexOf("await page.goto("));
  assert.match(source, /path: path\.join\(out, "failure\.png"\), animations: "disabled", timeout: 5000/);
  assert.doesNotMatch(source, /fullPage:\s*true/);
  assert.match(source, /normal settings startup response/); assert.match(source, /state\.update_preferences\.auto_check, false/);
});
