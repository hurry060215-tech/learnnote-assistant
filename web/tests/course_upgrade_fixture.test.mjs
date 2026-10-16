import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import vm from "node:vm";
import fixture from "../../scripts/course-upgrade-acceptance.cjs";

const { childEventStream } = fixture;
const url = new URL("http://127.0.0.1:18940/api/tasks/visual-child/events/stream?after=0");
const child = { id: "visual-child", status: "queued", mode: "video", source_task_id: "video-a" };

test("fresh visual fixture renders queued through production status precedence without inherited caption summary", () => {
  const source = { id: "video-a", title: "Original captions", status: "success", mode: "subtitle_only", summary_source: "subtitle-extract", transcript_path: "transcript.json" };
  const before = JSON.stringify(source), selected = { ...fixture.queuedVisualChild(source), kind: "task" };
  assert.equal(JSON.stringify(source), before); assert.equal(selected.summary_source, ""); assert.equal(selected.transcript_path, "");
  const panel = { dataset: {}, querySelector: () => null, querySelectorAll: () => [] };
  const state = { selected, model: {}, health: {} }, nodes = { taskStatus: panel, regenerate: {} };
  const context = vm.createContext({ state, taskEvents: new Map(), $: id => nodes[id], esc: String,
    timelineHtml: () => "", taskExplanation: () => "", mountQueueControls() {}, api() {}, refresh() {} });
  const desk = fs.readFileSync(new URL("../desk.js", import.meta.url), "utf8");
  vm.runInContext(desk.slice(desk.indexOf("function statusLabel("), desk.indexOf("function refresh(")), context);
  vm.runInContext(desk.slice(desk.indexOf("function renderTaskStatus("), desk.indexOf("async function loadAnnotations(")), context);
  assert.equal(context.statusLabel({ ...selected, summary_source: "subtitle-extract" }), "字幕已提取", "Production gives inherited summary precedence over queued state");
  assert.equal(context.statusLabel(selected), "排队中");
  context.renderTaskStatus(false);
  assert.match(panel.innerHTML, /^<div class="task-status-heading"><strong>排队中<\/strong>/);
  assert.equal(panel.dataset.status, "queued");
});

test("admitted child retains source title, has no completed artifacts, and hides fresh-upgrade action", () => {
  const source = { id: "video-a", title: "Original captions", page_url: "https://example.test/course?p=2", status: "success",
    summary_source: "subtitle-extract", note_path: "note.md", transcript_path: "transcript.json", media_path: "source.mp4",
    artifact_status: { draft_available: true }, frame_grids: [{ path: "old-grid.jpg" }], progress: 100 };
  const originals = JSON.stringify(source), tasks = [source], episode = { task_id: source.id, caption_upgrade_available: true, upgrades: [] };
  const selected = fixture.admitVisualChild(source, episode, tasks);
  assert.equal(selected.title, source.title); assert.equal(selected.page_url, source.page_url); assert.equal(selected.source_task_id, source.id);
  for (const field of ["summary_source", "summary_warning", "transcript_path", "note_path", "media_path", "source_media_path", "audio_path", "subtitle_path", "visual_index_path"])
    assert.equal(selected[field], "", field);
  assert.deepEqual(selected.frame_grids, []); assert.deepEqual(selected.visual_windows, []); assert.equal(selected.artifact_status, undefined);
  assert.equal(selected.progress, 0); assert.equal(selected.status, "queued"); assert.equal(selected.phase, "queued");
  assert.equal(episode.caption_upgrade_available, false); assert.equal(episode.task_id, source.id);
  assert.deepEqual(episode.upgrades, [{ task_id: selected.id, status: "queued" }]);
  assert.equal(tasks.length, 2); assert.equal(JSON.stringify(source), originals);
  const edition = fixture.fixtureEdition(selected); assert.equal(edition.text, ""); assert.equal(edition.edited, false);

  const reader = { dataset: {} }, state = { selected: { ...selected, kind: "task" }, text: edition.text, edition, revision: edition.revision };
  const context = vm.createContext({ state, $: id => id === "document" ? reader : id === "annotations" ? { dataset: {} } : undefined, esc: String,
    sectionReader: { clear() {} }, LearnNoteMarkdown: { configure() {}, markdownToHtml() { throw new Error("Empty queued note must not fabricate Markdown"); } },
    api() {}, canOcrMaterial: () => false, mountMaterialOcr() {}, collapseSourceReviews() {}, decorateSourceTimes() {}, loadClaimTimeline() {},
    Event, window: { dispatchEvent() {} } });
  const desk = fs.readFileSync(new URL("../desk.js", import.meta.url), "utf8");
  vm.runInContext(desk.slice(desk.indexOf("function renderNote("), desk.indexOf("function decorateSourceTimes(")), context);
  context.renderNote();
  assert.match(reader.innerHTML, /^<h1>Original captions<\/h1>/);
  assert.match(reader.innerHTML, /笔记准备好后会显示在这里，你可以先查看处理进度。/);
});

test("synthetic queued child serves an idle SSE heartbeat without changing identity or state", () => {
  const tasks = [structuredClone(child)], before = JSON.stringify(tasks);
  const response = childEventStream("GET", url, {}, tasks);
  assert.equal(response.contentType, "text/event-stream");
  assert.equal(response.headers["Cache-Control"], "no-cache, no-transform");
  assert.equal(response.body, ": heartbeat\n\n");
  assert.equal(JSON.stringify(tasks), before);
});

test("synthetic stream is exact, GET-only, cursor-bound and available only after admission", () => {
  assert.equal(childEventStream("POST", url, {}, [child]), null);
  assert.equal(childEventStream("GET", new URL("/api/tasks/other/events/stream?after=0", url), {}, [child]), null);
  for (const query of ["", "?after=1", "?after=0&extra=1", "?after=0&after=0"])
    assert.throws(() => childEventStream("GET", new URL(url.pathname + query, url), {}, [child]));
  assert.throws(() => childEventStream("GET", url, { "last-event-id": "1" }, [child]));
  assert.throws(() => childEventStream("GET", url, {}, []), /before upgrade admission/);
  for (const change of [{ status: "success" }, { mode: "subtitle_only" }, { source_task_id: "other" }])
    assert.throws(() => childEventStream("GET", url, {}, [{ ...child, ...change }]));
});
