// Pure task-list policy: task records + explicit selection, filters, history and clock.
// No DOM, storage, model or network access; input arrays and records stay untouched.
(function installModule(global) {
  "use strict";
  const { isUnreadableTitle, hostFromUrl, compactUrl } = global.LearnNoteTaskFormat;
  const { mediaKindText } = global.LearnNoteTaskDisplay;
  const ACTIVE_TASK_STATUSES = new Set(["running", "queued", "cancelling"]);

function taskAwaitingConfirmation(task = {}) {
  return Boolean(task?.awaiting_confirmation && task?.status === "queued");
}

function isActiveTask(task) {
  return ACTIVE_TASK_STATUSES.has(task?.status) && !taskAwaitingConfirmation(task);
}

function displayTaskTitle(task, fallback = "未命名任务") {
  const raw = String(task?.title || "").trim();
  if (!isUnreadableTitle(raw)) return raw;
  const selected = task?.selected_resource || {};
  const kind = mediaKindText(selected.kind) || selected.kind || (task?.media_path ? taskMediaDisplayName(task) : "");
  const source = task?.mode === "download_only"
    ? "当前页下载"
    : task?.mode === "rerun_from_media"
      ? "复用本地视频"
      : task?.source_type === "local"
        ? "本地视频"
        : task?.source_type === "page_text"
          ? "页面文本"
          : task?.source_type === "current_page"
            ? "当前页直取"
            : "";
  const host = hostFromUrl(task?.page_url || selected.page_url || selected.frame_url || selected.url);
  if (source && kind) return `${source} · ${kind}`;
  if (host && source) return `${source} · ${host}`;
  if (host) return compactUrl(host, 48);
  if (source) return source;
  return task?.id ? `任务 ${String(task.id).slice(0, 8)}` : fallback;
}

function preferredInitialTask(list) {
  const candidates = Array.isArray(list) ? list : [];
  return candidates.find(task => task.status === "running")
    || candidates.find(task => task.status === "success" && task.note_path)
    || candidates.find(task => task.status === "success" && (hasExportableMedia(task) || visualWindows(task).length))
    || candidates.find(task => task.status === "success")
    || candidates.find(task => task.status === "queued")
    || candidates.find(task => task.status === "failed" && task.note_path)
    || candidates[0]
    || null;
}

function taskStudyRank(task, currentTaskId = "") {
  if (!task) return 90;
  if (task.id && task.id === currentTaskId) return 0;
  if (task.status === "running") return 1;
  if (task.status === "success" && task.note_path) return 2;
  if (task.status === "success" && (hasExportableMedia(task) || visualWindows(task).length)) return 3;
  if (task.status === "success") return 4;
  if (task.status === "queued") return 5;
  if (task.status === "failed" && task.note_path) return 6;
  if (task.status === "failed") return 7;
  return 8;
}

function sortedVisibleTasks(list, currentTaskId = "") {
  return (Array.isArray(list) ? list : [])
    .map((task, index) => ({ task, index }))
    .sort((a, b) => taskStudyRank(a.task, currentTaskId) - taskStudyRank(b.task, currentTaskId) || a.index - b.index)
    .map(item => item.task);
}

function taskListFingerprint(items = []) {
  return JSON.stringify(items.map(task => [
    task.id,
    task.status,
    task.phase,
    task.title || "",
    task.note_path || "",
    task.media_path || "",
    task.transcript_path || "",
    task.source_task_id || "",
    task.error_code || "",
    task.evidence_quality?.video_evidence || ""
  ]));
}

function taskListLiveFingerprint(items = []) {
  return JSON.stringify(items.map(task => [
    task.id,
    Number(task.progress || 0),
    task.updated_at || ""
  ]));
}

function taskMatchesFilters(task, { statusFilter = "all", query = "" } = {}) {
  if (statusFilter !== "all") {
    const running = isActiveTask(task);
    if (statusFilter === "running" && !running) return false;
    if (statusFilter !== "running" && task.status !== statusFilter) return false;
  }
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) return true;
  return [
    task.title,
    displayTaskTitle(task),
    task.page_url,
    task.source_type,
    task.error_code,
    task.error_detail,
    task.drm_detected ? "drm eme encrypted" : "",
    ...(task.drm_signals || []).map(signal => `${signal.key_system || ""} ${signal.init_data_type || ""}`),
    task.selected_resource?.url,
    task.selected_resource?.source,
    task.selected_resource?.kind
  ].filter(Boolean).join(" ").toLowerCase().includes(normalizedQuery);
}

function recentTaskTime(task, now) {
  const raw = String(task?.updated_at || task?.created_at || "");
  const value = new Date(raw);
  if (Number.isNaN(value.getTime())) return "";
  const sameDay = value.toDateString() === now.toDateString();
  if (sameDay) return value.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (value.toDateString() === yesterday.toDateString()) return "昨天";
  return `${value.getMonth() + 1}月${value.getDate()}日`;
}

function noteVersionInfo(task, tasks) {
  if (!task?.id) return { rootId: "", index: 1, total: 1 };
  let rootId = task.id;
  let cursor = task;
  const seen = new Set();
  while (cursor?.source_task_id && !seen.has(cursor.source_task_id)) {
    seen.add(cursor.source_task_id);
    rootId = cursor.source_task_id;
    cursor = tasks.find(item => item.id === cursor.source_task_id);
  }
  const members = tasks
    .filter(item => {
      let itemRoot = item.id;
      let current = item;
      const visited = new Set();
      while (current?.source_task_id && !visited.has(current.source_task_id)) {
        visited.add(current.source_task_id);
        itemRoot = current.source_task_id;
        current = tasks.find(candidate => candidate.id === current.source_task_id);
      }
      return itemRoot === rootId;
    })
    .sort((left, right) => String(left.created_at || "").localeCompare(String(right.created_at || "")));
  return { rootId, index: Math.max(1, members.findIndex(item => item.id === task.id) + 1), total: Math.max(1, members.length) };
}

function hasExportableMedia(task) {
  const reuse = task?.reuse || {};
  return Boolean(task?.media_path || reuse.media_available);
}

function taskMediaDisplayName(task) {
  const reuse = task?.reuse || {};
  const raw = String(
    task?.media_path ||
    reuse.media_path_recorded ||
    task?.source_media_path ||
    reuse.source_media_path ||
    ""
  ).trim();
  if (!raw) return "media.mp4";
  const withoutQuery = raw.replace(/[?#].*$/, "").replace(/\\/g, "/");
  const parts = withoutQuery.split("/").filter(Boolean);
  return parts[parts.length - 1] || "media.mp4";
}

function visualWindows(task) {
  if (task.visual_windows?.length) return task.visual_windows;
  return (task.frame_grids || []).map((grid, index) => ({
    id: `W${String(index + 1).padStart(3, "0")}`,
    index: index + 1,
    start: grid.start,
    end: grid.end,
    frame_count: grid.frame_count,
    frame_timestamps: grid.frame_timestamps || [],
    grid_url: grid.url,
    transcript_excerpt: ""
  }));
}

  global.LearnNoteTaskList = Object.freeze({
    taskAwaitingConfirmation,
    isActiveTask,
    displayTaskTitle,
    preferredInitialTask,
    taskStudyRank,
    sortedVisibleTasks,
    taskListFingerprint,
    taskListLiveFingerprint,
    taskMatchesFilters,
    recentTaskTime,
    noteVersionInfo,
    hasExportableMedia,
    taskMediaDisplayName,
    visualWindows,
  });
})(globalThis);
