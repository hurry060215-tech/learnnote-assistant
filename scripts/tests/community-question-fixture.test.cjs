const assert = require("node:assert/strict");
const test = require("node:test");
const { EventEmitter } = require("node:events");
const { browserLaunchOptions, unexpectedDialog, withHeldPreview, stopFixtureProcess, finishFixture } = require("../community-question-api-acceptance.cjs");
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
test("held actual-preview route always releases and unroutes after primary failure", async () => {
  const page = heldPage(), primary = Error("second preview failed");
  const work = withHeldPreview(page, "/preview", async started => {
    page.start(); page.upstream.resolve({ exact: "real local response" }); await started(); throw primary;
  });
  await assert.rejects(work, error => error === primary); await page.settled();
  assert.deepEqual(page.calls, ["installed", "unrouted", "fulfilled"]);
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
test("both browser launch paths preserve sandbox defaults", () => {
  assert.deepEqual(browserLaunchOptions(), { channel: "msedge", headless: true });
  assert.deepEqual(browserLaunchOptions("/installed/browser"), { executablePath: "/installed/browser", headless: true });
  assert(!JSON.stringify(browserLaunchOptions("/installed/browser")).includes("no-sandbox"));
});
