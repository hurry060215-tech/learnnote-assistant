import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(new URL("../desk-material-encoding.js", import.meta.url), "utf8");
const tools = readFileSync(new URL("../desk-tools.js", import.meta.url), "utf8");
assert.match(tools, /"material-encoding": materialEncoding/);
assert.match(tools, /if \(canRedecodeMaterial\(s\)\)/);
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const fixture = { kind: "material", id: "local/text", material_id: "local/text", title: "<Local lesson>",
  filename: "lesson.txt", source_type: "text", updated_at: "original-version", metadata: { encoding: "big5", decoding_hint: "big5" } };
const updated = () => ({ material: { ...fixture, updated_at: "new-version", metadata: { encoding: "gb18030" } } });

function harness() {
  const nodes = new Map(), calls = [], posts = [], gets = [], confirmations = [], windowEvents = new Map();
  let generation = 0, refreshes = 0;
  class Element {
    constructor() { this.listeners = new Map(); this.disabled = false; this.value = "utf-8"; this.textContent = ""; }
    set innerHTML(html) { this.html = html; for (const [, id] of html.matchAll(/id="([^"]+)"/g)) nodes.set(id, new Element()); }
    addEventListener(name, fn) { this.listeners.set(name, fn); }
    close() { this.open = false; }
  }
  const dialog = new Element();
  const state = { selected: structuredClone(fixture), epoch: 1 };
  const $ = id => nodes.get(id);
  const h = { state, dialog, calls, posts, gets, confirmations, $, confirm: true,
    refreshError: null, refreshPending: null, get refreshes() { return refreshes; } };
  const context = vm.createContext({
    document: { getElementById: $ },
    window: { addEventListener: (name, fn) => windowEvents.set(name, fn) },
    confirm: text => { confirmations.push(text); return h.confirm; },
    esc: text => String(text).replaceAll("<", "&lt;").replaceAll(">", "&gt;"),
    api: async (path, options) => {
      calls.push({ path, options });
      if (options?.method === "POST") { const work = deferred(); posts.push(work); return work.promise; }
      if (h.deferGet) { const work = deferred(); gets.push(work); return work.promise; }
      return { material: structuredClone(fixture) };
    },
  });
  vm.runInContext(source.replace(/^import .*;\n/, "").replaceAll("export function", "function"), context);
  const show = () => {
    generation++; dialog.open = true;
    nodes.set("toolBody", new Element()); nodes.set("toolStatus", new Element());
    return generation;
  };
  h.open = context.installMaterialEncoding({ state, dialog, show, generation: () => generation,
    status: text => { $("toolStatus").textContent = text; },
    refresh: async () => { refreshes++; if (h.refreshPending) await h.refreshPending.promise; if (h.refreshError) throw h.refreshError; },
  });
  h.canRedecode = context.canRedecodeMaterial;
  h.submit = () => $("materialEncodingForm").listeners.get("submit")({ preventDefault() {}, stopPropagation() {} });
  h.close = () => { generation++; dialog.close(); };
  h.escape = () => { dialog.listeners.get("cancel")(); dialog.close(); };
  h.navigate = (same = false) => {
    windowEvents.get("learnnote:navigation")(); state.epoch++;
    state.selected = same ? structuredClone(fixture) : { kind: "task", id: "other-video" };
  };
  h.home = () => { state.selected = null; state.epoch++; windowEvents.get("learnnote:navigation")(); };
  h.otherTool = () => { show(); $("toolStatus").textContent = "Newer tool"; };
  return h;
}

{
  const h = harness();
  for (const filename of ["a.txt", "a.md", "a.markdown", "a.HTML", "a.htm"]) assert(h.canRedecode({ ...fixture, filename }));
  for (const change of [{ kind: "task" }, { linked_task_id: "task" }, { source_type: "pdf" }, { filename: "scan.pdf" }, { filename: "video.mp4" }])
    assert.equal(h.canRedecode({ ...fixture, ...change }), false);
  await h.open();
  assert.match(h.$("toolBody").html, /&lt;Local lesson&gt;/);
  assert.match(h.$("toolBody").html, /原始字节保留在本机/);
  assert.match(h.$("materialCurrentEncoding").textContent, /big5/);
  assert.equal(h.$("materialRedecodeEncoding").value, "big5");
  h.confirm = false; await h.submit(); assert.equal(h.posts.length, 0, "Declining confirmation never sends a request");
  h.confirm = true; h.$("materialRedecodeEncoding").value = "gb18030";
  const work = h.submit(); await h.submit();
  assert.equal(h.posts.length, 1, "Repeated submit is rejected while pending");
  assert.equal(h.$("materialRedecodeSubmit").disabled, true);
  assert.equal(h.$("materialRedecodeEncoding").disabled, true);
  assert.equal(h.calls.at(-1).path, "/api/library/materials/local%2Ftext/redecode");
  assert.deepEqual(JSON.parse(h.calls.at(-1).options.body), { encoding: "gb18030", expected_updated_at: "original-version" });
  h.posts[0].resolve(updated()); await work;
  assert.equal(h.refreshes, 1);
  assert.match(h.$("materialCurrentEncoding").textContent, /gb18030/);
  assert.match(h.$("toolStatus").textContent, /已重新解码/);
  assert.equal(h.$("materialRedecodeSubmit").disabled, false);
  const again = h.submit();
  assert.equal(JSON.parse(h.calls.at(-1).options.body).expected_updated_at, "new-version");
  h.posts[1].resolve(updated()); await again;
}

for (const leave of ["close", "escape", "navigate", "home", "same-source navigation", "otherTool"]) {
  for (const reject of [false, true]) {
    const h = harness(); await h.open();
    const work = h.submit();
    if (leave === "same-source navigation") h.navigate(true); else h[leave]();
    if (["navigate", "home", "same-source navigation"].includes(leave)) assert.equal(h.dialog.open, false);
    const status = h.$("toolStatus").textContent, selected = h.state.selected, open = h.dialog.open;
    if (reject) h.posts[0].reject(new Error("Stale error")); else h.posts[0].resolve(updated());
    await work;
    assert.equal(h.refreshes, 0, `${leave}: a late reply cannot reload any reader`);
    assert.equal(h.state.selected, selected);
    assert.equal(h.dialog.open, open, `${leave}: a late reply cannot reopen the dialog`);
    assert.equal(h.$("toolStatus").textContent, status, `${leave}: a late reply cannot replace status`);
  }
}

{
  const h = harness(); await h.open(); const work = h.submit(); h.close(); await h.open();
  assert.equal(h.$("materialRedecodeSubmit").disabled, true);
  await h.submit(); assert.equal(h.posts.length, 1, "Reopening cannot submit a duplicate request");
  h.posts[0].resolve(updated()); await work;
  assert.equal(h.refreshes, 0, "The previous visit cannot update a reopened panel");
  h.close(); await h.open(); assert.equal(h.$("materialRedecodeSubmit").disabled, false);
}

for (const reject of [false, true]) {
  const h = harness(); h.deferGet = true; const work = h.open(); h.navigate();
  if (reject) h.gets[0].reject(new Error("Stale load error")); else h.gets[0].resolve({ material: fixture });
  await work;
  assert.equal(h.$("materialEncodingForm"), undefined, "A delayed load cannot render after navigation");
  assert.equal(h.dialog.open, false);
}

{
  const h = harness(); await h.open(); const work = h.submit();
  h.posts[0].reject(new Error("资料已被另一项操作修改，未覆盖当前版本。")); await work;
  assert.match(h.$("toolStatus").textContent, /未覆盖当前版本/);
  assert.match(h.$("materialCurrentEncoding").textContent, /big5/);
  assert.equal(h.refreshes, 0); assert.equal(h.$("materialRedecodeSubmit").disabled, false);
}
{
  const h = harness(); h.refreshError = new Error("Offline"); await h.open(); const work = h.submit();
  h.posts[0].resolve(updated()); await work;
  assert.match(h.$("toolStatus").textContent, /重解码已保存，但阅读页刷新失败/);
}
{
  const h = harness(); h.refreshPending = deferred(); await h.open(); const work = h.submit();
  h.posts[0].resolve(updated()); await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.refreshes, 1); h.otherTool(); h.refreshPending.resolve(); await work;
  assert.equal(h.$("toolStatus").textContent, "Newer tool", "Navigation during refresh also rejects late status");
}
{
  const h = harness(), periodic = deferred(); h.state.refreshPromise = periodic.promise;
  await h.open(); const work = h.submit(); h.posts[0].resolve(updated());
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.refreshes, 0, "An old periodic refresh must finish before reloading the committed version");
  periodic.resolve(); await work; assert.equal(h.refreshes, 1);
}
console.log("Default reader encoding actions preserve source identity across confirmation, failures, repeats, dismissal and newer navigation");
