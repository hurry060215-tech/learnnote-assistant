/** Exercises the real importer with synthetic ZIP bytes and an in-memory vault. */
import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test, { after } from "node:test";
import esbuild from "esbuild";
import { strToU8, zipSync } from "fflate";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const output = await mkdtemp(path.join(tmpdir(), "learnnote-importer-"));
after(() => rm(output, { recursive: true, force: true }));
const modulePath = path.join(output, "importer.mjs");
await esbuild.build({
  stdin: {
    contents: `export { LearnNoteImporter } from "./src/importer.ts";
      export { LearnNoteApi } from "./src/api.ts";
      export { TFile, TFolder } from "obsidian";`,
    resolveDir: root,
    loader: "ts"
  },
  outfile: modulePath, bundle: true, platform: "node", format: "esm",
  plugins: [{ name: "memory-vault", setup(build) {
    build.onResolve({ filter: /^obsidian$/ }, () => ({ path: "obsidian", namespace: "fixture" }));
    build.onLoad({ filter: /.*/, namespace: "fixture" }, () => ({ loader: "js", contents: `
      export class TFile { constructor(path, content = "") { this.path = path; this.content = content; } }
      export class TFolder { constructor(path) { this.path = path; } }
      export const normalizePath = value => String(value).replace(/\\\\/g, "/").replace(/\\/{2,}/g, "/");
      export const requestUrl = init => globalThis.learnNoteRequestFixture(init);
    ` }));
  } }]
});
const { LearnNoteImporter, LearnNoteApi, TFile, TFolder } = await import(pathToFileURL(modulePath));

const task = { id: "synthetic-task", title: "映射验收 café 🧭", status: "success" };
const annotation = {
  id: "original-annotation-id", text: "  原样保留 café 🧭\t\n\n", quote: "字幕原句", revision: "original-annotation-revision",
  anchor: { kind: "transcript", source_task_id: task.id, evidence_id: "transcript-1", start: 12, end: 18, source_revision: "original-source", target_hash: "original-target" },
  anchor_status: { resolution: "exact", stale: false, current_revision: "generated-1" }
};
const payload = (items = [annotation]) => ({ schema_version: 2, task_id: task.id, annotations: items });

function fixture(initial = payload()) {
  const files = new Map();
  const writes = [];
  const create = async (filePath, content) => {
    assert.ok(!files.has(filePath), `create must not overwrite ${filePath}`);
    const file = new TFile(filePath, content); files.set(filePath, file); writes.push(filePath); return file;
  };
  const modify = async (file, content) => { file.content = content; writes.push(file.path); };
  const app = {
    vault: {
      getAbstractFileByPath: p => files.get(p),
      createFolder: async p => { const folder = new TFolder(p); files.set(p, folder); return folder; },
      create, modify, read: async file => file.content,
      createBinary: create, modifyBinary: modify
    },
    workspace: { getLeaf: () => ({ openFile: async () => {} }) }
  };
  const state = { personal: initial, generated: "# 新生成内容\n\n仅来自生成笔记。" };
  const api = { bundle: async () => {
    const entries = { "note.md": strToU8(state.generated) };
    if (state.personal !== undefined) entries["personal_annotations.json"] = strToU8(
      typeof state.personal === "string" ? state.personal : JSON.stringify(state.personal));
    return Uint8Array.from(zipSync(entries)).buffer;
  } };
  const settings = { targetFolder: "LearnNote", includeManifest: false, includeTranscript: false,
    includeVisualWindows: false, includeQaHistory: false, openAfterImport: false };
  const importer = new LearnNoteImporter(app, api, () => settings);
  const snapshots = () => [...files.entries()].filter(([name]) => /\/Personal annotations\/.*\.json$/.test(name));
  const latest = result => {
    const metadata = JSON.parse(files.get(`${result.folderPath}/_learnnote.json`).content);
    return files.get(`${result.folderPath}/${metadata.annotation_snapshot}`);
  };
  return { files, writes, app, state, importer, snapshots, latest };
}

test("actual API opts in to personal mapping on the existing local bundle route", async () => {
  const calls = [];
  globalThis.learnNoteRequestFixture = async init => { calls.push(init); return { status: 200, arrayBuffer: new ArrayBuffer(0) }; };
  try {
    await new LearnNoteApi(() => "http://127.0.0.1:8765").bundle("synthetic task");
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "http://127.0.0.1:8765/api/tasks/synthetic%20task/exports/bundle?include_annotations=true");
    assert.equal(calls[0].method, "GET");
  } finally { delete globalThis.learnNoteRequestFixture; }
});

test("actual importer preserves exact personal content and ID mapping through regeneration and retry", async () => {
  const f = fixture();
  const first = await f.importer.importTask(task);
  const note = f.files.get(first.notePath);
  const personal = "## 我的补充  \r\n\r\n  本地个人文字 🧭\t\r\n  ";
  note.content = note.content.slice(0, note.content.indexOf("## 我的补充")) + personal;
  const stored = JSON.parse(f.snapshots()[0][1].content).annotations[0];
  assert.equal(stored.id, annotation.id);
  assert.equal(stored.text, annotation.text);
  assert.deepEqual(stored.anchor, annotation.anchor);
  assert.equal(stored.anchor_status.resolution, "exact");
  assert.ok(f.latest(first).content.includes(annotation.text));
  assert.ok(!note.content.slice(0, note.content.indexOf("## 我的补充")).includes(annotation.text));
  const snapshotPath = f.snapshots()[0][0];
  const snapshotWrites = f.writes.filter(name => name.includes("/Personal annotations/")).length;
  for (let revision = 2; revision <= 4; revision++) {
    f.state.generated = `# 重新生成 ${revision}`;
    f.state.personal = payload([{ ...annotation, anchor_status: { ...annotation.anchor_status, current_revision: `generated-${revision}` } }]);
    const retry = await f.importer.importTask(task);
    assert.equal(retry.created, false);
    assert.equal(note.content.slice(note.content.indexOf("## 我的补充")), personal);
    assert.ok(note.content.includes(f.state.generated));
    assert.equal(f.snapshots().length, 1);
    assert.equal(f.snapshots()[0][0], snapshotPath);
  }
  assert.equal(f.writes.filter(name => name.includes("/Personal annotations/")).length, snapshotWrites);
});

test("remote revisions, unresolved anchors and deletions preserve every historical snapshot", async () => {
  const f = fixture();
  const first = await f.importer.importTask(task);
  const original = f.snapshots()[0];
  const originalBytes = original[1].content;
  f.state.personal = payload([{ ...annotation, revision: 2, text: "更新后的个人文字", anchor_status: { resolution: "orphaned", stale: true, reason: "ambiguous_target" } }]);
  const changed = await f.importer.importTask(task);
  assert.equal(f.snapshots().length, 2);
  assert.equal(original[1].content, originalBytes);
  assert.ok(f.latest(changed).content.includes("未定位，请人工核对原文"));
  assert.ok(f.latest(changed).content.includes("ambiguous_target"));
  assert.equal(JSON.parse(f.snapshots()[1][1].content).annotations[0].id, annotation.id);
  f.state.personal = payload([]);
  const deleted = await f.importer.importTask(task);
  assert.equal(f.snapshots().length, 3);
  assert.ok(f.latest(deleted).content.includes("此前导入的版本仍然保留"));
  assert.equal(original[1].content, originalBytes);
  assert.ok(f.files.get(first.notePath).content.includes("个人批注（0 条）"));
});

test("multi-cue interval mappings and literal text survive snapshot retries and local edits", async () => {
  const interval = { ...annotation, text: "\r\n  Multi-cue cafe\u0301 🧭\r\n ", anchor: { ...annotation.anchor,
    evidence_id: "task-synthetic-task-transcript-00000..00001", start: 12, end: 21,
    cues: [{ evidence_id: "task-synthetic-task-transcript-00000", start: 12, end: 18, target_hash: "first-exact-cue" },
      { evidence_id: "task-synthetic-task-transcript-00001", start: 16, end: 21, target_hash: "second-exact-cue" }] } };
  const f = fixture(payload([interval]));
  const first = await f.importer.importTask(task);
  const jsonFile = f.snapshots()[0][1], markdownFile = f.latest(first);
  const stored = JSON.parse(jsonFile.content).annotations[0];
  assert.equal(stored.id, interval.id); assert.equal(stored.text, interval.text);
  assert.deepEqual(stored.anchor, interval.anchor);
  assert.ok(markdownFile.content.includes("00:00:12 – 00:00:21"));
  assert.ok(markdownFile.content.includes(interval.text));
  await f.importer.importTask(task); assert.equal(f.snapshots().length, 1);
  markdownFile.content += "\r\n  Local interval explanation.\r\n";
  const local = markdownFile.content, original = jsonFile.content;
  f.state.personal = payload([{ ...interval, anchor_status: { resolution: "orphaned", stale: true, reason: "ambiguous_target" } }]);
  const changed = await f.importer.importTask(task);
  assert.equal(markdownFile.content, local); assert.equal(jsonFile.content, original);
  assert.ok(f.latest(changed).content.includes("未定位，请人工核对原文"));
  assert.deepEqual(JSON.parse(f.snapshots()[1][1].content).annotations[0].anchor, interval.anchor);
});

test("local JSON or Markdown conflicts get another snapshot and remain byte-for-byte intact", async () => {
  const f = fixture();
  const first = await f.importer.importTask(task);
  const jsonFile = f.snapshots()[0][1];
  const markdownFile = f.latest(first);
  jsonFile.content = "用户在 JSON 中的本地修改\t\n";
  markdownFile.content += "\n本地 Markdown 补充\t  ";
  const localJson = jsonFile.content, localMarkdown = markdownFile.content;
  const changed = await f.importer.importTask(task);
  assert.equal(jsonFile.content, localJson);
  assert.equal(markdownFile.content, localMarkdown);
  assert.equal(f.snapshots().length, 2);
  assert.ok(f.latest(changed).path.endsWith("-2.md"));
  assert.ok(f.latest(changed).content.includes("-2.json|JSON 映射"));
  assert.ok(f.files.get(changed.notePath).content.includes("检测到本地版本，已另存快照"));
  await f.importer.importTask(task);
  assert.equal(f.snapshots().length, 2);
  assert.equal(jsonFile.content, localJson);
  assert.equal(markdownFile.content, localMarkdown);
});

for (const [label, newline] of [["LF", "\n"], ["CRLF", "\r\n"]]) {
  test(`${label} code-like text and quote retain exact newlines, blank lines, NFD and old ID through retries and conflicts`, async () => {
    const exact = `${newline}${newline}  const cafe\u0301 = "🧭";${newline}\treturn x;${newline}${newline}`;
    const original = { ...annotation, id: "old-preserved-id", text: exact, quote: exact };
    const f = fixture(payload([original]));
    const first = await f.importer.importTask(task);
    const note = f.files.get(first.notePath);
    const personal = `## 我的补充  \r\n${exact}\r\n\r\n`;
    note.content = note.content.slice(0, note.content.indexOf("## 我的补充")) + personal;
    const originalJson = f.snapshots()[0][1];
    const originalMarkdown = f.latest(first);
    const assertExact = result => {
      const markdown = f.latest(result);
      const json = f.files.get(markdown.path.replace(/\.md$/, ".json"));
      const item = JSON.parse(json.content).annotations[0];
      assert.equal(item.id, "old-preserved-id");
      assert.equal(item.text, exact);
      assert.equal(item.quote, exact);
      assert.notEqual(item.text, exact.normalize("NFC"), "decomposed Unicode must not be normalized");
      assert.equal(markdown.content.split(exact).length - 1, 2, "both text and quote appear unchanged");
      assert.equal(note.content.slice(note.content.indexOf("## 我的补充")), personal);
    };
    assertExact(first);
    const second = await f.importer.importTask(task);
    assertExact(second);
    assert.equal(f.snapshots().length, 1);

    const localItem = { ...original, text: exact + `\tlocal ${label}${newline}`, quote: `${newline}${exact}` };
    originalJson.content = JSON.stringify(payload([localItem]), null, 2) + newline;
    originalMarkdown.content += `${newline}${exact}\tlocal Markdown${newline}${newline}`;
    const localJsonBytes = originalJson.content, localMarkdownBytes = originalMarkdown.content;
    for (let retry = 0; retry < 2; retry++) {
      const imported = await f.importer.importTask(task);
      assertExact(imported);
      assert.equal(f.snapshots().length, 2);
      assert.equal(originalJson.content, localJsonBytes);
      assert.equal(originalMarkdown.content, localMarkdownBytes);
      const local = JSON.parse(originalJson.content).annotations[0];
      assert.equal(local.id, "old-preserved-id");
      assert.equal(local.text, localItem.text);
      assert.equal(local.quote, localItem.quote);
    }
  });
}

test("missing, malformed or misidentified sidecars retain and link the previous snapshot", async () => {
  const f = fixture();
  const first = await f.importer.importTask(task);
  const previous = f.latest(first);
  const bytes = previous.content;
  for (const invalid of [undefined, "{invalid json", { ...payload(), task_id: "another-task" }, payload([annotation, annotation])]) {
    f.state.personal = invalid;
    const imported = await f.importer.importTask(task);
    assert.equal(f.latest(imported), previous);
    assert.equal(previous.content, bytes);
    assert.equal(f.snapshots().length, 1);
    assert.ok(f.files.get(imported.notePath).content.includes("本次未刷新"));
  }
});

test("partial snapshot creation resumes without rewriting the existing half", async () => {
  const f = fixture();
  const create = f.app.vault.create;
  let interrupted = false;
  f.app.vault.create = async (filePath, content) => {
    if (!interrupted && /\/Personal annotations\/.*\.md$/.test(filePath)) {
      interrupted = true;
      throw new Error("synthetic interrupted write");
    }
    return create(filePath, content);
  };
  await assert.rejects(f.importer.importTask(task), /synthetic interrupted write/);
  assert.equal(f.snapshots().length, 1);
  const preserved = f.snapshots()[0][1].content;
  const retried = await f.importer.importTask(task);
  assert.equal(f.snapshots().length, 1);
  assert.equal(f.snapshots()[0][1].content, preserved);
  assert.ok(f.latest(retried).content.includes(annotation.id));
});
