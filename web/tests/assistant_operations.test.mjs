import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

// Run the real controller and reading adapter with synthetic, local fixtures.
// The DOM implements the selectors/events used by the controller, including
// disabled buttons and the difference between textContent and parsed HTML.
const controller = readFileSync(new URL("../assistant-operations.js", import.meta.url), "utf8")
  .replace(/^import .*;\r?\n/, "").replace("export function", "function");
const readingSource = readFileSync(new URL("../reading-settings.js", import.meta.url), "utf8");
const { createReadingSettingsAdapter, READING_STORAGE_KEY } = await import(`data:text/javascript;base64,${Buffer.from(readingSource).toString("base64")}`);
const endpoint = "/api/assistant/operations";
const plain = value => JSON.parse(JSON.stringify(value));
const flush = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
};

function createHarness({ handleRequest, locks, selected = true, settings = {}, settingsDirty = () => false, confirm = () => true } = {}) {
  const calls = [], notices = [], opened = [], operations = new Map(), htmlWrites = [];
  const classes = new Set(), styles = {}, readingCalls = [], stored = new Map(), confirmations = [];
  if (Object.keys(settings).length) stored.set(READING_STORAGE_KEY, JSON.stringify(settings));
  let sequence = 0, revision = 0, writes = 0;
  const storage = {
    getItem(key) { if (this.failRead) throw Error("synthetic read failure"); return stored.get(key) ?? null; },
    setItem(key, value) {
      if (this.failWrite) throw Error("synthetic quota failure");
      writes++; stored.set(key, value); this.afterWrite?.();
    },
  };
  class Element {
    constructor(tag) {
      this.tagName = tag.toUpperCase(); this.children = []; this.attributes = new Map();
      this.dataset = {}; this.events = new Map(); this.checked = false;
      this.disabled = false; this.hidden = false; this.open = false; this._text = "";
    }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(""); }
    set textContent(text) { this.children = []; this._text = String(text); }
    get value() {
      if (this.tagName === "SELECT") return this.children.find(child => child.tagName === "OPTION" && child.value === this._value)?.value
        ?? this.children.find(child => child.tagName === "OPTION")?.value ?? "";
      return this._value ?? (this.tagName === "OPTION" ? this.textContent : "");
    }
    set value(value) { this._value = String(value); }
    setAttribute(key, value) {
      this.attributes.set(key, String(value));
      if (["id", "name", "class", "value"].includes(key)) this[key === "class" ? "className" : key] = String(value);
      if (["checked", "disabled", "hidden"].includes(key)) this[key] = true;
      if (key.startsWith("data-")) this.dataset[key.slice(5).replace(/-([a-z])/g, (_, char) => char.toUpperCase())] = String(value);
    }
    hasAttribute(key) {
      if (key.startsWith("data-")) return Object.hasOwn(this.dataset, key.slice(5).replace(/-([a-z])/g, (_, char) => char.toUpperCase()));
      return this.attributes.has(key);
    }
    matches(selector) {
      if (selector.startsWith("#")) return this.id === selector.slice(1);
      const attr = selector.match(/^\[([^=\]]+)(?:=["']?([^\]"']+)["']?)?\]$/);
      if (attr) return attr[2] === undefined ? this.hasAttribute(attr[1]) : String(this[attr[1]] ?? this.attributes.get(attr[1])) === attr[2];
      return this.tagName === selector.toUpperCase();
    }
    querySelectorAll(selector) { return this.children.flatMap(child => [...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]); }
    querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
    append(...children) { for (const child of children) { child.parentElement = this; this.children.push(child); } }
    prepend(child) { child.parentElement = this; this.children.unshift(child); }
    replaceChildren(...children) { this.children = []; this._text = ""; this.append(...children); }
    addEventListener(type, listener) { this.events.set(type, [...(this.events.get(type) || []), listener]); }
    async fire(type, { force = false, ...props } = {}) {
      if (type === "click" && this.disabled && !force) return;
      const event = { target: this, currentTarget: this, preventDefault() {}, ...props };
      await Promise.all([this[`on${type}`], ...(this.events.get(type) || [])].filter(Boolean).map(listener => listener(event)));
    }
    showModal() { this.open = true; }
    close() { if (!this.open) return; this.open = false; return this.fire("close"); }
    getBoundingClientRect() { return { left: 10, right: 100, top: 10, bottom: 100 }; }
    set innerHTML(html) {
      htmlWrites.push(html); this.replaceChildren(); const stack = [this];
      for (const [token] of html.matchAll(/<\/?[^>]+>|[^<]+/g)) {
        if (token.startsWith("</")) { stack.pop(); continue; }
        if (!token.startsWith("<")) { stack.at(-1)._text += token; continue; }
        const tag = token.match(/^<([\w-]+)/)?.[1];
        if (!tag) continue;
        const element = new Element(tag);
        for (const [, key, value = ""] of token.slice(tag.length + 1, -1).matchAll(/([\w-]+)(?:="([^"]*)")?/g)) element.setAttribute(key, value);
        stack.at(-1).append(element);
        if (!["input", "br", "img", "hr"].includes(tag)) stack.push(element);
      }
    }
  }
  const body = new Element("body"), header = new Element("div");
  body.classList = { toggle(key, value) { if (value) classes.add(key); else classes.delete(key); } };
  const note = new Element("textarea"), question = new Element("textarea");
  note.id = "noteText"; question.id = "aiQuestion"; body.append(note, question);
  const document = {
    body, documentElement: { style: { setProperty(key, value) { styles[key] = value; } } },
    createElement: tag => new Element(tag),
    getElementById: id => body.querySelector(`#${id}`) || header.querySelector(`#${id}`),
    querySelector: selector => selector === "#assistantPanel header > div" ? header : body.querySelector(selector),
  };
  const state = {
    selected: selected ? { id: "synthetic-note-1", kind: "task", title: "Synthetic note" } : null,
    revision: "saved-version-1", text: "# Synthetic note\nOriginal paragraph.", editing: false,
    items: [{ id: "synthetic-note-1", kind: "task", title: "Synthetic note" }],
  };
  note.value = state.text;
  const reading = createReadingSettingsAdapter({ storage, document, isDirty: settingsDirty,
    locks: locks ?? { request: async (_name, _options, fn) => fn() },
    newRevision: () => `reading-${++revision}` });
  const adapter = { ...reading };
  for (const method of ["patch", "undo"]) adapter[method] = request => { readingCalls.push({ method, request }); return reading[method](request); };
  let h;
  const api = async (path, options = {}) => {
    const call = { path, method: options.method || "GET", body: options.body ? JSON.parse(options.body) : undefined, signal: options.signal };
    calls.push(call);
    const override = handleRequest?.(call, h);
    if (override !== undefined) return await override;
    if (path === `${endpoint}/prepare`) {
      const { operation_id: id, ...candidate } = call.body;
      const value = { id, ...candidate, status: "prepared", preview: { arguments: candidate.arguments } };
      operations.set(id, value); return value;
    }
    if (path === endpoint) return { operations: [...operations.values()].map(plain) };
    const [, id, action] = path.slice(endpoint.length).split("/");
    const value = operations.get(id);
    if (!value) throw Error(`Unexpected synthetic request: ${path}`);
    if (call.method === "DELETE") { operations.delete(id); return { deleted: true }; }
    if (!action) return plain(value);
    if (action === "cancel") {
      const cancelled = { ...value, status: "cancelled" }; operations.set(id, cancelled); return cancelled;
    }
    if (action === "execute") {
      const result = { ...value, status: "completed", result: value.tool === "read_note" ? { text: "Saved synthetic text" } : { revision: "saved-version-2" } };
      operations.set(id, result); return result;
    }
    if (action === "undo") {
      const result = { ...value, id: call.body.operation_id, status: "completed", undo_of: id };
      operations.set(id, { ...value, undone_by: result.id }); operations.set(result.id, result); return result;
    }
    throw Error(`Unexpected synthetic request: ${path}`);
  };
  const context = vm.createContext({ document, window: { LearnNoteReadingSettings: adapter, confirm(message) { confirmations.push(message); return confirm(message); } }, api, AbortController,
    crypto: { randomUUID: () => `operation-${++sequence}` },
    ctx: { state, options: () => ({ text_model: "synthetic-model" }), notice: message => notices.push(message),
      openItem: async item => { opened.push(plain(item)); } } });
  vm.runInContext(`${controller}\ninstallAssistantOperations(ctx);`, context);
  const dialog = document.getElementById("assistantOperationsDialog");
  h = { calls, operations, notices, opened, htmlWrites, state, note, question, dialog, storage, stored, reading, adapter,
    readingCalls, classes, styles, confirmations, writes: () => writes, $: selector => dialog.querySelector(selector),
    status: () => dialog.querySelector("[data-agent-status]").textContent,
    card: () => dialog.querySelector("[data-agent-card]"),
    button: text => dialog.querySelectorAll("button").find(button => button.textContent === text),
    async open() { await document.getElementById("assistantOperations").fire("click"); await flush(); },
    async preview(tool, args = {}) {
      h.$("[name=tool]").value = tool; await h.$("[name=tool]").fire("change");
      for (const [key, value] of Object.entries(args)) h.$(`[name=${key}]`).value = value;
      await h.$("[data-agent-local]").fire("submit"); await flush();
    },
    async click(selector) { await h.$(selector).fire("click"); await flush(); },
  };
  return h;
}

test("explicit local read previews the saved source and executes only after confirmation", async () => {
  const h = createHarness(); await h.open(); await h.preview("read_note", { start_line: 3, line_count: 12 });
  assert.equal(h.calls.length, 1); assert.equal(h.calls[0].path, `${endpoint}/prepare`);
  assert.deepEqual(h.calls[0].body, { operation_id: "operation-1", tool: "read_note", arguments: { start_line: 3, line_count: 12 }, source: { kind: "task", id: "synthetic-note-1", revision: "saved-version-1" } });
  assert.match(h.card().textContent, /待执行/); assert.match(h.card().textContent, /Synthetic note/);
  await h.click("[data-agent-apply]");
  assert.deepEqual(h.calls[1].body, { confirm: true }); assert.match(h.calls[1].path, /operation-1\/execute$/);
  assert.match(h.card().textContent, /已完成/); assert.match(h.card().textContent, /Saved synthetic text/);
  assert.equal(h.$("[data-agent-undo]"), null); assert.equal(h.opened.length, 0);
});

test("local editing sends exact replacement text and reloads only the completed source", async () => {
  const h = createHarness(); await h.open();
  await h.preview("edit_note", { mode: "replace", old_text: "Original paragraph.", text: "Revised paragraph." });
  assert.deepEqual(h.calls[0].body.arguments, { mode: "replace", old_text: "Original paragraph.", text: "Revised paragraph." });
  assert.equal(h.opened.length, 0); await h.click("[data-agent-apply]");
  assert.deepEqual(h.opened, [h.state.selected]); assert.ok(h.$("[data-agent-undo]"));
});

test("append and title edits omit stale replacement text", async () => {
  for (const mode of ["append", "set_title"]) {
    const h = createHarness(); await h.open(); await h.preview("edit_note", { mode, old_text: "unused", text: "New text" });
    assert.deepEqual(h.calls[0].body.arguments, { mode, old_text: "", text: "New text" });
  }
});

test("export offers an artifact link only after its execution succeeds", async () => {
  for (const format of ["markdown", "docx", "pdf", "html"]) {
    const h = createHarness(); await h.open(); await h.preview("export_note", { format });
    assert.equal(h.card().querySelector("a"), null); assert.deepEqual(h.calls[0].body.arguments, { format });
    await h.click("[data-agent-apply]");
    assert.equal(h.card().querySelector("a").href, `${endpoint}/operation-1/artifact`);
    assert.equal(h.card().querySelector("a").download, ""); assert.equal(h.opened.length, 0);
  }
});

test("reading appearance uses the real local adapter without sending a source or model request", async () => {
  const h = createHarness({ selected: false }); await h.open();
  await h.preview("update_reading", { size: 20, theme: "dark", font: "serif" });
  assert.equal(h.calls.length, 0); assert.equal(h.writes(), 0); assert.match(h.card().textContent, /待执行/);
  await h.click("[data-agent-apply]");
  assert.equal(h.calls.length, 0); assert.equal(h.writes(), 1); assert.equal(h.styles["--reader-size"], "20px");
  assert.equal(h.classes.has("dark"), true); assert.equal(h.reading.read().settings.font, "serif");
  assert.match(h.card().textContent, /已完成/); assert.ok(h.$("[data-agent-undo]"));
});

test("model proposals prepare a structured preview and require a separate execution click", async () => {
  const h = createHarness({ settings: { notify: true, autoOpen: true, privateFixture: "local only" }, handleRequest(call) {
    if (call.path === `${endpoint}/plan`) return { state: "proposed", tool: "edit_note", arguments: { mode: "append", text: "Proposed paragraph" }, source: call.body.source, shared_characters: 0 };
  } });
  h.question.value = "Append a summary"; await h.open();
  assert.equal(h.$("[data-agent-question]").value, "Append a summary"); assert.equal(h.$("[data-agent-share]").checked, false);
  await h.click("[data-agent-plan]");
  assert.deepEqual(h.calls.map(call => call.path), [`${endpoint}/plan`, `${endpoint}/prepare`]);
  const plan = h.calls[0].body;
  assert.equal(plan.question, "Append a summary"); assert.equal(plan.share_source, false);
  assert.deepEqual(plan.options, { text_model: "synthetic-model" });
  assert.deepEqual(Object.keys(plan.reading).sort(), ["accent", "density", "font", "leading", "size", "theme", "weight", "width"]);
  assert.doesNotMatch(JSON.stringify(plan), /local only|Original paragraph|notify|autoOpen/);
  assert.match(h.status(), /0 字/); assert.match(h.card().textContent, /Proposed paragraph/); assert.equal(h.opened.length, 0);
  await h.click("[data-agent-apply]"); assert.match(h.calls.at(-1).path, /\/execute$/); assert.equal(h.opened.length, 1);
});

test("source sharing is explicit for each dialog opening and non-proposals never execute", async () => {
  const h = createHarness({ handleRequest(call) {
    if (call.path === `${endpoint}/plan`) return { state: "answer", answer: "Explain the requested change first." };
  } });
  await h.open(); h.$("[data-agent-question]").value = "Help me"; h.$("[data-agent-share]").checked = true;
  await h.click("[data-agent-plan]"); assert.equal(h.calls[0].body.share_source, true);
  assert.match(h.status(), /未执行操作/); assert.equal(h.$("[data-agent-apply]"), null);
  await h.dialog.close(); await h.open(); assert.equal(h.$("[data-agent-share]").checked, false);
  assert.equal(h.calls.length, 1);
});

test("untrusted proposal previews, source labels, results, notices and errors render as text", async () => {
  const attack = '<img src="x" onerror="globalThis.compromised=true"><script>malicious()</script>';
  const h = createHarness({ handleRequest(call, fixture) {
    if (call.path === `${endpoint}/prepare`) {
      const value = { id: call.body.operation_id, ...call.body, status: "prepared", preview: { diff: attack, notice: attack } };
      fixture.operations.set(value.id, value); return value;
    }
    if (call.path.endsWith("/execute")) return { ...fixture.operations.get("operation-1"), status: "failed", preview: null, result: { text: attack }, error: attack };
  } });
  h.state.items[0].title = attack; await h.open(); await h.preview("edit_note", { text: attack });
  assert.ok(h.card().textContent.includes(attack)); assert.equal(h.card().querySelector("img"), null); assert.equal(h.card().querySelector("script"), null);
  await h.click("[data-agent-apply]");
  assert.ok(h.card().textContent.includes(attack)); assert.equal(h.card().querySelector("img"), null); assert.equal(h.card().querySelector("script"), null);
  assert.ok(h.htmlWrites.every(html => !html.includes(attack))); assert.equal(h.opened.length, 0);
});

for (const change of ["selection", "kind", "revision", "draft"]) {
  test(`${change} changes after preview block execution of the stale source`, async () => {
    const h = createHarness(); await h.open(); await h.preview("edit_note", { text: "replacement" });
    if (change === "selection") h.state.selected = { ...h.state.selected, id: "other-note" };
    if (change === "kind") h.state.selected = { ...h.state.selected, kind: "material" };
    if (change === "revision") h.state.revision = "newer-version";
    if (change === "draft") { h.state.editing = true; h.note.value = "Unsaved work"; }
    await h.click("[data-agent-apply]");
    assert.equal(h.calls.length, 1); assert.equal(h.opened.length, 0); assert.match(h.status(), /未保存|版本已变化/);
  });
}

test("missing saved source and unsaved draft block both local preparation and model planning", async () => {
  for (const unavailable of ["missing", "revision", "draft"]) {
    const h = createHarness({ selected: unavailable !== "missing" });
    if (unavailable === "revision") h.state.revision = "";
    if (unavailable === "draft") { h.state.editing = true; h.note.value = "Uncommitted draft"; }
    await h.open(); await h.preview("edit_note", { text: "change" }); assert.equal(h.calls.length, 0);
    if (unavailable !== "missing") {
      h.$("[data-agent-question]").value = "Rewrite it"; await h.click("[data-agent-plan]"); assert.equal(h.calls.length, 0);
    }
    assert.match(h.status(), /未保存|已保存/);
  }
});

test("a late model proposal cannot prepare against a newly selected source", async () => {
  const pending = deferred(); const h = createHarness({ handleRequest: call => call.path.endsWith("/plan") ? pending.promise : undefined });
  await h.open(); h.$("[data-agent-question]").value = "Rewrite this";
  const work = h.$("[data-agent-plan]").fire("click"), source = h.calls[0].body.source;
  h.state.selected = { ...h.state.selected, id: "new-note" };
  pending.resolve({ state: "proposed", tool: "edit_note", source, arguments: { mode: "append", text: "late" }, shared_characters: 0 });
  await work; assert.equal(h.calls.length, 1); assert.match(h.status(), /来源或版本已变化/); assert.equal(h.$("[data-agent-apply]"), null);
});

test("cancelling a prepared operation never executes it or claims completion", async () => {
  for (const tool of ["edit_note", "update_reading"]) {
    const h = createHarness(); await h.open(); await h.preview(tool, tool === "edit_note" ? { text: "change" } : { size: 20 });
    await h.click("[data-agent-cancel]");
    assert.match(h.card().textContent, /已取消/); assert.doesNotMatch(h.card().textContent, /已完成/);
    assert.equal(h.$("[data-agent-apply]"), null); assert.equal(h.$("[data-agent-undo]"), null);
    assert.equal(h.writes(), 0); assert.equal(h.calls.filter(call => call.path.endsWith("/execute")).length, 0);
  }
});

test("queued reading execution can be cancelled without committing a receipt", async () => {
  const gate = deferred(); const h = createHarness({ locks: { request: async (_name, _options, commit) => { await gate.promise; return commit(); } } });
  await h.open(); await h.preview("update_reading", { size: 20 });
  const work = h.$("[data-agent-apply]").fire("click");
  assert.equal(h.$("[data-agent-cancel]").disabled, false); await h.click("[data-agent-cancel]");
  gate.resolve(); await work;
  assert.equal(h.writes(), 0); assert.equal(h.reading.recentOperations().operations.length, 0);
  assert.match(h.card().textContent, /已取消/); assert.doesNotMatch(h.card().textContent, /已完成/);
});

for (const interruption of ["reopened dialog", "new preview"]) {
  test(`a late cancellation response cannot replace a ${interruption}`, async () => {
    const pending = deferred(); const h = createHarness({ handleRequest: call => call.path.endsWith("/cancel") ? pending.promise : undefined });
    await h.open(); await h.preview("edit_note", { text: "old change" });
    const original = h.operations.get("operation-1"), work = h.$("[data-agent-cancel]").fire("click");
    if (interruption === "reopened dialog") { await h.dialog.close(); await h.open(); }
    else await h.preview("read_note", { start_line: 10, line_count: 5 });
    const visible = h.card().textContent;
    pending.resolve({ ...original, status: "cancelled" }); await work;
    assert.equal(h.card().textContent, visible);
  });
}

test("cancellation racing a committed edit displays the actual completed receipt", async () => {
  const pending = deferred(); const h = createHarness({ handleRequest(call, fixture) {
    if (call.path.endsWith("/execute")) return pending.promise;
    if (call.path.endsWith("/cancel")) return { ...fixture.operations.get("operation-1"), status: "completed", result: { revision: "saved-version-2" } };
  } });
  await h.open(); await h.preview("edit_note", { text: "committed change" });
  const work = h.$("[data-agent-apply]").fire("click"); await h.click("[data-agent-cancel]");
  assert.match(h.card().textContent, /已完成/); assert.doesNotMatch(h.card().textContent, /已取消/);
  pending.resolve({ ...h.operations.get("operation-1"), status: "completed", result: { revision: "saved-version-2" } }); await work;
  assert.equal(h.opened.length, 1);
});

test("duplicate execution clicks send once and a lost response can be recovered from actual history", async () => {
  const pending = deferred(); const h = createHarness({ handleRequest: call => call.path.endsWith("/execute") ? pending.promise : undefined });
  await h.open(); await h.preview("edit_note", { text: "change" });
  const apply = h.$("[data-agent-apply]"), work = apply.fire("click");
  await apply.fire("click", { force: true }); assert.equal(h.calls.filter(call => call.path.endsWith("/execute")).length, 1);
  h.operations.set("operation-1", { ...h.operations.get("operation-1"), status: "completed", result: { revision: "saved-version-2" } });
  pending.reject(Error("Connection lost; check actual status")); await work;
  assert.match(h.status(), /Connection lost/); assert.doesNotMatch(h.card().textContent, /已完成/); assert.equal(h.opened.length, 0);
  await h.button("刷新实际状态").fire("click");
  assert.match(h.card().textContent, /已完成/); assert.ok(h.$("[data-agent-undo]"));
  assert.equal(h.calls.filter(call => call.path.endsWith("/execute")).length, 1);
  await h.click("[data-agent-history]");
  const record = h.$("[data-agent-records]").querySelector("button"); assert.match(record.textContent, /completed/);
  await record.fire("click"); assert.match(h.card().textContent, /已完成/);
});

test("closing and reopening suppresses a late planner response and aborts its request", async () => {
  const pending = deferred(); const h = createHarness({ handleRequest: call => call.path.endsWith("/plan") ? pending.promise : undefined });
  await h.open(); h.$("[data-agent-question]").value = "Prepare a change";
  const work = h.$("[data-agent-plan]").fire("click"), call = h.calls[0];
  await h.dialog.close(); assert.equal(call.signal.aborted, true); await h.open();
  pending.resolve({ state: "proposed", tool: "edit_note", source: call.body.source, arguments: { mode: "append", text: "late" }, shared_characters: 0 });
  await work;
  assert.equal(h.calls.length, 1); assert.equal(h.card().textContent, ""); assert.equal(h.$("[data-agent-apply]"), null);
});

for (const interruption of ["selection", "kind", "draft", "close"]) {
  test(`${interruption} during edit execution preserves the newer view or draft`, async () => {
    const pending = deferred(); const h = createHarness({ handleRequest: call => call.path.endsWith("/execute") ? pending.promise : undefined });
    await h.open(); await h.preview("edit_note", { text: "change" });
    const value = h.operations.get("operation-1"), work = h.$("[data-agent-apply]").fire("click");
    if (interruption === "selection") h.state.selected = { ...h.state.selected, id: "other-note" };
    if (interruption === "kind") h.state.selected = { ...h.state.selected, kind: "material" };
    if (interruption === "draft") { h.state.editing = true; h.note.value = "New unsaved work"; }
    if (interruption === "close") { await h.dialog.close(); await h.open(); }
    pending.resolve({ ...value, status: "completed", result: { revision: "saved-version-2" } }); await work;
    assert.equal(h.opened.length, 0);
    if (interruption === "draft") assert.equal(h.note.value, "New unsaved work");
    if (interruption === "close") { assert.equal(h.card().textContent, ""); assert.ok(h.notices.some(text => text.includes("记录"))); }
  });
}

test("failed or conflicting server results expose no undo or download success", async () => {
  for (const status of ["failed", "conflict", "cancelled"]) {
    const h = createHarness({ handleRequest(call, fixture) {
      if (call.path.endsWith("/execute")) return { ...fixture.operations.get("operation-1"), status, error: "Synthetic operation was not committed" };
    } });
    await h.open(); await h.preview("export_note", { format: "pdf" }); await h.click("[data-agent-apply]");
    assert.doesNotMatch(h.card().textContent, /已完成/); assert.match(h.card().textContent, /not committed/);
    assert.equal(h.card().querySelector("a"), null); assert.equal(h.$("[data-agent-undo]"), null); assert.equal(h.opened.length, 0);
  }
});

test("reading failures never claim success and an uncertain commit is recoverable", async () => {
  const h = createHarness(); await h.open(); await h.preview("update_reading", { size: 20 });
  h.storage.afterWrite = () => { h.storage.failRead = true; }; await h.click("[data-agent-apply]");
  assert.equal(h.writes(), 1); assert.match(h.status(), /无法验证/); assert.doesNotMatch(h.card().textContent, /已完成/);
  assert.equal(h.$("[data-agent-undo]"), null);
  h.storage.failRead = false; await h.button("刷新实际状态").fire("click");
  assert.match(h.card().textContent, /已完成/); assert.equal(h.reading.read().settings.size, 20); assert.equal(h.writes(), 1);
});

test("unreadable reading history is reported instead of claiming there are no records", async () => {
  const h = createHarness(); await h.open(); await h.preview("update_reading", { size: 20 }); await h.click("[data-agent-apply]");
  h.storage.failRead = true; await h.click("[data-agent-history]");
  assert.doesNotMatch(h.$("[data-agent-records]").textContent, /还没有执行记录/);
  assert.match(h.status() + h.$("[data-agent-records]").textContent, /无法读取|不可用|未能读取/);
});

test("closing during note undo suppresses the old result and source reload", async () => {
  const pending = deferred(); const h = createHarness({ handleRequest: call => call.path.endsWith("/undo") ? pending.promise : undefined });
  await h.open(); await h.preview("edit_note", { text: "change" }); await h.click("[data-agent-apply]");
  const work = h.$("[data-agent-undo]").fire("click"), request = h.calls.at(-1);
  await h.dialog.close(); await h.open();
  pending.resolve({ ...h.operations.get("operation-1"), id: request.body.operation_id, undo_of: "operation-1", status: "completed" }); await work;
  assert.equal(h.opened.length, 1); assert.equal(h.card().textContent, "");
});

test("stale appearance previews and unsaved appearance drafts fail without writes", async () => {
  for (const failure of ["revision", "draft", "quota"]) {
    let dirty = false; const h = createHarness({ settingsDirty: () => dirty });
    await h.open(); await h.preview("update_reading", { size: 20 });
    if (failure === "revision") h.stored.set(READING_STORAGE_KEY, JSON.stringify({ size: 18 }));
    if (failure === "draft") dirty = true;
    if (failure === "quota") h.storage.failWrite = true;
    await h.click("[data-agent-apply]");
    assert.equal(h.writes(), 0); assert.doesNotMatch(h.card().textContent, /已完成/); assert.equal(h.$("[data-agent-undo]"), null);
    assert.match(h.status(), /已改变|未保存|无法保存/);
  }
});

test("undo retries preserve the original operation ID after a lost response", async () => {
  let attempts = 0; const h = createHarness({ handleRequest(call) {
    if (call.path.endsWith("/undo") && ++attempts === 1) return Promise.reject(Error("Synthetic lost undo response"));
  } });
  await h.open(); await h.preview("edit_note", { text: "change" }); await h.click("[data-agent-apply]");
  await h.click("[data-agent-undo]"); assert.match(h.status(), /lost undo response/);
  await h.click("[data-agent-undo]");
  const requests = h.calls.filter(call => call.path.endsWith("/undo"));
  assert.equal(requests.length, 2); assert.equal(requests[0].body.operation_id, requests[1].body.operation_id);
  assert.equal(requests[0].path, `${endpoint}/operation-1/undo`); assert.equal(h.opened.length, 2);
});

test("reading undo retries preserve both ID and expected revision after an uncertain commit", async () => {
  const h = createHarness(); await h.open(); await h.preview("update_reading", { size: 20 }); await h.click("[data-agent-apply]");
  const undo = h.adapter.undo; let attempts = 0;
  h.adapter.undo = async request => { const receipt = await undo(request); if (++attempts === 1) throw Error("Synthetic lost undo response"); return receipt; };
  await h.click("[data-agent-undo]"); assert.equal(h.writes(), 2); assert.equal(h.reading.read().settings.size, 17);
  await h.click("[data-agent-undo]");
  const requests = h.readingCalls.filter(call => call.method === "undo").map(call => call.request);
  assert.equal(requests.length, 2); assert.equal(requests[0].operationId, requests[1].operationId);
  assert.equal(requests[0].expectedRevision, requests[1].expectedRevision); assert.equal(requests[0].targetOperationId, "operation-1");
  assert.equal(h.writes(), 2); assert.match(h.card().textContent, /已完成/);
});

test("note undo blocks the wrong source and preserves an unsaved draft", async () => {
  for (const changed of ["source", "draft"]) {
    const h = createHarness(); await h.open(); await h.preview("edit_note", { text: "change" }); await h.click("[data-agent-apply]");
    if (changed === "source") h.state.selected = { ...h.state.selected, id: "another-note" };
    else { h.state.editing = true; h.note.value = "Keep this draft"; }
    await h.click("[data-agent-undo]"); assert.equal(h.calls.filter(call => call.path.endsWith("/undo")).length, 0);
    assert.match(h.status(), /草稿/); assert.equal(h.opened.length, 1);
  }
});

test("history does not offer undo for note undo receipts or already-undone originals", async () => {
  const h = createHarness(); await h.open(); await h.preview("edit_note", { text: "change" }); await h.click("[data-agent-apply]");
  await h.click("[data-agent-undo]"); assert.equal(h.$("[data-agent-undo]"), null, "an undo receipt must not offer another undo");
  await h.click("[data-agent-history]");
  const records = h.$("[data-agent-records]").querySelectorAll("button"); assert.equal(records.length, 2);
  for (const record of records) { await record.fire("click"); assert.equal(h.$("[data-agent-undo]"), null); }
});

test("history shows reading undo as a completed receipt without offering to undo the undo", async () => {
  const h = createHarness(); await h.open(); await h.preview("update_reading", { size: 20 }); await h.click("[data-agent-apply]");
  await h.click("[data-agent-undo]"); assert.equal(h.$("[data-agent-undo]"), null);
  await h.click("[data-agent-history]");
  const records = h.$("[data-agent-records]").querySelectorAll("button"); assert.equal(records.length, 2);
  await records.at(-1).fire("click"); assert.match(h.card().textContent, /已完成/); assert.equal(h.$("[data-agent-undo]"), null);
});

test("declining record deletion leaves receipts and the saved source intact", async () => {
  const h = createHarness({ confirm: () => false }); await h.open();
  await h.preview("edit_note", { text: "change" }); assert.equal(h.button("删除此操作记录…"), undefined);
  await h.click("[data-agent-apply]"); const visible = h.card().textContent, source = h.state.text;
  await h.button("删除此操作记录…").fire("click"); await flush();
  assert.equal(h.confirmations.length, 1); assert.match(h.confirmations[0], /撤销记录、正文副本和导出缓存/);
  assert.match(h.confirmations[0], /不能.*撤销/); assert.equal(h.calls.filter(call => call.method === "DELETE").length, 0);
  assert.equal(h.operations.has("operation-1"), true); assert.equal(h.card().textContent, visible);
  assert.equal(h.state.text, source); assert.equal(h.opened.length, 1);
});

test("confirming deletion removes the selected receipt and clears the card after success", async () => {
  const h = createHarness(); await h.open(); await h.preview("export_note", { format: "pdf" }); await h.click("[data-agent-apply]");
  const source = h.state.text; await h.button("删除此操作记录…").fire("click"); await flush();
  const request = h.calls.find(call => call.method === "DELETE");
  assert.equal(request.path, `${endpoint}/operation-1`); assert.deepEqual(request.body, { confirm: true });
  assert.equal(h.confirmations.length, 1); assert.equal(h.operations.has("operation-1"), false);
  assert.equal(h.card().textContent, ""); assert.match(h.status(), /已删除.*正文未变化/);
  assert.equal(h.state.text, source); assert.equal(h.opened.length, 0);
  await h.click("[data-agent-history]"); assert.match(h.$("[data-agent-records]").textContent, /还没有执行记录/);
});

test("a failed deletion keeps the receipt visible and does not claim it was removed", async () => {
  const h = createHarness({ handleRequest: call => call.method === "DELETE" ? Promise.reject(Error("Synthetic deletion failed")) : undefined });
  await h.open(); await h.preview("export_note", { format: "markdown" }); await h.click("[data-agent-apply]");
  const visible = h.card().textContent; await h.button("删除此操作记录…").fire("click"); await flush();
  assert.equal(h.card().textContent, visible); assert.equal(h.operations.has("operation-1"), true);
  assert.match(h.status(), /deletion failed/); assert.doesNotMatch(h.status(), /已删除/);
});
