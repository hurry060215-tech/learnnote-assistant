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

test("root scrolling anchors the current source section when an earlier batch arrives", () => {
  let inserted = false;
  const heading = (id, text, top) => ({ id, textContent: text, tagName: "H2",
    getBoundingClientRect: () => ({ top: top + (inserted && id !== "title" ? 220 : 0), bottom: top + 20 }) });
  const headings = [heading("title", "Lesson", -1200), heading("source-10", "00:10–00:20", -40),
    heading("source-20", "00:20–00:30", 800)];
  const element = { dataset: { readerSource: "task:a", readerRevision: "1" }, querySelectorAll: () => headings };
  const scroller = { scrollTop: 1200, getBoundingClientRect: () => ({ top: -1200 }), ownerDocument: {} };
  scroller.ownerDocument.scrollingElement = scroller;
  renderEditionStable(element, scroller, "task:a", "2", () => { inserted = true; });
  assert.equal(scroller.scrollTop, 1420);
});

test("an earlier batch cannot steal a repeated subheading anchor", () => {
  const node = (id, text, top, tagName = "H3") => ({ id, tagName, textContent: text,
    getBoundingClientRect: () => ({ top, bottom: top + 20 }) });
  let headings = [node("title", "Lesson", -500, "H1"), node("batch-2", "00:10–00:20", -60, "H2"),
    node("note-core", "Core points", -10)];
  const element = { dataset: { readerSource: "task:a", readerRevision: "1" }, querySelectorAll: () => headings };
  const scroller = { scrollTop: 500, getBoundingClientRect: () => ({ top: 0 }) };
  renderEditionStable(element, scroller, "task:a", "2", () => {
    headings = [headings[0], node("batch-1", "00:00–00:10", -250, "H2"), node("note-core", "Core points", -170),
      node("batch-2", "00:10–00:20", 140, "H2"), node("note-core-2", "Core points", 190)];
  });
  assert.equal(scroller.scrollTop, 700);
});

test("the last visible section remains anchored even with no later heading", () => {
  let offset = -90;
  const heading = { id: "last-source", textContent: "Last source", tagName: "H2",
    getBoundingClientRect: () => ({ top: offset, bottom: offset + 20 }) };
  const element = { dataset: { readerSource: "task:a", readerRevision: "1" }, querySelectorAll: () => [heading] };
  const scroller = { scrollTop: 1100, getBoundingClientRect: () => ({ top: 20 }) };
  renderEditionStable(element, scroller, "task:a", "2", () => { offset += 140; });
  assert.equal(scroller.scrollTop, 1240);
});
