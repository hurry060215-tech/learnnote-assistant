import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { Readable } from 'node:stream';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
const source = fs.readFileSync(new URL('../../scripts/task-diagnostic-preview-acceptance.cjs', import.meta.url), 'utf8');
for (const scenario of ['launch', 'context', 'context+close+write', 'launch+write']) {
  test(`hosted fixture owns cleanup and preserves original ${scenario} failure`, async () => {
    let closed = 0; const written = [], logged = [], primary = new Error(scenario.startsWith('launch') ? 'launch failed' : 'context failed');
    const process = { argv: ['node', 'fixture'], env: {}, exitCode: 0 };
    const browser = { async newContext() { throw primary; }, async close() { closed++; if (scenario.includes('close')) throw new Error('close failed'); } };
    const require = name => {
      if (name === 'playwright') return { chromium: { async launch() { if (scenario.startsWith('launch')) throw primary; return browser; } } };
      if (name === 'node:assert/strict') return assert;
      if (name === 'node:path') return path;
      if (name === 'node:fs') return { mkdirSync() {}, writeFileSync(_file, value) { if (scenario.includes('write')) throw new Error('write failed'); written.push(JSON.parse(value)); } };
      if (name === './classic-visual-study-fixture.cjs') return { fixtureResponse() {}, createStudyPlan() {}, TASK_ID: 'synthetic' };
      throw new Error(`Unexpected import ${name}`);
    };
    await vm.runInNewContext(source, { require, __dirname: '/fixture/scripts', process, console: { error(value) { logged.push(value); } } });
    assert.equal(process.exitCode, 1); assert.equal(logged.at(-1), primary);
    assert.equal(closed, scenario.startsWith('launch') ? 0 : 1);
    if (!scenario.includes('write')) { assert.equal(written.length, 1); assert.equal(written[0].passed, false); assert.equal(written[0].failure, primary.message); }
  });
}
test('hosted diagnostic route is task- and query-exact; unknown routes abort and fail acceptance', () => {
  assert.match(source, /name === `\/api\/tasks\/\$\{TASK_ID\}\/exports\/diagnostics` && \['', '\?format=json'\]\.includes\(url.search\)/);
  assert.match(source, /report.unexpected.push/); assert.match(source, /assert.deepEqual\(report.unexpected, \[\]\)/);
  assert.doesNotMatch(source, /name.endsWith\('\/exports\/diagnostics'\)/);
});

test("native mode closes its owned server after connection failure and retains the primary failure", async () => {
  const primary = new Error("connect failed"), logged = []; let closed = 0;
  const process = { argv: ["node", "fixture", "out", "--native"], platform: "win32", env: {}, exitCode: 0 };
  const require = name => {
    if (name === "playwright") return { chromium: { async launchServer() { return { process: () => ({ pid: 123 }), wsEndpoint: () => "ws://owned", async close() { closed++; throw new Error("server cleanup failed"); } }; }, async connect() { throw primary; } } };
    if (name === "node:assert/strict") return assert;
    if (name === "node:path") return path;
    if (name === "node:fs") return { mkdirSync() {}, writeFileSync() { throw new Error("write failed"); } };
    if (name === "./classic-visual-study-fixture.cjs") return { TASK_ID: "synthetic" };
    throw new Error(`Unexpected import ${name}`);
  };
  await vm.runInNewContext(source, { require, __dirname: "/fixture/scripts", process, console: { error(value) { logged.push(value); } } });
  assert.equal(closed, 1); assert.equal(logged.at(-1), primary); assert.equal(process.exitCode, 1);
});

test("fixture rejects wrong asset/API methods and unapproved querystrings before serving data", () => {
  const context = { TASK_ID: "synthetic" }; vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf("function fixtureTransportAllowed("), source.indexOf("const native =")), context);
  const allow = (method, route) => context.fixtureTransportAllowed(method, new URL(route, "http://127.0.0.1:8765"));
  for (const route of ["/web/desk.js", "/web/index.html?task=synthetic&tab=diagnostics", "/web/desk.css?v=version-1"]) {
    assert.equal(allow("GET", route), true); assert.equal(allow("POST", route), false); assert.equal(allow("DELETE", route), false);
  }
  for (const route of ["/api/model/connection?secret=x", "/api/preferences?other=true", "/api/tasks?all=true", "/api/tasks/synthetic/exports/diagnostics?format=zip", "/web/desk.js?callback=x"]) assert.equal(allow("GET", route), false);
  assert.equal(allow("GET", "/api/tasks/synthetic/exports/diagnostics?format=json"), true);
  assert.equal(allow("POST", "/api/study/activity?unexpected=1"), false);
});

for (const captureFails of [false, true]) test(`native failure page capture ${captureFails ? "failure" : "success"} preserves original error and independent cleanup`, async () => {
  const primary = new Error("owned capture failed"), logged = [], actions = []; let closed = 0, serverClosed = 0, captured = 0, report;
  const process = { argv: ["node", "fixture", "out", "--native"], platform: "win32", env: {}, exitCode: 0 };
  const locator = { async inputValue() { return "md"; }, async isChecked() { return false; }, async isDisabled() { return true; }, getByText() { return this; }, getByRole() { return this; }, async waitFor() {}, filter() { return this; }, locator() { return this; }, async click() {} };
  const page = { async screenshot(options) { captured++; assert.equal(options.fullPage, true); assert.equal(options.timeout, 15000); assert.equal(path.basename(options.path), "desk-failure-page.png"); if (captureFails) throw new Error("capture failed"); }, setDefaultTimeout() {}, on() {}, async goto() {}, locator() { return locator; }, async bringToFront() {}, async waitForFunction() {}, async evaluate() { return { width: 1440, height: 900, dpr: 1, cssZoom: "1", documentZoom: "1", visualScale: 1, overflow: 0 }; } };
  const browser = { async newContext() { return { async route() {}, async newPage() { return page; } }; }, async close() { closed++; throw new Error("browser cleanup failed"); } };
  const require = name => {
    if (name === "playwright") return { chromium: { async launchServer() { return { process: () => ({ pid: 123 }), wsEndpoint: () => "ws://owned", async close() { serverClosed++; throw new Error("server cleanup failed"); } }; }, async connect() { return browser; } } };
    if (name === "node:assert/strict") return assert;
    if (name === "node:path") return path;
    if (name === "node:fs") return { mkdirSync() {}, writeFileSync(_file, value) { report = JSON.parse(value); throw new Error("write failed"); } };
    if (name === "node:child_process") return { execFileSync(_command, args) { const action = args[args.indexOf("-Zoom") + 1]; actions.push(action); if (action === "prepare") { assert(!args.includes("-ExpectedWindow")); return JSON.stringify({ owned_pid: 123, window: 456, process_start: "638000000000000000" }); } assert.equal(args[args.indexOf("-ExpectedWindow") + 1], "456"); assert.equal(args[args.indexOf("-ExpectedProcessStart") + 1], "638000000000000000"); if (action === "capture") throw primary; if (action === "reset" && actions.includes("capture")) throw new Error("reset failed"); return "{}"; } };
    if (name === "./classic-visual-study-fixture.cjs") return { TASK_ID: "synthetic", createStudyPlan() {} };
    if (name === "./timeline-native-zoom-matrix.cjs") return { assertZoomMetrics() {}, async waitForNativePreset() { return { dpr: 2 }; } };
    throw new Error(`Unexpected import ${name}`);
  };
  await vm.runInNewContext(source, { require, __dirname: "/fixture/scripts", process, console: { error(value) { logged.push(value); } } });
  assert.deepEqual(actions, ["prepare", "dismiss-translation", "reset", "200", "capture", "reset"]);
  assert.equal(closed, 1); assert.equal(serverClosed, 1); assert.equal(logged.at(-1), primary); assert.equal(process.exitCode, 1);
  assert.equal(captured, 1); assert.equal(report.currentCase.surface, 'desk');
  assert.equal(report.currentCase.phase, 'native-preview-capture'); assert.equal(report.currentCase.zoomEvidence.zoomed.dpr, 2);
  assert.equal(report.failureCaptureError, captureFails ? 'Synthetic page failure capture unavailable' : undefined);
  assert.deepEqual(report.screenshots, captureFails ? [] : ['desk-failure-page.png']);
});

test("actual settings startup model-route query has one explicit synthetic response", () => {
  const settings = fs.readFileSync(new URL("../desk-settings.js", import.meta.url), "utf8");
  assert.match(settings, /loadModelRoute\(\);\s+load\(\);/);
  assert.match(settings, /id="prefWhisper"[^>]+value="small"/);
  const context = { TASK_ID: "synthetic", URLSearchParams, pref: {}, $: id => ({ value: id === "prefTranscriber" ? "faster-whisper" : "small" }) };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf("function fixtureTransportAllowed("), source.indexOf("const native =")), context);
  const start = settings.indexOf("      const query = new URLSearchParams({");
  const end = settings.indexOf("      const route = await api", start);
  vm.runInContext(settings.slice(start, end) + ";globalThis.queryValue = String(query);", context);
  const route = "/api/model/route?" + context.queryValue;
  assert.equal(context.fixtureTransportAllowed("GET", new URL(route, "http://127.0.0.1:8765")), true);
  assert.ok(source.includes(`'${route}': { routes: []`));
  assert.equal(context.fixtureTransportAllowed("GET", new URL(route + "&unexpected=true", "http://127.0.0.1:8765")), false);
});

test("hosted entry follows shipped collapsed disclosures through real summary clicks", async () => {
  const tools = fs.readFileSync(new URL("../desk-tools.js", import.meta.url), "utf8");
  const classic = fs.readFileSync(new URL("../classic.html", import.meta.url), "utf8");
  const reader = fs.readFileSync(new URL("../../scripts/reader-workflow-acceptance.cjs", import.meta.url), "utf8");
  assert.match(tools, /<details><summary>诊断详情与安全报告<\/summary>[^]*?<button data-safe-diagnostic-report/);
  assert.match(classic, /<details id="resultMoreActions"[^>]*>\s*<summary[^>]*aria-label="更多操作"/);
  assert.match(reader, /getByText\("诊断详情与安全报告", \{ exact: true \}\).click\(\)/);
  assert.match(reader, /getByRole\("button", \{ name: "预览安全诊断报告", exact: true \}\)/);
  assert.doesNotMatch(source + reader, /诊断详情与日志下载|脱敏诊断包|name: "逐步日志 JSON"|\.open\s*=\s*true/);
  const context = {}; vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf("async function openDiagnosticEntry("), source.indexOf("const native =")), context);
  for (const surface of ["desk", "classic"]) {
    let disclosed = false, visible = false; const clicks = [];
    const button = { async waitFor(options) { assert.equal(options.state, "visible"); assert(disclosed); visible = true; } };
    const page = { async waitForFunction() {}, async evaluate() {}, locator(selector) {
      if (selector === "#toolsDialog[open]") return {
        getByText(text, options) { assert.equal(text, "诊断详情与安全报告"); assert.equal(options.exact, true); return { async click() { disclosed = true; clicks.push("desk-summary"); } }; },
        getByRole(role, options) { assert.equal(role, "button"); assert.equal(options.name, "预览安全诊断报告"); assert.equal(options.exact, true); return button; },
      };
      if (selector === "#resultMoreActions > summary") return { async click() { disclosed = true; clicks.push("classic-summary"); } };
      assert.equal(selector, "#diagnosticsButton"); assert(disclosed); visible = true; return button;
    } };
    assert.equal(await context.openDiagnosticEntry(page, surface), button);
    assert.equal(visible, true); assert.deepEqual(clicks, [surface + "-summary"]);
  }
});

test("whole-page browser Back is explicit and follows verified native zoom restoration", () => {
  const seed = source.indexOf("await page.goto('about:blank#diagnostic-history-start')");
  const app = source.indexOf("await page.goto(`${base}/web/");
  const restored = source.indexOf("zoomEvidence.restored =");
  const back = source.indexOf("await page.goBack({ waitUntil: 'load' })");
  assert(seed >= 0 && seed < app && restored < back);
  assert.match(source.slice(back), /assert.equal\(page.url\(\), 'about:blank#diagnostic-history-start'\)/);
  assert.match(source.slice(back), /await dialog.waitFor\(\{ state: 'detached' \}\); assert.equal\(downloads, 2\)/);
  assert.match(source.slice(back), /wholePageBrowserBack: true/);
});

function downloadAssertion() {
  const context = { assert, Buffer }; vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('async function assertDownloadedBytes('), source.indexOf('async function openDiagnosticEntry(')), context);
  assert.match(source, /await assertDownloadedBytes\(download, Buffer.from\(bytes\)\)/);
  assert.doesNotMatch(source, /download\.(?:path|saveAs)\(/);
  return context.assertDownloadedBytes;
}
test('remote download stream preserves exact multibyte, BOM and CRLF bytes across chunks', async () => {
  const expected = Buffer.from('\ufeff报告\r\n<img src=x>'), stream = Readable.from([expected.subarray(0, 4), expected.subarray(4)]);
  let reads = 0;
  await downloadAssertion()({ async createReadStream() { reads++; return stream; } }, expected);
  assert.equal(reads, 1); assert.equal(stream.destroyed, true);
});
test('remote download creation and midstream failures retain the original error', async () => {
  const primary = new Error('synthetic stream failure'), check = downloadAssertion();
  await assert.rejects(check({ async createReadStream() { throw primary; } }, Buffer.from('abc')), error => error === primary);
  const stream = Readable.from((async function* () { yield Buffer.from('a'); throw primary; })());
  await assert.rejects(check({ async createReadStream() { return stream; } }, Buffer.from('abc')), error => error === primary);
  assert.equal(stream.destroyed, true);
});
test('remote download null, oversized, truncated and changed bytes fail closed', async () => {
  const check = downloadAssertion(), expected = Buffer.from('abc');
  await assert.rejects(check({ async createReadStream() { return null; } }, expected), /must provide a readable stream/);
  for (const bytes of ['abcd', 'ab', 'abd']) {
    const stream = Readable.from([Buffer.from(bytes)]);
    await assert.rejects(check({ async createReadStream() { return stream; } }, expected), bytes.length > 3 ? /exceeds expected byte length/ : /deep-equal/);
    assert.equal(stream.destroyed, true);
  }
});

test('native prepared-window predicate rejects identity and window replacement faults', { skip: process.platform !== 'win32' }, () => {
  execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-File', fileURLToPath(new URL('../../scripts/tests/task-diagnostic-window-binding.ps1', import.meta.url))], { timeout: 15000, stdio: 'pipe' });
});
