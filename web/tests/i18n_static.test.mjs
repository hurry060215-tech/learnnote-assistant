import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const source = fs.readFileSync(path.join(root, "web", "i18n.js"), "utf8");

function makeTextDocument(node) {
  const rootElement = { contains: () => true };
  return {
    body: {},
    querySelectorAll: () => [rootElement],
    createTreeWalker: () => {
      let visited = false;
      return { nextNode: () => (visited ? null : ((visited = true), node)) };
    }
  };
}

test("static UI copy translates and restores non-user text", () => {
  const node = { nodeValue: "完成后打开笔记", parentElement: { closest: () => null } };
  const context = {};
  vm.runInNewContext(source, context);
  const document = makeTextDocument(node);

  context.LearnNoteI18n.applyStatic(document, "en-US");
  assert.equal(node.nodeValue, "Open the note when complete");
  context.LearnNoteI18n.applyStatic(document, "zh-CN");
  assert.equal(node.nodeValue, "完成后打开笔记");
});

test("static UI copy translates accessibility attributes", () => {
  const attributes = new Map([["aria-label", "主导航"], ["placeholder", "搜索术语或问题"]]);
  const element = {
    closest: () => null,
    getAttribute: name => attributes.get(name) || null,
    setAttribute: (name, value) => attributes.set(name, String(value))
  };
  const root = { contains: () => true, querySelectorAll: () => [element] };
  const document = {
    body: {},
    querySelectorAll: () => [root],
    createTreeWalker: () => ({ nextNode: () => null })
  };
  const context = {};
  vm.runInNewContext(source, context);

  context.LearnNoteI18n.applyStatic(document, "en-US");
  assert.equal(attributes.get("aria-label"), "Main navigation");
  assert.equal(attributes.get("placeholder"), "Search terms or questions");
  context.LearnNoteI18n.applyStatic(document, "zh-CN");
  assert.equal(attributes.get("aria-label"), "主导航");
  assert.equal(attributes.get("placeholder"), "搜索术语或问题");
});

test("static UI copy rebinds dynamically rendered text without losing the Chinese source", () => {
  const node = { nodeValue: "完成后打开笔记", parentElement: { closest: () => null } };
  const context = {};
  vm.runInNewContext(source, context);
  const document = makeTextDocument(node);

  context.LearnNoteI18n.applyStatic(document, "en-US");
  assert.equal(node.nodeValue, "Open the note when complete");
  node.nodeValue = "搜索术语或问题";
  context.LearnNoteI18n.applyStatic(document, "en-US");
  assert.equal(node.nodeValue, "Search terms or questions");
  context.LearnNoteI18n.applyStatic(document, "zh-CN");
  assert.equal(node.nodeValue, "搜索术语或问题");
});
