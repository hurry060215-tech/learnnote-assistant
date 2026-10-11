import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
const source = readFileSync(new URL("../assistant-run-controller.js", import.meta.url), "utf8");
const { createAssistantRunController } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const root = "/api/assistant/runs";
const pending = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const tick = () => new Promise(resolve => setImmediate(resolve));
function harness(handler) {
  const calls = [], shown = [], errors = [], loaded = [], busy = [];
  const h = { current: { kind: "task", id: "synthetic-note", revision: "a".repeat(64) }, dirty: false, calls, shown, errors, loaded, busy };
  h.value = (status = "ready", version = 1, extra = {}) => ({ id: "synthetic-run", version, status, source: { ...h.current }, steps: [], ...extra });
  h.controller = createAssistantRunController({
    api: async (path, request = {}) => { const call = { path, method: request.method || "GET", body: request.body && JSON.parse(request.body) }; calls.push(call); return handler(call, h); },
    source: () => { if (h.dirty) throw Error("Unsaved synthetic draft"); return { ...h.current }; }, options: () => ({ llm_model: "mock-only" }),
    reload: async next => { loaded.push(next); h.current = { ...next }; }, render: value => shown.push(value), report: value => errors.push(value),
    busyChanged: value => busy.push(value), newId: () => "synthetic-run",
  });
  h.controller.open(); return h;
}

test("actual server receipts drive read, explicit edit approval, reload, and export", async () => {
  let step = 0;
  const h = harness(call => {
    if (call.path === root) return h.value();
    if (call.path.endsWith("/advance")) {
      step++;
      if (step === 1) return h.value("ready", 2, { steps: [{ tool: "read_note", status: "completed", result: { text: "Synthetic original" } }] });
      if (step === 2) return h.value("awaiting_approval", 3, { pending_operation: { id: "synthetic-edit", preview: { diff: "-original\n+revised" } } });
      assert.equal(h.loaded.length, 1, "saved revision must be reloaded before export decision");
      return h.value("completed", 5, { artifact_operation_id: "synthetic-export", edit_operation_id: "synthetic-edit" });
    }
    if (call.path.endsWith("/approve")) return h.value("ready", 4, { source: { ...h.current, revision: "b".repeat(64) }, edit_operation_id: "synthetic-edit" });
    throw Error(call.path);
  });
  await h.controller.start("Read, edit, export", true);
  assert.equal(step, 2); assert.equal(h.controller.active.status, "awaiting_approval");
  assert.equal(h.calls.filter(call => call.path.endsWith("/approve")).length, 0);
  await h.controller.approve();
  assert.deepEqual(h.calls.find(call => call.path.endsWith("/approve")).body, { expected_version: 3, operation_id: "synthetic-edit", confirm: true });
  assert.equal(h.controller.active.status, "completed"); assert.equal(h.current.revision, "b".repeat(64)); assert.deepEqual(h.errors, []);
});

test("no opt-in, blank request, or unsaved draft reaches the model or server", async () => {
  const h = harness(() => { throw Error("Unexpected request"); });
  await h.controller.start("Edit", false); await h.controller.start(" ", true); h.dirty = true; await h.controller.start("Edit", true);
  assert.equal(h.calls.length, 0); assert.equal(h.errors.length, 3);
});

test("lost create response is recovered by GET with no duplicate creation", async () => {
  const h = harness(call => {
    if (call.path === root) throw Error("Synthetic lost receipt");
    if (call.method === "GET") return h.value("awaiting_approval", 2, { pending_operation: { id: "edit-1" } });
    throw Error("Unexpected action");
  });
  await h.controller.start("Edit", true);
  assert.deepEqual(h.calls.map(call => call.method), ["POST", "GET"]); assert.equal(h.controller.active.status, "awaiting_approval");
});

test("unknown create outcome keeps the stable ID and original request on explicit retry", async () => {
  let count = 0;
  const h = harness(call => {
    if (++count <= 2) throw Error("Synthetic unavailable");
    return h.value("stopped", 2);
  });
  await h.controller.start("Original request", true); await h.controller.start("Different typed text", true);
  const creates = h.calls.filter(call => call.path === root);
  assert.equal(creates.length, 2); assert.equal(creates[0].body.run_id, creates[1].body.run_id);
  assert.equal(creates[1].body.question, "Original request");
});

test("lost advance response never automatically starts another model decision", async () => {
  const h = harness(call => {
    if (call.path === root) return h.value();
    if (call.path.endsWith("/advance")) throw Error("Synthetic response loss");
    return h.value("ready", 2);
  });
  await h.controller.start("Read then edit", true);
  assert.equal(h.calls.filter(call => call.path.endsWith("/advance")).length, 1);
  assert.equal(h.controller.active.version, 2); assert.match(h.errors[0], /response loss/);
});

test("cancellation during a model decision prevents late response from starting a dependency", async () => {
  const wait = pending();
  const h = harness(call => {
    if (call.path === root) return h.value();
    if (call.path.endsWith("/advance")) return wait.promise;
    if (call.path.endsWith("/cancel")) return h.value("cancelled", 3);
  });
  const running = h.controller.start("Read edit export", true); await tick();
  await h.controller.cancel(); wait.resolve(h.value("ready", 2)); await running;
  assert.equal(h.controller.active.status, "cancelled"); assert.equal(h.calls.filter(call => call.path.endsWith("/advance")).length, 1);
});

test("closing while create is in flight cancels the resulting run without a model decision", async () => {
  const wait = pending();
  const h = harness(call => call.path === root ? wait.promise : h.value("cancelled", 2));
  const running = h.controller.start("Edit", true); await tick(); h.controller.close(); wait.resolve(h.value()); await running;
  assert.equal(h.calls.filter(call => call.path.endsWith("/advance")).length, 0);
  assert.ok(h.calls.some(call => call.path.endsWith("/cancel"))); assert.equal(h.shown.length, 0);
});

test("changing source before approval cancels the run and sends no edit application", async () => {
  const h = harness(call => {
    if (call.path === root) return h.value("awaiting_approval", 2, { pending_operation: { id: "edit-1" } });
    if (call.path.endsWith("/cancel")) return { ...h.controller.active, status: "cancelled", version: 3 };
  });
  await h.controller.start("Edit", true); h.current.id = "different-note"; await h.controller.approve();
  assert.equal(h.calls.filter(call => call.path.endsWith("/approve")).length, 0); assert.equal(h.controller.active.status, "cancelled");
});

test("draft created during approval is preserved and no export is requested", async () => {
  const wait = pending();
  const h = harness(call => {
    if (call.path === root) return h.value("awaiting_approval", 2, { pending_operation: { id: "edit-1" } });
    if (call.path.endsWith("/approve")) return wait.promise;
    if (call.path.endsWith("/cancel")) return h.value("cancelled", 4);
  });
  await h.controller.start("Edit then export", true);
  const applying = h.controller.approve(); await tick(); h.dirty = true;
  wait.resolve(h.value("ready", 3, { source: { ...h.current, revision: "b".repeat(64) }, edit_operation_id: "edit-1" })); await applying;
  assert.equal(h.loaded.length, 0); assert.equal(h.calls.filter(call => call.path.endsWith("/advance")).length, 0);
  assert.ok(h.calls.some(call => call.path.endsWith("/cancel")));
});

test("failed approval response is read back rather than re-executed", async () => {
  const h = harness(call => {
    if (call.path === root) return h.value("awaiting_approval", 2, { pending_operation: { id: "edit-1" } });
    if (call.path.endsWith("/approve")) throw Error("Synthetic receipt loss");
    return h.value("ready", 3, { source: { ...h.current, revision: "b".repeat(64) }, edit_operation_id: "edit-1" });
  });
  await h.controller.start("Edit", true); await h.controller.approve();
  assert.equal(h.calls.filter(call => call.path.endsWith("/approve")).length, 1); assert.equal(h.loaded.length, 0);
  assert.equal(h.calls.filter(call => call.path.endsWith("/advance")).length, 0);
});

test("same-version ready reply stops client repetition", async () => {
  const h = harness(() => h.value()); await h.controller.start("Read", true);
  assert.equal(h.calls.filter(call => call.path.endsWith("/advance")).length, 1);
});

test("model/server terminal failure cannot be represented as completed", async () => {
  const h = harness(call => call.path === root ? h.value() : h.value("failed", 2, { reason: "Synthetic verification mismatch" }));
  await h.controller.start("Read edit export", true);
  assert.equal(h.controller.active.status, "failed"); assert.equal(h.calls.length, 2);
});

test("unexpected endlessly-ready server responses are bounded by the client too", async () => {
  let version = 0;
  const h = harness(call => h.value(call.path.endsWith("/cancel") ? "cancelled" : "ready", ++version));
  await h.controller.start("Read", true);
  assert.equal(h.calls.filter(call => call.path.endsWith("/advance")).length, 8);
  assert.equal(h.controller.active.status, "cancelled"); assert.match(h.errors[0], /上限/);
});


test("confirmed cancellation releases an uncertain creation for a different source", async () => {
  let attempts = 0;
  const h = harness(call => {
    if (call.path === root) { attempts++; if (attempts === 1) throw Error("Synthetic response loss"); return h.value("stopped", 5); }
    if (call.path.endsWith("/cancel")) return h.value("cancelled", 2);
    throw Error("Synthetic status unavailable");
  });
  await h.controller.start("Original request", true); await h.controller.cancel();
  h.current.id = "different-source"; await h.controller.start("New request", true);
  assert.equal(attempts, 2);
  assert.equal(h.calls.filter(call => call.path === root)[1].body.source.id, "different-source");
});

test("verified absent cancellation releases uncertain creation but uncertain cancellation does not", async () => {
  let absent = false, attempts = 0;
  const h = harness(call => {
    if (call.path === root) { attempts++; if (attempts > 1) return h.value("stopped", 5); throw Error("Synthetic create loss"); }
    if (call.path.endsWith("/cancel") && absent) { const error = Error("Not found"); error.status = 404; throw error; }
    throw Error("Synthetic unavailable");
  });
  await h.controller.start("Original", true); await h.controller.cancel();
  h.current.id = "different-source"; await h.controller.start("New", true); assert.equal(attempts, 1);
  absent = true; await h.controller.cancel(); await h.controller.start("New", true); assert.equal(attempts, 2);
});


test("pending local deadline receipt pauses approval without source fields or export", async () => {
  const h = harness(call => call.path === root ? h.value("awaiting_approval", 2, { pending_operation: { id: "edit-1" } })
    : { id: "synthetic-run", version: 3, status: "executing", reason: "active_timeout_pending_receipt", steps: [] });
  await h.controller.start("Edit then export", true); await h.controller.approve();
  assert.equal(h.controller.active.status, "executing"); assert.equal(h.loaded.length, 0);
  assert.equal(h.calls.filter(call => call.path.endsWith("/advance")).length, 0);
  assert.match(h.errors[0], /核对实际回执/);
});

test("confirmed missing source releases an idle active workflow without replay", async () => {
  let creates = 0;
  const h = harness(call => {
    if (call.path === root) { creates++; return h.value("awaiting_approval", 2, { pending_operation: { id: "edit-1" } }); }
    const error = Error("Source missing"); error.status = 404; throw error;
  });
  await h.controller.start("Original", true); await h.controller.cancel(); assert.equal(h.controller.active, null);
  h.current.id = "new-source"; await h.controller.start("New", true); assert.equal(creates, 2);
});
