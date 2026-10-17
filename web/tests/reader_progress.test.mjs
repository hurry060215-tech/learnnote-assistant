import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
const text = fs.readFileSync(new URL("../reader-progress.js", import.meta.url), "utf8");
const { preserveReaderPosition, renderEditionStable } = await import(`data:text/javascript;base64,${Buffer.from(text).toString("base64")}`);

function statusHarness({ scrollTop = 1087, bodyTop = -400, nested = false } = {}) {
  let height = 500, scroll = scrollTop, writes = 0;
  const scroller = { ownerDocument: {}, getBoundingClientRect: () => ({ top: nested ? 40 : -scroll }),
    get scrollTop() { return scroll; }, set scrollTop(value) { writes++; scroll = value; } };
  if (!nested) scroller.ownerDocument.scrollingElement = scroller;
  const selection = { anchorNode: {}, focusNode: {}, anchorOffset: 2, focusOffset: 12 };
  const element = { hidden: false, isConnected: true, dataset: { readerSource: "task:a" }, firstChild: {},
    getBoundingClientRect: () => ({ top: bodyTop + height - 500 + scrollTop - scroll }) };
  return { element, scroller, selection, writes: () => writes,
    resize: delta => { height += delta; }, nativeScroll: delta => { scroll += delta; } };
}

test("status growth and shrinkage preserve the unchanged passage and selection", () => {
  const h = statusHarness(), body = h.element.firstChild, selection = { ...h.selection };
  const before = h.element.getBoundingClientRect().top;
  for (const delta of [19.1875, 45, -64.1875]) {
    const result = preserveReaderPosition(h.element, h.scroller, "task:a", () => { h.resize(delta); return "rendered"; });
    assert.equal(result, "rendered");
    assert.equal(h.element.getBoundingClientRect().top, before);
    assert.equal(h.element.firstChild, body);
    assert.deepEqual(h.selection, selection);
  }
  assert.equal(h.scroller.scrollTop, 1087);
  assert.equal(h.writes(), 3);
});

test("status correction respects native anchoring and leaves unchanged layout alone", () => {
  const h = statusHarness(), before = h.element.getBoundingClientRect().top;
  preserveReaderPosition(h.element, h.scroller, "task:a", () => { h.resize(19.1875); h.nativeScroll(19.1875); });
  preserveReaderPosition(h.element, h.scroller, "task:a", () => {});
  assert.equal(h.element.getBoundingClientRect().top, before);
  assert.equal(h.scroller.scrollTop, 1106.1875);
  assert.equal(h.writes(), 0, "Do not undo native compensation or write a redundant scroll");
});

test("status updates do not pull the top of the page or status readers into the note", () => {
  for (const setup of [{ scrollTop: 0 }, { bodyTop: 100 }]) {
    const h = statusHarness(setup), before = h.scroller.scrollTop;
    preserveReaderPosition(h.element, h.scroller, "task:a", () => h.resize(19.1875));
    assert.equal(h.scroller.scrollTop, before);
    assert.equal(h.writes(), 0);
  }
});

test("hidden, detached, or different-source readers never restore an old position", () => {
  for (const mutate of [h => { h.element.hidden = true; }, h => { h.element.isConnected = false; },
    h => { h.element.dataset.readerSource = "task:b"; }, h => { delete h.element.dataset.readerSource; }]) {
    for (const during of [false, true]) {
      const h = statusHarness();
      if (!during) mutate(h);
      preserveReaderPosition(h.element, h.scroller, "task:a", () => { h.resize(19.1875); if (during) mutate(h); });
      assert.equal(h.scroller.scrollTop, 1087);
      assert.equal(h.writes(), 0);
    }
  }
});

test("a later history response takes a fresh position after user scrolling", () => {
  const h = statusHarness({ nested: true });
  preserveReaderPosition(h.element, h.scroller, "task:a", () => h.resize(19.1875));
  h.scroller.scrollTop += 200;
  const before = h.element.getBoundingClientRect().top;
  preserveReaderPosition(h.element, h.scroller, "task:a", () => h.resize(40));
  assert.equal(h.element.getBoundingClientRect().top, before);
  assert.equal(h.scroller.scrollTop, 1346.1875);
});

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

test("edition anchors use current scroll after eager or layout-triggered native compensation", () => {
  for (const native of ["none", "eager", "layout"]) {
    let scroll = 1000, y = 1140, pending = false;
    const scroller = { ownerDocument: {}, get scrollTop() { return scroll; }, set scrollTop(value) { scroll = value; } };
    scroller.ownerDocument.scrollingElement = scroller;
    const heading = { tagName: "H2", textContent: "Reading outline", getBoundingClientRect() {
      if (pending) { scroll += 1187; pending = false; }
      return { top: y - scroll, bottom: y - scroll + 35 };
    } };
    const element = { dataset: { readerSource: "task:a", readerRevision: "before" }, querySelectorAll: () => [heading] };
    renderEditionStable(element, scroller, "task:a", "after", () => {
      y += 1187;
      if (native === "eager") scroll += 1187;
      if (native === "layout") pending = true;
    });
    assert.equal(heading.getBoundingClientRect().top, 140, native);
    assert.equal(scroll, 2187, native);
  }
});

test("superseded, hidden or detached render callbacks cannot stamp or scroll an obsolete reader", () => {
  for (const invalidate of [element => { element.isConnected = false; }, element => { element.hidden = true; },
    element => { element.dataset.readerSource = "material:new"; },
    element => { element.dataset.readerRevision = "newer-same-source"; }]) {
    const element = { isConnected: true, hidden: false,
      dataset: { readerSource: "task:a", readerRevision: "before" }, querySelectorAll: () => [] };
    const scroller = { scrollTop: 1000 };
    renderEditionStable(element, scroller, "task:a", "after", () => { invalidate(element); scroller.scrollTop = 200; });
    assert.equal(scroller.scrollTop, 200, "Preserve the newer view's scroll");
    assert.notEqual(element.dataset.readerRevision, "after");
  }
});
