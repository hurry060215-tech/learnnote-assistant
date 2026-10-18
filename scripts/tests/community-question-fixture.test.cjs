const assert = require("node:assert/strict");
const test = require("node:test");
const { EventEmitter } = require("node:events");
const { spawnSync } = require("node:child_process");
const { readFileSync } = require("node:fs");
const vm = require("node:vm");
const { pagingViewportState, browserLaunchOptions, navigateHome, answerViewportState, unexpectedDialog, withHeldPreview, stopFixtureProcess, finishFixture } = require("../community-question-api-acceptance.cjs");
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
function heldPage({ unrouteError, fulfillError, aborted = false } = {}) {
  const calls = [], upstream = deferred(); let handler, work;
  return { calls, upstream,
    async route(url, fn) { calls.push("installed"); handler = fn; },
    async unroute() { calls.push("unrouted"); if (unrouteError) throw unrouteError; },
    start() { work = handler({ fetch: () => upstream.promise, fulfill: async () => { calls.push("fulfilled"); if (fulfillError) throw fulfillError; }, request: () => ({ failure: () => aborted ? { errorText: "net::ERR_ABORTED" } : null }), continue() { calls.push("continued"); } }); return work; },
    settled: () => work,
  };
}
test("answer viewport evidence requires both literal unverified label and answer below the sticky header", () => {
  const before = { width: global.innerWidth, height: global.innerHeight };
  global.innerWidth = 390; global.innerHeight = 844;
  const rect = (top, bottom) => ({ top, bottom, left: 38, right: 352, width: 314, height: bottom - top });
  const label = { textContent: "观点辅助回答 · 整体未经事实验证", getBoundingClientRect: () => rect(220, 265) };
  const answer = { getBoundingClientRect: () => rect(350, 420) };
  const dialog = { getBoundingClientRect: () => ({ top: 42, bottom: 802, left: 18, right: 372 }),
    querySelector: selector => selector === ":scope > header" ? { getBoundingClientRect: () => rect(42, 125) } : selector.endsWith("h3") ? label : answer };
  try {
    assert.deepEqual(answerViewportState(dialog), { label_visible: true, answer_visible: true, unverified_label: true });
    answer.getBoundingClientRect = () => rect(790, 860); assert.equal(answerViewportState(dialog).answer_visible, false);
    answer.getBoundingClientRect = () => rect(350, 420); label.getBoundingClientRect = () => rect(80, 110);
    assert.equal(answerViewportState(dialog).label_visible, false);
    label.getBoundingClientRect = () => rect(220, 265); label.textContent = "AI answer";
    assert.equal(answerViewportState(dialog).unverified_label, false);
  } finally { global.innerWidth = before.width; global.innerHeight = before.height; }
});
test("held actual-preview route always releases and unroutes after primary failure", async () => {
  const page = heldPage(), primary = Error("second preview failed");
  const work = withHeldPreview(page, "/preview", async started => {
    page.start(); page.upstream.resolve({ exact: "real local response" }); await started(); throw primary;
  });
  await assert.rejects(work, error => error === primary); await page.settled();
  assert.deepEqual(page.calls, ["installed", "fulfilled", "unrouted"]);
});
test("route cleanup failure preserves primary and still releases held response", async () => {
  const page = heldPage({ unrouteError: Error("route cleanup failed") }), primary = Error("assertion failed");
  await assert.rejects(withHeldPreview(page, "/preview", async started => {
    page.start(); page.upstream.resolve({}); await started(); throw primary;
  }), error => error === primary && error.cleanupErrors.length === 1);
  await page.settled(); assert(page.calls.includes("fulfilled"));
});
test("failure before interception does not wait for a nonexistent held request", async () => {
  const page = heldPage(), primary = Error("click failed");
  await assert.rejects(withHeldPreview(page, "/preview", async () => { throw primary; }), error => error === primary);
  assert.deepEqual(page.calls, ["installed", "unrouted"]);
});
test("held-response fulfillment failures are visible unless the browser actually aborted it", async () => {
  for (const aborted of [false, true]) {
    const page = heldPage({ fulfillError: Error("fulfill failed"), aborted });
    const work = withHeldPreview(page, "/preview", async started => { page.start(); page.upstream.resolve({}); await started(); return "current preview"; });
    if (aborted) assert.equal(await work, "current preview"); else await assert.rejects(work, /cleanup failed/);
    await page.settled(); assert(page.calls.includes("unrouted"));
  }
});
test("child exit is registered before synchronous kill completion, including already-exited children", async () => {
  const child = new EventEmitter(); child.exitCode = null; child.signalCode = null; let killed = 0;
  child.kill = () => { killed++; child.signalCode = "SIGTERM"; child.emit("exit", null, "SIGTERM"); };
  await stopFixtureProcess(child, 20); assert.equal(killed, 1); await stopFixtureProcess(child, 20); assert.equal(killed, 1);
  const hung = new EventEmitter(); hung.exitCode = null; hung.kill = () => {};
  await assert.rejects(stopFixtureProcess(hung, 5), /fixture process exit timed out/);
});
test("cleanup attempts every resource and reports without replacing a primary or report-write failure", async () => {
  const primary = Error("primary browser assertion"), writeError = Error("disk full"), child = new EventEmitter(); let stopped = false, written;
  child.exitCode = null; child.kill = () => { stopped = true; child.emit("exit", 0); };
  const report = { passed: true, cleanup: {} };
  await assert.rejects(finishFixture({ browser: { close: async () => { throw Error("browser close failed"); } }, backend: child, out: "/synthetic", report,
    write(file, text) { written = JSON.parse(text); throw writeError; } }, primary), error => error === primary && error.reportError === writeError && error.cleanupErrors.length === 1);
  assert.equal(stopped, true); assert.equal(written.passed, false); assert.equal(written.cleanup.backend_stopped, true);
  await assert.rejects(finishFixture({ out: "/synthetic", report: { passed: true, cleanup: {} }, write() { throw writeError; } }), error => error === writeError);
});
test("unexpected dialogs fail the report and are dismissed rather than accepted", async () => {
  const report = { errors: [] }; let dismissed = false;
  await unexpectedDialog({ type: () => "alert", message: () => "injected", dismiss: async () => { dismissed = true; }, accept: () => { throw Error("Never accept"); } }, report);
  assert.equal(dismissed, true); assert.deepEqual(report.errors, ["Unexpected alert dialog: injected"]);
});
test("home navigation waits for the shipped hydrated welcome route and rejects a stale dialog", async () => {
  const html = readFileSync(require.resolve("../../web/index.html"), "utf8");
  const product = readFileSync(require.resolve("../../web/desk-product.js"), "utf8");
  const desk = readFileSync(require.resolve("../../web/desk.js"), "utf8");
  assert.match(html, /id="welcome"/); assert.match(product, /id="homeUrlForm"/);
  const showHome = desk.slice(desk.indexOf("function showHome("), desk.indexOf("async function navigateBack("));
  assert.match(showHome, /\$\("welcome"\)\.hidden = false/); assert.match(showHome, /\$\("reading"\)\.hidden = true/);
  for (const staleDialog of [false, true]) {
    const location = { hash: "#task/synthetic" }, nodes = { reading: { hidden: false }, toolsDialog: { open: true } }, waits = [];
    const page = {
      evaluate: async fn => vm.runInNewContext(`(${fn.toString()})()`, { location, document: { getElementById: id => nodes[id] } }),
      locator: selector => ({ waitFor: async options => {
        waits.push([selector, options]); nodes.reading.hidden = true; nodes.toolsDialog.open = staleDialog;
      } }),
    };
    if (staleDialog) await assert.rejects(navigateHome(page), /dismiss the transient dialog/); else await navigateHome(page);
    assert.equal(location.hash, ""); assert.deepEqual(waits, [["#welcome #homeUrlForm", { state: "visible" }]]);
  }
});
test("both browser launch paths preserve sandbox defaults", () => {
  assert.deepEqual(browserLaunchOptions(), { channel: "msedge", headless: true });
  assert.deepEqual(browserLaunchOptions("/installed/browser"), { executablePath: "/installed/browser", headless: true });
  assert(!JSON.stringify(browserLaunchOptions("/installed/browser")).includes("no-sandbox"));
});

test("lifecycle helpers import without Playwright installed", () => {
  const consumer = require.resolve("../community-question-api-acceptance.cjs");
  const probe = `
    const Module = require("node:module"), assert = require("node:assert/strict");
    const originalLoad = Module._load, attempts = [];
    Module._load = function (id, ...args) {
      if (/^playwright(?:-core)?(?:\\/|$)/.test(id)) {
        attempts.push(id);
        throw Object.assign(new Error("Browser dependencies are unavailable in ordinary CI"), { code: "MODULE_NOT_FOUND" });
      }
      return originalLoad.call(this, id, ...args);
    };
    const helpers = require(${JSON.stringify(consumer)});
    assert.equal(typeof helpers.withHeldPreview, "function");
    assert.equal(typeof helpers.finishFixture, "function");
    assert.deepEqual(attempts, []);
  `;
  const result = spawnSync(process.execPath, ["-e", probe], { encoding: "utf8", timeout: 10000 });
  assert.equal(result.status, 0, result.stderr || result.error?.message || result.stdout);
});


test("paging viewport evidence rejects status hidden by the sticky header or clipped controls", () => {
  const before = { width: global.innerWidth, height: global.innerHeight };
  global.innerWidth = 390; global.innerHeight = 844;
  const rect = (top, bottom) => ({ top, bottom, left: 38, right: 352, width: 314, height: bottom - top });
  const controls = { getBoundingClientRect: () => rect(400, 488) };
  const status = { nextElementSibling: controls, getBoundingClientRect: () => rect(350, 390) };
  const dialog = { getBoundingClientRect: () => ({ top: 42, bottom: 802, left: 18, right: 372 }),
    querySelector: selector => selector === ":scope > header" ? { getBoundingClientRect: () => rect(42, 125) } : status };
  try {
    assert.deepEqual(pagingViewportState(dialog), { status_visible: true, controls_visible: true });
    status.getBoundingClientRect = () => rect(80, 110); assert.equal(pagingViewportState(dialog).status_visible, false);
    status.getBoundingClientRect = () => rect(350, 390); controls.getBoundingClientRect = () => rect(790, 878);
    assert.equal(pagingViewportState(dialog).controls_visible, false);
  } finally { global.innerWidth = before.width; global.innerHeight = before.height; }
});


test("held route fulfills before unroute can continue the outstanding request", async () => {
  const calls = [], upstream = deferred(); let handler, pending, handled = false, fulfillCount = 0;
  const page = {
    async route(url, fn) { handler = fn; },
    async unroute() { calls.push("unroute"); if (!handled) { handled = true; calls.push("continued-by-removal"); } },
  };
  const response = { exact: "captured real response" };
  const result = await withHeldPreview(page, "/page", async started => {
    pending = handler({
      fetch: () => upstream.promise,
      request: () => ({ failure: () => null }),
      fulfill: async options => {
        // Protocol dispatch need not complete in the release promise's microtask.
        await new Promise(resolve => setImmediate(resolve));
        if (handled) throw Error("Route is already handled!");
        assert.equal(options.response, response); handled = true; fulfillCount++; calls.push("fulfill");
      },
    });
    upstream.resolve(response); await started(); return "obsolete response discarded by the product";
  });
  await pending;
  assert.equal(result, "obsolete response discarded by the product");
  assert.equal(fulfillCount, 1); assert.deepEqual(calls, ["fulfill", "unroute"]);
});

test("settlement failure still removes the route and preserves a primary failure", async () => {
  const page = heldPage({ fulfillError: Error("Route is already handled!") });
  const primary = Error("original UI assertion");
  await assert.rejects(withHeldPreview(page, "/page", async started => {
    page.start(); page.upstream.resolve({}); await started(); throw primary;
  }), error => error === primary && error.cleanupErrors.length === 1
    && /already handled/.test(error.cleanupErrors[0].message));
  await page.settled(); assert.deepEqual(page.calls, ["installed", "fulfilled", "unrouted"]);
});
