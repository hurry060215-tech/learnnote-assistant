import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";

const { nativeModalFocusIsSafe } = createRequire(import.meta.url)("../../scripts/model-data-consent-visual.cjs");
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
    { insideModal: false, activeTag: "BUTTON", activeId: "welcomeNew", documentHasFocus: true },
    { insideModal: false, activeTag: "BUTTON", activeId: "welcomeNew", documentHasFocus: false },
    { insideModal: false, rootFallback: true, activeTag: "BODY", documentHasFocus: true },
  ]) {
    assert.equal(nativeModalFocusIsSafe({ ...modal, ...change }), false, JSON.stringify(change));
  }
  assert.equal(nativeModalFocusIsSafe({ ...chrome, activeTag: "BUTTON" }), false);
  assert.equal(nativeModalFocusIsSafe({ ...chrome, rootFallback: false }), false);
});
