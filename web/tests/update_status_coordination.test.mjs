import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import vm from "node:vm";
const source = fs.readFileSync(new URL("../desk-settings.js", import.meta.url), "utf8");
const actual = source.slice(source.indexOf("  let updateStatus ="), source.indexOf("  panes.usage.innerHTML"));
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
function status(preferences, extra = {}) { return { ok: true, preferences, capabilities: {}, ...extra }; }
function harness({ bridge = false } = {}) {
  const elements = new Map(), requests = [], downloads = [];
  const $ = id => { if (!elements.has(id)) elements.set(id, { textContent: "", hidden: false, checked: true, disabled: false }); return elements.get(id); };
  const request = target => { const pending = deferred(); requests.push({ target, ...pending }); return pending.promise; };
  const context = vm.createContext({ $, window: bridge ? { pywebview: { api: { update_status: force => request(force), start_update_download: async (...args) => { downloads.push(args); return { phase: "downloading" }; } } } } : {},
    state: { items: [], health: { app_version: "0.2.9" } }, ctx: { guard: () => true }, saved: () => {}, updateDirty: () => [], notice: () => {},
    api: target => request(target), setTimeout: () => 0, setInterval: () => 0, clearInterval: () => {}, Date });
  // Run the shipped functions and handler wiring. Only HTTP/bridge, timers and
  // DOM nodes are supplied by the fixture; no duplicated startup algorithm.
  vm.runInContext(actual + ";globalThis.methods={readUpdateStatus,refreshUpdates,pending:()=>updateRead,status:()=>updateStatus};", context);
  return { $, requests, downloads, methods: context.methods, startup: context.window.LearnNoteUpdates.startupCheck };
}

test("overlapping initial read and startup await disabled real preferences on HTTP and desktop bridge", async () => {
  for (const bridge of [false, true]) {
    const app = harness({ bridge }), first = app.methods.readUpdateStatus(false), startup = app.startup();
    assert.equal(app.requests.length, 1); assert.equal(app.requests[0].target, bridge ? false : "/api/update/status");
    const disabled = status({ auto_check: false, auto_download: false }); app.requests[0].resolve(disabled);
    assert.equal(await first, disabled); assert.equal(await startup, disabled); assert.equal(app.requests.length, 1);
    assert.equal(app.$("updateAutoCheck").checked, false); assert.equal(app.methods.pending(), null);
  }
});

test("enabled and due startup checks retain their explicit force request after the shared response", async () => {
  const app = harness(), first = app.methods.readUpdateStatus(false), startup = app.startup();
  app.requests[0].resolve(status({ auto_check: true, auto_download: false })); await first;
  await Promise.resolve(); await Promise.resolve();
  assert.deepEqual(app.requests.map(row => row.target), ["/api/update/status", "/api/update/status?force=true"]);
  const checked = status({ auto_check: true, auto_download: false, last_checked_at: Date.now() / 1000 });
  app.requests[1].resolve(checked); assert.equal(await startup, checked); assert.equal(app.methods.pending(), null);
});

test("unknown, disabled, failed and recently checked status cannot trigger an automatic force check", async () => {
  for (const result of [status(undefined), status({}), status({ auto_check: null }), status({ auto_check: "true" }),
    status({ auto_check: false }), status({ auto_check: true }, { ok: false, error: "status unavailable" }),
    status({ auto_check: true, last_checked_at: Date.now() / 1000 })]) {
    const app = harness(), startup = app.startup(); app.requests[0].resolve(result);
    assert.equal(await startup, result); assert.equal(app.requests.length, 1); assert.equal(app.methods.pending(), null);
  }
});

test("shared rejected status is visible, never force-checks and permits a later ordinary retry", async () => {
  const app = harness(), first = app.methods.refreshUpdates(false), startup = app.startup();
  app.requests[0].reject(new Error("local status unavailable"));
  assert.equal(await first, null); assert.equal(await startup, null); assert.equal(app.requests.length, 1);
  assert.equal(app.$("updateDownloadStatus").textContent, "local status unavailable"); assert.equal(app.methods.pending(), null);
  const retry = app.methods.refreshUpdates(false); assert.equal(app.requests.length, 2);
  const result = status({ auto_check: false }); app.requests[1].resolve(result); assert.equal(await retry, result);
});

test("older completion cannot clear a newer explicit forced read and ordinary refresh awaits that newer read", async () => {
  const app = harness(), older = app.methods.readUpdateStatus(false), forced = app.$("checkUpdates").onclick();
  assert.deepEqual(app.requests.map(row => row.target), ["/api/update/status", "/api/update/status?force=true"]);
  const active = app.methods.pending(); app.requests[0].resolve(status({ auto_check: false })); await older;
  assert.equal(app.methods.pending(), active);
  const shared = app.methods.readUpdateStatus(false); assert.equal(app.requests.length, 2);
  const latest = status({ auto_check: false, auto_download: false }); app.requests[1].resolve(latest);
  assert.equal(await shared, latest); await forced; assert.equal(app.methods.pending(), null);
});

test("failed older read preserves a newer manual request and explicit manual checks work with unknown preferences", async () => {
  const app = harness(), older = app.methods.refreshUpdates(false), forced = app.$("checkUpdates").onclick();
  const active = app.methods.pending(); app.requests[0].reject(new Error("older failed")); await older;
  assert.equal(app.methods.pending(), active); assert.equal(app.requests.length, 2);
  app.requests[1].resolve(status(undefined)); await forced; assert.equal(app.methods.pending(), null);
  const manual = app.$("checkUpdates").onclick(); assert.equal(app.requests[2].target, "/api/update/status?force=true");
  app.requests[2].resolve(status({ auto_check: false })); await manual;
});


test("late ordinary response cannot overwrite a completed newer manual status", async () => {
  const app = harness(), older = app.methods.readUpdateStatus(false), forced = app.$("checkUpdates").onclick();
  const latest = status({ auto_check: false, auto_download: false }); app.requests[1].resolve(latest); await forced;
  assert.equal(app.methods.status(), latest); assert.equal(app.methods.pending(), null);
  const stale = status({ auto_check: true, auto_download: true }); app.requests[0].resolve(stale);
  assert.equal(await older, stale, "The caller still receives its own actual response");
  assert.equal(app.methods.status(), latest); assert.equal(app.$("updateAutoCheck").checked, false); assert.equal(app.methods.pending(), null);
});

test("manual force remains available after an unsuccessful status with enabled stored preferences", async () => {
  const app = harness(), startup = app.startup();
  app.requests[0].resolve(status({ auto_check: true, last_checked_at: 0 }, { ok: false, error: "release unavailable" }));
  await startup; assert.equal(app.requests.length, 1);
  const manual = app.$("checkUpdates").onclick(); assert.equal(app.requests[1].target, "/api/update/status?force=true");
  app.requests[1].resolve(status({ auto_check: true, auto_download: false })); await manual;
});


function offered(preferences, extra = {}) {
  return status(preferences, { client_update_available: true, capabilities: { download: true },
    latest: { version: "9.8.7", client: { installable: true, url: "https://example.test/owned.exe", sha256: "synthetic" } }, ...extra });
}

test("automatic download requires successful fresh forced status and explicitly enabled current preferences", async () => {
  for (const checked of [offered(undefined), offered({}), offered({ auto_download: null }), offered({ auto_download: false }),
    offered({ auto_download: "true" }), offered({ auto_download: true }, { ok: false }), offered({ auto_download: true })]) {
    const app = harness({ bridge: true }), startup = app.startup();
    app.requests[0].resolve(status({ auto_check: true, auto_download: false }));
    for (let index = 0; index < 6; index++) await Promise.resolve();
    assert.equal(app.requests.length, 2); assert.equal(app.requests[1].target, true);
    app.requests[1].resolve(checked); await startup;
    assert.equal(app.downloads.length, checked.ok === true && checked.preferences?.auto_download === true ? 1 : 0);
  }
});

test("a failed forced read remains visible and never starts an automatic download", async () => {
  const app = harness({ bridge: true }), startup = app.startup();
  app.requests[0].resolve(status({ auto_check: true, auto_download: true }));
  for (let index = 0; index < 6; index++) await Promise.resolve();
  app.requests[1].reject(new Error("forced status unavailable"));
  assert.equal(await startup, null); assert.equal(app.downloads.length, 0);
  assert.equal(app.$("updateDownloadStatus").textContent, "forced status unavailable");
});

test("obsolete startup responses cannot force or download after a newer manual result disables automation", async () => {
  for (const duringForced of [false, true]) {
    const app = harness({ bridge: true }), startup = app.startup();
    if (duringForced) {
      app.requests[0].resolve(status({ auto_check: true, auto_download: true }));
      for (let index = 0; index < 6; index++) await Promise.resolve();
    }
    const staleIndex = duringForced ? 1 : 0, manual = app.$("checkUpdates").onclick();
    app.requests.at(-1).resolve(status({ auto_check: false, auto_download: false })); await manual;
    app.requests[staleIndex].resolve(offered({ auto_check: true, auto_download: true })); await startup;
    assert.equal(app.requests.length, duringForced ? 3 : 2); assert.equal(app.downloads.length, 0);
    assert.equal(app.methods.status().preferences.auto_check, false);
  }
});
