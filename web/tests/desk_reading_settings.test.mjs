import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import test from "node:test";
const moduleSource = fs.readFileSync(new URL("../reading-settings.js", import.meta.url), "utf8");
const shared = await import(`data:text/javascript;base64,${Buffer.from(moduleSource).toString("base64")}`);
const settings = fs.readFileSync(new URL("../desk-settings.js", import.meta.url), "utf8");
const integration = settings.slice(settings.indexOf('  let appearanceRevision = "";'), settings.indexOf('  function collect() {'));
const save = settings.slice(settings.indexOf('  $("savePreferences").onclick = async () => {'), settings.indexOf('  installModelCatalog(state);'));
let revision = 0;
class Element extends EventTarget {
  constructor() { super(); this._value = ""; this.checked = false; this.disabled = false; this.style = {}; this.hidden = false; this.textContent = ""; }
  set value(value) { this._value = String(value); }
  get value() { return this._value; }
}
function harness() {
  const inputs = ["prefReaderSize", "prefDensity", "prefFont", "prefWidth", "prefLeading", "prefWeight", "prefAccent", "prefAutoOpen", "prefNotify"];
  const nodes = new Map(), $ = id => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
  const data = new Map(), notices = [], events = new EventTarget(), styles = {}, classes = new Set();
  const storage = { getItem: key => data.get(key) ?? null, setItem(key, value) { if (storage.fail) throw Error("quota"); data.set(key, value); } };
  const values = () => JSON.stringify(inputs.map(id => [id, id === "prefAutoOpen" || id === "prefNotify" ? $(id).checked : $(id).value]));
  let baseline = "", otherDirty = false;
  const dirty = key => key === "appearance" ? baseline !== values() : otherDirty;
  const updateDirty = () => [...(dirty("appearance") ? ["appearance"] : []), ...(otherDirty ? ["model"] : [])];
  const saved = keys => { if (keys.includes("appearance")) baseline = values(); return updateDirty(); };
  const preview = { querySelector: () => $("previewParagraph") }, dialog = new Element();
  const panes = { appearance: new Element(), model: new Element() }; panes.model.hidden = true;
  const document = { documentElement: { style: { setProperty: (key, value) => { styles[key] = value; } } }, body: { classList: { toggle(key, value) { if (value) classes.add(key); else classes.delete(key); } } } };
  const context = vm.createContext({ ...shared, $, state: {}, dirty, saved, updateDirty, values, document, preview,
    panes, dialog, localStorage: storage, navigator: { locks: { request: async (name, options, fn) => fn() } }, window: events,
    notice: message => notices.push(message), CustomEvent: class extends Event {},
    crypto: { randomUUID: () => `ui-${++revision}` },
    // Inject deterministic revisions into the shared factory, whose lexical globals are outside vm.
    createReadingSettingsAdapter: options => shared.createReadingSettingsAdapter({ ...options, newRevision: () => `ui-${++revision}` }),
  });
  vm.runInContext(integration + save + '\nappearance(); saved(["appearance"]);', context);
  return { $, context, adapter: events.LearnNoteReadingSettings, storage, data, notices, styles, classes, dialog, panes,
    dirty: () => dirty("appearance"), otherDirty: value => { otherDirty = value; },
    input(id, value) { $(id).value = value; panes.appearance.dispatchEvent(new Event("input")); },
    storageEvent() { const event = new Event("storage"); Object.assign(event, { storageArea: storage, key: shared.READING_STORAGE_KEY }); events.dispatchEvent(event); },
    save: () => $("savePreferences").onclick(),
  };
}

test("desk adapter keeps actual form, CSS and saved state synchronized", async () => {
  const h = harness(); assert.equal(h.data.size, 0); assert.equal(h.$("prefReaderSize").value, "17");
  const result = await h.adapter.patch({ operationId: "ui-agent", expectedRevision: h.adapter.read().revision, patch: { size: 20, theme: "dark" } });
  assert.equal(result.ok, true); assert.equal(h.$("prefReaderSize").value, "20"); assert.equal(h.dirty(), false);
  assert.equal(h.styles["--reader-size"], "20px"); assert.ok(h.classes.has("dark")); assert.equal(h.context.state.reading.size, 20);
  h.otherDirty(true);
  const blocked = await h.adapter.patch({ operationId: "other-edit", expectedRevision: result.revision, patch: { size: 18 } });
  assert.equal(blocked.error.code, "unsaved_settings");
});

test("manual preview remains unsaved; close restores persisted CSS and ignores queued older close", () => {
  const h = harness(); h.input("prefReaderSize", "20"); assert.equal(h.styles["--reader-size"], "20px"); assert.equal(h.data.size, 0);
  h.dialog.open = true; h.dialog.dispatchEvent(new Event("close")); assert.equal(h.$("prefReaderSize").value, "20");
  h.dialog.open = false; h.dialog.dispatchEvent(new Event("close"));
  assert.equal(h.styles["--reader-size"], "17px"); assert.equal(h.$("prefReaderSize").value, "17"); assert.equal(h.dirty(), false);
});

test("external storage updates preserve a draft and prevent stale manual save", async () => {
  const h = harness(); h.input("prefReaderSize", "20");
  h.storage.setItem(shared.READING_STORAGE_KEY, JSON.stringify({ size: 16, custom: true })); h.storageEvent();
  assert.equal(h.context.state.reading.size, 16); assert.equal(h.styles["--reader-size"], "20px"); assert.equal(h.$("prefReaderSize").value, "20");
  await h.save(); assert.match(h.$("preferencesStatus").textContent, /未能保存/);
  assert.equal(JSON.parse(h.storage.getItem(shared.READING_STORAGE_KEY)).size, 16); assert.equal(h.dirty(), true);
});

test("manual notification wait preserves newer edits and keeps them dirty after original save", async () => {
  const h = harness(); let permission;
  const notification = { permission: "default", requestPermission: () => new Promise(resolve => { permission = resolve; }) };
  h.context.Notification = notification; h.context.window.Notification = notification;
  h.input("prefReaderSize", "18"); h.$("prefNotify").checked = true;
  const pending = h.save(); h.input("prefReaderSize", "20"); notification.permission = "granted"; permission("granted"); await pending;
  const stored = JSON.parse(h.storage.getItem(shared.READING_STORAGE_KEY));
  assert.equal(stored.size, 18); assert.equal(stored.notify, true);
  assert.equal(h.$("prefReaderSize").value, "20"); assert.equal(h.styles["--reader-size"], "20px"); assert.equal(h.dirty(), true);
  await h.save(); assert.equal(JSON.parse(h.storage.getItem(shared.READING_STORAGE_KEY)).size, 20); assert.equal(h.dirty(), false);
});

test("theme toggle shares atomic save, preserves drafts and reports storage failure", async () => {
  const h = harness(); h.input("prefReaderSize", "20");
  await h.$("theme").onclick(); assert.ok(h.classes.has("dark")); assert.equal(h.dirty(), true);
  await h.save(); assert.equal(h.dirty(), false); assert.equal(h.adapter.read().settings.size, 20); assert.equal(h.adapter.read().settings.theme, "dark");
  h.storage.fail = true; await h.$("theme").onclick(); assert.ok(h.classes.has("dark")); assert.match(h.notices.at(-1), /原配置未改变/);
});
