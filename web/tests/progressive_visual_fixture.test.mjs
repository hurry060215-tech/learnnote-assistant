import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";
import { readFileSync } from "node:fs";
import fixture from "../../scripts/progressive-visual-api-acceptance.cjs";
const { visualEventDetail, visualEventMatches, retainedViewport, inspectVisibleBatch, rememberVisibleBatch } = fixture;
const hash = letter => letter.repeat(64);
const details = () => ({ schema_version: 1, kind: "vision_batch", verified: false, section_id: "vision-" + "a".repeat(24), revision: hash("a"), section_count: 2 });
const event = value => ({ requestId: "native-request", eventId: "27", eventName: "partial_section_ready", data: JSON.stringify({ details: value }) });

test("native visual detail keeps only bounded unverified provenance", () => {
  const value = visualEventDetail(event({ ...details(), prompt: "private unused field" }));
  assert.deepEqual(Object.keys(value).sort(), ["id", "request_id", "revision", "section_count", "section_id", "verified"]);
  assert.equal(visualEventDetail({ eventName: "task_updated" }), null);
  for (const patch of [{ verified: true }, { kind: "topic_chapter" }, { schema_version: 2 }, { revision: "old" },
    { section_id: "<script>" }, { section_count: 0 }, { section_count: 81 }, { section_count: 1.5 }])
    assert.throws(() => visualEventDetail(event({ ...details(), ...patch })));
  assert.throws(() => visualEventDetail({ ...event(details()), data: "bad JSON" }));
});

test("a native event must bind task, request, section, persisted revision and current projection", () => {
  const detail = visualEventDetail(event(details()));
  const native = { request_id: detail.request_id, id: detail.id, task_id: "owned", event: "partial_section_ready" };
  const projection = { task_id: "owned", attempt_id: "current", source_revision: hash("b"), generation_revision: hash("c"),
    revision: hash("d"), verified: false, sections: [{ id: detail.section_id, kind: "vision_batch" }] };
  const persisted = { ...projection, revision: detail.revision, projection_revision: projection.revision, section_ids: [detail.section_id, "other"] };
  assert(visualEventMatches(detail, native, projection, persisted));
  for (const patch of [{ task_id: "other" }, { request_id: "obsolete" }, { id: "26" }, { event: "task_updated" }])
    assert.equal(visualEventMatches(detail, { ...native, ...patch }, projection, persisted), false);
  for (const patch of [{ attempt_id: "previous" }, { source_revision: hash("e") }, { generation_revision: hash("f") },
    { projection_revision: hash("e") }, { revision: hash("b") }, { verified: true }, { section_ids: [] }])
    assert.equal(visualEventMatches(detail, native, projection, { ...persisted, ...patch }), false);
});

function dom() {
  let top = 300, prose = "Readable deterministic unverified source draft.";
  const selected = { toString: () => prose, anchorNode: {}, focusNode: {}, anchorOffset: 0, focusOffset: 42 }, ancestor = { opacity: "1", parentElement: null };
  const node = { isConnected: true, parentElement: ancestor, innerText: prose, contains: child => child === selected.anchorNode,
    getBoundingClientRect: () => ({ top, bottom: top + 60, left: 200, right: 700 }) };
  const batch = { isConnected: true, dataset: { readerBatch: details().section_id }, querySelectorAll: () => [node] };
  ancestor.parentElement = batch;
  const chapter = { isConnected: true, contains: item => item === batch };
  const reader = { dataset: { readerSource: "task:owned", readerRevision: "new" }, contains: item => item === chapter };
  const context = vm.createContext({ location: { hash: "#task/owned" }, innerWidth: 1440, innerHeight: 1000, document: { getElementById: () => reader,
    getSelection: () => selected, elementFromPoint: () => node }, getComputedStyle: item => ({ display: "block", visibility: "visible", opacity: item.opacity || "1" }),
    visualReadingAnchor: { paragraph: node, body: ancestor, batch, chapter, source: "task:owned", route: "#task/owned", prose, selection: prose, anchor_node: selected.anchorNode, focus_node: selected.focusNode, anchor_offset: 0, focus_offset: 42, top: 300 } });
  return { read: () => vm.runInContext(`(${inspectVisibleBatch.toString()})()`, context), node, batch, chapter, reader, selected, ancestor, setTop: value => { top = value; } };
}

test("actual observation rejects changed nodes, source, selection, prose and hidden ancestors", () => {
  for (const mutate of [h => { h.batch.isConnected = false; }, h => { h.chapter.isConnected = false; },
    h => { h.node.isConnected = false; }, h => { h.node.parentElement = {}; }, h => { h.ancestor.parentElement = {}; }, h => { h.reader.dataset.readerSource = "task:other"; },
    h => { h.selected.toString = () => "lost"; }, h => { h.selected.anchorNode = {}; },
    h => { h.selected.focusNode = {}; }, h => { h.selected.anchorOffset = 1; }, h => { h.selected.focusOffset = 41; }, h => { h.node.innerText = "replaced"; }, h => { h.ancestor.opacity = "0"; }]) {
    const h = dom(); assert(retainedViewport(h.read())); mutate(h); assert.equal(retainedViewport(h.read()), false);
  }
});

test("strict viewport rejects jumps, offscreen source and malformed geometry", () => {
  for (const position of [-1, 303, 990]) { const h = dom(); h.setTop(position); assert.equal(retainedViewport(h.read()), false); }
  const h = dom(), good = h.read();
  for (const patch of [{ top: NaN }, { bottom: Infinity }, { right: 1500 }, { left: -1 }, { unobscured: false }, { viewport: { width: Infinity, height: 1000 } }])
    assert.equal(retainedViewport({ ...good, ...patch }), false);
});

const expectedProse = "Reference paragraph 1: This deterministic response describes the supplied synthetic image and caption window. It is an unverified draft, retained only for this bounded continuation test.";
function bodyAnchorDom() {
  const calls = [], range = {}, chapter = { isConnected: true }, body = {}, badge = { innerText: "图文草稿 · 证据补充中 · 未完成最终校验" };
  badge.scrollIntoView = options => calls.push(options); badge.getBoundingClientRect = () => ({ top: 200 });
  const paragraph = { innerText: expectedProse, isConnected: true, parentElement: body,
    scrollIntoView: options => calls.push(options), getBoundingClientRect: () => ({ top: 200 }) };
  const element = { isConnected: true, dataset: { readerBatch: details().section_id },
    // The unscoped descendant selector also matches the direct badge through an outer div.
    querySelector: selector => selector === "div p" ? badge : null,
    querySelectorAll: selector => { assert.equal(selector, ":scope > div > p"); return body.paragraphs; }, closest: () => chapter };
  body.parentElement = element; body.paragraphs = [paragraph];
  chapter.contains = node => node === element;
  const reader = { dataset: { readerSource: "task:owned" }, contains: node => node === element || node === chapter };
  const selection = { removeAllRanges() {}, addRange: value => assert.equal(value, range), toString: () => selection.anchorNode.innerText };
  range.selectNodeContents = node => { selection.anchorNode = node; selection.focusNode = node; selection.anchorOffset = 0; selection.focusOffset = 1; };
  const context = vm.createContext({ location: { hash: "#task/owned" }, document: { getSelection: () => selection, createRange: () => range, getElementById: () => reader } });
  const options = { task_id: "owned", batch_id: details().section_id, text: expectedProse };
  return { calls, paragraph, badge, body, element, reader, context, options,
    remember: () => vm.runInContext(`(${rememberVisibleBatch.toString()})`, context)(element, options) };
}

test("reading anchor selects exact direct body prose rather than the outer-div warning badge", () => {
  const h = bodyAnchorDom(); assert.equal(fixture.visualProse, expectedProse); h.remember();
  assert.deepEqual(JSON.parse(JSON.stringify(h.calls)), [{ block: "center", behavior: "instant" }]);
  assert.equal(h.context.visualReadingAnchor.batch, h.element);
  assert.equal(h.context.visualReadingAnchor.paragraph, h.paragraph);
  assert.equal(h.context.visualReadingAnchor.prose, expectedProse);
  assert.notEqual(h.context.visualReadingAnchor.paragraph, h.badge);
});

test("wrong source, batch, missing, duplicate or replaced deterministic body fails before scrolling", () => {
  for (const mutate of [h => { h.reader.dataset.readerSource = "task:other"; },
    h => { h.context.location.hash = "#task/other"; }, h => { h.element.dataset.readerBatch = "old"; },
    h => { h.element.isConnected = false; }, h => { h.body.paragraphs = []; },
    h => { h.body.paragraphs = [h.paragraph, h.paragraph]; },
    h => { h.paragraph.innerText = h.badge.innerText; }]) {
    const h = bodyAnchorDom(); mutate(h); assert.throws(h.remember); assert.equal(h.calls.length, 0);
  }
});

function captionDom(changed = false) {
  const calls = [], text = (changed ? "Changed source: " : "") + fixture.captionText;
  const literal = { nodeType: 3, textContent: " " + text }, button = { nodeType: 1, textContent: "0:00–0:12" };
  const section = { dataset: { readerSection: "draft-time-0" } }, reader = { dataset: { readerSource: "task:owned", readerRevision: "current:transcript-draft:" }, contains: node => node === section };
  const rect = { top: 300, bottom: 340, left: 200, right: 700 };
  const node = { childNodes: [button, literal], innerText: button.textContent + " " + text,
    isConnected: true, parentElement: section, scrollIntoView: options => calls.push(options),
    getBoundingClientRect: () => rect, contains: hit => hit === button };
  section.parentElement = reader;
  section.querySelectorAll = selector => { assert.equal(selector, ":scope > ul > li"); return section.matches; };
  section.matches = [node];
  reader.querySelector = selector => { assert.equal(selector, '[data-reader-section="draft-time-0"]'); return section; };
  const context = vm.createContext({ location: { hash: "#task/owned" }, innerWidth: 1440, innerHeight: 1000,
    document: { getElementById: () => reader, elementFromPoint: () => node },
    getComputedStyle: item => ({ display: "block", visibility: "visible", opacity: item.opacity || "1" }) });
  const expected = { task_id: "owned", section_id: "draft-time-0", text };
  return { calls, literal, node, section, reader, rect, context, expected,
    capture: () => vm.runInContext(`(${fixture.captureReadableCaption.toString()})`, context)(expected) };
}

test("caption captures resolve the exact source excerpt and make a single visible placement", () => {
  for (const changed of [false, true]) {
    const h = captionDom(changed), value = h.capture();
    assert.equal(value.reader_source, "task:owned"); assert.equal(value.section_id, "draft-time-0");
    assert.equal(value.text, h.expected.text); assert(value.rendered_text.endsWith(h.expected.text));
    assert.deepEqual(JSON.parse(JSON.stringify(h.calls)), [{ block: "center", behavior: "instant" }]);
    assert.equal(value.top, 300); assert.equal(value.bottom, 340);
  }
});

test("caption capture rejects wrong source or prose, hidden, detached, obscured and offscreen content", () => {
  for (const mutate of [h => { h.context.location.hash = "#task/other"; }, h => { h.reader.dataset.readerSource = "task:other"; },
    h => { h.expected.section_id = 'bad"]'; }, h => { h.literal.textContent = "old source"; },
    h => { h.section.matches = []; }, h => { h.section.matches = [h.node, h.node]; },
    h => { h.node.isConnected = false; }, h => { h.section.opacity = "0"; },
    h => { h.context.document.elementFromPoint = () => ({}); }, h => { h.rect.top = -1; },
    h => { h.rect.bottom = 1001; }, h => { h.rect.right = 1500; }, h => { h.rect.left = NaN; }]) {
    const h = captionDom(); mutate(h); assert.throws(h.capture);
  }
});

test("body and caption contracts match production structure and deterministic fixture content", () => {
  const renderer = readFileSync(new URL("../reader-sections.js", import.meta.url), "utf8");
  const python = readFileSync(new URL("../../scripts/progressive-visual-fixture.py", import.meta.url), "utf8");
  assert.match(renderer, /const body = make\("div"\); renderMarkdown\(body, item.markdown\)/);
  assert.match(renderer, /node.append\(provenance, body\)/);
  assert.match(renderer, /li.append\(sourceButton\(excerpt.start, excerpt.end\), doc.createTextNode\(` \$\{excerpt.text\}`\)\)/);
  assert(python.includes(fixture.captionText));
  assert(python.includes(fixture.visualProse.replace("Reference paragraph 1:", "Reference paragraph {index}:").split("It is an unverified")[0]));
  assert(python.includes('"It is an unverified draft, retained only for this bounded continuation test."'));
  const script = readFileSync(new URL("../../scripts/progressive-visual-api-acceptance.cjs", import.meta.url), "utf8");
  assert(script.indexOf("report.caption_geometry =") < script.indexOf('await capture("caption-draft.png")'));
  assert(script.indexOf("releaseDelayed(); await until") < script.indexOf("report.changed_caption_geometry ="));
  assert(script.indexOf("report.changed_caption_geometry =") < script.indexOf('await capture("changed-source-rejects-delayed-old-draft.png")'));
  const comparison = script.slice(script.indexOf("report.before_insertion ="), script.indexOf("report.before_cancel ="));
  assert.doesNotMatch(comparison, /rememberVisibleBatch|captureReadableCaption|scrollIntoView/);
});

test("browser selectors and task navigation match the hydrated production home", () => {
  const script = readFileSync(new URL("../../scripts/progressive-visual-api-acceptance.cjs", import.meta.url), "utf8");
  const product = readFileSync(new URL("../desk-product.js", import.meta.url), "utf8");
  const workspace = readFileSync(new URL("../desk.js", import.meta.url), "utf8");
  assert.match(product, /const home = \$\("welcome"\)/);
  assert.match(workspace, /\$\("welcome"\)\.hidden = false/);
  assert.match(script, /document\.getElementById\("welcome"\)\.hidden/);
  assert.doesNotMatch(script, /#home|welcomeNew|Browser\.getBrowserCommandLine|page\.reload|\.fulfill\(\{[^}]*json:/);
  assert.doesNotMatch(script, /assert\([^\n]*Edg/, "Edge identity is the validated owned executable; generic headless UA is descriptive");
  assert.match(script, /route\.fulfill\(\{ response \}\)/, "only the actual fetched old response may be delayed");
  assert.match(script, /active_completions === 0 && current\.queue\?\.callback_finished/);
  assert(script.indexOf("await image.evaluate(node => node.scrollIntoView") < script.indexOf("node.complete && node.naturalWidth"), "Reveal lazy source image before waiting for its load");
});

test("owned process cleanup rejects unrelated launch identities before any signal", async () => {
  let written = false;
  await assert.rejects(fixture.stopOwnedFixture({ pid: 12345, exitCode: null, signalCode: null,
    spawnargs: ["unrelated"], stdin: { writable: true, write() { written = true; } } }, "fixture", "owned"), /exact owned/);
  assert.equal(written, false);
});

test("worker locations are collected only after failure and before owned cleanup", () => {
  const script = readFileSync(new URL("../../scripts/progressive-visual-api-acceptance.cjs", import.meta.url), "utf8");
  const start = script.indexOf("primaryError = error; report.failure");
  const end = script.indexOf("} finally { releaseDelayed?.();", start);
  const operation = 'fixture_threads: () => api("/_fixture/diagnostics")';
  assert(start >= 0 && end > start);
  assert.equal(script.split(operation).length - 1, 1);
  assert(script.slice(start, end).includes(operation));
  assert.match(script.slice(start, end), /await recordFailureDiagnostics/);
});

test("cooperative shutdown and bounded fallback both stop a real owned descendant", async () => {
  const fs = await import("node:fs"), os = await import("node:os"), path = await import("node:path"), { spawn } = await import("node:child_process");
  for (const cooperative of [true, false]) {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "visual-tree-contract-")), script = path.join(dir, "owned.cjs");
    fs.writeFileSync(script, `const {spawn}=require('node:child_process');
const worker=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:'ignore'});
console.log(JSON.stringify({worker:worker.pid})); process.stdin.resume();
${cooperative ? "process.stdin.on('data',()=>{worker.once('exit',()=>process.exit(0));worker.kill();});" : ""}`);
    const child = spawn(process.execPath, [script, "--data-dir", dir], { detached: process.platform !== "win32", stdio: ["pipe", "pipe", "pipe"] });
    let worker;
    try {
      worker = await new Promise((resolve, reject) => {
        let text = ""; const timer = setTimeout(() => reject(new Error("Owned worker did not start")), 5000);
        child.once("error", reject); child.stdout.on("data", chunk => { text += chunk; if (text.includes("\n")) { clearTimeout(timer); resolve(JSON.parse(text.trim()).worker); } });
      });
      await fixture.stopOwnedFixture(child, script, dir, 100);
      assert(child.exitCode !== null || child.signalCode !== null);
      let alive;
      try { process.kill(worker, 0); alive = true; } catch (error) { assert.equal(error.code, "ESRCH"); alive = false; }
      if (alive && process.platform === "linux") alive = !/\) Z /.test(fs.readFileSync(`/proc/${worker}/stat`, "utf8"));
      assert.equal(alive, false, "No active owned descendant may remain");
    } finally {
      if (child.exitCode === null && child.signalCode === null) await fixture.stopOwnedFixture(child, script, dir, 0);
      fs.rmSync(dir, { recursive: true, force: true });
    }
  }
});


test("failure diagnostics stay bounded without hiding failure counts", () => {
  const report = {};
  for (const key of ["errors", "external_requests"]) {
    for (let i = 0; i < 100; i++) fixture.boundedDiagnostic(report, key, i);
    assert.equal(report[key].length, 64); assert.equal(report[key + "_dropped"], 36);
    assert.equal(report[key][0], 0);
  }
});

test("visible stage evidence rejects offscreen and falsely completed continuation", () => {
  const rows = ["queue", "download", "transcript", "frames", "vision", "merge", "verify"].map(stage => ({
    stage, text: stage, state: ({ frames: "done", vision: "stopped", merge: "pending", verify: "pending" })[stage] || "done",
    top: 100, bottom: 150, left: 10, right: 200, width: 1440, height: 1000 }));
  fixture.visibleStageStates(rows);
  for (const stage of ["frames", "vision", "merge", "verify"]) {
    const changed = structuredClone(rows); changed.find(row => row.stage === stage).state = "incorrect";
    assert.throws(() => fixture.visibleStageStates(changed), /Actual terminal stage/);
  }
  for (const patch of [{ top: -1 }, { bottom: 1001 }, { right: 0 }, { bottom: NaN }]) {
    const changed = structuredClone(rows); Object.assign(changed[0], patch);
    assert.throws(() => fixture.visibleStageStates(changed), /Visible stage/);
  }
});

const moduleUrl = source => `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const production = name => readFileSync(new URL(`../${name}`, import.meta.url), "utf8");
const { preserveReaderPosition } = await import(moduleUrl(production("reader-progress.js")));
const { escapeHtml: esc } = await import(moduleUrl(production("desk-api.js")));
const { timelineHtml, taskExplanation } = await import(moduleUrl(production("desk-progress.js")
  .replace('"/web/desk-api.js"', JSON.stringify(moduleUrl(production("desk-api.js"))))));
function stageNavigationDom() {
  let top = 2300, current, writes = 0;
  const scrolls = [], generation = hash("a"), state = { selected: { id: "owned", kind: "task", status: "cancelled", phase: "cancelled" }, model: {}, health: {} };
  const scroller = { ownerDocument: {}, get scrollTop() { return top; }, set scrollTop(value) { top = value; } };
  scroller.ownerDocument.scrollingElement = scroller;
  const reader = { isConnected: true, hidden: false, dataset: { readerSource: "task:owned", readerRevision: "partial-current" },
    getBoundingClientRect: () => ({ top: 900 - top }) };
  const panel = { dataset: {}, isConnected: true, hidden: false,
    querySelector: () => current?.progress, querySelectorAll: selector => selector === "details.task-progress-details" ? [current.progress] : [],
    contains: node => node === current && current.isConnected,
    set innerHTML(value) {
      if (current) current.isConnected = false;
      writes++;
      const rows = [...value.matchAll(/<li data-stage="([^"]+)" data-state="([^"]+)">/g)].map((match, index) => ({
        dataset: { stage: match[1], state: match[2] }, innerText: match[1],
        getBoundingClientRect: () => ({ top: 400 + Math.floor(index / 5) * 60 - top,
          bottom: 450 + Math.floor(index / 5) * 60 - top, left: 200 + index % 5 * 170, right: 360 + index % 5 * 170 }),
      }));
      current = { isConnected: true, progress: { dataset: { taskProgress: "owned" }, open: true },
        getBoundingClientRect: () => ({ top: 400 - top }), querySelectorAll: () => rows,
        scrollIntoView(options) { scrolls.push({ connected: this.isConnected, options }); if (this.isConnected) top = 200; } };
      current.progress.querySelector = () => current;
    } };
  const events = ["frames", "vision"].map(phase => ({ event: "stage_timing", phase,
    status: phase === "frames" ? "completed" : "cancelled", timestamp: "2026-10-17T00:00:00Z", details: { duration_ms: 100 } }));
  const context = vm.createContext({ state, taskEvents: new Map([["owned", { events }]]), $: id => ({ document: reader, taskStatus: panel, regenerate: {} })[id],
    document: { scrollingElement: scroller, getElementById: id => ({ document: reader, taskStatus: panel })[id] },
    location: { hash: "#task/owned" }, performance, innerWidth: 1440, innerHeight: 1000,
    referenceReadingMetadata: { event: { id: "owned", kind: "task", control_generation: generation, epoch: 1, source_event: "metadata" }, error: null },
    preserveReaderPosition, timelineHtml, taskExplanation, esc, statusLabel: () => "已停止", mountQueueControls() {}, api() {}, refresh() {} });
  const desk = production("desk.js");
  vm.runInContext(desk.slice(desk.indexOf("function renderStatus("), desk.indexOf("async function loadAnnotations(")), context);
  context.renderStatus(false);
  const expected = { task_id: "owned", generation, reader_revision: reader.dataset.readerRevision };
  return { context, panel, reader, scroller, scrolls, expected, current: () => current, writes: () => writes,
    capture: (scroll = false) => vm.runInContext(`(${fixture.captureStageNavigation.toString()})`, context)({ ...expected, scroll }) };
}

test("actual status repaint detaches a transported timeline; current one-shot stage navigation stays visible", () => {
  const h = stageNavigationDom(), stale = h.current();
  h.context.renderStatus(false);
  stale.scrollIntoView({ block: "center", behavior: "instant" });
  assert.equal(stale.isConnected, false); assert.equal(h.scroller.scrollTop, 2300);
  assert.throws(() => fixture.visibleStageStates(h.capture().rows), /Visible stage/);
  h.scrolls.length = 0;
  const placed = h.capture(true); fixture.visibleStageStates(placed.rows);
  assert.equal(placed.before.connected, true); assert.equal(placed.after.connected, true);
  assert.equal(placed.before.node_id, placed.after.node_id); assert.equal(placed.before.scroll_top, 2300); assert.equal(placed.after.scroll_top, 200);
  assert.equal(h.scrolls.length, 1); assert.equal(h.scrolls[0].connected, true);
  h.context.renderStatus(false); // A later history repaint must respect the explicit new position.
  const final = h.capture(); fixture.visibleStageStates(final.rows);
  assert.equal(h.scroller.scrollTop, 200); assert.notEqual(final.after.node_id, placed.after.node_id);
  assert.equal(h.scrolls.length, 1, "The pre-capture observation does not scroll again");
});

test("stage navigation refuses stale source, generation, closed or detached status before scrolling", () => {
  for (const mutate of [h => { h.context.location.hash = "#task/other"; },
    h => { h.reader.dataset.readerSource = "task:other"; }, h => { h.reader.dataset.readerRevision = "new"; },
    h => { h.context.referenceReadingMetadata.event.control_generation = hash("b"); },
    h => { h.context.referenceReadingMetadata.event.id = "other"; }, h => { h.context.referenceReadingMetadata.error = "obsolete"; },
    h => { h.context.referenceReadingMetadata.event = null; }, h => { h.expected.generation = ""; },
    h => { h.panel.dataset.status = "running"; }, h => { h.panel.hidden = true; }, h => { h.panel.isConnected = false; },
    h => { h.current().progress.open = false; }, h => { h.current().progress.dataset.taskProgress = "other"; },
    h => { h.current().isConnected = false; }]) {
    const h = stageNavigationDom(); mutate(h); assert.throws(() => h.capture(true)); assert.equal(h.scrolls.length, 0);
  }
});

test("a later offscreen stage remains a failure rather than triggering a corrective scroll", () => {
  const h = stageNavigationDom(); fixture.visibleStageStates(h.capture(true).rows);
  h.scroller.scrollTop = 2300;
  assert.throws(() => fixture.visibleStageStates(h.capture().rows), /Visible stage/);
  assert.equal(h.scrolls.length, 1);
});

test("stage navigation is separate from retained prose and rechecks current identity before the PNG", () => {
  const script = readFileSync(new URL("../../scripts/progressive-visual-api-acceptance.cjs", import.meta.url), "utf8");
  assert(script.indexOf("context.addInitScript(observeReadingMetadata)") < script.indexOf("context.newPage()"));
  const start = script.indexOf("const stageSource ="), final = script.indexOf("report.stage_before_capture =");
  assert(start > script.indexOf('await capture("cancelled-retained-visual.png")'));
  assert(script.indexOf("report.stage_geometry =") < final);
  assert(final < script.indexOf('await capture("actual-stage-states.png")'));
  assert.equal(script.split("page.evaluate(captureStageNavigation, { ...stageSource, scroll: true })").length - 1, 1);
  assert.match(script, /generation: report\.cancelled\.state\.generation/);
  assert.doesNotMatch(script, /progress\.locator\("\.task-timeline"\)\.evaluate/);
});

test("reader response diagnostics accept only exact same-origin task reads and safe metadata", () => {
  const origin = "http://127.0.0.1:12345", id = "abcdef123456";
  assert.deepEqual(fixture.readerResponseSource(`${origin}/api/tasks/${id}/partial-note`, origin), { kind: "partial", task_id: id });
  for (const path of [`https://other.test/api/tasks/${id}`, `${origin}/api/tasks/${id}?token=private`,
    `${origin}/api/tasks/${id}/events/stream?after=1`, `${origin}/api/tasks/editions/material/${id}`, `${origin}/api/tasks/invalid`,
    `http://user:secret@127.0.0.1:12345/api/tasks/${id}`]) assert.equal(fixture.readerResponseSource(path, origin), null);
  const partial = fixture.readerResponseMetadata({ kind: "partial", task_id: id }, { task_id: id, schema_version: 1, verified: false,
    status: "unavailable", reason: "snapshot_changed", task_updated_at: "2026-10-17T12:00:00+00:00", attempt_id: id,
    source_revision: hash("a"), generation_revision: hash("b"), revision: hash("c"), sections: [], secret: "private" });
  assert.equal(fixture.readerResponseMetadata({ kind: "partial", task_id: id }, { attempt_id: [id] }).attempt_id, null);
  assert.equal(partial.reason, "snapshot_changed"); assert.equal(partial.identity_matches, true); assert(!JSON.stringify(partial).includes("private"));
  assert.equal(fixture.readerResponseMetadata({ kind: "partial", task_id: id }, { task_id: "other", reason: "private" }).identity_matches, false);
  assert.equal(fixture.readerResponseMetadata({ kind: "partial", task_id: id }, { reason: "private" }).reason, "unknown");
  const edition = fixture.readerResponseMetadata({ kind: "edition", task_id: id }, { revision: hash("a"), text: "private prose", edited: false });
  assert.equal(edition.text_bytes, 13); assert.match(edition.text_sha256, /^[a-f0-9]{64}$/); assert(!JSON.stringify(edition).includes("private"));
  const task = { id, control_generation: hash("a"), page_url: "https://private.test/?token=secret", source_media_path: "private.mp4" };
  const first = fixture.readerResponseMetadata({ kind: "selected", task_id: id }, { task });
  const second = fixture.readerResponseMetadata({ kind: "selected", task_id: id }, { task: { ...task, learning_range: { start: 1, end: 9 } } });
  assert.notEqual(first.source_binding_sha256, second.source_binding_sha256); assert(!JSON.stringify(first).includes("private"));
});

function responseObserver({ body = {}, reader = {}, hold = false, reject = false } = {}) {
  const listeners = new Map(), calls = [], completions = [], report = {}, origin = "http://127.0.0.1:12345", id = "abcdef123456";
  const cdp = { on: (name, fn) => listeners.set(name, fn), off: name => listeners.delete(name),
    send: (method, params) => { calls.push({ method, params }); if (reject) return Promise.reject(new Error("private error"));
      return hold ? new Promise(resolve => completions.push(resolve)) : Promise.resolve({ body: JSON.stringify(body), base64Encoded: false }); } };
  let evaluations = 0;
  const page = { evaluate: async callback => { assert.equal(callback, fixture.currentReaderIdentity); evaluations++; return reader; } };
  const stop = fixture.observeReaderResponses(cdp, page, report, origin);
  const emit = (name, event) => listeners.get("Network." + name)?.(event);
  const request = (requestId, suffix = "", method = "GET") => emit("requestWillBeSent", { requestId, request: { url: `${origin}/api/tasks/${id}${suffix}`, method } });
  const finish = (requestId, suffix = "", status = 200, encodedDataLength = 100) => {
    emit("responseReceived", { requestId, response: { url: `${origin}/api/tasks/${id}${suffix}`, status } });
    emit("loadingFinished", { requestId, encodedDataLength });
  };
  return { report, calls, completions, stop, close: () => listeners.get("close")?.(), emit, request, finish, evaluations: () => evaluations, listeners };
}
const drainDiagnostics = () => new Promise(resolve => setImmediate(resolve));

test("diagnostic responses retain exact request binding asynchronously without an action wait", async () => {
  const h = responseObserver({ body: { task_id: "abcdef123456", status: "unavailable", reason: "snapshot_changed" }, reader: { shell_id: 2 } });
  h.request("owned", "/partial-note"); h.finish("owned", "/partial-note");
  assert.equal(h.calls.length, 0); assert.equal(h.report.reader_responses[0].capture, "reading");
  await drainDiagnostics();
  const row = h.report.reader_responses[0]; assert.equal(row.capture, "complete"); assert.equal(row.metadata.reason, "snapshot_changed");
  assert.equal(row.reader.shell_id, 2); assert.equal(h.evaluations(), 1);
  assert.deepEqual(h.calls, [{ method: "Network.getResponseBody", params: { requestId: "owned" } }]); h.stop();
  assert.equal(h.listeners.size, 0); assert.equal(row.capture, "complete");
});

test("diagnostic missing, replaced, wrong-source, failed and closed requests remain explicit and never read unrelated bodies", async () => {
  const h = responseObserver({ hold: true }); h.finish("missing");
  h.request("post", "", "POST"); h.finish("post");
  h.request("reused"); h.request("reused", "/events/stream?after=1"); h.finish("reused");
  h.request("wrong"); h.finish("wrong", "/partial-note");
  h.request("failed"); h.emit("loadingFailed", { requestId: "failed" });
  h.request("large"); h.finish("large", "", 200, 2097153);
  h.request("closed"); h.finish("closed"); await drainDiagnostics(); h.stop();
  h.completions[0]({ body: "{}" }); await drainDiagnostics();
  assert.deepEqual(h.report.reader_responses.map(row => row.capture), ["request_replaced", "response_identity_mismatch", "network_failed", "body_size_limit", "closed_before_capture"]);
  assert.equal(h.calls.length, 1); assert.equal(h.evaluations(), 0); assert.equal(h.report.reader_responses_unavailable, 5);
});

test("diagnostic record, concurrency, body and retained-byte budgets are enforced without throwing primary errors", async () => {
  const h = responseObserver({ hold: true });
  for (let i = 0; i < 140; i++) { h.request(String(i)); h.finish(String(i)); }
  await drainDiagnostics(); assert.equal(h.report.reader_responses.length, 128); assert.equal(h.report.reader_responses_dropped, 12);
  assert.equal(h.calls.length, 4); assert.equal(h.report.reader_responses_unavailable, 124); h.stop();
  for (const complete of h.completions) complete({ body: "{}" }); await drainDiagnostics();
  assert(Buffer.byteLength(JSON.stringify(h.report.reader_responses)) < h.report.reader_response_limits.retained_bytes);
  const failed = responseObserver({ reject: true }); failed.request("one"); failed.finish("one"); await drainDiagnostics();
  assert.equal(failed.report.reader_responses[0].capture, "body_or_reader_unavailable"); assert(!JSON.stringify(failed.report).includes("private")); failed.stop();
  const oversized = responseObserver({ reader: { untrusted: "x".repeat(4097) } }); oversized.request("one"); oversized.finish("one"); await drainDiagnostics();
  assert.equal(oversized.report.reader_responses[0].capture, "metadata_size_limit"); oversized.stop();
});

test("one-shot reader identity distinguishes replacement shells and lost retained nodes without selecting or scrolling", () => {
  let shell = {}, current = true;
  const id = "abcdef123456", reader = { dataset: { readerSource: `task:${id}`, readerRevision: hash("a") + ":partial-draft:" },
    querySelector: selector => { assert.equal(selector, "[data-progressive-reader]"); return shell; }, contains: () => current };
  const anchor = { chapter: { isConnected: true }, batch: { isConnected: true }, paragraph: {} };
  const context = vm.createContext({ performance, document: { getElementById: () => reader }, visualReadingAnchor: anchor,
    referenceReadingMetadata: { event: { id, control_generation: hash("b"), source_event: "metadata" }, error: null } });
  const inspect = () => vm.runInContext(`(${fixture.currentReaderIdentity.toString()})()`, context);
  const before = inspect(); assert.equal(before.shell_id, 1); assert.equal(before.selected_generation, hash("b"));
  assert.equal(inspect().shell_id, 1);
  shell = {}; current = false; anchor.chapter.isConnected = anchor.batch.isConnected = false;
  const after = inspect(); assert.equal(after.shell_id, 2); assert.equal(after.retained_paragraph_in_reader, false);
  assert.equal(after.retained_batch_connected, false); assert.equal(after.retained_chapter_connected, false);
  reader.dataset.readerSource = "private URL"; reader.dataset.readerRevision = "private title";
  assert.equal(inspect().reader_source, null); assert.equal(inspect().reader_revision, null);
  shell = null; assert.equal(inspect().shell_id, null);
});

test("replaced or closed bindings before the queued dispatch never retrieve a reused body", async () => {
  for (const action of [h => h.request("same", "/events/stream?after=1"), h => h.stop(), h => h.close()]) {
    const h = responseObserver(); h.request("same"); h.finish("same"); action(h); await drainDiagnostics();
    assert.equal(h.calls.length, 0); assert.equal(h.evaluations(), 0);
    assert(["request_replaced", "closed_before_capture"].includes(h.report.reader_responses[0].capture)); h.stop();
  }
});

test("CDP session closure marks both awaiting and in-flight reads unavailable and ignores late bodies", async () => {
  const h = responseObserver({ hold: true }); h.request("awaiting"); h.request("pending"); h.finish("pending"); await drainDiagnostics();
  assert.equal(h.calls.length, 1); h.close(); h.stop();
  assert.equal(h.listeners.size, 0); assert.equal(h.report.reader_responses_unavailable, 2);
  h.completions[0]({ body: "{}" }); await drainDiagnostics();
  assert(h.report.reader_responses.every(row => row.capture === "closed_before_capture")); assert.equal(h.evaluations(), 0);
});

test("decoded oversized bodies are explicitly unavailable even when encoded size is small", async () => {
  const h = responseObserver({ body: { text: "x".repeat(2097153) } }); h.request("compressed"); h.finish("compressed", "", 200, 100);
  await drainDiagnostics(); assert.equal(h.calls.length, 1); assert.equal(h.evaluations(), 0);
  assert.equal(h.report.reader_responses[0].capture, "body_size_limit"); h.stop();
});

test("diagnostics stop before cleanup so browser-close failure preserves the primary error and final report", async () => {
  const { default: reference } = await import("../../scripts/progressive-slo-api-acceptance.cjs");
  const h = responseObserver({ hold: true }); h.request("pending"); h.finish("pending"); await drainDiagnostics();
  const primary = new Error("original gate failure"); h.report.failure = primary.message; let saved;
  h.stop();
  await reference.finishAcceptance({ closeBrowser: async () => { throw new Error("close failed"); }, stopBackend: async () => {},
    save: () => { saved = JSON.stringify(h.report); } }, h.report, primary);
  assert.equal(h.report.failure, "original gate failure"); assert.equal(primary.cleanupErrors.length, 1);
  assert.equal(h.report.reader_responses[0].capture, "closed_before_capture"); assert.equal(h.listeners.size, 0);
  h.completions[0]({ body: "{}" }); await drainDiagnostics(); assert.equal(JSON.stringify(h.report), saved);
  const source = readFileSync(new URL("../../scripts/progressive-visual-api-acceptance.cjs", import.meta.url), "utf8");
  assert.match(source, /finally \{ releaseDelayed\?\.\(\); stopReaderResponses\?\.\(\); await finishAcceptance/);
});
