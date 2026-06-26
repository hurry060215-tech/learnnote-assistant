const API = "";
const MEDIA_RE = /\.(mp4|m4v|webm|mov|mkv)(\?|#|$)/i;
const HLS_RE = /\.(m3u8|mpd)(\?|#|$)/i;

let selectedSource = "browser";
let selectedTaskId = null;
let selectedTab = "note";
let lastNote = "";
let lastNoteTaskId = "";
let tasks = [];
let taskQuery = "";
let taskStatusFilter = "all";

const els = {
  health: document.querySelector("#health"),
  refreshButton: document.querySelector("#refreshButton"),
  toggleHistoryButton: document.querySelector("#toggleHistoryButton"),
  readingModeButton: document.querySelector("#readingModeButton"),
  sourceTabs: document.querySelectorAll(".source-tab"),
  panes: document.querySelectorAll(".source-pane"),
  urlInput: document.querySelector("#urlInput"),
  urlMode: document.querySelector("#urlMode"),
  urlModeHint: document.querySelector("#urlModeHint"),
  optionsDisclosure: document.querySelector("#optionsDisclosure"),
  titleInput: document.querySelector("#titleInput"),
  startUrlButton: document.querySelector("#startUrlButton"),
  copyBackendButton: document.querySelector("#copyBackendButton"),
  browserRefreshButton: document.querySelector("#browserRefreshButton"),
  browserBridgeStatus: document.querySelector("#browserBridgeStatus"),
  fileInput: document.querySelector("#fileInput"),
  fileName: document.querySelector("#fileName"),
  dropzone: document.querySelector("#dropzone"),
  uploadButton: document.querySelector("#uploadButton"),
  taskSearch: document.querySelector("#taskSearch"),
  statusFilter: document.querySelector("#statusFilter"),
  frameInterval: document.querySelector("#frameInterval"),
  gridSize: document.querySelector("#gridSize"),
  whisperModel: document.querySelector("#whisperModel"),
  noteStyle: document.querySelector("#noteStyle"),
  summaryDepth: document.querySelector("#summaryDepth"),
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
  copyButton: document.querySelector("#copyButton"),
  bundleButton: document.querySelector("#bundleButton"),
  mediaButton: document.querySelector("#mediaButton"),
  downloadButton: document.querySelector("#downloadButton")
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

function fmtBytes(bytes) {
  const value = Number(bytes || 0);
  if (!value) return "";
  if (value >= 1024 * 1024 * 1024) return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value} B`;
}

function requestHeaderNames(resource) {
  return Object.keys(resource?.request_headers || {})
    .filter(name => !/cookie|authorization/i.test(name))
    .sort()
    .join(", ") || "-";
}

function summaryDiagnosticText(task) {
  const diag = task?.summary_diagnostics || {};
  if (!Object.keys(diag).length) return "-";
  const visionGridCount = diag.vision_grid_count ?? diag.frame_grid_count ?? 0;
  const sentImages = diag.vision_image_count ?? 0;
  const omittedCount = Number(diag.omitted_frame_grid_count || 0);
  const missingImages = diag.all_sent_grids_had_images === false || diag.all_grids_had_images === false;
  return [
    diag.used_vision_llm ? "已使用视觉 LLM" : diag.used_text_llm ? "已使用文本 LLM" : diag.used_local_template ? "本地模板" : "",
    `模型 ${diag.llm_model || task.summary_source || "-"}`,
    `视觉窗口 ${diag.visual_window_count ?? 0}`,
    `画面网格 ${diag.frame_grid_count ?? 0}`,
    `\u9001\u5165\u89c6\u89c9 ${sentImages}/${visionGridCount}`,
    omittedCount > 0 ? `\u8d85\u9650\u7701\u7565 ${omittedCount}` : "",
    missingImages ? "\u5b58\u5728\u7f3a\u5931\u56fe\u7247" : "",
    diag.summary_warning || ""
  ].filter(Boolean).join(" · ");
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
  if (task.source_type === "local") return "本地视频";
  if (task.source_type === "page_text") return "页面文本";
  return task.selected_resource ? `直取 · ${task.selected_resource.kind}` : "页面解析";
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
    body: "可以先让页面视频播放几秒后重新检测；如果仍没有 mp4、m3u8 或 mpd，请改用本地视频上传。"
  },
  auth_required: {
    title: "资源需要登录态",
    body: "重新打开课程页面并确认已登录，再从扩展侧边栏创建任务；后端只会在点击任务时同步一次当前域 cookie。"
  },
  drm_or_encrypted: {
    title: "页面触发了 DRM/EME 加密媒体信号",
    body: "这个版本不会录制、破解或绕过 DRM。可直取 mp4、m3u8 或 mpd 不存在时，只能使用本地视频入口。"
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
  return `<div class="failure-guide"><strong>${escapeHtml(guide.title)}</strong>${escapeHtml(guide.body)}</div>`;
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

function optionText(task) {
  const options = task.options || {};
  return [
    options.frame_interval ? `${options.frame_interval} 秒切片` : "",
    options.grid_columns && options.grid_rows ? `${options.grid_columns}x${options.grid_rows} 画面网格` : "",
    options.whisper_model ? `ASR ${options.whisper_model}` : "",
    options.note_style ? `风格 ${options.note_style}` : "",
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
    auto: "自动识别会优先把 mp4/m3u8/mpd 当作媒体候选，其余 URL 交给页面扫描和 yt-dlp。",
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

function labelForUrlResource(kind, mode = selectedUrlMode()) {
  if (mode === "video") return "手动视频直连";
  if (mode === "hls") return "手动 HLS";
  if (mode === "dash") return "手动 DASH";
  if (kind === "video") return "手动媒体链接";
  if (kind === "hls") return "手动 HLS";
  if (kind === "dash") return "手动 DASH";
  return "手动链接";
}

function renderUrlModeHint() {
  if (!els.urlModeHint) return;
  els.urlModeHint.textContent = urlModeDescription();
}

function readOptions() {
  const [cols, rows] = els.gridSize.value.split("x").map(Number);
  const options = {
    visual_understanding: true,
    frame_interval: Number(els.frameInterval.value || 20),
    grid_columns: cols || 3,
    grid_rows: rows || 3,
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

async function checkHealth() {
  try {
    const data = await fetch(`${API}/health`).then(r => r.json());
    els.health.className = data.ffmpeg ? "health ok" : "health bad";
    els.health.textContent = data.ffmpeg ? "本地后端可用" : "ffmpeg 缺失";
    if (els.browserBridgeStatus) {
      els.browserBridgeStatus.textContent = data.ffmpeg
        ? "扩展读取播放状态、媒体请求和一次性 cookie，后端在本机处理。"
        : "后端已连接，但 ffmpeg 缺失；当前页直取后无法完成合并/切片。";
    }
  } catch {
    els.health.className = "health bad";
    els.health.textContent = "后端未连接";
    if (els.browserBridgeStatus) {
      els.browserBridgeStatus.textContent = "先启动本地后端，再从扩展 Side Panel 创建当前页任务。";
    }
  }
}

function setSource(source) {
  selectedSource = source;
  els.sourceTabs.forEach(tab => tab.classList.toggle("active", tab.dataset.source === source));
  els.panes.forEach(pane => pane.classList.toggle("active", pane.id === `${source}Source`));
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

function setReadingMode(enabled, persist = true) {
  document.body?.classList?.toggle("reading-mode", Boolean(enabled));
  setPressed(els.readingModeButton, enabled);
  if (persist) storeUiFlag("learnnote.readingMode", enabled);
}

function initializeWorkspaceView() {
  setHistoryCollapsed(storedUiFlag("learnnote.historyCollapsed"), false);
  setReadingMode(storedUiFlag("learnnote.readingMode"), false);
}

async function loadTasks() {
  const data = await fetch(`${API}/api/tasks`).then(r => r.json());
  tasks = data.tasks || [];
  if (!selectedTaskId && tasks[0]) selectedTaskId = tasks[0].id;
  renderTasks();
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

  const visibleTasks = tasks.filter(taskMatchesFilters);

  if (!tasks.length) {
    els.tasks.innerHTML = `<div class="detail empty">暂无任务。</div>`;
    return;
  }
  if (!visibleTasks.length) {
    els.tasks.innerHTML = `<div class="detail empty">没有匹配的任务。</div>`;
    return;
  }

  els.tasks.innerHTML = visibleTasks.map(task => `
    <button class="task status-${escapeHtml(task.status)} ${task.id === selectedTaskId ? "selected" : ""}" data-id="${escapeHtml(task.id)}">
      <div>
        <strong>${escapeHtml(task.title || task.id)}</strong>
        <small>${escapeHtml(statusText(task))} · ${escapeHtml(task.phase)}</small>
        <span class="source">${escapeHtml(sourceText(task))}</span>
        ${stageRail(task)}
        <div class="progress"><span style="width:${task.progress || 0}%"></span></div>
      </div>
      <small>${task.progress || 0}%</small>
    </button>
  `).join("");

  document.querySelectorAll(".task").forEach(button => {
    button.onclick = async () => {
      selectedTaskId = button.dataset.id;
      renderTasks();
      await renderDetail();
      focusResultPanelOnMobile();
    };
  });
}

async function taskRecord() {
  if (!selectedTaskId) return null;
  return fetch(`${API}/api/tasks/${selectedTaskId}`).then(r => r.json()).then(d => d.task);
}

async function noteForTask(taskId) {
  if (!taskId) return "";
  if (lastNoteTaskId === taskId && lastNote) return lastNote;
  const response = await fetch(`${API}/api/tasks/${taskId}/note`);
  if (!response.ok) return "";
  lastNote = await response.text();
  lastNoteTaskId = taskId;
  return lastNote;
}

function taskBrief(task) {
  const selected = task.selected_resource || {};
  return `<div class="task-brief">
    <span><b>${escapeHtml(statusText(task))}</b>${escapeHtml(task.phase || "-")} · ${task.progress || 0}%</span>
    <span><b>${escapeHtml(sourceText(task))}</b>${escapeHtml(selected.kind || task.source_type || "-")}</span>
    <span><b>${escapeHtml(task.options?.frame_interval || "-")} 秒切片</b>${escapeHtml(task.options?.grid_columns && task.options?.grid_rows ? `${task.options.grid_columns}x${task.options.grid_rows} 视觉窗口` : "未配置视觉窗口")}</span>
    <span><b>${escapeHtml(task.summary_source || task.options?.whisper_model || "-")}</b>${escapeHtml(task.summary_warning ? "已降级，详见诊断" : `${task.options?.note_style || "study"} · ${task.options?.visual_understanding === false ? "无视觉" : "图文"}`)}</span>
  </div>`;
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

function readingRail(markdown, task) {
  const outline = noteOutline(markdown);
  const visuals = visualRail(task);
  if (!outline && !visuals) return "";
  return `<aside class="reading-rail" aria-label="笔记阅读导航">${outline}${visuals}</aside>`;
}

function visualWindows(task) {
  if (task.visual_windows?.length) return task.visual_windows;
  return (task.frame_grids || []).map((grid, index) => ({
    id: `W${String(index + 1).padStart(3, "0")}`,
    index: index + 1,
    start: grid.start,
    end: grid.end,
    frame_count: grid.frame_count,
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

function transcriptTimeline(transcript, task, limit = Infinity) {
  const segments = (transcript?.segments || []).slice(0, limit);
  const windows = visualWindows(task);
  if (!windows.length) return transcriptLines(segments);

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

  return `<div class="transcript-timeline">${cards.join("")}</div>`;
}

async function renderDetail() {
  const task = await taskRecord();
  if (!task) {
    els.selectedTitle.textContent = "选择一个任务";
    els.selectedSource.textContent = "结果工作区";
    els.resultMeta.textContent = "";
    els.detail.className = "detail empty";
    els.detail.textContent = "任务完成后显示结构化结果。";
    lastNote = "";
    lastNoteTaskId = "";
    els.copyButton.disabled = true;
    els.bundleButton.disabled = true;
    els.mediaButton.disabled = true;
    els.downloadButton.disabled = true;
    return;
  }

  els.selectedTitle.textContent = task.title || task.id;
  els.selectedSource.textContent = `${sourceText(task)} · ${statusText(task)}`;
  els.resultMeta.textContent = [
    task.id,
    optionText(task),
    task.selected_resource?.playback_match ? playbackText(task.selected_resource.playback_match) : "",
    task.selected_resource?.content_length ? fmtBytes(task.selected_resource.content_length) : ""
  ].filter(Boolean).join(" · ");
  els.detail.className = "detail";
  const hasNote = Boolean(task.note_path);
  els.copyButton.disabled = !hasNote;
  els.bundleButton.disabled = !hasNote;
  els.mediaButton.disabled = !task.media_path;
  els.downloadButton.disabled = !hasNote;

  if (selectedTab === "note") {
    lastNote = await noteForTask(task.id);
    els.detail.innerHTML = `
      <div class="note-shell">
        ${taskBrief(task)}
        ${failureGuide(task)}
        <div class="note-workbench">
          <article class="markdown-note">${lastNote ? markdownToHtml(lastNote) : task.media_path ? "<p>视频已下载到本地。可点击右上角视频按钮导出，不会继续转写、切片或总结。</p>" : "<p>笔记尚未生成。</p>"}</article>
          ${readingRail(lastNote, task)}
        </div>
      </div>
    `;
    return;
  }

  if (selectedTab === "frames") {
    const windows = visualWindows(task);
    if (!windows.length) {
      els.detail.className = "detail empty";
      els.detail.textContent = "画面切片尚未生成。";
      return;
    }
    els.detail.innerHTML = `<div class="frames visual-windows">${windows.map(window => `
      <figure>
        <img src="${escapeHtml(window.grid_url)}" alt="frame grid">
        <figcaption>
          <strong>${escapeHtml(window.id)}</strong>
          <span>${fmt(window.start)} - ${fmt(window.end)} · ${window.frame_count} 帧</span>
          ${window.transcript_excerpt ? `<small>${escapeHtml(window.transcript_excerpt)}</small>` : ""}
        </figcaption>
      </figure>
    `).join("")}</div>`;
    return;
  }

  if (selectedTab === "diagnostics") {
    const selected = task.selected_resource || {};
    const attempts = task.download_attempts || [];
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
      <dl class="diagnostics">
        <dt>任务 ID</dt><dd>${escapeHtml(task.id)}</dd>
        <dt>状态</dt><dd>${escapeHtml(task.status)} / ${escapeHtml(task.phase)} / ${task.progress || 0}%</dd>
        <dt>来源</dt><dd>${escapeHtml(task.page_url || task.source_type)}</dd>
        <dt>播放器快照</dt><dd>${escapeHtml(activeVideoText(task.active_video))}</dd>
        <dt>DRM/EME</dt><dd>${escapeHtml(task.drm_detected ? (drmSignalText(task.drm_signals || []) || "已检测到") : "-")}</dd>
        <dt>下载策略</dt><dd>${selected.url ? "浏览器候选资源优先" : "页面解析 fallback"}</dd>
        <dt>已选资源</dt><dd>${escapeHtml(selected.url || "未选择直接资源")}</dd>
        <dt>播放 blob</dt><dd>${escapeHtml(selected.blob_url || "-")}</dd>
        <dt>所在 frame</dt><dd>${escapeHtml(selected.frame_url || "-")}</dd>
        <dt>资源类型</dt><dd>${escapeHtml([
          selected.kind || "-",
          selected.source || "-",
          selected.is_main_video ? "主视频" : "",
          playbackText(selected.playback_match),
          selected.request_type || "",
          selected.status_code ? `HTTP ${selected.status_code}` : "",
          fmtBytes(selected.content_length),
          selected.mime || "-"
        ].filter(Boolean).join(" · "))}</dd>
        <dt>复用请求头</dt><dd>${escapeHtml(requestHeaderNames(selected))}</dd>
        <dt>媒体文件</dt><dd>${escapeHtml(task.media_path || "-")}</dd>
        <dt>音频文件</dt><dd>${escapeHtml(task.audio_path || "-")}</dd>
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

  const transcript = await fetch(`${API}/api/tasks/${task.id}/transcript`).then(r => r.json());
  if (!transcript.segments?.length) {
    els.detail.className = "detail empty";
    els.detail.textContent = transcript.warning || "转写尚未生成。";
    return;
  }
  els.detail.innerHTML = transcriptTimeline(transcript, task);
}

async function startUrlTask() {
  const url = els.urlInput.value.trim();
  if (!url) {
    els.urlInput.focus();
    return;
  }
  const kind = resourceKindForUrl(url);
  const resources = kind === "unknown" ? [] : [{
    url,
    source: "manual",
    kind,
    mime: mimeForKind(kind),
    score: selectedUrlMode() === "auto" ? 96 : 98,
    label: labelForUrlResource(kind),
    request_type: selectedUrlMode() === "auto" ? "manual-auto" : "manual-forced"
  }];
  els.startUrlButton.disabled = true;
  try {
    const data = await fetch(`${API}/api/tasks/from-current-page`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode: "video",
        page_url: url,
        title: els.titleInput.value.trim() || url,
        page_text: "",
        resources,
        cookies: [],
        options: readOptions()
      })
    }).then(r => r.json());
    selectedTaskId = data.task_id;
    await loadTasks();
    focusResultPanelOnMobile();
  } finally {
    els.startUrlButton.disabled = false;
  }
}

async function uploadSelectedFile() {
  const file = els.fileInput.files?.[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  form.append("title", els.titleInput.value.trim() || file.name);
  form.append("options", JSON.stringify(readOptions()));
  els.uploadButton.disabled = true;
  els.uploadButton.textContent = "上传中...";
  try {
    const data = await fetch(`${API}/api/tasks/from-local`, { method: "POST", body: form }).then(r => r.json());
    selectedTaskId = data.task_id;
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

if (els.urlMode) {
  els.urlMode.onchange = renderUrlModeHint;
  renderUrlModeHint();
}

els.resultTabs.forEach(tab => {
  tab.onclick = () => {
    selectedTab = tab.dataset.tab;
    els.resultTabs.forEach(item => item.classList.toggle("active", item === tab));
    renderDetail();
  };
});

els.startUrlButton.onclick = startUrlTask;
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
els.copyBackendButton.onclick = async () => {
  const url = window.location.origin || "http://127.0.0.1:8765";
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
  const previous = els.copyBackendButton.innerHTML;
  els.copyBackendButton.textContent = "已复制";
  setTimeout(() => {
    els.copyBackendButton.innerHTML = previous;
  }, 1400);
};
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
els.bundleButton.onclick = () => {
  if (!selectedTaskId) return;
  window.location.assign(`${API}/api/tasks/${encodeURIComponent(selectedTaskId)}/exports/bundle`);
};
els.mediaButton.onclick = () => {
  if (!selectedTaskId) return;
  window.location.assign(`${API}/api/tasks/${encodeURIComponent(selectedTaskId)}/exports/media`);
};
els.downloadButton.onclick = () => {
  if (!selectedTaskId) return;
  window.location.assign(`${API}/api/tasks/${encodeURIComponent(selectedTaskId)}/exports/markdown`);
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
    els.fileInput.files = event.dataTransfer.files;
    els.fileName.textContent = event.dataTransfer.files[0].name;
    setSource("local");
  }
});

els.fileInput.onchange = () => {
  els.fileName.textContent = els.fileInput.files?.[0]?.name || "mp4 / webm / mov / mkv";
  setSource("local");
};

initializeResponsiveChrome();
initializeWorkspaceView();
checkHealth();
loadTasks();
setInterval(() => {
  checkHealth();
  loadTasks();
}, 3000);
