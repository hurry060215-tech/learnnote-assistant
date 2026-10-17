import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";
const source = fs.readFileSync(new URL("../desk.js", import.meta.url), "utf8");
const refreshAndOpen = source.slice(source.indexOf("function refresh() {"), source.indexOf("let editionRequest ="));
const home = source.slice(source.indexOf("function showHome("), source.indexOf("async function navigateBack("));
const route = source.slice(source.indexOf("function readRoute() {"), source.indexOf('window.addEventListener("hashchange"'));
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
function harness({ holdEdition = false } = {}) {
  const old = { kind: "task", id: "previous", title: "Previous", status: "success", updated_at: "1" };
  const next = { kind: "task", id: "newly-created", title: "New", status: "queued", awaiting_confirmation: true, updated_at: "2" };
  const held = deferred(), edition = deferred(), enteredEdition = deferred(), requests = [], notices = [], streams = [], actions = [], nodes = new Map();
  const $ = id => { if (!nodes.has(id)) nodes.set(id, { hidden: false, value: "", dataset: {}, replaceChildren() {} }); return nodes.get(id); };
  $("document").dataset.readerSource = "task:previous";
  const state = { items: [old], selected: old, epoch: 1, lastHealthAt: Date.now(), reading: { autoOpen: false } };
  const location = { hash: "#task/previous", search: "", pathname: "/" };
  let tasks = [old], materials = [], first = true, allowed = true, taskError = null;
  const context = vm.createContext({ state, location, URLSearchParams, Date, $, syncStatus: {},
    api: async path => {
      requests.push(path);
      if (path === "/api/tasks") { if (first) { first = false; return held.promise; } if (taskError) throw taskError; return { tasks }; }
      if (path.startsWith("/api/library/materials")) return { materials };
      if (path === "/api/study/activity") return {};
      throw new Error("Unexpected API: " + path);
    },
    syncTaskEventStreams: items => streams.push(items.map(item => item.id)), drawList() {},
    window: { dispatchEvent() {}, LearnNoteAssistant: { open: () => actions.push("qa:" + state.selected.id) } }, CustomEvent: class {}, Event: class {},
    claimMapVersion: item => item.updated_at, localMediaSource: () => null,
    renderStatus() {}, guard: () => allowed, notice: text => notices.push(text),
    claimTimeline: { reset() {} }, personalAnchorPicker: { reset() {} }, closeSource() {},
    history: { replaceState(_state, _title, url) { location.hash = url.startsWith("#") ? url : ""; } },
    loadEdition: async epoch => {
      if (holdEdition && state.selected.id === next.id) { enteredEdition.resolve(); await edition.promise; }
      if (epoch === state.epoch) $("document").dataset.readerSource = `${state.selected.kind}:${state.selected.id}`;
    },
    loadAnnotations: async () => {}, openSource: async () => actions.push("source:" + state.selected.id), document: { querySelector: () => null },
  });
  $("settings").click = () => { actions.push("settings"); $("settingsDialog").open = true; };
  vm.runInContext(home + refreshAndOpen + route + ";globalThis.methods={refresh,applyRoute,openItem,showHome};", context);
  return { state, location, requests, notices, streams, actions, $, held, edition, enteredEdition, old, next, methods: context.methods,
    create: () => { tasks = [next, old]; }, setTasks: value => { tasks = value; }, setMaterials: value => { materials = value; },
    setGuard: value => { allowed = value; }, failFreshTasks: error => { taskError = error; } };
}

test("a newly created task route cannot be declared missing from an older in-flight library snapshot", async () => {
  const app = harness(), background = app.methods.refresh();
  app.create(); app.location.hash = "#task/newly-created";
  const navigation = app.methods.applyRoute();
  app.held.resolve({ tasks: [app.old] }); await background; await navigation;
  assert.equal(app.requests.filter(path => path === "/api/tasks").length, 2, "Exactly one fresh lookup after joining the older request");
  await app.methods.refresh();
  assert(app.streams.some(ids => ids.includes("newly-created")), "The actual library stream list knows the created task");
  assert.equal(app.location.hash, "#task/newly-created");
  assert.equal(app.state.selected.id, "newly-created");
  assert.equal(app.$("document").dataset.readerSource, "task:newly-created");
  assert.deepEqual(app.notices, []);
});


test("rapid routes select only the newest task or material after shared stale refresh", async () => {
  for (const kind of ["task", "material"]) {
    const app = harness(), background = app.methods.refresh(); app.create();
    app.location.hash = "#task/newly-created"; const first = app.methods.applyRoute();
    const newest = { kind, id: "newest", material_id: "newest", title: "Newest", updated_at: "3" };
    if (kind === "task") app.setTasks([newest, app.next, app.old]); else app.setMaterials([newest]);
    app.location.hash = `#${kind}/newest`; const second = app.methods.applyRoute();
    app.held.resolve({ tasks: [app.old] }); await Promise.all([background, first, second]);
    assert.equal(app.state.selected.id, "newest"); assert.equal(app.state.selected.kind, kind);
    assert.equal(app.$("document").dataset.readerSource, `${kind}:newest`); assert.deepEqual(app.notices, []);
    assert.equal(app.requests.filter(path => path === "/api/tasks").length, 2);
  }
});

test("newer Home, direct item selection, settings or rejected navigation cancels an older pending lookup", async () => {
  for (const action of ["home", "item", "settings", "rejected", "raw-hash"]) {
    const app = harness(), background = app.methods.refresh(); app.create();
    app.location.hash = "#task/newly-created"; const navigation = app.methods.applyRoute();
    if (action === "home") app.methods.showHome();
    else if (action === "item") await app.methods.openItem({ kind: "material", id: "manual", title: "Manual" });
    else if (action === "raw-hash") app.location.hash = "#task/another";
    else { app.location.hash = "#settings"; if (action === "rejected") app.setGuard(false); await app.methods.applyRoute(); }
    app.held.resolve({ tasks: [app.old] }); await Promise.all([background, navigation]);
    assert.equal(app.state.selected?.id ?? null, action === "home" ? null : action === "item" ? "manual" : "previous");
    assert.equal(app.requests.filter(path => path === "/api/tasks").length, 1, "Cancelled route must not request another snapshot");
    assert.deepEqual(app.actions, action === "settings" ? ["settings"] : []); assert.deepEqual(app.notices, []);
  }
});

test("missing or deleted targets get a bounded absence result, and refresh failure is propagated", async () => {
  for (const alreadyPending of [false, true]) {
    const app = harness(), background = alreadyPending ? app.methods.refresh() : null;
    app.location.hash = "#task/deleted"; const navigation = app.methods.applyRoute();
    app.held.resolve({ tasks: [app.old] }); await background; await navigation;
    assert.equal(app.requests.filter(path => path === "/api/tasks").length, alreadyPending ? 2 : 1);
    assert.equal(app.state.selected.id, "previous"); assert.equal(app.notices.length, 1);
    assert.match(app.notices[0], /不存在或已被删除/);
  }
  const app = harness(), background = app.methods.refresh(); app.location.hash = "#task/newly-created";
  const navigation = app.methods.applyRoute(), failure = new Error("Library unavailable");
  const checks = [assert.rejects(background, error => error === failure), assert.rejects(navigation, error => error === failure)];
  app.held.reject(failure); await Promise.all(checks);
  assert.equal(app.requests.filter(path => path === "/api/tasks").length, 1);
  assert.equal(app.state.selected.id, "previous"); assert.deepEqual(app.notices, []);
});

test("route-specific source and QA follow-up cannot attach to a newer selection during reader loading", async () => {
  for (const tab of ["source", "qa"]) {
    const app = harness({ holdEdition: true }); app.state.items.push(app.next);
    app.location.hash = `#task/newly-created?tab=${tab}`; const navigation = app.methods.applyRoute();
    await app.enteredEdition.promise;
    await app.methods.openItem(app.old); app.edition.resolve(); await navigation;
    assert.equal(app.state.selected.id, "previous"); assert.equal(app.location.hash, "#task/previous");
    assert.deepEqual(app.actions, []);
  }
});

test("current route preserves source and QA follow-up after its own reader load", async () => {
  for (const tab of ["source", "qa"]) {
    const app = harness({ holdEdition: true }); app.state.items.push(app.next);
    app.location.hash = `#task/newly-created?tab=${tab}`; const navigation = app.methods.applyRoute();
    await app.enteredEdition.promise; app.edition.resolve(); await navigation;
    assert.deepEqual(app.actions, [`${tab}:newly-created`]);
    assert.equal(app.$("document").dataset.readerSource, "task:newly-created");
  }
});


test("a rejected fresh lookup remains an error without another retry or false missing notice", async () => {
  const app = harness(), background = app.methods.refresh(); app.create();
  app.location.hash = "#task/newly-created"; const navigation = app.methods.applyRoute();
  const failure = new Error("Fresh snapshot unavailable"); app.failFreshTasks(failure);
  const rejected = assert.rejects(navigation, error => error === failure);
  app.held.resolve({ tasks: [app.old] }); await background; await rejected;
  assert.equal(app.requests.filter(path => path === "/api/tasks").length, 2);
  assert.equal(app.state.selected.id, "previous"); assert.deepEqual(app.notices, []);
});

test("rejecting a newer navigation cancels pending route follow-up even when the restored hash matches", async () => {
  const app = harness({ holdEdition: true }); app.state.items.push(app.next);
  app.location.hash = "#task/newly-created?tab=qa"; const navigation = app.methods.applyRoute();
  await app.enteredEdition.promise;
  app.setGuard(false); app.location.hash = "#settings"; await app.methods.applyRoute();
  assert.equal(app.location.hash, "#task/newly-created");
  app.edition.resolve(); await navigation;
  assert.equal(app.state.selected.id, "newly-created"); assert.deepEqual(app.actions, []);
});

test("existing items and repeated direct routes do not force an extra library fetch", async () => {
  const known = harness(); known.state.items.push(known.next); known.location.hash = "#task/newly-created";
  await known.methods.applyRoute(); await known.methods.applyRoute();
  assert.equal(known.requests.filter(path => path === "/api/tasks").length, 0);
  assert.equal(known.requests.filter(path => path === "/api/study/activity").length, 1);
  assert.equal(known.state.selected.id, "newly-created");
  const joined = harness(), background = joined.methods.refresh();
  joined.location.hash = "#task/newly-created"; const navigation = joined.methods.applyRoute();
  joined.held.resolve({ tasks: [joined.next, joined.old] }); await Promise.all([background, navigation]);
  await joined.methods.applyRoute();
  assert.equal(joined.requests.filter(path => path === "/api/tasks").length, 1);
  assert.equal(joined.state.selected.id, "newly-created");
});
