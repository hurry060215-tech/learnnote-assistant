// No browser emulation: exercise selector intent with shipped disclosure content.
// Actual visibility, clicks and typography remain required in the hosted Edge gate.
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const { openDataManagement } = require("../settings-management-fixture.cjs");
const root = path.resolve(__dirname, "../..");
const read = name => fs.readFileSync(path.join(root, name), "utf8");
function shippedDisclosure(file, assignment) {
  const match = read(file).match(new RegExp(`${assignment}\\s*=\\s*('[^']*');`));
  assert(match, `Shipped disclosure assignment missing: ${file}`);
  const markup = vm.runInNewContext(match[1]);
  const summary = markup.match(/<summary>([^<]*)<\/summary>/);
  assert(summary);
  return { heading: summary[1], ids: [...markup.matchAll(/\bid="([^"]*)"/g)].map(match => match[1]),
    open: false, clicks: 0, hidden: new Set() };
}
function fixtures() {
  return {
    management: shippedDisclosure("web/desk-tools.js", "settingsTools\\.innerHTML"),
    migration: shippedDisclosure("web/data-migration-status.js", "element\\.innerHTML"),
  };
}
function pageFor(nodes) {
  function locator(values, selector = "") {
    const one = () => { assert.equal(values.length, 1); return values[0]; };
    return {
      selector, count: async () => values.length,
      filter({ has }) { assert.equal(has.selector, "#studyTools"); return locator(values.filter(node => node.ids.includes(has.selector.slice(1)))); },
      evaluate: async fn => fn(one()),
      locator(selector) {
        const node = one();
        if (selector === ":scope > summary") return {
          count: async () => 1, innerText: async () => node.heading,
          click: async () => { node.open = !node.open; node.clicks += 1; },
        };
        assert(["#studyTools", "#storageTools"].includes(selector));
        const exists = node.ids.includes(selector.slice(1));
        return { count: async () => Number(exists), isVisible: async () => exists && node.open && !node.hidden.has(selector) };
      },
    };
  }
  return { locator(selector) {
    if (selector === "#studyTools") return locator([], selector);
    assert.equal(selector, '#settingsDialog [data-settings-page="storage"] details');
    return locator(nodes);
  } };
}

test("shipped management controls and migration summary are distinct in the same storage pane", () => {
  const { management, migration } = fixtures();
  assert.equal(management.heading, "数据与学习管理");
  assert.deepEqual(management.ids, ["storageTools", "studyTools", "aboutTools"]);
  assert.equal(migration.heading, "查看迁移记录与路径");
  assert(!migration.ids.includes("studyTools"));
  const settings = read("web/desk-settings.js");
  assert.match(settings, /panes\.storage\.append\(nativeTools\)/);
  assert.match(settings, /installMigrationStatus/);
});

test("selects management with migration details before or after it, without opening migration", async () => {
  for (const reversed of [false, true]) {
    const { management, migration } = fixtures();
    await openDataManagement(pageFor(reversed ? [management, migration] : [migration, management]));
    assert.equal(management.open, true); assert.equal(management.clicks, 1);
    assert.equal(migration.open, false); assert.equal(migration.clicks, 0);
  }
});

test("reopening leaves an already-open management disclosure open", async () => {
  const { management, migration } = fixtures(); management.open = true;
  await openDataManagement(pageFor([migration, management]));
  assert.equal(management.open, true); assert.equal(management.clicks, 0);
});

test("missing or duplicate owning disclosures fail before any click", async () => {
  for (const duplicate of [false, true]) {
    const { management, migration } = fixtures();
    const nodes = duplicate ? [management, { ...management }, migration] : [migration];
    await assert.rejects(openDataManagement(pageFor(nodes)), /Exactly one storage disclosure/);
    assert(nodes.every(node => node.clicks === 0));
  }
});

test("wrong heading, missing content or hidden intended content cannot pass", async () => {
  for (const mode of ["heading", "missing", "hidden"]) {
    const { management, migration } = fixtures();
    if (mode === "heading") management.heading = migration.heading;
    if (mode === "missing") management.ids = management.ids.filter(id => id !== "storageTools");
    if (mode === "hidden") management.hidden.add("#studyTools");
    await assert.rejects(openDataManagement(pageFor([migration, management])));
    assert.equal(migration.clicks, 0);
    if (mode === "heading") assert.equal(management.clicks, 0);
  }
});

test("all four affected acceptance paths use the checked shared disclosure, with no generic storage summary", () => {
  const affected = ["ui-readability-acceptance.cjs", "unified-workspace-acceptance.cjs",
    "personal-anchors-acceptance.cjs", "material-catalog-recovery-acceptance.cjs"];
  for (const file of affected) {
    const source = read(`scripts/${file}`);
    assert.match(source, /require\(["']\.\/settings-management-fixture\.cjs["']\)/);
    assert.match(source, /await openDataManagement\((?:page|p)\)/);
  }
  for (const file of fs.readdirSync(path.join(root, "scripts")).filter(name => name.endsWith(".cjs"))) {
    if (file === "settings-management-fixture.cjs") continue;
    assert.doesNotMatch(read(`scripts/${file}`), /\[data-settings-page=["']storage["']\]\s+(?:summary|details)/,
      `${file} must not assume only one storage disclosure exists`);
  }
});
