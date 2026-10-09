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
const { taskTimeline, timelineHtml, taskExplanation, eventLogHtml, elapsedLabel } =
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
    timing("download", "skipped", 0),
    timing("media", "skipped", 0),
    timing("transcript", "completed", 200),
    timing("visual", "skipped", 0),
    timing("summary", "completed", 68000),
  ]);
  assert.equal(timeline.find((s) => s.key === "download").detail, "无需下载");
  assert.equal(timeline.find((s) => s.key === "download").state, "skipped");
  assert.equal(timeline.find((s) => s.key === "media").detail, "无需准备媒体");
  assert.equal(timeline.find((s) => s.key === "media").state, "skipped");
  assert.equal(
    timeline.find((s) => s.key === "summary").detail,
    "已完成 · 1 分 8 秒",
  );
});
test("download and media preparation retain their separate measured durations in the UI", () => {
  const task = { id: "synthetic-progress", status: "success", phase: "completed" };
  const events = [timing("download", "completed", 23000), timing("media", "completed", 1000)];
  const timeline = taskTimeline(task, events);
  assert.deepEqual(timeline.filter((s) => ["download", "media"].includes(s.key)), [
    { key: "download", label: "获取视频", state: "done", detail: "已完成 · 23 秒" },
    { key: "media", label: "准备媒体", state: "done", detail: "已完成 · 1 秒" },
  ]);
  const html = timelineHtml(task, events);
  assert.match(html, /data-stage="download" data-state="done"[^]*获取视频<\/strong><small>已完成 · 23 秒/);
  assert.match(html, /data-stage="media" data-state="done"[^]*准备媒体<\/strong><small>已完成 · 1 秒/);
  assert(html.indexOf('data-stage="download"') < html.indexOf('data-stage="media"'));
});
test("active download owns its elapsed time while media preparation still waits", () => {
  const started = Date.parse("2026-10-09T10:00:00Z");
  const timeline = taskTimeline({ status: "running", phase: "downloading" }, [
    { event: "task_updated", status: "running", phase: "detecting", timestamp: new Date(started - 5000).toISOString() },
    { event: "task_updated", status: "running", phase: "downloading", timestamp: new Date(started).toISOString() },
  ], started + 23000);
  assert.equal(timeline.find((s) => s.key === "download").detail, "获取视频中 · 已用 23 秒");
  assert.equal(timeline.find((s) => s.key === "download").state, "active");
  assert.equal(timeline.find((s) => s.key === "media").state, "pending");
});
test("media preparation becomes active after download and leaves transcription pending", () => {
  const timeline = taskTimeline({ status: "running", phase: "processing_video" }, [timing("download", "completed", 23000)]);
  assert.equal(timeline.find((s) => s.key === "download").detail, "已完成 · 23 秒");
  assert.equal(timeline.find((s) => s.key === "media").state, "active");
  assert.equal(timeline.find((s) => s.key === "transcript").state, "pending");
});
test("audio preparation after a completed media stage activates transcription without losing timings", () => {
  const timeline = taskTimeline({ status: "running", phase: "processing_video" }, [timing("media", "completed", 1000)]);
  assert.equal(timeline.find((s) => s.key === "media").detail, "已完成 · 1 秒");
  assert.equal(timeline.find((s) => s.key === "media").state, "done");
  assert.equal(timeline.find((s) => s.key === "transcript").state, "active");
});
test("failed and cancelled download timings never mark media preparation as stopped", () => {
  for (const status of ["failed", "cancelled"]) {
    const timeline = taskTimeline({ status, phase: status, failed_phase: "downloading" }, [timing("download", status, 23000)]);
    assert.equal(timeline.find((s) => s.key === "download").state, "stopped");
    assert.equal(timeline.find((s) => s.key === "download").detail, "未完成 · 23 秒");
    assert.equal(timeline.find((s) => s.key === "media").state, "pending");
  }
});
test("failures without a timing record identify download or media without inventing elapsed time", () => {
  for (const [phase, key] of [["downloading", "download"], ["processing_video", "media"]]) {
    const timeline = taskTimeline({ status: "failed", failed_phase: phase });
    assert.equal(timeline.find((s) => s.key === key).state, "stopped");
    assert.equal(timeline.find((s) => s.key === key).detail, "等待继续");
    assert.equal(timeline.find((s) => s.key === "transcript").state, "pending");
  }
});
test("audio extraction failure keeps completed download and media timings intact", () => {
  const timeline = taskTimeline({ status: "failed", failed_phase: "processing_video" }, [
    timing("download", "completed", 23000), timing("media", "completed", 1000),
  ]);
  assert.equal(timeline.find((s) => s.key === "download").state, "done");
  assert.equal(timeline.find((s) => s.key === "media").state, "done");
  assert.equal(timeline.find((s) => s.key === "transcript").state, "stopped");
});
test("retry drops previous download and media timings and active elapsed time", () => {
  const timeline = taskTimeline({ status: "running", phase: "downloading" }, [
    { event: "task_updated", status: "running", phase: "downloading", timestamp: "2026-10-09T10:00:00Z" },
    timing("download", "completed", 23000), timing("media", "completed", 1000),
    { event: "pipeline_attempt_started" },
  ], Date.parse("2026-10-09T11:00:00Z"));
  assert.equal(timeline.find((s) => s.key === "download").detail, "获取视频中");
  assert.equal(timeline.find((s) => s.key === "download").state, "active");
  assert.equal(timeline.find((s) => s.key === "media").detail, "等待记录");
  assert.equal(timeline.find((s) => s.key === "media").state, "pending");
});
test("legacy media timings do not stand in for absent download records", () => {
  for (const status of ["completed", "skipped"]) {
    const timeline = taskTimeline({ status: "success" }, [timing("media", status, 1000)]);
    assert.equal(timeline.find((s) => s.key === "download").state, "pending");
    assert.equal(timeline.find((s) => s.key === "download").detail, "未记录");
  }
});
test("a timing event without a valid duration does not fabricate a zero-second measurement", () => {
  for (const duration of [undefined, null, -1, "", NaN]) {
    const timeline = taskTimeline({ status: "success" }, [timing("download", "completed", duration)]);
    assert.equal(timeline.find((s) => s.key === "download").detail, "已完成 · 耗时未记录");
  }
  assert.equal(taskTimeline({ status: "success" }, [timing("download", "completed", 0)]).find((s) => s.key === "download").detail, "已完成 · 0 秒");
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
test("failed merge preserves the completed generated-section draft explanation", () => {
  const task = { status: "failed", summary_source: "local-template", error_code: "summary_unavailable",
    artifact_status: { draft_available: true, partial_draft_available: true } };
  assert.match(taskExplanation(task), /已生成的分段仍以草稿保留/);
  assert.match(eventLogHtml([{ event: "partial_section_ready", timestamp: "2026-10-09T00:00:00Z" }]), /分段草稿可读/);
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
