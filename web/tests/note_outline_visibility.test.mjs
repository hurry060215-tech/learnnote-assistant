import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import vm from "node:vm";

const require = createRequire(import.meta.url);
const { assertOutlineHeadingVisible } = require("../../scripts/note-controls-visual-acceptance.cjs");
const css = readFileSync(new URL("../desk.css", import.meta.url), "utf8");
const fixture = readFileSync(new URL("../../scripts/note-controls-visual-acceptance.cjs", import.meta.url), "utf8");

test("all outline-supported heading levels share the existing minimum and live sticky offset", () => {
  const lf = css.replace(/\r\n/g, "\n");
  for (const representation of [lf, lf.replace(/\n/g, "\r\n")]) {
    const rules = [...representation.replace(/\r\n/g, "\n").matchAll(/([^{}]+)\{([^{}]*)\}/g)]
      .filter(([, selector, body]) => /\.document\s+h[234]/.test(selector) && /scroll-margin/.test(body));
    assert.equal(rules.length, 1, "Do not introduce competing heading offset rules later in the cascade");
    assert.equal(rules[0][1].trim(), ".document h2,\n.document h3,\n.document h4");
    assert.equal(rules[0][2].trim(), "scroll-margin-top: max(140px, calc(var(--source-sticky-top, 128px) + 12px));");
  }
  assert.match(readFileSync(new URL("../index.html", import.meta.url), "utf8"), /desk\.css\?v=outline-clearance-20261018/);
});

const visible = () => ({
  heading: { top: 140, bottom: 168 }, headerBottom: 125, width: 390, height: 844, scrollWidth: 390,
  text: [{ top: 143, bottom: 165, left: 20, right: 140, unobscured: true }],
});

test("outline visibility checks actual text and sticky chrome rather than only the target center", () => {
  assert.doesNotThrow(() => assertOutlineHeadingVisible(visible()));
  for (const mutate of [
    state => { state.heading.top = 0; },
    state => { state.headerBottom = 150; },
    state => { state.heading.bottom = 900; },
    state => { state.text = []; },
    state => { state.text[0].top = 120; },
    state => { state.text[0].bottom = 845; },
    state => { state.text[0].left = -1; },
    state => { state.text[0].right = 391; },
    state => { state.text[0].unobscured = false; },
    state => { state.scrollWidth = 392; },
  ]) {
    const state = visible(); mutate(state);
    assert.throws(() => assertOutlineHeadingVisible(state));
  }
  const wrapped = visible(); wrapped.headerBottom = 180; wrapped.heading = { top: 192, bottom: 220 };
  wrapped.text[0] = { top: 195, bottom: 217, left: 20, right: 140, unobscured: true };
  assert.doesNotThrow(() => assertOutlineHeadingVisible(wrapped));
});

test("visual regression isolates the old offset, removes it finally, and never scrolls the target itself", () => {
  assert.match(fixture, /i === 13 \? `\\n\\n####/);
  assert.match(fixture, /#document h4 \{ scroll-margin-top: 0px; \}/);
  assert.match(fixture, /finally\s*\{\s*try \{ await oldHeadingStyle\.evaluate\(node => node\.remove\(\)\); \}/);
  const fixedCases = fixture.indexOf('for (const [width, height, sizing]');
  assert(fixture.indexOf("await oldHeadingStyle.evaluate(node => node.remove())") < fixedCases);
  assert.match(fixture, /if \(!oldOffsetFailure\) throw cleanupError/);
  assert.match(fixture, /\[195, 422, "effective-200-percent-reflow-not-native-zoom"\]/);
  assert.match(fixture, /for \(const motion of \["reduce", "no-preference"\]\)/);
  assert.match(fixture, /Math\.abs\(geometry\.scrollY - beforeY\) > 100/);
  const observation = fixture.slice(fixture.indexOf("function readOutlineHeading"), fixture.indexOf("async function main"));
  const navigation = fixture.slice(fixture.indexOf("async function selectDeepHeading"), fixture.indexOf("const oldHeadingStyle"));
  assert.doesNotMatch(observation + navigation, /\.(?:scrollIntoView(?:IfNeeded)?|scrollTo|scrollBy|focus)\s*\(/);
  assert(fixture.indexOf("outlineNavigation.push({ name, sizing") < fixture.indexOf("assertOutlineHeadingVisible(geometry)"));
});

test("fixture keeps the primary failure and attempts bounded screenshot, report and browser cleanup", async () => {
  for (const reportWriteFails of [false, true]) {
    const primary = new Error("synthetic primary route failure"), calls = [];
    let saved;
    const page = { setDefaultTimeout() {}, on() {}, async route() { throw primary; }, isClosed: () => false,
      async screenshot(options) { calls.push(["screenshot", options.timeout]); throw new Error("synthetic capture failure"); } };
    const browser = { version: () => "synthetic", newPage: async () => page,
      async close() { calls.push(["close"]); throw new Error("synthetic close failure"); } };
    const fakeRequire = name => name === "playwright" ? { chromium: { launch: async () => browser } }
      : name === "node:fs" ? { mkdirSync() {}, writeFileSync(file, value) {
        calls.push(["report"]); saved = JSON.parse(value);
        if (reportWriteFails) throw new Error("synthetic report failure");
      } } : require(name);
    const context = vm.createContext({ require: fakeRequire, module: { exports: {} }, URL,
      process: { argv: ["node", "fixture", "http://127.0.0.1:8765", "/not-written"] },
      console: { error() {}, log() {} } });
    vm.runInContext(fixture + "\nmodule.exports.run = main;", context);
    await assert.rejects(context.module.exports.run(), error => error === primary);
    assert.deepEqual(calls, [["screenshot", 2000], ["close"], ["report"]]);
    assert.equal(saved.passed, false);
    assert.match(saved.error, /primary route failure/);
    assert.match(saved.failure_screenshot_error, /capture failure/);
    assert.match(saved.cleanup_error, /close failure/);
    assert.deepEqual(saved.outlineNavigation, []);
  }
});
