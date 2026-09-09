import assert from "node:assert/strict";
import test from "node:test";
import { createDraftStore } from "../desk-drafts.js";

function memoryStorage() {
  const items = new Map();
  return {
    getItem: (key) => items.get(key),
    setItem: (key, value) => items.set(key, value),
    removeItem: (key) => items.delete(key),
  };
}
test("assistant drafts recover after reload and remain scoped to each source", () => {
  const storage = memoryStorage(),
    first = createDraftStore(storage);
  first.set("global", "如何导出笔记？");
  first.set("task:abc123", "解释这一段\n保留换行");
  const reloaded = createDraftStore(storage);
  assert.equal(reloaded.get("global"), "如何导出笔记？");
  assert.equal(reloaded.get("task:abc123"), "解释这一段\n保留换行");
  assert.equal(reloaded.get("material:abc123"), "");
  reloaded.set("global", "");
  assert.equal(createDraftStore(storage).get("global"), "");
  assert.equal(
    createDraftStore(storage).get("task:abc123"),
    "解释这一段\n保留换行",
  );
});
test("unavailable or malformed browser storage does not prevent drafting", () => {
  for (const storage of [
    null,
    {
      getItem() {
        throw Error("blocked");
      },
      setItem() {
        throw Error("quota");
      },
    },
    { getItem: () => "not json" },
  ]) {
    const drafts = createDraftStore(storage);
    assert.equal(drafts.set("global", "保留当前页面的输入"), false);
    assert.equal(drafts.get("global"), "保留当前页面的输入");
  }
});
test("draft storage is bounded and excludes invalid source scopes", () => {
  const storage = memoryStorage(),
    drafts = createDraftStore(storage);
  drafts.set("__proto__", "invalid");
  drafts.set("global", "x".repeat(1500));
  assert.equal(drafts.get("global").length, 1000);
  for (let i = 0; i < 40; i++) drafts.set(`task:task-${i}`, `问题 ${i}`);
  const saved = JSON.parse(storage.getItem("learnnote.assistant.drafts"));
  assert.equal(Object.keys(saved).length, 30);
  assert.equal(saved["task:task-39"].text, "问题 39");
  assert.equal(Object.hasOwn(saved, "__proto__"), false);
});
