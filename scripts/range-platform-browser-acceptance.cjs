/* Real Edge DOM rendering; synthetic Chrome transport and local-service replies.
 * No native extension install, permission prompt, website, media or model access.
 * Run: node scripts/range-platform-browser-acceptance.cjs build/range-platform-ui
 */
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path"), http = require("node:http");
const {createHash} = require("node:crypto");
const {execFileSync} = require("node:child_process");
const {FIXTURE, installFixtures, asset, writeFailureEvidence} = require("./extension-locale-visual-acceptance.cjs");
const ROOT = path.resolve(__dirname, "..");
const MODES = ["current5", "current15", "current30", "chapter", "custom"];
const TIMEOUT = 10000;

function loadCases(file = path.join(__dirname, "fixtures/range-platform-cases.json")) {
  const bytes = fs.readFileSync(file), cases = JSON.parse(bytes);
  assert.deepEqual(cases.map(item => item.id), ["bilibili", "youtube", "html5"]);
  assert.deepEqual(cases.map(item => item.page_url), [
    "https://www.bilibili.com/video/BV1SYNTHETIC?p=2",
    "https://www.youtube.com/watch?v=abcdefghijk", "https://example.com/synthetic-lesson"
  ]);
  for (const item of cases) {
    assert.equal(item.current_time, 300.25); assert.equal(item.duration, 600);
    assert.deepEqual(item.custom_range, {start: 300.25, end: 420.75});
    assert.deepEqual(item.chapters, [{...item.custom_range, title: "Synthetic selected chapter"}]);
    assert.match(item.title, /^Synthetic range lesson /);
  }
  return {cases, sha256: createHash("sha256").update(bytes).digest("hex")};
}
function scenarios(item) {
  return [...MODES.flatMap(mode => (mode.startsWith("current") ? [600, 2400] : [600]).map(duration => ({mode, duration, outcome: "sent"}))),
    ...["page-mismatch", "tab-mismatch", ...(item.id === "bilibili" ? ["part-mismatch"] : []),
      "permission-denied", "permission-dismissed"].map(outcome => ({mode: "custom", duration: 600, outcome}))];
}
function expectedRange(item, mode) {
  if (mode.startsWith("current")) return {start: item.current_time, end: Math.min(item.duration, item.current_time + Number(mode.slice(7)) * 60)};
  return mode === "chapter" ? {start: item.chapters[0].start, end: item.chapters[0].end} : item.custom_range;
}
function expectedSource(item) {
  return {tab_id: 7, canonical_page_url: item.page_url,
    platform: item.id === "html5" ? "example.com" : item.id,
    platform_video_id: item.id === "bilibili" ? "BV1SYNTHETIC" : item.id === "youtube" ? "abcdefghijk" : "",
    BVID: item.id === "bilibili" ? "BV1SYNTHETIC" : "", page_title: item.title,
    active_video: {current_src: `https://example.com/synthetic-${item.id}.mp4`}};
}
function isAssetRequest(url, method, origin) {
  try { return new URL(url).origin === origin && method === "GET" && Boolean(asset(url)); }
  catch { return false; }
}

// Serialized after the existing locale fixture in ONE init script, so ordering
// never depends on Playwright's ordering of separate addInitScript calls.
function installRangeFixture({item, outcome}) {
  const control = globalThis.__localeFixture, originalFetch = globalThis.fetch;
  const source = `https://example.com/synthetic-${item.id}.mp4`;
  control.context = {tab: {id: 7, url: item.page_url, title: item.title}, resources: [], page: {
    page_url: item.page_url, title: item.title,
    active_video: {src: source, duration: item.duration, current_time: item.current_time, paused: true, has_audio: true},
    browser_subtitles: Array.from({length: 12}, (_, i) => ({start: i * item.duration / 12, end: (i + 1) * item.duration / 12, text: `Synthetic source caption ${i + 1}`})),
    subtitle_probe: {status: "ready", elapsed_ms: 1}, chapters: item.chapters
  }};
  control.requests = []; control.permissionRequests = []; control.runtimeResponses = 0;
  control.permissionDecision = outcome.startsWith("permission-") ? outcome : "already-granted";
  const reject = description => { control.unexpected.push(description); throw Error(`Unexpected range fixture request: ${description}`); };
  globalThis.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    const method = String(options.method || input?.method || "GET").toUpperCase();
    const allowed = url.origin === "http://127.0.0.1:8765" && !url.search && !url.hash && method === "GET" &&
      ["/health", "/api/preferences", "/api/tasks/locale-fixture", "/api/tasks/locale-fixture/note", "/api/tasks/locale-fixture/transcript"].includes(url.pathname);
    if (!allowed) return reject(`${method} ${url.origin}${url.pathname}${url.search}`);
    control.requests.push({method, path: url.pathname});
    if (url.pathname === "/api/tasks/locale-fixture") return new Response(JSON.stringify({task: {
      id: "locale-fixture", status: "success", note_path: "synthetic-note", options: {content_mode: "subtitles"}
    }}), {status: 200, headers: {"Content-Type": "application/json"}});
    if (url.pathname === "/api/tasks/locale-fixture/transcript") return new Response(JSON.stringify({segments: control.context.page.browser_subtitles}), {status: 200});
    return originalFetch(input, options);
  };
  const runtime = chrome.runtime.sendMessage;
  chrome.runtime.sendMessage = async message => {
    if (!["get-current-context", "start-current-task"].includes(message.type)) return reject(`chrome.runtime ${message.type}`);
    const response = await runtime(message);
    control.runtimeResponses++;
    // Real Chrome messaging serializes responses. Never share a mutable page
    // object with the panel when switching the next context during Send.
    return JSON.parse(JSON.stringify(response));
  };
  const origin = new URL(item.page_url).origin + "/*";
  chrome.permissions.contains = async () => !outcome.startsWith("permission-");
  chrome.permissions.getAll = async () => ({origins: outcome.startsWith("permission-") ? [] : [origin]});
  chrome.permissions.request = async request => {
    control.permissionRequests.push(request);
    if (!outcome.startsWith("permission-")) return reject("unexpected synthetic permission request");
    // Denial and dismissal both return false. No native prompt is opened.
    return false;
  };
  chrome.permissions.remove = async () => reject("chrome.permissions.remove");
  chrome.tabs.create = async () => reject("chrome.tabs.create");
  chrome.tabs.update = async () => reject("chrome.tabs.update");
}
function initScript(catalog, item, outcome) {
  const fixture = {...FIXTURE, title: item.title, duration: item.duration, chapters: item.chapters};
  return `(${installFixtures.toString()})(${JSON.stringify({locale: "en-US", catalog, fixture})});\n(${installRangeFixture.toString()})(${JSON.stringify({item, outcome})});`;
}
function changeNextContext(outcome) {
  const fixture = globalThis.__localeFixture;
  const next = JSON.parse(JSON.stringify(fixture.context));
  if (outcome === "tab-mismatch") next.tab.id = 8;
  if (outcome === "part-mismatch") next.page.page_url = next.tab.url = next.page.page_url.replace("p=2", "p=3");
  if (outcome === "page-mismatch") next.page.page_url = next.tab.url = "https://example.com/different-synthetic-lesson";
  fixture.context = next;
}
function assertStart(message, item, mode) {
  assert.equal(message.type, "start-current-task");
  assert.equal(message.targetTabId, 7); assert.equal(message.mode, "subtitle_only");
  assert.equal(message.options.content_mode, "subtitles"); assert.equal(message.options.visual_understanding, false); assert.equal(message.defer, false);
  assert.equal(message.backendUrl, "http://127.0.0.1:8765");
  assert.deepEqual(message.resources, []); assert.deepEqual(message.learning_range, expectedRange(item, mode));
  assert.equal(message.page.page_url, item.page_url); assert.equal(message.page.title, item.title);
  assert.deepEqual(message.page.chapters, item.chapters);
  assert.equal(message.page.active_video.duration, item.duration); assert.equal(message.page.active_video.current_time, item.current_time);
  assert.equal(message.page.active_video.src, expectedSource(item).active_video.current_src);
  const {captured_at, resource_fingerprint, ...source} = message.sourceIdentity;
  assert.deepEqual(source, expectedSource(item));
  assert.match(captured_at, /^\d{4}-\d{2}-\d{2}T/); assert.match(resource_fingerprint, /^[0-9a-f]{8}$/);
  assert.match(message.handoffId, /^ln-[0-9a-f]{8}-[a-z0-9]+$/);
}
async function bounded(promise, label, timeout = TIMEOUT) {
  let timer;
  try { return await Promise.race([promise, new Promise((_, reject) => {timer = setTimeout(() => reject(Error(`${label} timed out`)), timeout);})]); }
  finally { clearTimeout(timer); }
}
async function cleanup(primary, actions) {
  const failures = [];
  for (const [label, action] of actions) {
    try { await bounded(Promise.resolve().then(action), label, 3000); }
    catch (error) { failures.push(`${label}: ${error.message}`); }
  }
  if (primary) { if (failures.length) primary.cleanup_errors = [...(primary.cleanup_errors || []), ...failures]; throw primary; }
  if (failures.length) throw Error(failures.join("; "));
}
function writeReport(out, report, primary, write = fs.writeFileSync) {
  try { write(path.join(out, "report.json"), JSON.stringify(report, null, 2) + "\n"); }
  catch (error) {
    if (!primary) throw error;
    primary.report_write_error = error.message;
  }
  if (primary) throw primary;
}

async function exercise({browser, origin, out, catalog, item, scenario, active}) {
  const context = await bounded(browser.newContext({viewport: {width: 576, height: 1000}, locale: "en-US", reducedMotion: "reduce", serviceWorkers: "block"}), "create browser context");
  let primary;
  try {
    const network = [], errors = [], failed = [], badResponses = [];
    await context.route("**/*", async route => {
      const request = route.request(), url = new URL(request.url());
      if (isAssetRequest(url.href, request.method(), origin)) return route.continue();
      network.push(`${request.method()} ${url.origin}${url.pathname}`); await route.abort("blockedbyclient");
    });
    const page = await bounded(context.newPage(), "create panel page");
    page.setDefaultTimeout(TIMEOUT); page.setDefaultNavigationTimeout(TIMEOUT);
    Object.assign(active, {page, item: {id: item.id, ...scenario}, errors, failedRequests: failed, badResponses});
    page.on("pageerror", error => errors.push(error.message));
    page.on("requestfailed", request => failed.push({url: request.url(), error: request.failure()?.errorText}));
    page.on("response", response => { if (response.status() >= 400) badResponses.push({url: response.url(), status: response.status()}); });
    await page.addInitScript({content: initScript(catalog, item, scenario.outcome)});
    active.phase = "load-rendered-panel";
    await page.goto(`${origin}/extension/sidepanel.html`, {waitUntil: "domcontentloaded"});
    await page.locator("#sourcePreviewCard").waitFor({state: "visible"});
    await bounded(page.evaluate(() => __localeFixture.connect()), "connect fixture");
    await page.waitForFunction(() => __learnnoteSidepanel.getState().clientConnected && !document.querySelector("#sendButton").disabled);
    assert.equal(await page.locator("#videoTitle").innerText(), item.title);
    await page.locator('[data-processing-mode="quick"]').click();
    assert.equal(await page.locator('[data-processing-mode="quick"]').getAttribute("aria-checked"), "true");
    active.phase = "select-range-through-dom";
    await page.locator("#learningRangeOptions > summary").click();
    await page.locator("#learningRangeMode").selectOption(scenario.mode);
    const range = expectedRange(item, scenario.mode);
    if (scenario.mode === "custom") {
      await page.locator("#learningRangeStart").fill(String(range.start));
      await page.locator("#learningRangeEnd").fill(String(range.end));
    }
    await page.waitForFunction(({start, end}) => document.querySelector("#learningRangeStart").value === String(start) && document.querySelector("#learningRangeEnd").value === String(end), range);
    assert.equal(await page.locator("#learningRangeMode").inputValue(), scenario.mode);
    assert.equal(await page.locator("#learningRangeStatus").innerText(), "");
    const prefix = `${item.id}-${scenario.mode}-${item.duration}-${scenario.outcome}`;
    await page.locator("#learningRangeOptions").screenshot({path: path.join(out, `${prefix}-selected.png`), timeout: TIMEOUT});
    if (scenario.outcome.endsWith("mismatch")) await bounded(page.evaluate(changeNextContext, scenario.outcome), "change next context");
    active.phase = "click-send-and-await-response";
    await page.locator("#sendButton").click();
    // A click alone is not completion: wait for async permission/context/start
    // handling and the rendered terminal result or the explicit rejection.
    await page.waitForFunction(() => !__learnnoteSidepanel.getState().sending && document.querySelector("#sendButton").getAttribute("aria-busy") === "false");
    if (scenario.outcome === "sent") {
      await page.locator("#quickTranscriptPanel .quick-transcript-cue").first().waitFor({state: "visible"});
      await page.waitForFunction(() => document.querySelector("#handoffProgress").getAttribute("aria-valuenow") === "100");
    } else {
      await page.waitForFunction(() => document.querySelector("#handoffProgress").dataset.state === "error" && document.querySelector("#handoffStatus").textContent.length > 0);
    }
    const observed = await bounded(page.evaluate(() => ({sent: __localeFixture.sent, unexpected: __localeFixture.unexpected,
      requests: __localeFixture.requests, permission_requests: __localeFixture.permissionRequests,
      runtime_responses: __localeFixture.runtimeResponses, task_id: __learnnoteSidepanel.getState().currentTaskId,
      status: document.querySelector("#handoffStatus").textContent})), "read transport evidence");
    const starts = observed.sent.filter(message => message.type === "start-current-task");
    assert.equal(starts.length, scenario.outcome === "sent" ? 1 : 0);
    if (starts.length) assertStart(starts[0], item, scenario.mode);
    else assert.equal(observed.task_id, "");
    assert.equal(observed.permission_requests.length, scenario.outcome.startsWith("permission-") ? 1 : 0);
    if (observed.permission_requests.length) assert.deepEqual(observed.permission_requests[0], {origins: [new URL(item.page_url).origin + "/*"]});
    assert(observed.runtime_responses >= 1); assert.deepEqual(observed.unexpected, []);
    assert.deepEqual(network, []); assert.deepEqual(errors, []); assert.deepEqual(failed, []); assert.deepEqual(badResponses, []);
    active.phase = "capture-result";
    await page.screenshot({path: path.join(out, `${prefix}-result.png`), fullPage: true, timeout: TIMEOUT});
    return {id: item.id, ...scenario, selected_range: range, source_part: new URL(item.page_url).searchParams.get("p"),
      ...observed, starts: starts.length, blocked_network_requests: network, page_errors: errors,
      screenshots: [`${prefix}-selected.png`, `${prefix}-result.png`]};
  } catch (error) {
    primary = error;
    try { await writeFailureEvidence({...active, out, sourceSha: active.sourceSha, error}); }
    catch (diagnosticError) { error.diagnostic_error = diagnosticError.message; }
  } finally {
    await cleanup(primary, [["browser context close", () => context.close()]]);
    active.page = null;
  }
}

async function run(out = path.resolve(process.argv[2] || "build/range-platform-ui")) {
  assert(!fs.existsSync(out) || fs.readdirSync(out).length === 0, "Use a new or empty output directory; stale reports are not reusable evidence");
  fs.mkdirSync(out, {recursive: true});
  const report = {schema_version: 1, passed: false, source_sha: execFileSync("git", ["rev-parse", "HEAD"], {cwd: ROOT, encoding: "utf8"}).trim(),
    browser: null, browser_channel: "msedge", rendering: "real Edge DOM with mocked Chrome transport",
    synthetic_platform_contexts: true, native_extension_installation_or_permission_prompts_tested: false,
    backend: "synthetic local-service replies; actual admission/processor evidence is a separate gate",
    screenshot_scope: "range selector and Chrome submission only; completion replies contain full synthetic captions, not processed range output",
    model_provider_or_media_calls: false, permission_dismissal: "mock permissions.request false; no native prompt",
    screenshots_visually_reviewed: false, cases: []};
  let browser, server, primary;
  const active = {sourceSha: report.source_sha, phase: "setup"};
  try {
    const loaded = loadCases(); report.fixture_sha256 = loaded.sha256;
    const catalog = JSON.parse(fs.readFileSync(path.join(ROOT, "extension/_locales/en/messages.json"), "utf8"));
    server = http.createServer((request, response) => {
      const file = request.method === "GET" && asset(request.url);
      if (!file) { response.writeHead(404); response.end(); return; }
      response.setHeader("Content-Type", file.endsWith(".css") ? "text/css" : file.endsWith(".js") ? "text/javascript" : file.endsWith(".png") ? "image/png" : "text/html");
      fs.createReadStream(file).pipe(response);
    });
    await bounded(new Promise((resolve, reject) => {server.once("error", reject); server.listen(0, "127.0.0.1", resolve);}), "listen for extension assets");
    browser = await require("playwright").chromium.launch({channel: "msedge", headless: true, chromiumSandbox: true, timeout: 15000});
    report.browser = browser.version();
    const origin = `http://127.0.0.1:${server.address().port}`;
    for (const item of loaded.cases) for (const scenario of scenarios(item)) {
      report.cases.push(await exercise({browser, origin, out, catalog, item: {...item, duration: scenario.duration}, scenario, active}));
    }
  } catch (error) {
    primary = error; report.error = {name: error.name, message: error.message, phase: active.phase, case: active.item || null};
  }
  try {
    await cleanup(primary, [["browser close", () => browser?.close()], ["asset server close", () => {
      if (!server?.listening) return;
      server.closeAllConnections(); return new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
    }]]);
    report.passed = true;
  } catch (error) {
    primary = error;
    report.error ||= {name: error.name, message: error.message, phase: "cleanup"};
    report.cleanup_errors = error.cleanup_errors || [];
  }
  writeReport(out, report, primary);
  console.log(JSON.stringify({passed: true, cases: report.cases.length, out, rendering: report.rendering}));
  return report;
}
module.exports = {loadCases, scenarios, expectedRange, expectedSource, isAssetRequest, initScript, changeNextContext, assertStart, bounded, cleanup, writeReport, run};
if (require.main === module) run().catch(error => {console.error(error); process.exitCode = 1;});
