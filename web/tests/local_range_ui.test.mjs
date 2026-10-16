import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import test from "node:test";
const source = readFileSync(new URL("../desk-tools.js", import.meta.url), "utf8");
const load = async file => import("data:text/javascript;base64," + Buffer.from(readFileSync(new URL(file, import.meta.url), "utf8")).toString("base64"));
const {localPlaybackPosition, localMediaSource} = await load("../local-player.js");
const {fullVideoSource, requestedRangeDuration} = await load("../range-source.js");
const deferred = () => { let resolve; const promise = new Promise(done => resolve = done); return { promise, resolve }; };
function extractAction(name, next) {
  const begin = source.indexOf(`    "${name}": `), end = source.indexOf(`    "${next}": `, begin);
  return source.slice(begin, end).trim().replace(new RegExp(`^"${name}": `), "").replace(/,$/, "");
}
function harness() {
  const original = {id: "original", title: "Local source", kind: "task", media_path: "synthetic.mp4", media_integrity: {duration: 20}};
  const selected = { ...original, id: "clip", source_task_id: "original", range_media_ready: true, learning_range: {start: 5, end: 15, original_start: 5, original_end: 15}, media_integrity: {duration: 10} };
  const h = { state: {selected, epoch: 1}, calls: [], opened: [], refreshed: 0, response: deferred(), confirms: [], html: "" };
  const nodes = { player: {dataset: {sourceTaskId: "clip"}, currentSrc: "http://127.0.0.1/api/tasks/clip/media", currentTime: 2.125, readyState: 1, getAttribute: () => "/api/tasks/clip/media"}, rangeStart: {value: "2.125"}, rangeEnd: {value: "4.5"} };
  const dialog = {open: true, dataset: {}, close() {this.open = false;}};
  const context = vm.createContext({ state: h.state, dialog, $: id => nodes[id], localPlaybackPosition, localMediaSource, fullVideoSource, requestedRangeDuration,
    current: () => ({...h.state.selected}), esc: value => String(value).replaceAll("<", "&lt;"), options: () => ({content_mode: "auto"}),
    openItem: async item => h.opened.push(item), refresh: async () => h.refreshed++,
    confirm: message => {h.confirms.push(message); return true;},
    api: async (path, options) => {h.calls.push({path, options}); if (options) return h.response.promise; return {task: path.endsWith("/clip") ? selected : original};},
  });
  const start = source.indexOf('  function rangeIsCurrent('), end = source.indexOf('  async function ocr()', start);
  const formStart = source.indexOf('      } else if (form.id === "rangeForm") {') + '      } else if (form.id === "rangeForm") {'.length;
  const formEnd = source.indexOf('      } else if (form.id === "askForm") {', formStart);
  vm.runInContext(`let generation = 1, rangeSelection = null; function show(title, body) {globalThis.html = body; dialog.open = true; return ++generation;} ${source.slice(start,end)}
    globalThis.position = ${extractAction("range-position", "screen-subtitles")};
    globalThis.full = ${extractAction("learn-full-source", "add-to-course")};
    globalThis.submitFields = async () => {${source.slice(formStart,formEnd)}};
    globalThis.dismiss = () => {generation++; dialog.open = false;};`, context);
  h.context = context; h.nodes = nodes; h.dialog = dialog; context.range(); return h;
}

test("range fields are task-local decimal seconds with source title and original offset disclosure", () => {
  const h = harness();
  assert.match(h.context.html, /value="2.125"/); assert.match(h.context.html, /max="10" step="any"/);
  assert.match(h.context.html, /Local source/); assert.match(h.context.html, /原视频 5–15 秒/);
  h.nodes.player.currentTime = 3.875; h.context.position(); assert.equal(h.nodes.rangeStart.value, "3.875");
  h.nodes.player.dataset.sourceTaskId = "other";
  assert.throws(() => h.context.position(), /未使用其他来源/);
  h.context.range(); assert.match(h.context.html, /value="0"/);
});

test("invalid bounds never post and two submits use exact decimal API seconds once", async () => {
  for (const [start,end] of [[-1,2],[4,3],[0,11],["NaN",2],[0,"Infinity"],["",2],[0,""]]) {
    const h = harness(); h.nodes.rangeStart.value = String(start); h.nodes.rangeEnd.value = String(end);
    await assert.rejects(h.context.submitFields(), /有效起止秒数/); assert.equal(h.calls.length, 0);
  }
  const h = harness(); const first = h.context.submitFields(), second = h.context.submitFields();
  assert.equal(h.calls.length, 1); assert.equal(h.calls[0].path, "/api/tasks/clip/learn-range");
  assert.deepEqual(JSON.parse(h.calls[0].options.body), {start: 2.125, end: 4.5, options: {content_mode: "auto"}});
  h.response.resolve({task_id: "child", task: {id: "child"}}); await Promise.all([first, second]);
  assert.equal(h.opened.length, 1); assert.equal(h.opened[0].id, "child"); assert.equal(h.refreshed, 1);
});

test("encoded padding is disclosed but cannot expand a nested learning range", async () => {
  const h = harness();
  Object.assign(h.state.selected, {learning_range: {start:5.25,end:15.75,original_start:5.25,original_end:15.75}, media_integrity: {duration:11.064026}});
  h.nodes.player.currentTime = 10.75;
  h.context.range();
  assert.match(h.context.html, /max="10.5" step="any" required value=""/);
  assert.match(h.context.html, /编码媒体时长 11.064026 秒/);
  assert.match(h.context.html, /原视频 5.25–15.75 秒/);
  assert.throws(() => h.context.position(), /超过原片段的学习范围/);
  for (const end of [11, 10.500000001, 10.505]) {
    h.nodes.rangeStart.value = "0"; h.nodes.rangeEnd.value = String(end);
    await assert.rejects(h.context.submitFields(), /有效起止秒数/);
  }
  assert.equal(h.calls.length, 0);
  h.nodes.rangeStart.value = "5.25"; h.nodes.rangeEnd.value = "10.5";
  const pending = h.context.submitFields();
  assert.equal(JSON.parse(h.calls[0].options.body).end, 10.5);
  h.response.resolve({task_id:"nested",task:{id:"nested"}}); await pending;
});

test("decimal parent endpoints yield an exact decimal max without binary rounding noise", async () => {
  for (const [start,end,expected] of [[0.1,0.3,0.2],[0.2,0.3,0.1],[1e-7,3e-7,2e-7],[1e20,1.1e20,1e19]])
    assert.equal(requestedRangeDuration({start,end}), expected);
  assert.equal(requestedRangeDuration({original_start:60}), null);
  const h = harness(); h.state.selected.learning_range = {start:0.1,end:0.3,original_start:0.1,original_end:0.3};
  h.context.range(); assert.match(h.context.html, /max="0.2"/);
  h.nodes.rangeStart.value = "0"; h.nodes.rangeEnd.value = "0.200000001";
  await assert.rejects(h.context.submitFields(), /有效起止秒数/); assert.equal(h.calls.length, 0);
  h.nodes.rangeEnd.value = "0.2"; const pending = h.context.submitFields();
  assert.equal(JSON.parse(h.calls[0].options.body).end, 0.2);
  h.response.resolve({task_id:"decimal",task:{id:"decimal"}}); await pending;
});

test("Close, same-source revisit and source replacement invalidate late range responses", async () => {
  for (const change of [h => h.context.dismiss(), h => h.state.epoch++, h => h.state.selected = {id: "other", kind: "task"}]) {
    const h = harness(), pending = h.context.submitFields(); change(h);
    h.response.resolve({task_id: "late", task: {id: "late"}}); await pending;
    assert.equal(h.opened.length, 0); assert.equal(h.refreshed, 0);
  }
});

test("full upgrade resolves ancestry once and uses the original task route", async () => {
  const h = harness(), first = h.context.full(), second = h.context.full();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(h.calls.map(c => c.path), ["/api/tasks/clip", "/api/tasks/original", "/api/tasks/original/rerun-from-media"]);
  assert.equal(h.confirms.length, 1); assert.match(h.confirms[0], /Local source/);
  h.response.resolve({task_id: "whole", task: {id: "whole"}}); await Promise.all([first, second]);
  assert.equal(h.opened.length, 1); assert.equal(h.opened[0].id, "whole");
});

test("navigation during full-source ancestry lookup cannot confirm or post", async () => {
  const h = harness(), lookup = deferred(); h.context.api = async path => {h.calls.push({path}); return lookup.promise;};
  const pending = h.context.full(); h.state.epoch++;
  lookup.resolve({task: {id: "clip", title: "whole", learning_range: {}}}); await pending;
  assert.equal(h.confirms.length, 0); assert.equal(h.calls.length, 1); assert.equal(h.opened.length, 0);
});
