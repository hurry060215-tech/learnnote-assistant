const DEFAULT_BACKEND = "http://127.0.0.1:8765";

let backendUrl = DEFAULT_BACKEND;
let page = null;
let resources = [];
let selectedResourceUrl = "";
let currentTaskId = "";
let currentTask = null;
let selectedTab = "note";
let transcriptCache = null;
let lastNote = "";

const els = {
  backendStatus: document.querySelector("#backendStatus"),
  pageTitle: document.querySelector("#pageTitle"),
  pageUrl: document.querySelector("#pageUrl"),
  activeVideo: document.querySelector("#activeVideo"),
  resourceCount: document.querySelector("#resourceCount"),
  resources: document.querySelector("#resources"),
  summarizeButton: document.querySelector("#summarizeButton"),
  uploadButton: document.querySelector("#uploadButton"),
  fileInput: document.querySelector("#fileInput"),
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

const PIPELINE_STEPS = [
  { key: "downloading", label: "下载" },
  { key: "transcribing", label: "识别" },
  { key: "extracting_frames", label: "切片" },
  { key: "summarizing", label: "生成" },
  { key: "completed", label: "完成" }
];

const DOWNLOAD_ERROR_CODES = new Set(["no_media_found", "auth_required", "drm_or_encrypted", "download_forbidden", "unsupported_manifest"]);

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

async function loadSettings() {
  const data = await chrome.storage.local.get({ backendUrl: DEFAULT_BACKEND });
  backendUrl = data.backendUrl || DEFAULT_BACKEND;
}

async function saveSettings() {
  const next = prompt("后端地址", backendUrl);
  if (!next) return;
  backendUrl = next.replace(/\/$/, "");
  await chrome.storage.local.set({ backendUrl });
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
  const response = await chrome.runtime.sendMessage({ type: "get-current-context" });
  if (response.error) {
    els.resources.innerHTML = `<p class="muted">${escapeHtml(response.error)}</p>`;
    return;
  }
  page = response.page;
  resources = (response.resources || []).filter(item => item.kind !== "fragment");
  selectedResourceUrl = resources[0]?.url || "";
  renderContext();
}

function renderContext() {
  els.pageTitle.textContent = page?.title || "Untitled";
  els.pageUrl.textContent = page?.page_url || "";
  const active = page?.active_video;
  if (active?.src) {
    els.activeVideo.innerHTML = `播放状态：${active.paused ? "暂停" : "播放中"} · ${fmt(active.current_time)} / ${fmt(active.duration)} · ${active.width || 0}x${active.height || 0}`;
  } else {
    els.activeVideo.textContent = "未读取到 HTML5 播放状态";
  }
  els.resourceCount.textContent = String(resources.length);
  if (!resources.length) {
    els.resources.innerHTML = `<p class="muted">未检测到可直接下载的视频资源。</p>`;
    return;
  }
  els.resources.innerHTML = resources.map(item => `
    <button class="resource ${item.url === selectedResourceUrl ? "selected" : ""}" data-url="${escapeHtml(item.url)}">
      <span>
        <strong>${escapeHtml(item.label || item.kind || "media")}</strong>
        <small>${escapeHtml([
          item.is_main_video ? "主视频" : "",
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
  `).join("");
  document.querySelectorAll(".resource").forEach(button => {
    button.onclick = () => {
      selectedResourceUrl = button.dataset.url;
      renderContext();
    };
  });
}

function selectedResources() {
  const selected = resources.find(item => item.url === selectedResourceUrl);
  const rest = resources.filter(item => item.url !== selectedResourceUrl);
  return selected ? [selected, ...rest] : resources;
}

async function startTask(mode = "video") {
  if (!page) await collect();
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

async function uploadLocal() {
  const file = els.fileInput.files?.[0];
  if (!file) return;
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
          selected.status_code ? `HTTP ${selected.status_code}` : "",
          fmtBytes(selected.content_length)
        ].filter(Boolean).join(" · "))}</dd>
        <dt>错误</dt><dd>${escapeHtml(currentTask.error_detail || currentTask.error_code || "-")}</dd>
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
els.textButton.onclick = () => startTask("page_text");
els.uploadButton.onclick = () => els.fileInput.click();
els.fileInput.onchange = uploadLocal;
els.copyButton.onclick = () => navigator.clipboard.writeText(lastNote || "");
els.settingsButton.onclick = saveSettings;

loadSettings().then(() => Promise.all([health(), collect()]));
