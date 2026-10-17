import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import {
  baseline, functionNames, providerFiles, adapterNames, functionSource, createAdapters, project
} from "./helpers/visual-study-contract.mjs";

const readSource = name => readFileSync(new URL(`../${name}`, import.meta.url), "utf8");
const moduleSource = readSource("visual-study.js");
const app = readSource("app.js");
const snapshot = JSON.parse(readFileSync(new URL("./fixtures/visual-study-d2b4ef0.json", import.meta.url), "utf8"));
assert.equal(snapshot.baseline, baseline);
for (const name of functionNames) {
  const digest = createHash("sha256").update(functionSource(moduleSource, name)).digest("hex");
  assert.equal(digest, snapshot.function_sha256[name], `${name} must retain its exact original body`);
  assert(!app.includes(`function ${name}(`), `${name} no longer belongs to app orchestration`);
}

const context = vm.createContext({ URL });
for (const key of ["document", "window", "location", "localStorage", "fetch", "chrome", "navigator", "setTimeout", "setInterval"]) {
  Object.defineProperty(context, key, { get() { throw Error(`Renderer touched ambient ${key}`); } });
}
for (const file of providerFiles) vm.runInContext(readSource(file), context);
vm.runInContext(moduleSource, context);
assert(Object.isFrozen(context.LearnNoteVisualStudy));
assert.deepEqual(Object.keys(context.LearnNoteVisualStudy), ["createVisualStudyRenderer"]);
const create = context.LearnNoteVisualStudy.createVisualStudyRenderer;
const normalize = value => JSON.parse(JSON.stringify(value));
function deepFreeze(value) {
  if (value && typeof value === "object" && !Object.isFrozen(value)) {
    Object.values(value).forEach(deepFreeze);
    Object.freeze(value);
  }
  return value;
}
for (const row of snapshot.cases) {
  const original = JSON.stringify(row.task) + JSON.stringify(row.transcript);
  deepFreeze(row.task); deepFreeze(row.transcript);
  const { ports } = createAdapters(app, readSource, row.runtime);
  const calls = [];
  const domain = create(Object.fromEntries(adapterNames.map(name => [name, (...args) => {
    calls.push(name);
    return ports[name](...args);
  }])));
  assert.deepEqual(calls, [], "Constructing the renderer must not call policy adapters");
  assert(Object.isFrozen(domain));
  assert.deepEqual(Object.keys(domain).sort(), [...functionNames].sort());
  assert.deepEqual(normalize(project(domain, context.LearnNoteTaskList, row)), row.expected, row.name);
  assert.deepEqual(normalize(project(domain, context.LearnNoteTaskList, row)), row.expected, `${row.name}: repeated rendering`);
  assert.equal(JSON.stringify(row.task) + JSON.stringify(row.transcript), original, `${row.name}: unchanged inputs`);
  const windows = context.LearnNoteTaskList.visualWindows(row.task);
  windows.forEach((window, index) => {
    assert.equal(domain.visualWindowReviewItem(row.task, window, index, row.transcript).window, window,
      "Review projection retains the original window reference");
  });
}

const example = snapshot.cases.find(row => row.name === "hostile-and-unicode");
const adapters = createAdapters(app, readSource);
const live = create(adapters.ports);
const initial = live.visualStudyHandoutHtml(example.task, example.transcript);
assert(initial.includes("127.0.0.1:8766"));
assert(!initial.includes("<script>"));
assert(!initial.includes("<svg"));
assert(initial.includes("&amp;amp;"), "Existing additional href escaping is byte-compatible");
adapters.context.API = "http://127.0.0.1:9400";
const changed = live.visualStudyHandoutHtml(example.task, example.transcript);
assert(changed.includes("127.0.0.1:9400"));
assert(!changed.includes("127.0.0.1:8766"), "Origin must resolve at render time, not construction time");
adapters.context.LearnNoteTaskLinks = {
  exportUrl: (apiUrl, task, type) => apiUrl(`/updated/${encodeURIComponent(task.id)}/${type}`),
  clipExportUrl: (apiUrl, task, id) => apiUrl(`/updated-clips/${encodeURIComponent(id)}`)
};
const lateLinks = live.visualStudyDeck(example.task, example.transcript);
assert(lateLinks.includes("127.0.0.1:9400/updated/"));
assert(lateLinks.includes("127.0.0.1:9400/updated-clips/"));
assert.equal(live.visualStudyDeck({}, null), "", "New task must not retain previous windows");
assert.equal(live.visualStudyHandoutHtml(example.task, example.transcript), changed,
  "Repeated navigation does not retain task or transcript state");

// Verify the real app entry binds the four existing functions without invoking
// any callback or rewiring lifecycle work. The full markdown harness also loads
// this module and executes the unmodified app initialization and event handlers.
const wiring = app.slice(0, app.indexOf("\n\n"));
const wired = vm.createContext({ LearnNoteVisualStudy: context.LearnNoteVisualStudy, ...adapters.ports });
vm.runInContext(wiring, wired);
assert.equal(wired.visualStudyDeck(example.task, example.transcript), lateLinks);
let diagnosticVisible = false;
const explicitPolicy = create({ ...adapters.ports, hasTaskDiagnostics: () => diagnosticVisible });
assert(!explicitPolicy.visualStudyOverviewHtml(example.task).includes('data-switch-result-tab="diagnostics"'));
diagnosticVisible = true;
assert(explicitPolicy.visualStudyOverviewHtml(example.task).includes('data-switch-result-tab="diagnostics"'));
const sentinel = new Error("policy failure");
const failing = create({ ...adapters.ports, safeNoteMediaUrl() { throw sentinel; } });
assert.throws(() => failing.visualWindowEvidenceState({}, {}), error => error === sentinel);
assert.equal(failing.visualStudyDeck({}), "", "Empty input must not call an irrelevant failing policy");

const classic = readSource("classic.html");
const scripts = [...classic.matchAll(/<script\b[^>]*src="([^"?]+)(?:\?v=([^"]+))?"/g)];
const position = name => scripts.findIndex(match => match[1] === `/web/${name}`);
assert.equal(scripts.filter(match => match[1] === "/web/visual-study.js").length, 1);
for (const name of providerFiles) assert(position(name) < position("visual-study.js"), name);
assert(position("visual-study.js") < position("app.js"));
assert.equal(scripts[position("visual-study.js")][2], "20261017-visual-study");
assert.equal(scripts[position("app.js")][2], "20261017-visual-study");
assert(!readSource("index.html").includes("visual-study.js"), "Classic renderer stays outside the native reader entry");
console.log(`Visual study: ${snapshot.cases.length} frozen original cases, exact bodies, immutable inputs, live adapters and load order pass`);
