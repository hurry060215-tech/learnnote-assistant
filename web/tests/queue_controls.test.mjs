import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
const source = fs.readFileSync(new URL("../queue-controls.js", import.meta.url), "utf8");
const { mountQueueControls } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.events = {}; this.isConnected = true; }
  append(...items) { this.children.push(...items); }
  setAttribute(key, value) { this[key] = value; }
  addEventListener(name, callback) { this.events[name] = callback; }
  set innerHTML(_) { throw new Error("Queue controls must use text-only DOM"); }
}
const all = item => [item, ...item.children.flatMap(all)];
test("pause/resume and priority use explicit local API actions", async () => {
  const previous = globalThis.document;
  globalThis.document = { createElement: tag => new Element(tag) };
  try {
    const panel = new Element("panel"), calls = []; let refreshed = 0;
    mountQueueControls(panel, { id: "task/one", queue: { state: "queued", paused: true, priority: 0 } },
      async (path, options) => { calls.push([path, JSON.parse(options.body)]); }, async () => { refreshed++; });
    const nodes = all(panel), button = nodes.find(item => item.tag === "button"), select = nodes.find(item => item.tag === "select");
    assert.equal(button.textContent, "继续排队任务");
    await button.events.click();
    assert.deepEqual(calls[0], ["/api/queue/pause", { paused: false }]);
    select.value = "5"; await select.events.change();
    assert.deepEqual(calls[1], ["/api/queue/tasks/task%2Fone/priority", { priority: 5 }]);
    assert.equal(refreshed, 2);
    const done = new Element("panel"); mountQueueControls(done, { queue: { state: "done" } }, () => {}, () => {});
    assert.equal(done.children.length, 0);
  } finally { globalThis.document = previous; }
});
test("running task has pause control but cannot change its admitted priority", () => {
  const previous = globalThis.document; globalThis.document = { createElement: tag => new Element(tag) };
  try {
    const panel = new Element("panel");
    mountQueueControls(panel, { queue: { state: "running", paused: false } }, () => {}, () => {});
    assert.equal(all(panel).filter(item => item.tag === "select").length, 0);
    assert.ok(all(panel).some(item => item.textContent?.includes("不中断")));
  } finally { globalThis.document = previous; }
});
