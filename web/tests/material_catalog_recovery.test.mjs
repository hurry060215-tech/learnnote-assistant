import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../material-catalog-recovery.js", import.meta.url), "utf8");
const moduleUrl = text => "data:text/javascript;base64," + Buffer.from(text).toString("base64");
const viewUrl = moduleUrl(readFileSync(new URL("../catalog-recovery-view.js", import.meta.url), "utf8"));
const taskSource = readFileSync(new URL("../task-catalog-recovery.js", import.meta.url), "utf8");
const taskUrl = moduleUrl(taskSource.replace('"/web/catalog-recovery-view.js"', JSON.stringify(viewUrl)));
const { mountMaterialCatalogRecovery } = await import(moduleUrl(source
  .replace('"/web/catalog-recovery-view.js"', JSON.stringify(viewUrl))
  .replace('"/web/task-catalog-recovery.js"', JSON.stringify(taskUrl))));
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
function setup(handler = async path => path.endsWith("/status") ? { state: "missing", recovery_required: true, orphaned_material_ids: ["retained-id"], message: "本机目录缺失。" } : path.endsWith("/preview") ? goodPreview() : applied(), options = {}) {
  const body = new Element("body"), container = new Element("main"); body.append(container);
  globalThis.document = { createElement: tag => new Element(tag) };
  globalThis.FormData = Multipart;
  let current = true;
  const calls = [], updates = [];
  const panel = mountMaterialCatalogRecovery(container, { api: async (...args) => { calls.push(args); return handler(...args); }, isCurrent: () => current, onRecovered: async value => { updates.push(value); await options.onRecovered?.(value); } });
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

const taskPreview = () => ({ can_apply: true, recovery_scope: "task_catalog_only", preview_token: "f".repeat(64), task_count: 2, evidence_count: 4, unknown_documents_unrestored: true, document_count: null, message: "未知文档未恢复，缺失数量无法确定。", restore_instructions: "完全退出应用，先保留新目录，再还原原始字节。" });
const taskApplied = () => ({ ...taskPreview(), status: "partial", restored_task_count: 2, restored_evidence_count: 4, rollback_directory: "catalog-recovery-original", rollback_snapshot_created: true });

test("corrupt task rescue requires its own fresh explicit preview and scope confirmation", async () => {
  const h = setup(path => path.endsWith("/status") ? { state: "corrupt" } : path.endsWith("/preview") ? taskPreview() : taskApplied());
  await h.ready;
  assert.equal(h.calls.length, 1); assert.equal(h.get("TaskApply").disabled, true);
  assert.match(h.root.textContent, /未知文档.*缺失数量无法确定/);
  await h.get("TaskPreview").click();
  assert.equal(h.calls[1][0], "/api/library/catalog/tasks/preview");
  assert.equal(h.get("TaskApply").disabled, false);
  assert.match(h.get("TaskStatus").textContent, /2 个任务、4 条出处/);
  await h.get("TaskApply").click();
  assert.equal(h.calls[2][0], "/api/library/catalog/tasks/apply");
  assert.deepEqual(JSON.parse(h.calls[2][1].body), { preview_token: "f".repeat(64), confirm_scope: "task_catalog_only" });
  assert.match(h.get("TaskStatus").textContent, /未知文档未恢复.*catalog-recovery-original.*完全退出/);
  assert.equal(h.get("TaskApply").disabled, true);
});

test("task recovery disabled diagnostics cannot be bypassed by clicking apply", async () => {
  for (const change of [{ can_apply: false, diagnostic: "未处理事务日志" }, { recovery_scope: "material_catalog_only" }, { preview_token: "bad" }]) {
    const h = setup(path => path.endsWith("/status") ? { state: "corrupt" } : { ...taskPreview(), ...change });
    await h.ready; await h.get("TaskPreview").click(); await h.get("TaskApply").click();
    assert.equal(h.calls.length, 2); assert.equal(h.get("TaskApply").disabled, true);
    if (change.diagnostic) assert.match(h.get("TaskStatus").textContent, /未处理事务日志/);
  }
});

test("cancel discards pending task preview and prevents a late result from authorizing apply", async () => {
  const pending = deferred();
  const h = setup(path => path.endsWith("/status") ? { state: "corrupt" } : pending.promise);
  await h.ready;
  const request = h.get("TaskPreview").click();
  assert.equal(h.get("RebuildTasks").disabled, true);
  await h.get("TaskCancel").click();
  pending.resolve(taskPreview()); await request;
  assert.match(h.get("TaskStatus").textContent, /已取消/);
  assert.equal(h.get("TaskApply").disabled, true); assert.equal(h.get("TaskPreview").disabled, false);
});

test("changed document selection and stale navigation invalidate task recovery results", async () => {
  for (const phase of ["preview", "apply"]) {
    const pending = deferred();
    const h = setup(path => path.endsWith("/status") ? { state: "corrupt" } : path.endsWith("/" + phase) ? pending.promise : taskPreview());
    await h.ready;
    if (phase === "apply") await h.get("TaskPreview").click();
    const request = h.get(phase === "preview" ? "TaskPreview" : "TaskApply").click();
    const before = h.root.textContent;
    h.leave(); pending.resolve(phase === "preview" ? taskPreview() : taskApplied()); await request;
    assert.equal(h.root.textContent, before); assert.equal(h.updates.length, 0);
  }
  const h = setup(path => path.endsWith("/status") ? { state: "corrupt" } : taskPreview());
  await h.ready; await h.get("TaskPreview").click(); h.choose(snapshot());
  assert.equal(h.get("TaskApply").disabled, true);
});

test("task rescue deduplicates apply and retains confirmed success when list refresh fails", async () => {
  const pending = deferred();
  const h = setup(path => path.endsWith("/status") ? { state: "corrupt" } : path.endsWith("/preview") ? taskPreview() : pending.promise,
    { onRecovered: async () => { throw new Error("synthetic refresh failed"); } });
  await h.ready; await h.get("TaskPreview").click();
  const request = h.get("TaskApply").click();
  await h.get("TaskApply").click(); await h.get("TaskPreview").click(); await h.get("TaskCancel").click();
  assert.equal(h.calls.length, 3); assert.equal(h.get("Snapshot").disabled, true);
  pending.resolve(taskApplied()); await request;
  assert.match(h.get("TaskStatus").textContent, /已恢复 2 个任务.*catalog-recovery-original.*列表刷新失败/);
  assert.doesNotMatch(h.get("TaskStatus").textContent, /未确认完成/);
});

test("reopening retains task-only warning, backup identity and offline rollback instructions", async () => {
  const h = setup(() => ({ state: "incomplete", message: "未知文档未恢复", task_only_recovery: { backup_directory: "catalog-recovery-retained", restore_instructions: "完全退出；先保留新目录；恢复原先损坏状态。" } }));
  await h.ready;
  assert.match(h.get("TaskStatus").textContent, /未知文档未恢复.*catalog-recovery-retained.*原先损坏状态/);
  assert.equal(h.calls.length, 1);
});

test("document preview and completion retain their exact literal output after extraction", async () => {
  const h = setup(); await h.ready; h.choose(snapshot());
  await h.get("Preview").click();
  assert.equal(h.get("Results").textContent, `快照：chosen.sqlite3 · SHA-256：${"a".repeat(64)}<img onerror=bad> 编码选择 · 可恢复资料编号：retained-id按所选快照恢复 gb18030 与历史编号`);
  assert.equal(h.get("Progress").textContent, "快照核对完成 可恢复 1 份资料。请核对后确认；执行前会创建回滚快照。");
  await h.get("Apply").click();
  assert.equal(h.get("Results").textContent, "恢复请求已完成。回滚备份位置：数据文件夹/exports/catalog-recovery-0123456789abcdef");
  assert.equal(h.get("Progress").textContent, "恢复完成：1 份资料，2 条出处。已创建回滚快照。");
});

test("cancelled task response cannot release an active document preview or lend its token", async () => {
  for (const fail of [false, true]) {
    const task = deferred(), document = deferred();
    const h = setup(path => path.endsWith("/status") ? { state: "corrupt" }
      : path.includes("/tasks/") ? task.promise : document.promise);
    await h.ready; h.choose(snapshot());
    const oldTask = h.get("TaskPreview").click();
    await h.get("TaskPreview").click();
    assert.equal(h.calls.length, 2, "Duplicate task previews are suppressed");
    await h.get("TaskCancel").click();
    const currentDocument = h.get("Preview").click();
    if (fail) task.reject(new Error("LATE CANCELLED TASK")); else task.resolve(taskPreview());
    await oldTask;
    assert.equal(h.get("Preview").disabled, true);
    assert.equal(h.get("TaskPreview").disabled, true);
    assert.equal(h.get("Apply").disabled, true);
    assert.equal(h.get("TaskApply").disabled, true);
    assert.match(h.get("TaskStatus").textContent, /已取消/);
    await h.get("Apply").click(); await h.get("TaskApply").click();
    assert.equal(h.calls.length, 3);
    document.resolve(goodPreview()); await currentDocument;
    assert.equal(h.get("Apply").disabled, false);
    assert.equal(h.get("TaskApply").disabled, true);
  }
});

test("changed selection invalidates an older document preview while task preview owns the lifecycle", async () => {
  for (const fail of [false, true]) {
    const document = deferred(), task = deferred();
    const h = setup(path => path.endsWith("/status") ? { state: "corrupt" }
      : path.includes("/tasks/") ? task.promise : document.promise);
    await h.ready; h.choose(snapshot("old.sqlite3"));
    const oldDocument = h.get("Preview").click();
    await h.get("TaskPreview").click();
    assert.equal(h.calls.length, 2, "Pending document preview excludes task preview");
    h.choose(snapshot("new.sqlite3"));
    const currentTask = h.get("TaskPreview").click();
    if (fail) document.reject(new Error("LATE DOCUMENT")); else document.resolve(goodPreview());
    await oldDocument;
    assert.equal(h.get("TaskPreview").disabled, true);
    assert.equal(h.get("Preview").disabled, true);
    assert.equal(h.get("Apply").disabled, true);
    assert.equal(h.get("Results").textContent, "");
    task.resolve(taskPreview()); await currentTask;
    assert.equal(h.get("Apply").disabled, true);
    assert.equal(h.get("TaskApply").disabled, false);
  }
});

test("alternating document and task recoveries always require their own fresh scoped token", async () => {
  const h = setup(path => path.endsWith("/status") ? { state: "corrupt" }
    : path.includes("/tasks/") ? path.endsWith("/preview") ? taskPreview() : taskApplied()
    : path.endsWith("/preview") ? goodPreview() : applied());
  await h.ready; const file = snapshot(); h.choose(file);
  await h.get("Preview").click(); await h.get("TaskPreview").click();
  assert.equal(h.get("Apply").disabled, true);
  await h.get("Apply").click(); await h.get("TaskApply").click();
  assert.equal(h.get("Apply").disabled, true);
  await h.get("Preview").click(); await h.get("Apply").click();
  await h.get("TaskPreview").click(); await h.get("Preview").click();
  assert.equal(h.get("TaskApply").disabled, true);
  await h.get("TaskApply").click(); await h.get("Apply").click();
  const applies = h.calls.filter(([path]) => path.endsWith("/apply"));
  assert.equal(applies.length, 3);
  assert.equal(applies[0][0], "/api/library/catalog/tasks/apply");
  assert.deepEqual(JSON.parse(applies[0][1].body), { preview_token: "f".repeat(64), confirm_scope: "task_catalog_only" });
  for (const [path, options] of applies.slice(1)) {
    assert.equal(path, "/api/library/catalog/recovery/apply");
    assert.equal(options.body.get("preview_token"), "chosen-preview-token");
    assert.equal(options.body.get("file"), file);
  }
});

test("closing and remounting isolates late task preview and apply responses from the new panel", async () => {
  for (const phase of ["preview", "apply"]) for (const fail of [false, true]) {
    const pending = deferred();
    const old = setup(path => path.endsWith("/status") ? { state: "corrupt" }
      : path.endsWith("/" + phase) ? pending.promise : taskPreview());
    await old.ready;
    if (phase === "apply") await old.get("TaskPreview").click();
    const request = old.get(phase === "preview" ? "TaskPreview" : "TaskApply").click();
    const oldText = old.root.textContent;
    old.container.replaceChildren();
    const calls = [];
    const fresh = mountMaterialCatalogRecovery(old.container, {
      api: async path => { calls.push(path); return path.endsWith("/status") ? { state: "corrupt" } : taskPreview(); },
    });
    await fresh.ready;
    const freshApply = all(fresh.root).find(item => item.id === "materialCatalogTaskApply");
    const before = fresh.root.textContent;
    if (fail) pending.reject(new Error("LATE CLOSED TASK")); else pending.resolve(phase === "preview" ? taskPreview() : taskApplied());
    await request;
    assert.equal(fresh.root.textContent, before);
    assert.equal(old.root.textContent, oldText);
    assert.equal(freshApply.disabled, true);
    assert.equal(old.updates.length, 0);
    assert.deepEqual(calls, ["/api/library/catalog/status"]);
  }
});

test("a new task preview retains its lock when an earlier cancelled preview finishes", async () => {
  const first = deferred(), second = deferred(); let requests = 0;
  const h = setup(path => path.endsWith("/status") ? { state: "corrupt" } : ++requests === 1 ? first.promise : second.promise);
  await h.ready;
  const old = h.get("TaskPreview").click(); await h.get("TaskCancel").click();
  const current = h.get("TaskPreview").click();
  first.resolve(taskPreview()); await old;
  assert.equal(h.get("TaskPreview").disabled, true);
  assert.equal(h.get("TaskApply").disabled, true);
  assert.equal(h.get("TaskCancel").disabled, false);
  second.resolve({ ...taskPreview(), preview_token: "e".repeat(64) }); await current;
  assert.equal(h.get("TaskApply").disabled, false);
});
