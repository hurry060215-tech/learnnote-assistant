import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import test from "node:test";
const source = fs.readFileSync(new URL("../task-diagnostic-export.js", import.meta.url), "utf8");
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.events = {}; this.isConnected = true; this.style = {}; this.value = tag === "select" ? "md" : ""; this.textContent = ""; }
  append(...items) { this.children.push(...items); }
  setAttribute(key, value) { this[key] = value; }
  addEventListener(name, handler) { (this.events[name] ||= new Set()).add(handler); }
  removeEventListener(name, handler) { this.events[name]?.delete(handler); }
  emit(name) { for (const handler of this.events[name] || []) handler(); }
  click() { this.emit("click"); }
  showModal() { this.open = true; }
  close() { this.open = false; this.emit("close"); }
  remove() { this.isConnected = false; }
  set innerHTML(_) { throw new Error("Report bytes must never enter HTML"); }
}
const tick = () => new Promise(resolve => setImmediate(resolve));
function setup() {
  const nodes = [], requests = [], blobs = [], revoked = [], timers = [];
  const window = new Element("window");
  const document = { body: new Element("body"), addEventListener() {}, createElement(tag) { const node = new Element(tag); nodes.push(node); return node; }, createTextNode(text) { const node = new Element("text"); node.textContent = text; return node; } };
  const context = { document, window, Blob, TextDecoder, AbortController, setTimeout(fn) { timers.push(fn); }, URL: { createObjectURL(blob) { blobs.push(blob); return "blob:fixture"; }, revokeObjectURL(url) { revoked.push(url); } }, fetch(path, options) { return new Promise(resolve => requests.push({ path, options, resolve })); } };
  vm.createContext(context); vm.runInContext(source, context);
  function find(text) { return nodes.findLast(node => node.textContent === text); }
  function resolve(index, text, ok = true) { const bytes = new TextEncoder().encode(text); requests[index].resolve({ ok, arrayBuffer: async () => bytes.buffer }); return bytes; }
  function consent() { const node = nodes.findLast(node => node.type === "checkbox"); node.checked = true; node.emit("change"); }
  return { context, document, api: context.LearnNoteDiagnosticExport, nodes, requests, blobs, timers, revoked, find, resolve, consent };
}
test("literal HTML preview and actual Blob bytes equal one fetched UTF-8 response; explicit one-shot save only", async () => {
  const h = setup(); h.api.open({ taskId: "private/id" });
  const payload = '\ufeff# 诊断\r\n<img src=x onerror="bad">\nusage: null\n';
  const bytes = h.resolve(0, payload); await tick();
  assert.equal(h.nodes.find(node => node.tag === "pre").textContent, payload);
  assert.equal(h.blobs.length, 0); h.find("保存已预览报告").click(); assert.equal(h.blobs.length, 0);
  h.consent(); h.find("保存已预览报告").click(); h.find("保存已预览报告").click();
  assert.equal(h.blobs.length, 1); assert.deepEqual(new Uint8Array(await h.blobs[0].arrayBuffer()), bytes);
  assert.equal(h.requests.length, 1); assert.equal(h.requests[0].path, "/api/tasks/private%2Fid/exports/diagnostics");
  assert.equal(h.nodes.find(node => node.tag === "a").download, "learnnote-diagnostics.md");
  h.timers.forEach(fn => fn()); assert.deepEqual(h.revoked, ["blob:fixture"]);
  assert.doesNotMatch(source, /sendBeacon|XMLHttpRequest|export_task\(|method:\s*["'](?:POST|PUT)|navigator\./);
});
test("format supersession drops older response; JSON uses exact bytes and generic name", async () => {
  const h = setup(); h.api.open({ taskId: "task" });
  const select = h.nodes.find(node => node.tag === "select"); select.value = "json"; select.emit("change");
  assert.equal(h.requests[0].options.signal.aborted, true);
  const bytes = h.resolve(1, '{"schema_version":1,"usage":null}\n'); await tick();
  h.resolve(0, "stale"); await tick(); h.consent(); h.find("保存已预览报告").click();
  assert.deepEqual(new Uint8Array(await h.blobs[0].arrayBuffer()), bytes);
  assert.equal(h.nodes.find(node => node.tag === "a").download, "learnnote-diagnostics.json");
  assert.match(h.requests[1].path, /\?format=json$/);
});
for (const action of ["取消导出", "关闭", "← 返回", "invalidate", "cancel", "close", "pagehide"]) {
  test(`${action} invalidates pending response and cached save`, async () => {
    const h = setup(), handle = h.api.open({ taskId: "task" });
    if (action === "pagehide") h.context.window.emit("pagehide");
    else if (action === "invalidate") h.api.invalidate();
    else if (["cancel", "close"].includes(action)) handle.dialog.emit(action);
    else h.find(action).click();
    assert.equal(h.requests[0].options.signal.aborted, true);
    h.resolve(0, "late"); await tick(); h.consent(); h.find("保存已预览报告").click(); assert.equal(h.blobs.length, 0);
  });
}
test("navigation away and return, refresh, close/reopen and parent close never revive old save", async () => {
  for (const reason of ["navigation", "refresh", "reopen", "parent-close"]) {
    const h = setup(), parent = new Element("dialog"); let epoch = 1;
    h.api.open({ taskId: "task", parent, isCurrent: () => epoch === 1 });
    h.resolve(0, "ready"); await tick(); h.consent(); const oldSave = h.find("保存已预览报告");
    if (reason === "navigation") { epoch = 2; oldSave.click(); epoch = 1; }
    else if (reason === "refresh") h.api.invalidate();
    else if (reason === "parent-close") parent.emit("close");
    else h.api.open({ taskId: "task" });
    oldSave.click(); assert.equal(h.blobs.length, 0);
  }
});
test("failed response is never previewed or saved", async () => {
  const h = setup(); h.api.open({ taskId: "task" }); h.resolve(0, "raw private error", false); await tick();
  h.consent(); h.find("保存已预览报告").click(); assert.equal(h.blobs.length, 0);
  assert.equal(h.nodes.find(node => node.tag === "pre").textContent, "");
  assert.ok(h.find("无法读取安全诊断报告。请关闭后重试；未保存或发送任何内容。"));
});
test("classic load order, all diagnostic anchors replaced, and installed desk hooks are explicit", () => {
  const read = file => fs.readFileSync(new URL(`../../${file}`, import.meta.url), "utf8");
  const html = read("web/classic.html"), app = read("web/app.js"), desk = read("web/desk.js"), tools = read("web/desk-tools.js");
  assert.ok(html.indexOf('/web/task-diagnostic-export.js') < html.indexOf('/web/app.js'));
  assert.doesNotMatch(app, /<a href="\$\{escapeHtml\(taskExportUrl\(task, "diagnostics"/);
  assert.ok(app.indexOf('["diagnostics", "support-package"].includes(exportType)') < app.indexOf('await api.export_task'));
  assert.match(app, /function selectTask[^]*?LearnNoteDiagnosticExport\?\.invalidate\(\)/);
  assert.doesNotMatch(app, /async function loadTasks\(\) \{\s+LearnNoteDiagnosticExport.invalidate/);
  assert.match(app, /els.refreshButton.onclick = \(\) => \{ globalThis.LearnNoteDiagnosticExport\?\.invalidate\(\)/);
  assert.match(desk, /\$\("refresh"\).onclick = \(\) => \{\s+globalThis.LearnNoteDiagnosticExport\?\.invalidate\(\)/);
  assert.doesNotMatch(desk, /function refresh\(\) \{\s+.*LearnNoteDiagnosticExport/);
  assert.match(desk, /LearnNoteDiagnosticExport\?\.invalidate\(\);\s+const epoch = \+\+state.epoch/);
  assert.match(desk, /LearnNoteDiagnosticExport\?\.invalidate\(\);\s+state.epoch\+\+/);
  const deskHtml = read("web/index.html");
  assert.ok(deskHtml.indexOf("/web/task-diagnostic-export.js") < deskHtml.indexOf("/web/desk.js"));
  assert.doesNotMatch(tools.slice(tools.indexOf('async function diagnostics()'), tools.indexOf('function more()')), /exports\/support-package|events\?limit=2000|exports\/resource-usage/);
});

for (const failure of ["Blob", "createObjectURL", "click"]) {
  test(`save ${failure} failure has fixed feedback and revokes any allocated URL`, async () => {
    const h = setup();
    if (failure === "Blob") h.context.Blob = class { constructor() { throw new Error("private raw error"); } };
    if (failure === "createObjectURL") h.context.URL.createObjectURL = () => { throw new Error("private raw error"); };
    if (failure === "click") {
      const create = h.document.createElement;
      h.document.createElement = tag => { const node = create(tag); if (tag === "a") node.click = () => { throw new Error("private raw error"); }; return node; };
    }
    h.api.open({ taskId: "task" }); h.resolve(0, "safe"); await tick(); h.consent(); h.find("保存已预览报告").click();
    assert.ok(h.find("无法保存预览文件。请关闭后重试；未上传或分享任何内容。"));
    assert.equal(h.find("已请求保存当前预览文件。是否分享、发给谁以及何时分享，由你决定。"), undefined);
    h.timers.forEach(fn => fn()); assert.equal(h.revoked.length, failure === "click" ? 1 : 0);
    assert.equal(h.nodes.some(node => node.textContent.includes("private raw error")), false);
  });
}
test("focus returns only to connected opener in the same current context", () => {
  for (const valid of [true, false]) {
    const h = setup(); let focused = 0, current = true;
    h.document.activeElement = { isConnected: true, focus() { focused++; } };
    h.api.open({ taskId: "task", isCurrent: () => current }); current = valid; h.api.invalidate();
    assert.equal(focused, valid ? 1 : 0);
  }
});

test("classic browser-card target binds to the opening selection even when its task differs", async () => {
  const app = fs.readFileSync(new URL("../app.js", import.meta.url), "utf8");
  const start = app.indexOf("async function exportTaskArtifact(");
  const end = app.indexOf("\nconst exportSelectedTask", start);
  let opened;
  const context = { selectedTaskId: "selected-local-note", apiUrl: path => path,
    LearnNoteDiagnosticExport: { open(options) { opened = options; } } };
  vm.createContext(context); vm.runInContext(app.slice(start, end), context);
  await context.exportTaskArtifact("browser-card-task", "diagnostics");
  assert.equal(opened.taskId, "browser-card-task"); assert.equal(opened.isCurrent(), true);
  context.selectedTaskId = "another-task"; assert.equal(opened.isCurrent(), false);
});

test("actual desk same-task settings route invalidates a report without changing selection", async () => {
  const desk = fs.readFileSync(new URL("../desk.js", import.meta.url), "utf8");
  const start = desk.indexOf("async function applyRoute(");
  const end = desk.indexOf('window.addEventListener("hashchange"', start);
  let invalidations = 0, settings = 0;
  const context = { state: { routeEpoch: 0, epoch: 1, selected: { id: "task", kind: "task" }, items: [] },
    readRoute: () => ({ view: "settings" }), guard: () => true,
    location: { hash: "#settings", search: "" },
    $: id => id === "settingsDialog" ? { open: false } : { value: "", click() { settings++; } },
    LearnNoteDiagnosticExport: { invalidate() { invalidations++; } } };
  const draft = desk.slice(desk.indexOf("function navigationDraftSnapshot()"), desk.indexOf("let editionRequest ="));
  vm.createContext(context); vm.runInContext(draft + desk.slice(start, end), context); await context.applyRoute();
  assert.equal(invalidations, 1); assert.equal(settings, 1); assert.equal(context.state.selected.id, "task");
});
