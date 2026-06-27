const API = "";
const MEDIA_RE = /\.(mp4|m4v|webm|mov|mkv|flv|avi)(\?|#|$)/i;
const HLS_RE = /\.(m3u8|mpd)(\?|#|$)/i;
const LOCAL_VIDEO_EXT_RE = /\.(mp4|m4v|mov|mkv|webm|flv|avi)$/i;

let selectedSource = "browser";
let selectedTaskId = null;
let selectedTab = "note";
let lastNote = "";
let lastNoteTaskId = "";
let lastTranscript = null;
let lastTranscriptTaskId = "";
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
  continueFromMediaButton: document.querySelector("#continueFromMediaButton"),
  copyButton: document.querySelector("#copyButton"),
  bundleButton: document.querySelector("#bundleButton"),
  diagnosticsButton: document.querySelector("#diagnosticsButton"),
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

function currentPageTasks() {
  return tasks.filter(task => task.source_type === "current_page");
}

function latestCurrentPageTask() {
  return currentPageTasks()[0] || null;
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

function browserRouteActions(task) {
  if (!task?.id) return "";
  const actions = [
    `<button type="button" data-select-browser-task="${escapeHtml(task.id)}">查看任务</button>`
  ];
  if (canContinueFromDownloadedMedia(task)) {
    actions.push(`<button type="button" data-rerun-browser-task="${escapeHtml(task.id)}">继续切片总结</button>`);
  }
  if (task.media_path) {
    actions.push(`<a href="${escapeHtml(taskExportUrl(task, "media"))}">导出本地视频</a>`);
  }
  if (hasTaskDiagnostics(task)) {
    actions.push(`<a href="${escapeHtml(taskExportUrl(task, "diagnostics"))}">下载诊断</a>`);
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
    ${browserRouteActions(task)}
  </section>`;
}

function renderBrowserRouteSummary() {
  if (!els.browserRouteSummary) return;
  els.browserRouteSummary.innerHTML = browserRouteSummaryHtml(latestCurrentPageTask());
}

function isManualUrlTask(task) {
  const selected = task?.selected_resource || {};
  return task?.source_type === "current_page"
    && (selected.source === "manual" || String(selected.request_type || "").startsWith("manual"));
}

function workflowTaskForSource(source) {
  if (source === "local") return tasks.find(task => task.source_type === "local") || null;
  if (source === "url") return tasks.find(isManualUrlTask) || null;
  return currentPageTasks().find(task => !isManualUrlTask(task)) || latestCurrentPageTask();
}

function workflowSourceConfig(source, task = null) {
  if (source === "local") {
    return {
      eyebrow: "本地视频",
      title: task ? "本地视频正在走完整切片链路" : "拖入本地视频，走同一套图文总结",
      hint: task ? statusText(task) : "适合 DRM、不可还原 blob 或学习平台不暴露媒体 URL 的课程。",
      steps: [
        ["导入文件", "mp4 / flv / avi / mkv / webm"],
        ["提取音频", "字幕优先，Whisper 兜底"],
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
      ["理解方式", "字幕优先，Whisper 兜底", "同样抽帧切片并送入视觉窗口"],
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

function sourceWorkflowHtml(source = selectedSource, task = workflowTaskForSource(source)) {
  const config = workflowSourceConfig(source, task);
  const state = task ? statusText(task) : "等待开始";
  return `<section class="source-workflow-card ${escapeHtml(source)}">
    <header>
      <span>${escapeHtml(config.eyebrow)}</span>
      <strong>${escapeHtml(config.title)}</strong>
      <small>${escapeHtml(config.hint)}</small>
    </header>
    <ol class="source-workflow-lane">
      ${config.steps.map(([title, detail], index) => `<li class="${workflowStepState(task, index)}">
        <b>${index + 1}</b>
        <span>${escapeHtml(title)}</span>
        <small>${escapeHtml(detail)}</small>
      </li>`).join("")}
    </ol>
    ${sourceRouteInsightsHtml(source, task)}
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
  if (task.source_type === "local") return "本地视频";
  if (task.source_type === "page_text") return "页面文本";
  return task.selected_resource ? `直取 · ${task.selected_resource.kind}` : "页面解析";
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
  if (resource?.source === "webRequest") return "浏览器请求";
  if (String(resource?.source || "").startsWith("pageHook")) return "页面接口";
  return resource?.source || "";
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
  </div>`;
}

function recoveryStepItems(task) {
  const attempts = task?.download_attempts || [];
  const codes = new Set([task?.error_code, ...attempts.map(attempt => attempt.code)].filter(Boolean));
  const steps = [];
  const add = text => {
    if (text && !steps.includes(text)) steps.push(text);
  };
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
  return {
    url,
    source: "manual",
    kind,
    mime: mimeForKind(kind),
    score: selectedUrlMode() === "auto" ? 96 : 98,
    label: labelForUrlResource(kind),
    request_type: selectedUrlMode() === "auto" ? "manual-auto" : "manual-forced"
  };
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
      ${taskPreviewHtml(task)}
      <div>
        <strong>${escapeHtml(task.title || task.id)}</strong>
        <small>${escapeHtml(statusText(task))} · ${escapeHtml(task.phase)}</small>
        <span class="source">${escapeHtml(sourceText(task))}</span>
        ${taskChipsHtml(task)}
        ${stageRail(task)}
        <div class="progress"><span style="width:${task.progress || 0}%"></span></div>
      </div>
      <small>${task.progress || 0}%</small>
    </button>
  `).join("");

  document.querySelectorAll(".task").forEach(button => {
    button.onclick = async () => {
      selectedTaskId = button.dataset.id;
      clearTaskCaches();
      renderTasks();
      await renderDetail();
      focusResultPanelOnMobile();
    };
  });
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
  const chips = [
    sourceText(task),
    selected.kind || "",
    selected.playback_match ? playbackText(selected.playback_match) : "",
    task.media_path ? "本地视频" : "",
    task.note_path ? "笔记" : "",
    windows.length ? `${windows.length} 视觉窗口` : "",
    attempts.length ? `${attempts.length} 次下载尝试` : "",
    task.error_code || ""
  ];
  const seen = new Set();
  return chips.filter(value => {
    const text = String(value || "").trim();
    if (!text || seen.has(text)) return false;
    seen.add(text);
    return true;
  }).slice(0, 8);
}

function taskChipsHtml(task) {
  const chips = taskChipItems(task);
  if (!chips.length) return "";
  return `<div class="task-chips">${chips.map(chip => `<span>${escapeHtml(chip)}</span>`).join("")}</div>`;
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

function clearTaskCaches() {
  lastNote = "";
  lastNoteTaskId = "";
  lastTranscript = null;
  lastTranscriptTaskId = "";
}

async function transcriptForTask(task) {
  if (!task?.id || !task.transcript_path) return null;
  if (lastTranscriptTaskId === task.id && lastTranscript) return lastTranscript;
  const response = await fetch(`${API}/api/tasks/${task.id}/transcript`);
  if (!response.ok) return null;
  lastTranscript = await response.json();
  lastTranscriptTaskId = task.id;
  return lastTranscript;
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

function taskStatusClass(task) {
  if (task.status === "success") return "success";
  if (task.status === "failed") return "failed";
  if (task.status === "running" || task.status === "queued") return "running";
  return "idle";
}

function taskExportUrl(task, type) {
  return `${API}/api/tasks/${encodeURIComponent(task.id)}/exports/${type}`;
}

function taskRerunUrl(taskId) {
  return `${API}/api/tasks/${encodeURIComponent(taskId)}/rerun-from-media`;
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

function canContinueFromDownloadedMedia(task) {
  return Boolean(task?.id && task.status === "success" && task.media_path && !task.note_path);
}

function updateContinueFromMediaAction(task) {
  if (!els.continueFromMediaButton) return;
  const canContinue = canContinueFromDownloadedMedia(task);
  els.continueFromMediaButton.hidden = !canContinue;
  els.continueFromMediaButton.disabled = !canContinue;
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
  const fallbackNote = task.status === "failed" && hasNote;
  const resourceLine = [
    sourceText(task),
    selected.kind || task.source_type || "",
    resourceSourceText(selected),
    selected.playback_match ? playbackText(selected.playback_match) : "",
    selected.content_length ? fmtBytes(selected.content_length) : ""
  ].filter(Boolean).join(" · ");
  const actionLinks = [
    downloadOnly ? `<button type="button" data-rerun-from-media="${escapeHtml(task.id)}">生成完整笔记</button>` : "",
    hasNote ? `<a href="${escapeHtml(taskExportUrl(task, "markdown"))}">导出 Markdown</a>` : "",
    hasMedia ? `<a href="${escapeHtml(taskExportUrl(task, "media"))}">导出本地视频</a>` : "",
    hasTaskDiagnostics(task) ? `<a href="${escapeHtml(taskExportUrl(task, "diagnostics"))}">导出诊断</a>` : "",
    hasBundle ? `<a href="${escapeHtml(taskExportUrl(task, "bundle"))}">导出资料包</a>` : ""
  ].filter(Boolean).join("");

  return `<section class="task-overview status-${statusClass}">
    <div class="task-overview-main">
      <span class="eyeless">当前学习任务</span>
      <strong>${escapeHtml(task.title || task.id)}</strong>
      <small>${escapeHtml(resourceLine || statusText(task))}</small>
      ${stageRail(task)}
    </div>
    <div class="task-overview-actions">
      ${actionLinks || `<span>${escapeHtml(statusText(task))}</span>`}
    </div>
    <div class="task-overview-metrics">
      <span><b>${escapeHtml(statusText(task))}</b>${escapeHtml(task.phase || "-")} · ${task.progress || 0}%</span>
      <span><b>${escapeHtml(options.frame_interval || "-")} 秒切片</b>${escapeHtml(options.grid_columns && options.grid_rows ? `${options.grid_columns}x${options.grid_rows} 视觉窗口` : "未配置视觉窗口")}</span>
      <span><b>${escapeHtml(task.summary_source || options.whisper_model || "-")}</b>${escapeHtml(task.summary_warning ? "已降级，查看诊断" : `${options.note_style || "study"} · ${options.visual_understanding === false ? "无视觉" : "图文"}`)}</span>
      <span><b>${windows.length || "-"}</b>${windows.length ? "画面窗口" : "等待画面切片"}</span>
    </div>
    ${downloadOnly ? `<div class="download-only-callout">
      <strong>已完成直取下载</strong>
      <span>这个任务按“只下载本地”运行，未进入转写、切片和总结。可以先导出 media.mp4，或直接复用这个本地视频生成完整笔记。</span>
    </div>` : ""}
    ${fallbackNote ? `<div class="download-only-callout fallback-note-callout">
      <strong>已生成兜底笔记</strong>
      <span>视频直取失败，但已用页面文本/浏览器字幕生成可读笔记；诊断仍保留原始下载错误和资源证据。</span>
    </div>` : ""}
  </section>`;
}

async function rerunTaskFromMedia(taskId) {
  if (!taskId) return;
  els.resultMeta.textContent = "正在复用已下载视频创建完整笔记任务...";
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
  selectedTaskId = data.task_id;
  clearTaskCaches();
  selectedTab = "note";
  els.resultTabs.forEach(item => item.classList.toggle("active", item.dataset.tab === selectedTab));
  await loadTasks();
  focusResultPanelOnMobile();
}

function bindTaskOverviewActions() {
  document.querySelectorAll(".task-overview-actions button[data-rerun-from-media]").forEach(button => {
    button.onclick = () => rerunTaskFromMedia(button.dataset.rerunFromMedia);
  });
  document.querySelectorAll("[data-switch-result-tab]").forEach(button => {
    button.onclick = () => switchResultTab(button.dataset.switchResultTab);
  });
}

function switchResultTab(tabName) {
  if (!tabName || selectedTab === tabName) return;
  selectedTab = tabName;
  els.resultTabs.forEach(item => item.classList.toggle("active", item.dataset.tab === selectedTab));
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
      text: task.summary_warning ? "有降级提示，建议看诊断" : `${task.options?.whisper_model || "small"} · ${task.options?.transcriber || "ASR"}`,
      action: hasTranscript ? `<button type="button" data-switch-result-tab="transcript">看字幕</button>` : ""
    },
    {
      label: "本地产物",
      value: [hasMedia ? "视频" : "", hasBundle ? "资料包" : ""].filter(Boolean).join(" · ") || "等待产物",
      text: hasMedia ? "可复用 media.mp4 继续处理" : "任务完成后可导出",
      action: hasBundle ? `<a href="${escapeHtml(taskExportUrl(task, "bundle"))}">导出资料包</a>` : ""
    }
  ];
  return `<section class="study-map" aria-label="学习笔记导览">
    <div class="study-map-head">
      <div>
        <span>学习导览</span>
        <strong>${escapeHtml(task.title || task.id)}</strong>
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

function transcriptOverview(transcript, task) {
  const segments = transcript?.segments || [];
  const windows = visualWindows(task);
  const first = segments[0];
  const last = segments[segments.length - 1];
  const range = first && last ? `${fmt(first.start)} - ${fmt(last.end ?? last.start)}` : "无时间轴";
  const source = transcript?.source === "browser-subtitle"
    ? "浏览器字幕"
    : transcript?.source === "page-subtitle"
      ? "页面字幕"
      : transcript?.source || "转写";
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

function visualStudyCueHtml(window, transcript) {
  const segments = transcript?.segments || [];
  const matched = segments.filter(segment => segmentOverlapsWindow(segment, window)).slice(0, 4);
  if (matched.length) {
    return `<div class="visual-study-cues">
      ${matched.map(segment => `<div><time>${fmt(segment.start)}</time><span>${escapeHtml(segment.text)}</span></div>`).join("")}
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
        <strong>${escapeHtml(task.title || task.id || "画面切片")}</strong>
      </div>
      <div class="visual-study-head-actions">
        <small>${escapeHtml(headDetail)}</small>
        <a href="${escapeHtml(taskExportUrl(task, "visual-windows"))}">导出切片索引</a>
      </div>
    </div>
    <div class="visual-study-list">
      ${windows.map((window, index) => {
        const image = safeNoteMediaUrl(window.grid_url || "");
        return `<article class="visual-study-card">
          <figure>
            ${image ? `<img src="${image}" alt="${escapeHtml(window.id)} frame grid">` : `<div class="visual-study-placeholder">无画面</div>`}
            <figcaption>${escapeHtml(window.id || `W${String(index + 1).padStart(3, "0")}`)}</figcaption>
          </figure>
          <div class="visual-study-card-body">
            <span>窗口 ${String(index + 1).padStart(2, "0")}</span>
            <strong>${fmt(window.start)} - ${fmt(window.end)}</strong>
            ${visualStudyCueHtml(window, transcript)}
            ${visualStudyChecklistHtml(window, transcript)}
            <div class="visual-study-meta">
              <em>${Number(window.frame_count || 0)} 帧</em>
              <em>${escapeHtml(task.options?.grid_columns && task.options?.grid_rows ? `${task.options.grid_columns}x${task.options.grid_rows}` : "网格")}</em>
              <em>${escapeHtml(task.summary_source || "本地索引")}</em>
            </div>
            <div class="visual-study-actions">
              <button type="button" data-switch-result-tab="transcript">看对应字幕</button>
              <button type="button" data-switch-result-tab="note">回到笔记</button>
            </div>
          </div>
        </article>`;
      }).join("")}
    </div>
  </section>`;
}

function emptyResultWorkbench() {
  return `
    <section class="empty-workbench" aria-label="学习工作区起始页">
      <div class="empty-hero">
        <div class="empty-hero-copy">
          <span>LearnNote 工作区</span>
          <h3>把正在看的课程视频变成可复习的图文笔记</h3>
          <p>从扩展 Side Panel 直取当前页可访问的视频资源，或上传本地视频；后端会下载到本机、转写、切片、生成画面网格，再合并成学习笔记。</p>
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
    els.mediaButton.disabled = true;
    els.downloadButton.disabled = true;
    updateContinueFromMediaAction(null);
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
  els.bundleButton.disabled = !hasTaskBundle(task);
  els.diagnosticsButton.disabled = !hasTaskDiagnostics(task);
  els.mediaButton.disabled = !task.media_path;
  els.downloadButton.disabled = !hasNote;
  updateContinueFromMediaAction(task);

  if (selectedTab === "note") {
    lastNote = await noteForTask(task.id);
    els.detail.innerHTML = `
      <div class="note-shell">
        ${taskOverview(task)}
        ${failureGuide(task)}
        ${noteStudyBar(lastNote, task)}
        <div class="note-workbench">
          <article class="markdown-note">${lastNote ? markdownToHtml(lastNote) : task.media_path ? "<p>视频已下载到本地。可点击右上角视频按钮导出，不会继续转写、切片或总结。</p>" : "<p>笔记尚未生成。</p>"}</article>
          ${readingRail(lastNote, task)}
        </div>
      </div>
    `;
    bindTaskOverviewActions();
    return;
  }

  if (selectedTab === "frames") {
    const windows = visualWindows(task);
    if (!windows.length) {
      els.detail.className = "detail empty";
      els.detail.textContent = "画面切片尚未生成。";
      return;
    }
    const transcript = await transcriptForTask(task);
    els.detail.innerHTML = visualStudyDeck(task, transcript);
    bindTaskOverviewActions();
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
      ${diagnosticRecoveryHtml(task)}
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
          resourceSourceText(selected) || selected.source || "-",
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

  const transcript = await transcriptForTask(task) || {};
  if (!transcript.segments?.length) {
    els.detail.className = "detail empty";
    els.detail.textContent = transcript.warning || "转写尚未生成。";
    return;
  }
  els.detail.innerHTML = transcriptTimeline(transcript, task);
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
    const data = await fetch(`${API}/api/tasks/from-current-page`, {
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
    }).then(r => r.json());
    selectedTaskId = data.task_id;
    clearTaskCaches();
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
  const resource = manualUrlResource(url);
  if (!resource) {
    els.urlModeHint.textContent = "当前链接类型不能直接预检。请切换为视频直连、HLS 或 DASH，或直接创建任务交给页面扫描和 yt-dlp。";
    return;
  }
  els.startUrlButton.disabled = true;
  if (els.preflightUrlButton) els.preflightUrlButton.disabled = true;
  if (els.downloadUrlButton) els.downloadUrlButton.disabled = true;
  els.urlModeHint.textContent = "正在预检链接可访问性...";
  try {
    const data = await fetch(`${API}/api/media/preflight`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        page_url: url,
        resource,
        cookies: []
      })
    }).then(r => r.json());
    const result = data.preflight || {};
    els.urlModeHint.textContent = result.downloadable
      ? `预检通过：${result.kind || resource.kind} 可访问，${result.status_code ? `HTTP ${result.status_code}，` : ""}${fmtBytes(result.content_length) || `${result.bytes_checked || 0} B`}。`
      : `预检未通过：${result.message || result.code || "该链接暂不可直接下载"}`;
  } finally {
    els.startUrlButton.disabled = false;
    if (els.preflightUrlButton) els.preflightUrlButton.disabled = false;
    if (els.downloadUrlButton) els.downloadUrlButton.disabled = false;
  }
}

async function uploadSelectedFile() {
  const file = els.fileInput.files?.[0];
  if (!file) return;
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
    const response = await fetch(`${API}/api/tasks/from-local`, { method: "POST", body: form });
    const data = await response.json().catch(() => ({}));
    if (response.ok === false || !data?.task_id) {
      els.fileName.textContent = apiErrorMessage(data, "本地视频上传失败，请确认文件格式和后端状态。");
      return;
    }
    selectedTaskId = data.task_id;
    clearTaskCaches();
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
  els.sourceWorkflow.addEventListener("click", event => {
    const button = event.target.closest("[data-select-workflow-task]");
    if (!button) return;
    selectedTaskId = button.dataset.selectWorkflowTask;
    renderTasks();
    renderDetail();
    focusResultPanelOnMobile();
  });
}

if (els.browserRouteSummary) {
  els.browserRouteSummary.addEventListener("click", async event => {
    const selectButton = event.target.closest("[data-select-browser-task]");
    if (selectButton) {
      selectedTaskId = selectButton.dataset.selectBrowserTask;
      renderTasks();
      await renderDetail();
      focusResultPanelOnMobile();
      return;
    }
    const rerunButton = event.target.closest("[data-rerun-browser-task]");
    if (rerunButton) {
      await rerunTaskFromMedia(rerunButton.dataset.rerunBrowserTask);
    }
  });
}

if (els.urlMode) {
  els.urlMode.onchange = renderUrlModeHint;
  renderUrlModeHint();
}

els.resultTabs.forEach(tab => {
  tab.onclick = () => switchResultTab(tab.dataset.tab);
});

els.startUrlButton.onclick = () => startUrlTask("video");
if (els.preflightUrlButton) els.preflightUrlButton.onclick = preflightUrlTask;
if (els.downloadUrlButton) els.downloadUrlButton.onclick = () => startUrlTask("download_only");
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
if (els.continueFromMediaButton) els.continueFromMediaButton.onclick = () => rerunTaskFromMedia(selectedTaskId);
els.bundleButton.onclick = () => {
  if (!selectedTaskId) return;
  window.location.assign(`${API}/api/tasks/${encodeURIComponent(selectedTaskId)}/exports/bundle`);
};
els.diagnosticsButton.onclick = () => {
  if (!selectedTaskId) return;
  window.location.assign(`${API}/api/tasks/${encodeURIComponent(selectedTaskId)}/exports/diagnostics`);
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
    uploadSelectedFile();
  }
});

els.fileInput.onchange = () => {
  els.fileName.textContent = els.fileInput.files?.[0]?.name || "mp4 / flv / avi / webm / mov / mkv";
  setSource("local");
};

initializeResponsiveChrome();
initializeWorkspaceView();
renderSourceWorkflow();
checkHealth();
loadTasks();
setInterval(() => {
  checkHealth();
  loadTasks();
}, 3000);
