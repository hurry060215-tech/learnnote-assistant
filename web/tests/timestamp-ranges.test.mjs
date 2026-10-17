import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync, readdirSync } from "node:fs";
import vm from "node:vm";
const source = readFileSync(new URL("../desk-api.js", import.meta.url), "utf8");
const { timestampRanges } = await import(
  "data:text/javascript;base64," + Buffer.from(source).toString("base64")
);
test("MiMo bracket ranges preserve exact visible copy and seek to first timestamp", () => {
  const text = "需要换乘专属列车（[00:53 – 01:00]），再抵达酒店。";
  assert.deepEqual(timestampRanges(text), [
    { index: text.indexOf("["), label: "[00:53 – 01:00]", start: 53, end: 60 },
  ]);
});
test("multiple bracket ranges and hour timestamps retain independent text offsets", () => {
  const result = timestampRanges("A [1:02:03-1:04:05] B [12:10 — 12:40]");
  assert.equal(result.length, 2);
  assert.equal(result[0].start, 3723);
  assert.equal(result[1].start, 730);
});
test("single bracket timestamps remain clickable in statements and source review records", () => {
  const text = "出处 [00:12]，长视频 [1:02:03]，范围 [00:20–00:25]";
  assert.deepEqual(timestampRanges(text), [
    { index: text.indexOf("[00:12]"), label: "[00:12]", start: 12, end: 12 },
    { index: text.indexOf("[1:02:03]"), label: "[1:02:03]", start: 3723, end: 3723 },
    { index: text.indexOf("[00:20"), label: "[00:20–00:25]", start: 20, end: 25 },
  ]);
  assert.deepEqual(timestampRanges("[00:99] [1:60:00] [引用12]"), []);
});
test("invalid seconds, reversed ranges, and ordinary bracket text stay untouched", () => {
  assert.deepEqual(
    timestampRanges(
      "[00:99 – 01:00] [02:00 – 01:00] [参考资料] [1:60:00-2:00:00]",
    ),
    [],
  );
});

const desk = readFileSync(new URL("../desk.js", import.meta.url), "utf8");
const decorator = desk.slice(desk.indexOf("function decorateSourceTimes("), desk.indexOf("const taskEvents ="));
function sourceButton(label) {
  const buttons = [], seeks = [];
  const original = { textContent: label, closest: () => null, parentElement: { closest: () => null }, replaceWith() {} };
  const code = !label.startsWith("["), nodes = code ? [] : [original];
  const context = vm.createContext({ state: { selected: { kind: "task" } }, timestampRanges,
    openSource: async seconds => seeks.push(seconds), failure: error => { throw error; }, NodeFilter: { SHOW_TEXT: 4 },
    document: {
      createElement: () => { const button = { attributes: {}, setAttribute(name, value) { this.attributes[name] = value; } }; buttons.push(button); return button; },
      createTextNode: text => ({ textContent: text }), createDocumentFragment: () => ({ append() {} }),
      createTreeWalker: () => ({ currentNode: null, nextNode() { this.currentNode = nodes.shift(); return Boolean(this.currentNode); } }),
    } });
  vm.runInContext(decorator, context);
  context.decorateSourceTimes({ querySelectorAll: () => code ? [original] : [] });
  assert.equal(buttons.length, 1, `Expected one shipped timestamp button for ${label}`);
  return { button: buttons[0], seeks };
}

function checkConsumerNames(source, file) {
  const names = [...source.matchAll(/getByRole\(\s*["']button["']\s*,\s*\{[^}]*?\bname:\s*(["'])(.*?)\1[^}]*?\bexact:\s*true[^}]*\}/gs)]
    .map(match => match[2]).filter(name => /^查看(?:原文|这一处字幕上下文)\s/.test(name));
  for (const name of names) {
    const label = name.replace(/^查看(?:原文|这一处字幕上下文)\s+/, "");
    const { button, seeks } = sourceButton(label);
    assert.equal(button.attributes["aria-label"], name, `${file}: exact accessible-name selector drifted from shipped decorator`);
    assert.equal(button.textContent, label, "The task-specific visible timestamp must remain intact");
    assert.equal(button.type, "button");
    button.onclick();
    const target = timestampRanges(label.startsWith("[") ? label : `[${label}]`)[0].start;
    assert.deepEqual(seeks, [target], `${file}: source action must retain its exact starting timestamp`);
  }
  return names.length;
}

test("every hosted exact timestamp-role selector matches the shipped decorator and seek target", () => {
  const root = new URL("../../scripts/", import.meta.url), consumers = [];
  for (const file of readdirSync(root, { recursive: true }).filter(name => /\.(cjs|mjs|js)$/.test(name))) {
    if (checkConsumerNames(readFileSync(new URL(file.replaceAll("\\", "/"), root), "utf8"), file)) consumers.push(file);
  }
  assert(consumers.includes("reader-workflow-acceptance.cjs"));
  assert(consumers.includes("progressive-sections-acceptance.cjs"));
});

test("the consumer contract detects the previous stale reader accessible name", () => {
  const reader = readFileSync(new URL("../../scripts/reader-workflow-acceptance.cjs", import.meta.url), "utf8");
  const stale = reader.replace("查看这一处字幕上下文 [00:53 – 01:00]", "查看原文 [00:53 – 01:00]");
  assert.notEqual(reader, stale);
  assert.throws(() => checkConsumerNames(stale, "stale-reader-fixture"), /exact accessible-name selector drifted/);
});
