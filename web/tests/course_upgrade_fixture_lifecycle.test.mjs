import assert from "node:assert/strict";
import test from "node:test";
import helpers from "../../scripts/course-upgrade-fixture-helpers.cjs";

const { completedAction, retryCourseReady, openChildReady, cleanupFixture } = helpers;
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const tick = () => new Promise(setImmediate);
const base = "http://127.0.0.1:18940";
const retryUrl = base + "/api/courses/course-a/episodes/episode-a/retry";
const response = (url, method, finished = async () => null) => ({ url: () => url, request: () => ({ method: () => method }), ok: () => true, status: () => 200, finished });

test("action waits for its exact response and complete body, with the listener registered before click", async () => {
  const body = deferred(), events = [];
  const page = { waitForResponse: (matches, options) => {
    events.push("listen"); assert.equal(options.timeout, 15000);
    assert(!matches(response(retryUrl, "GET"))); assert(!matches(response(retryUrl + "?extra=1", "POST")));
    assert(matches(response(retryUrl, "POST")));
    return Promise.resolve(response(retryUrl, "POST", () => body.promise));
  } };
  let done = false;
  const pending = completedAction(page, "POST", retryUrl, () => { events.push("click"); }).then(() => { done = true; });
  await tick(); assert.deepEqual(events, ["listen", "click"]); assert.equal(done, false);
  body.resolve(null); await pending; assert.equal(done, true);
});

test("failed status or incomplete response cannot advance fixture state", async () => {
  for (const value of [{ ...response(retryUrl, "POST"), ok: () => false, status: () => 409 }, response(retryUrl, "POST", async () => new Error("connection closed"))]) {
    await assert.rejects(completedAction({ waitForResponse: async () => value }, "POST", retryUrl, () => {}));
  }
});

test("retry cannot advance on an already-visible upgrade button before response and old-control detachment", async () => {
  const reply = deferred(), detached = deferred(), events = [];
  const oldControl = { isConnected: true, dispose: async () => events.push("disposed") };
  const page = {
    waitForResponse: () => reply.promise,
    waitForFunction: async (check, control) => {
      events.push("detach-wait"); assert.equal(control, oldControl); assert.equal(check(control), false);
      await detached.promise; assert.equal(check(control), true); events.push("detached");
    },
    locator: selector => ({
      elementHandle: async () => oldControl,
      click: async () => events.push("retry-click"),
      waitFor: async () => events.push("ready-control"),
      isEnabled: async () => true,
      innerText: async () => selector === "#toolsDialog h2" ? "Course A" : "",
    }),
  };
  const pending = retryCourseReady(page, { url: retryUrl, retrySelector: "[data-retry-episode]", readySelector: "[data-upgrade-episode]", title: "Course A" });
  await tick(); assert.deepEqual(events, ["retry-click"]);
  reply.resolve(response(retryUrl, "POST")); await tick(); assert.deepEqual(events, ["retry-click", "detach-wait"]);
  oldControl.isConnected = false; detached.resolve(); await pending;
  assert.deepEqual(events, ["retry-click", "detach-wait", "detached", "ready-control", "disposed"]);
});

test("linked-child readiness waits for exact edition completion, closed dialog and hydrated reader identity", async () => {
  const body = deferred(), events = [], id = "visual-child";
  const page = {
    waitForResponse: async matches => {
      assert(!matches(response(base + "/api/tasks/editions/task/other", "GET")));
      const value = response(base + `/api/tasks/editions/task/${id}`, "GET", () => body.promise);
      assert(matches(value)); return value;
    },
    waitForURL: async matches => { assert(matches(new URL(base + "#task/visual-child"))); assert(!matches(new URL(base + "#task/other"))); events.push("hash"); },
    waitForFunction: async check => { assert.match(check.toString(), /toolsDialog/); events.push("dialog-closed"); },
    locator: selector => ({
      click: async () => events.push("child-click"),
      waitFor: async () => { assert.equal(selector, '#document[data-reader-source="task:visual-child"]'); events.push("reader-ready"); },
      locator: heading => ({ innerText: async () => { assert.equal(heading, "h1"); events.push("heading"); return "Child"; } }),
      innerText: async () => { assert.equal(selector, "#taskStatus .task-status-heading strong"); events.push("queue-status"); return "排队中"; },
    }),
  };
  const pending = openChildReady(page, { base, id, title: "Child" });
  await tick(); assert.deepEqual(events, ["child-click"]);
  body.resolve(null); await pending;
  assert.deepEqual(events, ["child-click", "hash", "dialog-closed", "reader-ready", "heading", "queue-status"]);
});

test("cancel cannot complete on DELETE headers while the response body remains held", async () => {
  const body = deferred(), url = base + "/api/courses/course-a/episodes/episode-a/upgrade-preview/preview-a";
  let staleReviewChecked = false;
  const pending = completedAction({ waitForResponse: async matches => {
    assert(!matches(response(url.replace("preview-a", "preview-b"), "DELETE")));
    const value = response(url, "DELETE", () => body.promise); assert(matches(value)); return value;
  } }, "DELETE", url, () => {}).then(() => { staleReviewChecked = true; });
  await tick(); assert.equal(staleReviewChecked, false);
  body.resolve(null); await pending; assert.equal(staleReviewChecked, true);
});

test("primary failure survives report and browser cleanup failures; backend termination is still attempted", async () => {
  const primary = new Error("primary assertion failed"), calls = [];
  await assert.rejects((async () => {
    try { throw primary; }
    finally { await cleanupFixture({
      report: () => { calls.push("report"); throw new Error("disk unavailable"); },
      browser: async () => { calls.push("browser"); throw new Error("close rejected"); },
      backend: () => calls.push("backend"),
    }, primary); }
  })(), error => error === primary);
  assert.deepEqual(calls, ["report", "browser", "backend"]);
  assert.equal(primary.message, "primary assertion failed"); assert.equal(primary.cleanupErrors.length, 2);
});

test("cleanup failure without a primary failure is reported only after all cleanup actions run", async () => {
  for (const failing of ["report", "browser"]) {
    const calls = [];
    await assert.rejects(cleanupFixture(Object.fromEntries(["report", "browser", "backend"].map(label => [label, async () => {
      calls.push(label); if (label === failing) throw new Error("injected failure");
    }]))), error => error instanceof AggregateError && error.errors.length === 1);
    assert.deepEqual(calls, ["report", "browser", "backend"]);
  }
});
