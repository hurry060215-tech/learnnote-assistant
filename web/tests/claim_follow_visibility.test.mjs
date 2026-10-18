import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import vm from "node:vm";

const require = createRequire(import.meta.url);
const fixture = readFileSync(new URL("../../scripts/claim-follow-visibility-acceptance.cjs", import.meta.url), "utf8");
const { assertClaimFollowVisible } = require("../../scripts/claim-follow-visibility-acceptance.cjs");

test("active-claim margin is scoped, preserves heading clearance, and ships fresh dependency keys", () => {
  const css = readFileSync(new URL("../desk.css", import.meta.url), "utf8").replace(/\r\n/g, "\n");
  for (const representation of [css, css.replace(/\n/g, "\r\n")]) {
    const rules = [...representation.replace(/\r\n/g, "\n").matchAll(/([^{}]+)\{([^{}]*)\}/g)]
      .filter(([, selector, body]) => selector.includes(".note-claim-active") && body.includes("scroll-margin"));
    assert.equal(rules.length, 1);
    assert.equal(rules[0][1].trim(), ".document .note-claim-active");
    assert.equal(rules[0][2].trim(), "scroll-margin-top: max(140px, calc(var(--source-sticky-top, 128px) + 12px));");
  }
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  const entry = readFileSync(new URL("../desk.js", import.meta.url), "utf8");
  for (const name of ["desk.js", "desk.css"]) assert(html.includes(`${name}?v=claim-follow-visible-20261018`));
  assert(entry.includes('from "/web/claim-timeline.js?v=claim-follow-visible-20261018"'));
  assert(!entry.includes('from "/web/claim-timeline.js"'));
});

function geometry({ top = 300, height = 40, active = true } = {}) {
  return { top, bottom: top + height, targetHeight: height, text: [{ top: top + 2, bottom: top + 20, left: 10, right: 100, unobscured: true }],
    textLineCount: 1, headerBottom: 125, stickyTop: 125, margin: 140, width: 1440, height: 500,
    scrollY: 1000 - top, scrollWidth: 1440, targetOverflow: 0, active, follow: true, sourcePinned: false,
    sourceHeight: 700, claimListHeight: 200, claimListText: "Synthetic source row", claimListTextLength: 20, focusedControl: "followNote",
    sourceHidden: false, editorHidden: true, noteFocused: false, selectionCollapsed: true };
}

test("hosted geometry assertions distinguish actual center, visible no-scroll, oversized start and text occlusion", () => {
  assert.doesNotThrow(() => assertClaimFollowVisible(geometry(), "center"));
  assert.doesNotThrow(() => assertClaimFollowVisible(geometry({ top: 127 }), "unchanged"));
  assert.doesNotThrow(() => assertClaimFollowVisible(geometry({ top: 140, height: 400 }), "start"));
  for (const mutate of [
    state => { state.top = 100; }, state => { state.bottom = 501; }, state => { state.top = 230; },
    state => { state.text = []; }, state => { state.text[0].unobscured = false; }, state => { state.text[0].top = 120; },
    state => { state.text[0].right = 1441; }, state => { state.margin = 0; }, state => { state.stickyTop = 120; },
    state => { state.scrollWidth = 1450; }, state => { state.targetOverflow = 10; }, state => { state.sourcePinned = true; },
    state => { state.noteFocused = true; }, state => { state.selectionCollapsed = false; }, state => { state.follow = false; },
  ]) { const state = geometry(); mutate(state); assert.throws(() => assertClaimFollowVisible(state, "center")); }
  assert.throws(() => assertClaimFollowVisible(geometry({ top: 300, height: 400 }), "start"));
  assert.throws(() => assertClaimFollowVisible(geometry({ top: 140, height: 40 }), "start"));
});

function fakeRun({ primary, badGeometry = false, reflow = false, captureFailure, cleanupFailure, reportFailure, requireUniqueActiveClaim = false, ambiguous = false } = {}) {
  const writes = [], calls = [], records = [], module = { exports: {} };
  vm.runInNewContext(fixture, { module, console: { error: () => {} }, require: name => name === "node:fs" ? {
    writeFileSync: (_path, text) => { calls.push("report"); writes.push(JSON.parse(text)); if (reportFailure) throw reportFailure; },
  } : require(name) });
  let checked = false, time = 24, placed = { id: "small", covered: true }, reads = 0;
  const savedViewport = { width: 1280, height: 720 };
  const page = {
    viewportSize: () => savedViewport,
    setViewportSize: async value => { calls.push("viewport"); if (value === savedViewport && cleanupFailure) throw cleanupFailure; },
    keyboard: { press: async () => { checked = !checked; } },
    locator: selector => selector === "#followNote" ? { isChecked: async () => checked, focus: async () => { calls.push("focus follow"); } }
      : selector === '#document .note-claim-marker[aria-current="true"]' ? { evaluateAll: async () => ambiguous ? ["earlier", "small"] : [time === 12 ? "small" : "large"] }
      : { evaluate: async (_fn, value) => { time = value; calls.push("seek"); } },
    waitForFunction: async () => {},
    evaluateHandle: async () => ({ evaluate: async () => { calls.push("restore focus"); }, dispose: async () => { calls.push("dispose"); } }),
    screenshot: async options => { assert.equal(options.timeout, 5000); calls.push("capture"); if (captureFailure) throw captureFailure; },
    evaluate: async (fn, arg) => {
      if (fn.name === "readClaimFollowGeometry") {
        if (++reads === 2 && primary) throw primary;
        const { claimId, listTextLimit } = arg;
        assert.equal(listTextLimit, 1000);
        const height = claimId === "large" ? 400 : 40;
        const top = !checked ? (placed.covered ? 40 : 127) : claimId === "large" ? 140 : placed.covered ? (badGeometry ? 100 : 300) : 127;
        return { ...geometry({ top, height, active: time !== 24 }), follow: checked, sourceHeight: checked && reflow ? 800 : 700 };
      }
      const source = String(fn);
      if (source.includes("follow: document")) return { follow: false, time: 24, paused: true, x: 0, y: 0 };
      if (source.includes("scrollBy")) placed = arg;
      if (source.includes("scrollTo")) calls.push("restore scroll");
    },
  };
  const run = () => module.exports.assertClaimFollowVisibility(page, { claimId: "small", oversizedClaimId: "large", out: "/fixture", name: "test", viewport: { width: 1440, height: 500 }, records, requireUniqueActiveClaim });
  return { run, writes, calls, records };
}

test("hosted failure records geometry before asserting and always attempts restoration", async () => {
  const h = fakeRun({ badGeometry: true });
  await assert.rejects(h.run(), /Claim start must clear/);
  assert.equal(h.records[0].cases[0].before.top, 40);
  assert.equal(h.records[0].cases[0].after.top, 100);
  assert.equal(h.writes[0].passed, false);
  for (const action of ["capture", "restore focus", "restore scroll", "dispose", "report"]) assert(h.calls.includes(action));
});

test("primary fixture failure survives capture, cleanup, and report failures with bounded diagnostics", async () => {
  const primary = new Error("primary geometry read"), captureFailure = new Error("capture"), cleanupFailure = new Error("viewport cleanup"), reportFailure = new Error("report write");
  const h = fakeRun({ primary, captureFailure, cleanupFailure, reportFailure });
  await assert.rejects(h.run(), error => error === primary);
  assert.equal(h.records[0].cases[0].before.top, 40);
  assert.match(h.records[0].captureError, /capture/);
  assert.match(h.records[0].cleanupErrors[0], /viewport cleanup/);
  assert.match(h.records[0].writeError, /report write/);
  assert(h.calls.includes("dispose") && h.calls.includes("restore scroll"));
});

test("source-list reflow cannot masquerade as a successful follow decision", async () => {
  const h = fakeRun({ reflow: true });
  await assert.rejects(h.run(), /must not change source layout/);
  assert.equal(h.writes[0].cases[0].before.sourceHeight, 700);
  assert.equal(h.writes[0].cases[0].after.sourceHeight, 800);
});

test("successful geometry cannot hide a cleanup or report failure", async () => {
  const success = fakeRun(); await success.run();
  assert.equal(success.writes[0].passed, true); assert.equal(success.writes[0].cases.length, 3);
  assert.equal(success.writes[0].cases[2].after.targetHeight, 400);
  assert.equal(success.writes[0].cases[2].after.top, 140);
  const cleanup = fakeRun({ cleanupFailure: new Error("viewport cleanup") });
  await assert.rejects(cleanup.run(), /viewport cleanup/); assert.equal(cleanup.writes[0].passed, false);
  const error = new Error("report write"), report = fakeRun({ reportFailure: error });
  await assert.rejects(report.run(), value => value === error); assert.equal(report.records[0].passed, false);
});

test("installed target identity rejects overlapping active claims before geometry and covers both fixed times", async () => {
  const rejected = fakeRun({ requireUniqueActiveClaim: true, ambiguous: true });
  await assert.rejects(rejected.run(), /unique active mapped claim/);
  assert.deepEqual(Array.from(rejected.records[0].cases[0].activeClaimIds), ["earlier", "small"]);
  assert.equal(rejected.records[0].cases[0].before, undefined);
  const accepted = fakeRun({ requireUniqueActiveClaim: true }); await accepted.run();
  assert.deepEqual(Array.from(accepted.records[0].cases, item => Array.from(item.activeClaimIds)), [["small"], ["small"], ["large"]]);
  assert.equal(accepted.records[0].passed, true);
});

test("existing hosted owner covers desktop, mobile, short viewport and actual native zoom", () => {
  const owner = readFileSync(new URL("../../scripts/evidence-source-acceptance.cjs", import.meta.url), "utf8");
  const native = readFileSync(new URL("../../scripts/timeline-native-zoom-acceptance.cjs", import.meta.url), "utf8");
  assert(owner.includes('"--claim-follow"'));
  for (const size of ['"follow-desktop", 1440, 900', '"follow-mobile", 390, 844', '"follow-short", 1440, 240']) assert(owner.includes(size));
  assert(native.includes('name: "follow-native-200"'));
  assert(native.includes('capture: filename => nativeKey("capture", filename)'));
  assert.doesNotMatch(fixture, /addStyleTag|scrollIntoView|\.click\(/);
  const trigger = 'await page.keyboard.press("Space");';
  const triggered = fixture.slice(fixture.lastIndexOf(trigger) + trigger.length, fixture.indexOf("report.passed = true;"));
  assert.doesNotMatch(triggered, /scrollBy|scrollTo|\.focus\(|\.check\(|mouse|keyboard/);
});
