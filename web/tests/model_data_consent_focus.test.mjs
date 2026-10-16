import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";

const { nativeModalFocusIsSafe, BACKGROUND_CONTROL_SELECTOR } = createRequire(import.meta.url)("../../scripts/model-data-consent-visual.cjs");
const modal = { activeTag: "BUTTON", activeId: "", documentHasFocus: true, insideModal: true, rootFallback: false,
  open: true, modal: true, openDialogs: 1, outcomePending: true,
  backgroundVisible: true, backgroundDisabled: false, backgroundFocusRefused: true };
const chrome = { ...modal, activeTag: "BODY", documentHasFocus: false, insideModal: false, rootFallback: true };

test("native focus validator admits modal focus and only precise browser-control excursions", () => {
  assert.equal(nativeModalFocusIsSafe(modal), true);
  assert.equal(nativeModalFocusIsSafe(chrome), true);
  assert.equal(nativeModalFocusIsSafe({ ...chrome, activeTag: "HTML" }), true);
  for (const activeTag of ["BODY", "HTML"]) {
    assert.equal(nativeModalFocusIsSafe({ ...chrome, activeTag, documentHasFocus: true }), false);
  }
});

test("native focus validator rejects background controls, nonmodal states and ineffective inertness checks", () => {
  for (const change of [
    { open: false }, { modal: false }, { openDialogs: 0 }, { openDialogs: 2 }, { outcomePending: false },
    { backgroundFocusRefused: false }, { backgroundVisible: false }, { backgroundDisabled: true },
    { insideModal: false, activeTag: "BUTTON", activeId: "homeLocal", documentHasFocus: true },
    { insideModal: false, activeTag: "BUTTON", activeId: "homeLocal", documentHasFocus: false },
    { insideModal: false, rootFallback: true, activeTag: "BODY", documentHasFocus: true },
  ]) {
    assert.equal(nativeModalFocusIsSafe({ ...modal, ...change }), false, JSON.stringify(change));
  }
  assert.equal(nativeModalFocusIsSafe({ ...chrome, activeTag: "BUTTON" }), false);
  assert.equal(nativeModalFocusIsSafe({ ...chrome, rootFallback: false }), false);
});

test("consent focus probe uses the visible hydrated home control, not the hidden legacy CTA", () => {
  const source = readFileSync(new URL("../desk-product.js", import.meta.url), "utf8");
  const hydratedHome = source.match(/home\.innerHTML = `([^`]+)`;/)?.[1];
  assert.ok(hydratedHome, "Check production hydration rather than obsolete static index markup");
  assert.equal(BACKGROUND_CONTROL_SELECTOR, "#homeLocal");
  const sourceActions = hydratedHome.match(/<div class="home-source-actions">(.*?)<\/div>/)?.[1];
  const opener = sourceActions?.match(/<button\b[^>]*\bid="homeLocal"[^>]*>/)?.[0];
  assert.ok(opener, "Focus probe must target an actual hydrated home source action");
  assert.doesNotMatch(opener, /\b(?:hidden|disabled|inert)\b|aria-hidden="true"/);
  assert.match(hydratedHome, /<button id="welcomeNew" hidden>/, "Legacy CTA is intentionally hidden");
  assert.match(source, /\$\("homeLocal"\)\.onclick =/);
});
