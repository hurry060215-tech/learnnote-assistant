import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(new URL("../course-concepts.js", import.meta.url), "utf8");
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
function harness(literal) {
  class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.listeners = {}; this.dataset = {}; this.style = {}; this.value = ""; this.checked = false; this.isConnected = true; }
    append(...items) { this.children.push(...items); items.forEach(item => { item.parentElement = this; }); }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    setAttribute(key, value) { this[key] = value; }
    getAttribute(key) { return this[key] ?? null; }
    closest(selector) { return selector.includes("[data-user-content]") && this.dataset.userContent ? this : this.parentElement?.closest(selector); }
    click() { h.downloads.push({ href: this.href, download: this.download }); }
    querySelectorAll(tag) { return this.children.flatMap(child => [ ...(child.tag === tag || tag === "*" ? [child] : []), ...child.querySelectorAll(tag) ]); }
  }
  const h = { current: true, requests: [], reloads: 0, opened: [], downloads: [], blobs: [], revoked: [], root: new Element("main") };
  const document = { createElement: tag => new Element(tag), createTextNode: text => Object.assign(new Element("#text"), { textContent: text }) };
  const context = vm.createContext({ document, crypto: { randomUUID: () => "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" }, Blob,
    URL: { createObjectURL: blob => { h.blobs.push(blob); return "blob:local-history"; }, revokeObjectURL: url => h.revoked.push(url) }, setTimeout: callback => callback() });
  vm.runInContext(source.replaceAll("export function", "function"), context);
  const result = { identity_revision: 3, matches: [{ evidence_id: "a", title: literal ?? "Music <original>", locator: "12-18s" }, { evidence_id: "b", title: "Weight", locator: "page 2" }],
    concepts: [{ term: literal ?? "scale", scope_revision: "f".repeat(64), groups: [
      { id: "unassigned", label: "未区分含义", evidence_ids: ["a"], unresolved_ids: [] },
      { id: "second", label: literal ?? "Measurement", evidence_ids: ["b", "outside-current-filter"], unresolved_ids: ["missing-original"] },
    ] }] };
  context.mountConceptControls(h.root, result, { course: { id: "course/one", revision: 7 }, isCurrent: () => h.current,
    api: (path, options) => { const work = deferred(); h.requests.push({ path, configuredUrl: "http://configured-backend.invalid:9123" + path, options, work }); return work.promise; },
    reload: async () => { h.reloads++; }, openEvidence: async id => { h.opened.push(id); },
  });
  h.nodes = tag => h.root.querySelectorAll(tag);
  h.input = id => h.nodes("input").find(node => node.dataset.conceptEvidence === id);
  h.name = h.nodes("input").find(node => node.id === "conceptGroupLabel0");
  h.message = h.nodes("p").find(node => node.role === "status");
  h.action = action => h.nodes("button").find(node => node.dataset.conceptAction === action).listeners.click();
  h.presentation = context.relationPresentation;
  return h;
}

{
  const h = harness();
  await h.action("split");
  assert.equal(h.requests.length, 0);
  assert.match(h.message.textContent, /选择出处/);
  assert.match(h.nodes("p").find(node => node.dataset.conceptUnresolved).children[0].textContent, /保留旧分组/);
  assert(h.nodes("span").some(node => node.textContent === "Music <original> · 12-18s"));
  await h.nodes("button").find(node => node.textContent === "核对出处").listeners.click();
  assert.deepEqual(h.opened, ["a"]);
  assert.match(h.presentation({ kind: "keyword_cooccurrence" }).label, /不代表同义、因果或共识/);
  assert.notEqual(h.presentation({ kind: "inferred" }).dash, h.presentation({ kind: "keyword_cooccurrence" }).dash);
  assert.match(h.presentation({ kind: "made_up_fact" }).label, /未识别/);
}
{
  const literal = "\r\n  完成后打开笔记 cafe\u0301 🧭\r\n", h = harness(literal);
  const content = h.nodes("span").filter(node => node.textContent.includes("完成后打开笔记"));
  assert.equal(content.length, 3, "Search term, source title and exact user group label have literal-content spans");
  const nodes = content.map(parentElement => ({ nodeValue: parentElement.textContent, parentElement }));
  const normal = { nodeValue: "打开笔记", parentElement: h.nodes("button")[0] };
  const context = {};
  vm.runInNewContext(readFileSync(new URL("../i18n.js", import.meta.url), "utf8"), context);
  const document = { body: {}, querySelectorAll: () => [{ contains: () => true }],
    createTreeWalker: () => { const iterator = [...nodes, normal][Symbol.iterator](); return { nextNode: () => iterator.next().value ?? null }; } };
  for (const locale of ["en-US", "zh-CN", "en-US"]) {
    context.LearnNoteI18n.applyStatic(document, locale);
    for (let index = 0; index < nodes.length; index++) assert.equal(nodes[index].nodeValue, content[index].textContent);
    assert.equal(normal.nodeValue, locale === "en-US" ? "Open note" : "打开笔记");
  }
}
{
  const h = harness(); h.name.value = "  My label 原文  "; h.input("a").checked = true;
  const first = h.action("split"); await h.action("split");
  assert.equal(h.requests.length, 1, "Repeated clicks do not submit twice");
  const request = h.requests[0], payload = JSON.parse(request.options.body);
  assert.equal(request.path, "/api/courses/course%2Fone/concepts");
  assert.deepEqual(payload.evidence_ids, ["a"]);
  assert.equal(payload.label, "  My label 原文  ");
  assert.equal(payload.course_revision, 7);
  assert.equal(payload.revision, 3);
  request.work.reject(new Error("Connection interrupted")); await first;
  assert.equal(h.reloads, 0);
  const retry = h.action("split");
  assert.equal(h.requests[1].options.body, request.options.body, "Uncertain retry preserves idempotency key");
  h.requests[1].work.resolve({ replayed: true }); await retry;
  assert.equal(h.reloads, 1);
}
{
  const h = harness(); h.name.value = "Organize together";
  h.nodes("input").filter(node => node.dataset.conceptGroup).forEach(node => { node.checked = true; });
  const work = h.action("merge");
  const payload = JSON.parse(h.requests[0].options.body);
  assert.deepEqual(payload.group_ids, ["unassigned", "second"]);
  assert.deepEqual(payload.evidence_ids, [], "Server resolves group scope, including hidden and unresolved references");
  h.requests[0].work.reject(new Error("Unresolved original must be checked")); await work;
  assert.equal(h.reloads, 0);
  assert.match(h.message.textContent, /Unresolved/);
}
for (const detach of [false, true]) {
  for (const reject of [false, true]) {
    const h = harness(); h.name.value = "Music"; h.input("a").checked = true;
    const work = h.action("split");
    if (detach) h.root.children[0].isConnected = false;
    else h.current = false;
    h.message.textContent = "Newer view";
    if (reject) h.requests[0].work.reject(new Error("late failure"));
    else h.requests[0].work.resolve({ revision: 4 });
    await work;
    assert.equal(h.reloads, 0, "Close, newer navigation, and replacement comparison stay intact");
    assert.equal(h.message.textContent, "Newer view");
  }
}
{
  const h = harness(); h.name.value = "Keep my unsaved selection";
  const work = h.nodes("button").find(node => node.dataset.conceptBackup).listeners.click();
  assert.equal(h.requests[0].configuredUrl, "http://configured-backend.invalid:9123/api/courses/course%2Fone/concepts/backup");
  assert.equal(h.downloads.length, 0);
  const history = { schema_version: 1, course_id: "course/one", events: [{ label: "  原文 preserved  " }] };
  h.requests[0].work.resolve(history); await work;
  assert.equal(h.reloads, 0, "Export leaves unsaved controls intact");
  assert.equal(h.name.value, "Keep my unsaved selection");
  assert.deepEqual(JSON.parse(await h.blobs[0].text()), history);
  assert.deepEqual(h.downloads, [{ href: "blob:local-history", download: "concept-groups-course/one.json" }]);
  assert.deepEqual(h.revoked, ["blob:local-history"]);
}
{
  const h = harness(), file = h.nodes("input").find(node => node.dataset.conceptRestore);
  file.files = [{ size: 20_000_001, text: async () => { throw new Error("Must not read an oversized file"); } }];
  await file.listeners.change(); assert.equal(h.requests.length, 0); assert.match(h.message.textContent, /20 MB/);
  const backup = { schema_version: 1, course_id: "course/one", events: [] };
  file.files = [{ size: 90, text: async () => JSON.stringify(backup) }];
  const work = file.listeners.change(); await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(JSON.parse(h.requests[0].options.body), { revision: 3, backup });
  h.requests[0].work.resolve({ restored: 0 }); await work;
  assert.equal(h.reloads, 1);
}
console.log("Course concept controls: canonical selections, grouping, retry, stale views, truthful kinds and restore passed");
