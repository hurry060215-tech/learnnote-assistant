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
  const batch = { isConnected: true, dataset: { readerBatch: details().section_id } };
  const chapter = { isConnected: true, contains: item => item === batch };
  const reader = { dataset: { readerSource: "task:owned", readerRevision: "new" }, contains: item => item === chapter };
  const context = vm.createContext({ innerWidth: 1440, innerHeight: 1000, document: { getElementById: () => reader,
    getSelection: () => selected, elementFromPoint: () => node }, getComputedStyle: item => ({ display: "block", visibility: "visible", opacity: item.opacity || "1" }),
    visualReadingAnchor: { paragraph: node, batch, chapter, source: "task:owned", prose, selection: prose, anchor_node: selected.anchorNode, focus_node: selected.focusNode, anchor_offset: 0, focus_offset: 42, top: 300 } });
  return { read: () => vm.runInContext(`(${inspectVisibleBatch.toString()})()`, context), node, batch, chapter, reader, selected, ancestor, setTop: value => { top = value; } };
}

test("actual observation rejects changed nodes, source, selection, prose and hidden ancestors", () => {
  for (const mutate of [h => { h.batch.isConnected = false; }, h => { h.chapter.isConnected = false; },
    h => { h.node.isConnected = false; }, h => { h.reader.dataset.readerSource = "task:other"; },
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

test("reading anchor uses actual prose and centered scroll before retaining node/selection", () => {
  const calls = [], text = {}, paragraph = { innerText: "source", scrollIntoView: options => calls.push(options),
    getBoundingClientRect: () => ({ top: 200 }) }, chapter = {};
  const element = { querySelector: selector => { assert.equal(selector, "div p"); return paragraph; }, closest: () => chapter };
  const selection = { removeAllRanges() {}, addRange: range => assert.equal(range, text), toString: () => "source" };
  text.selectNodeContents = node => assert.equal(node, paragraph);
  const context = vm.createContext({ document: { getSelection: () => selection, createRange: () => text,
    getElementById: () => ({ dataset: { readerSource: "task:owned" } }) } });
  vm.runInContext(`(${rememberVisibleBatch.toString()})`, context)(element);
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [{ block: "center", behavior: "instant" }]);
  assert.equal(context.visualReadingAnchor.batch, element); assert.equal(context.visualReadingAnchor.paragraph, paragraph);
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
