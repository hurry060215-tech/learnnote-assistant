import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import test from "node:test";

const read = name => fs.readFileSync(new URL(`../${name}`, import.meta.url), "utf8");
const moduleUrl = source => `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const { preserveReaderPosition } = await import(moduleUrl(read("reader-progress.js")));
const { escapeHtml: esc } = await import(moduleUrl(read("desk-api.js")));
const { timelineHtml, taskExplanation } = await import(moduleUrl(read("desk-progress.js")
  .replace('"/web/desk-api.js"', JSON.stringify(moduleUrl(read("desk-api.js"))))));
const desk = read("desk.js");

function harness() {
  const task = { id: "a", kind: "task", status: "running", phase: "summarizing", updated_at: "one" };
  const state = { selected: task, model: {}, health: {} }, taskEvents = new Map();
  const pending = [];
  let statusHeight = 500, scrollTop = 1087, scrollWrites = 0, statusWrites = 0;
  const scroller = { ownerDocument: {}, get scrollTop() { return scrollTop; },
    set scrollTop(value) { scrollWrites++; scrollTop = value; } };
  scroller.ownerDocument.scrollingElement = scroller;
  const reader = { dataset: { readerSource: "task:a" }, isConnected: true, hidden: false,
    getBoundingClientRect: () => ({ top: statusHeight - scroller.scrollTop }) };
  const panel = { dataset: {}, querySelector: () => null, querySelectorAll: () => [],
    set innerHTML(value) {
      statusWrites++;
      // Reproduce the observed Edge line wrap when event history adds elapsed
      // time to the active stage (12px text at line-height 1.6).
      statusHeight = value.includes("已用") ? 519.1875 : 500;
    } };
  const nodes = { document: reader, taskStatus: panel, regenerate: {} };
  const context = vm.createContext({ state, taskEvents, $: id => nodes[id], document: { scrollingElement: scroller },
    preserveReaderPosition, timelineHtml, taskExplanation, esc, statusLabel: () => "正在整理", mountQueueControls() {}, refresh() {},
    api: path => new Promise(resolve => pending.push({ path, resolve })) });
  vm.runInContext(desk.slice(desk.indexOf("async function loadTaskEvents("), desk.indexOf("async function loadAnnotations(")), context);
  const finishHistory = async () => {
    pending.at(-1).resolve({ events: [{ event: "task_updated", status: "running", phase: "summarizing", timestamp: "2026-01-01T00:00:00Z" }] });
    await new Promise(resolve => setImmediate(resolve));
  };
  return { context, state, reader, scroller, panel, pending, finishHistory,
    scrollWrites: () => scrollWrites, statusWrites: () => statusWrites };
}

test("the production history repaint anchors an unchanged edition after elapsed-time text wraps", async () => {
  const h = harness(), before = h.reader.getBoundingClientRect().top;
  h.context.renderStatus();
  assert.equal(h.pending[0].path, "/api/tasks/a/events?limit=500");
  assert.equal(h.scrollWrites(), 0);
  await h.finishHistory();
  assert.equal(h.statusWrites(), 2, "Both metadata and fetched events paint the actual status function");
  assert.equal(h.reader.getBoundingClientRect().top, before);
  assert.equal(h.scroller.scrollTop, 1106.1875);
  assert.equal(h.scrollWrites(), 1);
});

test("delayed history honors a newer user scroll rather than restoring the request-time position", async () => {
  const h = harness(); h.context.renderStatus();
  h.scroller.scrollTop += 200;
  const before = h.reader.getBoundingClientRect().top;
  await h.finishHistory();
  assert.equal(h.reader.getBoundingClientRect().top, before);
  assert.equal(h.scroller.scrollTop, 1306.1875);
});

test("navigation during the history request cannot repaint or restore the previous task", async () => {
  const h = harness(); h.context.renderStatus();
  h.state.selected = { ...h.state.selected, id: "b" };
  h.reader.dataset.readerSource = "task:b";
  await h.finishHistory();
  assert.equal(h.statusWrites(), 1);
  assert.equal(h.scrollWrites(), 0);
});

test("a user cancellation remains authoritative when old running history arrives", async () => {
  const h = harness(); h.context.renderStatus();
  h.state.selected = { ...h.state.selected, status: "cancelling", phase: "cancelling" };
  await h.finishHistory();
  assert.equal(h.panel.dataset.status, "cancelling");
  assert.equal(h.scroller.scrollTop, 1087);
  assert.equal(h.scrollWrites(), 0);
});
