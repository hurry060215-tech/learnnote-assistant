import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
const text = fs.readFileSync(new URL("../reader-progress.js", import.meta.url), "utf8");
const { renderEditionStable } = await import(`data:text/javascript;base64,${Buffer.from(text).toString("base64")}`);

test("progress-only updates keep DOM, selection and scroll; changed text keeps source anchor", () => {
  let offset = 20, renders = 0;
  const heading = { textContent: "05:00–10:00", tagName: "H3", getBoundingClientRect: () => ({ top: offset, bottom: offset + 20 }) };
  const element = { dataset: {}, querySelectorAll: () => [heading] };
  const scroller = { scrollTop: 500, getBoundingClientRect: () => ({ top: 0 }) };
  const render = () => { renders++; offset += 100; };
  assert.equal(renderEditionStable(element, scroller, "task:a", "draft-1", render), true);
  assert.equal(renderEditionStable(element, scroller, "task:a", "draft-1", render), false);
  assert.equal(renders, 1); assert.equal(scroller.scrollTop, 500);
  assert.equal(renderEditionStable(element, scroller, "task:a", "draft-2", render), true);
  assert.equal(scroller.scrollTop, 600);
  assert.equal(renderEditionStable(element, scroller, "task:b", "draft-2", render), true);
  assert.equal(scroller.scrollTop, 600);
});

test("missing anchor keeps prior scroll instead of resetting to top", () => {
  const element = { dataset: { readerSource: "task:a", readerRevision: "a" }, querySelectorAll: () => [] };
  const scroller = { scrollTop: 720 };
  renderEditionStable(element, scroller, "task:a", "b", () => { scroller.scrollTop = 0; });
  assert.equal(scroller.scrollTop, 720);
});
