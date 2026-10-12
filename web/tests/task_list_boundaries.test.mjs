import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const context = vm.createContext({ URL });
for (const name of ["document", "window", "localStorage", "fetch", "XMLHttpRequest"]) {
  Object.defineProperty(context, name, { get() { throw new Error(`Unexpected ${name} access`); } });
}
for (const filename of ["task-format.js", "task-display.js", "task-list.js"]) {
  vm.runInContext(await readFile(new URL("../" + filename, import.meta.url), "utf8"), context);
}
const api = context.LearnNoteTaskList;
assert.ok(Object.isFrozen(api));
const snapshot = JSON.parse(await readFile(new URL("./fixtures/task_list_boundaries_v1.json", import.meta.url), "utf8"));
assert.equal(snapshot.base_commit, "6279fca6c049d92dc1be2ef2af37c44c1c720bb9");
assert.equal(snapshot.app_sha256, "3f2a06f5e4bc7b650181a7d81aa2f3c79cf1a4064bfe7e36f120e72b712c693f");

function freeze(value) {
  if (value && typeof value === "object") {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}

// The old-source snapshot was recorded with a fixed UTC clock. Production callers
// still supply a Date in their own timezone; the policy never reads the clock.
const originalTimezone = process.env.TZ;
process.env.TZ = snapshot.timezone;
try {
  for (const item of snapshot.cases) {
    const args = structuredClone(item.args);
    if (item.method === "recentTaskTime") args[1] = new Date(args[1]);
    args.forEach(freeze);
    const before = JSON.stringify(args);
    const result = api[item.method](...args);
    assert.deepEqual(JSON.parse(JSON.stringify(result)), item.expected, item.name);
    assert.equal(JSON.stringify(args), before, `${item.name} must not mutate inputs`);
  }
} finally {
  if (originalTimezone === undefined) delete process.env.TZ;
  else process.env.TZ = originalTimezone;
}
assert.deepEqual(new Set(snapshot.cases.map(item => item.method)), new Set(Object.keys(api)));

const first = freeze({ id: "first", status: "success", note_path: "fixture.md" });
const second = freeze({ id: "second", status: "success", note_path: "fixture.md" });
const list = freeze([first, second]);
assert.equal(api.preferredInitialTask(list), first);
assert.equal(api.sortedVisibleTasks(list)[0], first);
assert.equal(api.sortedVisibleTasks(list, "second")[0], second);
const windows = freeze([{ id: "W001" }]);
assert.equal(api.visualWindows({ visual_windows: windows }), windows);

// Keep the historic globals callable and resolve mutable UI state at call time.
const app = await readFile(new URL("../app.js", import.meta.url), "utf8");
const stateAdapters = ["taskStudyRank", "sortedVisibleTasks", "taskMatchesFilters", "recentTaskTime", "noteVersionInfo"];
for (const name of Object.keys(api).filter(name => !stateAdapters.includes(name))) {
  assert.doesNotMatch(app, new RegExp("^function " + name + "\\(", "m"), `${name} must have one implementation`);
}
const adapters = vm.createContext({ LearnNoteTaskList: api, selectedTaskId: "first", tasks: list, taskStatusFilter: "all", taskQuery: "" });
for (const name of stateAdapters) {
  const match = app.match(new RegExp("^function " + name + "\\([^]*?^}", "m"));
  assert.ok(match, `${name} compatibility adapter`);
  vm.runInContext(match[0], adapters);
}
assert.equal(adapters.sortedVisibleTasks(list)[0], first);
adapters.selectedTaskId = "second";
assert.equal(adapters.sortedVisibleTasks(list)[0], second);
assert.equal(adapters.taskStudyRank(second), 0);
assert.equal(adapters.taskMatchesFilters(first), true);
adapters.taskStatusFilter = "running";
assert.equal(adapters.taskMatchesFilters(first), false);
adapters.taskStatusFilter = "all";
adapters.taskQuery = "missing";
assert.equal(adapters.taskMatchesFilters(first), false);
adapters.tasks = [{ id: "root" }, { id: "child", source_task_id: "root" }];
assert.deepEqual(JSON.parse(JSON.stringify(adapters.noteVersionInfo(adapters.tasks[1]))), { rootId: "root", index: 2, total: 2 });
assert.equal(adapters.recentTaskTime({ updated_at: "invalid" }), "");
let clock = new Date(2026, 9, 9, 12);
adapters.Date = class extends Date {
  constructor() { super(clock); }
};
const recent = { updated_at: new Date(2026, 9, 8, 8, 5).toISOString() };
assert.equal(adapters.recentTaskTime(recent), "昨天");
clock = new Date(2026, 9, 10, 12);
assert.equal(adapters.recentTaskTime(recent), "10月8日");

const source = await readFile(new URL("../task-list.js", import.meta.url), "utf8");
assert.throws(() => vm.runInContext(source, vm.createContext({ URL })), /undefined/);
const missingDisplay = vm.createContext({ URL, LearnNoteTaskFormat: context.LearnNoteTaskFormat });
assert.throws(() => vm.runInContext(source, missingDisplay), /undefined/);
console.log(`${snapshot.cases.length} pre-extraction task-list snapshots, immutable inputs, state adapters and dependency boundaries pass`);
