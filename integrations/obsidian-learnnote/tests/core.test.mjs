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

test("personal text and whitespace survive repeated sync byte for byte", () => {
  const personal = "## 我的补充  \r\n\r\n  保留缩进 café 🧭\t\r\n\r\n  ";
  let note = "旧生成内容\n\n" + personal;
  for (let revision = 0; revision < 3; revision++) {
    note = mergeGeneratedNote(note, "frontmatter", `新版 ${revision}`);
    assert.equal(note.slice(note.indexOf(PERSONAL_SECTION)), personal);
  }
});

test("legacy prefix additions and unrecognized notes are never discarded", () => {
  const prefix = "\n  标记之前的个人文字\t\n";
  const suffix = "\n\n## 我的补充\n末尾个人文字  ";
  let note = `---\nlearnnote_task_id: task-2\n---\n${prefix}%% learnnote:generated:start %%旧内容%% learnnote:generated:end %%${suffix}`;
  note = mergeGeneratedNote(note, "frontmatter", "新内容");
  assert.ok(note.includes(prefix));
  assert.ok(note.includes(suffix));
  assert.ok(!note.includes("旧内容"));
  const preserved = note.slice(note.indexOf(PERSONAL_SECTION));
  assert.equal(mergeGeneratedNote(note, "frontmatter", "再次同步").split("再次同步\n\n")[1], preserved);
  for (const original of ["无分隔符的个人内容\t\n", `prefix\n%% learnnote:generated:start %%\n## 我的补充\n尾部`]) {
    const first = mergeGeneratedNote(original, "frontmatter", "generated");
    assert.ok(first.includes(original));
    const second = mergeGeneratedNote(first, "frontmatter", "new generated");
    assert.equal(second.slice(second.indexOf(PERSONAL_SECTION)), first.slice(first.indexOf(PERSONAL_SECTION)));
  }
});

test("legacy marker examples inside personal text are never interpreted as generated content", () => {
  const personal = "## 我的补充\n\n保留全部\n%% learnnote:generated:start %%\n用户记录的示例\n%% learnnote:generated:end %%\n末尾  ";
  const synced = mergeGeneratedNote(`旧笔记\n\n${personal}`, "frontmatter", "新笔记");
  assert.equal(synced.slice(synced.indexOf(PERSONAL_SECTION)), personal);
});

test("timestamps are readable", () => {
  assert.equal(formatTimestamp(65.9), "00:01:05");
  assert.equal(formatTimestamp(3723), "01:02:03");
});
