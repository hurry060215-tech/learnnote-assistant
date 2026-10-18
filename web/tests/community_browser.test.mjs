import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const code = readFileSync(new URL("../community-browser.js", import.meta.url), "utf8");
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const item = id => ({ item_id: String(id), text: "<script>Literal opinion</script>", timestamp_seconds: null, kind: "comment" });
const page = (offset = 0, total = 501, overrides = {}) => ({ task_id: "task/a", items: Array.from({ length: Math.min(500, total - offset) }, (_, i) => item(i + offset)),
  enabled: true, returned_count: Math.min(500, total - offset), total_count: total, offset, has_more: offset + 500 < total,
  next_cursor: offset + 500 < total ? "next" : null, previous_cursor: offset ? "previous" : null, groups_scope: "current_page_only", ...overrides });
function harness(source = code) {
  const nodes = new Map(), events = new Map(), calls = [], mounts = [];
  let generation = 0, invalidations = 0, heldModel = null;
  class Element {
    constructor(id) { this.id = id; this.dataset = {}; this.style = {}; this.children = []; this.listeners = new Map(); this.textContent = ""; nodes.set(id, this); }
    set innerHTML(value) {
      this.html = value; this.children = value ? [{}] : [];
      for (const match of value.matchAll(/id="([^"]+)"/g)) new Element(match[1]);
    }
    get innerHTML() { return this.html || ""; }
    replaceChildren() { this.innerHTML = ""; }
    querySelector(selector) { return nodes.get(selector.slice(1)); }
    addEventListener(event, fn) { const list = this.listeners.get(event) || []; list.push(fn); this.listeners.set(event, list); }
    dispatch(event) { return Promise.all((this.listeners.get(event) || []).map(fn => fn())); }
    focus() { this.focused = true; }
    scrollIntoView(options) { this.scrolled = options.block; }
    close() { this.open = false; return this.dispatch("close"); }
  }
  const root = new Element("toolBody"), dialog = new Element("dialog");
  const state = { epoch: 1, selected: { id: "task/a", kind: "task", source_identity: { id: "first" }, control_generation: "old" } };
  const context = vm.createContext({ URLSearchParams, AbortController,
    esc: value => String(value).replaceAll("<", "&lt;").replaceAll(">", "&gt;"),
    document: { getElementById: id => nodes.get(id) },
    window: { addEventListener(event, fn) { events.set(event, fn); } } });
  vm.runInContext(source.replace(/^import .*;\r?\n/gm, "").replace("export function", "function"), context);
  let controller;
  controller = context.installCommunityBrowser({ state, dialog, generation: () => generation,
    show() { controller?.invalidate(); generation++; dialog.open = true; return generation; },
    api(path, options) { const response = deferred(); calls.push({ path, options, ...response }); return response.promise; },
    question: { invalidate() { invalidations++; }, async mount(root, source, page) { mounts.push({ root, source, page }); if (heldModel) await heldModel.promise; } } });
  return { root, dialog, state, calls, mounts, nodes, controller, invalidations: () => invalidations,
    holdModel: value => { heldModel = value; }, $: id => nodes.get(id), open: () => controller.open(), event: name => events.get(name)(),
    async initial(value = page()) { const work = controller.open(); calls.at(-1).resolve(value); await work; } };
}

test("bounded pages replace rows and QA scope; keyboard targets, counts, literal text and draft survive", async () => {
  for (const newline of ["\n", "\r\n"]) {
    const h = harness(code.replace(/\r?\n/g, newline)); await h.initial();
    assert.match(h.calls[0].path, /task%2Fa\/community-context\/page\?limit=500/);
    assert.equal(h.mounts[0].page.items.length, 500);
    assert.match(h.$("communityPageStatus").textContent, /1–500.*501/);
    assert.match(h.$("communityRows").innerHTML, /&lt;script&gt;/);
    assert.equal(h.$("communityPrevious").disabled, true);
    h.$("communityText").value = "Unsaved manual draft";
    const before = h.invalidations(), work = h.$("communityNext").dispatch("click");
    assert.equal(h.$("communityRows").innerHTML, "");
    assert(h.invalidations() > before); assert(h.$("communityNext").disabled);
    h.calls.at(-1).resolve(page(500)); await work;
    assert.equal(h.mounts.at(-1).page.items.length, 1);
    assert.match(h.$("communityPageStatus").textContent, /501–501.*501/);
    assert.equal(h.$("communityText").value, "Unsaved manual draft");
    assert(h.$("communityPageStatus").focused); assert.equal(h.$("communityPageStatus").scrolled, "center"); assert.equal(h.$("communityNext").disabled, true);
    assert.equal(h.$("communityPrevious").style.minHeight, "44px");
    const previous = h.$("communityPrevious").dispatch("click");
    assert.match(h.calls.at(-1).path, /cursor=previous/);
    h.calls.at(-1).resolve(page()); await previous;
    assert.equal(h.mounts.at(-1).page.items.length, 500);
  }
});

test("changed data fails closed until explicit refresh, with no automatic read or retry", async () => {
  const h = harness(); await h.initial();
  const work = h.$("communityNext").dispatch("click"); h.calls.at(-1).reject(new Error("观点已变化")); await work;
  assert.equal(h.calls.length, 2); assert.equal(h.mounts.length, 1);
  assert.equal(h.$("communityRows").innerHTML, ""); assert.match(h.$("communityPageStatus").textContent, /刷新列表/);
  assert(h.$("communityNext").disabled); assert(!h.$("communityRefresh").disabled);
  const refresh = h.$("communityRefresh").dispatch("click"); h.calls.at(-1).resolve(page(0, 502)); await refresh;
  assert.match(h.calls.at(-1).path, /cursor=$/); assert.match(h.$("communityPageStatus").textContent, /502/);
});

test("delayed first and later pages cannot restore after close, cancel, navigation, source changes or revocation", async () => {
  for (const initial of [true, false]) for (const change of ["close", "cancel", "navigate", "source", "task", "revoke"]) {
    const h = harness(); let work;
    if (initial) work = h.open(); else { await h.initial(); work = h.$("communityNext").dispatch("click"); }
    const request = h.calls.at(-1), before = h.mounts.length;
    if (change === "close") await h.dialog.close();
    if (change === "cancel") await h.dialog.dispatch("cancel");
    if (change === "navigate") { h.state.epoch++; h.state.selected = null; h.event("learnnote:navigation"); }
    if (change === "source") { h.state.selected.control_generation = "new"; h.event("learnnote:metadata"); }
    if (change === "task") { h.state.selected.id = "other"; h.event("learnnote:metadata"); }
    if (change === "revoke") h.controller.invalidate();
    assert.equal(request.options.signal.aborted, true);
    request.resolve(initial ? page() : page(500)); await work;
    assert.equal(h.mounts.length, before, `${initial}/${change}`);
    assert.equal(h.$("communityRows").innerHTML, "");
  }
});

test("malformed, cross-task or oversized responses never expose rows to question picker", async () => {
  for (const result of [page(0, 0, { task_id: "other" }), page(0, 501, { returned_count: 501 }), page(0, 501, { groups_scope: "all" }),
    page(0, 501, { items: Array.from({ length: 501 }, (_, i) => item(i)), returned_count: 501 })]) {
    const h = harness(); await h.initial(result); assert.equal(h.mounts.length, 0); assert.equal(h.$("communityRows").innerHTML, "");
    assert.match(h.$("communityPageStatus").textContent, /刷新列表/);
  }
});

test("empty and disabled pages retain truthful count and exact enabled state", async () => {
  for (const result of [page(0, 0), page(0, 1, { enabled: false })]) {
    const h = harness(); await h.initial(result); assert.equal(h.mounts[0].page.enabled, result.enabled);
    assert.equal(h.$("communityControls").dataset.enabled, String(result.enabled));
    assert(h.$("communityNext").disabled); assert(h.$("communityPrevious").disabled);
  }
});


test("mutation rejection leaves accepted rows and working explicit refresh; success after close cannot reopen", async () => {
  for (const action of ["delete", "clear", "toggle", "import"]) {
    const h = harness(); await h.initial(); const rows = h.$("communityRows").innerHTML;
    h.controller.beginMutation();
    h.controller.mutationFailed(`Synthetic ${action} unavailable`);
    assert.match(h.$("communityPageStatus").textContent, new RegExp(`Synthetic ${action} unavailable.*刷新列表`));
    assert(h.$("communityPageStatus").focused); assert.equal(h.$("communityPageStatus").scrolled, "center");
    assert.equal(h.$("communityRows").innerHTML, rows, action);
    assert.equal(h.$("communityQuestionSlot").innerHTML, "");
    assert(!h.$("communityRefresh").disabled); assert(h.$("communityNext").disabled);
    const work = h.$("communityRefresh").dispatch("click"); h.calls.at(-1).resolve(page()); await work;
    assert.equal(h.mounts.length, 2); assert(!h.$("communityNext").disabled);
    h.controller.beginMutation(); await h.dialog.close(); await h.controller.refresh();
    assert.equal(h.calls.length, 2); assert.equal(h.dialog.open, false);
    const message = h.$("communityPageStatus").textContent;
    h.controller.mutationFailed("Obsolete mutation error"); assert.equal(h.$("communityPageStatus").textContent, message);
  }
});

test("held model-status read cannot lock paging after accepted rows arrive", async () => {
  const h = harness(), model = deferred(); h.holdModel(model);
  const first = h.open(); h.calls[0].resolve(page()); await new Promise(setImmediate);
  assert.equal(h.mounts.length, 1); assert(!h.$("communityNext").disabled);
  const next = h.$("communityNext").dispatch("click"); h.calls[1].resolve(page(500)); await new Promise(setImmediate);
  assert.equal(h.mounts.length, 2); assert.match(h.$("communityPageStatus").textContent, /501–501/);
  model.resolve(); await first; await next;
  assert.match(h.$("communityPageStatus").textContent, /501–501/);
});


test("mutation error feedback never crosses a changed source revision", async () => {
  const h = harness(); await h.initial(); h.controller.beginMutation();
  const message = h.$("communityPageStatus").textContent;
  h.state.selected.control_generation = "new";
  h.controller.mutationFailed("Obsolete mutation error");
  assert.equal(h.$("communityPageStatus").textContent, message);
});
