import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
const source = fs.readFileSync(new URL("../reading-settings.js", import.meta.url), "utf8");
const { createReadingSettingsAdapter, normalizeReading, READING_ALLOWED, READING_STORAGE_KEY: KEY, LEGACY_THEME_KEY: THEME } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);

class Storage {
  constructor(value = {}) { this.data = new Map(Object.entries(value)); this.writes = 0; }
  getItem(key) { if (this.readFailure) throw new Error("denied"); return this.data.get(key) ?? null; }
  setItem(key, value) { if (this.writeFailure) throw new Error("quota"); this.writes++; this.data.set(key, value); this.afterWrite?.(); }
}
function serialLocks() {
  let queue = Promise.resolve();
  return { request(name, options, callback) {
    const current = queue.then(() => { if (options.signal?.aborted) throw new Error("aborted"); return callback(); });
    queue = current.catch(() => {}); return current;
  } };
}
let token = 0;
function harness({ storage = new Storage(), locks = serialLocks(), dirty = () => false, onChange = () => {} } = {}) {
  const styles = {}, classes = new Set(), events = new EventTarget(), changes = [], errors = [];
  const document = {
    documentElement: { style: { setProperty: (key, value) => { styles[key] = value; } } },
    body: { classList: { toggle(key, value) { if (value) classes.add(key); else classes.delete(key); } } },
  };
  const preview = { style: {} };
  const adapter = createReadingSettingsAdapter({ storage, locks, isDirty: dirty, events, document, preview,
    newRevision: () => `test-${++token}`, onChange: snapshot => { changes.push(snapshot); onChange(snapshot); }, onError: result => errors.push(result) });
  return { adapter, storage, styles, classes, changes, errors, preview, events,
    patch(patch, operationId = `op-${++token}`, extra = {}) { return adapter.patch({ patch, operationId, expectedRevision: adapter.read().revision, ...extra }); },
    storageEvent(key = KEY) { const event = new Event("storage"); Object.assign(event, { key, storageArea: storage }); events.dispatchEvent(event); },
  };
}
const code = (result, expected) => { assert.equal(result.ok, false); assert.equal(result.error.code, expected); };

test("legacy defaults and allowed values keep the established appearance contract", () => {
  assert.deepEqual(normalizeReading({ size: "18", weight: 600, width: 760, notify: "true", autoOpen: true }), {
    size: 18, density: "comfortable", font: "sans", width: "760", leading: "1.65", weight: "600", accent: "neutral", autoOpen: true, notify: false,
  });
  const h = harness({ storage: new Storage({ [THEME]: "dark" }) });
  const current = h.adapter.read(); h.adapter.sync();
  assert.equal(current.settings.theme, "dark"); assert.ok(h.classes.has("dark"));
  assert.equal(h.storage.writes, 0, "reading and startup never migrate storage");
  assert.deepEqual(Object.keys(current.settings), Object.keys(READING_ALLOWED));
});

test("real patches persist and apply all existing CSS tokens without touching unrelated fields", async () => {
  const original = { autoOpen: true, notify: true, future: { untouched: "value" } };
  const h = harness({ storage: new Storage({ [KEY]: JSON.stringify(original), [THEME]: "light", other: "preserved" }) });
  const after = { theme: "dark", size: 20, font: "serif", width: "1120", leading: "2.1", weight: "600", density: "compact", accent: "plum" };
  const result = await h.patch(after, "actual-change");
  assert.equal(result.ok, true); assert.equal(result.status, "applied"); assert.deepEqual(result.after, after);
  assert.deepEqual(h.adapter.read().settings, after);
  assert.equal(h.styles["--reader-size"], "20px"); assert.equal(h.styles["--reader-width"], "1120px");
  assert.equal(h.styles["--reader-leading"], "2.1"); assert.equal(h.styles["--reader-weight"], "600");
  assert.equal(h.styles["--chosen-accent"], "#79516f"); assert.equal(h.styles["--chosen-accent-dark"], "#d9aed0");
  assert.match(h.styles["--reader-font"], /Noto Serif/); assert.equal(h.preview.style.fontSize, "20px");
  assert.ok(h.classes.has("dark")); assert.ok(h.classes.has("compact-density"));
  const stored = JSON.parse(h.storage.getItem(KEY));
  assert.equal(stored.autoOpen, true); assert.equal(stored.notify, true); assert.deepEqual(stored.future, original.future);
  assert.equal(h.storage.getItem(THEME), "light"); assert.equal(h.storage.getItem("other"), "preserved");
  assert.equal(h.storage.writes, 1, "theme, appearance and receipt commit in one atomic write");
  assert.equal(h.adapter.read().revision, result.revision);
});

test("strict agent whitelist rejects permissions, credentials, coercions and unknown values", async () => {
  const h = harness();
  for (const patch of [{ notify: true }, { autoOpen: true }, { api_key: "synthetic" }, { size: "20" }, { width: 760 }, { theme: "system" }, { leading: 1.65 }, { size: 19 }, {}, [], null, JSON.parse('{"__proto__":{}}')]) {
    code(await h.patch(patch), "invalid_patch");
  }
  assert.equal(h.storage.writes, 0);
});

test("retry, reordered payload, reload and conflicting operation IDs are deterministic", async () => {
  const h = harness();
  const request = { operationId: "replay-id", expectedRevision: h.adapter.read().revision, patch: { size: 18, theme: "dark" } };
  const first = await h.adapter.patch(request), saved = h.storage.getItem(KEY);
  const reloaded = harness({ storage: h.storage });
  const replay = await reloaded.adapter.patch({ ...request, patch: { theme: "dark", size: 18 } });
  assert.equal(replay.ok, true); assert.equal(replay.replayed, true); assert.equal(replay.revision, first.revision);
  assert.equal(h.storage.getItem(KEY), saved); assert.equal(h.storage.writes, 1);
  code(await reloaded.adapter.patch({ ...request, patch: { size: 20 } }), "operation_conflict");
  assert.deepEqual(reloaded.adapter.operation("replay-id").after, first.after);
  await reloaded.patch({ size: 15 }, "newer-id");
  const historical = await reloaded.adapter.patch(request);
  assert.equal(historical.after.size, 18); assert.equal(historical.current.size, 15);
  assert.notEqual(historical.currentRevision, historical.revision); assert.equal(h.storage.writes, 2);
});

test("unsaved manual settings and stale revisions block writes without changing the preview", async () => {
  let dirty = false; const h = harness({ dirty: () => dirty });
  h.adapter.sync(); const before = { ...h.styles }, revision = h.adapter.read().revision;
  dirty = true; code(await h.patch({ size: 20 }), "unsaved_settings");
  assert.deepEqual(h.styles, before); assert.equal(h.storage.writes, 0);
  dirty = false; await h.patch({ size: 18 });
  code(await h.patch({ size: 20 }, "stale", { expectedRevision: revision }), "revision_conflict");
  assert.equal(h.adapter.read().settings.size, 18);
});

test("cooperating tabs serialize; storage events apply the committed settings", async () => {
  const storage = new Storage(), locks = serialLocks();
  const a = harness({ storage, locks }), b = harness({ storage, locks });
  const revision = a.adapter.read().revision;
  const [first, second] = await Promise.all([
    a.patch({ size: 20 }, "tab-a", { expectedRevision: revision }),
    b.patch({ size: 15 }, "tab-b", { expectedRevision: revision }),
  ]);
  assert.equal(first.ok, true); code(second, "revision_conflict"); assert.equal(storage.writes, 1);
  b.storageEvent(); assert.equal(b.styles["--reader-size"], "20px");
  b.adapter.dispose(); const count = b.changes.length; b.storageEvent(); assert.equal(b.changes.length, count);
});

test("legacy/direct writes that keep metadata still invalidate stale revisions", async () => {
  const h = harness(); await h.patch({ size: 18 });
  const revision = h.adapter.read().revision;
  const stored = JSON.parse(h.storage.getItem(KEY)); stored.size = 20; h.storage.setItem(KEY, JSON.stringify(stored));
  code(await h.patch({ font: "serif" }, "after-direct", { expectedRevision: revision }), "revision_conflict");
  assert.equal(h.adapter.read().settings.size, 20);
});

test("undo requires unchanged after state, preserves manual-only fields and itself replays", async () => {
  const h = harness({ storage: new Storage({ [KEY]: JSON.stringify({ notify: true, future: 7 }) }) });
  const initial = h.adapter.read().settings;
  const applied = await h.patch({ size: 20, theme: "dark" }, "undo-target");
  const request = { operationId: "undo-id", targetOperationId: "undo-target", expectedRevision: applied.revision };
  const undone = await h.adapter.undo(request);
  assert.equal(undone.ok, true); assert.equal(undone.status, "undone"); assert.deepEqual(undone.after, initial);
  assert.deepEqual(h.adapter.read().settings, initial); assert.equal(h.classes.has("dark"), false);
  assert.equal((await h.adapter.undo(request)).replayed, true); assert.equal(h.storage.writes, 2);
  const stored = JSON.parse(h.storage.getItem(KEY)); assert.equal(stored.notify, true); assert.equal(stored.future, 7);
  await h.patch({ font: "mono" }, "after-undo");
  code(await h.adapter.undo({ ...request, operationId: "undo-again", expectedRevision: h.adapter.read().revision }), "undo_conflict");
});

test("cancel before commit, including while queued for a lock, leaves no operation receipt", async () => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const locks = { request: async (name, options, fn) => { await gate; return fn(); } };
  const h = harness({ locks }), controller = new AbortController();
  const pending = h.patch({ size: 20 }, "cancel-id", { signal: controller.signal });
  controller.abort(); release(); code(await pending, "cancelled");
  assert.equal(h.storage.writes, 0); code(h.adapter.operation("cancel-id"), "operation_unknown");
  code(await h.patch({ size: 20 }, "cancelled-already", { signal: controller.signal }), "cancelled");
});

test("storage write failure preserves exact preferences and current CSS", async () => {
  const h = harness({ storage: new Storage({ [KEY]: JSON.stringify({ size: 16, future: 99 }), [THEME]: "dark" }) });
  h.adapter.sync(); const stored = h.storage.getItem(KEY), styles = { ...h.styles };
  h.storage.writeFailure = true;
  code(await h.patch({ size: 20, theme: "light" }), "storage_write_failed");
  assert.equal(h.storage.getItem(KEY), stored); assert.deepEqual(h.styles, styles); assert.ok(h.classes.has("dark"));
  assert.equal(h.adapter.recentOperations().operations.length, 0);
});

test("failed reads and corrupt records fail closed; post-write read failure is reported truthfully", async () => {
  for (const raw of ["not-json", "[]", '{"__learnnoteReading":{"version":9}}']) {
    const h = harness({ storage: new Storage({ [KEY]: raw }) });
    code(h.adapter.read(), "invalid_storage");
    code(await h.adapter.patch({ operationId: "bad-storage", expectedRevision: "x", patch: { size: 20 } }), "invalid_storage");
    assert.equal(h.storage.getItem(KEY), raw); assert.equal(h.storage.writes, 0);
  }
  const h = harness(), revision = h.adapter.read().revision;
  h.storage.readFailure = true; code(h.adapter.read(), "storage_unavailable");
  code(await h.adapter.patch({ operationId: "read-denied", expectedRevision: revision, patch: { size: 20 } }), "storage_unavailable");
  h.storage.readFailure = false;
  h.storage.afterWrite = () => { h.storage.readFailure = true; };
  const result = await h.patch({ size: 20 }); code(result, "commit_unverified"); assert.equal(result.persisted, true);
  h.storage.readFailure = false; assert.equal(h.adapter.read().settings.size, 20);
});

test("a noncooperating writer after commit is reported without overwriting its new data", async () => {
  const h = harness();
  h.storage.afterWrite = () => { const p = JSON.parse(h.storage.data.get(KEY)); p.size = 15; p.foreign = true; h.storage.data.set(KEY, JSON.stringify(p)); };
  code(await h.patch({ size: 20 }), "commit_conflict");
  assert.equal(h.adapter.read().settings.size, 15); assert.equal(JSON.parse(h.storage.getItem(KEY)).foreign, true);
});

test("agent fails closed without Web Locks while existing manual controls still save", async () => {
  const h = harness({ locks: null });
  code(await h.patch({ size: 20 }), "locking_unavailable");
  const result = await h.adapter.saveManual({ expectedRevision: h.adapter.read().revision,
    preferences: { ...normalizeReading({ size: 20, notify: true }), theme: "dark" } });
  assert.equal(result.ok, true); assert.equal(h.styles["--reader-size"], "20px");
  assert.equal(JSON.parse(h.storage.getItem(KEY)).notify, true); assert.ok(h.classes.has("dark"));
});

test("bounded persisted receipts retain latest operation and original patch for undo recovery", async () => {
  const h = harness(); const request = { operationId: "oldest", expectedRevision: h.adapter.read().revision, patch: { size: 18 } };
  await h.adapter.patch(request);
  for (let index = 0; index < 70; index++) await h.patch({ size: index % 2 ? 18 : 20 }, `bounded-${index}`);
  const operations = h.adapter.recentOperations().operations;
  assert.equal(operations.length, 64); assert.equal(operations.at(-1).operationId, "bounded-69");
  code(await h.adapter.patch(request), "revision_conflict");
  // Many no-op undos are safe and must not evict the newest patch's receipt.
  await h.patch({ size: 18 }, "pinned-noop");
  for (let index = 0; index < 70; index++) {
    const result = await h.adapter.undo({ operationId: `undo-noop-${index}`, targetOperationId: "pinned-noop", expectedRevision: h.adapter.read().revision });
    assert.equal(result.ok, true);
  }
  assert.equal(h.adapter.recentOperations().operations.length, 64);
  assert.equal(h.adapter.operation("pinned-noop").ok, true); assert.equal(h.adapter.operation("undo-noop-69").status, "undone");
});

test("a failed render can be repaired by replay without another persisted operation", async () => {
  let broken = true; const h = harness({ onChange: () => { if (broken) throw new Error("synthetic render failure"); } });
  const request = { operationId: "render-retry", expectedRevision: h.adapter.read().revision, patch: { size: 20 } };
  const result = await h.adapter.patch(request); code(result, "apply_failed"); assert.equal(result.persisted, true);
  broken = false; const replay = await h.adapter.patch(request); assert.equal(replay.ok, true); assert.equal(replay.replayed, true);
  assert.equal(h.storage.writes, 1);
});

test("queued payloads are captured and public recovery excludes manual-only and unrelated fields", async () => {
  let release; const gate = new Promise(resolve => { release = resolve; });
  const h = harness({ locks: { request: async (name, options, fn) => { await gate; return fn(); } },
    storage: new Storage({ [KEY]: JSON.stringify({ notify: true, autoOpen: true, future: "private fixture" }) }) });
  const request = { operationId: "captured", expectedRevision: h.adapter.read().revision, patch: { size: 18 } };
  const pending = h.adapter.patch(request);
  request.operationId = "changed-id"; request.patch.size = 20; request.expectedRevision = "changed";
  release(); const result = await pending;
  assert.equal(result.ok, true); assert.equal(result.operationId, "captured"); assert.equal(result.after.size, 18);
  for (const response of [h.adapter.read(), result, h.adapter.operation("captured"), h.adapter.recentOperations()]) {
    assert.doesNotMatch(JSON.stringify(response), /notify|autoOpen|private fixture|future/);
  }
});
