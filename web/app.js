const DEFAULT_BACKEND_ORIGIN = "http://127.0.0.1:8765";

function normalizeApiBase(value) {
  const text = String(value || "").trim().replace(/\/+$/, "");
  return /^https?:\/\/(?:localhost|127\.0\.0\.1)(?::\d+)?$/i.test(text) ? text : "";
}

function isBackendSameOrigin(loc = window?.location || location) {
  const protocol = String(loc?.protocol || "");
  const hostname = String(loc?.hostname || "");
  const port = String(loc?.port || "");
  return (protocol === "http:" || protocol === "https:")
    && (hostname === "localhost" || hostname === "127.0.0.1")
    && (!port || port === "8765");
}

function resolveApiBase(loc = window?.location || location, storage = window?.localStorage) {
  const explicit = normalizeApiBase(currentUrlParam(["api", "backend", "backend_url"]));
  if (explicit) return explicit;
  const saved = normalizeApiBase(storage?.getItem?.("learnnote_api_base"));
  if (saved) return saved;
  return isBackendSameOrigin(loc) ? "" : DEFAULT_BACKEND_ORIGIN;
}

function apiUrl(path) {
  return `${API}${path}`;
}

let API = resolveApiBase();
const MEDIA_RE = /\.(mp4|m4v|webm|mov|mkv|flv|avi)(\?|#|$)/i;
const HLS_RE = /\.(m3u8|mpd)(\?|#|$)/i;
const LOCAL_VIDEO_EXT_RE = /\.(mp4|m4v|mov|mkv|webm|flv|avi)$/i;
const RESULT_TAB_NAMES = new Set(["note", "transcript", "slices", "frames", "diagnostics"]);
const LOCAL_ASR_MODELS = new Set(["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"]);
const MODEL_SETTINGS_STORAGE_KEY = "learnnote_model_settings";
const MODEL_PROVIDER_PRESETS = {
  openai: {
    baseUrl: "https://api.openai.com/v1",
    model: "gpt-4.1-mini",
    transcriber: "openai-compatible",
    whisperModel: "whisper-1"
  },
  groq: {
    baseUrl: "https://api.groq.com/openai/v1",
    model: "meta-llama/llama-4-scout-17b-16e-instruct",
    transcriber: "groq",
    whisperModel: "whisper-large-v3"
  },
  gemini: {
    baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai/",
    model: "gemini-3.5-flash",
    transcriber: "faster-whisper",
    whisperModel: "small"
  },
  dashscope: {
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    model: "qwen-vl-max",
    transcriber: "faster-whisper",
    whisperModel: "small"
  },
  siliconflow: {
    baseUrl: "https://api.siliconflow.cn/v1",
    model: "Qwen/Qwen2.5-VL-72B-Instruct",
    transcriber: "faster-whisper",
    whisperModel: "small"
  },
  openrouter: {
    baseUrl: "https://openrouter.ai/api/v1",
    model: "openai/gpt-4.1-mini",
    transcriber: "faster-whisper",
    whisperModel: "small"
  },
  "local-openai": {
    baseUrl: "http://127.0.0.1:11434/v1",
    model: "qwen2.5vl:7b",
    transcriber: "faster-whisper",
    whisperModel: "small"
  }
};

let selectedSource = "browser";
let selectedTaskId = taskIdFromCurrentUrl();
let selectedTab = resultTabFromCurrentUrl();
let lastNote = "";
let lastNoteTaskId = "";
let lastTranscript = null;
let lastTranscriptTaskId = "";
let tasks = [];
let taskQuery = "";
let taskStatusFilter = "all";
let urlPreflightResourceUrl = "";
let urlPreflightResult = null;
let lastHealthData = null;
let pendingLocalFile = null;
let pendingRerunNotice = null;

const els = {
  health: document.querySelector("#health"),
  refreshButton: document.querySelector("#refreshButton"),
  toggleWorkspaceButton: document.querySelector("#toggleWorkspaceButton"),
  toggleHistoryButton: document.querySelector("#toggleHistoryButton"),
  readingModeButton: document.querySelector("#readingModeButton"),
  sourceTabs: document.querySelectorAll(".source-tab"),
  panes: document.querySelectorAll(".source-pane"),
  urlInput: document.querySelector("#urlInput"),
  urlMode: document.querySelector("#urlMode"),
  urlModeHint: document.querySelector("#urlModeHint"),
  urlPreflightReport: document.querySelector("#urlPreflightReport"),
  optionsDisclosure: document.querySelector("#optionsDisclosure"),
  titleInput: document.querySelector("#titleInput"),
  startUrlButton: document.querySelector("#startUrlButton"),
  preflightUrlButton: document.querySelector("#preflightUrlButton"),
  downloadUrlButton: document.querySelector("#downloadUrlButton"),
  copyBackendButton: document.querySelector("#copyBackendButton"),
  browserRefreshButton: document.querySelector("#browserRefreshButton"),
  browserBridgeStatus: document.querySelector("#browserBridgeStatus"),
  browserRouteSummary: document.querySelector("#browserRouteSummary"),
  sourceWorkflow: document.querySelector("#sourceWorkflow"),
  fileInput: document.querySelector("#fileInput"),
  fileName: document.querySelector("#fileName"),
  dropzone: document.querySelector("#dropzone"),
  uploadButton: document.querySelector("#uploadButton"),
  taskSearch: document.querySelector("#taskSearch"),
  statusFilter: document.querySelector("#statusFilter"),
  frameInterval: document.querySelector("#frameInterval"),
  gridSize: document.querySelector("#gridSize"),
  visualUnderstanding: document.querySelector("#visualUnderstanding"),
  transcriber: document.querySelector("#transcriber"),
  whisperModel: document.querySelector("#whisperModel"),
  noteStyle: document.querySelector("#noteStyle"),
  noteTemplate: document.querySelector("#noteTemplate"),
  summaryDepth: document.querySelector("#summaryDepth"),
  llmProvider: document.querySelector("#llmProvider"),
  llmModel: document.querySelector("#llmModel"),
  llmBaseUrl: document.querySelector("#llmBaseUrl"),
  llmApiKey: document.querySelector("#llmApiKey"),
  taskCount: document.querySelector("#taskCount"),
  successCount: document.querySelector("#successCount"),
  runningCount: document.querySelector("#runningCount"),
  failedCount: document.querySelector("#failedCount"),
  tasks: document.querySelector("#tasks"),
  selectedSource: document.querySelector("#selectedSource"),
  selectedTitle: document.querySelector("#selectedTitle"),
  resultMeta: document.querySelector("#resultMeta"),
  resultTabs: document.querySelectorAll(".result-tab"),
  detail: document.querySelector("#detail"),
  continueFromMediaButton: document.querySelector("#continueFromMediaButton"),
  copyButton: document.querySelector("#copyButton"),
  bundleButton: document.querySelector("#bundleButton"),
  diagnosticsButton: document.querySelector("#diagnosticsButton"),
  visualWindowsButton: document.querySelector("#visualWindowsButton"),
  manifestButton: document.querySelector("#manifestButton"),
  mediaButton: document.querySelector("#mediaButton"),
  downloadButton: document.querySelector("#downloadButton")
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[ch]));
}

function compactUrl(value, limit = 88) {
  const text = String(value || "").trim();
  if (!text || text.length <= limit) return text;
  const head = Math.max(24, Math.floor(limit * 0.42));
  const tail = Math.max(24, limit - head - 3);
  return `${text.slice(0, head)}...${text.slice(-tail)}`;
}

function isUnreadableTitle(value) {
  const text = String(value || "").trim();
  if (!text) return true;
  const compact = text.replace(/\s+/g, "");
  if (!compact) return true;
  if (/^[?？\uFFFD]+$/.test(compact)) return true;
  if (compact.length >= 4) {
    const suspectCount = (compact.match(/[?？\uFFFD]/g) || []).length;
    if (suspectCount / compact.length >= 0.65) return true;
  }
  return false;
}

function hostFromUrl(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  try {
    const parsed = new URL(text);
    return parsed.hostname || "";
  } catch {
    const match = /^https?:\/\/([^/?#]+)/i.exec(text);
    return match ? match[1] : "";
  }
}

function displayTaskTitle(task, fallback = "未命名任务") {
  const raw = String(task?.title || "").trim();
  if (!isUnreadableTitle(raw)) return raw;
  const selected = task?.selected_resource || {};
  const kind = mediaKindText(selected.kind) || selected.kind || (task?.media_path ? "media.mp4" : "");
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
    || candidates.find(task => task.status === "success" && (task.media_path || visualWindows(task).length))
    || candidates.find(task => task.status === "success")
    || candidates.find(task => task.status === "queued")
    || candidates.find(task => task.status === "failed" && task.note_path)
    || candidates[0]
    || null;
}

function taskStudyRank(task, currentTaskId = selectedTaskId) {
  if (!task) return 90;
  if (task.id && task.id === currentTaskId) return 0;
  if (task.status === "running") return 1;
  if (task.status === "success" && task.note_path) return 2;
  if (task.status === "success" && (task.media_path || visualWindows(task).length)) return 3;
  if (task.status === "success") return 4;
  if (task.status === "queued") return 5;
  if (task.status === "failed" && task.note_path) return 6;
  if (task.status === "failed") return 7;
  return 8;
}

function sortedVisibleTasks(list, currentTaskId = selectedTaskId) {
  return (Array.isArray(list) ? list : [])
    .map((task, index) => ({ task, index }))
    .sort((a, b) => taskStudyRank(a.task, currentTaskId) - taskStudyRank(b.task, currentTaskId) || a.index - b.index)
    .map(item => item.task);
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers?.get?.("content-type") || "";
  if (response.ok === false) {
    const message = contentType.includes("application/json")
      ? JSON.stringify(await response.json().catch(() => ({})))
      : (typeof response.text === "function" ? await response.text().catch(() => "") : "");
    throw new Error(message || `HTTP ${response.status}`);
  }
  if (contentType && !contentType.includes("application/json")) {
    throw new Error(`Expected JSON from ${url}`);
  }
  const payload = await response.json();
  if (String(url).endsWith("/health")) {
    lastHealthData = payload;
  }
  return payload;
}

function currentUrlSearchText() {
  const href = String(window?.location?.href || location?.href || "");
  const explicitSearch = String(window?.location?.search || location?.search || "");
  return explicitSearch || (href.includes("?") ? href.slice(href.indexOf("?")) : "");
}

function currentUrlParam(names) {
  const search = currentUrlSearchText();
  const pattern = new RegExp(`[?&](?:${names.join("|")})=([^&#]+)`);
  const match = pattern.exec(search);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1].replace(/\+/g, " ")).trim() || null;
  } catch {
    return match[1].trim() || null;
  }
}

function taskIdFromCurrentUrl() {
  return currentUrlParam(["task", "task_id"]);
}

function resultTabFromCurrentUrl() {
  const tab = currentUrlParam(["tab", "result_tab"]);
  return normalizeResultTabName(tab);
}

function normalizeResultTabName(tabName) {
  const tab = String(tabName || "").trim();
  return RESULT_TAB_NAMES.has(tab) ? tab : "note";
}

function syncSelectedTaskUrl(taskId) {
  if (!taskId || !window?.history?.replaceState) return;
  const path = window.location?.pathname || "/";
  const hash = window.location?.hash || "";
  if (typeof URLSearchParams === "undefined") {
    window.history.replaceState(null, "", `${path}?task=${encodeURIComponent(taskId)}&tab=${encodeURIComponent(selectedTab)}${hash}`);
    return;
  }
  const params = new URLSearchParams(String(window.location?.search || ""));
  params.set("task", taskId);
  params.set("tab", selectedTab);
  window.history.replaceState(null, "", `${path}?${params.toString()}${hash}`);
}

function selectTask(taskId, { clearCaches = true, syncUrl = true } = {}) {
  if (!taskId) return;
  const changed = selectedTaskId !== taskId;
  selectedTaskId = taskId;
  if (changed && clearCaches) clearTaskCaches();
  if (syncUrl) syncSelectedTaskUrl(taskId);
}

function safeNoteMediaUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  if (/^(https?:\/\/|\/)/i.test(raw)) return escapeHtml(raw);
  return "";
}

function safeExternalUrl(value) {
  const raw = String(value || "").trim();
  return /^https?:\/\//i.test(raw) ? raw : "";
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

function noteOutline(markdown, limit = 12) {
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
  return `<section class="note-outline" aria-label="笔记目录">
    <div class="visual-rail-head">
      <strong>笔记目录</strong>
      <span>${headings.length} 节</span>
    </div>
    <div class="note-outline-list">
      ${headings.slice(0, limit).map(heading => `
        <a class="level-${heading.level}" href="#${escapeHtml(heading.id)}">${escapeHtml(heading.text)}</a>
      `).join("")}
    </div>
  </section>`;
}

function fmt(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  return `${String(Math.floor(sec / 3600)).padStart(2, "0")}:${String(Math.floor((sec % 3600) / 60)).padStart(2, "0")}:${String(sec % 60).padStart(2, "0")}`;
}

function seekTimeValue(seconds) {
  const value = Math.max(0, Number(seconds || 0));
  return Number.isFinite(value) ? value.toFixed(3) : "0.000";
}

function seekTimeButton(seconds, className = "time-seek") {
  return `<button type="button" class="${escapeHtml(className)}" data-media-seek-time="${seekTimeValue(seconds)}" title="跳到 ${escapeHtml(fmt(seconds))}"><time>${escapeHtml(fmt(seconds))}</time></button>`;
}

function seekLearningVideo(seconds, sourceElement = null) {
  const value = Math.max(0, Number(seconds || 0));
  if (!Number.isFinite(value)) return false;
  const video = document.querySelector("[data-learning-video]");
  if (!video) return false;
  video.currentTime = value;
  video.scrollIntoView?.({ behavior: "smooth", block: "center" });
  const playResult = video.play?.();
  if (playResult?.catch) playResult.catch(() => {});
  document.querySelectorAll(".media-seek-active").forEach(node => node.classList.remove("media-seek-active"));
  sourceElement?.classList?.add("media-seek-active");
  video.classList?.add("media-seek-active");
  setTimeout(() => video.classList?.remove("media-seek-active"), 1400);
  return true;
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

function requestBodySummary(resource) {
  const body = resource?.request_body || {};
  const content = String(body.content || "");
  if (!content) return "";
  const method = String(resource.method || "POST").toUpperCase();
  const type = String(body.type || "body");
  if (content === "<redacted>") return `${method} ${type} body 已捕获`;
  return `${method} ${type} body ${fmtBytes(content.length) || `${content.length} B`}`;
}

function mseAppendEvidence(resource) {
  if (!resource?.mse_append_count && !resource?.mse_append_magic && !resource?.mse_append_total_bytes) return "";
  return [
    resource.mse_append_count ? `MSE append ${resource.mse_append_count}x` : "MSE append",
    resource.mse_append_magic || "",
    fmtBytes(resource.mse_append_total_bytes),
    resource.mse_append_mime || "",
    resource.mse_append_detected_kind ? `detected ${resource.mse_append_detected_kind}` : ""
  ].filter(Boolean).join(" ");
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
    diag.llm_provider ? `Provider ${diag.llm_provider}` : "",
    diag.llm_base_host ? `Base ${diag.llm_base_host}` : "",
    diag.llm_failure_code ? `LLM 失败 ${diag.llm_failure_stage || "unknown"}/${diag.llm_failure_code}` : "",
    diag.llm_failure_reason ? `原因 ${diag.llm_failure_reason}` : "",
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

function currentPageTasks() {
  return tasks.filter(task => task.source_type === "current_page");
}

function latestCurrentPageTask() {
  return currentPageTasks()[0] || null;
}

function currentPageDisplayRank(task) {
  if (!task) return 90;
  if (task.status === "running") return 0;
  if (task.status === "queued") return 1;
  if (task.status === "success" && task.media_path && task.note_path) return 2;
  if (task.status === "success" && task.media_path) return 3;
  if (task.status === "success") return 4;
  if (task.status === "failed" && task.note_path) return 5;
  if (task.status === "failed") return 6;
  return 7;
}

function currentPageDisplayTask(list, { includeManual = false } = {}) {
  const candidates = (Array.isArray(list) ? list : [])
    .filter(task => task?.source_type === "current_page")
    .filter(task => includeManual || !isManualUrlTask(task));
  if (!candidates.length && !includeManual) {
    return currentPageDisplayTask(list, { includeManual: true });
  }
  return candidates
    .map((task, index) => ({ task, index }))
    .sort((a, b) => currentPageDisplayRank(a.task) - currentPageDisplayRank(b.task) || a.index - b.index)[0]?.task || null;
}

function preferredCurrentPageTask() {
  return currentPageDisplayTask(currentPageTasks());
}

function directRouteState(task) {
  if (!task) return "empty";
  if (task.status === "running" || task.status === "queued") return "running";
  if (task.status === "success" && task.media_path && task.note_path) return "ready";
  if (task.status === "success" && task.media_path) return "downloaded";
  if (task.status === "failed") {
    return ["drm_or_encrypted", "no_media_found", "unsupported_manifest"].includes(task.error_code) ? "blocked" : "failed";
  }
  return "empty";
}

function directRouteCopy(task) {
  const state = directRouteState(task);
  const selected = task?.selected_resource || {};
  const attempts = task?.download_attempts || [];
  if (state === "ready") {
    return {
      badge: "可复习",
      title: "最近当前页直取已生成笔记",
      detail: `${selected.kind || "media"} · ${attempts.length || 0} 次下载尝试 · ${visualWindows(task).length || 0} 个视觉窗口`,
      hint: "在右侧结果区查看笔记、字幕、画面切片和下载诊断。"
    };
  }
  if (state === "downloaded") {
    return {
      badge: "已下载",
      title: "视频已直取到本地",
      detail: `${selected.kind || "media"} · 可导出 media.mp4`,
      hint: "选择该任务后点击“继续切片总结”，复用已下载视频生成完整笔记。"
    };
  }
  if (state === "running") {
    return {
      badge: "处理中",
      title: task.status === "queued" ? "当前页任务排队中" : "当前页任务正在处理",
      detail: `${task.phase || "running"} · ${task.progress || 0}%`,
      hint: "后端会按下载、转写、切片、图文总结顺序更新进度。"
    };
  }
  if (state === "blocked") {
    return {
      badge: "不可直取",
      title: task.error_code === "drm_or_encrypted" ? "最近任务遇到 DRM/不可还原媒体" : "最近任务没有拿到可下载视频",
      detail: task.error_detail || task.message || task.error_code || "无法直接下载",
      hint: "不会录制或绕过 DRM。继续播放后重检，或切到本地视频入口上传文件。"
    };
  }
  if (state === "failed") {
    return {
      badge: "需重试",
      title: "最近当前页任务下载失败",
      detail: task.error_detail || task.message || task.error_code || "下载失败",
      hint: "常见原因是登录态、Referer、签名过期；回到原页面播放几秒后重新预检。"
    };
  }
  return {
    badge: "等待",
    title: "等待扩展侧栏创建当前页任务",
    detail: "在课程页打开 Chrome/Edge Side Panel，先预检候选，再开始总结。",
    hint: "只直取浏览器暴露的 mp4/FLV/AVI/m3u8/mpd 或 yt-dlp 可解析页面，不做标签页录制。"
  };
}

function browserRouteMetrics(task) {
  const selected = task?.selected_resource || {};
  const attempts = task?.download_attempts || [];
  return [
    { label: "最近资源", value: selected.kind || "-" },
    { label: "视觉窗口", value: task ? String(visualWindows(task).length || 0) : "-" },
    { label: "下载尝试", value: task ? String(attempts.length || 0) : "-" },
    { label: "状态", value: task ? statusText(task) : "等待" }
  ];
}

function browserRouteHandoffItems(task) {
  const selected = task?.selected_resource || {};
  const attempts = task?.download_attempts || [];
  const windows = task ? visualWindows(task) : [];
  return [
    {
      state: selected.url ? "done" : "pending",
      label: "资源证据",
      value: selected.kind || (task ? "未锁定" : "等待侧栏"),
      detail: selected.url
        ? (resourceSourceText(selected) || selected.source || "浏览器候选")
        : "播放几秒后由扩展读取播放器和媒体请求"
    },
    {
      state: task?.media_path ? "done" : attempts.length ? "active" : "pending",
      label: "本地落地",
      value: task?.media_path ? "media.mp4" : attempts.length ? `${attempts.length} 次尝试` : "未下载",
      detail: task?.media_path ? "已可导出或继续切片总结" : "直接文件、ffmpeg 或 yt-dlp 路线"
    },
    {
      state: windows.length ? "done" : task?.frame_grids?.length ? "active" : "pending",
      label: "画面切片",
      value: windows.length ? `${windows.length} 窗口` : task?.frame_grids?.length ? `${task.frame_grids.length} 网格` : "待生成",
      detail: "按字幕时间和抽帧网格对齐"
    },
    {
      state: task?.note_path ? "done" : canContinueFromDownloadedMedia(task) ? "active" : "pending",
      label: "学习笔记",
      value: task?.note_path ? "已完成" : canContinueFromDownloadedMedia(task) ? "可继续" : "待总结",
      detail: task?.note_path ? "可导出 Markdown/资料包" : "复用本地视频生成完整笔记"
    }
  ];
}

function browserRouteHandoffHtml(task) {
  return `<div class="browser-route-handoff" aria-label="当前页直取交接清单">
    ${browserRouteHandoffItems(task).map(item => `<section class="${escapeHtml(item.state)}">
      <span>${escapeHtml(item.label)}</span>
      <strong>${escapeHtml(item.value)}</strong>
      <small>${escapeHtml(item.detail)}</small>
    </section>`).join("")}
  </div>`;
}

function browserBridgeGateItems(task) {
  const hasCurrentPageTask = task?.source_type === "current_page";
  const hasBrowserEvidence = Boolean(task?.selected_resource?.url || task?.active_video || task?.download_attempts?.length);
  const hasProcessedMedia = Boolean(task?.media_path || task?.note_path);
  return [
    {
      state: hasCurrentPageTask ? "done" : "active",
      label: "扩展侧栏",
      value: hasCurrentPageTask ? "已交接" : "必须从课程页打开",
      detail: hasCurrentPageTask
        ? "任务由 Chrome/Edge Side Panel 创建，保留浏览器上下文。"
        : "Web 工作台不能直接读取你正在播放的 Chrome 标签页。"
    },
    {
      state: hasBrowserEvidence ? "done" : hasCurrentPageTask ? "active" : "pending",
      label: "播放证据",
      value: hasBrowserEvidence ? "已记录" : "等待侧栏读取",
      detail: hasBrowserEvidence
        ? "已保存候选资源、播放器快照或下载尝试。"
        : "侧栏会读取 DOM、Performance、webRequest、字幕和一次性 cookie。"
    },
    {
      state: hasProcessedMedia ? "done" : task ? "active" : "pending",
      label: "本地管线",
      value: hasProcessedMedia ? "已保存" : "等待任务",
      detail: hasProcessedMedia
        ? "可以继续查看笔记、切片、审计或导出资料。"
        : "拿到可访问媒体后才进入下载、转写、抽帧和总结。"
    }
  ];
}

function browserBridgeGateHtml(task) {
  return `<div class="browser-bridge-gate" aria-label="扩展侧栏交接门">
    <header>
      <span>扩展侧栏交接门</span>
      <strong>读取当前播放页只能从 Chrome/Edge 扩展发起</strong>
    </header>
    <div>
      ${browserBridgeGateItems(task).map(item => `<section class="${escapeHtml(item.state)}">
        <span>${escapeHtml(item.label)}</span>
        <strong>${escapeHtml(item.value)}</strong>
        <small>${escapeHtml(item.detail)}</small>
      </section>`).join("")}
    </div>
  </div>`;
}

function browserRouteActions(task) {
  const state = directRouteState(task);
  const actions = [];
  if (task?.id) {
    actions.push(`<button type="button" data-select-browser-task="${escapeHtml(task.id)}">查看任务</button>`);
  }
  if (task?.id && canContinueFromDownloadedMedia(task)) {
    actions.push(`<button type="button" data-rerun-browser-task="${escapeHtml(task.id)}">继续切片总结</button>`);
  }
  if (task?.media_path) {
    actions.push(`<a href="${escapeHtml(taskExportUrl(task, "media"))}">导出本地视频</a>`);
  }
  if (hasTaskAudit(task)) {
    actions.push(`<a href="${escapeHtml(taskExportUrl(task, "audit"))}">下载审计</a>`);
  }
  if (hasTaskDiagnostics(task)) {
    actions.push(`<a href="${escapeHtml(taskExportUrl(task, "diagnostics"))}">下载诊断</a>`);
  }
  actions.push(`<button type="button" data-browser-route-action="refresh">刷新任务</button>`);
  actions.push(`<button type="button" data-browser-route-action="copy-backend">复制后端地址</button>`);
  if (!task?.id || state === "blocked" || state === "failed" || state === "empty") {
    actions.push(`<button type="button" data-browser-route-action="local-video">本地视频兜底</button>`);
  }
  return `<div class="browser-route-actions">${actions.join("")}</div>`;
}

function browserRouteSummaryHtml(task = null) {
  const state = directRouteState(task);
  const copy = directRouteCopy(task);
  return `<section class="browser-route-summary-card ${escapeHtml(state)}">
    <div class="browser-route-summary-main">
      <span>${escapeHtml(copy.badge)}</span>
      <strong>${escapeHtml(copy.title)}</strong>
      <small>${escapeHtml(copy.hint)}</small>
    </div>
    <p>${escapeHtml(copy.detail)}</p>
    <div class="browser-route-summary-metrics">
      ${browserRouteMetrics(task).map(item => `<span><b>${escapeHtml(item.value)}</b>${escapeHtml(item.label)}</span>`).join("")}
    </div>
    ${browserBridgeGateHtml(task)}
    ${browserRouteHandoffHtml(task)}
    ${browserRouteActions(task)}
  </section>`;
}

function browserRouteEmptyHandoffHtml() {
  const steps = [
    ["1", "打开正在播放的视频页", "先让课程视频真实播放几秒，暴露浏览器请求。"],
    ["2", "点扩展侧栏总结当前视频", "由 Chrome/Edge Side Panel 读取候选、字幕和一次性 Cookie。"],
    ["3", "回到工作台看切片笔记", "下载成功后生成 media.mp4、转写、视觉窗口和 Markdown。"]
  ];
  return `<section class="browser-route-summary-card handoff empty">
    <div class="browser-route-summary-main">
      <span>交接</span>
      <strong>当前页直取需要从扩展侧栏开始</strong>
      <small>Web 工作台不能直接读取你正在播放的浏览器标签页；这里负责查看任务、切片和笔记。</small>
    </div>
    <p>不做标签页录制、不刷课、不绕过 DRM；如果课程页没有暴露可访问媒体 URL，就切到本地视频上传。</p>
    <div class="browser-route-empty-steps" aria-label="扩展侧栏交接步骤">
      ${steps.map(([index, title, detail]) => `<section>
        <b>${escapeHtml(index)}</b>
        <strong>${escapeHtml(title)}</strong>
        <small>${escapeHtml(detail)}</small>
      </section>`).join("")}
    </div>
    ${browserBridgeGateHtml(null)}
    ${browserRouteActions(null)}
  </section>`;
}

function renderBrowserRouteSummary() {
  if (!els.browserRouteSummary) return;
  const task = preferredCurrentPageTask();
  els.browserRouteSummary.innerHTML = task ? browserRouteSummaryHtml(task) : browserRouteEmptyHandoffHtml();
}

function isManualUrlTask(task) {
  const selected = task?.selected_resource || {};
  return task?.source_type === "current_page"
    && (selected.source === "manual" || String(selected.request_type || "").startsWith("manual"));
}

function workflowTaskForSource(source) {
  if (source === "local") return tasks.find(task => task.source_type === "local") || null;
  if (source === "url") return tasks.find(isManualUrlTask) || null;
  return preferredCurrentPageTask() || latestCurrentPageTask();
}

function workflowSourceConfig(source, task = null) {
  if (source === "local") {
    return {
      eyebrow: "本地视频",
      title: task ? "本地视频正在走完整切片链路" : "拖入本地视频，走同一套图文总结",
      hint: task ? statusText(task) : "适合 DRM、不可还原 blob 或学习平台不暴露媒体 URL 的课程。",
      steps: [
        ["导入文件", "mp4 / flv / avi / mkv / webm"],
        ["提取音频", "字幕优先，所选 ASR 兜底"],
        ["抽帧切片", "按视觉窗口生成网格"],
        ["整理笔记", "Markdown + 资料包"]
      ]
    };
  }
  if (source === "url") {
    return {
      eyebrow: "链接解析",
      title: task ? "链接任务已进入处理队列" : "粘贴网页或媒体链接，先预检再处理",
      hint: task ? statusText(task) : "无后缀播放接口可以手动指定视频直连、HLS 或 DASH。",
      steps: [
        ["粘贴链接", "页面 / 直连 / manifest"],
        ["预检类型", "检查 MIME、大小和策略"],
        ["下载合并", "yt-dlp 或 ffmpeg"],
        ["图文笔记", "字幕 + 切片总结"]
      ]
    };
  }
  const routeCopy = directRouteCopy(task);
  return {
    eyebrow: "当前页直取",
    title: routeCopy.title,
    hint: routeCopy.hint,
    steps: [
      ["读取当前页", "播放器、请求、Cookie"],
      ["预检资源", "mp4 / FLV / HLS / DASH"],
      ["切片识别", "字幕和画面网格"],
      ["生成笔记", "时间轴、复习题、资料包"]
    ]
  };
}

function workflowActiveIndex(task) {
  if (!task) return -1;
  if (task.status === "success") return 4;
  if (task.status === "failed") {
    if (task.note_path) return 4;
    if (task.transcript_path || task.visual_windows?.length || task.frame_grids?.length) return 3;
    if (task.media_path) return 2;
    return 1;
  }
  const phase = task.phase || "queued";
  if (["queued", "detecting"].includes(phase)) return 0;
  if (phase === "downloading") return 1;
  if (["processing_video", "transcribing", "extracting_frames"].includes(phase)) return 2;
  if (phase === "summarizing") return 3;
  if (phase === "completed") return 4;
  return 0;
}

function workflowStepState(task, index) {
  if (!task) return "pending";
  const activeIndex = workflowActiveIndex(task);
  if (task.status === "failed") {
    if (index < activeIndex) return "done";
    if (index === activeIndex) return "blocked";
    return "pending";
  }
  if (task.status === "success" || activeIndex >= 4) return "done";
  if (index < activeIndex) return "done";
  if (index === activeIndex) return "active";
  return "pending";
}

function sourceRouteInsightItems(source, task = null) {
  const selected = task?.selected_resource || {};
  const attempts = task?.download_attempts || [];
  const windows = task ? visualWindows(task) : [];
  if (source === "local") {
    return [
      ["视频入口", "本地文件直进管线", task?.media_path ? "已生成标准 media.mp4" : "拖拽上传后保存在 D 盘 data/uploads"],
      ["理解方式", "字幕优先，所选 ASR 兜底", "同样抽帧切片并送入视觉窗口"],
      ["适用场景", "平台不暴露 URL 时兜底", "DRM、不可还原 blob、过期签名都可改走本地"]
    ];
  }
  if (source === "url") {
    return [
      ["解析顺序", "直连优先，页面解析兜底", "手动指定 video/HLS/DASH 可减少误判"],
      ["下载方式", "yt-dlp / ffmpeg / 直接下载", task ? `${attempts.length || 0} 次下载尝试` : "预检通过后再进入任务"],
      ["输出产物", "media.mp4 + 图文笔记", windows.length ? `${windows.length} 个视觉窗口` : "生成后可导出资料包"]
    ];
  }
  return [
    ["浏览器证据", selected.url ? (resourceSourceText(selected) || selected.source || "候选资源") : "Side Panel 嗅探候选", selected.kind ? `${selected.kind} · ${selected.playback_match ? playbackText(selected.playback_match) : "待预检"}` : "播放器、请求、字幕、Cookie 一次性交接"],
    ["直取边界", "只下载可访问媒体", "不录制、不刷课、不绕过 DRM"],
    ["学习产物", "转写 + 切片 + 视觉总结", windows.length ? `${windows.length} 个视觉窗口` : task ? statusText(task) : "预检后生成完整笔记"]
  ];
}

function sourceRouteInsightsHtml(source, task = null) {
  return `<div class="source-route-insights" aria-label="路线产物">
    ${sourceRouteInsightItems(source, task).map(([label, title, detail]) => `<section>
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(title)}</strong>
      <small>${escapeHtml(detail)}</small>
    </section>`).join("")}
  </div>`;
}

function sourceWorkflowBriefItems(source, task = null) {
  const selected = task?.selected_resource || {};
  const routeLabel = source === "local" ? "本地视频" : source === "url" ? "链接解析" : "当前页直取";
  const routeDetail = source === "browser"
    ? selected.url
      ? `${selected.kind || "media"} · ${resourceSourceText(selected) || selected.source || "浏览器候选"}`
      : "从扩展侧栏读取播放器、请求和字幕"
    : source === "local"
      ? "拖拽或选择视频后直接进入同一套切片管线"
      : "粘贴页面、直连视频或 manifest，先预检再处理";
  const nextStep = task
    ? canContinueFromDownloadedMedia(task)
      ? "继续切片总结"
      : task.status === "failed"
        ? "查看诊断或切本地兜底"
        : task.status === "success"
          ? "查看笔记和资料包"
          : statusText(task)
    : source === "local"
      ? "选择文件"
      : source === "url"
        ? "预检链接"
        : "打开扩展侧栏总结当前页";
  const visualDetail = visualUnderstandingEnabled()
    ? `${visualPlanText()}，与字幕片段对齐`
    : "视觉理解关闭，仅生成转写笔记";
  return [
    ["入口", routeLabel, routeDetail],
    ["下一步", nextStep, task ? `${task.phase || task.status || "任务"} · ${task.progress || 0}%` : "先完成入口动作"],
    ["切片", visualUnderstandingEnabled() ? "图文窗口" : "纯文本", visualDetail],
    ["边界", source === "browser" ? "非录制直取" : source === "local" ? "离线兜底" : "可预检链接", source === "browser" ? "只下载已暴露且可访问的媒体，不刷课、不绕过 DRM" : "输出与当前页任务一致：media、转写、切片、Markdown"]
  ];
}

function sourceWorkflowBriefHtml(source, task = null) {
  return `<div class="source-workflow-brief" aria-label="学习流总览">
    ${sourceWorkflowBriefItems(source, task).map(([label, value, detail]) => `<section>
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <small>${escapeHtml(detail)}</small>
    </section>`).join("")}
  </div>`;
}

function sourceRunModeItems(source, task = null) {
  if (source === "url") {
    return [
      {
        state: "ready",
        label: "完整笔记",
        title: "生成新的链接笔记",
        detail: "粘贴页面、直连视频或 manifest，下载后进入转写、切片和图文总结。",
        action: "start-url"
      },
      {
        state: "ready",
        label: "只下载",
        title: "先把视频拉到本地",
        detail: "适合先验证平台资源是否可访问，再从 media.mp4 继续切片总结。",
        action: "download-url"
      },
      {
        state: canContinueFromDownloadedMedia(task) ? "active" : "wait",
        label: "继续切片",
        title: canContinueFromDownloadedMedia(task) ? "从 media.mp4 继续" : "等待本地媒体",
        detail: "复用已下载视频进入转写、抽帧、视觉窗口和图文总结；不会录制页面。",
        action: canContinueFromDownloadedMedia(task) ? "continue-media" : ""
      }
    ];
  }
  const hasMedia = Boolean(task?.media_path);
  const hasNote = Boolean(task?.note_path);
  const canContinue = canContinueFromDownloadedMedia(task);
  const isDownloadOnly = task?.mode === "download_only";
  const isRerun = task?.mode === "rerun_from_media";
  const fullState = hasNote ? "pass" : isRerun || (task && !isDownloadOnly) ? "active" : "ready";
  const downloadState = hasMedia ? "pass" : isDownloadOnly ? "active" : "ready";
  const continueState = canContinue ? "active" : isRerun ? "pass" : "wait";
  const fullAction = source === "url" ? "start-url" : source === "browser" ? "open-extension" : "upload-local";
  const downloadAction = source === "url" ? "download-url" : source === "browser" ? "open-extension" : "";
  return [
    {
      state: fullState,
      label: "完整笔记",
      title: hasNote ? "已生成图文笔记" : source === "local" ? "上传后直接总结" : "下载后直接总结",
      detail: source === "local"
        ? "上传文件后进入转写、切片、视觉总结。"
        : "媒体直取成功后自动进入转写、切片和图文总结。",
      action: hasNote ? "" : fullAction
    },
    {
      state: downloadState,
      label: "只下载",
      title: hasMedia ? "media.mp4 已保存" : "先把视频拉到本地",
      detail: source === "local"
        ? "本地文件会复制到任务目录，无需平台下载。"
        : "适合先验证平台资源是否可访问，再决定是否继续总结。",
      action: hasMedia ? "" : downloadAction
    },
    {
      state: continueState,
      label: "继续切片",
      title: canContinue ? "从 media.mp4 继续" : isRerun ? "正在生成完整笔记" : "等待本地媒体",
      detail: "复用已下载视频进入转写、抽帧、视觉窗口和图文总结；不会录制页面。",
      action: canContinue ? "continue-media" : ""
    }
  ];
}

function sourceRunModesHtml(source, task = null) {
  return `<div class="source-run-modes" aria-label="运行模式">
    ${sourceRunModeItems(source, task).map(item => {
      const attrs = item.action
        ? ` data-source-workflow-action="${escapeHtml(item.action)}"${item.action === "continue-media" && task?.id ? ` data-task-id="${escapeHtml(task.id)}"` : ""}`
        : " disabled";
      return `<button type="button" class="${escapeHtml(item.state)}"${attrs}>
        <span>${escapeHtml(item.label)}</span>
        <strong>${escapeHtml(item.title)}</strong>
        <small>${escapeHtml(item.detail)}</small>
      </button>`;
    }).join("")}
  </div>`;
}

function sourceWorkflowStatusItems(source, task = null) {
  const selected = task?.selected_resource || {};
  const attempts = task?.download_attempts || [];
  const windows = task ? visualWindows(task) : [];
  const failed = task?.status === "failed";
  const running = task?.status === "running" || task?.status === "queued";
  const hasMedia = Boolean(task?.media_path);
  const hasNote = Boolean(task?.note_path);
  const sourceLabel = source === "local" ? "本地视频" : source === "url" ? "链接解析" : "当前页直取";
  const routeDetail = source === "browser"
    ? selected.kind ? `${selected.kind} · ${resourceSourceText(selected) || selected.source || "候选"}` : "扩展侧栏交接播放器、媒体请求和一次性 Cookie"
    : source === "local"
      ? "文件直接进入本地管线，不依赖平台暴露 URL"
      : "手动 URL 可先预检，再进入直连、manifest 或 yt-dlp 路线";
  const downloadValue = hasMedia
    ? "media.mp4"
    : attempts.length
      ? `${attempts.length} 次尝试`
      : source === "local" ? "待上传" : source === "url" ? "待预检" : "待候选";
  const downloadDetail = hasMedia
    ? "已保存到本地，可导出或继续切片总结"
    : failed
      ? task.error_code || "下载失败"
      : running ? `${task.phase || "running"} · ${task.progress || 0}%` : "开始任务前先确认后端可访问媒体";
  const sliceValue = windows.length
    ? `${windows.length} 个视觉窗口`
    : visualUnderstandingEnabled() ? visualPlanText() : "仅转写";
  const sliceDetail = windows.length
    ? "可在学习切片页核对画面、字幕和自测题"
    : visualUnderstandingEnabled() ? "下载后抽帧拼网格，并按窗口对齐字幕" : "图文理解关闭，不生成视觉窗口";
  const fallbackValue = source === "browser"
    ? failed ? "本地兜底" : "非录制"
    : source === "local" ? "离线管线" : "页面兜底";
  const fallbackDetail = source === "browser"
    ? "不可还原 blob、DRM 或签名过期时切到本地视频"
    : source === "local" ? "同样输出 Markdown、诊断和资料包" : "直连失败后可切页面解析或本地上传";
  return [
    {
      state: task || source !== "browser" ? "pass" : "active",
      label: "入口",
      value: sourceLabel,
      detail: routeDetail
    },
    {
      state: hasMedia ? "pass" : failed ? "block" : running ? "active" : "wait",
      label: "下载",
      value: downloadValue,
      detail: downloadDetail
    },
    {
      state: windows.length ? "pass" : visualUnderstandingEnabled() ? (hasMedia || running ? "active" : "wait") : "skip",
      label: "切片",
      value: sliceValue,
      detail: sliceDetail
    },
    {
      state: failed && source === "browser" ? "warn" : "pass",
      label: "边界",
      value: fallbackValue,
      detail: fallbackDetail
    }
  ];
}

function sourceWorkflowStatusHtml(source, task = null) {
  return `<div class="source-workflow-status" aria-label="路线状态">
    ${sourceWorkflowStatusItems(source, task).map(item => `<section class="${escapeHtml(item.state)}">
      <span>${escapeHtml(item.label)}</span>
      <strong>${escapeHtml(item.value)}</strong>
      <small>${escapeHtml(item.detail)}</small>
    </section>`).join("")}
  </div>`;
}

function sourceWorkflowActionsHtml(source, task = null) {
  const actions = [];
  if (source === "browser") {
    if (task?.id && canContinueFromDownloadedMedia(task)) {
      actions.push(["continue-media", "继续切片总结", task.id]);
    }
    if (!task?.id) actions.push(["open-extension", "去扩展侧栏开始", ""]);
    actions.push(["refresh-browser", task?.id ? "刷新任务" : "刷新交接状态", ""]);
    actions.push(["copy-backend", "复制后端地址", ""]);
    actions.push(["switch-local", task?.id ? "本地兜底" : "上传本地视频兜底", ""]);
  } else if (source === "local") {
    actions.push(["choose-local", "选择文件", ""]);
    actions.push(["upload-local", "上传并生成", ""]);
    actions.push(["open-options", "处理参数", ""]);
  } else {
    actions.push(["focus-url", "填写链接", ""]);
    actions.push(["preflight-url", "预检链接", ""]);
    actions.push(["start-url", "生成笔记", ""]);
    actions.push(["download-url", "只下载", ""]);
  }
  return `<div class="source-workflow-actions" aria-label="下一步操作">
    ${actions.map(([action, label, taskId]) => `<button type="button" data-source-workflow-action="${escapeHtml(action)}"${taskId ? ` data-task-id="${escapeHtml(taskId)}"` : ""}>${escapeHtml(label)}</button>`).join("")}
  </div>`;
}

function sourceWorkflowHtml(source = selectedSource, task = workflowTaskForSource(source)) {
  const config = workflowSourceConfig(source, task);
  const state = task ? statusText(task) : "等待开始";
  return `<section class="source-workflow-card ${escapeHtml(source)}">
    <header>
      <span>${escapeHtml(config.eyebrow)}</span>
      <strong>${escapeHtml(config.title)}</strong>
      <small>${escapeHtml(config.hint)}</small>
    </header>
    ${sourceWorkflowBriefHtml(source, task)}
    ${sourceRunModesHtml(source, task)}
    ${sourceWorkflowStatusHtml(source, task)}
    <ol class="source-workflow-lane">
      ${config.steps.map(([title, detail], index) => `<li class="${workflowStepState(task, index)}">
        <b>${index + 1}</b>
        <span>${escapeHtml(title)}</span>
        <small>${escapeHtml(detail)}</small>
      </li>`).join("")}
    </ol>
    ${sourceRouteInsightsHtml(source, task)}
    <div class="source-option-strip" aria-label="当前处理参数">
      ${currentOptionSummaryItems().map(item => `<span>${escapeHtml(item)}</span>`).join("")}
    </div>
    ${sourceWorkflowActionsHtml(source, task)}
    <footer>
      <span>${escapeHtml(state)}</span>
      ${task ? `<button type="button" data-select-workflow-task="${escapeHtml(task.id)}">查看最近任务</button>` : `<em>选择入口后开始处理</em>`}
    </footer>
  </section>`;
}

function renderSourceWorkflow() {
  if (!els.sourceWorkflow) return;
  els.sourceWorkflow.innerHTML = sourceWorkflowHtml();
}

function drmSignalText(signals = []) {
  const parts = [];
  const keySystems = [...new Set(signals.map(item => item.key_system).filter(Boolean))];
  const initTypes = [...new Set(signals.map(item => item.init_data_type).filter(Boolean))];
  if (keySystems.length) parts.push(`key system：${keySystems.slice(0, 3).join(", ")}`);
  if (initTypes.length) parts.push(`init data：${initTypes.slice(0, 3).join(", ")}`);
  return parts.join(" · ");
}

function activeVideoText(active) {
  if (!active?.src) return "-";
  return [
    active.paused ? "暂停" : "播放中",
    `${fmt(active.current_time || 0)} / ${fmt(active.duration || 0)}`,
    `${active.width || 0}x${active.height || 0}`,
    active.frame_id !== null && active.frame_id !== undefined ? `frame ${active.frame_id}` : "",
    active.drm_detected ? "DRM/EME" : "",
    active.src
  ].filter(Boolean).join(" · ");
}

function statusText(task) {
  if (task.status === "success") return "已完成";
  if (task.status === "failed") return task.error_code || "失败";
  if (task.status === "queued") return "排队中";
  return task.message || task.phase;
}

function sourceText(task) {
  if (task.mode === "download_only") return "当前页下载";
  if (task.mode === "rerun_from_media") return "复用本地视频";
  if (task.source_type === "local") return "本地视频";
  if (task.source_type === "page_text") return "页面文本";
  return task.selected_resource ? `直取 · ${mediaKindText(task.selected_resource.kind) || "媒体"}` : "页面解析";
}

function mediaKindText(kind = "") {
  return ({
    hls: "HLS",
    dash: "DASH",
    video: "视频",
    audio: "音频",
    subtitle: "字幕",
    fragment: "分片",
    blob: "Blob"
  })[String(kind || "").toLowerCase()] || kind || "";
}

function playerLibrarySourceText(resource) {
  if (resource?.source !== "pageHookPlayer") return "";
  const label = String(resource.label || "");
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

function resourceSourceText(resource) {
  const playerSource = playerLibrarySourceText(resource);
  if (playerSource) return `${playerSource}源地址`;
  if (resource?.source === "manifest-guess") return "同目录 manifest 猜测";
  if (resource?.source === "inferred-manifest") return "分片路径回推 manifest";
  if (resource?.source === "webRequestResolved") return "最终媒体地址";
  if (resource?.source === "webRequest") return "浏览器请求";
  if (resource?.source === "iframeHint") return "iframe 内播放器线索";
  if (resource?.source === "scriptHint") return "页面脚本线索";
  if (resource?.source === "domHint") return "页面元素线索";
  if (resource?.source === "locationHint") return "页面 URL 线索";
  if (String(resource?.source || "").startsWith("pageHook")) return "页面接口";
  return resource?.source || "";
}

function taskResolvedTargetText(task, limit = 92) {
  const selected = task?.selected_resource || {};
  const target = selected.resolved_url || "";
  if (!target || target === selected.url) return "";
  return compactUrl(target, limit);
}

function playbackText(match) {
  return ({
    "exact-src": "当前 src",
    "source-element": "当前 source",
    "same-frame": "同播放器 frame",
    "blob-same-frame": "blob 播放同 frame",
    "blob-source": "Blob/MSE 来源映射",
    "range-near-playhead": "播放进度附近 Range 请求",
    "manifest-near-playhead": "播放进度附近 Manifest 请求",
    "resolved-final-url": "跳转后的真实媒体",
    "recent-media-request": "最近播放请求",
    "same-site-request": "同站请求",
    "inferred-from-fragment": "分片推断"
  })[match] || match || "";
}

const PIPELINE_STEPS = [
  { key: "downloading", label: "下载" },
  { key: "transcribing", label: "识别" },
  { key: "extracting_frames", label: "切片" },
  { key: "summarizing", label: "生成" },
  { key: "completed", label: "完成" }
];

const DOWNLOAD_ERROR_CODES = new Set(["no_media_found", "auth_required", "drm_or_encrypted", "download_forbidden", "unsupported_manifest"]);

const ERROR_GUIDES = {
  no_media_found: {
    title: "没有发现可直取的视频资源",
    body: "可以先让页面视频播放几秒后重新检测；如果仍没有 mp4、FLV、AVI、m3u8 或 mpd，请改用本地视频上传。"
  },
  auth_required: {
    title: "资源需要登录态",
    body: "重新打开课程页面并确认已登录，再从扩展侧边栏创建任务；后端只会在点击任务时同步一次当前域 cookie。"
  },
  drm_or_encrypted: {
    title: "页面触发了 DRM/EME 加密媒体信号",
    body: "这个版本不会录制、破解或绕过 DRM。可直取 mp4、FLV、AVI、m3u8 或 mpd 不存在时，只能使用本地视频入口。"
  },
  download_forbidden: {
    title: "媒体服务器拒绝下载",
    body: "通常是 Referer、cookie 或时效签名不匹配。回到原页面重新播放并立刻开始任务，或选择另一个候选资源。"
  },
  unsupported_manifest: {
    title: "manifest 或分片无法合并",
    body: "检测到了媒体线索，但它不是完整可下载的视频或播放列表。继续播放后重新检测，优先选择 m3u8/mpd 候选。"
  },
  processing_failed: {
    title: "本地处理失败",
    body: "下载可能成功，但转音频、转写、抽帧或总结阶段失败。请查看诊断里的阶段和本地 data/tasks 产物。"
  }
};

function failureGuide(task) {
  if (!task || task.status !== "failed") return "";
  const guide = ERROR_GUIDES[task.error_code] || { title: "任务失败", body: task.error_detail || "请查看下载诊断里的尝试记录。" };
  const attempts = task.download_attempts || [];
  const lastAttempt = attempts[attempts.length - 1] || null;
  const steps = recoveryStepItems(task);
  return `<div class="failure-guide">
    <strong>${escapeHtml(guide.title)}</strong>
    <p>${escapeHtml(guide.body)}</p>
    ${lastAttempt ? `<small>最近尝试：${escapeHtml([lastAttempt.strategy, lastAttempt.code, lastAttempt.status_code ? `HTTP ${lastAttempt.status_code}` : "", lastAttempt.message].filter(Boolean).join(" · "))}</small>` : ""}
    <ul>
      ${steps.map(step => `<li>${escapeHtml(step)}</li>`).join("")}
    </ul>
    ${recoveryActionsHtml(task)}
  </div>`;
}

function isChaoxingTask(task = {}) {
  const values = [
    task.page_url,
    task.title,
    task.error_detail,
    task.selected_resource?.url,
    task.selected_resource?.resolved_url,
    task.selected_resource?.initiator,
    task.selected_resource?.label,
    ...(task.download_attempts || []).flatMap(attempt => [attempt.url, attempt.resolved_url, attempt.source, attempt.message])
  ].map(value => String(value || "").toLowerCase()).join(" ");
  return /chaoxing|xuexitong|fanya|mooc1|mooc2|ananas|\u5b66\u4e60\u901a|\u8d85\u661f/.test(values);
}

function recoveryStepItems(task) {
  if (Array.isArray(task?.recovery?.steps) && task.recovery.steps.length) {
    return task.recovery.steps.map(step => String(step));
  }
  const attempts = task?.download_attempts || [];
  const codes = new Set([task?.error_code, ...attempts.map(attempt => attempt.code)].filter(Boolean));
  const steps = [];
  const add = text => {
    if (text && !steps.includes(text)) steps.push(text);
  };
  if (isChaoxingTask(task)) {
    add("检测到学习通/超星页面线索：请先在原课程页真实播放几秒，让 ananas/播放接口暴露 m3u8、mp4 或带 Referer 的媒体请求；本工具只复用你当前登录态可访问的资源，不刷课、不伪造进度、不自动答题。");
  }
  if (codes.has("drm_or_encrypted") || task?.drm_detected) {
    add("不会录制、破解或绕过 DRM；没有可访问 mp4/FLV/AVI/m3u8/mpd 时，请改用本地视频入口。");
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
  const recovery = task?.recovery || {};
  const primary = recovery.primary_action || null;
  const diagnosis = recovery.diagnosis || "";
  const summary = diagnosis || primary?.detail
    ? `<div class="recovery-diagnosis">
        ${diagnosis ? `<span>判断</span><strong>${escapeHtml(diagnosis)}</strong>` : ""}
        ${primary ? `<small>主动作：${escapeHtml(primary.label || primary.key || "查看诊断")}${primary.detail ? ` · ${escapeHtml(primary.detail)}` : ""}</small>` : ""}
      </div>`
    : "";
  return `<section class="diagnostic-recovery" aria-label="恢复建议">
    <strong>下一步建议</strong>
    ${summary}
    <ul>${steps.map(step => `<li>${escapeHtml(step)}</li>`).join("")}</ul>
    ${recoveryActionsHtml(task)}
  </section>`;
}

function recoveryActionButtonHtml(action, task) {
  const label = escapeHtml(action.label || action.key || "查看诊断");
  const title = action.detail ? ` title="${escapeHtml(action.detail)}"` : "";
  const intent = action.ui_intent || action.key || "";
  if (intent === "local_upload") {
    return `<button type="button" data-recovery-source="local"${title}>${label}</button>`;
  }
  if (intent === "retry_current_page") {
    return `<button type="button" data-recovery-source="browser"${title}>${label}</button>`;
  }
  if (intent === "inspect_diagnostics") {
    return `<button type="button" data-switch-result-tab="diagnostics"${title}>${label}</button>`;
  }
  if (intent === "continue_from_media") {
    return canContinueFromDownloadedMedia(task)
      ? `<button type="button" data-rerun-from-media="${escapeHtml(task.id)}"${title}>${label}</button>`
      : "";
  }
  if (intent === "export_markdown") {
    return task.note_path ? `<a href="${escapeHtml(taskExportUrl(task, "markdown"))}"${title}>${label}</a>` : "";
  }
  if (intent === "export_diagnostics") {
    return hasTaskDiagnostics(task) ? `<a href="${escapeHtml(taskExportUrl(task, "diagnostics"))}"${title}>${label}</a>` : "";
  }
  if (intent === "export_audit" || intent === "inspect_audit") {
    return hasTaskAudit(task) ? `<a href="${escapeHtml(taskExportUrl(task, "audit"))}"${title}>${label}</a>` : "";
  }
  return `<button type="button" data-switch-result-tab="diagnostics"${title}>${label}</button>`;
}

function recoveryActionsHtml(task, skipKeys = new Set()) {
  if (!task) return "";
  const structured = Array.isArray(task.recovery?.actions) ? task.recovery.actions : [];
  if (structured.length) {
    const skipped = skipKeys instanceof Set ? skipKeys : new Set(skipKeys || []);
    const rendered = structured
      .filter(action => !skipped.has(action.key) && !skipped.has(action.ui_intent))
      .map(action => recoveryActionButtonHtml(action, task))
      .filter(Boolean);
    return `<div class="recovery-actions">${rendered.join("")}</div>`;
  }
  const actions = [
    `<button type="button" data-recovery-source="local">上传本地视频</button>`,
    `<button type="button" data-switch-result-tab="diagnostics">查看诊断</button>`
  ];
  if (hasTaskDiagnostics(task)) actions.push(`<a href="${escapeHtml(taskExportUrl(task, "diagnostics"))}">导出诊断</a>`);
  if (hasTaskAudit(task)) actions.push(`<a href="${escapeHtml(taskExportUrl(task, "audit"))}">导出审计</a>`);
  if (canContinueFromDownloadedMedia(task)) actions.push(`<button type="button" data-rerun-from-media="${escapeHtml(task.id)}">继续切片总结</button>`);
  if (task.note_path) actions.push(`<a href="${escapeHtml(taskExportUrl(task, "markdown"))}">导出 Markdown</a>`);
  return `<div class="recovery-actions">${actions.join("")}</div>`;
}

function primaryRecoveryAction(task) {
  const primary = task?.recovery?.primary_action || null;
  if (!primary) return null;
  const intent = primary.ui_intent || primary.key || "";
  const actionable = task?.status === "failed"
    || canContinueFromDownloadedMedia(task)
    || ["local_upload", "retry_current_page", "continue_from_media"].includes(intent)
    || ["recoverable", "hard_boundary"].includes(task?.recovery?.severity || "");
  return actionable ? primary : null;
}

function recoveryDecisionTone(task) {
  const severity = task?.recovery?.severity || "";
  if (severity === "hard_boundary" || task?.drm_detected) return "blocked";
  if (task?.status === "failed" || severity === "recoverable") return "warn";
  if (canContinueFromDownloadedMedia(task)) return "ready";
  return "active";
}

function recoveryDecisionMetrics(task) {
  const recovery = task?.recovery || {};
  const direct = task?.direct_extraction || {};
  const reuse = task?.reuse || {};
  return [
    ["诊断码", recovery.code || task?.error_code || "-"],
    ["置信度", recovery.confidence || "-"],
    ["尝试", Number.isFinite(recovery.attempt_count) ? `${recovery.attempt_count} 条路线` : `${task?.download_attempts?.length || 0} 条路线`],
    ["边界", directExtractionBoundaryText(direct.boundary)],
    ["复用", reuse.rerun_from_media_ready || canContinueFromDownloadedMedia(task) ? "media.mp4 可续跑" : reuse.suggested_next_step || "-"]
  ];
}

function recoveryDecisionHtml(task) {
  if (!task?.id || !task.recovery) return "";
  const primary = primaryRecoveryAction(task);
  const show = Boolean(
    primary
    || task.status === "failed"
    || canContinueFromDownloadedMedia(task)
    || task.mode === "download_only"
    || task.direct_extraction?.boundary && task.direct_extraction.boundary !== "normal_accessible_media_only"
  );
  if (!show) return "";

  const recovery = task.recovery || {};
  const notes = Array.isArray(recovery.boundary_notes)
    ? recovery.boundary_notes.map(value => String(value || "").trim()).filter(Boolean).slice(0, 3)
    : [];
  const steps = Array.isArray(recovery.steps)
    ? recovery.steps.map(value => String(value || "").trim()).filter(Boolean).slice(0, 3)
    : [];
  const primaryHtml = primary ? recoveryActionButtonHtml(primary, task) : "";
  const skipKeys = new Set([primary?.key, primary?.ui_intent].filter(Boolean));
  const secondaryHtml = recoveryActionsHtml(task, skipKeys);
  const detail = recovery.diagnosis || primary?.detail || task.error_detail || "按阶段审计继续处理当前任务。";

  return `<section class="recovery-decision ${escapeHtml(recoveryDecisionTone(task))}" aria-label="推荐行动">
    <div class="recovery-decision-main">
      <span>推荐行动</span>
      <strong>${escapeHtml(primary?.label || (canContinueFromDownloadedMedia(task) ? "继续切片总结" : "查看阶段检查"))}</strong>
      <small>${escapeHtml(detail)}</small>
    </div>
    <div class="recovery-decision-actions">
      ${primaryHtml ? `<div class="recovery-decision-primary">${primaryHtml}</div>` : ""}
      ${secondaryHtml}
    </div>
    <div class="recovery-decision-metrics">
      ${recoveryDecisionMetrics(task).map(([label, value]) => `<span><b>${escapeHtml(label)}</b><strong>${escapeHtml(value || "-")}</strong></span>`).join("")}
    </div>
    ${notes.length || steps.length ? `<ul>
      ${[...notes, ...steps].slice(0, 4).map(item => `<li>${escapeHtml(item)}</li>`).join("")}
    </ul>` : ""}
  </section>`;
}

function failedStepIndex(task) {
  if (DOWNLOAD_ERROR_CODES.has(task.error_code)) return 0;
  if (task.media_path && !task.transcript_path) return 1;
  if (task.transcript_path && !task.frame_grids?.length) return 2;
  return 3;
}

function stepState(task, step) {
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

function stageRail(task) {
  if (task.source_type === "page_text") {
    const done = task.status === "success";
    const failed = task.status === "failed";
    return `<div class="stage-rail compact">
      <span class="${done ? "done" : failed ? "failed" : "active"}">解析</span>
      <span class="${done ? "done" : failed ? "failed" : task.phase === "summarizing" ? "active" : "pending"}">总结</span>
      <span class="${done ? "done" : failed ? "failed" : "pending"}">完成</span>
    </div>`;
  }
  return `<div class="stage-rail">${PIPELINE_STEPS.map(step => `<span class="${stepState(task, step)}">${step.label}</span>`).join("")}</div>`;
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

function optionText(task) {
  const options = task.options || {};
  return [
    options.frame_interval ? `${options.frame_interval} 秒切片` : "",
    options.grid_columns && options.grid_rows ? `${options.grid_columns}x${options.grid_rows} 画面网格` : "",
    asrOptionText(options),
    options.note_style ? `风格 ${options.note_style}` : "",
    options.note_template ? `格式 ${options.note_template}` : "",
    options.visual_understanding === false ? "未开启视觉理解" : "视觉理解"
  ].filter(Boolean).join(" · ");
}

function mediaKind(url) {
  if (HLS_RE.test(url)) return url.toLowerCase().includes(".mpd") ? "dash" : "hls";
  if (MEDIA_RE.test(url)) return "video";
  return "unknown";
}

function selectedUrlMode() {
  return els.urlMode?.value || "auto";
}

function urlModeDescription(mode = selectedUrlMode()) {
  return ({
    auto: "自动识别会优先把 mp4/FLV/AVI/m3u8/mpd 当作媒体候选；无后缀 URL 可切换直连/HLS/DASH 或交给页面扫描和 yt-dlp。",
    page: "按课程网页处理：后端先扫描页面里的媒体地址，再用 yt-dlp 解析，不把这个 URL 当直连文件。",
    video: "按视频文件直连处理：适合没有后缀但实际返回 video/* 的签名接口或播放接口。",
    hls: "按 HLS 播放列表处理：后端会用 ffmpeg 合并 m3u8 可访问的分片。",
    dash: "按 DASH manifest 处理：后端会用 ffmpeg 合并 mpd 可访问的分片。"
  })[mode] || "";
}

function resourceKindForUrl(url, mode = selectedUrlMode()) {
  if (mode === "video" || mode === "hls" || mode === "dash") return mode;
  if (mode === "page") return "unknown";
  return mediaKind(url);
}

function mimeForKind(kind) {
  if (kind === "video") return "video/mp4";
  if (kind === "hls") return "application/vnd.apple.mpegurl";
  if (kind === "dash") return "application/dash+xml";
  return "";
}

function isTextResponseMime(value = "") {
  return /(?:^|;|\s)(text\/|application\/json|application\/xml|application\/javascript)/i.test(String(value || ""));
}

function labelForUrlResource(kind, mode = selectedUrlMode()) {
  if (mode === "video") return "手动视频直连";
  if (mode === "hls") return "手动 HLS";
  if (mode === "dash") return "手动 DASH";
  if (kind === "video") return "手动媒体链接";
  if (kind === "hls") return "手动 HLS";
  if (kind === "dash") return "手动 DASH";
  return "手动链接";
}

function manualUrlResource(url) {
  const kind = resourceKindForUrl(url);
  if (kind === "unknown") return null;
  const resource = {
    url,
    source: "manual",
    kind,
    mime: mimeForKind(kind),
    score: selectedUrlMode() === "auto" ? 96 : 98,
    label: labelForUrlResource(kind),
    request_type: selectedUrlMode() === "auto" ? "manual-auto" : "manual-forced"
  };
  applyUrlPreflightToResource(resource);
  return resource;
}

function clearUrlPreflight() {
  urlPreflightResourceUrl = "";
  urlPreflightResult = null;
  renderUrlPreflightReport(null, null);
}

function rememberUrlPreflight(resource, result) {
  if (!resource?.url || !result) return result;
  urlPreflightResourceUrl = resource.url;
  urlPreflightResult = result;
  applyUrlPreflightToResource(resource);
  return result;
}

function applyUrlPreflightToResource(resource) {
  if (!resource?.url || resource.url !== urlPreflightResourceUrl || !urlPreflightResult?.downloadable) return;
  const kind = String(urlPreflightResult.kind || "").toLowerCase();
  if (["video", "hls", "dash"].includes(kind)) {
    resource.kind = kind;
    resource.mime = mimeForKind(kind) || resource.mime;
  }
  if (urlPreflightResult.resolved_url && urlPreflightResult.resolved_url !== resource.url) {
    resource.resolved_url = urlPreflightResult.resolved_url;
  }
  if (urlPreflightResult.content_type) {
    const resolvedMime = urlPreflightResult.strategy === "direct-response-probe" && isTextResponseMime(urlPreflightResult.content_type)
      ? mimeForKind(resource.kind || kind)
      : urlPreflightResult.content_type;
    if (resolvedMime) resource.mime = resolvedMime;
    resource.headers = { ...(resource.headers || {}), "content-type": urlPreflightResult.content_type };
  }
  if (urlPreflightResult.content_disposition) {
    resource.headers = { ...(resource.headers || {}), "content-disposition": urlPreflightResult.content_disposition };
  }
  const statusCode = Number(urlPreflightResult.status_code);
  if (Number.isFinite(statusCode) && statusCode > 0) resource.status_code = statusCode;
  const contentLength = Number(urlPreflightResult.content_length);
  if (Number.isFinite(contentLength) && contentLength > 0) resource.content_length = contentLength;
}

function preflightKindLabel(kind) {
  const key = String(kind || "").toLowerCase();
  if (key === "hls") return "HLS";
  if (key === "dash") return "DASH";
  if (key === "video") return "视频直连";
  if (key === "page") return "页面扫描";
  return key || "未知";
}

function preflightStrategyLabel(strategy) {
  const key = String(strategy || "").trim();
  const labels = {
    "direct-response-probe": "直连响应探测",
    "manifest-probe": "清单探测",
    "range-probe": "分段探测",
    "yt-dlp": "yt-dlp 页面解析"
  };
  return labels[key] || key || "后端预检";
}

function renderUrlPreflightReport(resource, result, state = "") {
  if (!els.urlPreflightReport) return;
  if (!resource && !result) {
    els.urlPreflightReport.hidden = true;
    els.urlPreflightReport.className = "url-preflight-report";
    els.urlPreflightReport.innerHTML = "";
    return;
  }

  const downloadable = Boolean(result?.downloadable);
  const status = state || (downloadable ? "pass" : "fail");
  const statusText = status === "checking" ? "预检中" : downloadable ? "可直取" : "未通过";
  const target = result?.resolved_url || (downloadable ? resource?.resolved_url : "") || resource?.url || "";
  const original = resource?.url || "";
  const sizeText = fmtBytes(result?.content_length) || (result?.bytes_checked ? `${result.bytes_checked} B checked` : "未知");
  const httpText = result?.status_code ? `HTTP ${result.status_code}` : "未返回";
  const kindText = preflightKindLabel(result?.kind || resource?.kind);
  const strategyText = preflightStrategyLabel(result?.strategy);
  const message = state === "checking"
    ? "正在确认后端是否能直接访问这个媒体资源。"
    : downloadable
      ? "可以直接生成笔记或只下载到本地；后续会复用这个解析目标。"
      : (result?.message || result?.code || "这个链接暂时不能直接下载，可切换链接类型、创建页面扫描任务，或改用本地视频。");
  const requestHeaders = Array.isArray(result?.request_header_names) && result.request_header_names.length
    ? result.request_header_names.slice(0, 5).join(" / ")
    : "";

  const rows = [
    ["类型", kindText],
    ["探测", strategyText],
    ["HTTP", httpText],
    ["大小", sizeText]
  ];
  if (target && target !== original) rows.push(["目标", compactUrl(target, 96)]);
  if (requestHeaders) rows.push(["请求头", requestHeaders]);

  els.urlPreflightReport.hidden = false;
  els.urlPreflightReport.className = `url-preflight-report ${status}`;
  els.urlPreflightReport.innerHTML = `
    <div class="url-preflight-report-head">
      <span>${escapeHtml(statusText)}</span>
      <strong>${escapeHtml(kindText)}</strong>
    </div>
    <div class="url-preflight-report-grid">
      ${rows.map(([label, value]) => `
        <span>${escapeHtml(label)}</span>
        <b>${escapeHtml(value)}</b>
      `).join("")}
    </div>
    <p>${escapeHtml(message)}</p>
  `;
}

function renderUrlModeHint() {
  if (!els.urlModeHint) return;
  els.urlModeHint.textContent = urlModeDescription();
  renderUrlPreflightReport(null, null);
}

function visualUnderstandingEnabled() {
  return els.visualUnderstanding?.checked !== false;
}

function visualPlanText() {
  if (!visualUnderstandingEnabled()) return "无视觉 · 仅转写";
  const [cols, rows] = String(els.gridSize?.value || "3x3").split("x").map(Number);
  return `${Number(els.frameInterval?.value || 20)}秒 · ${cols || 3}x${rows || 3}`;
}

function currentOptionSummaryItems() {
  return [
    visualPlanText(),
    asrOptionText({
      transcriber: els.transcriber?.value || "faster-whisper",
      whisper_model: els.whisperModel?.value || "small"
    }),
    `${els.noteStyle?.value || "study"} · ${els.noteTemplate?.value || "standard"} · ${els.summaryDepth?.value || "standard"}`
  ];
}

function refreshOptionDependentUi() {
  syncTranscriberModelDefault();
  renderSourceWorkflow();
}

function applyModelProviderPreset(force = false) {
  const preset = MODEL_PROVIDER_PRESETS[els.llmProvider?.value || ""];
  if (!preset) return;
  if (els.llmBaseUrl && (force || !els.llmBaseUrl.value.trim())) {
    els.llmBaseUrl.value = preset.baseUrl;
  }
  if (els.llmModel && (force || !els.llmModel.value.trim())) {
    els.llmModel.value = preset.model;
  }
  if (els.transcriber && preset.transcriber && (force || els.transcriber.value === "faster-whisper")) {
    els.transcriber.value = preset.transcriber;
  }
  if (els.whisperModel && preset.whisperModel && (force || !els.whisperModel.value.trim() || LOCAL_ASR_MODELS.has(els.whisperModel.value))) {
    els.whisperModel.value = preset.whisperModel;
  }
  syncTranscriberModelDefault(false);
  renderSourceWorkflow();
  updateHealthVisionStatus();
}

function currentModelSettings() {
  return {
    llm_provider: els.llmProvider?.value || "",
    llm_model: els.llmModel?.value?.trim() || "",
    llm_base_url: els.llmBaseUrl?.value?.trim() || "",
    transcriber: els.transcriber?.value || "faster-whisper",
    whisper_model: els.whisperModel?.value || "small"
  };
}

function applyModelSettings(settings = {}) {
  if (!settings || typeof settings !== "object") return;
  if (els.llmProvider && settings.llm_provider && MODEL_PROVIDER_PRESETS[settings.llm_provider]) {
    els.llmProvider.value = settings.llm_provider;
  }
  if (els.llmModel && typeof settings.llm_model === "string") {
    els.llmModel.value = settings.llm_model;
  }
  if (els.llmBaseUrl && typeof settings.llm_base_url === "string") {
    els.llmBaseUrl.value = settings.llm_base_url;
  }
  if (els.transcriber && typeof settings.transcriber === "string") {
    els.transcriber.value = settings.transcriber;
  }
  if (els.whisperModel && typeof settings.whisper_model === "string") {
    els.whisperModel.value = settings.whisper_model;
  }
  syncTranscriberModelDefault(false);
}

function loadModelSettings() {
  try {
    const raw = window.localStorage?.getItem(MODEL_SETTINGS_STORAGE_KEY);
    if (!raw) return;
    applyModelSettings(JSON.parse(raw));
  } catch {
    return;
  }
}

function saveModelSettings() {
  try {
    window.localStorage?.setItem(MODEL_SETTINGS_STORAGE_KEY, JSON.stringify(currentModelSettings()));
  } catch {
    return;
  }
}

function readOptions() {
  syncTranscriberModelDefault();
  const [cols, rows] = els.gridSize.value.split("x").map(Number);
  const options = {
    visual_understanding: visualUnderstandingEnabled(),
    frame_interval: Number(els.frameInterval.value || 20),
    grid_columns: cols || 3,
    grid_rows: rows || 3,
    transcriber: els.transcriber?.value || "faster-whisper",
    whisper_model: els.whisperModel.value || "small",
    note_style: els.noteStyle.value || "study",
    note_template: els.noteTemplate?.value || "standard",
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

function healthVisionReady(data) {
  return Boolean(data?.vision_model_configured || els.llmApiKey?.value?.trim());
}

function healthVisionModel(data) {
  return els.llmModel?.value?.trim() || data?.default_llm_model || "gpt-4.1-mini";
}

function healthVisionProvider(data) {
  const selected = (els.llmProvider?.value || "").trim();
  if (selected) {
    return ({
      openai: "OpenAI",
      groq: "Groq",
      gemini: "Gemini",
      dashscope: "DashScope",
      siliconflow: "SiliconFlow",
      openrouter: "OpenRouter",
      "local-openai": "Local",
      ollama: "Ollama"
    })[selected] || selected;
  }
  const provider = String(data?.default_llm_provider || "").trim();
  return ({
    openai: "OpenAI",
    groq: "Groq",
    gemini: "Gemini",
    dashscope: "DashScope",
    siliconflow: "SiliconFlow",
    openrouter: "OpenRouter",
    "local-openai": "Local",
    "local-openai-compatible": "Local",
    "openai-compatible": "Compatible"
  })[provider] || provider || "Compatible";
}

function healthVisionText(data) {
  const model = healthVisionModel(data);
  const provider = healthVisionProvider(data);
  const asr = healthAsrChipText();
  if (healthVisionReady(data)) {
    return `视觉模型已配置（${provider} · ${model}），切片网格会随字幕进入图文总结；转写：${asr}。`;
  }
  return `未配置视觉模型 API Key：当前默认 ${provider} · ${model} 仅作待用配置；转写：${asr}；仍会生成字幕、切片网格和本地图文索引。`;
}

function healthVisionChipText(data) {
  const model = healthVisionModel(data);
  const provider = healthVisionProvider(data);
  return healthVisionReady(data) ? `${provider} · ${model}` : `待填 · ${provider}`;
}

function healthAsrChipText() {
  return `${transcriberLabel(els.transcriber?.value || "faster-whisper")} · ${els.whisperModel?.value || "small"}`;
}

function healthMediaChipText(data) {
  if (!data?.ffmpeg) return "ffmpeg 缺失";
  if (data.ffprobe_optional) return "后端 · ffmpeg 时长回退";
  return "后端 · 直取/切片就绪";
}

function emptyReadinessItems(data = lastHealthData) {
  const backendReady = Boolean(data?.ffmpeg);
  return [
    {
      state: backendReady ? "pass" : "block",
      label: "后端媒体检查",
      value: backendReady ? healthMediaChipText(data) : "后端未就绪",
      detail: backendReady
        ? "可以下载、合并、转音频、抽帧和生成本地 media.mp4。"
        : "先启动 127.0.0.1 后端并确认 ffmpeg 可用。"
    },
    {
      state: healthVisionReady(data) ? "pass" : "warn",
      label: "视觉总结检查",
      value: healthVisionChipText(data),
      detail: healthVisionReady(data)
        ? "切片网格会和转写片段一起进入多模态总结。"
        : `${healthVisionProvider(data)} 默认模型待用；仍会生成转写、截图网格和本地索引，配置 Key 后再启用图文总结。`
    },
    {
      state: "pass",
      label: "本地视频检查",
      value: "拖拽自动上传",
      detail: "平台直取失败时，mp4、mkv、webm、flv、avi 可走同一套切片管线。"
    },
    {
      state: "warn",
      label: "当前页直取检查",
      value: "需要扩展侧栏",
      detail: "只使用可访问媒体 URL、manifest、播放器源和一次性 cookie，不录制页面。"
    }
  ];
}

function emptyReadinessGatesHtml(data = lastHealthData) {
  return `<div class="empty-readiness-gates" data-empty-readiness aria-label="准备度检查">
    ${emptyReadinessItems(data).map(item => `<section class="${escapeHtml(item.state)}">
      <span>${escapeHtml(item.label)}</span>
      <strong>${escapeHtml(item.value)}</strong>
      <small>${escapeHtml(item.detail)}</small>
    </section>`).join("")}
  </div>`;
}

function refreshEmptyWorkbenchReadiness() {
  const node = document.querySelector("[data-empty-readiness]");
  if (node) node.innerHTML = emptyReadinessItems().map(item => `<section class="${escapeHtml(item.state)}">
    <span>${escapeHtml(item.label)}</span>
    <strong>${escapeHtml(item.value)}</strong>
    <small>${escapeHtml(item.detail)}</small>
  </section>`).join("");
}

function updateHealthVisionStatus(data = lastHealthData) {
  if (!data || !els.browserBridgeStatus) return;
  const mediaText = String(els.browserBridgeStatus.dataset.mediaText || els.browserBridgeStatus.textContent || "").trim();
  const visionText = healthVisionText(data);
  els.browserBridgeStatus.dataset.mediaText = mediaText;
  els.browserBridgeStatus.title = `${mediaText} ${visionText}`.trim();
  els.browserBridgeStatus.classList.add("capture-status-grid");
  els.browserBridgeStatus.innerHTML = `
    <span class="capture-status-chip bridge"><b>桥接</b>需 Chrome/Edge 扩展侧栏</span>
    <span class="capture-status-chip media"><b>媒体</b>${escapeHtml(healthMediaChipText(data))}</span>
    <span class="capture-status-chip vision ${healthVisionReady(data) ? "ready" : "pending"}"><b>视觉</b>${escapeHtml(healthVisionChipText(data))}</span>
    <span class="capture-status-chip asr"><b>转写</b>${escapeHtml(healthAsrChipText())}</span>
  `;
}

async function checkHealth() {
  try {
    const data = await fetchJson(apiUrl("/health"));
    els.health.className = data.ffmpeg ? "health ok" : "health bad";
    els.health.textContent = data.ffmpeg
      ? data.ffprobe_optional ? "后端可用 · ffprobe 可选" : "本地后端可用"
      : "ffmpeg 缺失";
    if (els.browserBridgeStatus) {
      els.browserBridgeStatus.textContent = data.ffmpeg
        ? data.ffprobe_optional
          ? "ffmpeg 可用，缺少 ffprobe 时会用 ffmpeg 输出解析时长；仍可下载、转写、切片和图文总结。"
          : "扩展读取播放器、媒体请求和一次性 cookie，后端只下载可访问的视频地址。"
        : "后端已连接，但 ffmpeg 缺失；当前页直取后无法完成合并/切片。";
      updateHealthVisionStatus(data);
      refreshEmptyWorkbenchReadiness();
    }
  } catch {
    els.health.className = "health bad";
    els.health.textContent = "后端未连接";
    if (els.browserBridgeStatus) {
      els.browserBridgeStatus.textContent = "先启动本地后端，再从扩展 Side Panel 创建当前页任务。";
    }
    refreshEmptyWorkbenchReadiness();
  }
}

function setSource(source) {
  selectedSource = source;
  els.sourceTabs.forEach(tab => tab.classList.toggle("active", tab.dataset.source === source));
  els.panes.forEach(pane => pane.classList.toggle("active", pane.id === `${source}Source`));
  renderSourceWorkflow();
}

function shouldFocusResultPanel() {
  if (window.matchMedia) return window.matchMedia("(max-width: 760px)").matches;
  return Number(window.innerWidth || 0) <= 760;
}

function focusResultPanelOnMobile() {
  if (!shouldFocusResultPanel()) return;
  document.querySelector(".result-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function initializeResponsiveChrome() {
  if (shouldFocusResultPanel() && els.optionsDisclosure) {
    els.optionsDisclosure.open = false;
  }
}

function storedUiFlag(key) {
  try {
    return window.localStorage?.getItem(key) === "1";
  } catch {
    return false;
  }
}

function storeUiFlag(key, value) {
  try {
    window.localStorage?.setItem(key, value ? "1" : "0");
  } catch {
    // Storage can be unavailable in private contexts or tests.
  }
}

function setPressed(button, pressed) {
  if (!button) return;
  button.setAttribute?.("aria-pressed", pressed ? "true" : "false");
  button.classList?.toggle("active", Boolean(pressed));
}

function setHistoryCollapsed(collapsed, persist = true) {
  document.body?.classList?.toggle("queue-collapsed", Boolean(collapsed));
  setPressed(els.toggleHistoryButton, collapsed);
  if (persist) storeUiFlag("learnnote.historyCollapsed", collapsed);
}

function setWorkspaceCollapsed(collapsed, persist = true) {
  document.body?.classList?.toggle("workspace-collapsed", Boolean(collapsed));
  setPressed(els.toggleWorkspaceButton, collapsed);
  if (persist) storeUiFlag("learnnote.workspaceCollapsed", collapsed);
}

function setReadingMode(enabled, persist = true) {
  document.body?.classList?.toggle("reading-mode", Boolean(enabled));
  setPressed(els.readingModeButton, enabled);
  if (persist) storeUiFlag("learnnote.readingMode", enabled);
}

function renderResultTabState() {
  els.resultTabs.forEach(item => {
    const active = normalizeResultTabName(item.dataset.tab) === selectedTab;
    item.classList.toggle("active", active);
    item.setAttribute?.("aria-selected", active ? "true" : "false");
  });
}

function hasExplicitTaskRoute() {
  return Boolean(taskIdFromCurrentUrl());
}

function initializeWorkspaceView() {
  const taskRoute = hasExplicitTaskRoute();
  setWorkspaceCollapsed(taskRoute && storedUiFlag("learnnote.workspaceCollapsed"), false);
  setHistoryCollapsed(taskRoute && storedUiFlag("learnnote.historyCollapsed"), false);
  setReadingMode(taskRoute && storedUiFlag("learnnote.readingMode"), false);
  renderResultTabState();
}

async function loadTasks() {
  let data = { tasks: [] };
  try {
    data = await fetchJson(apiUrl("/api/tasks"));
  } catch {
    tasks = [];
    selectedTaskId = null;
    renderTasks();
    renderBrowserRouteSummary();
    renderSourceWorkflow();
    await renderDetail();
    return;
  }
  tasks = data.tasks || [];
  if (selectedTaskId && !tasks.some(task => task.id === selectedTaskId)) selectedTaskId = null;
  if (!selectedTaskId) {
    const initialTask = preferredInitialTask(tasks);
    if (initialTask) selectTask(initialTask.id, { clearCaches: false });
  }
  else if (selectedTaskId) syncSelectedTaskUrl(selectedTaskId);
  renderTasks();
  renderBrowserRouteSummary();
  renderSourceWorkflow();
  await renderDetail();
}

function taskMatchesFilters(task) {
  if (taskStatusFilter !== "all") {
    const running = task.status === "running" || task.status === "queued";
    if (taskStatusFilter === "running" && !running) return false;
    if (taskStatusFilter !== "running" && task.status !== taskStatusFilter) return false;
  }
  const query = taskQuery.trim().toLowerCase();
  if (!query) return true;
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
  ].filter(Boolean).join(" ").toLowerCase().includes(query);
}

function renderTasks() {
  els.taskCount.textContent = String(tasks.length);
  els.successCount.textContent = String(tasks.filter(task => task.status === "success").length);
  els.runningCount.textContent = String(tasks.filter(task => task.status === "running" || task.status === "queued").length);
  els.failedCount.textContent = String(tasks.filter(task => task.status === "failed").length);

  const visibleTasks = sortedVisibleTasks(tasks.filter(taskMatchesFilters), selectedTaskId);

  if (!tasks.length) {
    els.tasks.innerHTML = emptyTaskQueueHtml();
    return;
  }
  if (!visibleTasks.length) {
    els.tasks.innerHTML = `<div class="detail empty">没有匹配的任务。</div>`;
    return;
  }

  els.tasks.innerHTML = visibleTasks.map(task => `
    <button class="task status-${escapeHtml(task.status)} ${task.id === selectedTaskId ? "selected" : ""}" data-id="${escapeHtml(task.id)}">
      ${taskPreviewHtml(task)}
      <div class="task-body">
        <div class="task-headline">
          <strong>${escapeHtml(displayTaskTitle(task))}</strong>
          <span class="task-status-pill ${escapeHtml(taskStatusClass(task))}">${escapeHtml(statusText(task))} · ${task.progress || 0}%</span>
        </div>
        <small class="task-meta-line">${escapeHtml(taskMetaLine(task))}</small>
        ${taskChipsHtml(task)}
        ${taskHandoffHtml(task)}
        ${taskAuditMiniHtml(task)}
        ${stageRail(task)}
        <div class="progress"><span style="width:${task.progress || 0}%"></span></div>
      </div>
    </button>
  `).join("");

  document.querySelectorAll(".task").forEach(button => {
    button.onclick = async () => {
      selectTask(button.dataset.id);
      renderTasks();
      await renderDetail();
      focusResultPanelOnMobile();
    };
  });
}

function emptyTaskQueueHtml() {
  const steps = [
    ["1", "直取/上传", "当前页候选、链接或本地视频"],
    ["2", "下载与转写", "ffmpeg / yt-dlp / Whisper"],
    ["3", "画面切片", "按时间窗生成网格截图"],
    ["4", "整理笔记", "时间轴、概念、复习题"]
  ];
  return `<section class="queue-empty-workflow" aria-label="任务队列空状态">
    <span>暂无任务</span>
    <strong>选择左侧入口开始生成学习笔记</strong>
    <p>任务会在这里形成队列；成功后右侧直接进入笔记、字幕、画面切片和下载诊断。</p>
    <ol>
      ${steps.map(([index, title, detail]) => `<li>
        <b>${escapeHtml(index)}</b>
        <span>${escapeHtml(title)}</span>
        <small>${escapeHtml(detail)}</small>
      </li>`).join("")}
    </ol>
  </section>`;
}

function taskPreviewHtml(task) {
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
      : task.error_code || statusText(task);
  if (firstWindow?.grid_url) {
    return `<figure class="task-preview status-${escapeHtml(status)}">
      <img src="${escapeHtml(firstWindow.grid_url)}" alt="${escapeHtml(firstWindow.id || "frame grid")}">
      <figcaption><b>${escapeHtml(label)}</b><span>${escapeHtml(detail)}</span></figcaption>
    </figure>`;
  }
  return `<figure class="task-preview status-${escapeHtml(status)} empty">
    <div>${taskPreviewIcon(status)}</div>
    <figcaption><b>${escapeHtml(label)}</b><span>${escapeHtml(detail)}</span></figcaption>
  </figure>`;
}

function taskPreviewIcon(status) {
  if (status === "success") return "✓";
  if (status === "failed") return "!";
  if (status === "running") return "…";
  return "LN";
}

function taskChipItems(task) {
  const selected = task.selected_resource || {};
  const windows = visualWindows(task);
  const attempts = task.download_attempts || [];
  const route = selected.playback_match
    ? playbackText(selected.playback_match)
    : resourceSourceText(selected) || (task.source_type === "current_page" ? "页面解析" : sourceText(task));
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

function taskChipsHtml(task) {
  const metaParts = new Set(taskMetaLine(task).split(" · ").map(item => item.trim()).filter(Boolean));
  const chips = taskChipItems(task).filter(chip => {
    const text = String(chip || "").trim();
    return !(metaParts.has(text) && ["本地视频", "视频"].includes(text));
  });
  if (!chips.length) return "";
  return `<div class="task-chips">${chips.map(chip => `<span>${escapeHtml(chip)}</span>`).join("")}</div>`;
}

function taskHandoffItems(task) {
  const selected = task?.selected_resource || {};
  const windows = visualWindows(task || {});
  const attempts = task?.download_attempts || [];
  const sourceLabel = sourceText(task);
  const mediaLabel = task?.media_path
    ? "media.mp4 已保存"
    : attempts.length
      ? `${attempts.length} 次下载尝试`
      : task?.source_type === "local"
        ? "等待上传"
        : "等待直取";
  const sliceLabel = task?.options?.visual_understanding === false || task?.source_type === "page_text"
    ? "文本路线"
    : windows.length
      ? `${windows.length} 个切片窗口`
      : "等待切片";
  const nextLabel = (() => {
    if (canContinueFromDownloadedMedia(task)) return "下一步：继续切片总结";
    if (task?.status === "failed") return task?.recovery?.primary_action?.label ? `下一步：${task.recovery.primary_action.label}` : "下一步：查看诊断";
    if (task?.note_path) return windows.length ? "下一步：核对画面笔记" : "下一步：阅读笔记";
    if (task?.status === "running" || task?.status === "queued") return `下一步：${statusText(task)}`;
    return "下一步：打开任务";
  })();
  return [
    ["来源", [sourceLabel, selected.kind ? mediaKindText(selected.kind) : ""].filter(Boolean).join(" · ") || "-"],
    ["媒体", mediaLabel],
    ["切片", sliceLabel],
    ["动作", nextLabel]
  ];
}

function taskHandoffHtml(task) {
  const tone = task?.status === "failed"
    ? "blocked"
    : canContinueFromDownloadedMedia(task)
      ? "ready"
      : task?.note_path
        ? "done"
        : task?.status === "running" || task?.status === "queued"
          ? "active"
          : "idle";
  return `<div class="task-handoff ${escapeHtml(tone)}" aria-label="学习接力">
    ${taskHandoffItems(task).map(([label, value]) => `<span><b>${escapeHtml(label)}</b>${escapeHtml(value)}</span>`).join("")}
  </div>`;
}

function resultMetaChipsHtml(task) {
  if (!task) return "";
  const gates = pipelineAuditItems(task);
  const blocked = gates.find(item => item.state === "fail" || item.state === "warn" || item.state === "wait");
  const windows = visualWindows(task);
  const selected = task.selected_resource || {};
  const reuseEvidence = taskReuseEvidenceItem(task);
  const chips = [
    { state: taskStatusClass(task), label: statusText(task), value: `${task.progress || 0}%` },
    { state: "source", label: sourceText(task), value: selected.kind ? mediaKindText(selected.kind) : task.source_type || "-" },
    reuseEvidence ? { state: "source", label: "复用", value: "已下载媒体" } : null,
    { state: task.media_path ? "pass" : "wait", label: "媒体", value: task.media_path ? "已保存" : "待下载" },
    { state: task.transcript_path ? "pass" : "wait", label: "字幕", value: task.transcript_path ? "已生成" : "待转写" },
    {
      state: task.options?.visual_understanding === false ? "skip" : windows.length ? "pass" : "wait",
      label: "切片",
      value: task.options?.visual_understanding === false ? "关闭" : windows.length ? `${windows.length} 窗口` : "待生成"
    },
    { state: task.note_path ? "pass" : "wait", label: "笔记", value: task.summary_source || (task.note_path ? "完成" : "待总结") },
    { state: hasTaskBundle(task) ? "pass" : "wait", label: "导出", value: hasTaskBundle(task) ? "可导出" : "等待" },
    blocked ? { state: blocked.state, label: "当前门", value: `${blocked.label} · ${blocked.value || blocked.state}` } : null
  ].filter(Boolean);
  const optionLine = optionText(task);
  const notice = pendingRerunNotice?.taskId === task.id ? pendingRerunNotice.message : "";
  return `<div class="result-meta-chips" aria-label="任务阶段摘要">
    ${chips.map(chip => `<span class="${escapeHtml(chip.state)}"><b>${escapeHtml(chip.label)}</b>${escapeHtml(chip.value || "-")}</span>`).join("")}
    ${notice ? `<small class="rerun-notice">${escapeHtml(notice)}</small>` : ""}
    ${optionLine ? `<small>${escapeHtml(optionLine)}</small>` : ""}
  </div>`;
}

function taskAuditMiniHtml(task) {
  const items = pipelineAuditItems(task);
  if (!items.length) return "";
  const blocked = items.find(item => item.state === "fail" || item.state === "warn" || item.state === "wait");
  const passedCount = items.filter(item => item.state === "pass" || item.state === "skip").length;
  return `<div class="task-audit-mini" aria-label="任务检查">
    <div class="task-audit-dots">
      ${items.map(item => `<span class="${escapeHtml(item.state)}" title="${escapeHtml(`${item.label}：${item.value || "-"}；${item.detail || "-"}`)}">
        <b>${escapeHtml(item.label.slice(0, 2))}</b>
      </span>`).join("")}
    </div>
    <small>${escapeHtml(blocked ? `${blocked.label} · ${blocked.value || blocked.state}` : `${passedCount}/${items.length} 已放行`)}</small>
  </div>`;
}

function taskMetaLine(task) {
  return [
    sourceText(task),
    task.phase && task.phase !== "completed" ? task.phase : "",
  ].filter(Boolean).join(" · ");
}

async function taskRecord() {
  if (!selectedTaskId) return null;
  return fetch(apiUrl(`/api/tasks/${selectedTaskId}`)).then(r => r.json()).then(taskFromPayload);
}

function taskFromPayload(payload) {
  const task = payload?.task || null;
  if (task && (payload?.audit || task.audit)) task.audit = payload.audit || task.audit;
  return task;
}

async function noteForTask(taskId) {
  if (!taskId) return "";
  if (lastNoteTaskId === taskId && lastNote) return lastNote;
  const response = await fetch(apiUrl(`/api/tasks/${taskId}/note`));
  if (!response.ok) return "";
  lastNote = await response.text();
  lastNoteTaskId = taskId;
  return lastNote;
}

function clearTaskCaches() {
  lastNote = "";
  lastNoteTaskId = "";
  lastTranscript = null;
  lastTranscriptTaskId = "";
}

async function transcriptForTask(task) {
  if (!task?.id || !task.transcript_path) return null;
  if (lastTranscriptTaskId === task.id && lastTranscript) return lastTranscript;
  const response = await fetch(apiUrl(`/api/tasks/${task.id}/transcript`));
  if (!response.ok) return null;
  lastTranscript = await response.json();
  lastTranscriptTaskId = task.id;
  return lastTranscript;
}

function taskBrief(task) {
  const selected = task.selected_resource || {};
  const options = task.options || {};
  return `<div class="task-brief">
    <span><b>${escapeHtml(statusText(task))}</b>${escapeHtml(task.phase || "-")} · ${task.progress || 0}%</span>
    <span><b>${escapeHtml(sourceText(task))}</b>${escapeHtml(selected.kind || task.source_type || "-")}</span>
    <span><b>${escapeHtml(options.frame_interval || "-")} 秒切片</b>${escapeHtml(options.grid_columns && options.grid_rows ? `${options.grid_columns}x${options.grid_rows} 视觉窗口` : "未配置视觉窗口")}</span>
    <span><b>${escapeHtml(task.summary_source || asrOptionText(options))}</b>${escapeHtml(task.summary_warning ? "已降级，详见诊断" : `${options.note_style || "study"} · ${options.note_template || "standard"} · ${options.visual_understanding === false ? "无视觉" : "图文"}`)}</span>
  </div>`;
}

function taskStatusClass(task) {
  if (task.status === "success") return "success";
  if (task.status === "failed") return "failed";
  if (task.status === "running" || task.status === "queued") return "running";
  return "idle";
}

function taskExportUrl(task, type) {
  return apiUrl(`/api/tasks/${encodeURIComponent(task.id)}/exports/${type}`);
}

function taskMediaPreviewUrl(task) {
  if (!task?.id || !task.media_path) return "";
  return apiUrl(`/api/tasks/${encodeURIComponent(task.id)}/media`);
}

function taskRerunUrl(taskId) {
  return apiUrl(`/api/tasks/${encodeURIComponent(taskId)}/rerun-from-media`);
}

function hasTaskBundle(task) {
  if (!task) return false;
  return Boolean(
    task.note_path ||
    task.subtitle_path ||
    task.media_path ||
    task.status === "failed" ||
    task.download_attempts?.length ||
    visualWindows(task).length
  );
}

function hasVisualWindowExport(task) {
  return Boolean(task?.visual_windows?.length || task?.frame_grids?.length);
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

function hasTaskAudit(task) {
  return Boolean(task?.id && (hasTaskBundle(task) || hasTaskDiagnostics(task) || task.source_type || task.status));
}

function canContinueFromDownloadedMedia(task) {
  const finished = task?.status === "success" || task?.status === "failed";
  return Boolean(task?.id && finished && task.media_path && !task.note_path);
}

function downloadOnlyEmptyNoteHtml(task) {
  const hasSubtitle = Boolean(task?.subtitle_path || task?.transcript_path);
  const title = hasSubtitle ? "视频和字幕已直取到本地" : "视频已直取到本地";
  const detail = hasSubtitle
    ? "已保存字幕/转写，可先导出字幕核对，也可以继续进入抽帧、视觉窗口和图文笔记流程；不会录制页面。"
    : "可以先导出 media.mp4 核对，也可以继续进入转写、抽帧、视觉窗口和图文笔记流程；不会录制页面。";
  const actions = [
    task?.subtitle_path ? `<a href="${escapeHtml(taskExportUrl(task, "subtitles"))}">导出字幕</a>` : "",
    task?.media_path ? `<a href="${escapeHtml(taskExportUrl(task, "media"))}">导出 media.mp4</a>` : "",
    canContinueFromDownloadedMedia(task) ? `<button type="button" data-rerun-from-media="${escapeHtml(task.id)}">继续切片总结</button>` : ""
  ].filter(Boolean).join("");
  return `<section class="download-only-callout note-empty-continue ${hasSubtitle ? "subtitle-ready" : ""}">
    <strong>${escapeHtml(title)}</strong>
    <span>${escapeHtml(detail)}</span>
    ${actions ? `<div class="download-only-actions">${actions}</div>` : ""}
  </section>`;
}

function updateContinueFromMediaAction(task) {
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
  const shownWindows = validWindows.slice(0, 8);
  const missingSet = new Set(missingIds);
  const omittedSet = new Set(omittedIds);
  const lane = shownWindows.length
    ? `<div class="visual-coverage-lane" aria-label="视觉窗口覆盖">
      ${shownWindows.map(window => {
        const width = Math.max(8, Math.min(100, ((Math.max(1, window.end - window.start) / totalDuration) * 100)));
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
      <span><b>${gridCount || "-"}</b>画面网格</span>
      <span><b>${sentImages}/${visionGridCount || gridCount || 0}</b>送入视觉</span>
      <span><b>${missingIds.length || "-"}</b>缺图窗口</span>
      <span><b>${omittedIds.length || "-"}</b>超限省略</span>
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
    partial: "已生成画面证据，模型链路存在降级",
    index: "已有画面切片，当前笔记未确认使用视觉模型",
    skip: "本任务走文本路线",
    empty: "还没有视觉切片证据"
  }[state];
  const badge = {
    strong: "已接入视觉模型",
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
      ${hasTaskBundle(task) ? `<a href="${escapeHtml(taskExportUrl(task, "manifest"))}">导出清单</a>` : ""}
      ${hasTaskBundle(task) ? `<a href="${escapeHtml(taskExportUrl(task, "bundle"))}">导出资料包</a>` : ""}
    </div>
  </section>`;
}

function auditGateState(task, passed) {
  if (passed) return "pass";
  if (task?.status === "failed") return "fail";
  if (task?.status === "success") return "warn";
  return "wait";
}

function mergeBackendAuditItems(task, items) {
  const gates = Array.isArray(task?.audit?.gates) ? task.audit.gates : [];
  if (!gates.length) return items;
  const byKey = new Map(gates.map(gate => [gate.key, gate]));
  return items.map(item => {
    const gate = byKey.get(item.key);
    if (!gate) return item;
    return {
      ...item,
      state: gate.state || item.state,
      value: gate.value || item.value,
      detail: gate.detail || item.detail
    };
  });
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

  const sourceState = auditGateState(task, hasSelectedRoute || attempts.length || hasMedia || hasNote);
  const mediaState = isPageText ? "skip" : auditGateState(task, hasMedia);
  const transcriptState = isPageText && hasNote ? "pass" : auditGateState(task, hasTranscript);
  const visualState = visualDisabled ? "skip" : auditGateState(task, hasVisuals);
  const summaryState = auditGateState(task, hasNote);

  const items = [
    {
      key: "source",
      label: "来源检查",
      state: sourceState,
      value: sourceState === "pass" ? (resourceSourceText(selected) || sourceText(task)) : task?.error_code || "待捕获",
      detail: hasSelectedRoute
        ? [selected.kind || task?.source_type, selected.playback_match ? playbackText(selected.playback_match) : "", selected.resolved_url ? "最终 URL 已记录" : ""].filter(Boolean).join(" · ")
        : (attempts.length ? `${attempts.length} 次候选尝试` : "等待扩展/链接/本地入口提供来源")
    },
    {
      key: "media",
      label: "媒体检查",
      state: mediaState,
      value: mediaState === "skip" ? "文本路线" : hasMedia ? "media.mp4" : task?.error_code || "待下载",
      detail: hasMedia
        ? "已保存到本地，可导出或复用继续总结"
        : (attempts.length ? `${attempts.length} 次下载尝试` : "等待 yt-dlp、直连或 ffmpeg 合并")
    },
    {
      key: "transcript",
      label: "字幕检查",
      state: transcriptState,
      value: hasTranscript ? "字幕已生成" : isPageText && hasNote ? "页面文本/浏览器字幕" : task?.phase === "transcribing" ? "转写中" : "待转写",
      detail: hasTranscript
        ? "时间轴可在字幕页查看"
        : (isPageText ? `${diag.browser_subtitle_count ?? 0} 条浏览器字幕 · ${diag.combined_text_char_count ?? 0} 字` : task?.summary_warning || `字幕优先，${asrOptionText(task?.options || {})} 兜底`)
    },
    {
      key: "visual",
      label: "切片检查",
      state: visualState,
      value: visualDisabled ? "未启用" : hasVisuals ? `${windows.length || diag.frame_grid_count || task?.frame_grids?.length} 个窗口` : task?.phase === "extracting_frames" ? "抽帧中" : "待切片",
      detail: visualDisabled
        ? "当前任务不走视觉窗口"
        : hasVisuals
          ? `${diag.vision_image_count ?? windows.filter(window => safeNoteMediaUrl(window.grid_url)).length}/${diag.vision_grid_count ?? (windows.length || 0)} 送入视觉`
          : "等待 ffmpeg 抽帧生成网格"
    },
    {
      key: "summary",
      label: "总结检查",
      state: summaryState,
      value: hasNote ? (task?.summary_source || "笔记完成") : task?.phase === "summarizing" ? "总结中" : task?.error_code || "待总结",
      detail: hasNote
        ? (task?.summary_warning || `${task?.options?.note_style || "study"} · ${task?.options?.note_template || "standard"} · ${task?.options?.summary_depth || "standard"}`)
        : "等待字幕与视觉窗口汇总"
    }
  ];
  return mergeBackendAuditItems(task, items);
}

function pipelineAuditActionHtml(task, item) {
  if (!task || !item) return "";
  const actions = [];
  const state = String(item.state || "");
  const blocked = state === "fail" || state === "warn";

  if (item.key === "media") {
    if (canContinueFromDownloadedMedia(task)) {
      actions.push(`<button type="button" data-rerun-from-media="${escapeHtml(task.id)}">继续总结</button>`);
    } else if (task.media_path) {
      actions.push(`<button type="button" data-switch-result-tab="diagnostics">看证据</button>`);
    } else if (blocked || task.status === "failed") {
      actions.push(`<button type="button" data-switch-result-tab="diagnostics">看失败原因</button>`);
      actions.push(`<button type="button" data-recovery-source="local">本地兜底</button>`);
    }
  } else if (item.key === "transcript") {
    if (task.transcript_path) {
      actions.push(`<button type="button" data-switch-result-tab="transcript">核对转写</button>`);
    } else if (canContinueFromDownloadedMedia(task)) {
      actions.push(`<button type="button" data-rerun-from-media="${escapeHtml(task.id)}">开始转写</button>`);
    } else if (blocked || task.status === "failed") {
      actions.push(`<button type="button" data-switch-result-tab="diagnostics">看诊断</button>`);
    }
  } else if (item.key === "visual") {
    if (visualWindows(task).length || task.frame_grids?.length) {
      actions.push(`<button type="button" data-switch-result-tab="frames">看切片</button>`);
    } else if (blocked || task.status === "failed") {
      actions.push(`<button type="button" data-switch-result-tab="diagnostics">看诊断</button>`);
    }
  } else if (item.key === "summary") {
    if (task.note_path) {
      actions.push(`<button type="button" data-switch-result-tab="note">读笔记</button>`);
    } else if (blocked || task.status === "failed") {
      actions.push(`<button type="button" data-switch-result-tab="diagnostics">看诊断</button>`);
    }
  } else if (item.key === "source" && (blocked || task.status === "failed")) {
    actions.push(`<button type="button" data-switch-result-tab="diagnostics">看来源证据</button>`);
    actions.push(`<button type="button" data-recovery-source="local">本地兜底</button>`);
  }

  if (!actions.length) return "";
  return `<div class="pipeline-audit-actions">${actions.join("")}</div>`;
}

function pipelineAuditHtml(task) {
  const items = pipelineAuditItems(task);
  return `<section class="pipeline-audit" aria-label="阶段检查">
    <header>
      <span>阶段检查</span>
      <strong>${items.filter(item => item.state === "pass" || item.state === "skip").length}/${items.length} 已放行</strong>
    </header>
    <div class="pipeline-audit-grid">
      ${items.map(item => `<article class="${escapeHtml(item.state)}">
        <b>${escapeHtml(item.label)}</b>
        <strong>${escapeHtml(item.value || "-")}</strong>
        <small>${escapeHtml(item.detail || "-")}</small>
        ${pipelineAuditActionHtml(task, item)}
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
  const recoveryPrimary = primaryRecoveryAction(task);

  if (recoveryPrimary) {
    tone = recoveryDecisionTone(task);
    title = recoveryPrimary.label || "按推荐动作继续";
    detail = task.recovery?.diagnosis || recoveryPrimary.detail || detail;
    actions = [
      recoveryActionButtonHtml(recoveryPrimary, task),
      hasTaskAudit(task) ? `<a href="${escapeHtml(taskExportUrl(task, "audit"))}">导出审计</a>` : ""
    ];
  } else if (canContinueFromDownloadedMedia(task)) {
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
      `<button type="button" data-recovery-source="local">改用本地视频</button>`
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
    detail = "媒体已保存到本地，下一步会优先使用平台/内嵌字幕，没有字幕时再进入 ASR。";
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
    detail = "任务会按下载、转写、切片、总结顺序推进；阶段检查会显示当前卡点。";
    actions = [`<button type="button" data-switch-result-tab="diagnostics">查看阶段检查</button>`];
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
  const title = displayTaskTitle(task, "media");
  return `<section class="media-preview-card" aria-label="本地视频核对">
    <div class="media-preview-copy">
      <span>本地视频核对</span>
      <strong>${escapeHtml(title)}</strong>
      <small>${escapeHtml(task.media_path || "")}</small>
    </div>
    <video controls preload="metadata" src="${escapeHtml(url)}" data-learning-video></video>
    <div class="media-preview-actions">
      <span>点击字幕或视觉窗口时间可回看对应画面</span>
      <a href="${escapeHtml(taskExportUrl(task, "media"))}">导出 media.mp4</a>
      ${canContinueFromDownloadedMedia(task) ? `<button type="button" data-rerun-from-media="${escapeHtml(task.id)}">继续切片总结</button>` : ""}
    </div>
  </section>`;
}

function mediaSeekDockHtml(task) {
  if (!task?.media_path) return "";
  return `<section class="media-seek-dock" aria-label="本地视频回看">
    ${mediaPreviewHtml(task)}
  </section>`;
}

function taskCommandCenterItemState(task, key) {
  const windows = visualWindows(task || {});
  if (!task) return "wait";
  if (task.status === "failed" && ["source", "media"].includes(key) && !task.media_path) return "fail";
  if (key === "source") return (task.selected_resource?.url || task.download_attempts?.length || task.media_path) ? "pass" : "wait";
  if (key === "transcript") return task.transcript_path || task.source_type === "page_text" ? "pass" : task.phase === "transcribing" ? "active" : "wait";
  if (key === "visual") {
    if (task.options?.visual_understanding === false || task.source_type === "page_text") return "skip";
    return windows.length || task.frame_grids?.length ? "pass" : task.phase === "extracting_frames" ? "active" : "wait";
  }
  if (key === "note") return task.note_path ? "pass" : task.phase === "summarizing" ? "active" : "wait";
  return "wait";
}

function nextCommandCenterText(task, items) {
  if (task.status === "failed") {
    return {
      title: "先看来源证据和失败原因",
      detail: task.error_detail || task.error_code || "确认是登录态、签名、DRM 还是无可直取资源。"
    };
  }
  if (canContinueFromDownloadedMedia(task)) {
    return {
      title: "视频已保存到本地，可以继续切片总结",
      detail: "复用 media.mp4 进入转写、抽帧、视觉窗口和图文笔记。"
    };
  }
  const waiting = items.find(item => !["pass", "skip"].includes(taskCommandCenterItemState(task, item.key)));
  if (waiting) {
    return {
      title: `${waiting.label}正在推进`,
      detail: "任务会按来源、媒体、字幕、切片、总结顺序流转。"
    };
  }
  return {
    title: "笔记和资料包已就绪",
    detail: "可以阅读笔记、核对字幕/画面，或导出完整学习资料包。"
  };
}

function taskCommandCenter(task) {
  if (!task) return "";
  const windows = visualWindows(task);
  const selected = task.selected_resource || {};
  const attempts = task.download_attempts || [];
  const sourceDetail = selected.audio_url
    ? `音视频合并 · ${compactUrl(selected.audio_url, 52)}`
    : selected.playback_match ? playbackText(selected.playback_match) : `${attempts.length || 0} 次下载尝试`;
  const items = [
    {
      key: "source",
      label: "来源证据",
      value: mediaKindText(selected.kind) || selected.kind || task.source_type || "-",
      detail: sourceDetail,
      action: hasTaskDiagnostics(task) ? `<button type="button" data-switch-result-tab="diagnostics">看证据</button>` : ""
    },
    {
      key: "transcript",
      label: "字幕转写",
      value: task.transcript_path ? "已生成" : task.source_type === "page_text" ? "页面文本" : task.phase === "transcribing" ? "转写中" : "等待",
      detail: task.transcript_path ? asrOptionText(task.options || {}) : "平台字幕优先，ASR 兜底",
      action: task.transcript_path ? `<button type="button" data-switch-result-tab="transcript">核对字幕</button>` : ""
    },
    {
      key: "visual",
      label: "画面切片",
      value: windows.length ? `${windows.length} 窗口` : task.options?.visual_understanding === false ? "已关闭" : "等待",
      detail: windows.length ? `${fmt(windows[0]?.start || 0)} - ${fmt(windows[windows.length - 1]?.end || 0)}` : "抽帧后按视觉窗口对齐",
      action: windows.length ? `<button type="button" data-switch-result-tab="frames">看切片</button>` : ""
    },
    {
      key: "note",
      label: "笔记导出",
      value: task.note_path ? (task.summary_source || "笔记完成") : task.phase === "summarizing" ? "总结中" : canContinueFromDownloadedMedia(task) ? "可继续" : "等待",
      detail: task.note_path ? `${task.options?.note_style || "study"} · ${task.options?.note_template || "standard"}` : "生成 Markdown 和资料包",
      action: task.note_path
        ? `<button type="button" data-switch-result-tab="note">读笔记</button>${hasTaskBundle(task) ? `<button type="button" data-export="bundle">资料包</button>` : ""}`
        : canContinueFromDownloadedMedia(task) ? `<button type="button" data-rerun-from-media="${escapeHtml(task.id)}">继续总结</button>` : ""
    }
  ];
  const next = nextCommandCenterText(task, items);
  return `<section class="task-command-center" aria-label="BiliNote 式任务导航">
    <header>
      <div>
        <span>学习任务导航</span>
        <strong>${escapeHtml(next.title)}</strong>
      </div>
      <small>${escapeHtml(next.detail)}</small>
    </header>
    <div class="task-command-grid">
      ${items.map(item => `<article class="${escapeHtml(taskCommandCenterItemState(task, item.key))}">
        <b>${escapeHtml(item.label)}</b>
        <strong>${escapeHtml(item.value)}</strong>
        <small>${escapeHtml(item.detail)}</small>
        ${item.action ? `<div>${item.action}</div>` : ""}
      </article>`).join("")}
    </div>
  </section>`;
}

function directExtractionRouteLabel(route) {
  const labels = {
    download_only_to_local_media: "只下载到本地",
    browser_candidate_to_local_media: "浏览器候选直取",
    local_video_pipeline: "本地视频管线",
    page_text_only: "页面文本兜底",
    resolver_to_local_media: "解析器落地",
    attempted_direct_extraction: "已尝试直取",
    pending_or_no_media: "等待媒体"
  };
  return labels[route] || route || "未知路线";
}

function directExtractionBoundaryText(boundary) {
  const labels = {
    normal_accessible_media_only: "仅可访问媒体",
    drm_or_encrypted_not_bypassed: "DRM 不绕过",
    mediastream_not_recorded: "MediaStream 不录制",
    unresolved_blob_or_fragment_not_recorded: "blob/分片不录制"
  };
  return labels[boundary] || boundary || "边界正常";
}

function directExtractionSafeHeaders(direct) {
  const names = direct?.selected_candidate?.safe_request_header_names;
  if (!Array.isArray(names)) return "";
  return names
    .map(name => String(name || "").trim())
    .filter(name => name && !/cookie|authorization/i.test(name))
    .sort()
    .join(", ");
}

function directExtractionEvidenceItems(task) {
  const direct = task?.direct_extraction;
  if (!direct) return [];
  const selected = direct.selected_candidate || {};
  const browser = direct.browser_context || {};
  const download = direct.download || {};
  const processing = direct.processing || {};
  const safeHeaders = directExtractionSafeHeaders(direct);
  const contextDetail = [
    selected.source ? `source ${selected.source}` : "",
    selected.playback_match ? playbackText(selected.playback_match) : "",
    browser.active_source_type ? `active ${browser.active_source_type}` : "",
    Number.isFinite(browser.browser_subtitle_count) ? `${browser.browser_subtitle_count} 字幕` : "",
    Number.isFinite(browser.cookie_count) ? `${browser.cookie_count} cookie` : "",
    Number.isFinite(browser.cookie_domain_count) ? `${browser.cookie_domain_count} cookie 域` : "",
    Number.isFinite(browser.partitioned_cookie_count) && browser.partitioned_cookie_count > 0 ? `${browser.partitioned_cookie_count} 分区 cookie` : "",
    Number.isFinite(browser.partition_key_count) && browser.partition_key_count > 0 ? `${browser.partition_key_count} partition key` : "",
    safeHeaders ? `headers ${safeHeaders}` : ""
  ].filter(Boolean).join(" · ");
  const strategyOrder = Array.isArray(download.strategy_order)
    ? download.strategy_order.map(item => String(item || "").trim()).filter(Boolean).slice(0, 4).join(" → ")
    : "";
  const successCount = Number(download.successful_attempt_count || 0);
  const failedCount = Number(download.failed_attempt_count || 0);
  const processingDetail = [
    processing.transcript_ready ? "转写已就绪" : "转写待生成",
    Number.isFinite(processing.frame_grid_count) ? `${processing.frame_grid_count} 网格` : "",
    Number.isFinite(processing.visual_window_count) ? `${processing.visual_window_count} 视觉窗` : "",
    processing.note_ready ? "笔记已就绪" : "",
    directExtractionBoundaryText(direct.boundary)
  ].filter(Boolean).join(" · ");

  return [
    {
      state: direct.no_tab_recording === false ? "warn" : "pass",
      label: "直取路线",
      value: directExtractionRouteLabel(direct.route),
      detail: [
        direct.no_tab_recording === false ? "录制状态未知" : "不录制标签页",
        direct.no_drm_bypass === false ? "DRM 边界未知" : "不绕过 DRM"
      ].join(" · ")
    },
    {
      state: direct.media_landed ? "pass" : "warn",
      label: "媒体保存",
      value: direct.media_landed ? "已保存 media.mp4" : "未保存",
      detail: direct.media_reusable ? "可复用本地视频" : directExtractionBoundaryText(direct.boundary)
    },
    {
      state: contextDetail ? "active" : "skip",
      label: "浏览器上下文",
      value: selected.kind ? `${selected.kind} · ${selected.source || "候选"}` : (browser.active_source_type ? `active ${browser.active_source_type}` : "无候选"),
      detail: contextDetail || "Cookie 仅任务启动时同步"
    },
    {
      state: successCount ? "pass" : failedCount ? "fail" : "wait",
      label: "下载尝试",
      value: `成功 ${successCount} / 失败 ${failedCount}`,
      detail: strategyOrder || "等待下载器结果"
    },
    {
      state: processing.note_ready || processing.transcript_ready || processing.download_only ? "pass" : "wait",
      label: "处理状态",
      value: processing.download_only ? "只下载模式" : processing.note_ready ? "已生成笔记" : processing.transcript_ready ? "已转写" : "待处理",
      detail: processingDetail || directExtractionBoundaryText(direct.boundary)
    }
  ];
}

function directExtractionEvidenceHtml(task) {
  const items = directExtractionEvidenceItems(task);
  if (!items.length) return "";
  return `<section class="direct-extraction-evidence" aria-label="直取证据">
    <header>
      <span>直取证据</span>
      <strong>非录制下载路线</strong>
    </header>
    <div class="direct-extraction-grid">
      ${items.map(item => `<article class="${escapeHtml(item.state)}">
        <b>${escapeHtml(item.label)}</b>
        <strong>${escapeHtml(item.value)}</strong>
        <small>${escapeHtml(item.detail)}</small>
      </article>`).join("")}
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
  const downloadOnly = hasMedia && !hasNote && task.status === "success";
  const canContinueMedia = canContinueFromDownloadedMedia(task);
  const fallbackNote = task.status === "failed" && hasNote;
  const failedWithoutFallback = task.status === "failed" && !fallbackNote;
  const resourceLine = [
    sourceText(task),
    mediaKindText(selected.kind) || selected.kind || task.source_type || "",
    selected.audio_url ? "伴随音频流" : "",
    resourceSourceText(selected),
    selected.playback_match ? playbackText(selected.playback_match) : "",
    selected.resolved_url ? "已跟踪最终 URL" : "",
    contentDispositionHint(selected.headers?.["content-disposition"]),
    selected.content_length ? fmtBytes(selected.content_length) : ""
  ].filter(Boolean).join(" · ");
  const actionLinks = [
    canContinueMedia ? `<button type="button" data-rerun-from-media="${escapeHtml(task.id)}">生成完整笔记</button>` : "",
    hasNote ? `<a href="${escapeHtml(taskExportUrl(task, "markdown"))}">导出 Markdown</a>` : "",
    hasMedia ? `<a href="${escapeHtml(taskExportUrl(task, "media"))}">导出本地视频</a>` : "",
    hasTaskAudit(task) ? `<a href="${escapeHtml(taskExportUrl(task, "audit"))}">导出审计</a>` : "",
    hasTaskDiagnostics(task) ? `<a href="${escapeHtml(taskExportUrl(task, "diagnostics"))}">导出诊断</a>` : "",
    hasBundle ? `<a href="${escapeHtml(taskExportUrl(task, "manifest"))}">导出清单</a>` : "",
    hasBundle ? `<a href="${escapeHtml(taskExportUrl(task, "bundle"))}">导出资料包</a>` : ""
  ].filter(Boolean).join("");

  return `<section class="task-overview status-${statusClass}">
    <div class="task-overview-main">
      <span class="eyeless">当前学习任务</span>
      <strong>${escapeHtml(displayTaskTitle(task))}</strong>
      <small>${escapeHtml(resourceLine || statusText(task))}</small>
      ${stageRail(task)}
    </div>
    <div class="task-overview-actions">
      ${actionLinks || `<span>${escapeHtml(statusText(task))}</span>`}
    </div>
    <div class="task-overview-metrics">
      <span><b>${escapeHtml(statusText(task))}</b>${escapeHtml(task.phase || "-")} · ${task.progress || 0}%</span>
      <span><b>${escapeHtml(options.frame_interval || "-")} 秒切片</b>${escapeHtml(options.grid_columns && options.grid_rows ? `${options.grid_columns}x${options.grid_rows} 视觉窗口` : "未配置视觉窗口")}</span>
      <span><b>${escapeHtml(task.summary_source || asrOptionText(options))}</b>${escapeHtml(task.summary_warning ? "已降级，查看诊断" : `${options.note_style || "study"} · ${options.note_template || "standard"} · ${options.visual_understanding === false ? "无视觉" : "图文"}`)}</span>
      <span><b>${windows.length || "-"}</b>${windows.length ? "画面窗口" : "等待画面切片"}</span>
    </div>
    ${taskBrowserEvidenceHtml(task)}
    ${directExtractionEvidenceHtml(task)}
    ${pipelineAuditHtml(task)}
    ${recoveryDecisionHtml(task)}
    ${taskCommandCenter(task)}
    ${nextStepHtml(task)}
    ${mediaPreviewHtml(task)}
    ${visualCoverageHtml(task)}
    ${taskRouteEvidenceHtml(task)}
    ${downloadOnly ? `<div class="download-only-callout">
      <strong>已完成直取下载</strong>
      <span>这个任务按“只下载本地”运行，未进入转写、切片和总结。可以先导出 media.mp4，或直接复用这个本地视频生成完整笔记。</span>
    </div>` : ""}
    ${fallbackNote ? `<div class="download-only-callout fallback-note-callout">
      <strong>已生成兜底笔记</strong>
      <span>视频直取失败，但已用页面文本/浏览器字幕生成可读笔记；诊断仍保留原始下载错误和资源证据。</span>
    </div>` : ""}
    ${failedWithoutFallback ? `<div class="download-only-callout failed-media-callout">
      <strong>${escapeHtml(task.error_code || "任务失败")}</strong>
      <span>${escapeHtml(task.error_detail || "请查看诊断里的下载尝试和处理日志。")}</span>
    </div>` : ""}
  </section>`;
}

function taskBrowserEvidenceHtml(task) {
  if (!task || task.source_type !== "current_page") return "";
  const selected = task.selected_resource || {};
  const activeText = activeVideoText(task.active_video);
  const target = taskResolvedTargetText(task, 108) || selected.url || "";
  const requestContext = [
    requestHeaderNames(selected),
    selected.frame_url ? `frame ${compactUrl(selected.frame_url, 58)}` : "",
    mseAppendEvidence(selected),
    selected.blob_url ? "blob 已映射" : ""
  ].filter(item => item && item !== "-").join(" · ");
  if (activeText === "-" && !target && !requestContext) return "";
  return `<section class="task-browser-evidence" aria-label="浏览器播放证据">
    <header>
      <span>浏览器播放证据</span>
      <strong>非录制直取</strong>
    </header>
    <div>
      <article>
        <b>播放状态</b>
        <span>${escapeHtml(activeText)}</span>
      </article>
      <article>
        <b>直取目标</b>
        <span>${escapeHtml(target || "等待媒体候选")}</span>
      </article>
      <article>
        <b>请求上下文</b>
        <span>${escapeHtml(requestContext || "Cookie 仅任务启动时同步")}</span>
      </article>
    </div>
  </section>`;
}

function lastDownloadAttempt(task) {
  const attempts = task?.download_attempts || [];
  return attempts.length ? attempts[attempts.length - 1] : null;
}

function taskReuseEvidenceItem(task) {
  const reuse = task?.reuse || {};
  const sourceTaskId = String(task?.source_task_id || reuse.source_task_id || "").trim();
  const sourceMediaPath = String(task?.source_media_path || reuse.source_media_path || reuse.media_path_recorded || "").trim();
  if (!sourceTaskId && !sourceMediaPath) return null;
  return {
    label: "复用来源",
    value: sourceTaskId ? `来自 ${sourceTaskId}` : "已复用本地媒体",
    detail: sourceMediaPath ? compactUrl(sourceMediaPath, 86) : "原直取任务媒体"
  };
}

function rerunFromMediaNotice(sourceTaskId, newTaskId, task = null) {
  const sourceId = String(sourceTaskId || task?.source_task_id || task?.reuse?.source_task_id || "").trim();
  const targetId = String(newTaskId || task?.id || "").trim();
  const sourceText = sourceId ? `从任务 ${sourceId} 复用已下载 media.mp4` : "复用已下载 media.mp4";
  const targetText = targetId ? `，新完整笔记任务 ${targetId}` : "";
  return `${sourceText}${targetText}，正在进入转写、抽帧、视觉窗口和图文总结；不会录制页面。`;
}

function taskRouteEvidenceItems(task) {
  const selected = task?.selected_resource || {};
  const attempts = task?.download_attempts || [];
  const lastAttempt = lastDownloadAttempt(task);
  const headers = requestHeaderNames(selected);
  const diag = task?.summary_diagnostics || {};
  const reuseEvidence = taskReuseEvidenceItem(task);
  const resolvedTarget = taskResolvedTargetText(task, 86);
  const downloadDetail = resolvedTarget
    ? (lastAttempt ? `${resolvedTarget} · ${lastAttempt.code || lastAttempt.status || lastAttempt.strategy || "-"}` : resolvedTarget)
    : (lastAttempt ? `${lastAttempt.strategy || "-"} · ${lastAttempt.code || lastAttempt.status || "-"}` : (task.error_code || task.phase || "-"));
  const summaryText = summaryDiagnosticText(task);
  const summaryValue = task.summary_source || (diag.used_page_text_fallback ? "页面文本兜底" : task.note_path ? "已有笔记" : "待生成");
  const summaryDetail = summaryText === "-"
    ? (task.summary_warning || (task.note_path ? "未记录总结诊断" : "等待图文总结"))
    : summaryText;
  const items = [
    {
      label: "直取来源",
      value: selected.kind ? `${selected.kind} · ${resourceSourceText(selected) || selected.source || "候选资源"}` : sourceText(task),
      detail: selected.playback_match ? playbackText(selected.playback_match) : (selected.label || "页面/本地任务")
    },
    {
      label: "下载路线",
      value: attempts.length ? `${attempts.length} 次尝试` : task.media_path ? "已有本地媒体" : "等待下载",
      detail: downloadDetail
    },
    ...(reuseEvidence ? [reuseEvidence] : []),
    {
      label: "浏览器证据",
      value: headers !== "-" ? headers : selected.status_code ? `HTTP ${selected.status_code}` : "无可复用请求头",
      detail: [
        selected.mime || "",
        selected.content_length ? fmtBytes(selected.content_length) : "",
        selected.request_type || "",
        mseAppendEvidence(selected)
      ].filter(Boolean).join(" · ") || "Cookie 仅任务启动时同步"
    },
    {
      label: "总结证据",
      value: summaryValue,
      detail: summaryDetail
    }
  ];
  return items.filter(item => item.value || item.detail);
}

function taskRouteEvidenceHtml(task) {
  const items = taskRouteEvidenceItems(task);
  if (!items.length) return "";
  return `<div class="route-evidence-strip" aria-label="直取和总结证据">
    ${items.map(item => `<span>
      <b>${escapeHtml(item.label)}</b>
      <strong>${escapeHtml(item.value || "-")}</strong>
      <small>${escapeHtml(item.detail || "-")}</small>
    </span>`).join("")}
  </div>`;
}

async function rerunTaskFromMedia(taskId) {
  if (!taskId) return;
  els.resultMeta.textContent = "正在复用已下载视频，并按当前切片、ASR 和视觉模型参数创建完整笔记任务...";
  const response = await fetch(taskRerunUrl(taskId), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(readOptions())
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    els.resultMeta.textContent = detail?.detail?.message || detail?.detail || "无法复用已下载视频。";
    return;
  }
  const data = await response.json();
  pendingRerunNotice = {
    taskId: data.task_id,
    message: rerunFromMediaNotice(data.source_task_id || taskId, data.task_id, data.task)
  };
  selectTask(data.task_id);
  selectedTab = "note";
  renderResultTabState();
  syncSelectedTaskUrl(selectedTaskId);
  await loadTasks();
  focusResultPanelOnMobile();
}

async function copyBackendUrl(feedbackButton = els.copyBackendButton) {
  const url = API || (isBackendSameOrigin() ? window.location.origin : DEFAULT_BACKEND_ORIGIN);
  try {
    await navigator.clipboard.writeText(url);
  } catch {
    const input = document.createElement("input");
    input.value = url;
    input.setAttribute("readonly", "");
    input.style.position = "fixed";
    input.style.opacity = "0";
    document.body.appendChild(input);
    input.select();
    document.execCommand("copy");
    input.remove();
  }
  if (els.browserBridgeStatus) {
    els.browserBridgeStatus.textContent = `后端地址已复制：${url}`;
  }
  if (feedbackButton) {
    const previous = feedbackButton.innerHTML;
    feedbackButton.textContent = "已复制";
    setTimeout(() => {
      feedbackButton.innerHTML = previous;
    }, 1400);
  }
  return url;
}

function bindTaskOverviewActions() {
  document.querySelectorAll("[data-rerun-from-media]").forEach(button => {
    button.onclick = () => rerunTaskFromMedia(button.dataset.rerunFromMedia);
  });
  document.querySelectorAll("[data-switch-result-tab]").forEach(button => {
    button.onclick = () => switchResultTab(button.dataset.switchResultTab);
  });
  document.querySelectorAll("[data-media-seek-time]").forEach(button => {
    button.onclick = () => seekLearningVideo(button.dataset.mediaSeekTime, button);
  });
  document.querySelectorAll("[data-recovery-source]").forEach(button => {
    button.onclick = () => {
      setSource(button.dataset.recoverySource);
      document.querySelector(".workspace-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
    };
  });
}

function switchResultTab(tabName) {
  const normalizedTab = normalizeResultTabName(tabName);
  if (!RESULT_TAB_NAMES.has(normalizedTab) || selectedTab === normalizedTab) return;
  selectedTab = normalizedTab;
  renderResultTabState();
  syncSelectedTaskUrl(selectedTaskId);
  renderDetail();
}

function noteHeadingStats(markdown) {
  if (!markdown) return { total: 0, h1: 0, h2: 0, h3: 0 };
  const stats = { total: 0, h1: 0, h2: 0, h3: 0 };
  const inFence = { value: false };
  markdown.split(/\r?\n/).forEach(line => {
    if (/^\s*```/.test(line)) {
      inFence.value = !inFence.value;
      return;
    }
    if (inFence.value) return;
    const match = line.match(/^(#{1,3})\s+(.+)/);
    if (!match) return;
    stats.total += 1;
    stats[`h${match[1].length}`] += 1;
  });
  return stats;
}

function notePrimaryTitle(markdown, task) {
  const inFence = { value: false };
  for (const line of String(markdown || "").split(/\r?\n/)) {
    if (/^\s*```/.test(line)) {
      inFence.value = !inFence.value;
      continue;
    }
    if (inFence.value) continue;
    const match = line.match(/^\s*#{1,2}\s+(.+)/);
    if (match) {
      const text = plainHeadingText(match[1]);
      if (text) return text;
    }
  }
  return task?.title || task?.id || "LearnNote";
}

function noteHeroBanner(markdown, task) {
  if (!task) return "";
  const windows = visualWindows(task);
  const headings = noteHeadingStats(markdown);
  const selected = task.selected_resource || {};
  const firstWindow = windows.find(window => safeNoteMediaUrl(window.grid_url)) || windows[0] || null;
  const image = safeNoteMediaUrl(firstWindow?.grid_url || "");
  const sourceUrl = safeExternalUrl(task.page_url || selected.url || "");
  const sourceLabel = [
    sourceText(task),
    selected.playback_match ? playbackText(selected.playback_match) : "",
    selected.kind ? mediaKindText(selected.kind) : "",
    task.summary_source || ""
  ].filter(Boolean).join(" · ");
  const timeline = windows.length && firstWindow
    ? `${fmt(windows[0].start || 0)} - ${fmt(windows[windows.length - 1].end || 0)}`
    : task.media_path ? "media.mp4 已保存" : "等待切片";
  const metrics = [
    { label: "章节", value: headings.total ? `${headings.total}` : "-" },
    { label: "字幕", value: task.transcript_path ? "已生成" : task.browser_subtitles?.length ? `${task.browser_subtitles.length} 条` : "-" },
    { label: "画面", value: windows.length ? `${windows.length} 窗口` : "-" },
    { label: "状态", value: statusText(task) }
  ];
  const actions = [
    task.note_path ? `<a href="${escapeHtml(taskExportUrl(task, "markdown"))}">Markdown</a>` : "",
    task.transcript_path ? `<button type="button" data-switch-result-tab="transcript">字幕</button>` : "",
    windows.length ? `<button type="button" data-switch-result-tab="frames">画面</button>` : "",
    sourceUrl ? `<a href="${escapeHtml(sourceUrl)}" target="_blank" rel="noreferrer">原页面</a>` : "",
    hasTaskBundle(task) ? `<a href="${escapeHtml(taskExportUrl(task, "bundle"))}">资料包</a>` : ""
  ].filter(Boolean).join("");

  return `<section class="note-hero-banner" aria-label="课程笔记资料页">
    <div class="note-hero-media ${image ? "" : "empty"}">
      ${image ? `<img src="${image}" alt="课程画面预览">` : `<span>LN</span>`}
    </div>
    <div class="note-hero-main">
      <span>课程笔记</span>
      <strong>${escapeHtml(notePrimaryTitle(markdown, task))}</strong>
      <small>${escapeHtml(sourceLabel || task.page_url || task.source_type || "-")}</small>
      <div class="note-hero-meta">
        <em>${escapeHtml(timeline)}</em>
        <em>${escapeHtml(optionText(task) || asrOptionText(task.options || {}))}</em>
      </div>
      <div class="note-hero-metrics">
        ${metrics.map(item => `<b><span>${escapeHtml(item.value)}</span>${escapeHtml(item.label)}</b>`).join("")}
      </div>
      ${actions ? `<div class="note-hero-actions">${actions}</div>` : ""}
    </div>
  </section>`;
}

function noteStudyBar(markdown, task) {
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
      action: hasBundle ? `<a href="${escapeHtml(taskExportUrl(task, "manifest"))}">导出清单</a><a href="${escapeHtml(taskExportUrl(task, "bundle"))}">导出资料包</a>` : ""
    }
  ];
  return `<section class="study-map" aria-label="学习笔记导览">
    <div class="study-map-head">
      <div>
        <span>学习导览</span>
        <strong>${escapeHtml(displayTaskTitle(task))}</strong>
      </div>
      <small>${escapeHtml(sourceText(task))} · ${escapeHtml(statusText(task))}</small>
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

function noteExportCtaBar(task) {
  if (!task?.id) return "";
  const primary = [
    task.note_path ? `<a class="primary" href="${escapeHtml(taskExportUrl(task, "markdown"))}">导出 Markdown</a>` : "",
    hasVisualWindowExport(task) ? `<a href="${escapeHtml(taskExportUrl(task, "visual-windows"))}">导出切片索引</a>` : "",
    hasTaskBundle(task) ? `<a href="${escapeHtml(taskExportUrl(task, "bundle"))}">导出资料包</a>` : ""
  ].filter(Boolean);
  const secondary = [
    task.subtitle_path ? `<a href="${escapeHtml(taskExportUrl(task, "subtitles"))}">字幕</a>` : "",
    task.media_path ? `<a href="${escapeHtml(taskExportUrl(task, "media"))}">media.mp4</a>` : "",
    hasTaskDiagnostics(task) ? `<a href="${escapeHtml(taskExportUrl(task, "diagnostics"))}">诊断</a>` : "",
    hasTaskAudit(task) ? `<a href="${escapeHtml(taskExportUrl(task, "audit"))}">审计</a>` : "",
    hasTaskBundle(task) ? `<a href="${escapeHtml(taskExportUrl(task, "manifest"))}">清单</a>` : ""
  ].filter(Boolean);
  if (!primary.length && !secondary.length) return "";
  const windows = visualWindows(task);
  const status = task.note_path ? "ready" : task.media_path ? "partial" : "diagnostic";
  const detail = task.note_path
    ? `Markdown、切片索引和资料包可直接保存；${windows.length ? `${windows.length} 个视觉窗口会写入资料包。` : "当前任务没有视觉窗口。"}`
    : task.media_path
      ? "视频已保存到本地，可先导出媒体或继续切片总结。"
      : "任务未生成完整笔记，但诊断和审计仍可导出。";
  return `<section class="export-cta-bar ${escapeHtml(status)}" aria-label="导出学习成果">
    <div>
      <span>导出阶段</span>
      <strong>拿走学习成果</strong>
      <small>${escapeHtml(detail)}</small>
    </div>
    <nav>
      ${primary.join("")}
      ${secondary.length ? `<span>${secondary.join("")}</span>` : ""}
    </nav>
  </section>`;
}

function visualRail(task, limit = 8) {
  const windows = visualWindows(task);
  if (!windows.length) return "";
  return `<section class="visual-rail" aria-label="画面索引">
    <div class="visual-rail-head">
      <strong>画面索引</strong>
      <span>${windows.length} 个窗口</span>
    </div>
    <div class="visual-rail-list">
      ${windows.slice(0, limit).map(window => `
        <figure>
          <img src="${escapeHtml(window.grid_url)}" alt="${escapeHtml(window.id)} frame grid">
          <figcaption>
            <strong>${escapeHtml(window.id)}</strong>
            <span>${fmt(window.start)} - ${fmt(window.end)} · ${window.frame_count} 帧</span>
            ${window.transcript_excerpt ? `<small>${escapeHtml(window.transcript_excerpt)}</small>` : ""}
          </figcaption>
        </figure>
      `).join("")}
    </div>
  </section>`;
}

function readingProgressRail(markdown, task) {
  const headings = noteHeadingStats(markdown);
  const windows = visualWindows(task || {});
  const hasTranscript = Boolean(task?.transcript_path);
  const hasMedia = Boolean(task?.media_path);
  const hasNote = Boolean(task?.note_path);
  const items = [
    {
      state: hasNote ? "done" : "wait",
      label: "笔记",
      value: headings.total ? `${headings.total} 标题` : hasNote ? "已生成" : "等待",
      detail: headings.h2 ? `${headings.h2} 章节 · ${headings.h3} 小节` : "阅读主笔记"
    },
    {
      state: hasTranscript ? "done" : "wait",
      label: "字幕",
      value: hasTranscript ? "已对齐" : "等待",
      detail: hasTranscript ? "可切到字幕时间轴核对" : asrOptionText(task?.options || {})
    },
    {
      state: windows.length ? "done" : task?.options?.visual_understanding === false ? "skip" : "wait",
      label: "画面",
      value: windows.length ? `${windows.length} 窗口` : task?.options?.visual_understanding === false ? "未启用" : "等待",
      detail: windows.length ? `${fmt(windows[0]?.start || 0)} - ${fmt(windows[windows.length - 1]?.end || 0)}` : "抽帧后在这里预览"
    },
    {
      state: hasTaskBundle(task) ? "done" : hasMedia ? "active" : "wait",
      label: "产物",
      value: hasTaskBundle(task) ? "可导出" : hasMedia ? "media.mp4" : "等待",
      detail: hasMedia ? "本地视频可复用" : "完成后生成资料包"
    }
  ];
  return `<section class="reading-progress-rail" aria-label="学习进度">
    <div class="visual-rail-head">
      <strong>学习进度</strong>
      <span>${escapeHtml(statusText(task || {}))}</span>
    </div>
    <div class="reading-progress-list">
      ${items.map(item => `<div class="${escapeHtml(item.state)}">
        <b>${escapeHtml(item.label)}</b>
        <strong>${escapeHtml(item.value)}</strong>
        <small>${escapeHtml(item.detail)}</small>
      </div>`).join("")}
    </div>
  </section>`;
}

function readingArtifactsRail(task) {
  if (!task?.id) return "";
  const actions = [
    task.note_path ? `<a href="${escapeHtml(taskExportUrl(task, "markdown"))}">Markdown</a>` : "",
    task.subtitle_path ? `<a href="${escapeHtml(taskExportUrl(task, "subtitles"))}">字幕文件</a>` : "",
    task.media_path ? `<a href="${escapeHtml(taskExportUrl(task, "media"))}">media.mp4</a>` : "",
    hasVisualWindowExport(task) ? `<a href="${escapeHtml(taskExportUrl(task, "visual-windows"))}">切片索引</a>` : "",
    hasTaskAudit(task) ? `<a href="${escapeHtml(taskExportUrl(task, "audit"))}">审计</a>` : "",
    hasTaskDiagnostics(task) ? `<a href="${escapeHtml(taskExportUrl(task, "diagnostics"))}">诊断</a>` : "",
    hasTaskBundle(task) ? `<a href="${escapeHtml(taskExportUrl(task, "manifest"))}">清单</a>` : "",
    hasTaskBundle(task) ? `<a href="${escapeHtml(taskExportUrl(task, "bundle"))}">资料包</a>` : ""
  ].filter(Boolean);
  if (!actions.length) return "";
  return `<section class="reading-artifacts-rail" aria-label="导出产物">
    <div class="visual-rail-head">
      <strong>导出产物</strong>
      <span>${actions.length} 项</span>
    </div>
    <div class="reading-artifact-actions">${actions.join("")}</div>
  </section>`;
}

function readingActionsRail(task) {
  if (!task) return "";
  const actions = [
    `<button type="button" data-switch-result-tab="note">读笔记</button>`,
    task.transcript_path ? `<button type="button" data-switch-result-tab="transcript">查字幕</button>` : "",
    hasVisualWindowExport(task) ? `<button type="button" data-switch-result-tab="frames">看画面</button>` : "",
    hasTaskDiagnostics(task) ? `<button type="button" data-switch-result-tab="diagnostics">看诊断</button>` : "",
    canContinueFromDownloadedMedia(task) ? `<button type="button" data-rerun-from-media="${escapeHtml(task.id)}">继续总结</button>` : ""
  ].filter(Boolean);
  return `<section class="reading-actions-rail" aria-label="阅读动作">
    <div class="visual-rail-head">
      <strong>阅读动作</strong>
      <span>${actions.length} 个入口</span>
    </div>
    <div class="reading-action-list">${actions.join("")}</div>
  </section>`;
}

function readingRail(markdown, task) {
  const outline = noteOutline(markdown);
  const visuals = visualRail(task);
  const progress = readingProgressRail(markdown, task);
  const artifacts = readingArtifactsRail(task);
  const actions = readingActionsRail(task);
  const blocks = [progress, outline, visuals, actions, artifacts].filter(Boolean);
  if (!blocks.length) return "";
  return `<aside class="reading-rail" aria-label="笔记阅读导航">${blocks.join("")}</aside>`;
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

function segmentOverlapsWindow(segment, window) {
  const start = Number(segment.start || 0);
  const end = Number(segment.end ?? start);
  return start < Number(window.end || 0) && end >= Number(window.start || 0);
}

function transcriptLines(segments) {
  return segments.map(seg => `<div class="line" data-line-time="${seekTimeValue(seg.start)}">${seekTimeButton(seg.start)}<span>${escapeHtml(seg.text)}</span></div>`).join("");
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

function transcriptTimeline(transcript, task, limit = Infinity) {
  const segments = (transcript?.segments || []).slice(0, limit);
  const windows = visualWindows(task);
  if (!windows.length) {
    return `${transcriptOverview(transcript, task)}<div class="transcript-timeline transcript-timeline-plain">${transcriptLines(segments)}</div>`;
  }

  const used = new Set();
  const cards = windows.map(window => {
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
    return `<section class="transcript-window" data-visual-window="${escapeHtml(window.id || "")}" data-window-start="${seekTimeValue(window.start)}">
      <figure>
        ${window.grid_url ? `<img src="${escapeHtml(window.grid_url)}" alt="${escapeHtml(window.id)} frame grid">` : ""}
        <figcaption>
          <strong>${escapeHtml(window.id)}</strong>
          <span>${fmt(window.start)} - ${fmt(window.end)} · ${window.frame_count || 0} 帧</span>
          ${seekTimeButton(window.start, "window-seek")}
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

function visualStudyCueHtml(window, transcript) {
  const segments = transcript?.segments || [];
  const matched = segments.filter(segment => segmentOverlapsWindow(segment, window)).slice(0, 4);
  if (matched.length) {
    return `<div class="visual-study-cues">
      ${matched.map(segment => `<div>${seekTimeButton(segment.start)}<span>${escapeHtml(segment.text)}</span></div>`).join("")}
    </div>`;
  }
  const excerpt = window.transcript_excerpt || "这个窗口暂无字幕摘录，可切到“字幕”查看完整时间轴。";
  return `<p>${escapeHtml(excerpt)}</p>`;
}

function visualStudyChecklistHtml(window, transcript) {
  const hasCue = Boolean(window.transcript_excerpt) || (transcript?.segments || []).some(segment => segmentOverlapsWindow(segment, window));
  const target = hasCue
    ? "核对截图里的板书、PPT 切换、代码/界面状态是否已被字幕覆盖。"
    : "先从截图判断这一段的主题，重点看标题、公式、代码和演示状态。";
  const action = hasCue
    ? "复述这一窗口的结论，再按画面顺序补齐遗漏步骤。"
    : "补一句本段主题，再和前后窗口串成完整时间线。";
  return `<div class="visual-study-checklist">
    <span>学习动作</span>
    <ul>
      <li>${escapeHtml(target)}</li>
      <li>${escapeHtml(action)}</li>
    </ul>
  </div>`;
}

function visualStudyCheckpointHtml(window, transcript) {
  const segments = (transcript?.segments || [])
    .filter(segment => segmentOverlapsWindow(segment, window))
    .slice(0, 3)
    .map(segment => ({ seconds: Number(segment.start || 0), time: fmt(segment.start), text: String(segment.text || "").replace(/\s+/g, " ").trim() }))
    .filter(item => item.text);
  if (!segments.length && window.transcript_excerpt) {
    segments.push({
      seconds: Number(window.start || 0),
      time: fmt(window.start || 0),
      text: String(window.transcript_excerpt || "").replace(/\s+/g, " ").trim()
    });
  }
  const items = segments.length
    ? segments.map(item => `<li>${seekTimeButton(item.seconds, "checkpoint-seek")}<span>${escapeHtml(item.text.length > 96 ? `${item.text.slice(0, 96).trim()}...` : item.text)}；对照画面确认对应的板书、PPT、代码或操作步骤。</span></li>`)
    : [`<li><span>无同步字幕；先描述画面网格中的标题、公式、代码或界面状态，再回看原视频确认上下文。</span></li>`];
  return `<div class="visual-study-checkpoints">
    <span>回看检查点</span>
    <ol>${items.join("")}</ol>
  </div>`;
}

function visualStudyQuestionHtml(window, transcript) {
  const segments = (transcript?.segments || [])
    .filter(segment => segmentOverlapsWindow(segment, window))
    .slice(0, 2)
    .map(segment => ({ seconds: Number(segment.start || 0), time: fmt(segment.start), text: String(segment.text || "").replace(/\s+/g, " ").trim() }))
    .filter(item => item.text);
  if (!segments.length && window.transcript_excerpt) {
    segments.push({
      seconds: Number(window.start || 0),
      time: fmt(window.start || 0),
      text: String(window.transcript_excerpt || "").replace(/\s+/g, " ").trim()
    });
  }
  const items = segments.length
    ? segments.map(item => {
      const text = item.text.length > 72 ? `${item.text.slice(0, 72).trim()}...` : item.text;
      return `<li>${seekTimeButton(item.seconds, "question-seek")}<span>这句“${escapeHtml(text)}”在画面中对应的标题、公式、代码或操作状态是什么？</span></li>`;
    })
    : (() => {
      const frameTimes = (window.frame_timestamps || []).slice(0, 3).map(value => fmt(value)).join(" / ");
      return [
        `<li><span>${escapeHtml(frameTimes ? `这些帧（${frameTimes}）里最能说明本段主题的画面证据是什么？` : "这个窗口里最值得回看的标题、公式、代码、界面状态或演示步骤是什么？")}</span></li>`,
        `<li><span>如果没有字幕，能否用一句话描述这组截图的操作顺序或 PPT 结构？</span></li>`
      ];
    })();
  return `<div class="visual-study-questions">
    <span>自测问题</span>
    <ol>${items.join("")}</ol>
  </div>`;
}

function visualWindowEvidenceState(task, window, index = 0) {
  const diag = task?.summary_diagnostics || {};
  const id = String(window?.id || `W${String(index + 1).padStart(3, "0")}`);
  const sentIds = new Set((diag.vision_image_window_ids || []).map(value => String(value)));
  const missingIds = new Set((diag.missing_vision_image_window_ids || []).map(value => String(value)));
  const omittedIds = new Set((diag.omitted_vision_window_ids || []).map(value => String(value)));
  if (missingIds.has(id)) {
    return { state: "missing", label: "缺图", detail: "未送入视觉模型，按字幕与索引复习" };
  }
  if (omittedIds.has(id)) {
    return { state: "omitted", label: "已省略", detail: "超出视觉批次上限，保留本地索引" };
  }
  if (sentIds.has(id) || diag.used_vision_llm || task?.summary_source === "vision-llm") {
    return { state: "vision", label: "已进视觉", detail: "网格图已参与图文总结" };
  }
  return { state: "ready", label: "本地索引", detail: safeNoteMediaUrl(window?.grid_url || "") ? "可核对画面和字幕" : "等待网格图" };
}

function visualStudyDeck(task, transcript = null) {
  const windows = visualWindows(task);
  if (!windows.length) return "";
  const firstWindow = windows[0];
  const lastWindow = windows[windows.length - 1];
  const range = firstWindow && lastWindow ? `${fmt(firstWindow.start)} - ${fmt(lastWindow.end)}` : "等待切片";
  const matchedCueCount = (transcript?.segments || []).filter(segment => windows.some(window => segmentOverlapsWindow(segment, window))).length;
  const headDetail = matchedCueCount ? `${windows.length} 个窗口 · ${matchedCueCount} 段字幕已同步` : `${windows.length} 个窗口 · ${range}`;
  return `<section class="visual-study-deck" aria-label="视觉窗口复习">
    <div class="visual-study-head">
      <div>
        <span>视觉窗口复习</span>
        <strong>${escapeHtml(displayTaskTitle(task, "画面切片"))}</strong>
      </div>
      <div class="visual-study-head-actions">
        <small>${escapeHtml(headDetail)}</small>
        <a href="${escapeHtml(taskExportUrl(task, "visual-windows"))}">导出切片索引</a>
      </div>
    </div>
    <div class="visual-study-list">
      ${windows.map((window, index) => {
        const image = safeNoteMediaUrl(window.grid_url || "");
        const evidence = visualWindowEvidenceState(task, window, index);
        return `<article class="visual-study-card ${escapeHtml(evidence.state)}" data-visual-window="${escapeHtml(window.id || "")}" data-window-start="${seekTimeValue(window.start)}">
          <figure>
            ${image ? `<img src="${image}" alt="${escapeHtml(window.id)} frame grid">` : `<div class="visual-study-placeholder">无画面</div>`}
            <figcaption>${escapeHtml(window.id || `W${String(index + 1).padStart(3, "0")}`)}</figcaption>
          </figure>
          <div class="visual-study-card-body">
            <span>窗口 ${String(index + 1).padStart(2, "0")}</span>
            <strong>${fmt(window.start)} - ${fmt(window.end)}</strong>
            <small class="visual-study-evidence ${escapeHtml(evidence.state)}">${escapeHtml(evidence.label)} · ${escapeHtml(evidence.detail)}</small>
            ${visualStudyCueHtml(window, transcript)}
            ${visualStudyCheckpointHtml(window, transcript)}
            ${visualStudyQuestionHtml(window, transcript)}
            ${visualStudyChecklistHtml(window, transcript)}
            <div class="visual-study-meta">
              <em>${Number(window.frame_count || 0)} 帧</em>
              ${frameTimestampText(window) ? `<em>${escapeHtml(frameTimestampText(window))}</em>` : ""}
              <em>${escapeHtml(task.options?.grid_columns && task.options?.grid_rows ? `${task.options.grid_columns}x${task.options.grid_rows}` : "网格")}</em>
              <em>${escapeHtml(task.summary_source || "本地索引")}</em>
            </div>
            <div class="visual-study-actions">
              <button type="button" data-media-seek-time="${seekTimeValue(window.start)}">回看此段</button>
              <button type="button" data-switch-result-tab="transcript">看对应字幕</button>
              <button type="button" data-switch-result-tab="note">回到笔记</button>
            </div>
          </div>
        </article>`;
      }).join("")}
    </div>
  </section>`;
}

function visualStudyNavigatorHtml(task, transcript = null) {
  const windows = visualWindows(task);
  if (!windows.length) return "";
  const diag = task.summary_diagnostics || {};
  const sentIds = new Set((diag.vision_image_window_ids || []).map(value => String(value)));
  const missingIds = new Set((diag.missing_vision_image_window_ids || []).map(value => String(value)));
  const omittedIds = new Set((diag.omitted_vision_window_ids || []).map(value => String(value)));
  const items = windows.map((window, index) => {
    const id = String(window.id || `W${String(index + 1).padStart(3, "0")}`);
    const matched = (transcript?.segments || []).filter(segment => segmentOverlapsWindow(segment, window));
    let state = "ready";
    if (missingIds.has(id)) state = "missing";
    else if (omittedIds.has(id)) state = "omitted";
    else if (sentIds.has(id) || diag.used_vision_llm || task.summary_source === "vision-llm") state = "vision";
    const label = {
      vision: "已进视觉",
      ready: "本地索引",
      missing: "缺图",
      omitted: "已省略"
    }[state];
    return `<button type="button" class="${escapeHtml(state)}" data-media-seek-time="${seekTimeValue(window.start)}" data-window-start="${seekTimeValue(window.start)}">
      <span>${escapeHtml(id)}</span>
      <strong>${fmt(window.start)} - ${fmt(window.end)}</strong>
      <small>${escapeHtml(label)} · ${Number(window.frame_count || 0)} 帧 · ${matched.length || 0} 字幕</small>
    </button>`;
  });
  return `<section class="visual-study-navigator" aria-label="视觉窗口学习队列">
    <header>
      <span>复习队列</span>
      <strong>按画面窗口回看</strong>
      <small>先扫窗口，再进入下方卡片核对字幕、截图和自测题。</small>
    </header>
    <div>${items.join("")}</div>
  </section>`;
}

function learningSliceWorkbench(task, transcript = null) {
  const windows = visualWindows(task);
  if (!windows.length) return "";
  const matchedCueCount = (transcript?.segments || []).filter(segment => windows.some(window => segmentOverlapsWindow(segment, window))).length;
  const totalFrames = windows.reduce((sum, window) => sum + Number(window.frame_count || 0), 0);
  const firstWindow = windows[0];
  const lastWindow = windows[windows.length - 1];
  const range = firstWindow && lastWindow ? `${fmt(firstWindow.start)} - ${fmt(lastWindow.end)}` : "等待切片";
  return `<div class="slice-workbench" aria-label="学习切片工作台">
    <section class="slice-brief">
      <div>
        <span>学习切片</span>
        <strong>${escapeHtml(displayTaskTitle(task, "视频学习切片"))}</strong>
        <small>按视觉窗口把截图网格、同步字幕和回看动作组织在一起，适合复习 PPT、板书、代码演示和界面操作。</small>
      </div>
      <dl>
        <div><dt>窗口</dt><dd>${windows.length}</dd></div>
        <div><dt>画面</dt><dd>${totalFrames || "-"}</dd></div>
        <div><dt>字幕</dt><dd>${matchedCueCount || "-"}</dd></div>
        <div><dt>范围</dt><dd>${escapeHtml(range)}</dd></div>
      </dl>
      <nav>
        ${transcript?.segments?.length ? `<button type="button" data-switch-result-tab="transcript">核对字幕</button>` : ""}
        <a href="${escapeHtml(taskExportUrl(task, "visual-windows"))}">导出切片索引</a>
        ${hasTaskBundle(task) ? `<a href="${escapeHtml(taskExportUrl(task, "bundle"))}">导出资料包</a>` : ""}
      </nav>
    </section>
    ${visualStudyNavigatorHtml(task, transcript)}
    ${visualStudyDeck(task, transcript)}
  </div>`;
}

function visualFrameWorkbench(task, transcript = null) {
  const windows = visualWindows(task);
  if (!windows.length) return "";
  const totalFrames = windows.reduce((sum, window) => sum + Number(window.frame_count || 0), 0);
  const firstWindow = windows[0];
  const lastWindow = windows[windows.length - 1];
  const range = firstWindow && lastWindow ? `${fmt(firstWindow.start)} - ${fmt(lastWindow.end)}` : "等待切片";
  return `<div class="slice-workbench frame-workbench" aria-label="画面网格复核">
    <section class="slice-brief">
      <div>
        <span>画面网格</span>
        <strong>${escapeHtml(displayTaskTitle(task, "视频画面网格"))}</strong>
        <small>集中核对每个视觉窗口的截图网格、帧时间和回看按钮，适合检查 PPT、板书、代码和界面操作有没有进入笔记。</small>
      </div>
      <dl>
        <div><dt>窗口</dt><dd>${windows.length}</dd></div>
        <div><dt>帧数</dt><dd>${totalFrames || "-"}</dd></div>
        <div><dt>网格</dt><dd>${escapeHtml(task.options?.grid_columns && task.options?.grid_rows ? `${task.options.grid_columns}x${task.options.grid_rows}` : "默认")}</dd></div>
        <div><dt>范围</dt><dd>${escapeHtml(range)}</dd></div>
      </dl>
      <nav>
        <button type="button" data-switch-result-tab="slices">学习切片</button>
        ${transcript?.segments?.length ? `<button type="button" data-switch-result-tab="transcript">核对字幕</button>` : ""}
        <a href="${escapeHtml(taskExportUrl(task, "visual-windows"))}">导出切片索引</a>
      </nav>
    </section>
    ${visualStudyDeck(task, transcript)}
  </div>`;
}

function pendingSliceWorkbench(task) {
  if (!task?.media_path) return "";
  const canContinue = canContinueFromDownloadedMedia(task);
  return `<div class="slice-workbench pending" aria-label="待生成学习切片">
    ${mediaSeekDockHtml(task)}
    <section class="slice-pending-card">
      <div>
        <span>下一步</span>
        <strong>${canContinue ? "视频已直取到本地，可以继续切片总结" : "等待生成学习切片"}</strong>
        <small>${canContinue
          ? "复用已下载的 media.mp4，按当前参数进入转写、抽帧、视觉窗口和图文笔记流程；不会重新录制页面。"
          : "任务完成抽帧后，这里会显示按时间窗口组织的截图网格、字幕片段和回看动作。"}</small>
      </div>
      <ol>
        <li class="done"><b>1</b><span>本地视频</span><small>media.mp4 已保存，可导出核对。</small></li>
        <li class="${canContinue ? "active" : "wait"}"><b>2</b><span>转写与抽帧</span><small>继续任务后生成字幕和画面网格。</small></li>
        <li class="wait"><b>3</b><span>学习切片</span><small>按视觉窗口汇总字幕、截图和复习问题。</small></li>
      </ol>
      <nav>
        ${canContinue ? `<button type="button" data-rerun-from-media="${escapeHtml(task.id)}">继续切片总结</button>` : ""}
        <a href="${escapeHtml(taskExportUrl(task, "media"))}">导出 media.mp4</a>
        ${hasTaskDiagnostics(task) ? `<button type="button" data-switch-result-tab="diagnostics">查看下载诊断</button>` : ""}
      </nav>
    </section>
  </div>`;
}

function emptyResultWorkbench() {
  return `
    <section class="empty-workbench" aria-label="学习工作区起始页">
      <div class="empty-hero">
        <div class="empty-hero-copy">
          <span>LearnNote 工作区</span>
          <h3>把正在看的课程视频变成可复习的图文笔记</h3>
          <p>从扩展 Side Panel 直取当前页可访问的视频资源，或上传本地视频；后端会下载到本机、转写、切片、生成画面网格，再合并成学习笔记。</p>
          <div class="empty-production-brief" aria-label="本次产出工作台">
            <section>
              <b>输入</b>
              <strong>当前页 / 本地 / 链接</strong>
              <small>优先直取可访问媒体，不录制页面。</small>
            </section>
            <section>
              <b>处理</b>
              <strong>下载 · 转写 · 切片</strong>
              <small>生成字幕、时间轴和视觉窗口。</small>
            </section>
            <section>
              <b>交付</b>
              <strong>Markdown · 诊断 · 资料包</strong>
              <small>可直接下载，不写入额外记录。</small>
            </section>
          </div>
          <div class="empty-hero-actions">
            <button type="button" data-empty-source="browser">当前页直取</button>
            <button type="button" data-empty-source="local">本地视频</button>
            <button type="button" data-empty-source="url">链接解析</button>
          </div>
        </div>
        <div class="empty-demo-board" aria-label="图文笔记生成预览">
          <header>
            <strong>当前页课程</strong>
            <span>直取候选 · HLS</span>
          </header>
          <div class="empty-demo-video">
            <div class="empty-demo-play"></div>
            <span>00:12:48</span>
          </div>
          <div class="empty-demo-caption">
            <time>12:48</time>
            <span>浏览器字幕和转写片段会按视觉窗口对齐。</span>
          </div>
          <div class="empty-demo-grids">
            ${Array.from({ length: 9 }).map(() => "<i></i>").join("")}
          </div>
          <div class="empty-demo-note">
            <b>生成笔记</b>
            <span>课程主题、时间轴重点、画面索引、易错点、复习题</span>
          </div>
        </div>
      </div>

      <div class="empty-flow" aria-label="处理流程">
        <span><b>01</b>检测媒体</span>
        <span><b>02</b>预检下载</span>
        <span><b>03</b>转写切片</span>
        <span><b>04</b>图文总结</span>
      </div>

      <section class="empty-readiness-panel" aria-label="准备度审计">
        <header>
          <div>
            <span>检查项</span>
            <strong>先看这条链路现在能不能跑通</strong>
          </div>
          <div class="empty-readiness-actions">
            <button type="button" data-empty-source="local">本地视频兜底</button>
            <button type="button" data-empty-action="copy-backend">复制后端地址</button>
            <button type="button" data-empty-action="open-options">处理参数</button>
          </div>
        </header>
        ${emptyReadinessGatesHtml()}
      </section>

      <div class="empty-route-grid" aria-label="开始路线">
        <section class="empty-route-card primary">
          <div>
            <span>当前页直取</span>
            <strong>读取正在播放的视频</strong>
            <p>扩展侧栏嗅探 MP4/FLV/WebM、HLS/DASH、yt-dlp 支持页面和可复用请求头；失败时给出原因，不录制页面。</p>
          </div>
          <div class="empty-route-tags">
            <em>主视频匹配</em>
            <em>Cookie 直取</em>
            <em>DRM 边界</em>
          </div>
          <button type="button" data-empty-source="browser">打开当前页路线</button>
        </section>
        <section class="empty-route-card">
          <div>
            <span>本地视频</span>
            <strong>拖入文件直接切片</strong>
            <p>mp4、mkv、webm、flv、avi 等文件走同一套转写、抽帧、视觉窗口和图文总结管线。</p>
          </div>
          <div class="empty-route-tags">
            <em>离线处理</em>
            <em>视觉切片</em>
            <em>资料包导出</em>
          </div>
          <button type="button" data-empty-source="local">选择本地视频</button>
        </section>
        <section class="empty-route-card">
          <div>
            <span>链接解析</span>
            <strong>粘贴页面或媒体链接</strong>
            <p>可预检 mp4、m3u8、mpd 或平台页面；适合先验证能否下载，再进入完整总结。</p>
          </div>
          <div class="empty-route-tags">
            <em>预检下载</em>
            <em>只下载本地</em>
            <em>继续总结</em>
          </div>
          <button type="button" data-empty-source="url">粘贴链接</button>
        </section>
      </div>
    </section>
  `;
}

function bindEmptyWorkbenchActions() {
  document.querySelectorAll("[data-empty-source]").forEach(button => {
    button.onclick = () => {
      setSource(button.dataset.emptySource);
      document.querySelector(".workspace-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
    };
  });
  document.querySelectorAll("[data-empty-action]").forEach(button => {
    button.onclick = async () => {
      if (button.dataset.emptyAction === "copy-backend") {
        await copyBackendUrl(button);
        return;
      }
      if (button.dataset.emptyAction === "open-options") {
        if (els.optionsDisclosure) els.optionsDisclosure.open = true;
        els.optionsDisclosure?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
      }
    };
  });
}

async function renderDetail() {
  const task = await taskRecord();
  if (!task) {
    els.selectedTitle.textContent = "选择一个任务";
    els.selectedSource.textContent = "结果工作区";
    els.resultMeta.textContent = "";
    els.detail.className = "detail empty";
    els.detail.innerHTML = emptyResultWorkbench();
    bindEmptyWorkbenchActions();
    lastNote = "";
    lastNoteTaskId = "";
    els.copyButton.disabled = true;
    els.bundleButton.disabled = true;
    els.diagnosticsButton.disabled = true;
    if (els.visualWindowsButton) els.visualWindowsButton.disabled = true;
    if (els.manifestButton) els.manifestButton.disabled = true;
    els.mediaButton.disabled = true;
    els.downloadButton.disabled = true;
    updateContinueFromMediaAction(null);
    return;
  }

  els.selectedTitle.textContent = displayTaskTitle(task);
  els.selectedSource.textContent = `${sourceText(task)} · ${statusText(task)}`;
  els.resultMeta.innerHTML = resultMetaChipsHtml(task);
  els.detail.className = "detail";
  const hasNote = Boolean(task.note_path);
  els.copyButton.disabled = !hasNote;
  els.bundleButton.disabled = !hasTaskBundle(task);
  els.diagnosticsButton.disabled = !hasTaskDiagnostics(task);
  if (els.visualWindowsButton) els.visualWindowsButton.disabled = !hasVisualWindowExport(task);
  if (els.manifestButton) els.manifestButton.disabled = !hasTaskBundle(task);
  els.mediaButton.disabled = !task.media_path;
  els.downloadButton.disabled = !hasNote;
  updateContinueFromMediaAction(task);

  if (selectedTab === "note") {
    lastNote = await noteForTask(task.id);
    const emptyNoteHtml = task.media_path ? downloadOnlyEmptyNoteHtml(task) : "<p>笔记尚未生成。</p>";
    els.detail.innerHTML = `
      <div class="note-shell">
        ${taskOverview(task)}
        ${noteHeroBanner(lastNote, task)}
        ${failureGuide(task)}
        ${visionEvidenceBar(task)}
        ${noteStudyBar(lastNote, task)}
        ${noteExportCtaBar(task)}
        <div class="note-workbench">
          <article class="markdown-note">${lastNote ? markdownToHtml(lastNote) : emptyNoteHtml}</article>
          ${readingRail(lastNote, task)}
        </div>
      </div>
    `;
    bindTaskOverviewActions();
    return;
  }

  if (selectedTab === "slices" || selectedTab === "frames") {
    const windows = visualWindows(task);
    if (!windows.length && task?.media_path) {
      els.detail.className = "detail";
      els.detail.innerHTML = pendingSliceWorkbench(task);
      bindTaskOverviewActions();
      return;
    }
    if (!windows.length) {
      els.detail.className = "detail empty";
      els.detail.textContent = "画面切片尚未生成。";
      return;
    }
    const transcript = await transcriptForTask(task);
    const workbench = selectedTab === "frames"
      ? visualFrameWorkbench(task, transcript)
      : learningSliceWorkbench(task, transcript);
    els.detail.innerHTML = `${mediaSeekDockHtml(task)}${visionEvidenceBar(task)}${workbench}`;
    bindTaskOverviewActions();
    return;
  }

  if (selectedTab === "diagnostics") {
    const selected = task.selected_resource || {};
    const attempts = task.download_attempts || [];
    const transcript = await transcriptForTask(task);
    const transcriptSource = transcript?.source ? transcriptSourceText(transcript.source) : "-";
    const attemptHtml = attempts.length ? `
      <div class="attempt-list">
        ${attempts.map(attempt => `
          <div class="attempt ${escapeHtml(attempt.status)}">
            <div class="attempt-header">
              <div>
                <strong>${escapeHtml(attempt.strategy)}</strong>
                <small>${escapeHtml([
                  attempt.code,
                  attempt.status_code ? `HTTP ${attempt.status_code}` : "",
                  fmtBytes(attempt.bytes_downloaded || attempt.content_length),
                  attempt.kind,
                  attempt.source
                ].filter(Boolean).join(" · "))}</small>
              </div>
              <span class="attempt-status">${escapeHtml(attempt.status)}</span>
            </div>
            <p>${escapeHtml(attempt.message || attempt.url || "-")}</p>
            ${attempt.url ? `<code>${escapeHtml(attempt.url)}</code>` : ""}
          </div>
        `).join("")}
      </div>
    ` : "暂无下载尝试记录";
    els.detail.innerHTML = `
      ${failureGuide(task)}
      ${diagnosticRecoveryHtml(task)}
      ${taskBrowserEvidenceHtml(task)}
      ${directExtractionEvidenceHtml(task)}
      ${taskRouteEvidenceHtml(task)}
      ${pipelineAuditHtml(task)}
      <dl class="diagnostics">
        <dt>任务 ID</dt><dd>${escapeHtml(task.id)}</dd>
        <dt>状态</dt><dd>${escapeHtml(task.status)} / ${escapeHtml(task.phase)} / ${task.progress || 0}%</dd>
        <dt>来源</dt><dd>${escapeHtml(task.page_url || task.source_type)}</dd>
        <dt>播放器快照</dt><dd>${escapeHtml(activeVideoText(task.active_video))}</dd>
        <dt>DRM/EME</dt><dd>${escapeHtml(task.drm_detected ? (drmSignalText(task.drm_signals || []) || "已检测到") : "-")}</dd>
        <dt>下载策略</dt><dd>${selected.url ? "浏览器候选资源优先" : "页面解析 fallback"}</dd>
        <dt>已选资源</dt><dd>${escapeHtml(selected.url || "未选择直接资源")}</dd>
        <dt>实际媒体 URL</dt><dd>${escapeHtml(taskResolvedTargetText(task, 140) || "-")}</dd>
        <dt>播放 blob</dt><dd>${escapeHtml(selected.blob_url || "-")}</dd>
        <dt>MSE append</dt><dd>${escapeHtml(mseAppendEvidence(selected) || "-")}</dd>
        <dt>所在 frame</dt><dd>${escapeHtml(selected.frame_url || "-")}</dd>
        <dt>资源类型</dt><dd>${escapeHtml([
          selected.kind || "-",
          resourceSourceText(selected) || selected.source || "-",
          selected.is_main_video ? "主视频" : "",
          playbackText(selected.playback_match),
          selected.request_type || "",
          selected.status_code ? `HTTP ${selected.status_code}` : "",
          fmtBytes(selected.content_length),
          contentDispositionHint(selected.headers?.["content-disposition"]),
          selected.mime || "-"
        ].filter(Boolean).join(" · "))}</dd>
        <dt>复用请求头</dt><dd>${escapeHtml(requestHeaderNames(selected))}</dd>
        <dt>请求 body</dt><dd>${escapeHtml(requestBodySummary(selected) || "-")}</dd>
        <dt>媒体文件</dt><dd>${escapeHtml(task.media_path || "-")}</dd>
        <dt>音频文件</dt><dd>${escapeHtml(task.audio_path || "-")}</dd>
        <dt>转写引擎</dt><dd>${escapeHtml(asrOptionText(task.options || {}))}</dd>
        <dt>转写来源</dt><dd>${escapeHtml(transcriptSource)}</dd>
        <dt>字幕文件</dt><dd>${escapeHtml(task.subtitle_path || "-")}</dd>
        <dt>总结来源</dt><dd>${escapeHtml(task.summary_source || "-")}</dd>
        <dt>图文总结诊断</dt><dd>${escapeHtml(summaryDiagnosticText(task))}</dd>
        <dt>总结提示</dt><dd>${escapeHtml(task.summary_warning || "-")}</dd>
        <dt>处理选项</dt><dd>${escapeHtml(optionText(task) || "-")}</dd>
        <dt>错误</dt><dd>${escapeHtml(task.error_detail || task.error_code || "-")}</dd>
        <dt>尝试记录</dt><dd>${attemptHtml}</dd>
      </dl>
    `;
    return;
  }

  const transcript = await transcriptForTask(task) || {};
  if (!transcript.segments?.length) {
    els.detail.className = "detail empty";
    els.detail.textContent = transcript.warning || "转写尚未生成。";
    return;
  }
  els.detail.innerHTML = `${mediaSeekDockHtml(task)}${transcriptTimeline(transcript, task)}`;
  bindTaskOverviewActions();
}

async function startUrlTask(mode = "video") {
  const url = els.urlInput.value.trim();
  if (!url) {
    els.urlInput.focus();
    return;
  }
  const resource = manualUrlResource(url);
  const resources = resource ? [resource] : [];
  els.startUrlButton.disabled = true;
  if (els.preflightUrlButton) els.preflightUrlButton.disabled = true;
  if (els.downloadUrlButton) els.downloadUrlButton.disabled = true;
  try {
    const data = await fetchJson(apiUrl("/api/tasks/from-current-page"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode,
        page_url: url,
        title: els.titleInput.value.trim() || url,
        page_text: "",
        resources,
        cookies: [],
        options: readOptions()
      })
    });
    selectTask(data.task_id);
    await loadTasks();
    focusResultPanelOnMobile();
  } finally {
    els.startUrlButton.disabled = false;
    if (els.preflightUrlButton) els.preflightUrlButton.disabled = false;
    if (els.downloadUrlButton) els.downloadUrlButton.disabled = false;
  }
}

async function preflightUrlTask() {
  const url = els.urlInput.value.trim();
  if (!url) {
    els.urlInput.focus();
    return;
  }
  if (urlPreflightResourceUrl === url) clearUrlPreflight();
  const resource = manualUrlResource(url);
  if (!resource) {
    els.urlModeHint.textContent = "当前链接类型不能直接预检。请切换为视频直连、HLS 或 DASH，或直接创建任务交给页面扫描和 yt-dlp。";
    renderUrlPreflightReport({ url, kind: resourceKindForUrl(url) }, {
      downloadable: false,
      code: "unsupported_url_mode",
      message: "当前链接类型不能直接预检。可切换为视频直连、HLS 或 DASH，或创建页面扫描任务。"
    }, "fail");
    return;
  }
  els.startUrlButton.disabled = true;
  if (els.preflightUrlButton) els.preflightUrlButton.disabled = true;
  if (els.downloadUrlButton) els.downloadUrlButton.disabled = true;
  els.urlModeHint.textContent = "正在预检链接可访问性...";
  renderUrlPreflightReport(resource, { downloadable: false }, "checking");
  try {
    const data = await fetchJson(apiUrl("/api/media/preflight"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        page_url: url,
        resource,
        cookies: []
      })
    });
    const result = rememberUrlPreflight(resource, data.preflight || {});
    const resolvedTarget = resource.resolved_url && resource.resolved_url !== resource.url
      ? `，目标：${compactUrl(resource.resolved_url, 92)}`
      : "";
    els.urlModeHint.textContent = result.downloadable
      ? `预检通过：${result.kind || resource.kind} 可访问，${result.status_code ? `HTTP ${result.status_code}，` : ""}${fmtBytes(result.content_length) || `${result.bytes_checked || 0} B`}${resolvedTarget}。`
      : `预检未通过：${result.message || result.code || "该链接暂不可直接下载"}`;
    renderUrlPreflightReport(resource, result);
  } finally {
    els.startUrlButton.disabled = false;
    if (els.preflightUrlButton) els.preflightUrlButton.disabled = false;
    if (els.downloadUrlButton) els.downloadUrlButton.disabled = false;
  }
}

async function uploadSelectedFile(fileOverride = null) {
  const file = fileOverride || els.fileInput.files?.[0] || pendingLocalFile;
  if (!file) return;
  pendingLocalFile = file;
  if (!isSupportedLocalVideoFile(file)) {
    els.fileName.textContent = `${file.name} 暂不支持，请选择 mp4 / m4v / mov / flv / avi / mkv / webm 等视频文件`;
    return;
  }
  const form = new FormData();
  form.append("file", file);
  form.append("title", file.name);
  form.append("options", JSON.stringify(readOptions()));
  els.uploadButton.disabled = true;
  els.uploadButton.textContent = "上传中...";
  try {
    const response = await fetch(apiUrl("/api/tasks/from-local"), { method: "POST", body: form });
    const data = await response.json().catch(() => ({}));
    if (response.ok === false || !data?.task_id) {
      els.fileName.textContent = apiErrorMessage(data, "本地视频上传失败，请确认文件格式和后端状态。");
      return;
    }
    selectTask(data.task_id);
    await loadTasks();
    focusResultPanelOnMobile();
  } finally {
    els.uploadButton.disabled = false;
    els.uploadButton.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12M7 8l5-5 5 5M4 17v3h16v-3"/></svg>上传并生成`;
  }
}

els.sourceTabs.forEach(tab => {
  tab.onclick = () => setSource(tab.dataset.source);
});

if (els.sourceWorkflow) {
  els.sourceWorkflow.addEventListener("click", async event => {
    const button = event.target.closest("[data-select-workflow-task]");
    if (button) {
      selectTask(button.dataset.selectWorkflowTask);
      renderTasks();
      await renderDetail();
      focusResultPanelOnMobile();
      return;
    }
    const actionButton = event.target.closest("[data-source-workflow-action]");
    if (!actionButton) return;
    const action = actionButton.dataset.sourceWorkflowAction;
    if (action === "continue-media" && actionButton.dataset.taskId) {
      await rerunTaskFromMedia(actionButton.dataset.taskId);
      return;
    }
    if (action === "refresh-browser") {
      actionButton.disabled = true;
      try {
        await loadTasks();
      } finally {
        actionButton.disabled = false;
      }
      return;
    }
    if (action === "copy-backend") {
      await copyBackendUrl(actionButton);
      return;
    }
    if (action === "open-extension") {
      const url = await copyBackendUrl(actionButton);
      if (els.browserBridgeStatus) {
        els.browserBridgeStatus.textContent = `已复制后端地址：${url}。请在课程播放页打开 LearnNote 扩展侧栏，点击“总结当前视频”。`;
      }
      return;
    }
    if (action === "switch-local") {
      setSource("local");
      els.fileInput?.focus?.();
      return;
    }
    if (action === "choose-local") {
      els.fileInput?.click?.();
      return;
    }
    if (action === "upload-local") {
      await uploadSelectedFile();
      return;
    }
    if (action === "open-options") {
      if (els.optionsDisclosure) els.optionsDisclosure.open = true;
      els.optionsDisclosure?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
      return;
    }
    if (action === "focus-url") {
      els.urlInput?.focus?.();
      return;
    }
    if (action === "preflight-url") {
      await preflightUrlTask();
      return;
    }
    if (action === "start-url") {
      await startUrlTask("video");
      return;
    }
    if (action === "download-url") {
      await startUrlTask("download_only");
    }
  });
}

if (els.browserRouteSummary) {
  els.browserRouteSummary.addEventListener("click", async event => {
    const selectButton = event.target.closest("[data-select-browser-task]");
    if (selectButton) {
      selectTask(selectButton.dataset.selectBrowserTask);
      renderTasks();
      await renderDetail();
      focusResultPanelOnMobile();
      return;
    }
    const rerunButton = event.target.closest("[data-rerun-browser-task]");
    if (rerunButton) {
      await rerunTaskFromMedia(rerunButton.dataset.rerunBrowserTask);
      return;
    }
    const routeAction = event.target.closest("[data-browser-route-action]");
    if (!routeAction) return;
    if (routeAction.dataset.browserRouteAction === "refresh") {
      routeAction.disabled = true;
      try {
        await loadTasks();
      } finally {
        routeAction.disabled = false;
      }
      return;
    }
    if (routeAction.dataset.browserRouteAction === "copy-backend") {
      await copyBackendUrl(routeAction);
      return;
    }
    if (routeAction.dataset.browserRouteAction === "local-video") {
      setSource("local");
      document.querySelector(".workspace-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });
}

if (els.urlMode) {
  els.urlMode.onchange = () => {
    clearUrlPreflight();
    renderUrlModeHint();
  };
  renderUrlModeHint();
}
if (els.urlInput) {
  els.urlInput.oninput = clearUrlPreflight;
}
if (els.transcriber) {
  els.transcriber.onchange = () => {
    syncTranscriberModelDefault(true);
    saveModelSettings();
  };
}
if (els.llmProvider) {
  els.llmProvider.onchange = () => {
    applyModelProviderPreset(true);
    saveModelSettings();
  };
}

els.resultTabs.forEach(tab => {
  tab.onclick = () => switchResultTab(tab.dataset.tab);
});

els.startUrlButton.onclick = () => startUrlTask("video");
if (els.preflightUrlButton) els.preflightUrlButton.onclick = preflightUrlTask;
if (els.downloadUrlButton) els.downloadUrlButton.onclick = () => startUrlTask("download_only");
if (els.toggleWorkspaceButton) {
  els.toggleWorkspaceButton.onclick = () => {
    const collapsed = !document.body?.classList?.contains?.("workspace-collapsed");
    setWorkspaceCollapsed(collapsed);
  };
}
if (els.toggleHistoryButton) {
  els.toggleHistoryButton.onclick = () => {
    const collapsed = !document.body?.classList?.contains?.("queue-collapsed");
    setHistoryCollapsed(collapsed);
  };
}
if (els.readingModeButton) {
  els.readingModeButton.onclick = () => {
    const enabled = !document.body?.classList?.contains?.("reading-mode");
    setReadingMode(enabled);
  };
}
els.copyBackendButton.onclick = () => copyBackendUrl(els.copyBackendButton);
els.browserRefreshButton.onclick = () => loadTasks();
els.uploadButton.onclick = uploadSelectedFile;
els.refreshButton.onclick = () => loadTasks();
els.taskSearch.oninput = () => {
  taskQuery = els.taskSearch.value;
  renderTasks();
};
els.statusFilter.onchange = () => {
  taskStatusFilter = els.statusFilter.value;
  renderTasks();
};
els.copyButton.onclick = async () => navigator.clipboard.writeText(await noteForTask(selectedTaskId) || "");
if (els.continueFromMediaButton) els.continueFromMediaButton.onclick = () => rerunTaskFromMedia(selectedTaskId);
els.bundleButton.onclick = () => {
  if (!selectedTaskId) return;
  window.location.assign(apiUrl(`/api/tasks/${encodeURIComponent(selectedTaskId)}/exports/bundle`));
};
if (els.manifestButton) {
  els.manifestButton.onclick = () => {
    if (!selectedTaskId) return;
    window.location.assign(apiUrl(`/api/tasks/${encodeURIComponent(selectedTaskId)}/exports/manifest`));
  };
}
els.diagnosticsButton.onclick = () => {
  if (!selectedTaskId) return;
  window.location.assign(apiUrl(`/api/tasks/${encodeURIComponent(selectedTaskId)}/exports/diagnostics`));
};
if (els.visualWindowsButton) {
  els.visualWindowsButton.onclick = () => {
    if (!selectedTaskId) return;
    window.location.assign(apiUrl(`/api/tasks/${encodeURIComponent(selectedTaskId)}/exports/visual-windows`));
  };
}
els.mediaButton.onclick = () => {
  if (!selectedTaskId) return;
  window.location.assign(apiUrl(`/api/tasks/${encodeURIComponent(selectedTaskId)}/exports/media`));
};
els.downloadButton.onclick = () => {
  if (!selectedTaskId) return;
  window.location.assign(apiUrl(`/api/tasks/${encodeURIComponent(selectedTaskId)}/exports/markdown`));
};

els.dropzone.addEventListener("dragover", event => {
  event.preventDefault();
  els.dropzone.classList.add("drag");
});
els.dropzone.addEventListener("dragleave", () => els.dropzone.classList.remove("drag"));
els.dropzone.addEventListener("drop", event => {
  event.preventDefault();
  els.dropzone.classList.remove("drag");
  if (event.dataTransfer.files?.[0]) {
    pendingLocalFile = event.dataTransfer.files[0];
    els.fileName.textContent = pendingLocalFile.name;
    setSource("local");
    uploadSelectedFile(pendingLocalFile);
  }
});

els.fileInput.onchange = () => {
  pendingLocalFile = els.fileInput.files?.[0] || null;
  els.fileName.textContent = pendingLocalFile?.name || "mp4 / flv / avi / webm / mov / mkv";
  setSource("local");
};

[
  els.frameInterval,
  els.gridSize,
  els.visualUnderstanding,
  els.noteStyle,
  els.noteTemplate,
  els.summaryDepth,
  els.llmProvider,
  els.transcriber,
  els.whisperModel
].filter(Boolean).forEach(control => {
  control.addEventListener("change", () => {
    refreshOptionDependentUi();
    if ([els.llmProvider, els.transcriber, els.whisperModel].includes(control)) saveModelSettings();
  });
});
els.llmModel?.addEventListener("input", () => {
  updateHealthVisionStatus();
  saveModelSettings();
});
els.llmBaseUrl?.addEventListener("input", () => {
  updateHealthVisionStatus();
  saveModelSettings();
});
els.llmApiKey?.addEventListener("input", () => updateHealthVisionStatus());

initializeResponsiveChrome();
loadModelSettings();
initializeWorkspaceView();
renderSourceWorkflow();
checkHealth();
loadTasks();
setInterval(() => {
  checkHealth();
  loadTasks();
}, 3000);
