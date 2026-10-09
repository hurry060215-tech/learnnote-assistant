import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../material-catalog-recovery.js", import.meta.url), "utf8");
const { mountMaterialCatalogRecovery } = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.dataset = {}; this.style = {}; this.listeners = {}; this.attributes = {}; this._text = ""; this.disabled = false; }
  get isConnected() { return this.tagName === "body" || Boolean(this.parent?.isConnected); }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(""); }
  set textContent(value) { this._text = String(value); this.replaceChildren(); }
  append(...nodes) { for (const node of nodes) { node.parent = this; this.children.push(node); } }
  replaceChildren(...nodes) { for (const child of this.children) child.parent = null; this.children = []; this.append(...nodes); }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  async click() { if (!this.disabled) await this.listeners.click?.(); }
}
class Multipart {
  constructor() { this.fields = new Map(); }
  append(name, value) { this.fields.set(name, value); }
  get(name) { return this.fields.get(name); }
}
const all = root => [root, ...root.children.flatMap(all)];
const deferred = () => { let resolve, reject; const promise = new Promise((done, fail) => { resolve = done; reject = fail; }); return { promise, resolve, reject }; };
const snapshot = (name = "chosen.sqlite3") => ({ name, size: 80 });
const goodPreview = () => ({ snapshot_sha256: "a".repeat(64), preview_token: "chosen-preview-token", recovery_scope: "material_catalog_only", can_apply: true, recoverable_count: 1, materials: [{ material_id: "retained-id", title: "<img onerror=bad> 编码选择", status: "recoverable", reason: "按所选快照恢复 gb18030 与历史编号" }], unresolved: [], message: "快照核对完成" });
const applied = () => ({ status: "pass", restored_material_count: 1, restored_evidence_count: 2, rollback_snapshot_created: true, rollback_directory: "catalog-recovery-0123456789abcdef", unresolved: [] });
function setup(handler = async path => path.endsWith("/status") ? { state: "missing", recovery_required: true, orphaned_material_ids: ["retained-id"], message: "本机目录缺失。" } : path.endsWith("/preview") ? goodPreview() : applied()) {
  const body = new Element("body"), container = new Element("main"); body.append(container);
  globalThis.document = { createElement: tag => new Element(tag) };
  globalThis.FormData = Multipart;
  let current = true;
  const calls = [], updates = [];
  const panel = mountMaterialCatalogRecovery(container, { api: async (...args) => { calls.push(args); return handler(...args); }, isCurrent: () => current, onRecovered: async value => updates.push(value) });
  const get = id => all(panel.root).find(item => item.id === `materialCatalog${id}`);
  const choose = file => { get("Snapshot").files = file ? [file] : []; get("Snapshot").listeners.change(); };
  return { ...panel, calls, updates, container, get, choose, leave: () => { current = false; } };
}

test("opening only checks catalog; explicit selection and preview authorize the same file and token", async () => {
  const h = setup(); await h.ready;
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0][0], "/api/library/catalog/status");
  assert.equal(h.calls[0][1], undefined);
  assert.equal(h.get("Preview").disabled, true); assert.equal(h.get("Apply").disabled, true);
  assert.match(h.get("Status").textContent, /目录：缺失.*1 份/);
  assert.match(h.root.textContent, /仅有原文件无法找回丢失的编号、编码选择或历史关联/);
  assert.match(h.root.textContent, /无法证明所选快照就是最新的历史版本/);
  const file = snapshot(); h.choose(file);
  assert.equal(h.calls.length, 1, "Selecting a file cannot apply or even preview it automatically");
  await h.get("Preview").click();
  assert.equal(h.calls[1][1].body.get("file"), file);
  assert.match(h.get("Results").textContent, /<img onerror=bad>/);
  assert.equal(all(h.root).filter(item => item.tagName === "img").length, 0);
  assert.equal(h.get("Apply").disabled, false);
  await h.get("Apply").click();
  assert.equal(h.calls[2][0], "/api/library/catalog/recovery/apply");
  assert.equal(h.calls[2][1].body.get("file"), file);
  assert.equal(h.calls[2][1].body.get("preview_token"), "chosen-preview-token");
  assert.equal(h.updates.length, 1);
  assert.match(h.get("Progress").textContent, /1 份资料，2 条出处。已创建回滚快照/);
  assert.match(h.get("Results").textContent, /回滚备份位置：数据文件夹\/exports\/catalog-recovery-0123456789abcdef/);
  assert.equal(h.get("Apply").disabled, true, "A completed preview cannot be replayed");
  assert.equal(h.get("Snapshot").disabled, false);
  assert.ok(!h.calls.some(([path]) => path === "/api/library/restore"));
});

test("invalid and empty file choices never send a request", async () => {
  const h = setup(); await h.ready;
  for (const file of [snapshot("wrong.json"), { ...snapshot(), size: 0 }, { ...snapshot(), size: 128 * 1024 * 1024 + 1 }, null]) {
    h.choose(file); await h.get("Preview").click(); await h.get("Apply").click();
    assert.equal(h.get("Preview").disabled, true); assert.equal(h.get("Apply").disabled, true);
  }
  assert.equal(h.calls.length, 1);
});

test("excluded video registrations explain their original-task requirement without blocking documents", async () => {
  const h = setup(path => path.endsWith("/status") ? { state: "missing" } : {
    ...goodPreview(), excluded_count: 1, materials: [...goodPreview().materials,
      { material_id: "video-alias", title: "视频资料", status: "excluded", reason: "视频资料登记需要原任务，不在文档目录恢复范围内。" }],
  });
  await h.ready; h.choose(snapshot()); await h.get("Preview").click();
  assert.equal(h.get("Apply").disabled, false);
  assert.match(h.get("Results").textContent, /视频资料 · 不在恢复范围.*视频资料登记需要原任务/);
});

test("unresolved/conflicting metadata, zero recovery, wrong scope or absent token forbid apply", async () => {
  for (const change of [
    { can_apply: false }, { recoverable_count: 0 }, { preview_token: "" }, { recovery_scope: "tasks" },
    { unresolved: [{ material_id: "missing", reason: "原文件不存在" }] },
    { materials: [{ material_id: "bad", title: "冲突资料", status: "unresolved", reason: "编码元数据冲突" }] },
    { materials: [] },
  ]) {
    const h = setup(async path => path.endsWith("/status") ? { state: "incomplete" } : ({ ...goodPreview(), ...change })); await h.ready;
    h.choose(snapshot()); await h.get("Preview").click(); await h.get("Apply").click();
    assert.equal(h.get("Apply").disabled, true);
    assert.match(h.get("Progress").textContent, /当前预览不能执行恢复/);
    assert.equal(h.calls.length, 2);
    if (change.unresolved) assert.match(h.get("Results").textContent, /原文件不存在/);
    if (change.materials?.[0]) assert.match(h.get("Results").textContent, /编码元数据冲突/);
  }
});

test("new selection clears preview and ignores an older delayed success or error", async () => {
  for (const fail of [false, true]) {
    const old = deferred();
    const h = setup(async (path, options) => path.endsWith("/status") ? { state: "corrupt" } : options.body.get("file").name === "old.sqlite3" ? old.promise : { ...goodPreview(), preview_token: "new-token", snapshot_sha256: "b".repeat(64) });
    await h.ready; h.choose(snapshot("old.sqlite3")); const pending = h.get("Preview").click();
    h.choose(snapshot("new.sqlite3")); assert.equal(h.get("Results").textContent, "");
    await h.get("Preview").click(); const before = h.get("Results").textContent;
    if (fail) old.reject(new Error("STALE ERROR")); else old.resolve({ ...goodPreview(), message: "STALE RESULT" });
    await pending;
    assert.equal(h.get("Results").textContent, before); assert.doesNotMatch(h.root.textContent, /STALE/);
    assert.match(before, /new.sqlite3/); assert.equal(h.get("Apply").disabled, false);
    h.choose(snapshot("third.sqlite3")); assert.equal(h.get("Apply").disabled, true); assert.equal(h.get("Results").textContent, "");
  }
});

test("double clicks submit each operation once and lock selection while applying", async () => {
  const preview = deferred(), apply = deferred();
  const h = setup(path => path.endsWith("/status") ? { state: "healthy" } : path.endsWith("/preview") ? preview.promise : apply.promise);
  await h.ready; h.choose(snapshot());
  const p = h.get("Preview").click(); await h.get("Preview").click();
  assert.equal(h.calls.length, 2); preview.resolve(goodPreview()); await p;
  const a = h.get("Apply").click(); await h.get("Apply").click();
  assert.equal(h.calls.length, 3); assert.equal(h.get("Snapshot").disabled, true);
  assert.equal(h.get("RebuildTasks").disabled, true); await h.get("RebuildTasks").click(); assert.equal(h.calls.length, 3);
  apply.resolve(applied()); await a; assert.equal(h.updates.length, 1);
});

test("closed or replaced panels ignore delayed status, preview, and apply success/failure", async () => {
  for (const stage of ["status", "preview", "apply"]) for (const fail of [false, true]) for (const detach of [false, true]) {
    const response = deferred();
    const h = setup(path => path.endsWith(`/${stage}`) ? response.promise : path.endsWith("/status") ? { state: "missing" } : goodPreview());
    let pending = h.ready;
    if (stage !== "status") { await h.ready; h.choose(snapshot()); pending = h.get("Preview").click(); }
    if (stage === "apply") { await pending; pending = h.get("Apply").click(); }
    const before = h.root.textContent;
    if (detach) h.container.replaceChildren(); else h.leave();
    if (fail) response.reject(new Error("LATE ERROR")); else response.resolve(stage === "status" ? { state: "healthy", message: "LATE STATUS" } : stage === "preview" ? goodPreview() : applied());
    await pending;
    assert.equal(h.root.textContent, before); assert.equal(h.updates.length, 0);
  }
});

test("structured failure text stays readable and apply failures require a fresh preview", async () => {
  let phase = "status";
  const h = setup(path => {
    if (path.endsWith(`/${phase}`)) throw Object.assign(new Error("快照已变化，请重新核对"), { code: "snapshot_mismatch" });
    return path.endsWith("/status") ? { state: "healthy" } : goodPreview();
  });
  await h.ready; assert.match(h.get("Status").textContent, /检查失败.*snapshot_mismatch/);
  phase = "preview"; await h.get("Check").click(); assert.match(h.get("Status").textContent, /正常/);
  h.choose(snapshot()); await h.get("Preview").click(); assert.match(h.get("Progress").textContent, /预览失败.*snapshot_mismatch/);
  assert.equal(h.get("Apply").disabled, true);
  phase = "apply"; await h.get("Preview").click(); await h.get("Apply").click();
  assert.match(h.get("Progress").textContent, /恢复失败.*snapshot_mismatch.*重新预览/);
  assert.equal(h.get("Results").textContent, "", "A stale or failed apply invalidates the old preview result");
  assert.equal(h.get("Apply").disabled, true); assert.equal(h.get("Preview").disabled, false);
});

test("partial results retain per-item reasons without claiming all materials recovered", async () => {
  const h = setup(path => path.endsWith("/status") ? { state: "incomplete" } : path.endsWith("/preview") ? goodPreview() : { ...applied(), status: "partial", unresolved: [{ material_id: "unresolved-id", reason: "原文件在预览后丢失" }] });
  await h.ready; h.choose(snapshot()); await h.get("Preview").click(); await h.get("Apply").click();
  assert.match(h.get("Progress").textContent, /部分恢复完成/);
  assert.match(h.get("Results").textContent, /unresolved-id.*原文件在预览后丢失/);
});

test("rollback location is literal text with no path link or markup execution", async () => {
  const h = setup(path => path.endsWith("/status") ? { state: "missing" } : path.endsWith("/preview") ? goodPreview() : { ...applied(), rollback_directory: '<a href="unsafe">backup</a>' });
  await h.ready; h.choose(snapshot()); await h.get("Preview").click(); await h.get("Apply").click();
  assert.match(h.get("Results").textContent, /数据文件夹\/exports\/<a href="unsafe">backup<\/a>/);
  assert.equal(all(h.get("Results")).filter(element => element.tagName === "a").length, 0);
});

test("task rebuild reports pass, partial and blocked honestly, preserving selection but invalidating preview", async () => {
  for (const outcome of ["pass", "partial", "blocked"]) {
    const result = { status: outcome, indexed: outcome === "blocked" ? 0 : 2, skipped: 1 };
    const h = setup(path => path.endsWith("/status") ? { state: outcome === "blocked" ? "corrupt" : "incomplete" } : path.endsWith("/rebuild") ? result : goodPreview());
    await h.ready; const file = snapshot(); h.choose(file); await h.get("Preview").click();
    assert.equal(h.get("Apply").disabled, false); await h.get("RebuildTasks").click();
    assert.equal(h.calls[2][0], "/api/library/rebuild"); assert.equal(h.calls[2][1].method, "POST"); assert.equal(h.calls[2][1].body, undefined);
    assert.equal(h.calls[3][0], "/api/library/catalog/status");
    assert.equal(h.get("Snapshot").files[0], file); assert.equal(h.get("Results").textContent, "");
    assert.equal(h.get("Apply").disabled, true); assert.equal(h.get("Preview").disabled, false);
    assert.match(h.get("Progress").textContent, outcome === "pass" ? /任务索引重建完成/ : outcome === "partial" ? /仅部分完成，文档目录仍未恢复/ : /重建受阻，文档目录未恢复/);
    if (outcome !== "pass") { assert.match(h.get("Progress").textContent, /选择已有 SQLite 快照预览并恢复文档目录/); assert.doesNotMatch(h.get("Progress").textContent, /恢复完成/); }
    assert.match(h.get("Progress").textContent, /已选快照需重新预览/);
    assert.equal(h.updates.length, outcome === "blocked" ? 0 : 1);
  }
});

test("task rebuild excludes preview/apply and repeated clicks", async () => {
  const preview = deferred(), rebuild = deferred();
  const h = setup(path => path.endsWith("/status") ? { state: "missing" } : path.endsWith("/preview") ? preview.promise : rebuild.promise);
  await h.ready; h.choose(snapshot()); const p = h.get("Preview").click();
  assert.equal(h.get("RebuildTasks").disabled, true); await h.get("RebuildTasks").click(); assert.equal(h.calls.length, 2);
  preview.resolve(goodPreview()); await p;
  const r = h.get("RebuildTasks").click(); await h.get("RebuildTasks").click(); await h.get("Preview").click(); await h.get("Apply").click();
  assert.equal(h.calls.length, 3); assert.equal(h.get("Snapshot").disabled, true);
  assert.equal(h.get("Preview").disabled, true); assert.equal(h.get("Apply").disabled, true);
  rebuild.resolve({ status: "partial", indexed: 1, skipped: 0 }); await r;
  assert.equal(h.get("RebuildTasks").disabled, false); assert.equal(h.get("Snapshot").disabled, false);
});

test("closed or replaced panels suppress late task rebuild responses and failures", async () => {
  for (const fail of [false, true]) for (const detach of [false, true]) {
    const response = deferred();
    const h = setup(path => path.endsWith("/status") ? { state: "missing" } : response.promise);
    await h.ready; const pending = h.get("RebuildTasks").click(), before = h.root.textContent;
    if (detach) h.container.replaceChildren(); else h.leave();
    if (fail) response.reject(new Error("LATE TASK ERROR")); else response.resolve({ status: "partial", indexed: 2, skipped: 0 });
    await pending; assert.equal(h.root.textContent, before); assert.equal(h.updates.length, 0); assert.equal(h.calls.length, 2);
  }
});

test("task rebuild failure clears old eligibility and checks current catalog state", async () => {
  const h = setup(path => { if (path.endsWith("/rebuild")) throw new Error("Task rebuild unavailable"); return path.endsWith("/status") ? { state: "corrupt" } : goodPreview(); });
  await h.ready; h.choose(snapshot()); await h.get("Preview").click(); await h.get("RebuildTasks").click();
  assert.match(h.get("Progress").textContent, /任务索引重建失败.*Task rebuild unavailable/);
  assert.equal(h.get("Apply").disabled, true); assert.equal(h.get("Results").textContent, "");
  assert.equal(h.calls.at(-1)[0], "/api/library/catalog/status"); assert.equal(h.updates.length, 0);
});

const tools = readFileSync(new URL("../desk-tools.js", import.meta.url), "utf8");
assert.match(tools, /mountMaterialCatalogRecovery\(\$\("toolBody"\), \{ api, isCurrent: \(\) => token === generation && dialog.open, onRecovered: refresh \}\)/);
