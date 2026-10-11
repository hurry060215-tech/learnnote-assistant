import assert from "node:assert/strict";
import vm from "node:vm";
import {createRequire} from "node:module";
import {createSidepanelHarness} from "./sidepanel_test_harness.mjs";

const require = createRequire(import.meta.url);
const {FIXTURE, installFixtures, matrix} = require("../../scripts/extension-locale-visual-acceptance.cjs");
const drain = () => new Promise(resolve => setImmediate(resolve));
function gate() {
  let release;
  return {promise: new Promise(resolve => { release = resolve; }), release: () => release()};
}
async function fixtureHarness(locale, held = [], fixture = FIXTURE) {
  const gates = Object.fromEntries(held.map(name => [name, gate()]));
  const calls = [];
  let externalFetches = 0;
  const h = await createSidepanelHarness({locale, beforeLoad(context, {catalog}) {
    context.Response = Response;
    context.location = {href: "http://127.0.0.1:1234/extension/sidepanel.html", origin: "http://127.0.0.1:1234"};
    context.fetch = () => { externalFetches++; throw Error("No external fetch in readiness test"); };
    // Exercise the same serialized init script as Edge, not a second set of mocks.
    vm.runInContext(`(${installFixtures.toString()})(${JSON.stringify({locale, catalog, fixture})})`, context);
    const wrap = (owner, key, name) => {
      const original = owner[key];
      owner[key] = async (...args) => {
        calls.push(name);
        if (gates[name]) await gates[name].promise;
        return original(...args);
      };
    };
    wrap(context.chrome.permissions, "getAll", "permissions");
    wrap(context.chrome.storage.local, "get", "storage");
    wrap(context.chrome.runtime, "sendMessage", "context");
  }});
  return {...h, calls, gates, externalFetches: () => externalFetches,
    async release(name) { gates[name].release(); await drain(); },
    async connect() { h.context.__localeFixture.connect(); await h.api.checkClient(); await drain(); }
  };
}
function previewReady(h, expected = true) {
  assert.equal(h.elements.get("#sourcePreviewCard").hidden, !expected);
  assert.equal(Boolean(h.api.getState().currentContext?.page?.browser_subtitles?.length), expected);
  assert.equal(h.externalFetches(), 0);
}

// These are startup/data checks for the 18 fixture inputs, not layout coverage.
for (const item of matrix()) {
  const h = await fixtureHarness(item.locale);
  try {
    previewReady(h);
    assert.equal(h.api.getState().clientConnected, false, "Preview must render before releasing health");
    assert.equal(h.elements.get("#sendButton").disabled, true);
    assert(h.elements.get("#sourcePreviewContent").innerHTML.includes(FIXTURE.subtitle));
    assert.deepEqual(h.calls, ["permissions", "storage", "context"]);
  } finally { await h.connect(); }
  previewReady(h);
  assert.equal(h.elements.get("#sendButton").disabled, false);
}

for (const locale of ["zh-CN", "en-US"]) {
  // Release later dependencies early, then unblock the real initialization chain.
  const serial = await fixtureHarness(locale, ["permissions", "storage", "context"]);
  try {
    previewReady(serial, false);
    assert.deepEqual(serial.calls, ["permissions"]);
    await serial.release("context");
    await serial.release("storage");
    previewReady(serial, false);
    await serial.release("permissions");
    previewReady(serial);
    assert.equal(serial.api.getState().clientConnected, false);
  } finally {
    Object.values(serial.gates).forEach(value => value.release());
    await drain(); await serial.connect();
  }

  for (const held of ["storage", "context"]) {
    const h = await fixtureHarness(locale, [held]);
    try {
      previewReady(h, false);
      if (held === "context") {
        await h.connect();
        assert.equal(h.api.getState().clientConnected, true);
        assert.equal(h.elements.get("#sendButton").disabled, true, "Health alone cannot authorize sending");
      }
      await h.release(held);
      previewReady(h);
    } finally { h.gates[held].release(); await drain(); await h.connect(); }
    assert.equal(h.elements.get("#sendButton").disabled, false);
    await h.api.collectContext(true);
    previewReady(h);
  }

  const empty = await fixtureHarness(locale, [], {...FIXTURE, cues: []});
  try { previewReady(empty, false); }
  finally { await empty.connect(); }
  previewReady(empty, false);
}
console.log("Exact locale fixture startup: 18 inputs, delayed/reordered permissions/storage/context, health-first and health-held, repeated collection and empty captions passed; no browser or native extension used.");
