// Execute the shipped sidebar handlers against a queued-resize DOM double.
// This catches responsive readiness races without a browser or socket server.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import vm from "node:vm";
const require = createRequire(import.meta.url);
const { migrationSidebarReady, openMigrationSettings } = require("../../scripts/data-migration-visual-acceptance.cjs");
const source = readFileSync(new URL("../desk-interactions.js", import.meta.url), "utf8");
const start = source.indexOf("  const compactScreen = () =>"), end = source.indexOf('  document.querySelector(".brand").onclick');
assert(start > 0 && end > start);
function harness(width = 1440, collapsed = false) {
  const classes = new Set(), windowListeners = {}, documentListeners = {}, nodes = new Map(), clicks = [];
  const classList = { contains: key => classes.has(key), add: (...keys) => keys.forEach(key => classes.add(key)), remove: (...keys) => keys.forEach(key => classes.delete(key)),
    toggle(key, force = !classes.has(key)) { if (force) classes.add(key); else classes.delete(key); return force; } };
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, { attributes: {}, hidden: false, inert: false,
      setAttribute(key, value) { this.attributes[key] = value; }, getAttribute(key) { return this.attributes[key] ?? null; },
      focus() {}, click() { clicks.push(id); this.onclick?.(); }, getBoundingClientRect() { return { left: 14, right: 80, width: 66 }; } });
    return nodes.get(id);
  };
  const document = { body: { classList }, querySelector: selector => node(selector.slice(1)), addEventListener: (type, listener) => documentListeners[type] = listener };
  const context = vm.createContext({ document, window: { LearnNoteSettings: {}, addEventListener: (type, listener) => windowListeners[type] = listener },
    $: node, innerWidth: width, matchMedia: () => ({ matches: context.innerWidth <= 760 }),
    collapse: node("collapseSidebar"), localStorage: { getItem: () => String(collapsed), setItem() {} } });
  vm.runInContext(source.slice(start, end), context);
  const evaluate = fn => vm.runInContext(`(${fn})()`, context);
  let resizeQueued = false, waitChecks = 0;
  const page = {
    evaluate: async fn => evaluate(fn),
    locator: selector => ({ click: async () => { assert(!resizeQueued, "Never click while the app's resize state is stale"); node(selector === '[data-settings-section="storage"]' ? "storage" : selector.slice(1)).click(); } }),
    async waitForFunction(fn) {
      for (let attempt = 0; attempt < 3; attempt++) {
        waitChecks++;
        if (evaluate(fn)) return;
        if (resizeQueued) { resizeQueued = false; windowListeners.resize(); }
        await Promise.resolve();
      }
      throw Error("Synthetic fixture readiness did not settle");
    },
  };
  return { page, node, context, clicks, classes, evaluate, get waits() { return waitChecks; },
    resize(width) { context.innerWidth = width; resizeQueued = true; },
    escape() { documentListeners.keydown({ key: "Escape" }); },
    flushResize() { resizeQueued = false; windowListeners.resize(); },
  };
}
{
  const h = harness(390); h.escape(); h.resize(1440);
  assert.equal(h.node("menu").getAttribute("aria-expanded"), "false");
  assert.equal(h.evaluate(migrationSidebarReady), false, "Old mobile ARIA must not be used to toggle the desktop sidebar");
  // Reproduce the old helper's observed failure with actual production onclick.
  const legacy = harness(390); legacy.escape(); legacy.resize(1440); legacy.node("menu").click(); legacy.flushResize();
  assert(legacy.classes.has("sidebar-collapsed")); assert.equal(legacy.node("sidebar").inert, true);
  await openMigrationSettings(h.page);
  assert.deepEqual(h.clicks, ["settings", "storage"], "A visible desktop sidebar needs no click after the queued resize settles");
  assert(!h.classes.has("sidebar-collapsed")); assert.equal(h.node("sidebar").inert, false);
}
{
  const h = harness(1440); h.resize(390); await openMigrationSettings(h.page);
  assert.deepEqual(h.clicks, ["menu", "settings", "storage"]);
  h.escape(); await openMigrationSettings(h.page);
  assert.deepEqual(h.clicks, ["menu", "settings", "storage", "menu", "settings", "storage"]);
}
{
  const h = harness(1440, true); await openMigrationSettings(h.page);
  assert.deepEqual(h.clicks, ["menu", "settings", "storage"]);
  h.resize(390); await openMigrationSettings(h.page); h.escape(); h.resize(1440); await openMigrationSettings(h.page);
  assert.equal(h.clicks.filter(id => id === "menu").length, 2, "Only truly closed layouts receive a menu click");
}
{
  const h = harness(); const onclick = h.node("menu").onclick; h.node("menu").onclick = null;
  assert.equal(h.evaluate(migrationSidebarReady), false, "Static markup is not a hydrated menu");
  h.node("menu").onclick = onclick; assert.equal(h.evaluate(migrationSidebarReady), true);
}
console.log("Migration menu fixture: actual sidebar handlers reproduce stale mobile ARIA and reject it before clicks; desktop/mobile/repeated Escape/collapsed hydration passed");
