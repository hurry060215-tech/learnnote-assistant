const DEFAULT_BACKEND = "http://127.0.0.1:8765";
const HAS_EXTENSION_API = typeof chrome !== "undefined" && Boolean(chrome.runtime?.sendMessage && chrome.storage?.local);

let backendUrl = DEFAULT_BACKEND;
let page = null;
let resources = [];
let selectedResourceUrl = "";
let currentTaskId = "";
let currentTask = null;
let selectedTab = "note";
let transcriptCache = null;
let lastNote = "";
let preflight = null;
let preflightResourceUrl = "";

const els = {
  backendStatus: document.querySelector("#backendStatus"),
  pageTitle: document.querySelector("#pageTitle"),
  pageUrl: document.querySelector("#pageUrl"),
  activeVideo: document.querySelector("#activeVideo"),
  resourceCount: document.querySelector("#resourceCount"),
  readiness: document.querySelector("#readiness"),
  resources: document.querySelector("#resources"),
  resourceInspector: document.querySelector("#resourceInspector"),
  summarizeButton: document.querySelector("#summarizeButton"),
  preflightButton: document.querySelector("#preflightButton"),
  uploadButton: document.querySelector("#uploadButton"),
  fileInput: document.querySelector("#fileInput"),
  localDrop: document.querySelector("#localDrop"),
  localDropText: document.querySelector("#localDropText"),
  textButton: document.querySelector("#textButton"),
  redetectButton: document.querySelector("#redetectButton"),
  frameInterval: document.querySelector("#frameInterval"),
  gridSize: document.querySelector("#gridSize"),
  whisperModel: document.querySelector("#whisperModel"),
  noteStyle: document.querySelector("#noteStyle"),
  progressBar: document.querySelector("#progressBar"),
  stageRail: document.querySelector("#stageRail"),
  taskPhase: document.querySelector("#taskPhase"),
  taskMessage: document.querySelector("#taskMessage"),
  resultTabs: document.querySelectorAll(".result-tab"),
  result: document.querySelector("#result"),
  copyButton: document.querySelector("#copyButton"),
  downloadButton: document.querySelector("#downloadButton"),
  openWebButton: document.querySelector("#openWebButton"),
  settingsButton: document.querySelector("#settingsButton")
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[ch]));
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

function readOptions() {
  const [cols, rows] = els.gridSize.value.split("x").map(Number);
  return {
    visual_understanding: true,
    frame_interval: Number(els.frameInterval.value || 20),
    grid_columns: cols || 3,
    grid_rows: rows || 3,
    whisper_model: els.whisperModel.value || "small",
    note_style: els.noteStyle.value || "study"
  };
}

function isDownloadableResource(item) {
  return DOWNLOADABLE_KINDS.has(item?.kind);
}

function playbackText(match) {
  return ({
    "exact-src": "当前 src",
    "source-element": "当前 source",
    "same-frame": "同播放器 frame",
    "blob-same-frame": "blob 同 frame",
    "blob-source": "blob 来源映射",
    "recent-media-request": "最近播放请求",
    "same-site-request": "同站请求",
    "inferred-from-fragment": "分片推断"
  })[match] || match || "";
}

function pickDefaultResourceUrl(items, previousUrl = "") {
  if (previousUrl && items.some(item => item.url === previousUrl)) return previousUrl;
  const downloadable = items.filter(isDownloadableResource);
  const preferred = downloadable.find(item => item.playback_match || item.is_main_video) || downloadable[0];
  return preferred?.url || items[0]?.url || "";
}

function selectedResource() {
  return resources.find(item => item.url === selectedResourceUrl) || null;
}

function currentPreflight() {
  return preflight && preflightResourceUrl === selectedResourceUrl ? preflight : null;
}

function directnessText(item) {
  if (!item) return "未选择资源";
  if (isDownloadableResource(item)) {
    if (item.kind === "hls") return "HLS manifest，可交给 ffmpeg 合并";
    if (item.kind === "dash") return "DASH manifest，可交给 ffmpeg 合并";
    return "直接视频文件，可下载到本地处理";
  }
  if (item.kind === "blob") return "blob 线索，不可直接下载";
  if (item.kind === "fragment") return "分片线索，需要对应 manifest";
  if (item.kind === "subtitle") return "字幕轨，可辅助转写";
  return "媒体线索，需继续检测";
}

function requestEvidence(item) {
  if (!item) return "";
  return [
    item.source,
    playbackText(item.playback_match),
    item.is_main_video ? "主视频" : "",
    item.request_type,
    item.status_code ? `HTTP ${item.status_code}` : "",
    fmtBytes(item.content_length),
    item.frame_id !== null && item.frame_id !== undefined ? `frame ${item.frame_id}` : "",
    item.mime || ""
  ].filter(Boolean).join(" · ");
}

function resourceHint() {
  const downloadable = resources.filter(isDownloadableResource).length;
  const blobCount = resources.filter(item => item.kind === "blob").length;
  const fragmentCount = resources.filter(item => item.kind === "fragment").length;
  const playbackMatched = resources.some(item => item.playback_match || item.is_main_video);
  const activeBlob = page?.active_video?.src?.startsWith("blob:");
  if (downloadable && activeBlob) {
    return `<p class="resource-hint">当前播放器是 blob，已按同 frame / 最近媒体请求优先选择可直取候选。</p>`;
  }
  if (downloadable && playbackMatched) {
    return `<p class="resource-hint">已优先选择与当前播放状态匹配的可下载资源。</p>`;
  }
  if (!downloadable && (blobCount || fragmentCount)) {
    return `<p class="resource-hint warn">只检测到 blob 或分片线索，第一版不会录制或破解；可以继续播放几秒后重新检测，或改用本地视频上传。</p>`;
  }
  return "";
}

function renderReadiness() {
  const downloadable = resources.filter(isDownloadableResource);
  const selected = selectedResource();
  const hasBlob = resources.some(item => item.kind === "blob");
  const hasFragment = resources.some(item => item.kind === "fragment");
  const checked = currentPreflight();
  if (checked) {
    els.readiness.className = checked.downloadable ? "readiness" : checked.code === "drm_or_encrypted" ? "readiness bad" : "readiness warn";
    els.readiness.textContent = checked.downloadable
      ? `预检通过：后端可访问 ${checked.kind}，正式任务会完整下载。`
      : `预检未通过：${checked.message || checked.code || "候选不可直取"}`;
    return;
  }
  if (downloadable.length) {
    els.readiness.className = "readiness";
    els.readiness.textContent = `可直取候选 ${downloadable.length} 个；当前选择：${directnessText(selected || downloadable[0])}`;
    return;
  }
  if (hasBlob || hasFragment) {
    els.readiness.className = "readiness warn";
    els.readiness.textContent = "只看到 blob 或分片线索；不会录制，继续播放后重新检测，或拖入本地视频。";
    return;
  }
  els.readiness.className = "readiness bad";
  els.readiness.textContent = "当前页还没有可下载媒体候选；可先播放几秒后重新检测。";
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
  els.resourceInspector.innerHTML = `
    <strong>${escapeHtml(directnessText(item))}</strong>
    <span>${escapeHtml(requestEvidence(item) || "无请求证据")}</span>
    ${item.blob_url ? `<span>对应 blob：${escapeHtml(item.blob_url)}</span>` : ""}
    <span>复用请求头：${escapeHtml(requestHeaderNames(item))}</span>
    ${checked ? `<span>预检：${escapeHtml(checked.downloadable ? "通过" : checked.code || "未通过")} · ${escapeHtml(checked.status_code ? `HTTP ${checked.status_code}` : checked.strategy || "")} · ${escapeHtml(checked.content_type || "")} · ${escapeHtml(fmtBytes(checked.content_length) || `${checked.bytes_checked || 0} B`)}</span>` : ""}
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

async function health() {
  try {
    const data = await fetch(`${backendUrl}/health`).then(r => r.json());
    els.backendStatus.textContent = data.ffmpeg ? "本地后端可用" : "ffmpeg 缺失";
    els.backendStatus.style.color = data.ffmpeg ? "#159947" : "#c27803";
  } catch {
    els.backendStatus.textContent = "后端未连接";
    els.backendStatus.style.color = "#d92d20";
  }
}

async function collect() {
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
    return;
  }
  const response = await chrome.runtime.sendMessage({ type: "get-current-context" });
  if (response.error) {
    els.resources.innerHTML = `<p class="muted">${escapeHtml(response.error)}</p>`;
    return;
  }
  page = response.page;
  resources = response.resources || [];
  selectedResourceUrl = pickDefaultResourceUrl(resources, selectedResourceUrl);
  preflight = null;
  preflightResourceUrl = "";
  renderContext();
}

function renderContext() {
  els.pageTitle.textContent = page?.title || "Untitled";
  els.pageUrl.textContent = page?.page_url || "";
  const active = page?.active_video;
  const frames = page?.frames || [];
  if (active?.src) {
    els.activeVideo.innerHTML = `播放状态：${active.paused ? "暂停" : "播放中"} · ${fmt(active.current_time)} / ${fmt(active.duration)} · ${active.width || 0}x${active.height || 0} · frame ${active.frame_id ?? 0}`;
  } else {
    els.activeVideo.textContent = frames.length ? `未读取到 HTML5 播放状态 · 已扫描 ${frames.length} 个 frame` : "未读取到 HTML5 播放状态";
  }
  els.resourceCount.textContent = String(resources.length);
  renderReadiness();
  if (!resources.length) {
    els.resources.innerHTML = `<p class="muted">未检测到可直接下载的视频资源。</p>`;
    renderInspector();
    return;
  }
  els.resources.innerHTML = `${resourceHint()}${resources.map(item => `
    <button class="resource ${item.url === selectedResourceUrl ? "selected" : ""} ${isDownloadableResource(item) ? "" : "non-downloadable"} ${item.playback_match || item.is_main_video ? "playback" : ""}" data-url="${escapeHtml(item.url)}">
      <span>
        <strong>${escapeHtml(item.label || item.kind || "media")}</strong>
        <small>${escapeHtml([
          isDownloadableResource(item) ? "可直取" : "线索",
          item.is_main_video ? "主视频" : "",
          playbackText(item.playback_match),
          item.kind,
          item.source,
          item.request_type,
          item.status_code ? `HTTP ${item.status_code}` : "",
          fmtBytes(item.content_length),
          item.frame_id !== null && item.frame_id !== undefined ? `frame ${item.frame_id}` : "",
          item.mime || "unknown"
        ].filter(Boolean).join(" · "))}</small>
      </span>
      <span class="confidence">${item.score || 0}%</span>
    </button>
  `).join("")}`;
  document.querySelectorAll(".resource").forEach(button => {
    button.onclick = () => {
      selectedResourceUrl = button.dataset.url;
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

async function startTask(mode = "video") {
  if (!page) await collect();
  if (!HAS_EXTENSION_API) {
    els.taskMessage.textContent = "请在 Chrome/Edge 扩展 Side Panel 中读取当前页视频。";
    return;
  }
  const response = await chrome.runtime.sendMessage({
    type: "start-current-task",
    backendUrl,
    page,
    resources: mode === "video" ? selectedResources() : [],
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
  pollTask();
}

async function runPreflight() {
  if (!page) await collect();
  if (!HAS_EXTENSION_API) {
    els.taskMessage.textContent = "请在 Chrome/Edge 扩展 Side Panel 中预检当前页视频。";
    return;
  }
  const resource = selectedResource();
  if (!resource) {
    els.taskMessage.textContent = "没有可预检的候选资源。";
    return;
  }
  els.preflightButton.disabled = true;
  els.taskMessage.textContent = "正在预检直取可行性...";
  try {
    const response = await chrome.runtime.sendMessage({
      type: "preflight-current-resource",
      backendUrl,
      page,
      resource
    });
    if (response.error) {
      els.taskMessage.textContent = response.error;
      return;
    }
    preflight = response.preflight;
    preflightResourceUrl = resource.url;
    els.taskMessage.textContent = preflight.message || (preflight.downloadable ? "预检通过" : "预检未通过");
    renderContext();
  } finally {
    els.preflightButton.disabled = false;
  }
}

async function uploadLocal() {
  const file = els.fileInput.files?.[0];
  if (!file) return;
  els.localDropText.textContent = file.name;
  const form = new FormData();
  form.append("file", file);
  form.append("title", file.name);
  form.append("options", JSON.stringify(readOptions()));
  els.taskMessage.textContent = "上传本地视频...";
  const data = await fetch(`${backendUrl}/api/tasks/from-local`, { method: "POST", body: form }).then(r => r.json());
  currentTaskId = data.task_id;
  transcriptCache = null;
  lastNote = "";
  pollTask();
}

async function pollTask() {
  if (!currentTaskId) return;
  const data = await fetch(`${backendUrl}/api/tasks/${currentTaskId}`).then(r => r.json());
  currentTask = data.task;
  els.progressBar.style.width = `${currentTask.progress || 0}%`;
  renderStageRail(currentTask);
  els.taskPhase.textContent = currentTask.phase || "-";
  els.taskMessage.textContent = currentTask.error_detail || currentTask.message || currentTask.phase;
  if (currentTask.status === "success") {
    await loadResult();
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
  transcriptCache = await fetch(`${backendUrl}/api/tasks/${currentTaskId}/transcript`).then(r => r.json());
  lastNote = await fetch(`${backendUrl}/api/tasks/${currentTaskId}/note`).then(r => r.text());
  renderResult();
}

function renderResult() {
  const hasNote = Boolean(currentTaskId) && (Boolean(currentTask?.note_path) || currentTask?.status === "success");
  els.copyButton.disabled = !hasNote;
  els.downloadButton.disabled = !hasNote;
  if (!currentTask) {
    els.result.textContent = "任务完成后显示结果。";
    return;
  }
  if (selectedTab === "note") {
    els.result.className = "result-body";
    els.result.innerHTML = `<pre class="note">${escapeHtml(lastNote || currentTask.message || "笔记尚未生成。")}</pre>`;
    return;
  }
  if (selectedTab === "frames") {
    if (!currentTask.frame_grids?.length) {
      els.result.className = "result-body muted";
      els.result.textContent = "画面切片尚未生成。";
      return;
    }
    els.result.className = "result-body";
    els.result.innerHTML = `<div class="frame-grid">${currentTask.frame_grids.slice(0, 8).map(grid => `
      <figure>
        <img src="${escapeHtml(grid.url)}" alt="frame grid">
        <figcaption>${fmt(grid.start)} - ${fmt(grid.end)}</figcaption>
      </figure>
    `).join("")}</div>`;
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
      <dl class="diagnostics">
        <dt>状态</dt><dd>${escapeHtml(currentTask.status)} / ${escapeHtml(currentTask.phase)} / ${currentTask.progress || 0}%</dd>
        <dt>策略</dt><dd>${selected.url ? "浏览器候选资源优先" : "页面解析 fallback"}</dd>
        <dt>资源</dt><dd>${escapeHtml(selected.url || "未选择直接资源")}</dd>
        <dt>类型</dt><dd>${escapeHtml([
          selected.kind || "-",
          selected.source || "-",
          selected.is_main_video ? "主视频" : "",
          playbackText(selected.playback_match),
          selected.status_code ? `HTTP ${selected.status_code}` : "",
          fmtBytes(selected.content_length)
        ].filter(Boolean).join(" · "))}</dd>
        <dt>请求头</dt><dd>${escapeHtml(requestHeaderNames(selected))}</dd>
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
  els.result.innerHTML = transcript.segments.slice(0, 100).map(seg => `<div class="line"><time>${fmt(seg.start)}</time><span>${escapeHtml(seg.text)}</span></div>`).join("");
}

els.resultTabs.forEach(tab => {
  tab.onclick = () => {
    selectedTab = tab.dataset.tab;
    els.resultTabs.forEach(item => item.classList.toggle("active", item === tab));
    renderResult();
  };
});

els.redetectButton.onclick = collect;
els.summarizeButton.onclick = () => startTask("video");
els.preflightButton.onclick = runPreflight;
els.textButton.onclick = () => startTask("page_text");
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
els.copyButton.onclick = () => navigator.clipboard.writeText(lastNote || "");
els.downloadButton.onclick = () => {
  if (!currentTaskId) return;
  const url = `${backendUrl}/api/tasks/${encodeURIComponent(currentTaskId)}/exports/markdown`;
  if (HAS_EXTENSION_API) chrome.tabs.create({ url });
  else window.open(url, "_blank", "noopener");
};
els.openWebButton.onclick = () => {
  if (HAS_EXTENSION_API) chrome.tabs.create({ url: backendUrl });
  else window.open(backendUrl, "_blank", "noopener");
};
els.settingsButton.onclick = saveSettings;

loadSettings().then(() => Promise.all([health(), collect()]));
