import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { File } from "node:buffer";

const sources = ["material-batch.js", "desk-material-batch.js"].map(name => readFileSync(new URL(`../${name}`, import.meta.url), "utf8"));
const defer = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const tick = () => new Promise(resolve => setImmediate(resolve));
const file = (name, text = "Synthetic text") => new File([text], name, { type: name.endsWith("mp4") ? "video/mp4" : "text/plain" });
function harness(newline = "\n") {
  const elements = new Map(), events = new Map(), calls = [], pending = [], opened = [];
  const h = { elements, calls, pending, opened, refreshes: 0, importWait: null, previewWait: null, refreshWait: null };
  class Element {
    constructor() { this.listeners = new Map(); this.dataset = {}; this.value = ""; this.disabled = false; this.open = true; this.textContent = ""; this.files = []; this.classList = { toggle() {}, remove() {} }; }
    addEventListener(name, callback) { const list = this.listeners.get(name) || []; list.push(callback); this.listeners.set(name, list); }
    async event(name, detail = {}) { for (const fn of this.listeners.get(name) || []) await fn(detail); }
    close() { this.open = false; this.event("beforetoggle", { newState: "closed" }); pending.push(() => this.event("close")); }
    querySelectorAll() { return []; }
  }
  const $ = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  const state = { input: "file", epoch: 1, health: { default_llm_model: "synthetic-model", default_llm_base_url: "https://example.invalid" } };
  h.state = state; h.$ = $;
  const context = vm.createContext({
    FormData, AbortController, URL, setTimeout, clearTimeout,
    esc: text => String(text).replaceAll("<", "&lt;").replaceAll(">", "&gt;"), timestamp: seconds => `${seconds}s`,
    document: { getElementById: $, querySelectorAll: () => [], createElement: () => ({ load() {}, removeAttribute() {}, set src(value) { queueMicrotask(() => this.onerror?.()); } }) },
    window: { addEventListener: (name, fn) => events.set(name, fn) },
    api: async (path, request) => {
      const selected = request.body.get("file"); calls.push({ path, request, file: selected });
      if (path.endsWith("/preflight-local")) return { duration: 12.5, staging_token: "a".repeat(32) };
      if (path.endsWith("/preview")) {
        if (h.previewWait?.name === selected.name) await h.previewWait.work.promise;
        return { filename: selected.name, byte_size: selected.size, estimated_storage_bytes: 42 };
      }
      if (h.importWait) await h.importWait.promise;
      return path.endsWith("/from-local") ? { task_id: "video-result", task: { id: "video-result" } }
        : { material: { material_id: `material-${selected.name}`, title: selected.name } };
    },
  });
  for (const source of sources) vm.runInContext(source.replace(/\r?\n/g, newline).replace(/^import .*;\r?\n/gm, "").replaceAll("export ", ""), context);
  h.videoOptions = { content_mode: "subtitles", visual_understanding: false, transcriber: "faster-whisper" };
  h.view = context.installMaterialBatch({ state, options: () => h.videoOptions, updatePresentation: () => h.view.render(),
    openResult: async item => opened.push(item), refresh: async () => { h.refreshes++; if (h.refreshWait) await h.refreshWait.promise; },
  });
  h.select = async files => { $("file").files = files; await $("file").event("change"); };
  h.close = () => $("createDialog").close();
  h.escape = () => { $("createDialog").event("cancel"); $("createDialog").open = false; };
  h.navigate = () => { state.epoch++; events.get("learnnote:navigation")(); };
  h.reopen = () => { $("createDialog").open = true; h.view.open(); };
  h.flushClose = async () => { for (const work of pending.splice(0)) await work(); };
  return h;
}
for (const newline of ["\n", "\r\n"]) {
  const h = harness(newline); await h.select([file("single.txt")]);
  assert.equal(h.$("createSubmit").disabled, false);
  assert.match(h.$("materialBatchItems").innerHTML, /data-status="ready"/);
  await h.view.submit();
  assert.equal(h.opened.length, 1); assert.equal(h.refreshes, 1);
  assert.equal(h.$("createDialog").open, false);
  assert.equal(h.view.items.length, 0, "Single-file completion clears the old selection");
}
{
  const h = harness(); await h.select([file("<file>.txt"), file("video.mp4")]);
  assert.match(h.$("materialBatchItems").innerHTML, /&lt;file&gt;/);
  assert.match(h.$("materialBatchItems").innerHTML, /时长 12.5s.*本机校验并暂存/);
  assert.match(h.$("materialBatchRoute").textContent, /仅提取内嵌字幕/);
  h.importWait = defer(); const work = h.view.submit(); await tick();
  assert.equal(h.$("materialBatchCancel").hidden, false);
  assert.equal(h.$("file").disabled, true);
  assert.equal(h.$("materialEncoding").disabled, true);
  assert.equal(h.$("contentModeChoices").disabled, true);
  await h.view.submit(); assert.equal(h.calls.filter(call => !call.path.endsWith("/preview") && !call.path.endsWith("/preflight-local")).length, 1);
  h.$("materialBatchCancel").onclick(); h.importWait.resolve(); await work;
  assert.equal(h.opened.length, 0);
  assert.equal(h.view.items[0].status, "success"); assert.equal(h.view.items[1].status, "ready");
  assert.equal(h.$("createDialog").open, true);
  h.importWait = null; h.videoOptions = { content_mode: "visual", visual_understanding: true };
  await h.view.submit();
  assert.equal(JSON.parse(h.calls.at(-1).request.body.get("options")).content_mode, "subtitles");
  assert.equal(h.opened.length, 0, "Multi-file completion leaves results visible");
}
for (const leave of ["close", "escape", "navigate"]) {
  const h = harness(); await h.select([file("first.txt"), file("second.txt")]);
  h.importWait = defer(); const work = h.view.submit(); await tick();
  h[leave](); h.reopen(); h.$("createStatus").textContent = "Newer visit";
  await h.flushClose();
  assert.equal(h.$("file").disabled, true, "Reopening cannot bypass an in-flight import");
  h.importWait.resolve(); await work;
  assert.equal(h.calls.filter(call => !call.path.endsWith("/preview") && !call.path.endsWith("/preflight-local")).length, 1, `${leave} stops unsent items`);
  assert.equal(h.$("createStatus").textContent, "Newer visit");
  assert.equal(h.opened.length, 0); assert.equal(h.refreshes, 0, `${leave} cannot trigger a late reader refresh`);
  assert.equal(h.$("createDialog").open, true, "An old completion must not close the reopened dialog");
  await h.select([file("replacement.txt")]); assert.equal(h.view.items[0].file.name, "replacement.txt");
}
{
  const h = harness(); h.previewWait = { name: "old.txt", work: defer() };
  const first = h.select([file("old.txt")]); await tick();
  await h.select([file("new.txt")]); const view = h.$("materialBatchItems").innerHTML;
  h.previewWait.work.resolve(); await first;
  assert.equal(h.$("materialBatchItems").innerHTML, view);
  assert.equal(h.view.items[0].file.name, "new.txt");
}
{
  const h = harness(); await h.select([file("single.txt")]); h.refreshWait = defer();
  const work = h.view.submit(); await tick();
  assert.equal(h.refreshes, 1); h.navigate(); h.refreshWait.resolve(); await work;
  assert.equal(h.opened.length, 0, "Navigation during refresh blocks a late automatic open");
}
{
  const h = harness(); await h.select([file("single.txt")]); const periodic = defer(); h.state.refreshPromise = periodic.promise;
  const work = h.view.submit(); await tick(); assert.equal(h.refreshes, 0);
  h.close(); periodic.resolve(); await work; assert.equal(h.refreshes, 0); assert.equal(h.opened.length, 0);
}
{
  const h = harness(); let prevented = false;
  await h.$("fileDrop").event("drop", { preventDefault() { prevented = true; }, stopPropagation() {}, dataTransfer: { items: [], files: [file("dropped.txt"), file("another.md")] } });
  await tick(); assert.equal(prevented, true); assert.equal(h.view.items.length, 2);
  assert.equal(h.view.items.every(item => item.status === "ready"), true);
  const count = h.calls.length;
  await h.$("fileDrop").event("drop", { preventDefault() {}, stopPropagation() {}, dataTransfer: { items: [{ webkitGetAsEntry: () => ({ isDirectory: true }) }], files: [] } });
  assert.equal(h.calls.length, count); assert.match(h.$("createStatus").textContent, /文件夹/);
}
{
  const h = harness(); await h.select([file("video.mp4"), file("document.txt")]);
  h.videoOptions = { content_mode: "visual", visual_understanding: true, llm_base_url: "https://new-provider.invalid", llm_model: "changed-model" };
  await h.view.submit();
  assert.equal(h.calls.filter(call => !call.path.endsWith("/preview") && !call.path.endsWith("/preflight-local")).length, 0, "A silently changed processing route needs another explicit click after showing the new route");
  assert.match(h.$("createStatus").textContent, /设置已变化/);
  assert.match(h.$("materialBatchRoute").textContent, /new-provider.invalid/);
  await h.view.submit(); assert.equal(h.calls.filter(call => !call.path.endsWith("/preview") && !call.path.endsWith("/preflight-local")).length, 2);
  h.state.input = "url"; h.view.render();
  assert.equal(h.$("contentModeChoices").disabled, false, "A retained batch must not lock a later URL workflow");
}
console.log("Batch dialog preserves selection, current route, single-file opening, cancellation and LF/CRLF stale-dialog/navigation guards");
