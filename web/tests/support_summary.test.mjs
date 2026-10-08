import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const source = fs.readFileSync(new URL("../support-summary.js", import.meta.url), "utf8");
const { mountSupportSummary } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.events = {}; this.isConnected = true; this.textContent = ""; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  setAttribute(key, value) { this[key] = value; }
  addEventListener(name, handler) { this.events[name] = handler; }
  click() { this.clicked = true; return this.events.click?.(); }
  set innerHTML(_) { throw new Error("Support content must never enter HTML"); }
}
function all(element) { return [element, ...element.children.flatMap(all)]; }
test("support preview exports precisely reviewed fields and cancel makes no request", async () => {
  const oldDocument = globalThis.document;
  const oldCreate = URL.createObjectURL, oldRevoke = URL.revokeObjectURL;
  const nodes = [], requests = [], blobs = [];
  globalThis.document = {
    createElement(tag) { const item = new Element(tag); nodes.push(item); return item; },
    createTextNode(text) { const item = new Element("text"); item.textContent = text; return item; },
  };
  URL.createObjectURL = blob => { blobs.push(blob); return "blob:local-fixture"; };
  URL.revokeObjectURL = () => {};
  try {
    const values = { installed: true, desktop_connected: false, first_task_started: true,
      first_task_succeeded: false, error_categories: ["model"], version: "<img src=x onerror=bad>" };
    const api = async (path, opts) => {
      requests.push([path, opts]);
      assert.match(path, /^\/api\/support\//);
      if (path.endsWith("activation")) return { enabled: true, fields: values };
      return Object.fromEntries(JSON.parse(opts.body).fields.map(key => [key, values[key]]));
    };
    const panel = await mountSupportSummary(new Element("host"), api);
    const find = text => all(panel).find(item => item.textContent === text);
    const preview = all(panel).find(item => item.tag === "pre");
    assert.match(preview.textContent, /<img/);
    const save = find("保存已预览摘要");
    await save.click(); assert.equal(blobs.length, 0);
    const checks = all(panel).filter(item => item.type === "checkbox");
    checks[0].checked = false; await checks[0].events.change();
    await new Promise(resolve => setTimeout(resolve, 0));
    assert.equal(JSON.parse(preview.textContent).installed, undefined);
    const consent = checks.at(-1); consent.checked = true; consent.events.change();
    await save.click(); assert.equal(blobs.length, 1);
    assert.equal(await blobs[0].text(), preview.textContent);
    const before = requests.length;
    await find("取消导出").click(); await save.click();
    assert.equal(blobs.length, 1); assert.equal(requests.length, before);
    await find("删除并关闭本地记录").click();
    assert.ok(requests.some(([, options]) => options?.method === "DELETE"));
    assert.doesNotMatch(source, /sendBeacon|fetch\(|XMLHttpRequest|localStorage|navigator\.userAgent/);
  } finally {
    globalThis.document = oldDocument; URL.createObjectURL = oldCreate; URL.revokeObjectURL = oldRevoke;
  }
});
