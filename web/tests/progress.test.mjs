import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
const apiSource = readFileSync(
  new URL("../desk-api.js", import.meta.url),
  "utf8",
);
const apiUrl =
  "data:text/javascript;base64," + Buffer.from(apiSource).toString("base64");
const source = readFileSync(
  new URL("../desk-progress.js", import.meta.url),
  "utf8",
).replace('"/web/desk-api.js"', JSON.stringify(apiUrl));
const { taskTimeline, taskExplanation, eventLogHtml, elapsedLabel } =
  await import(
    "data:text/javascript;base64," + Buffer.from(source).toString("base64")
  );
const timing = (phase, status, duration_ms) => ({
  event: "stage_timing",
  phase,
  status,
  details: { duration_ms },
});

test("subtitle-only steps distinguish skipped downloads from measured work", () => {
  const timeline = taskTimeline({ status: "success", phase: "completed" }, [
    timing("subtitle_probe", "completed", 2300),
    timing("media", "skipped", 0),
    timing("transcript", "completed", 200),
    timing("visual", "skipped", 0),
    timing("summary", "completed", 68000),
  ]);
  assert.equal(timeline.find((s) => s.key === "media").detail, "无需下载");
  assert.equal(
    timeline.find((s) => s.key === "summary").detail,
    "已完成 · 1 分 8 秒",
  );
});
test("retry history does not claim old attempt timings as current completion", () => {
  const timeline = taskTimeline({ status: "running", phase: "summarizing" }, [
    timing("summary", "completed", 10000),
    { event: "pipeline_attempt_started" },
  ]);
  assert.equal(timeline.find((s) => s.key === "summary").state, "active");
  assert.equal(timeline.find((s) => s.key === "media").state, "pending");
});
test("old successful tasks without events do not fabricate complete pipeline or durations", () => {
  assert(
    taskTimeline({ status: "success" }).every((s) => s.detail === "未记录"),
  );
});
test("active step elapsed time comes from the recorded phase start", () => {
  const started = Date.parse("2026-09-08T10:00:00Z");
  const timeline = taskTimeline(
    { status: "running", phase: "transcribing" },
    [
      {
        event: "task_updated",
        status: "running",
        phase: "transcribing",
        timestamp: new Date(started).toISOString(),
      },
      {
        event: "task_updated",
        status: "running",
        phase: "transcribing",
        timestamp: new Date(started + 60000).toISOString(),
      },
    ],
    started + 125000,
  );
  assert.match(
    timeline.find((s) => s.key === "transcript").detail,
    /已用 2 分 5 秒/,
  );
});
test("waiting confirmation never implies any work has already happened", () => {
  assert(
    taskTimeline({ status: "queued", awaiting_confirmation: true }, [
      timing("summary", "completed", 50),
    ]).every((s) => s.detail === "尚未开始"),
  );
  assert.match(
    taskExplanation({ awaiting_confirmation: true }),
    /还没有开始处理/,
  );
});
test("model fallback is explicitly reported as missing summary", () => {
  assert.match(
    taskExplanation({ status: "success", summary_source: "local-template" }),
    /AI 总结尚未生成/,
  );
  assert.equal(
    taskTimeline({ status: "failed", error_code: "summary_unavailable" }).find(
      (s) => s.key === "summary",
    ).state,
    "stopped",
  );
});
test("log text is escaped and duration formatting handles long steps", () => {
  assert(
    !eventLogHtml([
      {
        timestamp: "2026-09-08T10:00:00Z",
        phase: "summary",
        message: "<script>alert(1)</script>",
      },
    ]).includes("<script>"),
  );
  assert.equal(elapsedLabel(3660000), "1 小时 1 分");
});
