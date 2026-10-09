import assert from "node:assert/strict";
import test from "node:test";
import {
  PERSONAL_SECTION,
  formatTimestamp,
  importedTaskId,
  mergeGeneratedNote,
  normalizeBackendUrl,
  safeArchivePath,
  sanitizeVaultSegment,
  taskFolderPath,
  taskFolderCandidates
} from "../src/core.mjs";

test("backend URL only accepts the local LearnNote service", () => {
  assert.equal(normalizeBackendUrl("http://127.0.0.1:8765/"), "http://127.0.0.1:8765");
  assert.equal(normalizeBackendUrl("http://localhost:8765"), "http://localhost:8765");
  assert.throws(() => normalizeBackendUrl("https://example.com"), /本机/);
});

test("vault paths are stable and remove unsafe characters", () => {
  assert.equal(sanitizeVaultSegment('课程: 01 / 入门?'), "课程 01 入门");
  assert.equal(taskFolderPath("LearnNote/课程", "A/B", "abc"), "LearnNote/课程/A B--abc");
  assert.equal(taskFolderPath("../LearnNote/./课程", "A/B", "abc"), "LearnNote/课程/A B--abc");
});

test("Unicode names keep complete NFC codepoints and byte-safe folder segments", () => {
  const name = "a".repeat(89) + "🧭";
  assert.equal(sanitizeVaultSegment(name), name);
  assert.ok(sanitizeVaultSegment(name).isWellFormed());
  assert.equal(sanitizeVaultSegment("cafe\u0301"), "café");
  for (const value of ["中文".repeat(100), "日本語🧭".repeat(100), "🧭".repeat(100)]) {
    assert.ok(Buffer.byteLength(sanitizeVaultSegment(value), "utf8") <= 180);
    const folder = taskFolderPath("LearnNote", value, "abc123def456").split("/").at(-1);
    assert.ok(folder.isWellFormed()); assert.ok(Buffer.byteLength(folder, "utf8") <= 240);
    assert.ok(folder.endsWith("--abc123def456"));
  }
});

test("NFC paths keep identity and existing legacy note lookup without traversal", () => {
  assert.equal(sanitizeVaultSegment(" /:*? "), "LearnNote");
  assert.equal(taskFolderPath("../LearnNote/./课程", "cafe\u0301", "one"), "LearnNote/课程/café--one");
  assert.notEqual(taskFolderPath("LearnNote", "café", "one"), taskFolderPath("LearnNote", "café", "two"));
  assert.deepEqual(taskFolderCandidates("LearnNote", "cafe\u0301", "one"), ["LearnNote/café--one", "LearnNote/cafe\u0301--one"]);
  assert.equal(safeArchivePath("中文/../secret.md"), "");
});

test("archive traversal paths are rejected", () => {
  assert.equal(safeArchivePath("grids/grid_001.jpg"), "grids/grid_001.jpg");
  assert.equal(safeArchivePath("../secret.txt"), "");
  assert.equal(safeArchivePath("/absolute.txt"), "");
});

test("sync replaces generated content and preserves personal notes", () => {
  const frontmatter = "---\nlearnnote_task_id: \"task-1\"\n---";
  const first = mergeGeneratedNote("", frontmatter, "第一版");
  const edited = `${first}\n用户自己的补充`;
  const synced = mergeGeneratedNote(edited, frontmatter, "第二版");
  assert.ok(synced.includes(PERSONAL_SECTION));
  assert.ok(synced.includes("第二版"));
  assert.ok(!synced.includes("第一版"));
  assert.ok(synced.includes("用户自己的补充"));
  assert.equal(importedTaskId(synced), "task-1");
});

test("sync removes legacy markers while preserving personal content", () => {
  const legacy = "---\nlearnnote_task_id: task-2\n---\n\n<!-- learnnote:generated:start -->\n旧内容\n<!-- learnnote:generated:end -->\n\n## 我的补充\n保留我";
  const synced = mergeGeneratedNote(legacy, "ignored", "新内容");
  assert.ok(!synced.includes("<!-- learnnote:generated:start -->"));
  assert.ok(!synced.includes("%% learnnote:generated:start %%"));
  assert.ok(synced.includes("保留我"));
});

test("timestamps are readable", () => {
  assert.equal(formatTimestamp(65.9), "00:01:05");
  assert.equal(formatTimestamp(3723), "01:02:03");
});
