// Exercise the shipped hub, selected/list adoption, edition and metadata hooks.
// Deferred local reads model ordering only; no browser, timers or provider calls.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { createHash, webcrypto } from "node:crypto";
import test from "node:test";
const read = name => readFileSync(new URL(`../${name}`, import.meta.url), "utf8");
const load = async name => import("data:text/javascript;base64," + Buffer.from(read(name)).toString("base64"));
const { createTaskEventHub } = await load("desk-events.js");
const { claimMapVersion } = await load("claim-timeline.js");
const { localMediaSource } = await load("local-player.js");
const desk = read("desk.js"), product = read("desk-product.js");
const flush = () => new Promise(resolve => setImmediate(resolve));
const task = (changes = {}) => ({ id: "selected", kind: "task", title: "Selected", status: "running", updated_at: "one",
  control_generation: "generation-one", options: {}, summary_source: "transcript-draft", transcript_path: "transcript.json",
  artifact_status: { draft_available: true }, frame_grids: [], ...changes });
function harness({ holdEdition = false, reading = {}, ignoreAbort = false, projectionConflict = () => false, initial = {} } = {}) {
  const old = task(initial), nodes = new Map(), events = [], listeners = new Map(), requests = [], targets = [], lists = [], editions = [], snapshots = [], controls = [], streams = [];
  const renders = [], sources = [], notices = [], notifications = [];
  let active = 0, maxActive = 0, decorations = 0, snapshotActive = 0, maxSnapshotActive = 0, currentEdition = { text: "Existing text", revision: "same" };
  const $ = id => {
    if (!nodes.has(id)) nodes.set(id, { hidden: false, value: "", dataset: {}, innerHTML: "", textContent: "",
      querySelector: () => null, querySelectorAll: () => [], replaceChildren() {}, addEventListener() {} });
    return nodes.get(id);
  };
  $("document").dataset.readerSource = "task:selected";
  $("document").dataset.readerRevision = "same::";
  $("inlineSourceView").hidden = $("assistantPanel").hidden = true;
  $("sourcePanel").hidden = true; $("sourcePanel").dataset.sourceTaskId = old.id;
  const state = { selected: old, items: [old], epoch: 1, text: currentEdition.text, revision: "same", editing: false,
    lastHealthAt: Date.now(), reading, model: {}, health: {} };
  const defer = (path, options, collection, target = false) => {
    let yes, no, settled = false;
    const promise = new Promise((resolve, reject) => { yes = resolve; no = reject; });
    if (target) { active++; maxActive = Math.max(maxActive, active); }
    const settle = callback => value => { if (settled) return; settled = true; if (target) active--; callback(value); };
    const pending = { path, options, resolve: settle(yes), reject: settle(no) }; collection.push(pending);
    if (!ignoreAbort) options.signal?.addEventListener("abort", () => pending.reject(Object.assign(new Error("Aborted"), { name: "AbortError" })), { once: true });
    return promise;
  };
  const window = {
    addEventListener: (name, handler) => { if (!listeners.has(name)) listeners.set(name, []); listeners.get(name).push(handler); },
    dispatchEvent: event => { events.push(event); for (const listener of listeners.get(event.type) || []) listener(event); },
  };
  class Event { constructor(type, options = {}) { this.type = type; this.detail = options.detail; } }
  class Notification { static permission = "granted"; constructor(title, options) { notifications.push({ title, ...options }); } }
  window.Notification = Notification;
  const context = vm.createContext({ state, $, Date, Map, JSON, Promise, AbortController, crypto: webcrypto, TextEncoder, window, Event, CustomEvent: Event, Notification,
    claimMapVersion, localMediaSource, createTaskEventHub, syncStatus: {},
    EventSource: class {
      constructor(url) { this.url = url; this.listeners = new Map(); streams.push(this); }
      addEventListener(name, fn) { this.listeners.set(name, fn); }
      close() { this.closed = true; }
    },
    api: (path, options = {}) => {
      requests.push({ path, options });
      if (path === "/api/tasks") return defer(path, options, lists);
      if (path.startsWith("/api/library/materials")) return Promise.resolve({ materials: [] });
      if (path === "/health") return Promise.resolve({});
      if (path === "/api/study/activity") return Promise.resolve({});
      if (path.includes("?reader_snapshot=true&expected_generation=")) {
        snapshotActive++; maxSnapshotActive = Math.max(maxSnapshotActive, snapshotActive);
        return defer(path, options, snapshots).finally(() => { snapshotActive--; });
      }
      if (path.startsWith("/api/tasks/editions/")) return holdEdition ? defer(path, options, editions) : Promise.resolve(currentEdition);
      if (/^\/api\/tasks\/[^/]+$/.test(path)) return defer(path, options, targets, true);
      if (/^\/api\/tasks\/[^/]+\/(cancel|start|resume|retry-summary)$/.test(path)) return defer(path, options, controls);
      throw new Error("Unexpected read: " + path);
    },
    drawList() {}, renderStatus() {}, guard: () => true, notice: value => notices.push(value), failure: error => notices.push(error.message),
    claimTimeline: { reset() {} }, personalAnchorPicker: { reset() {} },
    closeSource: () => { $("sourcePanel").hidden = true; }, openSource: async () => sources.push(localMediaSource(state.selected)),
    loadAnnotations: async () => {}, sourcePath: selected => `/api/tasks/editions/${selected.kind}/${selected.id}`,
    sectionReader: { clear() {}, retainableSnapshot: projectionConflict, render: () => false }, LearnNoteMarkdown: { configure() {}, markdownToHtml: text => text }, taskAsset: value => value,
    renderEditionStable: (element, _scroller, source, revision, render) => {
      if (element.dataset.readerSource === source && element.dataset.readerRevision === revision) return false;
      render(); element.dataset.readerSource = source; element.dataset.readerRevision = revision; return true;
    },
    collapseSourceReviews() {}, decorateSourceTimes: () => { decorations++; },
    renderNote: () => renders.push({ id: state.selected?.id, text: state.text }), loadClaimTimeline() {},
    history: { replaceState() {} }, location: { pathname: "/" },
    document: { hidden: false, scrollingElement: {}, querySelector: () => null },
    readerNav: {}, timestamp: () => "5:00", installNoteEditor: options => { context.editorOptions = options; },
    workspaceTools: { diagnostics: async () => {} }, options: () => ({}), reviewTaskModelData: async () => ({}),
  });
  const home = desk.slice(desk.indexOf("function showHome("), desk.indexOf("async function navigateBack("));
  const refresh = desk.slice(desk.indexOf("function refresh() {"), desk.indexOf("let editionRequest ="));
  const edition = desk.slice(desk.indexOf("async function loadEdition("), desk.indexOf("function renderNote()"));
  const hub = desk.slice(desk.indexOf("const taskEvents ="), desk.indexOf('window.addEventListener("visibilitychange"'));
  const editor = desk.slice(desk.indexOf("installNoteEditor({"), desk.indexOf('$("export").onclick'));
  const action = desk.slice(desk.indexOf('$("taskStatus").onclick'), desk.indexOf('$("settings").onclick'));
  const metadata = product.slice(product.indexOf("  function updateReadingContext() {"), product.indexOf('  $("sourceFrames").onclick'));
  vm.runInContext("let evidenceRequest = 0;" + home + refresh + "let editionRequest = 0;" + edition + hub + editor + action + metadata, context);
  context.syncTaskEventStreams([old]);
  let eventId = 0;
  return { context, state, old, $, requests, targets, lists, editions, snapshots, controls, events, renders, sources, notices, notifications,
    decorations: () => decorations, maxSnapshotActive: () => maxSnapshotActive,
    maxActive: () => maxActive, active: () => active, setEdition: value => { currentEdition = value; },
    emit: name => { const stream = streams.findLast(item => !item.closed); assert(stream, "current stream"); stream.listeners.get(name)?.({ lastEventId: String(++eventId) }); },
    control: action => $("taskStatus").onclick({ target: { closest: () => ({ dataset: { taskAction: action } }) } }),
  };
}

test("one native draft event bypasses a joined stale periodic list and its late response cannot roll back the reader", async () => {
  const h = harness(), periodic = h.context.refresh(); h.emit("draft_ready");
  assert.equal(h.lists.length, 1); assert.equal(h.targets.length, 1);
  h.setEdition({ text: "Draft is readable", revision: "draft" });
  h.targets[0].resolve({ task: task({ updated_at: "two" }) }); await flush();
  assert.equal(h.state.text, "Draft is readable"); assert.equal(h.state.selected.updated_at, "two");
  assert.equal(h.state.items[0].updated_at, "one", "fast reads do not own the retained library");
  h.lists[0].resolve({ tasks: [h.old] }); await periodic; await flush();
  assert.equal(h.state.selected.updated_at, "two"); assert.equal(h.state.text, "Draft is readable");
  assert.equal(h.state.items[0].updated_at, "two"); assert.equal(h.targets.length, 1);
});

test("newer library adoption fences an older targeted generation and permits one fresh replay", async () => {
  const h = harness(), targeted = h.context.refreshSelectedTask(), library = h.context.refresh();
  const newer = task({ control_generation: "generation-two" });
  h.lists[0].resolve({ tasks: [newer] }); await library;
  h.targets[0].resolve({ task: h.old }); await flush();
  assert.equal(h.state.selected.control_generation, "generation-two"); assert.equal(h.targets.length, 2);
  h.targets[1].resolve({ task: newer }); await targeted;
  assert.equal(h.state.selected.control_generation, "generation-two"); assert.equal(h.maxActive(), 1);
});

test("identical overlapping polls cannot sustain contention retries after the one replay", async () => {
  const h = harness(), targeted = h.context.refreshSelectedTask();
  for (let round = 0; round < 2; round++) {
    const library = h.context.refresh(); h.lists[round].resolve({ tasks: [h.old] }); await library;
    h.targets[round].resolve({ task: h.old }); await flush();
  }
  await targeted; assert.equal(h.targets.length, 2); assert.equal(h.active(), 0);
  for (let round = 2; round < 5; round++) { const library = h.context.refresh(); h.lists[round].resolve({ tasks: [h.old] }); await library; }
  await flush(); assert.equal(h.targets.length, 2); assert.equal(h.maxActive(), 1);
});

test("continuous bursts re-dirty one selected lane and stop after terminal with no new invalidation", async () => {
  const h = harness(), pending = h.context.refreshSelectedTask();
  for (let round = 0; round < 3; round++) {
    for (let event = 0; event < 20; event++) h.context.refreshSelectedTask();
    assert.equal(h.targets.length, round + 1); assert.equal(h.active(), 1);
    h.targets[round].resolve({ task: task({ updated_at: String(round) }) }); await flush();
  }
  h.targets[3].resolve({ task: task({ status: "cancelled", updated_at: "terminal" }) }); await pending; await flush();
  assert.equal(h.targets.length, 4); assert.equal(h.active(), 0); assert.equal(h.maxActive(), 1);
  assert.equal(h.state.selected.status, "cancelled");
});

test("generation-only metadata refresh requests its edition without waiting for a library", async () => {
  const h = harness(); h.setEdition({ text: "New attempt", revision: "new" });
  const pending = h.context.refreshSelectedTask(); h.targets[0].resolve({ task: task({ control_generation: "generation-two" }) }); await pending;
  assert.equal(h.state.text, "New attempt"); assert.equal(h.state.selected.updated_at, "one"); assert.equal(h.lists.length, 0);
  assert.equal(h.events.find(event => event.type === "learnnote:metadata").detail.control_generation, "generation-two");
});

test("away/back to the same ID and a later material route reject old targeted metadata and hooks", async () => {
  for (const destination of [task(), { id: "material", kind: "material", title: "Material", updated_at: "one" }]) {
    const h = harness(), pending = h.context.refreshSelectedTask();
    await h.context.openItem(task({ id: "other" })); await h.context.openItem(destination);
    const count = h.events.filter(event => event.type === "learnnote:metadata").length;
    h.targets[0].resolve({ task: task({ updated_at: "obsolete" }) }); await pending; await flush();
    assert.equal(h.state.selected.id, destination.id); assert.equal(h.state.selected.updated_at, "one");
    assert.equal(h.events.filter(event => event.type === "learnnote:metadata").length, count);
  }
});

test("editing fences old reads and post-edit rendering starts a fresh read without changing the editor text", async () => {
  const h = harness(), pending = h.context.refreshSelectedTask();
  h.context.editorOptions.onEnterEdit(); h.state.editing = true; h.$("noteText").value = "Unsaved words";
  h.targets[0].resolve({ task: task({ updated_at: "obsolete" }) }); await pending;
  await h.context.refreshSelectedTask(); assert.equal(h.targets.length, 1); assert.equal(h.state.text, "Existing text");
  assert.equal(h.$("noteText").value, "Unsaved words");
  h.state.editing = false; h.context.editorOptions.renderNote(); assert.equal(h.targets.length, 2);
  h.targets[1].resolve({ task: task({ updated_at: "two" }) }); await flush();
  assert.equal(h.state.selected.updated_at, "two"); assert.equal(h.$("noteText").value, "Unsaved words");
});

test("only an exact current-source 404 clears the reader; transient errors and stale 404s keep it", async () => {
  const current = harness(), missing = current.context.refreshSelectedTask();
  current.targets[0].reject(Object.assign(new Error("Missing"), { status: 404 })); await missing;
  assert.equal(current.state.selected, null); assert.equal(current.$("reading").hidden, true);
  const transient = harness(), failed = transient.context.refreshSelectedTask();
  transient.targets[0].reject(Object.assign(new Error("Unavailable"), { status: 503 })); await failed;
  assert.equal(transient.state.selected.id, "selected"); assert.equal(transient.state.text, "Existing text");
  const stale = harness(), waiting = stale.context.refreshSelectedTask(); await stale.context.openItem(task({ id: "other" }));
  stale.targets[0].reject(Object.assign(new Error("Missing"), { status: 404 })); await waiting;
  assert.equal(stale.state.selected.id, "other");
});

test("a missing selected task replays after identical library adoption and clears despite an empty later list", async () => {
  const h = harness(), pending = h.context.refreshSelectedTask(), library = h.context.refresh();
  h.lists[0].resolve({ tasks: [h.old] }); await library;
  h.targets[0].reject(Object.assign(new Error("Missing"), { status: 404 })); await flush();
  assert.equal(h.targets.length, 2); assert.equal(h.state.selected.id, "selected");
  const later = h.context.refresh(); h.lists[1].resolve({ tasks: [] }); await later;
  assert.equal(h.state.items.length, 0); assert.equal(h.state.selected, null);
  h.targets[1].reject(Object.assign(new Error("Missing"), { status: 404 })); await pending;
  assert.equal(h.state.selected, null); assert.equal(h.$("reading").hidden, true);
  assert.equal(h.targets.length, 2); assert.equal(h.maxActive(), 1);
});

test("exhausted 404 contention settles on a fresh complete-list absence without another targeted read", async () => {
  const h = harness(), pending = h.context.refreshSelectedTask(), first = h.context.refresh();
  h.lists[0].resolve({ tasks: [h.old] }); await first;
  const second = h.context.refresh();
  h.targets[0].reject(Object.assign(new Error("Missing"), { status: 404 })); await flush();
  h.lists[1].resolve({ tasks: [h.old] }); await second;
  h.targets[1].reject(Object.assign(new Error("Missing"), { status: 404 })); await pending;
  assert.equal(h.targets.length, 2); assert.equal(h.active(), 0); assert.equal(h.state.selected.id, "selected");
  for (let round = 2; round < 5; round++) {
    const library = h.context.refresh(); h.lists[round].resolve({ tasks: [] }); await library;
    assert.equal(h.state.selected, null); assert.equal(h.$("reading").hidden, true);
  }
  assert.equal(h.targets.length, 2); assert.equal(h.maxActive(), 1);
});

test("an obsolete empty list cannot clear navigation, edits, pending controls or newer-generation metadata", async () => {
  for (const boundary of ["away-back", "material", "editing", "control", "generation"]) {
    const h = harness(), library = h.context.refresh();
    let control;
    if (boundary === "away-back") { await h.context.openItem(task({ id: "other" })); await h.context.openItem(h.old); }
    if (boundary === "material") await h.context.openItem({ id: "material", kind: "material", title: "Material" });
    if (boundary === "editing") { h.context.editorOptions.onEnterEdit(); h.state.editing = true; h.$("noteText").value = "Unsaved words"; }
    if (boundary === "control") { control = h.control("cancel"); assert.equal(h.controls.length, 1); }
    if (boundary === "generation") {
      const targeted = h.context.refreshSelectedTask();
      h.targets[0].resolve({ task: task({ control_generation: "generation-two" }) }); await targeted;
    }
    h.lists[0].resolve({ tasks: [] }); await library;
    assert.equal(h.state.items.length, 0);
    assert.equal(h.state.selected.id, boundary === "material" ? "material" : "selected");
    assert.equal(h.$("reading").hidden, false);
    if (boundary === "editing") assert.equal(h.$("noteText").value, "Unsaved words");
    if (boundary === "generation") assert.equal(h.state.selected.control_generation, "generation-two");
    if (control) {
      h.controls[0].resolve({}); await flush();
      const current = task({ status: "cancelling" });
      h.targets[0].resolve({ task: current }); await flush();
      h.lists[1].resolve({ tasks: [current] }); await control;
      assert.equal(h.state.selected.status, "cancelling");
    }
  }
});

test("a stale 404 after newer-generation adoption replays without clearing the newer task", async () => {
  const h = harness(), pending = h.context.refreshSelectedTask(), library = h.context.refresh();
  const newer = task({ control_generation: "generation-two" });
  h.lists[0].resolve({ tasks: [newer] }); await library;
  h.targets[0].reject(Object.assign(new Error("Missing"), { status: 404 })); await flush();
  assert.equal(h.targets.length, 2); assert.equal(h.state.selected.control_generation, "generation-two");
  h.targets[1].resolve({ task: newer }); await pending;
  assert.equal(h.state.selected.control_generation, "generation-two"); assert.equal(h.$("reading").hidden, false);
});

test("edition 404 rechecks task existence once without looping when only the edition is missing", async () => {
  for (const taskExists of [false, true]) {
    const h = harness({ holdEdition: true }), pending = h.context.refreshSelectedTask();
    h.targets[0].resolve({ task: h.old }); await flush();
    h.editions[0].reject(Object.assign(new Error("Missing edition"), { status: 404 })); await flush();
    assert.equal(h.targets.length, 2); assert.equal(h.state.selected.id, "selected");
    if (taskExists) {
      h.targets[1].resolve({ task: h.old }); await flush();
      h.editions[1].reject(Object.assign(new Error("Missing edition"), { status: 404 }));
    } else h.targets[1].reject(Object.assign(new Error("Missing task"), { status: 404 }));
    await pending; await flush();
    assert.equal(h.targets.length, 2); assert.equal(h.active(), 0); assert.equal(h.maxActive(), 1);
    assert.equal(h.state.selected?.id || null, taskExists ? "selected" : null);
    if (taskExists) assert.equal(h.state.text, "Existing text");
  }
});

test("navigation, editing and control admission fence a late non-cooperative 404 during replay", async () => {
  for (const boundary of ["away-back", "material", "editing", "control"]) {
    const h = harness({ ignoreAbort: true }), pending = h.context.refreshSelectedTask(), library = h.context.refresh();
    h.lists[0].resolve({ tasks: [h.old] }); await library;
    h.targets[0].reject(Object.assign(new Error("Missing"), { status: 404 })); await flush();
    assert.equal(h.targets.length, 2);
    let control;
    if (boundary === "away-back") { await h.context.openItem(task({ id: "other" })); await h.context.openItem(h.old); }
    if (boundary === "material") await h.context.openItem({ id: "material", kind: "material", title: "Material" });
    if (boundary === "editing") { h.context.editorOptions.onEnterEdit(); h.state.editing = true; h.$("noteText").value = "Unsaved words"; }
    if (boundary === "control") { control = h.control("cancel"); assert.equal(h.controls.length, 1); }
    h.targets[1].reject(Object.assign(new Error("Missing"), { status: 404 })); await pending; await flush();
    assert.equal(h.state.selected.id, boundary === "material" ? "material" : "selected");
    assert.equal(h.targets.length, 2); assert.equal(h.$("reading").hidden, false);
    if (boundary === "editing") assert.equal(h.$("noteText").value, "Unsaved words");
    if (control) {
      h.controls[0].resolve({}); await flush();
      const current = task({ status: "cancelling" });
      h.targets[2].resolve({ task: current }); await flush();
      h.lists[1].resolve({ tasks: [current] }); await control;
      assert.equal(h.state.selected.status, "cancelling");
    }
  }
});

test("terminal metadata updates even with unchanged edition, without selection resets or focus work", async () => {
  const h = harness(), pending = h.context.refreshSelectedTask();
  h.targets[0].resolve({ task: task({ status: "cancelled", updated_at: "terminal" }) }); await pending;
  assert.match(h.$("readerMetadata").textContent, /已停止 · 字幕已保留/); assert.equal(h.renders.length, 0);
  assert.equal(h.events.filter(event => event.type === "learnnote:selection").length, 0);
  h.$("readerMetadata").textContent = "untouched";
  h.context.window.dispatchEvent(new h.context.CustomEvent("learnnote:metadata", { detail: { id: "selected", kind: "task", epoch: 0 } }));
  assert.equal(h.$("readerMetadata").textContent, "untouched");
});

test("the full library still owns the single completion notification after a fast terminal adoption", async () => {
  const h = harness({ reading: { notify: true } }), library = h.context.refresh(), targeted = h.context.refreshSelectedTask();
  h.targets[0].resolve({ task: task({ status: "success", updated_at: "done" }) }); await targeted;
  assert.equal(h.state.items[0].status, "running"); assert.equal(h.notifications.length, 0);
  h.lists[0].resolve({ tasks: [h.old] }); await library;
  assert.equal(h.notifications.length, 1); assert.equal(h.state.items[0].status, "success");
  const next = h.context.refresh(); h.lists[1].resolve({ tasks: [h.state.selected] }); await next;
  assert.equal(h.notifications.length, 1);
});

test("closing the source while a selected edition waits cannot resurrect the source panel", async () => {
  const h = harness({ holdEdition: true }); h.$("sourcePanel").hidden = false;
  const pending = h.context.refreshSelectedTask();
  h.targets[0].resolve({ task: task({ updated_at: "media", media_path: "clip.mp4", media_integrity: { sha256: "clip" } }) }); await flush();
  h.$("sourcePanel").hidden = true; h.editions[0].resolve({ text: "Draft", revision: "new" }); await pending;
  assert.equal(h.sources.length, 0); assert.equal(h.$("sourcePanel").hidden, true);
});

test("cancel admission fences old reads but its acknowledgement starts a selected read before full-list completion", async () => {
  const h = harness(), obsolete = h.context.refreshSelectedTask(), cancel = h.control("cancel");
  assert.equal(h.controls.length, 1); assert.equal(h.controls[0].options.method, "POST");
  await obsolete; await h.context.refreshSelectedTask(); assert.equal(h.targets.length, 1);
  h.controls[0].resolve({ task: task({ status: "cancelling" }) }); await flush();
  assert.equal(h.targets.length, 2); assert.equal(h.lists.length, 1);
  h.targets[1].resolve({ task: task({ status: "cancelling", updated_at: "stopping" }) }); await flush();
  assert.equal(h.state.selected.status, "cancelling"); assert.match(h.$("readerMetadata").textContent, /正在停止/);
  h.lists[0].resolve({ tasks: [h.old] }); await cancel;
  assert.equal(h.state.selected.status, "cancelling"); assert.equal(h.controls.length, 1);
});


test("completion auto-open is also exactly once across old-running and fresh-success library replies", async () => {
  const h = harness({ reading: { notify: true, autoOpen: true } }), library = h.context.refresh(), targeted = h.context.refreshSelectedTask();
  const completed = task({ status: "success", updated_at: "done" });
  h.targets[0].resolve({ task: completed }); await targeted;
  h.lists[0].resolve({ tasks: [h.old] }); await library;
  const second = h.context.refresh(); h.lists[1].resolve({ tasks: [completed] }); await second;
  assert.equal(h.notifications.length, 1);
  assert.equal(h.events.filter(event => event.type === "learnnote:selection").length, 1);
  assert.equal(h.requests.filter(request => request.path === "/api/study/activity").length, 1);
});

test("actual initialize refresh and route opening run after the edition counter declaration", async () => {
  assert(desk.indexOf("let editionRequest = 0;") < desk.indexOf("\ninitialize();"));
  const h = harness(); h.state.selected = null; h.state.items = [];
  let intervals = 0;
  h.context.loadKey = async () => {};
  h.context.applyRoute = async () => h.context.openItem(h.state.items[0], { remember: false });
  h.context.setInterval = () => { intervals++; };
  const start = desk.indexOf("async function initialize() {");
  vm.runInContext(desk.slice(start, desk.indexOf("\ninitialize();", start)), h.context);
  const startup = h.context.initialize(); await flush();
  h.lists[0].resolve({ tasks: [h.old] }); await startup;
  assert.equal(h.state.selected.id, h.old.id); assert.equal(intervals, 1);
  assert.deepEqual(h.notices, []); assert.equal(h.$("document").dataset.readerSource, "task:selected");
});

test("terminal projection conflict reconciles once with unchanged metadata and no later event", async () => {
  let conflicts = 1;
  const h = harness({ projectionConflict: () => conflicts-- > 0 }); h.emit("task_terminal");
  const pending = h.state.selectedRefresh.promise, cancelled = task({ status: "cancelled", updated_at: "terminal" });
  h.targets[0].resolve({ task: cancelled }); await flush();
  assert.equal(h.state.selected.status, "cancelled"); assert.match(h.$("readerMetadata").textContent, /已停止/);
  assert.equal(h.targets.length, 2, "The returned edition conflict must not await its own pending lane");
  h.targets[1].resolve({ task: cancelled }); await pending;
  assert.equal(h.targets.length, 2); assert.equal(h.renders.length, 0); assert.equal(h.state.selectedRefresh.promise, null);
});

test("persistent ready conflict shares the one replay budget and a later ordinary event remains eligible", async () => {
  const h = harness({ projectionConflict: () => true }), pending = h.context.refreshSelectedTask();
  for (let i = 0; i < 2; i++) { h.targets[i].resolve({ task: task({ status: "cancelled" }) }); await flush(); }
  await pending; assert.equal(h.targets.length, 2); assert.equal(h.renders.length, 0);
  h.emit("task_updated"); assert.equal(h.targets.length, 3);
  h.targets[2].resolve({ task: h.old }); await flush(); h.targets[3].resolve({ task: h.old }); await h.state.selectedRefresh.promise;
  assert.equal(h.targets.length, 4);
});

test("full-list conflict schedules one bounded targeted reconciliation without awaiting it", async () => {
  const h = harness({ projectionConflict: () => true }), periodic = h.context.refresh();
  h.lists[0].resolve({ tasks: [task({ status: "cancelled", updated_at: "terminal" })] }); await periodic;
  assert.equal(h.targets.length, 1); const pending = h.state.selectedRefresh.promise;
  h.targets[0].resolve({ task: h.state.selected }); await pending;
  assert.equal(h.targets.length, 1, "The failed full-list pair consumed the same replay budget");
  for (let i = 1; i < 4; i++) { const list = h.context.refresh(); h.lists[i].resolve({ tasks: [h.state.selected] }); await list; }
  assert.equal(h.targets.length, 1); assert.equal(h.state.selected.status, "cancelled");
});

test("interleaved full-list, CAS and projection conflicts cannot repeatedly re-dirty the selected lane", async () => {
  const h = harness({ projectionConflict: () => true }), targeted = h.context.refreshSelectedTask(), library = h.context.refresh();
  h.lists[0].resolve({ tasks: [task({ status: "cancelled", updated_at: "terminal" })] }); await library;
  h.targets[0].resolve({ task: h.old }); await flush(); assert.equal(h.targets.length, 2);
  const secondList = h.context.refresh(); h.lists[1].resolve({ tasks: [task({ status: "cancelled", updated_at: "last" })] }); await secondList;
  h.targets[1].resolve({ task: h.state.selected }); await targeted; await flush();
  assert.equal(h.targets.length, 2); assert.equal(h.maxActive(), 1); assert.equal(h.state.selectedRefresh.promise, null);
});

test("retained conflict followed by missing task clears it under the existing 404 contract", async () => {
  const h = harness({ projectionConflict: () => true }), pending = h.context.refreshSelectedTask();
  h.targets[0].resolve({ task: h.old }); await flush();
  h.targets[1].reject(Object.assign(new Error("Deleted"), { status: 404 })); await pending;
  assert.equal(h.state.selected, null); assert.equal(h.targets.length, 2);
});

test("full-list conflict finishing after away/back cannot dispatch reconciliation for the newer intent", async () => {
  const h = harness({ holdEdition: true, projectionConflict: () => true }), library = h.context.refresh();
  h.lists[0].resolve({ tasks: [task({ updated_at: "terminal", status: "cancelled" })] }); await flush();
  h.state.epoch++; h.context.invalidateSelectedReads(); h.state.selected = task();
  h.editions[0].resolve({ text: "Existing text", revision: "same" }); await library;
  assert.equal(h.targets.length, 0); assert.equal(h.state.selected.status, "running");
});

test("a full-list reconciliation at lane completion is not lost or repeated", async () => {
  for (const microtasks of [0, 1, 2, 3, 4, 5]) {
    let h, scheduled = false;
    const after = (count, callback) => count ? queueMicrotask(() => after(count - 1, callback)) : callback();
    h = harness({ projectionConflict: () => {
      if (!scheduled) { scheduled = true; after(microtasks, () => h.context.refreshSelectedTask("selected", true)); }
      return false;
    } });
    const pending = h.context.refreshSelectedTask(); h.targets[0].resolve({ task: h.old }); await flush();
    assert.equal(h.targets.length, 2, `A proven list conflict at microtask boundary ${microtasks} must get its one reconciliation`);
    h.targets[1].resolve({ task: h.old }); await pending; await flush();
    assert.equal(h.targets.length, 2); assert.equal(h.state.selectedRefresh.promise, null);
  }
});

test("persistent conflict and invalidation at finalization cannot renew the budget or revive an obsolete lane", async () => {
  for (const mutation of [null, h => { h.state.epoch++; h.context.invalidateSelectedReads(); },
    h => { h.state.editing = true; }, h => { h.state.selectedControlPending = { id: "selected", kind: "task" }; }]) {
    let h, calls = 0;
    const later = (count, callback) => count ? queueMicrotask(() => later(count - 1, callback)) : callback();
    h = harness({ projectionConflict: () => {
      calls++;
      if (calls === 1) {
        const snapshot = h.context.selectedSnapshot();
        later(3, () => { mutation?.(h); if (h.context.selectedSourceCurrent(snapshot)) h.context.refreshSelectedTask("selected", true); });
      }
      return calls > 1;
    } });
    const pending = h.context.refreshSelectedTask(); h.targets[0].resolve({ task: h.old }); await flush();
    if (!mutation) h.targets[1].resolve({ task: h.old });
    await pending; await flush();
    assert.equal(h.targets.length, mutation ? 1 : 2); assert.equal(h.active(), 0);
    assert.equal(h.renders.length, 0);
  }
});


const generation = "a".repeat(64);
const boundDraft = (changes = {}, identity = {}) => {
  const text = "# Selected\n\n## Captions\n\nRetained caption `00:04`.";
  const revision = createHash("sha256").update(text).digest("hex");
  return { text, revision, edited: false, reader_snapshot: {
    schema_version: 1, task_id: "selected", control_generation: generation, retry_count: 0,
    attempt_id: "012345abcdef", publication_sequence: 1, body_revision: revision, source_revision: "b".repeat(64),
    task_updated_at: "two", title: "Selected", status: "running", artifact: "draft.md", summary_source: "transcript-draft",
    summary_generated: false, verified: false, provisional: false, ...identity,
  }, ...changes };
};
const previewHarness = options => harness({ initial: { control_generation: generation, summary_source: "" }, ...options });
async function answerSnapshot(h, value = boundDraft(), index = h.snapshots.length - 1) {
  const pending = h.state.readerSnapshotRefresh.promise;
  h.snapshots[index].resolve(value);
  await pending;
}

test("bound caption body renders while selected GET and a stale full list remain held", async () => {
  const h = previewHarness(), periodic = h.context.refresh();
  h.emit("draft_ready");
  assert.equal(h.targets.length, 1); assert.equal(h.snapshots.length, 1);
  assert.match(h.snapshots[0].path, new RegExp(`reader_snapshot=true&expected_generation=${generation}$`));
  await answerSnapshot(h);
  assert.equal(h.active(), 1, "No heavyweight selected response was needed");
  assert.equal(h.state.text, boundDraft().text); assert.equal(h.state.selected.updated_at, "one");
  assert.equal(h.$("noteActions").inert, true); assert.equal(h.$("readerStrip").inert, true); assert.equal(h.$("annotations").inert, true);
  assert.equal(h.decorations(), 0); assert.equal(h.events.filter(event => event.type === "learnnote:document").length, 0);
  h.lists[0].resolve({ tasks: [h.old] }); await periodic;
  assert.equal(h.state.text, boundDraft().text); assert.equal(h.state.readerSnapshot.task_updated_at, "two");
  h.targets[0].resolve({ task: h.old }); await flush();
  assert.equal(h.targets.length, 2, "Old selected metadata gets only its existing reconciliation");
  h.setEdition(boundDraft()); h.targets[1].resolve({ task: task({ ...h.old, updated_at: "two", note_path: "/synthetic/draft.md", summary_source: "transcript-draft" }) });
  await h.state.selectedRefresh.promise;
  assert.equal(h.state.readerSnapshot, null); assert.equal(h.$("noteActions").inert, false);
  assert.equal(h.renders.length, 0, "The same body is kept in place");
  assert.equal(h.decorations(), 1); assert.match(h.$("readerMetadata").textContent, /字幕已取得/);
  assert.equal(h.events.filter(event => event.type === "learnnote:document").length, 1);
});

test("pre-pointer draft_ready unavailability does not retry; later task_updated wakes the same lane", async () => {
  const h = previewHarness(); h.emit("draft_ready");
  let pending = h.state.readerSnapshotRefresh.promise;
  h.snapshots[0].reject(Object.assign(new Error("reader_snapshot_unavailable"), { status: 409, code: "reader_snapshot_unavailable" }));
  await pending; await flush();
  assert.equal(h.snapshots.length, 1); assert.equal(h.state.text, "Existing text");
  h.emit("task_updated"); assert.equal(h.snapshots.length, 2);
  await answerSnapshot(h);
  assert.equal(h.state.text, boundDraft().text); assert.equal(h.targets.length, 1);
});

test("snapshot bursts have one in-flight request and one dirty follow-up, then stop after preview adoption", async () => {
  const h = previewHarness(); h.emit("draft_ready");
  for (let i = 0; i < 40; i++) h.emit("task_updated");
  assert.equal(h.snapshots.length, 1);
  h.snapshots[0].reject(Object.assign(new Error("changed"), { status: 409 })); await flush();
  assert.equal(h.snapshots.length, 2); assert.equal(h.maxSnapshotActive(), 1);
  for (let i = 0; i < 40; i++) h.emit("task_updated");
  await answerSnapshot(h);
  for (let i = 0; i < 40; i++) h.emit("task_updated");
  await flush();
  assert.equal(h.snapshots.length, 2, "Accepted initial body is neither fetched nor hashed again while metadata waits");
  assert.equal(h.maxSnapshotActive(), 1); assert.equal(h.targets.length, 1);
});

test("invalid envelope, generation, retry, body and source hashes never repaint or retry", async () => {
  const invalid = [
    boundDraft({}, { task_id: "other" }), boundDraft({}, { control_generation: "c".repeat(64) }),
    boundDraft({}, { retry_count: 1 }), boundDraft({}, { body_revision: "c".repeat(64) }),
    boundDraft({}, { source_revision: "" }), boundDraft({}, { publication_sequence: 0 }),
    boundDraft({}, { attempt_id: "legacy" }), boundDraft({}, { title: null }), boundDraft({}, { task_updated_at: "" }),
    boundDraft({}, { status: "success" }),
    boundDraft({}, { artifact: "final.md" }), boundDraft({}, { summary_source: "text-llm" }),
    boundDraft({}, { summary_generated: true }), boundDraft({}, { verified: true }),
    boundDraft({ text: "Mixed body" }), boundDraft({ edited: true }), boundDraft({}, { provisional: undefined }), boundDraft({ reader_snapshot: null }),
  ];
  for (const response of invalid) {
    const h = previewHarness(); h.emit("draft_ready"); await answerSnapshot(h, response); await flush();
    assert.equal(h.state.text, "Existing text"); assert.equal(h.snapshots.length, 1); assert.equal(h.state.readerSnapshot, undefined);
  }
});

test("late bound responses cannot cross editing, away/back, pending controls or same-generation source changes", async () => {
  for (const boundary of ["editing", "away-back", "control", "generation", "range", "media", "source"]) {
    const h = previewHarness({ ignoreAbort: true }); h.emit("draft_ready");
    const pending = h.state.readerSnapshotRefresh.promise;
    if (boundary === "editing") { h.context.editorOptions.onEnterEdit(); h.state.editing = true; h.$("noteText").value = "Unsaved words"; }
    if (boundary === "away-back") { await h.context.openItem(task({ id: "other" })); await h.context.openItem(h.old); }
    if (boundary === "control") { h.state.selectedControlPending = { id: "selected", kind: "task" }; h.context.invalidateSelectedReads(); }
    if (boundary === "generation") h.state.selected = { ...h.old, control_generation: "c".repeat(64) };
    if (boundary === "range") h.state.selected = { ...h.old, learning_range: { start: 12, end: 18 } };
    if (boundary === "media") h.state.selected = { ...h.old, media_path: "other.mp4" };
    if (boundary === "source") h.state.selected = { ...h.old, source_identity: { page_url: "https://example.test/other" } };
    h.snapshots[0].resolve(boundDraft()); await pending;
    assert.notEqual(h.state.text, boundDraft().text, boundary); assert.equal(h.$("noteActions").inert || false, false);
    if (boundary === "editing") assert.equal(h.$("noteText").value, "Unsaved words");
  }
});

test("bound preview is discarded before a changed source/generation or retry control can expose stale actions", async () => {
  for (const changes of [{ control_generation: "c".repeat(64) }, { learning_range: { start: 10, end: 20 } }, { source_task_id: "other" }]) {
    const h = previewHarness({ holdEdition: true }); h.emit("draft_ready"); await answerSnapshot(h);
    const selected = task({ ...h.old, ...changes, updated_at: "new" });
    const pending = h.context.adoptSelectedSnapshot(selected, h.context.selectedSnapshot(), true); await flush();
    assert.equal(h.state.readerSnapshot, null); assert.equal(h.state.text, ""); assert.match(h.$("document").innerHTML, /正在同步正文/);
    h.editions[0].resolve({ text: "New source", revision: "new" }); await pending;
    assert.equal(h.state.text, "New source");
  }
  const h = previewHarness(); h.emit("draft_ready"); await answerSnapshot(h);
  h.state.selectedControlPending = { id: "selected", kind: "task" }; h.context.invalidateSelectedReads();
  assert.equal(h.state.readerSnapshot, null); assert.equal(h.state.text, "");
});

test("deleted bound source clears only its current reader; stale deletion cannot clear a later route", async () => {
  for (const navigate of [false, true]) {
    const h = previewHarness({ ignoreAbort: true }); h.emit("draft_ready");
    const pending = h.state.readerSnapshotRefresh.promise;
    if (navigate) await h.context.openItem(task({ id: "other" }));
    h.snapshots[0].reject(Object.assign(new Error("Deleted"), { status: 404 })); await pending;
    assert.equal(h.state.selected?.id || null, navigate ? "other" : null);
  }
});

test("manual, terminal, partial and non-generated editions retain their ordinary read paths", async () => {
  for (const mutate of [h => { h.state.edition = { edited: true }; }, h => { h.state.selected.status = "success"; },
    h => { h.state.selected.status = "failed"; }, h => { h.state.selected.summary_source = "local-template"; },
    h => { h.state.selected.summary_source = "text-llm"; }, h => { h.$("document").querySelector = () => ({}); }]) {
    const h = previewHarness(); mutate(h); h.context.refreshSelectedTask();
    assert.equal(h.snapshots.length, 0); assert.equal(h.targets.length, 1);
  }
});


test("only the exact provisional pre-pointer pair retains a read-only preview", async () => {
  const cases = [
    ["exact", {}, { text: "", revision: "empty", edited: false }, true],
    ["timestamp", { updated_at: "newer" }, { text: "", edited: false }, false],
    ["generation", { control_generation: "c".repeat(64) }, { text: "", edited: false }, false],
    ["retry", { retry_count: 1 }, { text: "", edited: false }, false],
    ["source", { source_task_id: "other" }, { text: "", edited: false }, false],
    ["terminal", { status: "cancelled" }, { text: "", edited: false }, false],
    ["pointer", { note_path: "draft.md" }, { text: "", edited: false }, false],
    ["summary", { summary_source: "transcript-draft" }, { text: "", edited: false }, false],
    ["personal", {}, { text: "", edited: true }, false],
    ["body", {}, { text: "Fresh body", revision: "fresh", edited: false }, false],
    ["ordinary", {}, { text: "", edited: false }, false],
  ];
  for (const [name, changes, edition, retain] of cases) {
    const h = previewHarness({ holdEdition: true }); h.emit("draft_ready");
    await answerSnapshot(h, boundDraft({}, { provisional: name !== "ordinary", task_updated_at: "one" }));
    const pending = h.context.adoptSelectedSnapshot({ ...h.old, note_path: "", summary_source: "", ...changes }, h.context.selectedSnapshot(), true);
    await flush(); h.editions[0].resolve(edition); const result = await pending;
    assert.equal(result, retain ? "projection_conflict" : undefined, name);
    assert.equal(Boolean(h.state.readerSnapshot), retain, name); assert.equal(h.$("noteActions").inert, retain, name);
    assert.equal(h.state.text, retain ? boundDraft().text : edition.text, name);
  }
});

test("ordinary readable draft and active assistant, dialogs or annotation edits do not open the fast lane", () => {
  for (const mutate of [h => { h.state.selected.summary_source = "transcript-draft"; h.state.edition = { text: "Already readable" }; },
    h => { h.$("assistantPanel").hidden = false; }, h => { h.context.document.querySelector = () => ({}); },
    h => { h.$("annotationText").value = "Unsaved annotation"; }, h => { h.state.annotationSaving = true; },
    h => { h.state.annotationEditingId = "edit-annotation"; }]) {
    const h = previewHarness(); mutate(h); h.context.refreshSelectedTask();
    assert.equal(h.snapshots.length, 0); assert.equal(h.targets.length, 1);
  }
});


test("stale queued metadata can read the bound server-running draft without waiting for selected GET", async () => {
  const h = previewHarness({ initial: { control_generation: generation, status: "queued", awaiting_confirmation: true, summary_source: "" } });
  h.emit("draft_ready"); assert.equal(h.snapshots.length, 1); await answerSnapshot(h);
  assert.equal(h.state.text, boundDraft().text); assert.equal(h.state.selected.status, "queued"); assert.equal(h.active(), 1);
});

test("a pre-preview ordinary edition cannot overwrite the bound body or release source controls", async () => {
  const h = previewHarness({ holdEdition: true });
  const older = h.context.loadEdition(h.state.epoch); h.emit("draft_ready"); await answerSnapshot(h);
  h.editions[0].resolve({ text: "Obsolete edition", revision: "obsolete" }); await older;
  assert.equal(h.state.text, boundDraft().text); assert.equal(h.$("noteActions").inert, true); assert.equal(h.decorations(), 0);
});

test("newer ordinary metadata+edition rejects a late non-cooperative fast response", async () => {
  const h = previewHarness({ ignoreAbort: true }); h.emit("draft_ready");
  const pending = h.state.readerSnapshotRefresh.promise;
  h.setEdition({ text: "New personal edit", revision: "personal", edited: true });
  h.targets[0].resolve({ task: task({ ...h.old, updated_at: "new" }) }); await h.state.selectedRefresh.promise;
  h.snapshots[0].resolve(boundDraft()); await pending;
  assert.equal(h.state.text, "New personal edit"); assert.equal(h.state.readerSnapshot, undefined);
});


test("final, partial, terminal and changed provisional metadata retire preview before a held ordinary edition", async () => {
  for (const changes of [{ note_path: "/synthetic/note.md", summary_source: "text-llm" },
    { note_path: "/synthetic/draft.partial.md", summary_source: "partial-draft" },
    { note_path: "", summary_source: "", status: "cancelled" }, { note_path: "", summary_source: "", updated_at: "newer" }]) {
    const h = previewHarness({ holdEdition: true }); h.emit("draft_ready");
    await answerSnapshot(h, boundDraft({}, { provisional: true, task_updated_at: "one" }));
    const pending = h.context.adoptSelectedSnapshot({ ...h.old, ...changes }, h.context.selectedSnapshot(), true);
    await flush(); assert.equal(h.state.readerSnapshot, null); assert.equal(h.state.text, ""); assert.equal(h.editions.length, 1);
    h.editions[0].resolve({ text: "Ordinary result", revision: "ordinary", edited: false }); await pending;
    assert.equal(h.state.text, "Ordinary result");
  }
});

test("current ordinary missing/personal conflict retires preview, while an older error cannot touch it", async () => {
  for (const status of [404, 409]) {
    const h = previewHarness({ holdEdition: true }); h.emit("draft_ready"); await answerSnapshot(h);
    const pending = h.context.adoptSelectedSnapshot({ ...h.old, note_path: "/synthetic/draft.md", summary_source: "transcript-draft" }, h.context.selectedSnapshot(), true);
    h.editions[0].reject(Object.assign(new Error("Source unavailable"), { status }));
    await assert.rejects(pending); assert.equal(h.state.readerSnapshot, null); assert.equal(h.state.text, "");
    const old = previewHarness({ holdEdition: true }); const stale = old.context.loadEdition(old.state.epoch);
    old.emit("draft_ready"); await answerSnapshot(old);
    old.editions[0].reject(Object.assign(new Error("Old conflict"), { status })); await assert.rejects(stale);
    assert.equal(old.state.text, boundDraft().text); assert.equal(old.$("noteActions").inert, true);
  }
});


test("an edited edition from the previous route cannot block a new task's first bound draft", async () => {
  const h = previewHarness(); h.state.edition = { edited: true, text: "Previous personal note" };
  delete h.$("document").dataset.readerSource;
  h.emit("draft_ready"); assert.equal(h.snapshots.length, 1); await answerSnapshot(h);
  assert.equal(h.state.text, boundDraft().text); assert.equal(h.$("noteActions").inert, true);
});
