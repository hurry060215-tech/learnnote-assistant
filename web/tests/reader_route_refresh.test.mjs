import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";
const source = fs.readFileSync(new URL("../desk.js", import.meta.url), "utf8");
const refreshAndOpen = source.slice(source.indexOf("function refresh() {"), source.indexOf("let editionRequest ="));
const home = source.slice(source.indexOf("function showHome("), source.indexOf("async function navigateBack("));
const back = source.slice(source.indexOf("async function navigateBack("), source.indexOf("function statusLabel("));
const resolver = source.slice(source.indexOf("async function resolveSource("), source.indexOf("async function openEvidenceSource("));
const inlineSource = source.slice(source.indexOf("let inlineSourceRequest ="), source.indexOf("async function openSource("));
const route = source.slice(source.indexOf("function readRoute() {"), source.indexOf('window.addEventListener("hashchange"'));
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
function harness({ holdEdition = false, holdLookup = false } = {}) {
  const old = { kind: "task", id: "previous", title: "Previous", status: "success", updated_at: "1" };
  const next = { kind: "task", id: "newly-created", title: "New", status: "queued", updated_at: "2" };
  const material = { kind: "material", id: "outside-page", material_id: "outside-page", title: "Old material", updated_at: "0" };
  const held = deferred(), lookup = deferred(), edition = deferred(), enteredEdition = deferred(), requests = [], notices = [], actions = [], nodes = new Map();
  const $ = id => { if (!nodes.has(id)) nodes.set(id, { hidden: false, value: "", dataset: {}, replaceChildren() {} }); return nodes.get(id); };
  $("document").dataset.readerSource = "task:previous";
  const state = { items: [old], selected: old, epoch: 1, lastHealthAt: Date.now(), reading: { autoOpen: false } };
  const location = { hash: "#task/previous", search: "", pathname: "/" };
  let allowed = true, lookupError = null, guardCalls = 0;
  const records = new Map([[next.id, next], [material.id, material], [old.id, old]]);
  const context = vm.createContext({ state, location, URLSearchParams, Date, $, syncStatus: {},
    api: async path => {
      requests.push(path);
      if (path === "/api/tasks/catalog") return held.promise;
      if (path.startsWith("/api/library/materials?")) return { materials: [] };
      if (path === "/api/study/activity") return {};
      if (holdLookup) await lookup.promise;
      if (lookupError) throw lookupError;
      const record = records.get(decodeURIComponent(path.split("/").at(-1)));
      if (!record) throw Object.assign(new Error("missing"), { status: 404 });
      return record.kind === "material" ? { material: record } : { task: record };
    },
    syncTaskEventStreams() {}, drawList() {},
    window: { dispatchEvent() {}, LearnNoteAssistant: { open: () => actions.push("qa:" + state.selected.id) } }, CustomEvent: class {}, Event: class {},
    claimMapVersion: item => item.updated_at, localMediaSource: () => null,
    renderStatus() {}, guard: () => { guardCalls++; return allowed; }, notice: text => notices.push(text),
    claimTimeline: { reset() {} }, personalAnchorPicker: { reset() {} }, closeSource() {},
    history: { replaceState(_state, _title, url) { location.hash = url.startsWith("#") ? url : ""; } },
    loadEdition: async epoch => {
      if (holdEdition && state.selected.id === next.id) { enteredEdition.resolve(); await edition.promise; }
      if (epoch === state.epoch) $("document").dataset.readerSource = `${state.selected.kind}:${state.selected.id}`;
    },
    loadAnnotations: async () => {}, openSource: async () => actions.push("source:" + state.selected.id), document: { querySelector: () => null },
  });
  $("settings").click = () => { actions.push("settings"); $("settingsDialog").open = true; };
  vm.runInContext("let editionRequest = 0;" + home + back + resolver + refreshAndOpen + inlineSource + route + ";globalThis.methods={refresh,applyRoute,openItem,showHome,navigateBack,openInlineSource};", context);
  return { state, location, requests, notices, actions, $, held, lookup, edition, enteredEdition, old, next, material, records, methods: context.methods,
    get guardCalls() { return guardCalls; }, setGuard: value => { allowed = value; }, failLookup: error => { lookupError = error; } };
}

test("new note edits and annotations survive a delayed catalog or outside-page route when discard is declined", async () => {
  for (const via of ["catalog", "route", "catalog-route", "back", "catalog-back"]) for (const input of ["note", "annotation"]) {
    const app = harness({ holdLookup: true });
    const catalog = { ...app.next, catalog: true };
    if (via.startsWith("catalog-")) app.state.items.push(catalog);
    let pending;
    if (via === "catalog") pending = app.methods.openItem(catalog);
    else if (via.includes("back")) {
      app.state.navigation = [{ kind: "task", id: app.next.id }]; pending = app.methods.navigateBack();
    } else { app.location.hash = "#task/newly-created"; pending = app.methods.applyRoute(); }
    if (input === "note") {
      app.state.editing = true; app.$("editor").hidden = false; app.$("noteText").value = "New unsaved note";
    } else app.$("annotationText").value = "New unsaved annotation";
    app.setGuard(false); app.lookup.resolve(); await pending;
    assert.equal(app.state.selected.id, app.old.id, `${via}/${input}`);
    assert.equal(app.location.hash, "#task/previous", "Declined routes return to the still-selected source");
    assert.equal(app.guardCalls, 2, "Only the new input requires fresh discard consent");
    if (input === "note") {
      assert.equal(app.state.editing, true); assert.equal(app.$("editor").hidden, false);
      assert.equal(app.$("noteText").value, "New unsaved note");
    } else assert.equal(app.$("annotationText").value, "New unsaved annotation");
    if (via.includes("back")) assert.equal(app.state.navigation.at(-1).id, app.next.id);
    assert.equal(app.requests.includes("/api/study/activity"), false);
  }
});

test("unchanged approved edits do not prompt twice, while new inputs may be explicitly discarded", async () => {
  for (const via of ["catalog", "route", "catalog-route"]) for (const changed of [false, "note", "annotation-whitespace"]) {
    const app = harness({ holdLookup: true }), catalog = { ...app.next, catalog: true };
    app.state.editing = true; app.$("noteText").value = "Already approved discard";
    app.$("annotationText").value = "Already approved annotation";
    if (via === "catalog-route") app.state.items.push(catalog);
    const pending = via === "catalog" ? app.methods.openItem(catalog)
      : (app.location.hash = "#task/newly-created", app.methods.applyRoute());
    if (changed === "note") app.$("noteText").value = "New input after approval";
    if (changed === "annotation-whitespace") app.$("annotationText").value += "  \n";
    app.lookup.resolve(); await pending;
    assert.equal(app.state.selected.id, app.next.id);
    assert.equal(app.guardCalls, changed ? 2 : 1);
    assert.equal(app.state.editing, false); assert.equal(app.$("annotationText").value, "");
  }
});

test("cross-source inline reading cannot bypass unsaved-input consent", async () => {
  for (const cached of [false, true]) {
    const app = harness({ holdLookup: true });
    if (cached) app.state.items.push({ ...app.next, catalog: true });
    app.$("annotationText").value = "Retained personal input"; app.setGuard(false);
    const pending = app.methods.openInlineSource(0, app.next);
    app.lookup.resolve(); await pending;
    assert.equal(app.state.selected.id, app.old.id);
    assert.equal(app.$("annotationText").value, "Retained personal input");
    assert.equal(app.guardCalls, 1);
    assert.equal(app.requests.includes("/api/study/activity"), false);
    assert.equal(app.requests.some(route => route.endsWith("/transcript")), false);
  }
});

test("newly created routes bypass an old full-list request and stale lists cannot roll back navigation", async () => {
  const app = harness(), background = app.methods.refresh();
  app.location.hash = "#task/newly-created"; await app.methods.applyRoute();
  assert.equal(app.state.selected.id, app.next.id);
  app.held.resolve({ tasks: [app.old] }); await background;
  assert.equal(app.state.selected.id, app.next.id); assert.equal(app.$("document").dataset.readerSource, "task:newly-created");
  assert.equal(app.requests.filter(path => path === "/api/tasks/catalog").length, 1);
  assert.equal(app.requests.filter(path => path === "/api/tasks/newly-created").length, 1);
  assert.deepEqual(app.notices, []);
});

test("an existing material outside every loaded page opens directly, including startup", async () => {
  for (const initial of [false, true]) {
    const app = harness(); app.location.hash = "#material/outside-page";
    await app.methods.applyRoute({ initial }); await app.methods.applyRoute();
    assert.equal(app.state.selected.id, app.material.id);
    assert.equal(app.requests.filter(path => path === "/api/library/materials/outside-page").length, 1);
    assert.equal(app.requests.filter(path => path === "/api/tasks/catalog").length, 0);
    assert.equal(app.requests.filter(path => path === "/api/study/activity").length, 1);
    assert.deepEqual(app.notices, []);
  }
});

test("rapid task and material routes select only the newest intent", async () => {
  const app = harness({ holdLookup: true });
  app.location.hash = "#task/newly-created"; const first = app.methods.applyRoute();
  app.location.hash = "#material/outside-page"; const second = app.methods.applyRoute();
  app.lookup.resolve(); await Promise.all([first, second]);
  assert.equal(app.state.selected.id, "outside-page"); assert.deepEqual(app.notices, []);
});

test("catalog navigation hydrates the task and respects newer selections and settings routes", async () => {
  for (const navigation of ["same", "other", "settings"]) {
    const app = harness({ holdLookup: true });
    const pending = app.methods.openItem({ ...app.next, catalog: true });
    assert.equal(app.state.selected.id, app.old.id, "The summary is never published as a full task");
    if (navigation === "other") await app.methods.openItem(app.material);
    if (navigation === "settings") { app.location.hash = "#settings"; await app.methods.applyRoute(); }
    app.lookup.resolve(); const opened = await pending;
    assert.equal(app.state.selected.id, navigation === "same" ? app.next.id : navigation === "other" ? app.material.id : app.old.id);
    assert.equal(app.state.selected.catalog, undefined); assert.equal(opened, navigation === "same");
  }
});

test("Home, selection, settings and rejected navigation cancel an older pending lookup", async () => {
  for (const action of ["home", "item", "settings", "rejected", "raw-hash"]) {
    const app = harness({ holdLookup: true }); app.location.hash = "#task/newly-created";
    const navigation = app.methods.applyRoute();
    if (action === "home") app.methods.showHome();
    else if (action === "item") await app.methods.openItem(app.material);
    else if (action === "raw-hash") app.location.hash = "#task/another";
    else { app.location.hash = "#settings"; if (action === "rejected") app.setGuard(false); await app.methods.applyRoute(); }
    app.lookup.resolve(); await navigation;
    assert.equal(app.state.selected?.id ?? null, action === "home" ? null : action === "item" ? app.material.id : app.old.id);
    assert.deepEqual(app.notices, []);
  }
});

test("only an actual 404 reports missing; transient failures remain retryable errors", async () => {
  const app = harness(); app.location.hash = "#material/deleted"; await app.methods.applyRoute();
  assert.equal(app.notices.length, 1); assert.match(app.notices[0], /不存在或已被删除/);
  assert.equal(app.state.selected.id, app.old.id);
  const unavailable = harness(), error = new Error("offline"); unavailable.failLookup(error);
  unavailable.location.hash = "#task/newly-created";
  await assert.rejects(unavailable.methods.applyRoute(), candidate => candidate === error);
  assert.deepEqual(unavailable.notices, []); assert.equal(unavailable.requests.length, 1);
});

test("source and QA follow-up cannot attach to newer selection during reader loading", async () => {
  for (const tab of ["source", "qa"]) {
    const app = harness({ holdEdition: true }); app.location.hash = `#task/newly-created?tab=${tab}`;
    const navigation = app.methods.applyRoute(); await app.enteredEdition.promise;
    await app.methods.openItem(app.old); app.edition.resolve(); await navigation;
    assert.equal(app.state.selected.id, app.old.id); assert.deepEqual(app.actions, []);
  }
});

test("current route retains its source and QA follow-up after reader loading", async () => {
  for (const tab of ["source", "qa"]) {
    const app = harness({ holdEdition: true }); app.location.hash = `#task/newly-created?tab=${tab}`;
    const navigation = app.methods.applyRoute(); await app.enteredEdition.promise; app.edition.resolve(); await navigation;
    assert.deepEqual(app.actions, [`${tab}:newly-created`]);
  }
});

test("rejecting later navigation cancels pending route follow-up even when the restored hash matches", async () => {
  const app = harness({ holdEdition: true }); app.location.hash = "#task/newly-created?tab=qa";
  const navigation = app.methods.applyRoute(); await app.enteredEdition.promise;
  app.setGuard(false); app.location.hash = "#settings"; await app.methods.applyRoute();
  assert.equal(app.location.hash, "#task/newly-created");
  app.edition.resolve(); await navigation; assert.deepEqual(app.actions, []);
});
