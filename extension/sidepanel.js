const DEFAULT_BACKEND = "http://127.0.0.1:8765";
const HAS_EXTENSION_API = typeof chrome !== "undefined" && Boolean(chrome.runtime?.sendMessage && chrome.storage?.local);
const LOCAL_VIDEO_EXT_RE = /\.(mp4|m4v|mov|mkv|webm|flv|avi)$/i;
const RESULT_TAB_NAMES = new Set(["note", "transcript", "frames", "diagnostics"]);
const LOCAL_ASR_MODELS = new Set(["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"]);
const PENDING_INTENT_TTL_MS = 15000;
const ONE_CLICK_RESOURCE_WAIT_ATTEMPTS = 4;
const ONE_CLICK_RESOURCE_WAIT_DELAY_MS = 900;

let backendUrl = DEFAULT_BACKEND;
let page = null;
let resources = [];
let selectedResourceUrl = "";
let resourceSelectionPinned = false;
let resourceFilter = "all";
let currentTaskId = "";
let currentTask = null;
let selectedTab = "note";
let transcriptCache = null;
let lastNote = "";
let preflight = null;
let preflightResourceUrl = "";
let preflightResultsByUrl = new Map();
let contextRefreshTimer = 0;
let isCollectingContext = false;
let pendingContextRefresh = false;
let currentTabId = null;
let taskHistory = [];
let lastHealthData = null;

const els = {
  backendStatus: document.querySelector("#backendStatus"),
  pageTitle: document.querySelector("#pageTitle"),
  pageUrl: document.querySelector("#pageUrl"),
  activeVideo: document.querySelector("#activeVideo"),
  playbackReadiness: document.querySelector("#playbackReadiness"),
  currentStudyCard: document.querySelector("#currentStudyCard"),
  launchBar: document.querySelector("#launchBar"),
  resourceCount: document.querySelector("#resourceCount"),
  readiness: document.querySelector("#readiness"),
  routeSummary: document.querySelector("#routeSummary"),
  extractionPlan: document.querySelector("#extractionPlan"),
  resources: document.querySelector("#resources"),
  resourceInspector: document.querySelector("#resourceInspector"),
  summarizeButton: document.querySelector("#summarizeButton"),
  preflightButton: document.querySelector("#preflightButton"),
  downloadOnlyButton: document.querySelector("#downloadOnlyButton"),
  continueFromMediaButton: document.querySelector("#continueFromMediaButton"),
  uploadButton: document.querySelector("#uploadButton"),
  fileInput: document.querySelector("#fileInput"),
  localDrop: document.querySelector("#localDrop"),
  localDropText: document.querySelector("#localDropText"),
  textButton: document.querySelector("#textButton"),
  redetectButton: document.querySelector("#redetectButton"),
  frameInterval: document.querySelector("#frameInterval"),
  gridSize: document.querySelector("#gridSize"),
  transcriber: document.querySelector("#transcriber"),
  whisperModel: document.querySelector("#whisperModel"),
  noteStyle: document.querySelector("#noteStyle"),
  summaryDepth: document.querySelector("#summaryDepth"),
  llmModel: document.querySelector("#llmModel"),
  llmBaseUrl: document.querySelector("#llmBaseUrl"),
  llmApiKey: document.querySelector("#llmApiKey"),
  progressBar: document.querySelector("#progressBar"),
  stageRail: document.querySelector("#stageRail"),
  taskPhase: document.querySelector("#taskPhase"),
  taskMessage: document.querySelector("#taskMessage"),
  refreshHistoryButton: document.querySelector("#refreshHistoryButton"),
  taskHistory: document.querySelector("#taskHistory"),
  resultTabs: document.querySelectorAll(".result-tab"),
  result: document.querySelector("#result"),
  copyButton: document.querySelector("#copyButton"),
  bundleButton: document.querySelector("#bundleButton"),
  diagnosticsButton: document.querySelector("#diagnosticsButton"),
  visualWindowsButton: document.querySelector("#visualWindowsButton"),
  mediaButton: document.querySelector("#mediaButton"),
  downloadButton: document.querySelector("#downloadButton"),
  openWebButton: document.querySelector("#openWebButton"),
  settingsButton: document.querySelector("#settingsButton")
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[ch]));
}

function safeNoteMediaUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  if (/^(https?:\/\/|\/)/i.test(raw)) return escapeHtml(raw);
  return "";
}

function isSupportedLocalVideoFile(file) {
  if (!file?.name) return false;
  if (String(file.type || "").startsWith("video/")) return true;
  return LOCAL_VIDEO_EXT_RE.test(file.name);
}

function apiErrorMessage(payload, fallback) {
  const detail = payload?.detail;
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (typeof detail?.message === "string" && detail.message.trim()) return detail.message.trim();
  if (typeof payload?.message === "string" && payload.message.trim()) return payload.message.trim();
  if (typeof payload?.error === "string" && payload.error.trim()) return payload.error.trim();
  return fallback;
}

function inlineMarkdown(value) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

function plainHeadingText(value) {
  return String(value || "")
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[`*_~#]/g, "")
    .trim();
}

function noteHeadingId(value, counts = new Map()) {
  const plain = plainHeadingText(value);
  const slug = plain
    .toLowerCase()
    .replace(/[^\w\u4e00-\u9fff]+/g, "-")
    .replace(/^-+|-+$/g, "") || "section";
  const base = `note-${slug}`;
  const count = counts.get(base) || 0;
  counts.set(base, count + 1);
  return count ? `${base}-${count + 1}` : base;
}

function markdownToHtml(markdown) {
  const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
  const html = [];
  const headingIds = new Map();
  let listType = "";
  let inCode = false;
  const closeList = () => {
    if (listType) {
      html.push(`</${listType}>`);
      listType = "";
    }
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    if (line.startsWith("```")) {
      closeList();
      if (inCode) {
        html.push("</code></pre>");
      } else {
        html.push("<pre><code>");
      }
      inCode = !inCode;
      continue;
    }
    if (inCode) {
      html.push(escapeHtml(rawLine) + "\n");
      continue;
    }
    if (!line.trim()) {
      closeList();
      continue;
    }
    const image = /^!\[([^\]]*)\]\(([^)]+)\)$/.exec(line.trim());
    if (image) {
      closeList();
      const src = safeNoteMediaUrl(image[2]);
      const alt = escapeHtml(image[1] || "frame grid");
      if (src) {
        html.push(`<figure class="note-image-frame"><img src="${src}" alt="${alt}"><figcaption>${alt}</figcaption></figure>`);
      } else {
        html.push(`<p>${inlineMarkdown(line)}</p>`);
      }
      continue;
    }
    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading) {
      closeList();
      const level = heading[1].length;
      const id = noteHeadingId(heading[2], headingIds);
      html.push(`<h${level} id="${escapeHtml(id)}">${inlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }
    const bullet = /^[-*]\s+(.+)$/.exec(line);
    if (bullet) {
      if (listType !== "ul") {
        closeList();
        html.push("<ul>");
        listType = "ul";
      }
      html.push(`<li>${inlineMarkdown(bullet[1])}</li>`);
      continue;
    }
    const numbered = /^\d+\.\s+(.+)$/.exec(line);
    if (numbered) {
      if (listType !== "ol") {
        closeList();
        html.push("<ol>");
        listType = "ol";
      }
      html.push(`<li>${inlineMarkdown(numbered[1])}</li>`);
      continue;
    }
    if (line.startsWith(">")) {
      closeList();
      html.push(`<blockquote>${inlineMarkdown(line.replace(/^>\s?/, ""))}</blockquote>`);
      continue;
    }
    closeList();
    html.push(`<p>${inlineMarkdown(line)}</p>`);
  }
  closeList();
  if (inCode) html.push("</code></pre>");
  return html.join("");
}

function noteOutline(markdown, limit = 10) {
  const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
  const headingIds = new Map();
  const headings = [];
  let inCode = false;
  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    if (line.startsWith("```")) {
      inCode = !inCode;
      continue;
    }
    if (inCode) continue;
    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (!heading) continue;
    const text = plainHeadingText(heading[2]);
    if (!text) continue;
    headings.push({
      level: heading[1].length,
      text,
      id: noteHeadingId(heading[2], headingIds)
    });
  }
  if (!headings.length) return "";
  return `<nav class="note-outline" aria-label="笔记目录">
    <div class="note-outline-head">
      <strong>笔记目录</strong>
      <span>${headings.length} 节</span>
    </div>
    <div class="note-outline-list">
      ${headings.slice(0, limit).map(heading => `
        <a class="level-${heading.level}" href="#${escapeHtml(heading.id)}">${escapeHtml(heading.text)}</a>
      `).join("")}
    </div>
  </nav>`;
}

function fmt(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  return `${String(Math.floor(sec / 3600)).padStart(2, "0")}:${String(Math.floor((sec % 3600) / 60)).padStart(2, "0")}:${String(sec % 60).padStart(2, "0")}`;
}

function frameTimestampText(window, limit = 4) {
  const values = (window?.frame_timestamps || []).slice(0, limit).map(value => fmt(value));
  if (!values.length) return "";
  const suffix = (window.frame_timestamps || []).length > values.length ? "..." : "";
  return `${values.join(" / ")}${suffix}`;
}

function fmtBytes(bytes) {
  const value = Number(bytes || 0);
  if (!value) return "";
  if (value >= 1024 * 1024 * 1024) return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value} B`;
}

function contentDispositionFilename(value = "") {
  let filename = "";
  for (const part of String(value || "").split(";")) {
    const [rawKey, ...rest] = part.trim().split("=");
    if (!rawKey || !rest.length) continue;
    const key = rawKey.toLowerCase();
    let raw = rest.join("=").trim().replace(/^"|"$/g, "");
    if (key === "filename*") {
      const marker = raw.indexOf("''");
      raw = marker >= 0 ? raw.slice(marker + 2) : raw;
      try {
        filename = decodeURIComponent(raw);
      } catch {
        filename = raw;
      }
      break;
    }
    if (key === "filename" && raw) {
      try {
        filename = decodeURIComponent(raw);
      } catch {
        filename = raw;
      }
    }
  }
  return filename.split(/[\\/]/).pop() || "";
}

function contentDispositionHint(value = "") {
  const filename = contentDispositionFilename(value);
  return filename ? `filename ${filename}` : "";
}

function requestHeaderNames(resource) {
  return Object.keys(resource?.request_headers || {})
    .filter(name => !/cookie|authorization/i.test(name))
    .sort()
    .join(", ") || "-";
}

function hasRangeRequestHeader(resource) {
  return Object.keys(resource?.request_headers || {}).some(name => String(name).toLowerCase() === "range");
}

function compactIdList(values, limit = 3) {
  const ids = (values || []).map(value => String(value || "").trim()).filter(Boolean);
  if (!ids.length) return "";
  const suffix = ids.length > limit ? ` 等 ${ids.length} 个` : "";
  return `${ids.slice(0, limit).join(", ")}${suffix}`;
}

function resourcePreflightLine(result = null) {
  if (!result) return "未预检";
  return [
    result.downloadable ? "通过" : result.code || "未通过",
    result.strategy || "",
    result.status_code ? `HTTP ${result.status_code}` : "",
    result.content_type || "",
    contentDispositionHint(result.content_disposition),
    fmtBytes(result.content_length) || (result.bytes_checked ? `${result.bytes_checked} B` : "")
  ].filter(Boolean).join(" · ");
}

function selectedResourceReport(item = selectedResource()) {
  if (!item) return "";
  const confidence = candidateConfidence(item);
  const checked = preflightForResource(item);
  return [
    `LearnNote 候选资源：${item.label || item.kind || "media"}`,
    `URL: ${item.url}`,
    `类型: ${item.kind || "unknown"}`,
    `下载策略: ${candidateStrategyText(item)}`,
    `下载顺序: 第 ${candidateTryOrder(item) || "-"} 顺位`,
    `置信度: ${confidence.label} - ${confidence.detail}`,
    `选择依据: ${resourceReasonText(item) || requestEvidence(item) || "-"}`,
    `请求证据: ${requestEvidence(item) || "-"}`,
    `响应证据: ${responseEvidenceLine(item) || "-"}`,
    `复用请求头: ${requestHeaderNames(item)}`,
    `POST body: ${requestBodySummary(item) || "-"}`,
    `预检: ${resourcePreflightLine(checked)}`
  ].join("\n");
}

function workbenchUrl(taskId = currentTaskId, tabName = selectedTab) {
  if (!taskId) return backendUrl;
  const tab = RESULT_TAB_NAMES.has(tabName) ? tabName : "note";
  return `${backendUrl.replace(/\/$/, "")}/?task=${encodeURIComponent(taskId)}&tab=${encodeURIComponent(tab)}`;
}

function taskMediaPreviewUrl(task) {
  if (!task?.id || !task.media_path) return "";
  return `${backendUrl.replace(/\/$/, "")}/api/tasks/${encodeURIComponent(task.id)}/media`;
}

function openWorkbench(taskId = currentTaskId, tabName = selectedTab) {
  const url = workbenchUrl(taskId, tabName);
  if (HAS_EXTENSION_API) chrome.tabs.create({ url });
  else window.open(url, "_blank", "noopener");
}

async function copyTextToClipboard(text, successMessage) {
  if (!text) return false;
  try {
    await navigator.clipboard.writeText(text);
    els.taskMessage.textContent = successMessage;
    return true;
  } catch (error) {
    els.taskMessage.textContent = error?.message ? `复制失败：${error.message}` : "复制失败，请手动复制。";
    return false;
  }
}

async function copySelectedResourceUrl() {
  const item = selectedResource();
  if (!item?.url) {
    els.taskMessage.textContent = "没有可复制的候选资源。";
    return false;
  }
  return copyTextToClipboard(item.url, "已复制候选资源 URL。");
}

async function copySelectedResourceReport() {
  const report = selectedResourceReport();
  if (!report) {
    els.taskMessage.textContent = "没有可复制的候选证据。";
    return false;
  }
  return copyTextToClipboard(report, "已复制候选资源证据摘要。");
}

function summaryDiagnosticText(task) {
  const diag = task?.summary_diagnostics || {};
  if (!Object.keys(diag).length) return "-";
  const visionGridCount = diag.vision_grid_count ?? diag.frame_grid_count ?? 0;
  const sentImages = diag.vision_image_count ?? 0;
  const omittedCount = Number(diag.omitted_frame_grid_count || 0);
  const missingImages = diag.all_sent_grids_had_images === false || diag.all_grids_had_images === false;
  const missingWindowIds = compactIdList(diag.missing_vision_image_window_ids);
  const omittedWindowIds = compactIdList(diag.omitted_vision_window_ids);
  return [
    diag.used_vision_llm ? "已使用视觉 LLM" : diag.used_text_llm ? "已使用文本 LLM" : diag.used_local_template ? "本地模板" : "",
    `模型 ${diag.llm_model || task.summary_source || "-"}`,
    `视觉窗口 ${diag.visual_window_count ?? 0}`,
    `画面网格 ${diag.frame_grid_count ?? 0}`,
    `\u9001\u5165\u89c6\u89c9 ${sentImages}/${visionGridCount}`,
    omittedCount > 0 ? `\u8d85\u9650\u7701\u7565 ${omittedCount}` : "",
    missingWindowIds ? `缺图 ${missingWindowIds}` : "",
    omittedWindowIds ? `省略窗口 ${omittedWindowIds}` : "",
    missingImages ? "\u5b58\u5728\u7f3a\u5931\u56fe\u7247" : "",
    diag.used_page_text_fallback ? `页面文本 ${diag.page_text_char_count ?? 0} 字` : "",
    diag.used_page_text_fallback ? `浏览器字幕 ${diag.browser_subtitle_count ?? 0} 条` : "",
    diag.used_page_text_fallback ? `合并文本 ${diag.combined_text_char_count ?? 0} 字` : "",
    diag.summary_warning || ""
  ].filter(Boolean).join(" · ");
}

const PIPELINE_STEPS = [
  { key: "downloading", label: "下载" },
  { key: "transcribing", label: "识别" },
  { key: "extracting_frames", label: "切片" },
  { key: "summarizing", label: "生成" },
  { key: "completed", label: "完成" }
];

const DOWNLOAD_ERROR_CODES = new Set(["no_media_found", "auth_required", "drm_or_encrypted", "download_forbidden", "unsupported_manifest"]);
const DOWNLOADABLE_KINDS = new Set(["video", "hls", "dash"]);

function failedStepIndex(task) {
  if (DOWNLOAD_ERROR_CODES.has(task.error_code)) return 0;
  if (task.media_path && !task.transcript_path) return 1;
  if (task.transcript_path && !task.frame_grids?.length) return 2;
  return 3;
}

function stepState(task, step) {
  if (!task) return "pending";
  if (task.status === "failed") {
    const failedIndex = failedStepIndex(task);
    const stepIndex = PIPELINE_STEPS.findIndex(item => item.key === step.key);
    if (stepIndex < failedIndex) return "done";
    if (stepIndex === failedIndex) return "failed";
    return "pending";
  }
  if (task.status === "success" || task.phase === "completed") return "done";
  const currentIndex = PIPELINE_STEPS.findIndex(item => item.key === task.phase);
  const stepIndex = PIPELINE_STEPS.findIndex(item => item.key === step.key);
  if (currentIndex < 0) return stepIndex === 0 && task.status === "running" ? "active" : "pending";
  if (stepIndex < currentIndex) return "done";
  if (stepIndex === currentIndex) return "active";
  return "pending";
}

function renderStageRail(task) {
  if (!els.stageRail) return;
  els.stageRail.innerHTML = PIPELINE_STEPS.map(step => `<span class="${stepState(task, step)}">${step.label}</span>`).join("");
}

function taskStatusText(task = {}) {
  if (task.status === "success") return "已完成";
  if (task.status === "failed") return task.error_code || "失败";
  if (task.status === "queued") return "排队中";
  return task.message || task.phase || "处理中";
}

function taskSourceText(task = {}) {
  if (task.source_type === "local") return "本地视频";
  if (task.source_type === "page_text") return "页面文本";
  return task.selected_resource ? `直取 · ${mediaKindText(task.selected_resource.kind) || "媒体"}` : "当前页";
}

function mediaKindText(kind = "") {
  return ({
    hls: "HLS",
    dash: "DASH",
    video: "视频",
    subtitle: "字幕",
    fragment: "分片",
    blob: "Blob"
  })[String(kind || "").toLowerCase()] || kind || "";
}

function mediaMimeForKind(kind = "") {
  return ({
    hls: "application/vnd.apple.mpegurl",
    dash: "application/dash+xml",
    video: "video/mp4"
  })[String(kind || "").toLowerCase()] || "";
}

function isTextResponseMime(value = "") {
  return /json|text|html|javascript|xml/i.test(String(value || ""));
}

function taskHistoryChipItems(task = {}) {
  const selected = task.selected_resource || {};
  const windows = visualWindows(task);
  const attempts = task.download_attempts || [];
  const route = selected.playback_match
    ? playbackText(selected.playback_match)
    : resourceSourceText(selected) || (task.source_type === "current_page" ? "当前页" : taskSourceText(task));
  const chips = task.status === "failed" ? [
    route,
    mediaKindText(selected.kind),
    task.error_code || "",
    attempts.length ? `${attempts.length} 次尝试` : "",
    task.note_path ? "兜底笔记" : task.media_path ? "media.mp4" : "",
    windows.length ? `${windows.length} 窗口` : ""
  ] : [
    route,
    mediaKindText(selected.kind),
    task.media_path ? "media.mp4" : "",
    task.note_path ? "笔记" : "",
    windows.length ? `${windows.length} 窗口` : "",
    attempts.length > 1 ? `${attempts.length} 次尝试` : ""
  ];
  const seen = new Set();
  return chips.filter(value => {
    const text = String(value || "").trim();
    if (!text || seen.has(text)) return false;
    seen.add(text);
    return true;
  }).slice(0, 5);
}

function taskHistoryChipsHtml(task = {}) {
  const chips = taskHistoryChipItems(task);
  if (!chips.length) return "";
  return `<span class="history-task-chips">${chips.map(chip => `<em>${escapeHtml(chip)}</em>`).join("")}</span>`;
}

function taskHistoryPreviewIcon(status) {
  if (status === "success") return "看";
  if (status === "failed") return "错";
  if (status === "running" || status === "queued") return "跑";
  return "LN";
}

function taskHistoryPreviewHtml(task = {}) {
  const windows = visualWindows(task);
  const firstWindow = windows[0];
  const selected = task.selected_resource || {};
  const status = taskStatusClass(task);
  const label = firstWindow
    ? firstWindow.id || "切片"
    : selected.kind || (task.media_path ? "视频" : task.error_code ? "诊断" : "任务");
  const detail = firstWindow
    ? `${fmt(firstWindow.start)} - ${fmt(firstWindow.end)}`
    : task.media_path
      ? "media.mp4"
      : task.error_code || taskStatusText(task);
  if (firstWindow?.grid_url) {
    return `<figure class="history-task-preview status-${escapeHtml(status)}">
      <img src="${escapeHtml(firstWindow.grid_url)}" alt="${escapeHtml(firstWindow.id || "frame grid")}">
      <figcaption><b>${escapeHtml(label)}</b><span>${escapeHtml(detail)}</span></figcaption>
    </figure>`;
  }
  return `<figure class="history-task-preview status-${escapeHtml(status)} empty">
    <div>${escapeHtml(taskHistoryPreviewIcon(task.status))}</div>
    <figcaption><b>${escapeHtml(label)}</b><span>${escapeHtml(detail)}</span></figcaption>
  </figure>`;
}

function renderTaskHistory() {
  if (!els.taskHistory) return;
  const visible = taskHistory.slice(0, 6);
  if (!visible.length) {
    els.taskHistory.className = "task-history muted";
    els.taskHistory.textContent = "等待任务生成后显示最近记录";
    return;
  }
  els.taskHistory.className = "task-history";
  els.taskHistory.innerHTML = visible.map(task => `
    <button class="history-task status-${escapeHtml(task.status || "unknown")} ${task.id === currentTaskId ? "selected" : ""}" data-id="${escapeHtml(task.id)}">
      ${taskHistoryPreviewHtml(task)}
      <span>
        <strong>${escapeHtml(task.title || task.id)}</strong>
        <small>${escapeHtml(taskSourceText(task))} · ${escapeHtml(taskStatusText(task))} · ${task.progress || 0}%</small>
        ${taskHistoryChipsHtml(task)}
      </span>
    </button>
  `).join("");
  document.querySelectorAll(".history-task").forEach(button => {
    button.onclick = () => selectHistoryTask(button.dataset.id);
  });
}

async function loadTaskHistory() {
  if (!els.taskHistory) return;
  try {
    const data = await fetch(`${backendUrl}/api/tasks`).then(r => r.json());
    taskHistory = data.tasks || [];
    renderTaskHistory();
  } catch {
    els.taskHistory.className = "task-history muted";
    els.taskHistory.textContent = "无法读取本地历史";
  }
}

async function selectHistoryTask(taskId) {
  if (!taskId) return;
  currentTaskId = taskId;
  transcriptCache = null;
  lastNote = "";
  await loadResult();
  resetResultScroll();
  renderTaskHistory();
}

function readOptions() {
  syncTranscriberModelDefault();
  const [cols, rows] = els.gridSize.value.split("x").map(Number);
  const options = {
    visual_understanding: true,
    frame_interval: Number(els.frameInterval.value || 20),
    grid_columns: cols || 3,
    grid_rows: rows || 3,
    transcriber: els.transcriber?.value || "faster-whisper",
    whisper_model: els.whisperModel.value || "small",
    note_style: els.noteStyle.value || "study",
    summary_depth: els.summaryDepth.value || "standard"
  };
  const llmModel = els.llmModel.value.trim();
  const llmBaseUrl = els.llmBaseUrl.value.trim();
  const llmApiKey = els.llmApiKey.value.trim();
  if (llmModel) options.llm_model = llmModel;
  if (llmBaseUrl) options.llm_base_url = llmBaseUrl;
  if (llmApiKey) options.llm_api_key = llmApiKey;
  return options;
}

function syncTranscriberModelDefault(force = false) {
  if (!els.transcriber || !els.whisperModel) return;
  const transcriber = els.transcriber.value || "faster-whisper";
  const model = els.whisperModel.value || "small";
  if (transcriber === "faster-whisper" && !LOCAL_ASR_MODELS.has(model)) {
    els.whisperModel.value = "small";
  } else if (transcriber === "openai-compatible" && (force || LOCAL_ASR_MODELS.has(model))) {
    els.whisperModel.value = "whisper-1";
  } else if (transcriber === "groq" && (force || LOCAL_ASR_MODELS.has(model))) {
    els.whisperModel.value = "whisper-large-v3";
  }
}

function transcriberLabel(value) {
  return ({
    "faster-whisper": "本地 faster-whisper",
    "openai-compatible": "OpenAI-compatible ASR",
    "openai-compatible-asr": "OpenAI-compatible ASR",
    openai: "OpenAI ASR",
    groq: "Groq ASR",
    "groq-asr": "Groq ASR"
  })[String(value || "faster-whisper").toLowerCase()] || String(value || "ASR");
}

function asrOptionText(options = {}) {
  return `${transcriberLabel(options.transcriber)} · ${options.whisper_model || "small"}`;
}

function transcriptSourceText(source) {
  return ({
    "browser-subtitle": "浏览器字幕",
    "page-subtitle": "页面字幕",
    "embedded-subtitle": "视频内嵌字幕",
    "faster-whisper": "本地 faster-whisper",
    "openai-compatible-asr": "OpenAI-compatible ASR",
    "groq-asr": "Groq ASR"
  })[String(source || "").toLowerCase()] || source || "转写";
}

function isDownloadableResource(item) {
  return DOWNLOADABLE_KINDS.has(item?.kind);
}

function playbackText(match) {
  return ({
    "exact-src": "当前 src",
    "source-element": "当前 source",
    "same-frame": "同播放器 frame",
    "blob-same-frame": "blob 播放同 frame",
    "blob-source": "Blob/MSE 来源映射",
    "range-near-playhead": "播放进度附近 Range 请求",
    "recent-media-request": "最近播放请求",
    "same-site-request": "同站请求",
    "inferred-from-fragment": "分片推断"
  })[match] || match || "";
}

function pickDefaultResourceUrl(items, previousUrl = "") {
  if (!items.length) return "";
  const previous = previousUrl ? items.find(item => item.url === previousUrl) : null;
  const downloadable = items.filter(isDownloadableResource);
  const preferred = downloadable.find(item => item.playback_match || item.is_main_video) || downloadable[0];
  if (!previous) return preferred?.url || items[0]?.url || "";
  if (resourceSelectionPinned) return previous.url;
  const previousMatched = Boolean(previous.playback_match || previous.is_main_video);
  const preferredMatched = Boolean(preferred?.playback_match || preferred?.is_main_video);
  if (preferred?.url && preferredMatched && !previousMatched) return preferred.url;
  return previous.url;
}

function selectedResource() {
  return resources.find(item => item.url === selectedResourceUrl) || null;
}

function hasPageTextFallback() {
  if ((page?.page_text || "").trim()) return true;
  return (page?.browser_subtitles || []).some(item => (item?.text || "").trim());
}

function isPlaybackMatchedResource(item) {
  return Boolean(item?.playback_match || item?.is_main_video);
}

function isDiagnosticResource(item) {
  return !isDownloadableResource(item) || ["blob", "fragment", "subtitle", "unknown"].includes(item?.kind || "");
}

function resourceFilterOptions() {
  return [
    {
      key: "all",
      label: "全部",
      count: resources.length,
      match: () => true
    },
    {
      key: "downloadable",
      label: "可直取",
      count: resources.filter(isDownloadableResource).length,
      match: isDownloadableResource
    },
    {
      key: "matched",
      label: "播放匹配",
      count: resources.filter(isPlaybackMatchedResource).length,
      match: isPlaybackMatchedResource
    },
    {
      key: "diagnostic",
      label: "诊断线索",
      count: resources.filter(isDiagnosticResource).length,
      match: isDiagnosticResource
    }
  ];
}

function resourceFilterOption(key = resourceFilter) {
  return resourceFilterOptions().find(item => item.key === key) || resourceFilterOptions()[0];
}

function filteredResources() {
  const option = resourceFilterOption();
  return resources.filter(option.match);
}

function resourceFilterBarHtml() {
  if (!resources.length) return "";
  return `<div class="resource-filter-bar" aria-label="候选资源筛选">
    ${resourceFilterOptions().map(option => `<button type="button" class="${option.key === resourceFilter ? "active" : ""}" data-resource-filter="${escapeHtml(option.key)}">
      <span>${escapeHtml(option.label)}</span>
      <b>${escapeHtml(option.count)}</b>
    </button>`).join("")}
  </div>`;
}

function currentPreflight() {
  const item = selectedResource();
  if (!item?.url) return null;
  return preflightForResource(item);
}

function preflightForResource(item) {
  if (!item?.url) return null;
  return preflightResultsByUrl.get(item.url) || (preflight && preflightResourceUrl === item.url ? preflight : null);
}

function applyPreflightToResource(resource, result) {
  if (!resource || !result?.downloadable) return;
  const kind = String(result.kind || "").toLowerCase();
  if (DOWNLOADABLE_KINDS.has(kind)) resource.kind = kind;
  if (result.resolved_url && result.resolved_url !== resource.url) resource.resolved_url = result.resolved_url;
  if (result.content_type) {
    const resolvedMime = result.strategy === "direct-response-probe" && isTextResponseMime(result.content_type)
      ? mediaMimeForKind(resource.kind || kind)
      : result.content_type;
    if (resolvedMime) resource.mime = resolvedMime;
    resource.headers = { ...(resource.headers || {}), "content-type": result.content_type };
  }
  if (result.content_disposition) {
    resource.headers = { ...(resource.headers || {}), "content-disposition": result.content_disposition };
  }
  const statusCode = Number(result.status_code);
  if (Number.isFinite(statusCode) && statusCode > 0) resource.status_code = statusCode;
  const contentLength = Number(result.content_length);
  if (Number.isFinite(contentLength) && contentLength > 0) {
    resource.content_length = contentLength;
  }
}

function rememberPreflightResult(resource, result) {
  if (!resource?.url || !result) return result;
  applyPreflightToResource(resource, result);
  preflight = result;
  preflightResourceUrl = resource.url;
  preflightResultsByUrl.set(resource.url, result);
  return result;
}

function isMediaTaskMode(mode) {
  return mode === "video" || mode === "download_only";
}

function shouldPreflightBeforeStart(mode, item) {
  if (!isMediaTaskMode(mode)) return false;
  if (!item?.url) return false;
  return ["video", "hls", "dash", "blob", "fragment"].includes(item.kind);
}

function preflightBlockMessage(result) {
  return result?.message || result?.code || "当前候选资源预检未通过；请换一个候选、重新检测，或使用本地视频入口。";
}

function canAttemptBackendPageFallback(mode = "video") {
  if (!isMediaTaskMode(mode)) return false;
  const pageUrl = page?.page_url || "";
  return /^https?:\/\//i.test(pageUrl);
}

function preflightFallbackStartMessage(result) {
  const reason = result?.message || result?.code || "直取候选暂不可用";
  return `${reason}；继续创建任务，交给后端页面扫描、iframe fallback 和 yt-dlp 继续尝试。`;
}

function preflightRecoveryText(result = {}) {
  const code = result.code || "";
  if (code === "auth_required") return "重新打开课程页并确认已登录，然后播放几秒后重新检测；Cookie 只会在点击任务时同步一次。";
  if (code === "drm_or_encrypted") return "当前版本不会录制、破解或绕过 DRM；如果没有可访问 mp4/FLV/m3u8/mpd，请改用本地视频入口。";
  if (code === "download_forbidden") return "通常是 Referer、Cookie 或签名过期；回到原页面继续播放后立刻重新预检，或换一个候选资源。";
  if (code === "unsupported_manifest") return "检测到的可能只是分片或非完整 manifest；继续播放后重新检测，优先选择 m3u8/mpd 候选。";
  if (code === "no_media_found") return "当前页还没有暴露可直取资源；先播放几秒，等待媒体请求出现，再重新检测。";
  if (code === "preflight_failed") return "本地后端或扩展通信没有完成；确认 127.0.0.1 后端可用后重试。";
  if (result.downloadable) return "可以直接开始完整总结，或先用“下载本地”验证可导出的 media.mp4。";
  return "可以换一个候选、重新检测，或使用本地视频入口。";
}

function recoveryStepItems(task) {
  const attempts = task?.download_attempts || [];
  const codes = new Set([task?.error_code, ...attempts.map(attempt => attempt.code)].filter(Boolean));
  const steps = [];
  const add = text => {
    if (text && !steps.includes(text)) steps.push(text);
  };
  if (codes.has("drm_or_encrypted") || task?.drm_detected) {
    add("不会录制、破解或绕过 DRM；没有可访问 mp4/FLV/m3u8/mpd 时，请改用本地视频入口。");
  }
  if (codes.has("auth_required")) {
    add("重新打开课程页并确认登录有效，播放几秒后立刻重新创建任务。");
  }
  if (codes.has("download_forbidden")) {
    add("回到原页面继续播放后重新检测，优先选择带 Referer/Origin 或当前播放匹配的候选。");
  }
  if (codes.has("unsupported_manifest")) {
    add("继续播放后重新检测，优先选择完整 m3u8/mpd，而不是孤立 ts/m4s 分片。");
  }
  if (codes.has("no_media_found") || (!attempts.length && task?.status === "failed")) {
    add("先让视频实际播放几秒再重新检测；仍没有候选时上传本地视频。");
  }
  if (attempts.length > 1) {
    add(`后端已尝试 ${attempts.length} 条路线；打开诊断查看每次失败的 URL、状态码和策略。`);
  }
  if (task?.selected_resource?.request_headers && Object.keys(task.selected_resource.request_headers).length) {
    add(`已捕获可复用请求头名：${requestHeaderNames(task.selected_resource)}；不会保存 Cookie 或 Authorization 值。`);
  }
  if (hasRangeRequestHeader(task?.selected_resource)) {
    add("Range 只作为浏览器播放证据；正式下载会去掉播放 Range，避免只保存一个视频片段。");
  }
  if (canContinueFromDownloadedMedia(task)) {
    add("这个任务已把视频下载到本地，可先导出 media.mp4，或点击“继续切片总结”复用本地视频生成完整笔记。");
  }
  if (task?.note_path) {
    add("已生成兜底笔记时，可以先导出 Markdown/资料包复习，再按诊断重新尝试直取。");
  }
  if (!steps.length) add("打开诊断查看下载尝试记录；当前页直取不稳定时可改用本地视频入口。");
  return steps;
}

function diagnosticRecoveryHtml(task) {
  const steps = recoveryStepItems(task);
  return `<section class="diagnostic-recovery" aria-label="恢复建议">
    <strong>下一步建议</strong>
    <ul>${steps.map(step => `<li>${escapeHtml(step)}</li>`).join("")}</ul>
    ${recoveryActionsHtml(task)}
  </section>`;
}

function recoveryActionsHtml(task) {
  if (!task) return "";
  const actions = [
    `<button type="button" data-recovery-local>上传本地视频</button>`,
    `<button type="button" data-switch-result-tab="diagnostics">查看诊断</button>`
  ];
  if (hasTaskDiagnostics(task)) {
    actions.push(`<button type="button" data-export="diagnostics">导出诊断</button>`);
  }
  if (canContinueFromDownloadedMedia(task)) {
    actions.push(`<button type="button" data-rerun-from-media="${escapeHtml(task.id)}">继续切片总结</button>`);
  }
  if (task.note_path) {
    actions.push(`<button type="button" data-export="markdown">导出 Markdown</button>`);
  }
  return `<div class="recovery-actions">${actions.join("")}</div>`;
}

function drmSignalText(signals = []) {
  const parts = [];
  const keySystems = [...new Set(signals.map(item => item.key_system).filter(Boolean))];
  const initTypes = [...new Set(signals.map(item => item.init_data_type).filter(Boolean))];
  if (keySystems.length) parts.push(`key system：${keySystems.slice(0, 3).join(", ")}`);
  if (initTypes.length) parts.push(`init data：${initTypes.slice(0, 3).join(", ")}`);
  return parts.join(" · ");
}

function directnessText(item) {
  if (!item) return "未选择资源";
  const playerSource = playerLibrarySourceText(item);
  if (isDownloadableResource(item)) {
    if (item.kind === "hls") return playerSource ? `${playerSource} HLS manifest，可交给 ffmpeg 合并` : "HLS manifest，可交给 ffmpeg 合并";
    if (item.kind === "dash") return playerSource ? `${playerSource} DASH manifest，可交给 ffmpeg 合并` : "DASH manifest，可交给 ffmpeg 合并";
    return playerSource ? `${playerSource} 视频文件，可下载到本地处理` : "直接视频文件，可下载到本地处理";
  }
  if (item.kind === "blob") return "blob 播放地址线索，不可直接下载";
  if (item.kind === "fragment") return "分片线索，需要对应 manifest";
  if (item.kind === "subtitle") return "字幕轨，可辅助转写";
  return "媒体线索，需继续检测";
}

function playerLibrarySourceText(item) {
  if (item?.source !== "pageHookPlayer") return "";
  const label = String(item.label || "");
  const libraries = [
    [/hls\.js/i, "hls.js"],
    [/dash\.js/i, "dash.js"],
    [/shaka/i, "shaka"],
    [/video\.js/i, "video.js"],
    [/DPlayer/i, "DPlayer"],
    [/ArtPlayer/i, "ArtPlayer"],
    [/\bxgplayer\b|XGPlayer/i, "xgplayer"],
    [/Aliplayer/i, "Aliplayer"],
    [/TcPlayer/i, "TcPlayer"],
    [/jwplayer/i, "jwplayer"]
  ];
  const match = libraries.find(([pattern]) => pattern.test(label));
  if (match) return `${match[1]} 已加载`;
  return "播放器已加载";
}

function resourceSourceText(item) {
  const playerSource = playerLibrarySourceText(item);
  if (playerSource) return `${playerSource}源地址`;
  if (item?.source === "manifest-guess") return "同目录 manifest 猜测";
  if (item?.source === "inferred-manifest") return "分片路径回推 manifest";
  if (item?.source === "webRequest") return "浏览器请求";
  if (String(item?.source || "").startsWith("pageHook")) return "页面接口";
  return item?.source || "";
}

function requestEvidence(item) {
  if (!item) return "";
  return [
    resourceSourceText(item),
    playbackText(item.playback_match),
    item.is_main_video ? "主视频" : "",
    item.request_type,
    item.status_code ? `HTTP ${item.status_code}` : "",
    fmtBytes(item.content_length),
    requestBodySummary(item),
    contentDispositionHint(item.headers?.["content-disposition"]),
    item.frame_id !== null && item.frame_id !== undefined ? `frame ${item.frame_id}` : "",
    item.mime || ""
  ].filter(Boolean).join(" · ");
}

function responseEvidenceLine(item) {
  if (!item) return "";
  const headers = item.headers || {};
  const contentType = headers["content-type"] || item.mime || "";
  return [
    item.status_code ? `HTTP ${item.status_code}` : "",
    contentType,
    contentDispositionHint(headers["content-disposition"]),
    fmtBytes(item.content_length),
    headers["content-range"] ? `range ${headers["content-range"]}` : "",
    headers["accept-ranges"] ? `accept-ranges ${headers["accept-ranges"]}` : ""
  ].filter(Boolean).join(" · ");
}

function requestHeaderValue(item, targetName) {
  const target = String(targetName || "").toLowerCase();
  for (const [name, value] of Object.entries(item?.request_headers || {})) {
    if (String(name).toLowerCase() === target) return String(value || "");
  }
  return "";
}

function requestBodySummary(item) {
  const body = item?.request_body || {};
  const content = String(body.content || "");
  if (!content) return "";
  const method = String(item.method || "POST").toUpperCase();
  const type = String(body.type || "body");
  if (content === "<redacted>") return `${method} ${type} body 已捕获`;
  return `${method} ${type} body ${fmtBytes(content.length) || `${content.length} B`}`;
}

function resourceHasRangeRequest(item) {
  return /^bytes=\d*-\d*$/i.test(requestHeaderValue(item, "range").trim());
}

function resourceEvidenceTags(item) {
  if (!item) return [];
  const tags = [];
  const add = value => {
    if (value && !tags.includes(value)) tags.push(value);
  };
  if (item.is_main_video) add("当前主视频");
  add(playbackText(item.playback_match));
  if (item.kind === "hls" || item.kind === "dash") add("可合并 manifest");
  if (item.kind === "video") add("可直接下载");
  if (item.kind === "blob") add("blob 线索");
  if (item.kind === "fragment") add("分片线索");
  if (item.blob_url) add("blob/MSE 映射");
  if (item.source === "webRequest") add("浏览器请求");
  const playerSource = playerLibrarySourceText(item);
  if (playerSource) add(`${playerSource}源地址`);
  if (item.source === "manifest-guess") add("同目录 manifest 猜测");
  if (item.source === "inferred-manifest") add("分片路径回推");
  if (String(item.source || "").startsWith("pageHook")) add("页面接口");
  if (item.request_type === "media") add("media 请求");
  if (resourceHasRangeRequest(item)) add("Range 播放请求");
  if (requestBodySummary(item)) add("POST body");
  if (requestHeaderValue(item, "referer") || requestHeaderValue(item, "origin")) add("带 Referer/Origin");
  if (item.status_code) add(`HTTP ${item.status_code}`);
  return tags.slice(0, 9);
}

function resourceReasonText(item) {
  const tags = resourceEvidenceTags(item);
  return tags.length ? tags.join(" · ") : "";
}

function resourceTagHtml(item, limit = 4) {
  const tags = resourceEvidenceTags(item);
  if (!tags.length) return "";
  const visible = tags.slice(0, limit);
  const overflow = tags.length - visible.length;
  return `<span class="resource-tags">${visible.map(tag => `<em>${escapeHtml(tag)}</em>`).join("")}${overflow > 0 ? `<em>+${overflow}</em>` : ""}</span>`;
}

function candidateStrategyText(item) {
  if (!item) return "等待检测";
  if (item.kind === "hls" || item.kind === "dash") return "ffmpeg 合并";
  if (item.kind === "video") return "直接下载";
  if (item.kind === "fragment") return "尝试推断 manifest";
  if (item.kind === "blob") return "不可直接下载";
  if (item.kind === "subtitle") return "字幕辅助";
  return "后端解析";
}

function candidateConfidence(item) {
  if (!item) return { className: "muted", label: "待判断", detail: "等待候选资源。" };
  if (item.source === "manifest-guess") {
    return {
      className: "low",
      label: "低置信兜底",
      detail: "由分片同目录猜测 manifest，需要预检确认。"
    };
  }
  if (item.source === "inferred-manifest") {
    return {
      className: "medium",
      label: "路径回推",
      detail: "从分片 URL 中已有的 manifest 路径回推。"
    };
  }
  if (item.playback_match || item.is_main_video) {
    return {
      className: "high",
      label: "播放匹配",
      detail: "与当前播放器或最近播放请求匹配，优先预检。"
    };
  }
  if (item.source === "webRequest" || String(item.source || "").startsWith("pageHook")) {
    return {
      className: "medium",
      label: "请求证据",
      detail: "来自浏览器请求或页面播放器接口。"
    };
  }
  return {
    className: "muted",
    label: "待验证",
    detail: "需要预检判断是否可下载。"
  };
}

function candidateConfidenceHtml(item) {
  const confidence = candidateConfidence(item);
  return `<span class="resource-confidence ${escapeHtml(confidence.className)}">${escapeHtml(confidence.label)}</span>`;
}

function candidateTryOrder(item) {
  if (!item?.url) return 0;
  const index = selectedResources().findIndex(candidate => candidate.url === item.url);
  return index >= 0 ? index + 1 : 0;
}

function resourcePriorityBadgeHtml(item) {
  const order = candidateTryOrder(item);
  const label = order ? `第 ${order} 顺位` : "未排序";
  return `<span class="resource-priority">${escapeHtml(label)} · ${escapeHtml(candidateStrategyText(item))}</span>`;
}

function preflightBadgeHtml(item) {
  const result = preflightForResource(item);
  if (!result) return "";
  const state = result.downloadable ? "ok" : result.code === "drm_or_encrypted" ? "bad" : "warn";
  const resolvedLabel = result.strategy === "direct-response-probe" && result.resolved_url ? "解析媒体 URL" : "";
  const label = result.downloadable
    ? `预检通过 · ${result.kind || item.kind || "media"}`
    : `预检未过 · ${result.code || result.message || "不可直取"}`;
  const detail = [
    resolvedLabel,
    result.status_code ? `HTTP ${result.status_code}` : "",
    result.content_type || "",
    contentDispositionHint(result.content_disposition),
    fmtBytes(result.content_length) || (result.bytes_checked ? `${result.bytes_checked} B` : "")
  ].filter(Boolean).join(" · ");
  return `<span class="resource-preflight ${state}">${escapeHtml(detail ? `${label} · ${detail}` : label)}</span>`;
}

function resourceAttemptState(item) {
  const result = preflightForResource(item);
  if (result?.downloadable) return { className: "ok", label: "预检通过" };
  if (result) return { className: result.code === "drm_or_encrypted" ? "bad" : "warn", label: result.code || "预检未过" };
  if (isDownloadableResource(item)) return { className: "pending", label: "待预检" };
  if (item?.kind === "blob" || item?.kind === "fragment") return { className: "warn", label: "线索" };
  return { className: "muted", label: "候选" };
}

function resourceAttemptQueueHtml(limit = 4) {
  if (!resources.length) return "";
  const ordered = selectedResources().slice(0, limit);
  return `<section class="resource-attempt-queue" aria-label="候选下载队列">
    <div class="resource-attempt-head">
      <strong>下载队列</strong>
      <span>${resources.filter(isDownloadableResource).length}/${resources.length} 可直取</span>
    </div>
    <div class="resource-attempt-list">
      ${ordered.map((item, index) => {
        const state = resourceAttemptState(item);
        const evidence = [
          item.kind || "media",
          candidateStrategyText(item),
          candidateConfidence(item).label,
          item.score ? `${item.score}%` : "",
          playbackText(item.playback_match),
          resourceSourceText(item)
        ].filter(Boolean).join(" · ");
        return `<button type="button" class="resource-attempt-row ${item.url === selectedResourceUrl ? "selected" : ""}" data-url="${escapeHtml(item.url)}">
          <em>${index + 1}</em>
          <span>
            <strong>${escapeHtml(item.label || item.kind || "media")}</strong>
            <small>${escapeHtml(evidence || directnessText(item))}</small>
          </span>
          <b class="${escapeHtml(state.className)}">${escapeHtml(state.label)}</b>
        </button>`;
      }).join("")}
    </div>
  </section>`;
}

function activeVideoText(active) {
  if (!hasActiveVideoSignal(active)) return "-";
  return [
    active.paused ? "暂停" : "播放中",
    `${fmt(active.current_time || 0)} / ${fmt(active.duration || 0)}`,
    `${active.width || 0}x${active.height || 0}`,
    active.frame_id !== null && active.frame_id !== undefined ? `frame ${active.frame_id}` : "",
    active.drm_detected ? "DRM/EME" : "",
    activeSrcObjectOnly(active) ? srcObjectText(active) : active.src
  ].filter(Boolean).join(" · ");
}

function compactUrl(value, limit = 92) {
  const text = String(value || "").trim();
  if (!text) return "";
  if (text.length <= limit) return text;
  const head = Math.max(24, Math.floor(limit * 0.42));
  const tail = Math.max(24, limit - head - 3);
  return `${text.slice(0, head)}...${text.slice(-tail)}`;
}

function playbackReadinessState() {
  const active = page?.active_video || null;
  const frames = page?.frames || [];
  const subtitles = page?.browser_subtitles || [];
  const downloadable = resources.filter(isDownloadableResource);
  const drmDetected = page?.drm_detected || active?.drm_detected;
  const isBlob = Boolean(active?.src?.startsWith("blob:"));
  const srcObjectOnly = activeSrcObjectOnly(active);
  if (drmDetected && !downloadable.length) return "blocked";
  if (downloadable.length) return "ready";
  if (srcObjectOnly) return "blocked";
  if (hasActiveVideoSignal(active) || frames.length) return isBlob ? "mapping" : "waiting";
  if (subtitles.length) return "waiting";
  return "empty";
}

function hasActiveVideoSignal(active) {
  return Boolean(active?.src || active?.src_object);
}

function activeSrcObjectOnly(active) {
  return Boolean(active?.src_object && !active?.src);
}

function srcObjectText(active) {
  if (!active?.src_object) return "";
  const tracks = [];
  if (active.src_object_video_tracks) tracks.push(`${active.src_object_video_tracks} video`);
  if (active.src_object_audio_tracks) tracks.push(`${active.src_object_audio_tracks} audio`);
  if (!tracks.length && active.src_object_track_count) tracks.push(`${active.src_object_track_count} track`);
  return [active.src_object_type || "MediaStream", tracks.join(" + ")].filter(Boolean).join(" · ");
}

function playbackSourceLabel(active) {
  if (!hasActiveVideoSignal(active)) return "未读取";
  if (activeSrcObjectOnly(active)) return "MediaStream/srcObject";
  if (active.src.startsWith("blob:")) return "Blob/MSE";
  if (/^https?:\/\//i.test(active.src)) return "可见 URL";
  return "播放器源";
}

function playbackReadinessCopy(state) {
  const downloadable = resources.filter(isDownloadableResource).length;
  const matched = resources.filter(item => item.playback_match || item.is_main_video).length;
  const subtitleCount = (page?.browser_subtitles || []).length;
  const frames = page?.frames || [];
  if (state === "blocked") {
    if (activeSrcObjectOnly(page?.active_video)) {
      return {
        title: "当前视频来自 MediaStream",
        detail: "页面没有暴露可下载 URL；不会录制当前标签页，请使用本地视频入口或页面文本兜底。"
      };
    }
    return {
      title: "检测到 DRM/不可还原媒体",
      detail: "不会录制、破解或绕过 DRM；没有可直取资源时请使用本地视频入口。"
    };
  }
  if (state === "ready") {
    return {
      title: "已读取当前播放视频",
      detail: matched ? `有 ${matched} 个候选与播放器匹配，可先预检再总结。` : `发现 ${downloadable} 个可直取候选，可先预检再总结。`
    };
  }
  if (state === "mapping") {
    return {
      title: "播放器是 Blob/MSE，正在找真实媒体",
      detail: "继续播放几秒后重检，扩展会用 webRequest 和页面接口线索映射真实 URL。"
    };
  }
  if (state === "waiting") {
    return {
      title: "已读取页面线索，等待可直取资源",
      detail: frames.length ? `已扫描 ${frames.length} 个 frame；继续播放或重新检测。` : "继续播放几秒后重新检测媒体请求。"
    };
  }
  return {
    title: subtitleCount ? "已读取字幕线索，等待视频资源" : "等待播放器信号",
    detail: subtitleCount ? `已读取 ${subtitleCount} 条浏览器字幕，可作为兜底文本。` : "先播放课程视频，再点击重新检测。"
  };
}

function renderPlaybackReadiness() {
  if (!els.playbackReadiness) return;
  const active = page?.active_video || null;
  const subtitles = page?.browser_subtitles || [];
  const downloadable = resources.filter(isDownloadableResource);
  const matched = resources.filter(item => item.playback_match || item.is_main_video);
  const state = playbackReadinessState();
  const copy = playbackReadinessCopy(state);
  const playValue = active?.src
    ? active.paused ? "暂停" : "播放中"
    : active?.src_object ? active.paused ? "MediaStream 暂停" : "MediaStream 播放中"
    : (page?.frames || []).length ? `扫描 ${(page?.frames || []).length} frame` : "等待";
  const items = [
    { label: "播放", value: playValue },
    { label: "源类型", value: playbackSourceLabel(active) },
    { label: "候选", value: matched.length ? `${matched.length}/${resources.length} 匹配` : `${downloadable.length}/${resources.length}` },
    { label: "字幕", value: subtitles.length ? `${subtitles.length} 条` : "未读取" }
  ];
  els.playbackReadiness.className = `playback-readiness ${state}`;
  els.playbackReadiness.innerHTML = `
    <div class="playback-readiness-head">
      <strong>${escapeHtml(copy.title)}</strong>
      <small>${escapeHtml(copy.detail)}</small>
    </div>
    <div class="playback-readiness-grid">
      ${items.map(item => `<span><b>${escapeHtml(item.value)}</b>${escapeHtml(item.label)}</span>`).join("")}
    </div>
  `;
}

function currentStudyState() {
  const state = routeSummaryState();
  if (state === "ready") return "ready";
  if (state === "candidate") return "candidate";
  if (state === "fallback") return "fallback";
  if (state === "blocked") return "blocked";
  return playbackReadinessState();
}

function currentStudyCopy(state) {
  if (state === "ready") {
    return {
      badge: "已验证",
      title: "可以开始当前视频总结",
      detail: "已确认后端可访问选中媒体；开始后会先下载到本地，再转写、切片和生成图文笔记。"
    };
  }
  if (state === "candidate") {
    return {
      badge: "待预检",
      title: "发现当前视频直取候选",
      detail: "建议先预检资源；开始任务时也会自动按队列尝试可下载候选。"
    };
  }
  if (state === "fallback" || state === "mapping") {
    return {
      badge: "需兜底",
      title: "正在把播放器线索映射成真实媒体",
      detail: "继续播放几秒后重检；若直链失败，后端会尝试页面解析，仍失败则使用本地视频入口。"
    };
  }
  if (state === "blocked") {
    if (activeSrcObjectOnly(page?.active_video)) {
      return {
        badge: "不可直取",
        title: "当前视频来自 MediaStream",
        detail: "没有可交给后端下载的媒体 URL；不会录制标签页，请使用本地视频或页面文本兜底。"
      };
    }
    return {
      badge: "不可直取",
      title: "当前页不能直接下载",
      detail: "不会录制、破解或绕过 DRM。可以继续播放重检，或拖入本地视频走同一套笔记管线。"
    };
  }
  if (state === "waiting") {
    return {
      badge: "等待资源",
      title: "已读到页面线索",
      detail: "保持课程视频播放几秒，扩展会继续捕获媒体请求和字幕变化。"
    };
  }
  return {
    badge: "等待播放",
    title: "播放课程后创建学习任务",
    detail: "打开课程视频并播放几秒，再让扩展检测可访问的 mp4、FLV、HLS 或 DASH。"
  };
}

function currentStudyMetrics() {
  const active = page?.active_video || null;
  const selected = selectedResource();
  const subtitles = page?.browser_subtitles || [];
  const [cols, rows] = String(els.gridSize?.value || "3x3").split("x").map(Number);
  const playTime = hasActiveVideoSignal(active)
    ? `${fmt(active.current_time || 0)} / ${fmt(active.duration || 0)}`
    : (page?.frames || []).length ? `${(page?.frames || []).length} frame` : "-";
  return [
    { label: "播放时间", value: playTime },
    { label: "直取路线", value: selected ? `${selected.kind || "media"} · ${candidateStrategyText(selected)}` : "等待候选" },
    { label: "字幕兜底", value: subtitles.length ? `${subtitles.length} 条` : "未读取" },
    { label: "画面切片", value: `${Number(els.frameInterval?.value || 20)}秒 · ${cols || 3}x${rows || 3}` }
  ];
}

function currentStudyActionText(state) {
  if (state === "ready") return "下一步：点击“总结当前视频”生成完整图文笔记。";
  if (state === "candidate") return "下一步：点击“预检资源”，确认当前候选能被本地后端访问。";
  if (state === "fallback" || state === "mapping" || state === "waiting") return "下一步：继续播放几秒后重新检测，或直接尝试后端解析。";
  if (state === "blocked") return "下一步：使用本地视频上传；本工具不会录制或绕过 DRM。";
  return "下一步：播放课程视频并点击重新检测。";
}

function renderCurrentStudyCard() {
  if (!els.currentStudyCard) return;
  const state = currentStudyState();
  const copy = currentStudyCopy(state);
  els.currentStudyCard.className = `current-study-card ${state}`;
  els.currentStudyCard.innerHTML = `
    <div class="current-study-head">
      <span>${escapeHtml(copy.badge)}</span>
      <div>
        <strong>${escapeHtml(copy.title)}</strong>
        <small>${escapeHtml(copy.detail)}</small>
      </div>
    </div>
    <div class="current-study-metrics">
      ${currentStudyMetrics().map(item => `<span><b>${escapeHtml(item.value)}</b>${escapeHtml(item.label)}</span>`).join("")}
    </div>
    <p>${escapeHtml(currentStudyActionText(state))}</p>
  `;
}

function launchBarActionsHtml(state) {
  const hasSelected = Boolean(selectedResource());
  const actions = [];
  if (state === "empty" || state === "fallback" || state === "blocked" || !hasSelected) {
    actions.push(`<button type="button" data-route-action="redetect">重检</button>`);
  }
  if (state === "candidate" && hasSelected) {
    actions.push(`<button type="button" data-route-action="preflight">预检</button>`);
  }
  if (state === "ready" || state === "candidate" || state === "fallback") {
    actions.push(`<button type="button" class="primary" data-route-action="summarize">总结</button>`);
  }
  if (hasSelected && state !== "blocked" && state !== "empty") {
    actions.push(`<button type="button" data-route-action="download">下载</button>`);
  }
  if (state === "blocked" || state === "fallback" || state === "mapping" || state === "waiting" || !hasSelected) {
    actions.push(`<button type="button" data-route-action="local">本地</button>`);
  }
  if (hasPageTextFallback() && (state === "blocked" || state === "fallback" || state === "empty" || state === "waiting" || !hasSelected)) {
    actions.push(`<button type="button" data-route-action="text">文本</button>`);
  }
  return actions.join("");
}

function launchBarMeta(state) {
  const selected = selectedResource();
  const checked = currentPreflight();
  const [cols, rows] = String(els.gridSize?.value || "3x3").split("x").map(Number);
  return [
    selected ? `${selected.kind || "media"} · ${candidateStrategyText(selected)}` : "等待候选",
    checked ? checked.downloadable ? "预检通过" : checked.code || "预检未过" : state === "candidate" ? "建议预检" : "未预检",
    `${Number(els.frameInterval?.value || 20)}秒 · ${cols || 3}x${rows || 3}`,
    "点击时同步 Cookie"
  ];
}

function renderLaunchBar() {
  if (!els.launchBar) return;
  const state = routeSummaryState();
  const copy = routeSummaryCopy(state);
  els.launchBar.className = `launch-bar ${state}`;
  els.launchBar.innerHTML = `
    <div class="launch-bar-main">
      <span>${escapeHtml(copy.badge)}</span>
      <strong>${escapeHtml(copy.title)}</strong>
      <small>${escapeHtml(launchBarMeta(state).join(" · "))}</small>
    </div>
    <div class="launch-bar-actions">
      ${launchBarActionsHtml(state)}
    </div>
  `;
}

function resourceHint() {
  const downloadable = resources.filter(isDownloadableResource).length;
  const blobCount = resources.filter(item => item.kind === "blob").length;
  const fragmentCount = resources.filter(item => item.kind === "fragment").length;
  const playbackMatched = resources.some(item => item.playback_match || item.is_main_video);
  const activeBlob = page?.active_video?.src?.startsWith("blob:");
  const activeStream = activeSrcObjectOnly(page?.active_video);
  const drmDetected = page?.drm_detected || page?.active_video?.drm_detected;
  if (drmDetected) {
    const detail = drmSignalText(page?.drm_signals || []);
    return `<p class="resource-hint bad">检测到 EME/DRM 加密媒体信号${detail ? `（${escapeHtml(detail)}）` : ""}；本工具不会录制、破解或绕过 DRM，只会继续尝试页面暴露的可访问 mp4/FLV/m3u8/mpd。</p>`;
  }
  if (activeStream && !downloadable) {
    return `<p class="resource-hint bad">当前播放器使用 MediaStream/srcObject，没有暴露可下载 URL；本工具不会录制标签页，请使用本地视频上传或页面文本兜底。</p>`;
  }
  if (downloadable && activeBlob) {
    return `<p class="resource-hint">当前播放器是 blob/MSE，已按同 frame、来源映射和最近媒体请求优先选择可直取候选。</p>`;
  }
  if (downloadable && playbackMatched) {
    return `<p class="resource-hint">已优先选择与当前播放状态匹配的可下载资源。</p>`;
  }
  if (!downloadable && (blobCount || fragmentCount)) {
    return `<p class="resource-hint warn">只检测到未映射的 blob 或分片线索；不会录制或破解。可以继续播放几秒后重新检测，或改用本地视频上传。</p>`;
  }
  return "";
}

function noResourceGuideHtml() {
  const drmDetected = page?.drm_detected || page?.active_video?.drm_detected;
  const activeStream = activeSrcObjectOnly(page?.active_video);
  const hasBlob = resources.some(item => item.kind === "blob");
  const hasFragment = resources.some(item => item.kind === "fragment");
  const state = drmDetected || activeStream ? "blocked" : hasBlob || hasFragment ? "warn" : "empty";
  const headline = drmDetected
    ? "当前页没有可直取媒体，且检测到 DRM/EME"
    : activeStream
      ? "当前视频来自 MediaStream，不能直接下载"
    : hasBlob || hasFragment
      ? "只看到 blob 或分片线索，还没还原到 manifest"
      : "还没有捕获到可下载的视频候选";
  const detail = drmDetected
    ? "不会录制、破解或绕过 DRM；可以改用本地视频入口走同一套转写、切片和图文总结。"
    : activeStream
      ? "MediaStream/srcObject 通常是 WebRTC、Canvas 或脚本生成流；没有浏览器可访问的 mp4/HLS/DASH 地址时，只能改用本地视频或页面文本。"
    : hasBlob || hasFragment
      ? "继续播放几秒后重新检测；如果页面暴露 m3u8/mpd/mp4 请求，候选会自动进入直取队列。"
      : "先让课程视频真实播放几秒，再重新检测媒体请求；也可以只总结当前页面文本。";
  const steps = [
    ["播放几秒", "让浏览器产生真实媒体请求"],
    ["重新检测", "读取 DOM、Performance 和 webRequest 缓存"],
    ["本地兜底", "上传视频后仍走切片和图文总结"]
  ];
  return `<section class="no-resource-guide ${escapeHtml(state)}" aria-label="无候选资源排障">
    <span>${escapeHtml(state === "blocked" ? "不可直取" : state === "warn" ? "需要重检" : "等待捕获")}</span>
    <strong>${escapeHtml(headline)}</strong>
    <p>${escapeHtml(detail)}</p>
    <ol>
      ${steps.map(([title, text], index) => `<li>
        <b>${index + 1}</b>
        <span>${escapeHtml(title)}</span>
        <small>${escapeHtml(text)}</small>
      </li>`).join("")}
    </ol>
    <div class="no-resource-actions">
      <button type="button" data-resource-empty-action="redetect">重新检测资源</button>
      <button type="button" data-resource-empty-action="local">上传本地视频</button>
      <button type="button" data-resource-empty-action="text">只总结页面文本</button>
    </div>
  </section>`;
}

function renderReadiness() {
  const downloadable = resources.filter(isDownloadableResource);
  const selected = selectedResource();
  const hasBlob = resources.some(item => item.kind === "blob");
  const hasFragment = resources.some(item => item.kind === "fragment");
  const checked = currentPreflight();
  const drmDetected = page?.drm_detected || page?.active_video?.drm_detected;
  const activeStream = activeSrcObjectOnly(page?.active_video);
  if (checked) {
    els.readiness.className = checked.downloadable ? "readiness" : checked.code === "drm_or_encrypted" ? "readiness bad" : "readiness warn";
    els.readiness.textContent = checked.downloadable
      ? `预检通过：后端可访问 ${checked.kind}，正式任务会完整下载。${preflightRecoveryText(checked)}`
      : `预检未通过：${checked.message || checked.code || "候选不可直取"}；${preflightRecoveryText(checked)}`;
    return;
  }
  if (drmDetected && !downloadable.length) {
    els.readiness.className = "readiness bad";
    els.readiness.textContent = "检测到 EME/DRM 加密媒体信号，且当前没有可直取 mp4/FLV/m3u8/mpd；不会录制或绕过 DRM，请改用本地视频入口。";
    return;
  }
  if (activeStream && !downloadable.length) {
    els.readiness.className = "readiness bad";
    els.readiness.textContent = "当前视频来自 MediaStream/srcObject，没有可直接下载的媒体 URL；不会录制标签页，请改用本地视频入口或页面文本兜底。";
    return;
  }
  if (downloadable.length) {
    els.readiness.className = "readiness";
    els.readiness.textContent = `可直取候选 ${downloadable.length} 个；当前选择：${directnessText(selected || downloadable[0])}`;
    return;
  }
  if (hasBlob || hasFragment) {
    els.readiness.className = "readiness warn";
    els.readiness.textContent = "只看到未映射的 blob 或分片线索；不会录制，继续播放后重新检测，或拖入本地视频。";
    return;
  }
  els.readiness.className = "readiness bad";
  els.readiness.textContent = "当前页还没有可下载媒体候选；可先播放几秒后重新检测。";
}

function extractionPlanStateClass(state) {
  if (state === "done") return "done";
  if (state === "active") return "active";
  if (state === "warn") return "warn";
  if (state === "blocked") return "blocked";
  return "ready";
}

function extractionPlanStatusText(state) {
  return {
    done: "已就绪",
    active: "进行中",
    warn: "需兜底",
    blocked: "不可用",
    ready: "待命"
  }[state] || "待命";
}

function selectedResourceLabel(item) {
  if (!item) return "等待媒体候选";
  return [
    item.kind || "media",
    resourceSourceText(item),
    item.score ? `${item.score}%` : ""
  ].filter(Boolean).join(" · ");
}

function routeSummaryState() {
  const selected = selectedResource();
  const checked = currentPreflight();
  const downloadableCount = resources.filter(isDownloadableResource).length;
  const drmDetected = page?.drm_detected || page?.active_video?.drm_detected;
  const activeStream = activeSrcObjectOnly(page?.active_video);
  const canFallback = canAttemptBackendPageFallback("video");
  if (checked?.downloadable) return "ready";
  if (checked && !checked.downloadable) return canFallback ? "fallback" : "blocked";
  if (downloadableCount) return "candidate";
  if (drmDetected) return "blocked";
  if (activeStream) return "blocked";
  if (resources.length && canFallback) return "fallback";
  if (resources.length) return "blocked";
  return "empty";
}

function routeSummaryCopy(state) {
  const selected = selectedResource();
  const checked = currentPreflight();
  const fallbackText = canAttemptBackendPageFallback("video")
    ? "后端仍会尝试页面扫描、iframe、Referer/Origin 和 yt-dlp。"
    : "当前没有可扫描页面 URL，只能继续播放重检或上传本地视频。";
  if (state === "ready") {
    return {
      badge: "可开始",
      title: "直取路线已验证",
      action: "点击“总结当前视频”会先下载到本地，再按切片窗口生成图文笔记。",
      detail: `${checked.kind || selected?.kind || "media"} 预检通过；${preflightRecoveryText(checked)}`
    };
  }
  if (state === "candidate") {
    return {
      badge: "待预检",
      title: "已找到可直取候选",
      action: "建议先预检资源；也可以直接总结，系统会自动预检并尝试下一个候选。",
      detail: selected ? `${selectedResourceLabel(selected)}；${directnessText(selected)}。` : "等待选择候选资源。"
    };
  }
  if (state === "fallback") {
    return {
      badge: "需兜底",
      title: "直链不稳，保留后端解析路线",
      action: "可以继续开始任务；若仍失败，使用本地视频入口走同一套切片总结。",
      detail: checked ? `${checked.message || checked.code || "预检未通过"}；${fallbackText}` : fallbackText
    };
  }
  if (state === "blocked") {
    const activeStream = activeSrcObjectOnly(page?.active_video);
    return {
      badge: "不可直取",
      title: activeStream ? "MediaStream 不能直接下载" : "当前页还不能直接下载",
      action: "不会录制或绕过 DRM。继续播放几秒后重检，或拖入本地视频。",
      detail: checked?.message || (activeStream ? "当前播放器只暴露 MediaStream/srcObject，没有可交给后端下载的 URL。" : page?.drm_detected || page?.active_video?.drm_detected ? "检测到 DRM/EME 或只有不可还原媒体线索。" : "没有可独立下载的 mp4/FLV/m3u8/mpd。")
    };
  }
  return {
    badge: "等待播放",
    title: "播放课程后自动识别",
    action: "先让页面视频播放几秒，再重新检测媒体请求。",
    detail: "系统只直取浏览器已暴露的可访问资源，不做标签页录制。"
  };
}

function routeSummaryMetrics() {
  const selected = selectedResource();
  const checked = currentPreflight();
  const [cols, rows] = String(els.gridSize?.value || "3x3").split("x").map(Number);
  return [
    { label: "候选", value: `${resources.filter(isDownloadableResource).length}/${resources.length}` },
    { label: "选中", value: selected?.kind || "-" },
    { label: "预检", value: checked ? checked.downloadable ? "通过" : checked.code || "未过" : "未跑" },
    { label: "切片", value: `${Number(els.frameInterval?.value || 20)}秒 · ${cols || 3}x${rows || 3}` }
  ];
}

function routeHandoffItems(state) {
  const selected = selectedResource();
  const checked = currentPreflight();
  const downloadableCount = resources.filter(isDownloadableResource).length;
  const [cols, rows] = String(els.gridSize?.value || "3x3").split("x").map(Number);
  return [
    {
      state: selected ? "done" : downloadableCount ? "active" : "pending",
      label: "资源证据",
      value: selected?.kind || `${downloadableCount}/${resources.length}`,
      detail: selected ? directnessText(selected) : "播放课程页后收集播放器、请求和字幕"
    },
    {
      state: checked?.downloadable ? "done" : checked ? "blocked" : state === "candidate" ? "active" : "pending",
      label: "可下载性",
      value: checked ? checked.downloadable ? "预检通过" : checked.code || "未通过" : "待预检",
      detail: checked ? checked.message || preflightRecoveryText(checked) : "点击预检候选，先确认后端能访问"
    },
    {
      state: state === "ready" ? "active" : "pending",
      label: "本地落地",
      value: state === "ready" ? "可开始" : "media.mp4",
      detail: "后端直下、ffmpeg 合并或 yt-dlp 兜底"
    },
    {
      state: "pending",
      label: "切片笔记",
      value: `${Number(els.frameInterval?.value || 20)}秒 · ${cols || 3}x${rows || 3}`,
      detail: "下载后转写、抽帧并生成视觉窗口"
    }
  ];
}

function routeHandoffHtml(state) {
  return `<div class="route-handoff" aria-label="当前页直取交接清单">
    ${routeHandoffItems(state).map(item => `<section class="${escapeHtml(item.state)}">
      <span>${escapeHtml(item.label)}</span>
      <strong>${escapeHtml(item.value || "-")}</strong>
      <small>${escapeHtml(item.detail || "-")}</small>
    </section>`).join("")}
  </div>`;
}

function routeSummaryActionsHtml(state) {
  const hasSelected = Boolean(selectedResource());
  const actions = [];
  if (state === "empty" || state === "fallback" || state === "blocked" || !hasSelected) {
    actions.push(`<button type="button" data-route-action="redetect">重新检测</button>`);
  }
  if (hasSelected && state !== "ready") {
    actions.push(`<button type="button" data-route-action="preflight">预检候选</button>`);
  }
  if (state === "ready" || state === "candidate" || state === "fallback") {
    actions.push(`<button type="button" data-route-action="summarize">总结当前视频</button>`);
  }
  if (hasSelected && state !== "blocked") {
    actions.push(`<button type="button" data-route-action="download">下载本地</button>`);
  }
  if (state === "blocked" || state === "fallback" || !hasSelected) {
    actions.push(`<button type="button" data-route-action="local">上传本地视频</button>`);
  }
  if (hasPageTextFallback() && (state === "blocked" || state === "fallback" || state === "empty" || !hasSelected)) {
    actions.push(`<button type="button" data-route-action="text">只总结页面文本</button>`);
  }
  if (!actions.length) return "";
  return `<div class="route-summary-actions">${actions.join("")}</div>`;
}

function renderRouteSummary() {
  if (!els.routeSummary) return;
  const state = routeSummaryState();
  const copy = routeSummaryCopy(state);
  els.routeSummary.className = `route-summary ${state}`;
  els.routeSummary.innerHTML = `
    <div class="route-summary-main">
      <span>${escapeHtml(copy.badge)}</span>
      <strong>${escapeHtml(copy.title)}</strong>
      <small>${escapeHtml(copy.action)}</small>
    </div>
    <div class="route-summary-detail">${escapeHtml(copy.detail)}</div>
    <div class="route-summary-metrics">
      ${routeSummaryMetrics().map(item => `<span><b>${escapeHtml(item.value)}</b>${escapeHtml(item.label)}</span>`).join("")}
    </div>
    ${routeHandoffHtml(state)}
    ${routeSummaryActionsHtml(state)}
  `;
}

function renderExtractionPlan() {
  if (!els.extractionPlan) return;
  const selected = selectedResource();
  const checked = currentPreflight();
  const downloadableCount = resources.filter(isDownloadableResource).length;
  const pageFallback = canAttemptBackendPageFallback("video");
  const drmDetected = page?.drm_detected || page?.active_video?.drm_detected;
  const directState = checked
    ? checked.downloadable ? "done" : "warn"
    : downloadableCount ? "active" : drmDetected ? "blocked" : resources.length ? "warn" : "blocked";
  const fallbackState = pageFallback
    ? checked?.downloadable ? "ready" : "active"
    : "blocked";
  const localState = "ready";
  const directDetail = checked
    ? checked.downloadable
      ? `${checked.kind || selected?.kind || "media"} 可访问，任务会优先直取。`
      : `${checked.code || checked.message || "预检未通过"}，会保留证据并尝试兜底。`
    : selected
      ? `${selectedResourceLabel(selected)}；${directnessText(selected)}。`
      : "播放几秒或重新检测后生成候选。";
  const fallbackDetail = pageFallback
    ? "当前页、iframe、Referer/Origin 和 yt-dlp 会作为下载兜底。"
    : "当前上下文没有可扫描的 HTTP(S) 页面 URL。";
  const localDetail = "本地视频走同一套转写、切片、视觉窗口和笔记管线。";
  const steps = [
    { key: "direct", title: "首选直取", state: directState, detail: directDetail },
    { key: "fallback", title: "页面兜底", state: fallbackState, detail: fallbackDetail },
    { key: "local", title: "本地入口", state: localState, detail: localDetail }
  ];
  els.extractionPlan.innerHTML = steps.map((step, index) => `
    <section class="extraction-step ${extractionPlanStateClass(step.state)}" data-step="${step.key}">
      <span>${index + 1}</span>
      <div>
        <strong>${escapeHtml(step.title)}</strong>
        <small>${escapeHtml(step.detail)}</small>
      </div>
      <em>${escapeHtml(extractionPlanStatusText(step.state))}</em>
    </section>
  `).join("");
}

function renderInspector() {
  const item = selectedResource();
  const checked = currentPreflight();
  if (!item) {
    els.resourceInspector.className = "resource-inspector muted";
    els.resourceInspector.textContent = "选择一个候选资源后显示请求证据。";
    return;
  }
  els.resourceInspector.className = "resource-inspector";
  const confidence = candidateConfidence(item);
  els.resourceInspector.innerHTML = `
    <strong>${escapeHtml(directnessText(item))}</strong>
    <div class="resource-inspector-actions">
      <button type="button" data-copy-resource-url>复制链接</button>
      <button type="button" data-copy-resource-report>复制证据</button>
    </div>
    <span>下载顺序：第 ${escapeHtml(candidateTryOrder(item) || "-")} 顺位 · ${escapeHtml(candidateStrategyText(item))}</span>
    <span>候选置信度：${escapeHtml(confidence.label)} · ${escapeHtml(confidence.detail)}</span>
    ${resourceReasonText(item) ? `<span>选择依据：${escapeHtml(resourceReasonText(item))}</span>` : ""}
    <span>${escapeHtml(requestEvidence(item) || "无请求证据")}</span>
    ${responseEvidenceLine(item) ? `<span>响应证据：${escapeHtml(responseEvidenceLine(item))}</span>` : ""}
    ${item.blob_url ? `<span>播放 blob：${escapeHtml(item.blob_url)}</span>` : ""}
    ${item.frame_url ? `<span>所在 frame：${escapeHtml(item.frame_url)}</span>` : ""}
    <span>复用请求头：${escapeHtml(requestHeaderNames(item))}</span>
    ${requestBodySummary(item) ? `<span>POST body：${escapeHtml(requestBodySummary(item))}</span>` : ""}
    ${checked ? `<span>预检：${escapeHtml(resourcePreflightLine(checked))}</span>` : ""}
    ${checked ? `<span>下一步：${escapeHtml(preflightRecoveryText(checked))}</span>` : ""}
    ${checked?.warnings?.length ? `<span>提示：${escapeHtml(checked.warnings.join("；"))}</span>` : ""}
    <code>${escapeHtml(item.url)}</code>
  `;
}

async function loadSettings() {
  if (!HAS_EXTENSION_API) {
    backendUrl = DEFAULT_BACKEND;
    return;
  }
  const data = await chrome.storage.local.get({ backendUrl: DEFAULT_BACKEND });
  backendUrl = data.backendUrl || DEFAULT_BACKEND;
}

async function saveSettings() {
  const next = prompt("后端地址", backendUrl);
  if (!next) return;
  backendUrl = next.replace(/\/$/, "");
  if (HAS_EXTENSION_API) await chrome.storage.local.set({ backendUrl });
  await health();
}

async function consumePendingSidePanelIntent() {
  if (!HAS_EXTENSION_API) return;
  const data = await chrome.storage.local.get({ pendingSidePanelIntent: null });
  const intent = data.pendingSidePanelIntent || null;
  if (chrome.storage.local.remove) await chrome.storage.local.remove("pendingSidePanelIntent");
  else await chrome.storage.local.set({ pendingSidePanelIntent: null });
  await runSidePanelIntent(intent);
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function hasDownloadableResources(items = resources) {
  return (items || []).some(isDownloadableResource);
}

async function waitForOneClickMediaCandidate() {
  for (let attempt = 0; attempt < ONE_CLICK_RESOURCE_WAIT_ATTEMPTS; attempt += 1) {
    if (hasDownloadableResources(resources)) return true;
    if (hasActiveVideoSignal(page?.active_video) && resources.length) return true;
    const remaining = ONE_CLICK_RESOURCE_WAIT_ATTEMPTS - attempt;
    els.taskMessage.textContent = `正在等待当前页暴露可直取视频资源...剩余 ${remaining} 次自动重检`;
    await sleep(ONE_CLICK_RESOURCE_WAIT_DELAY_MS);
    await collect();
  }
  return hasActiveVideoSignal(page?.active_video) || resources.length > 0;
}

async function runSidePanelIntent(intent) {
  if (!intent || intent.action !== "summarize-current-video") return;
  const age = Date.now() - Number(intent.createdAt || 0);
  if (!Number.isFinite(age) || age < 0 || age > PENDING_INTENT_TTL_MS) return;
  if (intent.tabId !== null && intent.tabId !== undefined && currentTabId !== null && currentTabId !== intent.tabId) return;
  const hasCandidate = await waitForOneClickMediaCandidate();
  if (!hasCandidate) {
    els.taskMessage.textContent = "已打开当前页助手；还没有读取到正在播放的视频或媒体候选，先播放几秒后再点总结。";
    return;
  }
  els.taskMessage.textContent = "已从扩展图标进入一键总结，正在预检当前播放视频...";
  await startTask("video");
}

function healthVisionReady(data) {
  return Boolean(data?.vision_model_configured || els.llmApiKey?.value?.trim());
}

function healthVisionModel(data) {
  return els.llmModel?.value?.trim() || data?.default_llm_model || "gpt-4.1-mini";
}

function healthVisionText(data) {
  const model = healthVisionModel(data);
  if (healthVisionReady(data)) {
    return `视觉模型已配置（${model}），切片网格会随字幕进入图文总结。`;
  }
  return "未配置视觉模型 API Key：仍会生成字幕、切片网格和本地图文索引；填写 Key 后才会把画面送入视觉模型。";
}

function healthVisionChipText(data) {
  const model = healthVisionModel(data);
  return healthVisionReady(data) ? `模型 · ${model}` : "API Key 待填";
}

function healthMediaChipText(data) {
  if (!data?.ffmpeg) return "ffmpeg 缺失";
  if (data.ffprobe_optional) return "后端 · ffmpeg 时长回退";
  return "后端 · 直取/切片就绪";
}

function updateHealthVisionStatus(data = lastHealthData) {
  if (!data || !els.backendStatus) return;
  const mediaText = String(els.backendStatus.dataset.mediaText || els.backendStatus.textContent || "").trim();
  const visionText = healthVisionText(data);
  els.backendStatus.dataset.mediaText = mediaText;
  els.backendStatus.title = `${mediaText} ${visionText}`.trim();
  els.backendStatus.classList.add("backend-status-grid");
  els.backendStatus.innerHTML = `
    <span class="backend-status-chip media"><b>媒体</b>${escapeHtml(healthMediaChipText(data))}</span>
    <span class="backend-status-chip vision ${healthVisionReady(data) ? "ready" : "pending"}"><b>视觉</b>${escapeHtml(healthVisionChipText(data))}</span>
  `;
}

async function health() {
  try {
    const data = await fetch(`${backendUrl}/health`).then(r => r.json());
    lastHealthData = data;
    els.backendStatus.textContent = data.ffmpeg
      ? data.ffprobe_optional ? "后端可用 · ffprobe 可选" : "本地后端可用"
      : "ffmpeg 缺失";
    els.backendStatus.style.color = data.ffmpeg ? "#159947" : "#c27803";
    updateHealthVisionStatus(data);
  } catch {
    els.backendStatus.textContent = "后端未连接";
    els.backendStatus.style.color = "#d92d20";
  }
}

function scheduleContextRefresh(reason = "media", delay = 350) {
  if (!HAS_EXTENSION_API) return;
  if (contextRefreshTimer) clearTimeout(contextRefreshTimer);
  contextRefreshTimer = setTimeout(() => {
    contextRefreshTimer = 0;
    if (!currentTaskId && reason !== "pending") {
      els.taskMessage.textContent = reason === "tab-activated"
        ? "已切换到当前标签页，正在读取播放上下文..."
        : "检测到当前页媒体变化，正在刷新候选资源...";
    }
    collect();
  }, delay);
}

function shouldAcceptContextUpdate(message = {}) {
  if (message?.type !== "current-context-updated") return false;
  if (message.reason === "tab-activated") return true;
  if (currentTabId === null || currentTabId === undefined) return true;
  if (message.tabId === null || message.tabId === undefined) return true;
  return message.tabId === currentTabId;
}

async function collectContextNow() {
  els.pageTitle.textContent = "读取中...";
  els.resources.innerHTML = `<p class="muted">正在检测媒体资源...</p>`;
  if (!HAS_EXTENSION_API) {
    page = {
      title: "普通浏览器预览",
      page_url: location.href,
      page_text: "",
      active_video: null,
      frames: []
    };
    resources = [];
    selectedResourceUrl = "";
    renderContext();
    return true;
  }
  const response = await chrome.runtime.sendMessage({ type: "get-current-context" });
  if (response.error) {
    els.resources.innerHTML = `<p class="muted">${escapeHtml(response.error)}</p>`;
    return false;
  }
  const nextTabId = response.tab?.id ?? null;
  if (currentTabId !== null && nextTabId !== null && currentTabId !== nextTabId) {
    resourceSelectionPinned = false;
  }
  currentTabId = response.tab?.id ?? null;
  page = response.page;
  resources = response.resources || [];
  if (selectedResourceUrl && !resources.some(item => item.url === selectedResourceUrl)) {
    resourceSelectionPinned = false;
  }
  selectedResourceUrl = pickDefaultResourceUrl(resources, selectedResourceUrl);
  preflight = null;
  preflightResourceUrl = "";
  preflightResultsByUrl = new Map();
  renderContext();
  return true;
}

async function collect() {
  if (isCollectingContext) {
    pendingContextRefresh = true;
    return false;
  }
  isCollectingContext = true;
  let ok = false;
  try {
    ok = await collectContextNow();
  } finally {
    isCollectingContext = false;
    if (pendingContextRefresh) {
      pendingContextRefresh = false;
      scheduleContextRefresh("pending", 150);
    }
  }
  return ok;
}

function renderContext() {
  els.pageTitle.textContent = page?.title || "Untitled";
  els.pageUrl.textContent = page?.page_url || "";
  const active = page?.active_video;
  const frames = page?.frames || [];
  if (hasActiveVideoSignal(active)) {
    const state = active.drm_detected ? "blocked" : active.paused ? "paused" : "playing";
    els.activeVideo.className = `playback-card active-video-card ${state}`;
    els.activeVideo.innerHTML = `
      <div class="active-video-top">
        <span>${active.drm_detected ? "DRM/EME" : active.paused ? "暂停" : "播放中"}</span>
        <strong>${escapeHtml(fmt(active.current_time))} / ${escapeHtml(fmt(active.duration))}</strong>
      </div>
      <div class="active-video-metrics">
        <span><b>${escapeHtml(playbackSourceLabel(active))}</b>源类型</span>
        <span><b>${escapeHtml(`${active.width || 0}x${active.height || 0}`)}</b>画面</span>
        <span><b>${escapeHtml(active.frame_id ?? "-")}</b>Frame</span>
      </div>
      <code>${escapeHtml(activeSrcObjectOnly(active) ? srcObjectText(active) : compactUrl(active.src))}</code>
    `;
  } else {
    els.activeVideo.className = `playback-card active-video-card ${frames.length ? "scanning" : "idle"}`;
    els.activeVideo.innerHTML = `
      <div class="active-video-top">
        <span>${frames.length ? "扫描中" : "等待播放"}</span>
        <strong>${frames.length ? `已扫描 ${frames.length} 个 frame` : "未读取到 HTML5 播放状态"}</strong>
      </div>
      <p>${frames.length ? "继续播放几秒后重新检测，扩展会把媒体请求和播放器 frame 对齐。" : "先播放课程视频，再重新检测当前页媒体资源。"}</p>
    `;
  }
  renderPlaybackReadiness();
  renderCurrentStudyCard();
  renderLaunchBar();
  els.resourceCount.textContent = String(resources.length);
  renderReadiness();
  renderRouteSummary();
  renderExtractionPlan();
  if (!resources.length) {
    els.resources.innerHTML = `${resourceHint()}${noResourceGuideHtml()}`;
    renderInspector();
    return;
  }
  const visibleResources = filteredResources();
  if (visibleResources.length && !visibleResources.some(item => item.url === selectedResourceUrl)) {
    selectedResourceUrl = pickDefaultResourceUrl(visibleResources, "");
  }
  const filterCopy = resourceFilterOption();
  const emptyFilterHtml = visibleResources.length ? "" : `<section class="resource-filter-empty">
    <strong>${escapeHtml(filterCopy.label)}没有匹配候选</strong>
    <small>切回“全部”查看当前页已捕获的资源，或继续播放几秒后重新检测。</small>
    <button type="button" data-resource-filter="all">查看全部</button>
  </section>`;
  els.resources.innerHTML = `${resourceHint()}${resourceAttemptQueueHtml()}${resourceFilterBarHtml()}${emptyFilterHtml}${visibleResources.map(item => `
    <button class="resource ${item.url === selectedResourceUrl ? "selected" : ""} ${isDownloadableResource(item) ? "" : "non-downloadable"} ${item.playback_match || item.is_main_video ? "playback" : ""}" data-url="${escapeHtml(item.url)}">
      <span>
        <strong>${escapeHtml(item.label || item.kind || "media")}</strong>
        ${resourcePriorityBadgeHtml(item)}
        ${candidateConfidenceHtml(item)}
        ${resourceTagHtml(item)}
        ${preflightBadgeHtml(item)}
        <small>${escapeHtml([
          isDownloadableResource(item) ? "可直取" : "线索",
          item.is_main_video ? "主视频" : "",
          playbackText(item.playback_match),
          item.kind,
          resourceSourceText(item),
          item.request_type,
          item.status_code ? `HTTP ${item.status_code}` : "",
          fmtBytes(item.content_length),
          item.frame_id !== null && item.frame_id !== undefined ? `frame ${item.frame_id}` : "",
          item.mime || "unknown"
        ].filter(Boolean).join(" · "))}</small>
        ${responseEvidenceLine(item) ? `<small class="resource-response-evidence">${escapeHtml(responseEvidenceLine(item))}</small>` : ""}
      </span>
      <span class="confidence">${item.score || 0}%</span>
    </button>
  `).join("")}`;
  document.querySelectorAll(".resource").forEach(button => {
    button.onclick = () => {
      selectedResourceUrl = button.dataset.url;
      resourceSelectionPinned = true;
      renderContext();
    };
  });
  document.querySelectorAll(".resource-attempt-row").forEach(button => {
    button.onclick = () => {
      selectedResourceUrl = button.dataset.url;
      resourceSelectionPinned = true;
      renderContext();
    };
  });
  renderInspector();
}

function selectedResources() {
  const selected = resources.find(item => item.url === selectedResourceUrl);
  const rest = resources.filter(item => item.url !== selectedResourceUrl);
  return selected ? [selected, ...rest] : resources;
}

function preflightCandidatesForStart(mode = "video") {
  if (!isMediaTaskMode(mode)) return [];
  const ordered = selectedResources().filter(item => shouldPreflightBeforeStart(mode, item));
  const seen = new Set();
  return ordered.filter(item => {
    if (!item?.url || seen.has(item.url)) return false;
    seen.add(item.url);
    return true;
  });
}

async function requestResourcePreflight(resource) {
  const response = await chrome.runtime.sendMessage({
    type: "preflight-current-resource",
    backendUrl,
    page,
    resource
  });
  if (response.error) {
    return {
      ok: false,
      downloadable: false,
      code: "preflight_failed",
      message: response.error,
      url: resource?.url || ""
    };
  }
  return response.preflight;
}

async function preflightBestResource(mode = "video") {
  const candidates = preflightCandidatesForStart(mode);
  if (!candidates.length) return null;

  const cached = currentPreflight();
  if (cached?.downloadable) return cached;

  let lastResult = null;
  els.taskMessage.textContent = candidates.length > 1
    ? `正在预检 ${candidates.length} 个直取候选...`
    : "正在预检直取候选...";

  for (const candidate of candidates) {
    const result = rememberPreflightResult(candidate, await requestResourcePreflight(candidate));
    lastResult = result;
    if (result?.downloadable) {
      selectedResourceUrl = candidate.url;
      els.taskMessage.textContent = `预检通过：已选择 ${candidate.kind || result.kind || "media"} 候选。`;
      renderContext();
      return result;
    }
  }

  if (lastResult) {
    els.taskMessage.textContent = candidates.length > 1
      ? `所有直取候选预检未通过：${preflightBlockMessage(lastResult)}`
      : preflightBlockMessage(lastResult);
    renderContext();
  }
  return lastResult;
}

async function startTask(mode = "video") {
  if (!HAS_EXTENSION_API) {
    els.taskMessage.textContent = "请在 Chrome/Edge 扩展 Side Panel 中读取当前页视频。";
    return;
  }
  els.summarizeButton.disabled = true;
  if (els.downloadOnlyButton) els.downloadOnlyButton.disabled = true;
  if (els.textButton) els.textButton.disabled = true;
  try {
    els.taskMessage.textContent = isMediaTaskMode(mode) ? "正在刷新当前播放页和媒体候选..." : "正在刷新当前页面文本...";
    const refreshed = await collect();
    if (!refreshed || !page) {
      els.taskMessage.textContent = "刷新当前页面失败，无法确认最新播放资源；请重新打开页面或刷新后再试。";
      return;
    }
    if (preflightCandidatesForStart(mode).length) {
      const checked = await preflightBestResource(mode);
      if (!checked?.downloadable) {
        if (!canAttemptBackendPageFallback(mode)) {
          els.taskMessage.textContent = preflightBlockMessage(checked);
          renderContext();
          return;
        }
        els.taskMessage.textContent = preflightFallbackStartMessage(checked);
      }
    }
    const response = await chrome.runtime.sendMessage({
      type: "start-current-task",
      backendUrl,
      page,
      resources: isMediaTaskMode(mode) ? selectedResources() : [],
      mode,
      options: readOptions()
    });
    if (response.error) {
      els.taskMessage.textContent = response.error;
      return;
    }
    currentTaskId = response.task_id;
    transcriptCache = null;
    lastNote = "";
    await loadTaskHistory();
    pollTask();
  } finally {
    els.summarizeButton.disabled = false;
    if (els.downloadOnlyButton) els.downloadOnlyButton.disabled = false;
    if (els.textButton) els.textButton.disabled = false;
  }
}

async function preflightSelectedResource({ silent = false } = {}) {
  if (!HAS_EXTENSION_API) {
    els.taskMessage.textContent = "请在 Chrome/Edge 扩展 Side Panel 中预检当前页视频。";
    return null;
  }
  const refreshed = await collect();
  if (!refreshed || !page) {
    els.taskMessage.textContent = "刷新当前页面失败，无法预检最新播放资源；请重新打开页面或刷新后再试。";
    return null;
  }
  const resource = selectedResource();
  if (!resource) {
    els.taskMessage.textContent = "没有可预检的候选资源。";
    return null;
  }
  els.preflightButton.disabled = true;
  if (!silent) els.taskMessage.textContent = "正在预检直取可行性...";
  try {
    preflight = rememberPreflightResult(resource, await requestResourcePreflight(resource));
    els.taskMessage.textContent = preflight.message || (preflight.downloadable ? "预检通过" : "预检未通过");
    renderContext();
    return preflight;
  } finally {
    els.preflightButton.disabled = false;
  }
}

async function runPreflight() {
  if (!HAS_EXTENSION_API) {
    els.taskMessage.textContent = "请在 Chrome/Edge 扩展 Side Panel 中预检当前页视频。";
    return null;
  }
  els.preflightButton.disabled = true;
  els.summarizeButton.disabled = true;
  if (els.downloadOnlyButton) els.downloadOnlyButton.disabled = true;
  try {
    els.taskMessage.textContent = "正在刷新当前播放页和媒体候选...";
    const refreshed = await collect();
    if (!refreshed || !page) {
      els.taskMessage.textContent = "刷新当前页面失败，无法预检最新播放资源；请重新打开页面或刷新后再试。";
      return null;
    }
    const candidates = preflightCandidatesForStart("video");
    if (!candidates.length) {
      els.taskMessage.textContent = "没有可预检的直取候选；继续播放几秒后重新检测，或上传本地视频。";
      return null;
    }
    return await preflightBestResource("video");
  } finally {
    els.preflightButton.disabled = false;
    els.summarizeButton.disabled = false;
    if (els.downloadOnlyButton) els.downloadOnlyButton.disabled = false;
  }
}

async function uploadLocal() {
  const file = els.fileInput.files?.[0];
  if (!file) return;
  if (!isSupportedLocalVideoFile(file)) {
    els.localDropText.textContent = "请选择 mp4 / m4v / mov / flv / avi / mkv / webm 等视频文件";
    els.taskMessage.textContent = `${file.name} 不是支持的视频格式。`;
    return;
  }
  els.localDropText.textContent = file.name;
  els.uploadButton.disabled = true;
  els.localDrop.classList.add("uploading");
  const form = new FormData();
  form.append("file", file);
  form.append("title", file.name);
  form.append("options", JSON.stringify(readOptions()));
  els.taskMessage.textContent = "上传本地视频...";
  try {
    const response = await fetch(`${backendUrl}/api/tasks/from-local`, { method: "POST", body: form });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.task_id) {
      const message = apiErrorMessage(data, "本地视频上传失败，请确认后端可用并重试。");
      els.localDropText.textContent = message;
      els.taskMessage.textContent = message;
      return;
    }
    currentTaskId = data.task_id;
    transcriptCache = null;
    lastNote = "";
    await loadTaskHistory();
    pollTask();
  } catch (error) {
    const detail = error?.message ? `本地视频上传失败：${error.message}` : "本地视频上传失败，请确认后端可用并重试。";
    els.localDropText.textContent = "上传失败，请重试";
    els.taskMessage.textContent = detail;
  } finally {
    els.uploadButton.disabled = false;
    els.localDrop.classList.remove("uploading");
  }
}

async function pollTask() {
  if (!currentTaskId) return;
  const data = await fetch(`${backendUrl}/api/tasks/${currentTaskId}`).then(r => r.json());
  currentTask = data.task;
  const index = taskHistory.findIndex(task => task.id === currentTask.id);
  if (index >= 0) taskHistory[index] = currentTask;
  else taskHistory.unshift(currentTask);
  renderTaskHistory();
  els.progressBar.style.width = `${currentTask.progress || 0}%`;
  renderStageRail(currentTask);
  els.taskPhase.textContent = currentTask.phase || "-";
  els.taskMessage.textContent = currentTask.error_detail || currentTask.message || currentTask.phase;
  if (currentTask.status === "success") {
    await loadResult();
    await loadTaskHistory();
    return;
  }
  renderResult();
  if (currentTask.status !== "failed") {
    setTimeout(pollTask, 2500);
  }
}

async function loadResult() {
  if (!currentTaskId) return;
  currentTask = await fetch(`${backendUrl}/api/tasks/${currentTaskId}`).then(r => r.json()).then(d => d.task);
  transcriptCache = null;
  lastNote = "";
  if (currentTask.transcript_path || currentTask.status === "success") {
    try {
      const response = await fetch(`${backendUrl}/api/tasks/${currentTaskId}/transcript`);
      if (response.ok !== false) transcriptCache = await response.json();
    } catch {
      transcriptCache = null;
    }
  }
  if (currentTask.note_path || currentTask.status === "success") {
    try {
      const response = await fetch(`${backendUrl}/api/tasks/${currentTaskId}/note`);
      if (response.ok !== false) lastNote = await response.text();
    } catch {
      lastNote = "";
    }
  }
  const index = taskHistory.findIndex(task => task.id === currentTask.id);
  if (index >= 0) taskHistory[index] = currentTask;
  else taskHistory.unshift(currentTask);
  renderResult();
}

function visualWindows(task) {
  if (task?.visual_windows?.length) return task.visual_windows;
  return (task?.frame_grids || []).map((grid, index) => ({
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

function segmentOverlapsWindow(segment, window) {
  const start = Number(segment.start || 0);
  const end = Number(segment.end ?? start);
  return start < Number(window.end || 0) && end >= Number(window.start || 0);
}

function transcriptLines(segments) {
  return segments.map(seg => `<div class="line"><time>${fmt(seg.start)}</time><span>${escapeHtml(seg.text)}</span></div>`).join("");
}

function transcriptOverview(transcript, task) {
  const segments = transcript?.segments || [];
  const windows = visualWindows(task);
  const first = segments[0];
  const last = segments[segments.length - 1];
  const range = first && last ? `${fmt(first.start)} - ${fmt(last.end ?? last.start)}` : "无时间轴";
  const source = transcriptSourceText(transcript?.source);
  return `<section class="transcript-overview" aria-label="字幕概览">
    <div>
      <span>字幕时间轴</span>
      <strong>${escapeHtml(source)}</strong>
      <small>${escapeHtml(windows.length ? "已按画面窗口对齐" : "独立字幕时间轴")}</small>
    </div>
    <div class="transcript-overview-metrics">
      <span><b>${segments.length}</b>段字幕</span>
      <span><b>${escapeHtml(range)}</b>时间范围</span>
      <span><b>${windows.length || "-"}</b>${windows.length ? "视觉窗口" : "无切片"}</span>
    </div>
  </section>`;
}

function taskStatusClass(task = {}) {
  if (task.status === "success") return "success";
  if (task.status === "failed") return "failed";
  if (task.status === "running" || task.status === "queued") return "running";
  return "idle";
}

function hasTaskBundle(task) {
  if (!task) return false;
  return Boolean(
    task.note_path ||
    task.media_path ||
    task.status === "failed" ||
    task.download_attempts?.length ||
    visualWindows(task).length
  );
}

function hasTaskDiagnostics(task) {
  if (!task) return false;
  return Boolean(
    task.status === "failed" ||
    task.download_attempts?.length ||
    task.selected_resource ||
    task.media_path ||
    task.summary_diagnostics_path ||
    Object.keys(task.summary_diagnostics || {}).length
  );
}

function hasVisualWindowExport(task) {
  return Boolean(task?.visual_windows?.length || task?.frame_grids?.length);
}

function canContinueFromDownloadedMedia(task = currentTask) {
  const finished = task?.status === "success" || task?.status === "failed";
  return Boolean(task?.id && finished && task.media_path && !task.note_path);
}

function updateContinueFromMediaAction(task = currentTask) {
  if (!els.continueFromMediaButton) return;
  const canContinue = canContinueFromDownloadedMedia(task);
  els.continueFromMediaButton.hidden = !canContinue;
  els.continueFromMediaButton.disabled = !canContinue;
}

function visualCoverageHtml(task) {
  const windows = visualWindows(task || {});
  const diag = task?.summary_diagnostics || {};
  const hasDiagnostics = Object.keys(diag).length > 0;
  const gridCount = Number(diag.frame_grid_count ?? task?.frame_grids?.length ?? windows.length ?? 0);
  const visionGridCount = Number(diag.vision_grid_count ?? gridCount ?? 0);
  const sentImages = Number(diag.vision_image_count ?? windows.filter(window => safeNoteMediaUrl(window.grid_url)).length ?? 0);
  const missingIds = (diag.missing_vision_image_window_ids || []).map(id => String(id || "").trim()).filter(Boolean);
  const omittedIds = (diag.omitted_vision_window_ids || []).map(id => String(id || "").trim()).filter(Boolean);
  const windowCount = Number(diag.visual_window_count ?? windows.length ?? 0);
  if (!windows.length && !hasDiagnostics && !gridCount) return "";

  const validWindows = windows
    .map((window, index) => ({
      ...window,
      id: String(window.id || `W${String(index + 1).padStart(3, "0")}`),
      start: Number(window.start || 0),
      end: Number(window.end ?? window.start ?? 0),
      frame_count: Number(window.frame_count || 0)
    }))
    .filter(window => Number.isFinite(window.start) && Number.isFinite(window.end));
  const minStart = validWindows.length ? Math.min(...validWindows.map(window => window.start)) : 0;
  const maxEnd = validWindows.length ? Math.max(...validWindows.map(window => window.end)) : 0;
  const totalDuration = Math.max(1, maxEnd - minStart);
  const shownWindows = validWindows.slice(0, 6);
  const missingSet = new Set(missingIds);
  const omittedSet = new Set(omittedIds);
  const lane = shownWindows.length
    ? `<div class="visual-coverage-lane" aria-label="视觉窗口覆盖">
      ${shownWindows.map(window => {
        const width = Math.max(12, Math.min(100, ((Math.max(1, window.end - window.start) / totalDuration) * 100)));
        const state = omittedSet.has(window.id) ? "omitted" : missingSet.has(window.id) ? "missing" : safeNoteMediaUrl(window.grid_url) ? "ready" : "pending";
        return `<span class="${escapeHtml(state)}" style="--w:${width.toFixed(2)}%" title="${escapeHtml(`${window.id} ${fmt(window.start)} - ${fmt(window.end)}`)}">
          <b>${escapeHtml(window.id)}</b><small>${escapeHtml(fmt(window.start))}</small>
        </span>`;
      }).join("")}
      ${validWindows.length > shownWindows.length ? `<em>+${validWindows.length - shownWindows.length}</em>` : ""}
    </div>`
    : `<div class="visual-coverage-empty">等待抽帧生成视觉窗口</div>`;
  const flags = [
    missingIds.length ? `缺图 ${compactIdList(missingIds)}` : "",
    omittedIds.length ? `超限省略 ${compactIdList(omittedIds)}` : "",
    diag.summary_warning || "",
    diag.used_page_text_fallback ? "已使用页面文本/浏览器字幕兜底" : ""
  ].filter(Boolean);

  return `<section class="visual-coverage" aria-label="视觉切片覆盖">
    <header>
      <span>视觉切片覆盖</span>
      <strong>${windowCount || windows.length || "-"} 个窗口</strong>
      <small>${validWindows.length ? `${fmt(minStart)} - ${fmt(maxEnd)}` : "尚无时间覆盖"}</small>
    </header>
    <div class="visual-coverage-metrics">
      <span><b>${gridCount || "-"}</b>网格</span>
      <span><b>${sentImages}/${visionGridCount || gridCount || 0}</b>送入视觉</span>
      <span><b>${missingIds.length || "-"}</b>缺图</span>
      <span><b>${omittedIds.length || "-"}</b>省略</span>
    </div>
    ${lane}
    ${flags.length ? `<p>${flags.map(escapeHtml).join(" · ")}</p>` : ""}
  </section>`;
}

function visionEvidenceBar(task) {
  if (!task) return "";
  const windows = visualWindows(task || {});
  const diag = task.summary_diagnostics || {};
  const hasDiagnostics = Object.keys(diag).length > 0;
  const gridCount = Number(diag.frame_grid_count ?? task.frame_grids?.length ?? windows.length ?? 0);
  const visionGridCount = Number(diag.vision_grid_count ?? gridCount ?? 0);
  const sentImages = Number(diag.vision_image_count ?? windows.filter(window => safeNoteMediaUrl(window.grid_url)).length ?? 0);
  const missingIds = (diag.missing_vision_image_window_ids || []).map(id => String(id || "").trim()).filter(Boolean);
  const omittedIds = (diag.omitted_vision_window_ids || []).map(id => String(id || "").trim()).filter(Boolean);
  const source = task.summary_source || diag.summary_source || (diag.used_vision_llm ? "vision-llm" : diag.used_text_llm ? "text-llm" : diag.used_local_template ? "local-template" : "");
  const visualDisabled = task.options?.visual_understanding === false || task.source_type === "page_text";
  const shouldShow = visualDisabled || hasDiagnostics || gridCount || windows.length || task.note_path || task.media_path;
  if (!shouldShow) return "";

  let state = "empty";
  if (visualDisabled) state = "skip";
  else if (source === "vision-llm" || diag.used_vision_llm) state = "strong";
  else if (sentImages > 0 || missingIds.length || omittedIds.length) state = "partial";
  else if (gridCount || windows.length) state = "index";

  const title = {
    strong: "画面已参与图文总结",
    partial: "已有画面证据，模型链路存在降级",
    index: "已生成画面切片，当前笔记未确认使用视觉模型",
    skip: "本任务走文本路线",
    empty: "还没有视觉切片证据"
  }[state];
  const badge = {
    strong: "视觉模型",
    partial: "视觉索引",
    index: "本地切片",
    skip: "文本总结",
    empty: "等待切片"
  }[state];
  const detail = {
    strong: `已把 ${sentImages}/${visionGridCount || gridCount || 0} 张网格图送入视觉模型，并和对应转写窗口合并成笔记。`,
    partial: `检测到 ${windows.length || gridCount || 0} 个视觉窗口；当前结果可能使用了文本模型、模板或存在缺图窗口。`,
    index: `已生成 ${windows.length || gridCount || 0} 个视觉窗口，可在“画面”页复核；总结来源为 ${source || "本地索引"}。`,
    skip: "页面文本或用户选项关闭了视觉理解，因此不会调用画面切片总结。",
    empty: "尚未看到抽帧、网格或视觉模型诊断；任务完成后这里会显示画面证据。"
  }[state];
  const flags = [
    missingIds.length ? `缺图 ${compactIdList(missingIds, 4)}` : "",
    omittedIds.length ? `超限省略 ${compactIdList(omittedIds, 4)}` : "",
    diag.summary_warning || "",
    diag.used_page_text_fallback ? "已使用页面文本/浏览器字幕兜底" : "",
    diag.used_local_template ? "本地模板兜底" : ""
  ].filter(Boolean);

  return `<section class="vision-evidence ${escapeHtml(state)}" aria-label="图文总结证据">
    <div class="vision-evidence-main">
      <span>${escapeHtml(badge)}</span>
      <strong>${escapeHtml(title)}</strong>
      <p>${escapeHtml(detail)}</p>
    </div>
    <div class="vision-evidence-metrics">
      <span><b>${windows.length || gridCount || "-"}</b>视觉窗口</span>
      <span><b>${sentImages}/${visionGridCount || gridCount || 0}</b>送入视觉</span>
      <span><b>${escapeHtml(source || "-")}</b>总结来源</span>
      <span><b>${missingIds.length + omittedIds.length || "-"}</b>异常窗口</span>
    </div>
    ${flags.length ? `<p class="vision-evidence-flags">${flags.map(escapeHtml).join(" · ")}</p>` : ""}
    <div class="vision-evidence-actions">
      ${windows.length ? `<button type="button" data-switch-result-tab="frames">查看切片</button>` : ""}
      ${hasTaskDiagnostics(task) ? `<button type="button" data-switch-result-tab="diagnostics">查看诊断</button>` : ""}
      ${hasTaskBundle(task) ? `<button type="button" data-export="bundle">导出资料包</button>` : ""}
    </div>
  </section>`;
}

function auditGateState(task, passed) {
  if (passed) return "pass";
  if (task?.status === "failed") return "fail";
  if (task?.status === "success") return "warn";
  return "wait";
}

function pipelineAuditItems(task) {
  const selected = task?.selected_resource || {};
  const attempts = task?.download_attempts || [];
  const windows = visualWindows(task || {});
  const diag = task?.summary_diagnostics || {};
  const isLocal = task?.source_type === "local";
  const isPageText = task?.source_type === "page_text" || Boolean(diag.used_page_text_fallback);
  const hasSelectedRoute = Boolean(selected.url || selected.kind || isLocal || isPageText);
  const hasMedia = Boolean(task?.media_path);
  const hasTranscript = Boolean(task?.transcript_path);
  const hasVisuals = Boolean(windows.length || task?.frame_grids?.length || Number(diag.frame_grid_count || 0));
  const hasNote = Boolean(task?.note_path);
  const visualDisabled = task?.options?.visual_understanding === false || isPageText;

  return [
    {
      label: "来源门",
      state: auditGateState(task, hasSelectedRoute || attempts.length || hasMedia || hasNote),
      value: hasSelectedRoute ? (resourceSourceText(selected) || taskSourceText(task)) : task?.error_code || "待捕获",
      detail: hasSelectedRoute
        ? [selected.kind || task?.source_type, selected.playback_match ? playbackText(selected.playback_match) : "", selected.resolved_url ? "最终 URL" : ""].filter(Boolean).join(" · ")
        : (attempts.length ? `${attempts.length} 次候选尝试` : "等待当前页候选")
    },
    {
      label: "媒体门",
      state: isPageText ? "skip" : auditGateState(task, hasMedia),
      value: isPageText ? "文本路线" : hasMedia ? "media.mp4" : task?.error_code || "待下载",
      detail: hasMedia ? "已落盘，可导出/复用" : (attempts.length ? `${attempts.length} 次下载尝试` : "等待直连、yt-dlp 或 ffmpeg")
    },
    {
      label: "转写门",
      state: isPageText && hasNote ? "pass" : auditGateState(task, hasTranscript),
      value: hasTranscript ? "字幕已生成" : isPageText && hasNote ? "页面文本/浏览器字幕" : task?.phase === "transcribing" ? "转写中" : "待转写",
      detail: hasTranscript ? "可切到转写页核对" : (isPageText ? `${diag.browser_subtitle_count ?? 0} 条字幕 · ${diag.combined_text_char_count ?? 0} 字` : `字幕优先，${asrOptionText(task?.options || {})} 兜底`)
    },
    {
      label: "切片门",
      state: visualDisabled ? "skip" : auditGateState(task, hasVisuals),
      value: visualDisabled ? "未启用" : hasVisuals ? `${windows.length || diag.frame_grid_count || task?.frame_grids?.length} 窗口` : task?.phase === "extracting_frames" ? "抽帧中" : "待切片",
      detail: visualDisabled
        ? "当前任务不走视觉"
        : hasVisuals
          ? `${diag.vision_image_count ?? windows.filter(window => safeNoteMediaUrl(window.grid_url)).length}/${diag.vision_grid_count ?? (windows.length || 0)} 送入视觉`
          : "等待画面网格"
    },
    {
      label: "总结门",
      state: auditGateState(task, hasNote),
      value: hasNote ? (task?.summary_source || "笔记完成") : task?.phase === "summarizing" ? "总结中" : task?.error_code || "待总结",
      detail: hasNote ? (task?.summary_warning || `${task?.options?.note_style || "study"} · ${task?.options?.summary_depth || "standard"}`) : "等待字幕和切片"
    }
  ];
}

function pipelineAuditHtml(task) {
  const items = pipelineAuditItems(task);
  return `<section class="pipeline-audit" aria-label="阶段审计门">
    <header>
      <span>阶段审计门</span>
      <strong>${items.filter(item => item.state === "pass" || item.state === "skip").length}/${items.length} 已放行</strong>
    </header>
    <div class="pipeline-audit-grid">
      ${items.map(item => `<article class="${escapeHtml(item.state)}">
        <b>${escapeHtml(item.label)}</b>
        <strong>${escapeHtml(item.value || "-")}</strong>
        <small>${escapeHtml(item.detail || "-")}</small>
      </article>`).join("")}
    </div>
  </section>`;
}

function nextStepHtml(task) {
  if (!task) return "";
  const windows = visualWindows(task);
  const hasNote = Boolean(task.note_path);
  const hasMedia = Boolean(task.media_path);
  const hasTranscript = Boolean(task.transcript_path);
  const hasVisuals = Boolean(windows.length || task.frame_grids?.length || Number(task.summary_diagnostics?.frame_grid_count || 0));
  const failed = task.status === "failed";
  let tone = "active";
  let title = "继续处理";
  let detail = "等待任务进入下一阶段。";
  let actions = [];

  if (canContinueFromDownloadedMedia(task)) {
    tone = "ready";
    title = "继续生成完整笔记";
    detail = "视频已经下载到本地，可以复用 media.mp4 继续转写、切片和图文总结。";
    actions = [
      `<button type="button" data-rerun-from-media="${escapeHtml(task.id)}">生成完整笔记</button>`,
      `<button type="button" data-switch-result-tab="diagnostics">看下载证据</button>`
    ];
  } else if (failed && !hasNote) {
    tone = "blocked";
    title = "直取链路需要处理";
    detail = task.error_detail || task.error_code || "当前任务失败；先看诊断确认是登录、DRM、签名过期还是资源不完整。";
    actions = [
      `<button type="button" data-switch-result-tab="diagnostics">查看诊断</button>`,
      `<button type="button" data-recovery-local>改用本地视频</button>`
    ];
  } else if (hasNote) {
    tone = "ready";
    title = "阅读并核对笔记";
    detail = hasVisuals
      ? "笔记、字幕和画面切片已经形成，可以按时间轴回看关键画面。"
      : "笔记已生成；如果缺少画面证据，请查看诊断确认视觉理解是否关闭或降级。";
    actions = [
      `<button type="button" data-switch-result-tab="note">阅读笔记</button>`,
      hasVisuals ? `<button type="button" data-switch-result-tab="frames">核对画面</button>` : `<button type="button" data-switch-result-tab="diagnostics">查看诊断</button>`
    ];
  } else if (hasMedia && !hasTranscript) {
    title = "等待转写字幕";
    detail = "媒体已落盘，下一步会优先使用平台/内嵌字幕，没有字幕时再进入 ASR。";
    actions = [`<button type="button" data-switch-result-tab="diagnostics">看处理状态</button>`];
  } else if (hasTranscript && !hasVisuals && task.options?.visual_understanding !== false) {
    title = "等待画面切片";
    detail = "字幕已经生成，下一步应抽帧、拼网格并按视觉窗口对齐字幕。";
    actions = [
      `<button type="button" data-switch-result-tab="transcript">核对字幕</button>`,
      `<button type="button" data-switch-result-tab="diagnostics">查看诊断</button>`
    ];
  } else {
    title = "等待图文总结";
    detail = "任务会按下载、转写、切片、总结顺序推进；阶段门会显示当前卡点。";
    actions = [`<button type="button" data-switch-result-tab="diagnostics">查看阶段门</button>`];
  }

  return `<section class="next-step-card ${escapeHtml(tone)}" aria-label="下一步">
    <div>
      <span>下一步</span>
      <strong>${escapeHtml(title)}</strong>
      <small>${escapeHtml(detail)}</small>
    </div>
    <div class="next-step-actions">${actions.filter(Boolean).join("")}</div>
  </section>`;
}

function mediaPreviewHtml(task) {
  const url = taskMediaPreviewUrl(task);
  if (!url) return "";
  const title = task.title || task.id || "media";
  return `<section class="media-preview-card" aria-label="本地视频核对">
    <div class="media-preview-copy">
      <span>本地视频核对</span>
      <strong>${escapeHtml(title)}</strong>
      <small>${escapeHtml(task.media_path || "")}</small>
    </div>
    <video controls preload="metadata" src="${escapeHtml(url)}"></video>
    <div class="media-preview-actions">
      <button type="button" data-export="media">导出 media.mp4</button>
      ${canContinueFromDownloadedMedia(task) ? `<button type="button" data-rerun-from-media="${escapeHtml(task.id)}">继续切片总结</button>` : ""}
    </div>
  </section>`;
}

function taskOverview(task) {
  const selected = task.selected_resource || {};
  const options = task.options || {};
  const windows = visualWindows(task);
  const hasNote = Boolean(task.note_path);
  const hasMedia = Boolean(task.media_path);
  const hasBundle = hasTaskBundle(task);
  const statusClass = taskStatusClass(task);
  const fallbackNote = task.status === "failed" && hasNote;
  const canContinueMedia = canContinueFromDownloadedMedia(task);
  const resourceLine = [
    taskSourceText(task),
    selected.kind || task.source_type || "",
    selected.playback_match ? playbackText(selected.playback_match) : "",
    selected.resolved_url ? "已跟踪最终 URL" : "",
    selected.content_length ? fmtBytes(selected.content_length) : ""
  ].filter(Boolean).join(" · ");
  const actionLinks = [
    `<button type="button" data-open-workbench="${escapeHtml(task.id)}">Web 工作台</button>`,
    hasNote ? `<button type="button" data-export="markdown">Markdown</button>` : "",
    hasMedia ? `<button type="button" data-export="media">本地视频</button>` : "",
    hasTaskDiagnostics(task) ? `<button type="button" data-export="diagnostics">诊断</button>` : "",
    hasBundle ? `<button type="button" data-export="bundle">资料包</button>` : ""
  ].filter(Boolean).join("");
  const downloadOnly = hasMedia && !hasNote && task.status === "success";
  const failed = task.status === "failed";

  return `<section class="task-overview status-${statusClass}">
    <div class="task-overview-main">
      <span>当前学习任务</span>
      <strong>${escapeHtml(task.title || task.id)}</strong>
      <small>${escapeHtml(resourceLine || taskStatusText(task))}</small>
      <div class="stage-rail inline">${PIPELINE_STEPS.map(step => `<span class="${stepState(task, step)}">${step.label}</span>`).join("")}</div>
    </div>
    <div class="task-overview-actions">
      ${canContinueMedia ? `<button type="button" data-rerun-from-media="${escapeHtml(task.id)}">生成完整笔记</button>` : ""}
      ${actionLinks || `<span>${escapeHtml(taskStatusText(task))}</span>`}
    </div>
    <div class="task-overview-metrics">
      <span><b>${escapeHtml(taskStatusText(task))}</b>${escapeHtml(task.phase || "-")} · ${task.progress || 0}%</span>
      <span><b>${escapeHtml(options.frame_interval || "-")} 秒切片</b>${escapeHtml(options.grid_columns && options.grid_rows ? `${options.grid_columns}x${options.grid_rows} 视觉窗口` : "未配置视觉窗口")}</span>
      <span><b>${escapeHtml(task.summary_source || asrOptionText(options))}</b>${escapeHtml(task.summary_warning ? "已降级" : `${options.note_style || "study"} · ${options.visual_understanding === false ? "无视觉" : "图文"}`)}</span>
      <span><b>${windows.length || "-"}</b>${windows.length ? "画面窗口" : "等待切片"}</span>
    </div>
    ${pipelineAuditHtml(task)}
    ${nextStepHtml(task)}
    ${mediaPreviewHtml(task)}
    ${visualCoverageHtml(task)}
    ${taskRouteEvidenceHtml(task)}
    ${downloadOnly ? `<div class="task-overview-callout">
      <strong>已完成直取下载</strong>
      <span>这个任务按“下载本地”运行，未进入转写、切片和总结；可导出 media.mp4，或直接复用这个本地视频生成完整笔记。</span>
    </div>` : ""}
    ${fallbackNote ? `<div class="task-overview-callout">
      <strong>已生成兜底笔记</strong>
      <span>视频直取失败，但已用页面文本/浏览器字幕生成可读笔记；诊断页仍保留原始下载错误和资源证据。</span>
    </div>` : ""}
    ${failed ? `<div class="task-overview-callout failed">
      <strong>${escapeHtml(task.error_code || "任务失败")}</strong>
      <span>${escapeHtml(task.error_detail || "请查看诊断页里的下载尝试和资源证据。")}</span>
    </div>` : ""}
  </section>`;
}

function lastDownloadAttempt(task) {
  const attempts = task?.download_attempts || [];
  return attempts.length ? attempts[attempts.length - 1] : null;
}

function taskRouteEvidenceItems(task) {
  const selected = task?.selected_resource || {};
  const attempts = task?.download_attempts || [];
  const lastAttempt = lastDownloadAttempt(task);
  const headers = requestHeaderNames(selected);
  const diag = task?.summary_diagnostics || {};
  const summaryText = summaryDiagnosticText(task);
  const summaryValue = task.summary_source || (diag.used_page_text_fallback ? "页面文本兜底" : task.note_path ? "已有笔记" : "待生成");
  const summaryDetail = summaryText === "-"
    ? (task.summary_warning || (task.note_path ? "未记录总结诊断" : "等待图文总结"))
    : summaryText;
  return [
    {
      label: "直取来源",
      value: selected.kind ? `${selected.kind} · ${resourceSourceText(selected) || selected.source || "候选资源"}` : taskSourceText(task),
      detail: selected.playback_match ? playbackText(selected.playback_match) : (selected.label || "页面/本地任务")
    },
    {
      label: "下载路线",
      value: attempts.length ? `${attempts.length} 次尝试` : task.media_path ? "已有本地媒体" : "等待下载",
      detail: lastAttempt ? `${lastAttempt.strategy || "-"} · ${lastAttempt.code || lastAttempt.status || "-"}` : (task.error_code || task.phase || "-")
    },
    {
      label: "浏览器证据",
      value: headers !== "-" ? headers : selected.status_code ? `HTTP ${selected.status_code}` : "无可复用请求头",
      detail: [
        selected.mime || "",
        selected.content_length ? fmtBytes(selected.content_length) : "",
        selected.request_type || ""
      ].filter(Boolean).join(" · ") || "Cookie 仅任务启动时同步"
    },
    {
      label: "总结证据",
      value: summaryValue,
      detail: summaryDetail
    }
  ].filter(item => item.value || item.detail);
}

function taskRouteEvidenceHtml(task) {
  const items = taskRouteEvidenceItems(task);
  if (!items.length) return "";
  return `<div class="task-route-evidence" aria-label="直取和总结证据">
    ${items.map(item => `<span>
      <b>${escapeHtml(item.label)}</b>
      <strong>${escapeHtml(item.value || "-")}</strong>
      <small>${escapeHtml(item.detail || "-")}</small>
    </span>`).join("")}
  </div>`;
}

async function openTaskExport(type) {
  if (!currentTaskId) return;
  const url = `${backendUrl}/api/tasks/${encodeURIComponent(currentTaskId)}/exports/${type}`;
  if (HAS_EXTENSION_API) {
    try {
      const response = await chrome.runtime.sendMessage({ type: "download-task-export", url });
      if (response?.ok) {
        els.taskMessage.textContent = type === "media" ? "已开始下载本地视频。" : "已开始下载导出文件。";
        return;
      }
      if (response?.error) els.taskMessage.textContent = `${response.error} 已改为打开导出链接。`;
    } catch (error) {
      els.taskMessage.textContent = `${error?.message || "导出下载失败"} 已改为打开导出链接。`;
    }
    chrome.tabs.create({ url });
    return;
  }
  window.open(url, "_blank", "noopener");
}

async function rerunTaskFromMedia(taskId) {
  if (!taskId) return;
  els.taskMessage.textContent = "正在复用已下载视频，并按当前切片、ASR 和视觉模型参数创建完整笔记任务...";
  const response = await fetch(`${backendUrl}/api/tasks/${encodeURIComponent(taskId)}/rerun-from-media`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(readOptions())
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    els.taskMessage.textContent = detail?.detail?.message || detail?.detail || "无法复用已下载视频。";
    return;
  }
  const data = await response.json();
  currentTaskId = data.task_id;
  transcriptCache = null;
  lastNote = "";
  selectedTab = "note";
  els.resultTabs.forEach(item => item.classList.toggle("active", item.dataset.tab === selectedTab));
  await loadTaskHistory();
  pollTask();
}

function bindTaskOverviewActions() {
  document.querySelectorAll("button[data-open-workbench]").forEach(button => {
    button.onclick = () => openWorkbench(button.dataset.openWorkbench, selectedTab);
  });
  document.querySelectorAll("button[data-export]").forEach(button => {
    button.onclick = () => openTaskExport(button.dataset.export);
  });
  document.querySelectorAll("button[data-rerun-from-media]").forEach(button => {
    button.onclick = () => rerunTaskFromMedia(button.dataset.rerunFromMedia);
  });
  document.querySelectorAll("button[data-switch-result-tab]").forEach(button => {
    button.onclick = () => switchResultTab(button.dataset.switchResultTab);
  });
  document.querySelectorAll("button[data-recovery-local]").forEach(button => {
    button.onclick = () => els.fileInput.click();
  });
}

function resetResultScroll() {
  if (els.result) els.result.scrollTop = 0;
}

function switchResultTab(tabName) {
  if (!tabName || selectedTab === tabName) return;
  selectedTab = tabName;
  els.resultTabs.forEach(item => item.classList.toggle("active", item.dataset.tab === selectedTab));
  renderResult();
  resetResultScroll();
}

function noteHeadingStats(markdown) {
  if (!markdown) return { total: 0, h1: 0, h2: 0, h3: 0 };
  const stats = { total: 0, h1: 0, h2: 0, h3: 0 };
  let inFence = false;
  String(markdown || "").replace(/\r\n?/g, "\n").split("\n").forEach(rawLine => {
    const line = rawLine.trimEnd();
    if (line.startsWith("```")) {
      inFence = !inFence;
      return;
    }
    if (inFence) return;
    const match = /^(#{1,3})\s+(.+)$/.exec(line);
    if (!match) return;
    stats.total += 1;
    stats[`h${match[1].length}`] += 1;
  });
  return stats;
}

function noteStudyMap(markdown, task) {
  const headings = noteHeadingStats(markdown);
  const windows = visualWindows(task);
  const hasNote = Boolean(task.note_path);
  const hasTranscript = Boolean(task.transcript_path);
  const hasMedia = Boolean(task.media_path);
  const hasBundle = hasTaskBundle(task);
  const firstWindow = windows[0];
  const lastWindow = windows[windows.length - 1];
  const visualRange = windows.length && firstWindow && lastWindow
    ? `${fmt(firstWindow.start)} - ${fmt(lastWindow.end)}`
    : "等待切片";
  const cards = [
    {
      label: "笔记目录",
      value: headings.total ? `${headings.total} 个标题` : hasNote ? "无标题" : "未生成",
      text: headings.h2 ? `${headings.h2} 个章节 · ${headings.h3} 个小节` : "生成后自动提取目录",
      action: hasNote ? `<button type="button" data-switch-result-tab="note">阅读笔记</button>` : ""
    },
    {
      label: "画面切片",
      value: windows.length ? `${windows.length} 个窗口` : "未生成",
      text: visualRange,
      action: windows.length ? `<button type="button" data-switch-result-tab="frames">查看画面</button>` : ""
    },
    {
      label: "转写字幕",
      value: hasTranscript ? "已对齐" : "未生成",
      text: task.summary_warning ? "有降级提示，建议看诊断" : asrOptionText(task.options || {}),
      action: hasTranscript ? `<button type="button" data-switch-result-tab="transcript">看字幕</button>` : ""
    },
    {
      label: "本地产物",
      value: [hasMedia ? "视频" : "", hasBundle ? "资料包" : ""].filter(Boolean).join(" · ") || "等待产物",
      text: hasMedia ? "可复用 media.mp4 继续处理" : "任务完成后可导出",
      action: hasBundle ? `<button type="button" data-export="bundle">导出资料包</button>` : ""
    }
  ];
  return `<section class="study-map" aria-label="学习笔记导览">
    <div class="study-map-head">
      <div>
        <span>学习导览</span>
        <strong>${escapeHtml(task.title || task.id)}</strong>
      </div>
      <small>${escapeHtml(taskSourceText(task))} · ${escapeHtml(taskStatusText(task))}</small>
    </div>
    <div class="study-map-grid">
      ${cards.map(card => `<div class="study-map-card">
        <span>${escapeHtml(card.label)}</span>
        <strong>${escapeHtml(card.value)}</strong>
        <small>${escapeHtml(card.text)}</small>
        ${card.action ? `<div class="study-map-action">${card.action}</div>` : ""}
      </div>`).join("")}
    </div>
  </section>`;
}

function noteVisualRail(task, limit = 4) {
  const windows = visualWindows(task).filter(window => window.grid_url).slice(0, limit);
  if (!windows.length) return "";
  return `<section class="note-visual-rail" aria-label="画面索引">
    <div class="note-outline-head">
      <strong>画面索引</strong>
      <span>${visualWindows(task).length} 个窗口</span>
    </div>
    <div class="note-visual-list">
      ${windows.map(window => `
        <figure>
          <img src="${escapeHtml(window.grid_url)}" alt="${escapeHtml(window.id)} frame grid">
          <figcaption>
            <strong>${escapeHtml(window.id)}</strong>
            <span>${fmt(window.start)} - ${fmt(window.end)} · ${window.frame_count || 0} 帧</span>
            ${window.transcript_excerpt ? `<small>${escapeHtml(window.transcript_excerpt)}</small>` : ""}
          </figcaption>
        </figure>
      `).join("")}
    </div>
  </section>`;
}

function transcriptTimeline(transcript, task, limit = 100) {
  const segments = (transcript?.segments || []).slice(0, limit);
  const windows = visualWindows(task);
  if (!windows.length) {
    return `${transcriptOverview(transcript, task)}<div class="transcript-timeline transcript-timeline-plain">${transcriptLines(segments)}</div>`;
  }

  const used = new Set();
  const cards = windows.slice(0, 8).map(window => {
    const matched = segments.filter((segment, index) => {
      if (!segmentOverlapsWindow(segment, window)) return false;
      used.add(index);
      return true;
    });
    const body = matched.length
      ? transcriptLines(matched)
      : window.transcript_excerpt
        ? `<p>${escapeHtml(window.transcript_excerpt)}</p>`
        : `<p class="muted">这个画面窗口没有匹配到字幕段落。</p>`;
    return `<section class="transcript-window">
      <figure>
        ${window.grid_url ? `<img src="${escapeHtml(window.grid_url)}" alt="${escapeHtml(window.id)} frame grid">` : ""}
        <figcaption>
          <strong>${escapeHtml(window.id)}</strong>
          <span>${fmt(window.start)} - ${fmt(window.end)} · ${window.frame_count || 0} 帧</span>
        </figcaption>
      </figure>
      <div class="transcript-window-lines">${body}</div>
    </section>`;
  });

  const unmatched = segments.filter((_, index) => !used.has(index));
  if (unmatched.length) {
    cards.push(`<section class="transcript-window transcript-window-orphan">
      <figure>
        <figcaption>
          <strong>未归入切片</strong>
          <span>${unmatched.length} 段字幕</span>
        </figcaption>
      </figure>
      <div class="transcript-window-lines">${transcriptLines(unmatched)}</div>
    </section>`);
  }

  return `${transcriptOverview(transcript, task)}<div class="transcript-timeline">${cards.join("")}</div>`;
}

function visualStudyDeck(task) {
  const windows = visualWindows(task);
  if (!windows.length) return "";
  const firstWindow = windows[0];
  const lastWindow = windows[windows.length - 1];
  const range = firstWindow && lastWindow ? `${fmt(firstWindow.start)} - ${fmt(lastWindow.end)}` : "等待切片";
  return `<section class="side-visual-study" aria-label="视觉窗口复习">
    <div class="side-visual-study-head">
      <div>
        <span>视觉窗口复习</span>
        <strong>${escapeHtml(task.title || task.id || "画面切片")}</strong>
      </div>
      <div class="side-visual-study-head-actions">
        <small>${escapeHtml(`${windows.length} 窗口 · ${range}`)}</small>
        <button type="button" data-export="visual-windows">导出切片索引</button>
      </div>
    </div>
    <div class="side-visual-study-list">
      ${windows.slice(0, 8).map((window, index) => {
        const image = safeNoteMediaUrl(window.grid_url || "");
        const excerpt = window.transcript_excerpt || "暂无字幕摘录，可切到“转写”查看完整时间轴。";
        return `<article class="side-visual-study-card">
          <figure>
            ${image ? `<img src="${image}" alt="${escapeHtml(window.id)} frame grid">` : `<div class="side-visual-placeholder">无画面</div>`}
            <figcaption>${escapeHtml(window.id || `W${String(index + 1).padStart(3, "0")}`)}</figcaption>
          </figure>
          <div>
            <span>窗口 ${String(index + 1).padStart(2, "0")}</span>
            <strong>${fmt(window.start)} - ${fmt(window.end)}</strong>
            <p>${escapeHtml(excerpt)}</p>
            ${sideVisualStudyCheckpointHtml(window)}
            ${sideVisualStudyChecklistHtml(window)}
            <div class="side-visual-meta">
              <em>${Number(window.frame_count || 0)} 帧</em>
              ${frameTimestampText(window) ? `<em>${escapeHtml(frameTimestampText(window))}</em>` : ""}
              <em>${escapeHtml(task.options?.grid_columns && task.options?.grid_rows ? `${task.options.grid_columns}x${task.options.grid_rows}` : "网格")}</em>
              <em>${escapeHtml(task.summary_source || "本地索引")}</em>
            </div>
            <div class="side-visual-actions">
              <button type="button" data-switch-result-tab="transcript">看转写</button>
              <button type="button" data-switch-result-tab="note">回笔记</button>
            </div>
          </div>
        </article>`;
      }).join("")}
    </div>
  </section>`;
}

function sideVisualStudyCheckpointHtml(window) {
  const excerpt = String(window.transcript_excerpt || "").replace(/\s+/g, " ").trim();
  const item = excerpt
    ? `<li><time>${fmt(window.start || 0)}</time><span>${escapeHtml(excerpt.length > 96 ? `${excerpt.slice(0, 96).trim()}...` : excerpt)}；对照画面确认对应的板书、PPT、代码或操作步骤。</span></li>`
    : `<li><span>无同步字幕；先描述画面网格中的标题、公式、代码或界面状态，再回看原视频确认上下文。</span></li>`;
  return `<div class="side-visual-study-checkpoints">
    <span>回看检查点</span>
    <ol>${item}</ol>
  </div>`;
}

function sideVisualStudyChecklistHtml(window) {
  const hasCue = Boolean(window.transcript_excerpt);
  const target = hasCue
    ? "核对截图里的板书、PPT 切换、代码/界面状态是否已被字幕覆盖。"
    : "先从截图判断本段主题，重点看标题、公式、代码和演示状态。";
  const action = hasCue
    ? "复述这一窗口的结论，再按画面顺序补齐遗漏步骤。"
    : "补一句本段主题，再和前后窗口串成完整时间线。";
  return `<div class="side-visual-study-checklist">
    <span>学习动作</span>
    <ul>
      <li>${escapeHtml(target)}</li>
      <li>${escapeHtml(action)}</li>
    </ul>
  </div>`;
}

function renderResult() {
  const hasNote = Boolean(currentTaskId) && Boolean(currentTask?.note_path);
  els.copyButton.disabled = !hasNote;
  els.bundleButton.disabled = !hasTaskBundle(currentTask);
  els.diagnosticsButton.disabled = !hasTaskDiagnostics(currentTask);
  if (els.visualWindowsButton) els.visualWindowsButton.disabled = !hasVisualWindowExport(currentTask);
  els.mediaButton.disabled = !currentTask?.media_path;
  els.downloadButton.disabled = !hasNote;
  updateContinueFromMediaAction(currentTask);
  if (!currentTask) {
    els.result.textContent = "任务完成后显示结果。";
    return;
  }
  if (selectedTab === "note") {
    els.result.className = "result-body";
    const noteHtml = lastNote
      ? markdownToHtml(lastNote)
      : currentTask.media_path
        ? `<p>视频已下载到本地。可点击右上角视频按钮导出，不会继续转写、切片或总结。</p>`
        : `<p>${escapeHtml(currentTask.message || "笔记尚未生成。")}</p>`;
    els.result.innerHTML = `${taskOverview(currentTask)}${visionEvidenceBar(currentTask)}${noteStudyMap(lastNote, currentTask)}${noteOutline(lastNote)}${noteVisualRail(currentTask)}<article class="markdown-note">${noteHtml}</article>`;
    bindTaskOverviewActions();
    return;
  }
  if (selectedTab === "frames") {
    const windows = visualWindows(currentTask);
    if (!windows.length) {
      els.result.className = "result-body muted";
      els.result.textContent = "画面切片尚未生成。";
      return;
    }
    els.result.className = "result-body";
    els.result.innerHTML = `${visionEvidenceBar(currentTask)}${visualStudyDeck(currentTask)}`;
    bindTaskOverviewActions();
    return;
  }
  if (selectedTab === "diagnostics") {
    const selected = currentTask.selected_resource || {};
    const attempts = currentTask.download_attempts || [];
    const attemptHtml = attempts.length ? `
      <div class="attempt-list">
        ${attempts.map(attempt => `
          <div class="attempt ${attempt.status}">
            <strong>${escapeHtml(attempt.strategy)} · ${escapeHtml(attempt.status)}</strong>
            <small>${escapeHtml([
              attempt.code,
              attempt.status_code ? `HTTP ${attempt.status_code}` : "",
              fmtBytes(attempt.bytes_downloaded || attempt.content_length),
              attempt.kind,
              attempt.source
            ].filter(Boolean).join(" · "))}</small>
            <span>${escapeHtml(attempt.message || attempt.url || "-")}</span>
          </div>
        `).join("")}
      </div>
    ` : "暂无下载尝试记录";
    els.result.className = "result-body";
    els.result.innerHTML = `
      ${diagnosticRecoveryHtml(currentTask)}
      <dl class="diagnostics">
        <dt>状态</dt><dd>${escapeHtml(currentTask.status)} / ${escapeHtml(currentTask.phase)} / ${currentTask.progress || 0}%</dd>
        <dt>策略</dt><dd>${selected.url ? "浏览器候选资源优先" : "页面解析 fallback"}</dd>
        <dt>播放器快照</dt><dd>${escapeHtml(activeVideoText(currentTask.active_video))}</dd>
        <dt>DRM/EME</dt><dd>${escapeHtml(currentTask.drm_detected ? (drmSignalText(currentTask.drm_signals || []) || "已检测到") : "-")}</dd>
        <dt>资源</dt><dd>${escapeHtml(selected.url || "未选择直接资源")}</dd>
        <dt>播放 blob</dt><dd>${escapeHtml(selected.blob_url || "-")}</dd>
        <dt>所在 frame</dt><dd>${escapeHtml(selected.frame_url || "-")}</dd>
        <dt>类型</dt><dd>${escapeHtml([
          selected.kind || "-",
          selected.source || "-",
          selected.is_main_video ? "主视频" : "",
          playbackText(selected.playback_match),
          selected.status_code ? `HTTP ${selected.status_code}` : "",
          fmtBytes(selected.content_length)
        ].filter(Boolean).join(" · "))}</dd>
        <dt>请求头</dt><dd>${escapeHtml(requestHeaderNames(selected))}</dd>
        <dt>请求 body</dt><dd>${escapeHtml(requestBodySummary(selected) || "-")}</dd>
        <dt>转写引擎</dt><dd>${escapeHtml(asrOptionText(currentTask.options || {}))}</dd>
        <dt>转写来源</dt><dd>${escapeHtml(transcriptCache?.source ? transcriptSourceText(transcriptCache.source) : "-")}</dd>
        <dt>总结来源</dt><dd>${escapeHtml(currentTask.summary_source || "-")}</dd>
        <dt>图文总结诊断</dt><dd>${escapeHtml(summaryDiagnosticText(currentTask))}</dd>
        <dt>总结提示</dt><dd>${escapeHtml(currentTask.summary_warning || "-")}</dd>
        <dt>错误</dt><dd>${escapeHtml(currentTask.error_detail || currentTask.error_code || "-")}</dd>
        <dt>字幕</dt><dd>${escapeHtml(currentTask.subtitle_path || "-")}</dd>
        <dt>尝试记录</dt><dd>${attemptHtml}</dd>
      </dl>
    `;
    return;
  }
  const transcript = transcriptCache;
  if (!transcript?.segments?.length) {
    els.result.className = "result-body muted";
    els.result.textContent = transcript?.warning || "转写尚未生成。";
    return;
  }
  els.result.className = "result-body";
  els.result.innerHTML = transcriptTimeline(transcript, currentTask, 100);
}

els.resultTabs.forEach(tab => {
  tab.onclick = () => switchResultTab(tab.dataset.tab);
});

els.redetectButton.onclick = collect;
els.summarizeButton.onclick = () => startTask("video");
els.preflightButton.onclick = runPreflight;
if (els.downloadOnlyButton) els.downloadOnlyButton.onclick = () => startTask("download_only");
if (els.continueFromMediaButton) els.continueFromMediaButton.onclick = () => rerunTaskFromMedia(currentTask?.id);
els.textButton.onclick = () => startTask("page_text");
if (els.refreshHistoryButton) els.refreshHistoryButton.onclick = loadTaskHistory;
if (els.transcriber) els.transcriber.onchange = () => syncTranscriberModelDefault(true);
els.uploadButton.onclick = () => els.fileInput.click();
els.fileInput.onchange = uploadLocal;
els.localDrop.onclick = () => els.fileInput.click();
els.localDrop.addEventListener("dragover", event => {
  event.preventDefault();
  els.localDrop.classList.add("drag");
});
els.localDrop.addEventListener("dragleave", () => els.localDrop.classList.remove("drag"));
els.localDrop.addEventListener("drop", event => {
  event.preventDefault();
  els.localDrop.classList.remove("drag");
  if (event.dataTransfer.files?.[0]) {
    els.fileInput.files = event.dataTransfer.files;
    els.localDropText.textContent = event.dataTransfer.files[0].name;
    uploadLocal();
  }
});
els.resourceInspector.addEventListener("click", event => {
  if (event.target.closest("[data-copy-resource-url]")) {
    copySelectedResourceUrl();
    return;
  }
  if (event.target.closest("[data-copy-resource-report]")) {
    copySelectedResourceReport();
  }
});
els.resources.addEventListener("click", event => {
  const filterButton = event.target.closest("[data-resource-filter]");
  if (filterButton) {
    resourceFilter = filterButton.dataset.resourceFilter || "all";
    const visible = filteredResources();
    if (visible.length && !visible.some(item => item.url === selectedResourceUrl)) {
      selectedResourceUrl = pickDefaultResourceUrl(visible, "");
    }
    renderContext();
    return;
  }
  const button = event.target.closest("[data-resource-empty-action]");
  if (!button) return;
  const action = button.dataset.resourceEmptyAction;
  if (action === "redetect") {
    collect();
  } else if (action === "local") {
    els.fileInput.click();
  } else if (action === "text") {
    startTask("page_text");
  }
});
function handleRouteAction(action) {
  if (action === "redetect") {
    collect();
  } else if (action === "preflight") {
    preflightSelectedResource();
  } else if (action === "summarize") {
    startTask("video");
  } else if (action === "download") {
    startTask("download_only");
  } else if (action === "local") {
    els.fileInput.click();
  } else if (action === "text") {
    startTask("page_text");
  }
}
document.querySelectorAll("[data-source-action]").forEach(button => {
  button.addEventListener("click", () => handleRouteAction(button.dataset.sourceAction));
});
els.routeSummary.addEventListener("click", event => {
  const button = event.target.closest("[data-route-action]");
  if (!button) return;
  handleRouteAction(button.dataset.routeAction);
});
if (els.launchBar) {
  els.launchBar.addEventListener("click", event => {
    const button = event.target.closest("[data-route-action]");
    if (!button) return;
    handleRouteAction(button.dataset.routeAction);
  });
}
els.copyButton.onclick = () => navigator.clipboard.writeText(lastNote || "");
els.bundleButton.onclick = () => {
  openTaskExport("bundle");
};
els.diagnosticsButton.onclick = () => {
  openTaskExport("diagnostics");
};
if (els.visualWindowsButton) {
  els.visualWindowsButton.onclick = () => {
    openTaskExport("visual-windows");
  };
}
els.mediaButton.onclick = () => {
  openTaskExport("media");
};
els.downloadButton.onclick = () => {
  openTaskExport("markdown");
};
els.openWebButton.onclick = () => {
  openWorkbench();
};
els.settingsButton.onclick = saveSettings;
els.llmModel?.addEventListener("input", () => updateHealthVisionStatus());
els.llmApiKey?.addEventListener("input", () => updateHealthVisionStatus());

if (HAS_EXTENSION_API && chrome.runtime.onMessage?.addListener) {
  chrome.runtime.onMessage.addListener(message => {
    if (shouldAcceptContextUpdate(message)) {
      scheduleContextRefresh(message.reason || "media");
      return;
    }
    if (message?.type === "sidepanel-action-intent") {
      (async () => {
        await collect();
        await runSidePanelIntent(message.intent);
      })();
    }
  });
}

loadSettings().then(async () => {
  await Promise.all([health(), collect(), loadTaskHistory()]);
  await consumePendingSidePanelIntent();
});
