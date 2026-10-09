import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../course-graph-snapshot.js", import.meta.url), "utf8");
const concepts = readFileSync(new URL("../course-concepts.js", import.meta.url), "utf8");
const tools = readFileSync(new URL("../desk-tools.js", import.meta.url), "utf8");
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const flush = () => new Promise(resolve => setImmediate(resolve));
const hostile = '<img src="https://not-loaded.invalid" onerror="alert(1)"> 完成后打开笔记 cafe\u0301 🧭';
const graph = () => ({
  query: "  SCALE   scale  ", warning: "关键词共现不代表同义、因果或观点一致。",
  counts: { matches: 2, nodes: 2, edges: 1 }, truncated: { matches: false, nodes: false, edges: false },
  matches: [{ evidence_id: "one", title: hostile, locator: "0-12s", excerpt: "Short excerpt" }, { evidence_id: "two", title: "Second", locator: "page 2", excerpt: "scale" }],
  nodes: [{ id: "material:first", title: hostile, evidence_ids: ["one"] }, { id: "material:second", title: "Second", evidence_ids: ["two"] }],
  edges: [{ from: "material:first", to: "material:second", kind: "keyword_cooccurrence", terms: ["scale"], evidence_ids: ["one", "two"],
    citations: [{ evidence_id: "one", title: hostile, locator: "0-12s" }, { evidence_id: "two", title: "Second", locator: "page 2" }] }],
});
const snapshot = () => ({
  format: "learnnote.filtered-comparison", schema_version: 1,
  course: { id: "course/one", title: hostile, revision: 7 },
  scope: { query: "  SCALE   scale  ", terms: ["scale"], filters: { source_kind: "material", source_id: "", start: 0, end: 12.5 } },
  evidence: [{ evidence_id: "one", title: hostile, locator: "0-12s", text: "Long original scale " + hostile + " complete end beyond excerpt", source_uri: "javascript:alert(1)", metadata: { start: 0, end: 12 }, redacted_fields: ["source_uri"] },
    { evidence_id: "two", title: "Second", locator: "page 2", text: "Second scale original", source_uri: "https://not-loaded.invalid/private" }],
  history: { events: [{ label: hostile, action: "split" }] },
  unresolved: [{ term: "scale", evidence_id: "missing", status: "missing" }, { term: "scale", evidence_id: "stale", status: "stale" }],
  group_state: [{ term: "scale", groups: [{ label: hostile, evidence_ids: ["one"], unresolved_ids: ["missing"] }] }],
  sources: [{ reference: { title: hostile }, status: "missing", missing_evidence_ids: ["missing"] }],
  graph: graph(), digest: "a".repeat(64),
});

function harness() {
  const h = { current: true, requests: [], downloads: [], blobs: [], revoked: [], focused: [], scrolled: [] };
  const camel = value => value.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
  class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.style = {}; this.listeners = {}; this.attributes = {}; this._text = ""; this.value = ""; this.disabled = false; this.open = false; }
    set textContent(value) { this._text = String(value); this.replaceChildren(); }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(""); }
    set innerHTML(html) {
      if (!h.allowMarkup) throw new Error("Snapshot UI must never parse user markup");
      this._text = ""; this.replaceChildren(); const stack = [this];
      for (const match of html.matchAll(/<\/?[^>]+>|[^<]+/g)) {
        const token = match[0];
        if (token.startsWith("</")) { stack.pop(); continue; }
        if (!token.startsWith("<")) { const text = new Element("#text"); text.textContent = token; stack.at(-1).append(text); continue; }
        const tag = token.match(/^<([\w-]+)/)?.[1];
        if (!tag) continue;
        const element = new Element(tag);
        for (const [, key, value = ""] of token.slice(tag.length + 1, -1).matchAll(/([\w-]+)(?:="([^"]*)")?/g)) {
          element.setAttribute(key, value);
          if (["id", "type", "value"].includes(key)) element[key] = value;
        }
        stack.at(-1).append(element);
        if (!["input", "img", "br", "hr"].includes(tag)) stack.push(element);
      }
    }
    get isConnected() { return this._connected || !!this.parentElement?.isConnected; }
    append(...items) { for (const item of items) { item.parentElement = this; this.children.push(item); } }
    replaceChildren(...items) { for (const item of this.children) item.parentElement = null; this.children = []; this.append(...items); }
    remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(item => item !== this); this.parentElement = null; }
    addEventListener(event, action) { this.listeners[event] = action; }
    setAttribute(name, value) { this.attributes[name] = value; if (name.startsWith("data-")) this.dataset[camel(name.slice(5))] = value; }
    getAttribute(name) { return name.startsWith("data-") ? this.dataset[camel(name.slice(5))] ?? null : this.attributes[name] ?? null; }
    hasAttribute(name) { return this.getAttribute(name) !== null; }
    matches(selector) {
      if (selector === "*") return true;
      if (selector.startsWith("[")) { const [, key, value] = selector.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/); return this.hasAttribute(key) && (value === undefined || this.getAttribute(key) === value); }
      return this.tag === selector;
    }
    querySelectorAll(selector) { return this.children.flatMap(item => [...(item.matches(selector) ? [item] : []), ...item.querySelectorAll(selector)]); }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    click() { if (this.tag === "a") h.downloads.push({ href: this.href, name: this.download }); else if (!this.disabled) return this.listeners.click?.(); }
    showModal() { this.open = true; }
    close() { this.open = false; }
    focus() { h.focused.push(this); }
    scrollIntoView() { h.scrolled.push(this); }
  }
  h.root = new Element("main"); h.root._connected = true;
  const document = { createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag), createTextNode: text => Object.assign(new Element("#text"), { textContent: text }) };
  document.getElementById = id => h.root.querySelectorAll("*").find(node => node.id === id);
  h.context = vm.createContext({ document, Blob, URLSearchParams, URL: { createObjectURL: blob => { h.blobs.push(blob); return `blob:${h.blobs.length}`; }, revokeObjectURL: url => h.revoked.push(url) }, setTimeout: callback => callback() });
  vm.runInContext(concepts.replaceAll("export function", "function") + "\n" + source.replace(/^import .*;\n/, "").replaceAll("export function", "function"), h.context);
  h.api = (path, options = {}) => { const request = deferred(); h.requests.push({ path, options, ...request }); return request.promise; };
  h.nodes = selector => h.root.querySelectorAll(selector);
  h.find = selector => h.root.querySelector(selector);
  h.importer = () => h.context.mountGraphSnapshotImport(h.root, { api: h.api, isCurrent: () => h.current });
  h.exporter = (overrides = {}) => h.context.mountGraphSnapshotExport(h.root, { api: h.api, course: { id: "course/one", revision: 7 }, scope: new URLSearchParams("q=++SCALE+++scale++&source_kind=material&source_id=&start=0&end=12.5"), isCurrent: () => h.current, ...overrides });
  h.select = async (value, { file, size } = {}) => {
    const input = h.find("[data-graph-snapshot-file]");
    const text = JSON.stringify(value);
    input.files = file ? [file] : [{ size: size ?? new Blob([text]).size, text: async () => text }];
    return input.listeners.change();
  };
  h.accept = async (value = snapshot(), previewGraph = value.graph) => {
    const work = h.select(value); await flush();
    h.requests.at(-1).resolve({ snapshot: value, graph: previewGraph, read_only: true }); await work;
    return value;
  };
  h.integrateCourses = () => {
    h.allowMarkup = true;
    h.context.request = h.api;
    h.context.dialog = h.root;
    h.context.window = {};
    h.context.esc = value => String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
    const requestAndShow = tools.slice(tools.indexOf("  async function api(path, options)"), tools.indexOf("  function status(text)"));
    const courseEntry = tools.slice(tools.indexOf("  async function listCourses()"), tools.indexOf("  function courseEditor()"));
    vm.runInContext(`let generation = 0, backAction = null, courses = []; const state = { selected: null }; const $ = id => document.getElementById(id); ${requestAndShow} ${courseEntry}`, h.context);
  };
  h.status = () => h.nodes('[role="status"]').map(node => node.textContent).join("\n");
  return h;
}

test("exports capture exact submitted query, every filter and revision; repeated clicks and downloads stay safe", async () => {
  const h = harness(), scope = new URLSearchParams("q=++SCALE+++scale++&source_kind=material&source_id=source%2F1&start=0&end=12.5"), course = { id: "course/one", revision: 7 };
  h.exporter({ scope, course });
  scope.set("q", "new unsent query"); course.revision = 99;
  const button = h.find("[data-graph-snapshot-export]"), first = button.listeners.click();
  await button.listeners.click(); assert.equal(h.requests.length, 1);
  const url = new URL(h.requests[0].path, "http://configured-backend.invalid:9123");
  assert.equal(url.pathname, "/api/courses/course%2Fone/graph-snapshot");
  assert.deepEqual(Object.fromEntries(url.searchParams), { q: "  SCALE   scale  ", source_kind: "material", source_id: "source/1", start: "0", end: "12.5", revision: "7" });
  const value = snapshot(); h.requests[0].resolve(value); await first;
  assert.deepEqual(JSON.parse(await h.blobs[0].text()), value);
  assert.equal(button.disabled, false); assert.equal(h.downloads[0].name, "learnnote-filtered-comparison.json");
  const repeat = button.click(); h.requests[1].resolve(value); await repeat;
  assert.equal(h.requests[1].path, h.requests[0].path);
  assert.equal(await h.blobs[1].text(), await h.blobs[0].text());
  assert.deepEqual(h.revoked, ["blob:1", "blob:2"]);
});

test("export failures are readable, limits do not download partial snapshots, and retry is allowed", async () => {
  const h = harness(); h.exporter(); const button = h.find("[data-graph-snapshot-export]");
  const work = button.click(); h.requests[0].reject(Object.assign(new Error("opaque limit"), { code: "graph_snapshot_too_large" })); await work;
  assert.match(h.status(), /20 MB.*10,000.*200.*20,000.*缩小/); assert.equal(h.downloads.length, 0);
  const retry = button.click(); h.requests[1].reject(new Error("课程已变化，请重新查找。")); await retry;
  assert.match(h.status(), /重新查找/); assert.equal(button.disabled, false);
});

for (const detach of [false, true]) for (const reject of [false, true]) test(`late export does nothing after ${detach ? "replacement" : "close/navigation"}, reject=${reject}`, async () => {
  const h = harness(); h.exporter(); const work = h.find("[data-graph-snapshot-export]").click(), oldStatus = h.nodes('[role="status"]')[0];
  if (detach) h.root.replaceChildren(); else h.current = false;
  oldStatus.textContent = "Newer view";
  if (reject) h.requests[0].reject(new Error("Late error")); else h.requests[0].resolve(snapshot());
  await work; assert.equal(h.downloads.length, 0); assert.equal(oldStatus.textContent, "Newer view");
});

test("import validates independently, renders hostile full text literally, and citations only open embedded evidence", async () => {
  const h = harness(); h.importer(); assert.equal(h.requests.length, 0, "No course/catalog query is needed");
  const value = await h.accept();
  assert.equal(h.requests[0].path, "/api/courses/graph-snapshot/preview");
  assert.equal(h.requests[0].options.method, "POST");
  assert.deepEqual(JSON.parse(h.requests[0].options.body), { snapshot: value });
  assert.match(h.root.textContent, /未验证来源真实性/);
  assert.match(h.root.textContent, /1 条出处 · 1 条缺失或变化/);
  assert.match(h.root.textContent, /缺失 · 1 条出处缺失/);
  assert.match(h.root.textContent, /scale · missing · 原文缺失/);
  assert.match(h.root.textContent, /scale · stale · 原文已变化/);
  assert(h.nodes("pre").some(node => node.textContent.includes('"start": 0') && node.textContent.includes('"end": 12') && node.textContent.includes('"redacted_fields"') && node.textContent.includes('"source_uri"')));
  assert(h.nodes("pre").some(node => node.textContent === value.evidence[0].text));
  assert(h.nodes("span").some(node => node.textContent === value.scope.query));
  assert(h.nodes("pre").some(node => node.textContent.includes(value.history.events[0].label)));
  assert.equal(h.nodes("img").length, 0); assert.equal(h.nodes("a").length, 0);
  assert.equal(h.nodes("[data-evidence]").length, 0); assert.equal(h.nodes("[data-concept-action]").length, 0);
  const evidence = h.find('[data-snapshot-evidence="one"]');
  await h.find('[data-snapshot-citation="one"]').click();
  assert.equal(evidence.open, true); assert.equal(h.scrolled[0], evidence); assert.equal(h.requests.length, 1);
  const reexport = h.find("[data-graph-snapshot-reexport]");
  await reexport.click(); await reexport.click();
  assert.deepEqual(JSON.parse(await h.blobs[0].text()), value); assert.equal(await h.blobs[0].text(), await h.blobs[1].text());
  assert.equal(h.requests.length, 1, "Import/citations/reexport never mutate or fetch live records");
});

test("preview uses recomputed graph and preserves validated original for reexport", async () => {
  const h = harness(); h.importer(); const value = snapshot(), rebuilt = graph(); rebuilt.edges = [];
  rebuilt.counts.edges = 0;
  await h.accept(value, rebuilt);
  assert.match(h.root.textContent, /关系列表显示 0\/0/);
  await h.find("[data-graph-snapshot-reexport]").click();
  assert.equal(JSON.parse(await h.blobs[0].text()).graph.edges.length, 1);
});

test("file cancellation preserves the preview and choosing the same file validates again", async () => {
  const h = harness(); h.importer(); await h.accept(); const original = h.find("[data-graph-snapshot-preview]"), input = h.find("[data-graph-snapshot-file]");
  input.files = []; await input.listeners.change();
  assert.equal(h.find("[data-graph-snapshot-preview]"), original); assert.equal(h.requests.length, 1);
  assert.equal(input.value, ""); await h.accept(); assert.equal(h.requests.length, 2);
  assert.equal(original.isConnected, false);
});

test("newer file selection supersedes stale validation responses and stale file reads", async () => {
  for (const reject of [false, true]) {
    const h = harness(); h.importer(); const stale = h.select(snapshot()); await flush();
    const newer = snapshot(); newer.course.title = "Newest file"; await h.accept(newer);
    if (reject) h.requests[0].reject(new Error("Late invalid file")); else h.requests[0].resolve({ snapshot: snapshot(), graph: graph(), read_only: true });
    await stale; assert.match(h.root.textContent, /Newest file/); assert.doesNotMatch(h.status(), /Late/);
  }
  const h = harness(); h.importer(); const read = deferred();
  const stale = h.select(null, { file: { size: 1, text: () => read.promise } });
  await h.accept(); read.resolve(JSON.stringify(snapshot())); await stale;
  assert.equal(h.requests.length, 1, "Superseded files never reach validation");
});

for (const detach of [false, true]) for (const reject of [false, true]) test(`import ignores late validation after ${detach ? "detachment" : "close/navigation"}, reject=${reject}`, async () => {
  const h = harness(); h.importer(); const work = h.select(snapshot()); await flush(); const oldStatus = h.nodes('[role="status"]')[0];
  if (detach) h.root.replaceChildren(); else h.current = false;
  oldStatus.textContent = "Newer page";
  if (reject) h.requests[0].reject(new Error("Late failure")); else h.requests[0].resolve({ snapshot: snapshot(), graph: graph(), read_only: true });
  await work; assert.equal(h.find("[data-graph-snapshot-preview]"), null); assert.equal(oldStatus.textContent, "Newer page");
});

test("invalid JSON, oversized bytes and failed digest validation clear stale previews without writes", async () => {
  const h = harness(); h.importer(); await h.accept();
  await h.select(null, { file: { size: 20_000_001, text: async () => { throw new Error("Should not read large file"); } } });
  assert.equal(h.requests.length, 1); assert.match(h.status(), /缩小/); assert.equal(h.find("[data-graph-snapshot-preview]"), null);
  await h.select(null, { file: { size: 1, text: async () => "{" } }); assert.match(h.status(), /有效的 JSON/);
  await h.select(null, { file: { size: 1, text: async () => "界".repeat(6_666_667) } });
  assert.equal(h.requests.length, 1); assert.match(h.status(), /20 MB/, "Measure encoded bytes, not JS characters");
  const invalid = h.select(snapshot()); await flush(); h.requests[1].reject(new Error("快照摘要不匹配，文件可能已损坏。")); await invalid;
  assert.match(h.status(), /摘要不匹配/); assert.equal(h.find("[data-graph-snapshot-reexport]"), null);
  const malformedResponse = h.select(snapshot()); await flush(); h.requests[2].resolve({ snapshot: snapshot(), graph: graph(), read_only: false }); await malformedResponse;
  assert.match(h.status(), /有效的只读/);
});

test("import preserves duplicate JSON keys for strict server rejection", async () => {
  const h = harness(); h.importer();
  const raw = '{"format":"hostile.first.value",' + JSON.stringify(snapshot()).slice(1);
  const work = h.select(null, { file: { size: new Blob([raw]).size, text: async () => raw } });
  await flush();
  assert.equal(h.requests[0].options.body, '{"snapshot":' + raw + '}');
  assert.equal((h.requests[0].options.body.match(/"format":/g) || []).length, 2, "Conflicting keys must not be erased by JSON.stringify");
  h.requests[0].reject(new Error("快照格式包含重复字段，未打开。"));
  await work;
  assert.match(h.status(), /重复字段/);
  assert.equal(h.find("[data-graph-snapshot-preview]"), null);
});

test("old embedded citations and reexport controls cannot act after navigation or replacement", async () => {
  const h = harness(); h.importer(); await h.accept();
  const button = h.find("[data-graph-snapshot-reexport]"), citation = h.find('[data-snapshot-citation="one"]');
  const newer = h.select(snapshot()); await flush();
  await button.listeners.click(); await citation.listeners.click();
  assert.equal(h.downloads.length, 0); assert.equal(h.scrolled.length, 0);
  h.current = false; h.requests[1].resolve({ snapshot: snapshot(), graph: graph(), read_only: true }); await newer;
  assert.equal(h.find("[data-graph-snapshot-preview]"), null);
});

test("returned graph limits and visual layout caps are disclosed and complete snapshot relations paginate", async () => {
  const h = harness(), partial = graph(); partial.counts = { matches: 1000, nodes: 80, edges: 200 };
  partial.truncated = { matches: true, nodes: true, edges: true }; partial.query_terms_truncated = true;
  h.context.mountGraphCompleteness(h.root, partial);
  assert.equal(h.find("[data-graph-completeness]").dataset.graphCompleteness, "truncated");
  assert.match(h.root.textContent, /出处 2\/1000、来源 2\/80、关系 1\/200/);
  assert.match(h.root.textContent, /已截断/);
  assert.match(h.root.textContent, /只使用前 8 个不同关键词/);
  const value = snapshot(); value.graph.nodes = Array.from({ length: 30 }, (_, index) => ({ id: `n${index}`, title: `Source ${index}`, evidence_ids: [] }));
  value.graph.edges = Array.from({ length: 150 }, () => ({ ...graph().edges[0], from: "n0", to: "n1" }));
  value.graph.counts = { matches: 2, nodes: 30, edges: 150 };
  h.root.replaceChildren(); h.importer(); await h.accept(value);
  assert.match(h.root.textContent, /图形显示 24\/30/);
  assert.match(h.root.textContent, /关系列表显示 100\/150/);
  await h.nodes("button").find(node => node.textContent === "显示接下来的 100 条关系").click();
  assert.match(h.root.textContent, /关系列表显示 150\/150/);
  await h.find("[data-graph-snapshot-reexport]").click(); assert.equal(JSON.parse(await h.blobs[0].text()).graph.edges.length, 150);
});


test("course entry keeps import available through empty or failed catalog loading", async () => {
  for (const failed of [false, true]) {
    const h = harness(); h.integrateCourses();
    const work = h.context.listCourses();
    const entry = h.find("[data-graph-snapshot-import]");
    assert(entry?.isConnected, "The import entry precedes the catalog response");
    assert.equal(entry.dataset.action, "graph-snapshot");
    if (failed) { h.requests[0].reject(new Error("Unreadable live catalog")); await assert.rejects(work, /Unreadable/); }
    else { h.requests[0].resolve({ courses: [] }); await work; assert.match(h.root.textContent, /还没有课程/); }
    assert.equal(h.find("[data-graph-snapshot-import]"), entry);
    h.context.graphSnapshot();
    assert(h.find("[data-graph-snapshot-file]"));
    assert.equal(h.requests.length, 1, "Opening the importer makes no live requests");
    await h.accept();
    assert(h.find("[data-graph-snapshot-preview]"));
    assert.equal(h.requests[1].path, "/api/courses/graph-snapshot/preview");
  }
});

test("late catalog response cannot replace a snapshot preview opened while catalog loads", async () => {
  const h = harness(); h.integrateCourses();
  const list = h.context.listCourses(); h.context.graphSnapshot();
  await h.accept(); const preview = h.find("[data-graph-snapshot-preview]");
  h.requests[0].resolve({ courses: [{ id: "live", title: "Old catalog" }] });
  await assert.rejects(list, /已离开/);
  assert.equal(h.find("[data-graph-snapshot-preview]"), preview);
  assert.doesNotMatch(h.root.textContent, /Old catalog/);
  h.root.close(); const old = h.downloads.length;
  await h.find("[data-graph-snapshot-reexport]").click();
  assert.equal(h.downloads.length, old, "Closed tools cannot reexport");
});
