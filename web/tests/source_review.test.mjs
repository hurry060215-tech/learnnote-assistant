import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
const code = readFileSync(new URL("../source-review.js", import.meta.url), "utf8");
const { collapseSourceReviews } = await import("data:text/javascript;base64," + Buffer.from(code).toString("base64"));
class Node {
  constructor(tag, text = "") { this.tagName = tag.toUpperCase(); this.nodeType = tag === "#text" ? 3 : 1; this.children = []; this.dataset = {}; this.parentElement = null; this.value = text; }
  get textContent() { return this.value + this.children.map(node => node.textContent).join(""); }
  set textContent(value) { this.value = value; this.children = []; }
  append(...nodes) { for (const node of nodes) { node.parentElement = this; this.children.push(node); } }
  matches(selector) { return selector.split(",").some(value => value === "[data-source-reviews]" ? "sourceReviews" in this.dataset : value.toUpperCase() === this.tagName); }
  closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector); }
  querySelectorAll(selector) { return this.children.flatMap(node => [...(node.matches(selector) ? [node] : []), ...node.querySelectorAll(selector)]); }
  get nextSibling() { return this.parentElement?.children[this.parentElement.children.indexOf(this) + 1]; }
  cloneNode(deep) { const copy = new Node(this.tagName, this.value); copy.href = this.href; if (deep) copy.append(...this.children.map(node => node.cloneNode(true))); return copy; }
  replaceWith(node) { const parent = this.parentElement; parent.children[parent.children.indexOf(this)] = node; node.parentElement = parent; this.parentElement = null; }
  setAttribute(key, value) { this[key] = value; }
  scrollIntoView(options) { this.scroll = options; }
}
const marker = () => new Node("strong", "【待核对：仅定位到来源】");
function setup() {
  globalThis.document = { createElement: tag => new Node(tag) };
  globalThis.matchMedia = () => ({ matches: true });
  return new Node("main");
}
test("review controls preserve exact body and links and expand the matching notice", () => {
  const root = setup(), paragraph = new Node("p"), link = new Node("a", "00:12");
  link.href = "https://example.com/watch?t=12";
  paragraph.append(marker(), new Node("#text", " First statement "), link, marker(), new Node("#text", " Second statement")); root.append(paragraph);
  collapseSourceReviews(root);
  const panel = root.querySelectorAll("details")[0], items = panel.querySelectorAll("section"), buttons = paragraph.querySelectorAll("button");
  assert.equal(panel.open, undefined); assert.equal(buttons.length, 2);
  assert.match(paragraph.textContent, /First statement.*Second statement/);
  assert.match(items[0].textContent, /First statement/); assert.doesNotMatch(items[0].textContent, /Second statement/);
  assert.equal(items[0].querySelectorAll("a")[0].href, link.href);
  assert.equal(paragraph.querySelectorAll("a")[0], link, "original link remains available");
  buttons[1].onclick(); assert.equal(panel.open, true); assert.equal(items[1].scroll.behavior, "instant");
  collapseSourceReviews(root); assert.equal(root.querySelectorAll("details").length, 1, "repeat rendering cannot duplicate notices");
});
test("stronger warnings and code, quoted, heading and link examples stay in place", () => {
  const root = setup();
  for (const tag of ["code", "pre", "blockquote", "h2", "a"]) { const node = new Node(tag); node.append(marker()); root.append(node); }
  const pending = new Node("strong", "【待核对：未找到支持来源】"), inference = new Node("strong", "【推断：需回源核对】");
  root.append(pending, inference); collapseSourceReviews(root);
  assert.equal(root.querySelectorAll("details").length, 0);
  assert.equal(root.querySelectorAll("strong").length, 7); assert.equal(pending.parentElement, root); assert.equal(inference.parentElement, root);
});
test("a dangling notice retains an explicit review record rather than disappearing", () => {
  const root = setup(), paragraph = new Node("p"); paragraph.append(marker()); root.append(paragraph);
  collapseSourceReviews(root); assert.match(root.querySelectorAll("details")[0].textContent, /尚未验证支持.*没有正文/s);
});
