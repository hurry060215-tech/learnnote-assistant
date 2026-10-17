import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const desk = fs.readFileSync(new URL("../desk.js", import.meta.url), "utf8");
function harness(change = {}) {
  const task = { id: "synthetic", kind: "task", status: "failed", error_code: "summary_unavailable",
    summary_source: "local-template", transcript_path: "transcript.json", ...change };
  const panel = { dataset: {}, querySelector: () => null, querySelectorAll: () => [] };
  const state = { selected: task, model: {}, health: {}, epoch: 1 }, calls = [], errors = [];
  const context = vm.createContext({ state, taskEvents: new Map(), $: id => id === "taskStatus" ? panel : {},
    esc: String, timelineHtml: () => "", taskExplanation: () => "", statusLabel: () => "failed", mountQueueControls() {}, refresh() {},
    openSource: async (...args) => calls.push(args), failure: error => errors.push(error.message),
    api() { throw new Error("Reading source must not invoke a task mutation"); },
    renderStatus() { throw new Error("Reading source must not replace task state"); } });
  vm.runInContext(desk.slice(desk.indexOf("function renderTaskStatus("), desk.indexOf("async function loadAnnotations(")), context);
  const start = desk.indexOf('$("taskStatus").onclick =');
  vm.runInContext(desk.slice(start, desk.indexOf('$("settings").onclick', start)), context);
  return { context, state, panel, calls, errors, click: () => panel.onclick({ target: { closest: () => ({ dataset: { taskAction: "source" } }) } }) };
}

test("failed and progressive transcript states expose the existing read-only source entry", async () => {
  for (const change of [{}, { status: "running", error_code: "", summary_source: "transcript-draft" },
    { status: "cancelled", error_code: "", summary_source: "partial-draft" }]) {
    const h = harness(change), before = JSON.stringify(h.state.selected);
    h.context.renderTaskStatus(false);
    assert.match(h.panel.innerHTML, /type="button" data-task-action="source">查看字幕原文/);
    await h.click();
    assert.equal(h.calls.length, 1); assert.equal(h.calls[0][0], undefined);
    assert.equal(h.calls[0][1], h.state.selected);
    assert.equal(JSON.stringify(h.state.selected), before); assert.equal(h.state.taskAction, undefined);
  }
});

test("missing transcript and ordinary finished notes do not get an extra recovery action", () => {
  for (const change of [{ transcript_path: "" }, { status: "success", error_code: "", summary_source: "text-llm" },
    { status: "success", error_code: "", summary_source: "subtitle-extract" }]) {
    const h = harness(change); h.context.renderTaskStatus(false);
    assert.doesNotMatch(h.panel.innerHTML, /data-task-action="source"/);
  }
});

test("read failure remains local and a pending task control is not bypassed", async () => {
  const h = harness(); h.context.openSource = async () => { throw new Error("Source unavailable"); };
  await h.click(); assert.deepEqual(h.errors, ["Source unavailable"]);
  h.state.taskAction = { id: "synthetic", action: "retry-summary" };
  await h.click(); assert.deepEqual(h.errors, ["Source unavailable"]);
});
