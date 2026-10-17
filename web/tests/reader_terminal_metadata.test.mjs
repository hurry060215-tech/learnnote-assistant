import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../desk-product.js", import.meta.url), "utf8");
const projection = source.slice(source.indexOf("  function updateReadingContext() {"), source.indexOf('  $("sourceFrames").onclick ='));
assert.ok(projection.includes('$("readerMetadata").textContent'), "exercise the actual shipped projection");
function harness(selected) {
  const state = { selected }, nodes = new Map(), readerNav = {};
  const $ = id => { if (!nodes.has(id)) nodes.set(id, {}); return nodes.get(id); };
  const context = vm.createContext({ window: { addEventListener() {} }, state, $, readerNav, timestamp: () => "5:00" });
  vm.runInContext(projection, context);
  return { state, $, readerNav, update: () => context.updateReadingContext() };
}
const draft = status => ({ kind: "task", id: "retained", status, summary_source: "transcript-draft",
  transcript_path: "transcript.json", note_path: "draft.md", artifact_status: { draft_available: true },
  media_integrity: { duration: 300 }, frame_grids: [] });

test("cancelled and failed retained drafts describe stopped work without changing source data", () => {
  for (const [status, label] of [["cancelled", "已停止"], ["failed", "处理失败"], ["cancelling", "正在停止"]]) {
    const selected = draft(status), before = structuredClone(selected), h = harness(selected);
    h.update();
    assert.equal(h.$("readerMetadata").textContent, `${label} · 字幕已保留 · 5:00`);
    assert.doesNotMatch(h.$("readerMetadata").textContent, /等待总结|正在准备内容/);
    assert.deepEqual(selected, before);
    selected.summary_source = "partial-draft"; h.update();
    assert.equal(h.$("readerMetadata").textContent, `${label} · 字幕已保留 · 5:00`);
  }
});

test("completed retained text does not imply an active summary or fact verification", () => {
  const h = harness(draft("success")); h.update();
  assert.equal(h.$("readerMetadata").textContent, "处理已完成 · 字幕已保留 · 5:00");
  h.state.selected.summary_source = "vision-llm"; h.update();
  assert.equal(h.$("readerMetadata").textContent, "处理已完成 · AI 整理笔记 · 5:00");
  assert.doesNotMatch(h.$("readerMetadata").textContent, /已核验|事实正确/);
});

test("failed work keeps prior generated note provenance without claiming new verification", () => {
  const h = harness({ ...draft("failed"), summary_source: "text-llm", edited: true }); h.update();
  assert.equal(h.$("readerMetadata").textContent, "处理失败 · AI 整理笔记 · 5:00");
  assert.equal(h.state.selected.edited, true);
  assert.equal(h.state.selected.note_path, "draft.md");
});

test("ordinary queued and running subtitle labels remain unchanged", () => {
  for (const status of ["queued", "running"]) {
    const h = harness(draft(status)); h.update();
    assert.equal(h.$("readerMetadata").textContent, "字幕已取得 · 等待总结 · 5:00");
    h.state.selected.transcript_path = null; h.update();
    assert.equal(h.$("readerMetadata").textContent, "正在准备内容 · 5:00");
    h.state.selected.summary_source = "subtitle-extract"; h.update();
    assert.equal(h.$("readerMetadata").textContent, "字幕原文 · 未调用模型 · 5:00");
  }
});

test("terminal tasks without retained text do not claim that text exists", () => {
  const h = harness({ kind: "task", status: "failed", frame_grids: [] }); h.update();
  assert.equal(h.$("readerMetadata").textContent, "处理失败");
  h.state.selected.artifact_status = { draft_available: true }; h.update();
  assert.equal(h.$("readerMetadata").textContent, "处理失败 · 草稿已保留");
});

test("actual repeated projection refreshes status without resetting frame/version controls", () => {
  const h = harness(draft("running")); h.state.selected.frame_grids = ["grid.jpg"]; h.update();
  h.state.selected.status = "cancelled"; h.update();
  assert.equal(h.$("readerMetadata").textContent, "已停止 · 字幕已保留 · 5:00");
  assert.equal(h.$("sourceFrames").hidden, false); assert.equal(h.$("openVersions").hidden, false);
  h.state.selected.status = "running"; h.update();
  assert.equal(h.$("readerMetadata").textContent, "字幕已取得 · 等待总结 · 5:00");
});

test("material and cleared-selection projections remain unchanged", () => {
  const h = harness({ kind: "material", status: "failed" }); h.update();
  assert.equal(h.$("readerMetadata").textContent, "原始资料 · 可编辑修订");
  assert.equal(h.$("sourceFrames").hidden, true); assert.equal(h.$("openVersions").hidden, true);
  h.state.selected = null; h.update(); assert.equal(h.readerNav.hidden, true);
});
