import { escapeHtml as esc } from "/web/desk-api.js";

const stageNames = {
  subtitle_probe: "检查字幕",
  media: "获取视频",
  transcript: "读取文字",
  visual: "补充画面",
  summary: "生成笔记",
};
export const phaseName = (phase) =>
  ({
    queued: "等待开始",
    detecting: "探测字幕",
    downloading: "获取视频",
    processing_video: "准备音轨",
    transcribing: "读取字幕或转写",
    extracting_frames: "补充画面",
    summarizing: "生成总结",
    completed: "已完成",
    failed: "需要处理",
    cancelled: "已停止",
    cancelling: "正在停止",
    download: "获取视频",
    ...stageNames,
  })[phase] || "处理内容";
export function elapsedLabel(ms) {
  const seconds = Math.max(0, Math.round(Number(ms) / 1000));
  return seconds < 60
    ? `${seconds} 秒`
    : seconds < 3600
      ? `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
      : `${Math.floor(seconds / 3600)} 小时 ${Math.floor(seconds / 60) % 60} 分`;
}
export function taskTimeline(task, events = [], now = Date.now()) {
  const start = events.findLastIndex(
    (e) => e.event === "pipeline_attempt_started",
  );
  const current = start < 0 ? events : events.slice(start);
  const stages = Object.entries(stageNames).map(([key, label]) => ({
    key,
    label,
    state: "pending",
    detail: "等待记录",
  }));
  for (const stage of stages) {
    const timed = current.findLast(
      (e) => e.event === "stage_timing" && e.phase === stage.key,
    );
    if (timed) {
      stage.state =
        timed.status === "completed"
          ? "done"
          : timed.status === "skipped"
            ? "skipped"
            : "stopped";
      stage.detail =
        stage.state === "skipped"
          ? {
              media: "无需下载",
              visual: "未启用 / 无需画面",
              transcript: "复用已有文字",
              subtitle_probe: "复用已有结果",
            }[stage.key] || "无需执行"
          : `${stage.state === "done" ? "已完成" : "未完成"} · ${elapsedLabel(timed.details?.duration_ms || 0)}`;
    }
  }
  const activeKey = {
    detecting: "subtitle_probe",
    downloading: "media",
    processing_video: "transcript",
    transcribing: "transcript",
    extracting_frames: "visual",
    summarizing: "summary",
  }[task.phase];
  const active = stages.find((s) => s.key === activeKey);
  if (
    active &&
    !task.awaiting_confirmation &&
    ["running", "queued"].includes(task.status) &&
    active.state === "pending"
  ) {
    active.state = "active";
    active.detail = phaseName(task.phase) + "中";
    const updates = current.filter(
      (event) => event.event === "task_updated" && event.status === "running",
    );
    const previousPhase = updates.findLastIndex(
      (event) => event.phase !== task.phase,
    );
    const started = Date.parse(updates[previousPhase + 1]?.timestamp || "");
    if (Number.isFinite(started) && now >= started)
      active.detail += ` · 已用 ${elapsedLabel(now - started)}`;
  }
  if (
    !task.awaiting_confirmation &&
    ["failed", "cancelled", "cancelling"].includes(task.status)
  ) {
    const failedKey =
      {
        detecting: "subtitle_probe",
        downloading: "media",
        transcribing: "transcript",
        summarizing: "summary",
        extracting_frames: "visual",
      }[task.failed_phase] ||
      (task.error_code === "summary_unavailable" ? "summary" : null);
    const stopped = stages.find((s) => s.key === failedKey);
    if (stopped) {
      if (stopped.state === "pending") stopped.detail = "等待继续";
      stopped.state = "stopped";
    }
  }
  if (["success", "failed", "cancelled"].includes(task.status)) {
    stages
      .filter((s) => s.state === "pending")
      .forEach((s) => {
        s.detail = "未记录";
      });
  }
  // Older tasks have no timing events. Do not invent completed steps or durations.
  if (task.awaiting_confirmation)
    stages.forEach((s) => {
      s.state = "pending";
      s.detail = "尚未开始";
    });
  if (task.summary_source === "subtitle-extract") {
    const stage = stages.find((s) => s.key === "summary");
    stage.state = "skipped";
    stage.detail = "未要求生成总结";
  }
  return stages;
}
export function timelineHtml(
  task,
  events,
  expanded = task.status !== "success",
) {
  return `<details class="task-progress-details" data-task-progress="${esc(task.id)}" ${expanded ? "open" : ""}><summary>处理步骤</summary><ol class="task-timeline" aria-label="实际处理步骤">${taskTimeline(
    task,
    events,
  )
    .map(
      (s, i) =>
        `<li data-stage="${s.key}" data-state="${s.state}"><span class="timeline-mark" aria-hidden="true">${s.state === "done" ? "✓" : s.state === "skipped" ? "−" : i + 1}</span><div><strong>${s.label}</strong><small>${esc(s.detail)}</small></div></li>`,
    )
    .join("")}</ol></details>`;
}
export function taskExplanation(task) {
  if (task.options?.content_mode === "subtitles")
    return task.status === "success"
      ? "已有字幕已保存，可以阅读或导出。本次未下载视频、转写音频或调用模型。"
      : "仅检查和保存已有字幕。未取得字幕会停止，不会自动下载视频、转写或调用模型。";

  if (task.awaiting_confirmation)
    return "来源已送达，还没有开始处理。先尝试直接读取字幕；字幕可用时直接生成笔记。只有缺少字幕或需要画面时，才获取视频。";
  if (
    task.error_code === "summary_unavailable" ||
    task.summary_source === "local-template"
  )
    return "字幕已经保留，但 AI 总结尚未生成。可以检查模型连接后仅重试总结，不必重新下载或转写。";
  if (task.status === "success")
    return "笔记已生成。可以阅读正文、核对原始字幕，或查看各步骤的处理记录。";
  if (task.status === "cancelled")
    return "处理已停止，已取得的文字和文件仍保留。";
  if (task.status === "failed")
    return "这次处理没有完成。已取得的内容仍保留，可查看记录并从可用步骤继续。";
  return (
    {
      queued: "任务已加入队列，轮到后会开始处理。",
      detecting: "正在检查是否有可直接读取的字幕，取得后即可整理。",
      downloading: "当前步骤需要视频内容，正在获取文件。",
      processing_video: "正在准备本地识别所需的音轨。",
      transcribing: "正在读取文字。没有可用字幕时，本地识别会按音轨逐段进行。",
      extracting_frames: "文字已经准备好，正在补充你选择的画面内容。",
      summarizing: "正在将原文整理成核心观点、内容大纲和笔记正文。",
      cancelling: "正在停止，已完成的内容会保留。",
    }[task.phase] || "正在整理内容，已记录的步骤会显示在下方。"
  );
}
export function eventLogHtml(events) {
  const names = {
    pipeline_attempt_started: "开始本次处理",
    stage_timing: "步骤结束",
    draft_ready: "字幕草稿可读",
    summary_retry_requested: "重新生成总结",
    task_created: "接收来源",
    task_started: "开始处理",
    task_completed: "处理完成",
    task_failed: "处理未完成",
    task_cancelled: "停止处理",
  };
  const rows = events.filter(
    (e) => e.message || names[e.event] || e.event === "phase_changed",
  );
  return rows.length
    ? `<details open><summary>最近 ${Math.min(rows.length, 120)} 条处理记录</summary><ol class="processing-records">${rows
        .slice(-120)
        .map(
          (e) =>
            `<li><time>${esc(new Date(e.timestamp).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }))}</time><div><strong>${esc(names[e.event] || phaseName(e.phase))}</strong><p>${esc(e.event === "stage_timing" ? `${phaseName(e.phase)} · ${e.status === "skipped" ? "无需执行" : elapsedLabel(e.details?.duration_ms || 0)}` : e.message || phaseName(e.phase))}</p></div></li>`,
        )
        .join("")}</ol></details>`
    : '<p class="muted">这份旧任务没有可用的逐步记录。可以下载诊断报告查看已保存的状态。</p>';
}
