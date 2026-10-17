import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
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

test("native post-zoom capture failure still resets and closes owned process despite cleanup failures", async () => {
  const primary = new Error("owned capture failed"), logged = [], actions = []; let closed = 0, serverClosed = 0;
  const process = { argv: ["node", "fixture", "out", "--native"], platform: "win32", env: {}, exitCode: 0 };
  const locator = { async waitFor() {}, filter() { return this; }, locator() { return this; }, async click() {} };
  const page = { setDefaultTimeout() {}, on() {}, async goto() {}, locator() { return locator; }, async bringToFront() {}, async waitForFunction() {}, async evaluate() { return { width: 1440, height: 900, dpr: 1, cssZoom: "1", documentZoom: "1", visualScale: 1, overflow: 0 }; } };
  const browser = { async newContext() { return { async route() {}, async newPage() { return page; } }; }, async close() { closed++; throw new Error("browser cleanup failed"); } };
  const require = name => {
    if (name === "playwright") return { chromium: { async launchServer() { return { process: () => ({ pid: 123 }), wsEndpoint: () => "ws://owned", async close() { serverClosed++; throw new Error("server cleanup failed"); } }; }, async connect() { return browser; } } };
    if (name === "node:assert/strict") return assert;
    if (name === "node:path") return path;
    if (name === "node:fs") return { mkdirSync() {}, writeFileSync() { throw new Error("write failed"); } };
    if (name === "node:child_process") return { execFileSync(_command, args) { const action = args[args.indexOf("-Zoom") + 1]; actions.push(action); if (action === "capture") throw primary; if (action === "reset" && actions.includes("capture")) throw new Error("reset failed"); return "{}"; } };
    if (name === "./classic-visual-study-fixture.cjs") return { TASK_ID: "synthetic", createStudyPlan() {} };
    if (name === "./timeline-native-zoom-matrix.cjs") return { assertZoomMetrics() {}, async waitForNativePreset() { return { dpr: 2 }; } };
    throw new Error(`Unexpected import ${name}`);
  };
  await vm.runInNewContext(source, { require, __dirname: "/fixture/scripts", process, console: { error(value) { logged.push(value); } } });
  assert.deepEqual(actions, ["prepare", "dismiss-translation", "reset", "200", "capture", "reset"]);
  assert.equal(closed, 1); assert.equal(serverClosed, 1); assert.equal(logged.at(-1), primary); assert.equal(process.exitCode, 1);
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
