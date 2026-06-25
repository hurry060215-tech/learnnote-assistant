const API = "";
const MEDIA_RE = /\.(mp4|m4v|webm|mov|mkv)(\?|#|$)/i;
const HLS_RE = /\.(m3u8|mpd)(\?|#|$)/i;

let selectedSource = "url";
let selectedTaskId = null;
let selectedTab = "note";
let lastNote = "";
let tasks = [];

const els = {
  health: document.querySelector("#health"),
  refreshButton: document.querySelector("#refreshButton"),
  sourceTabs: document.querySelectorAll(".source-tab"),
  panes: document.querySelectorAll(".source-pane"),
  urlInput: document.querySelector("#urlInput"),
  titleInput: document.querySelector("#titleInput"),
  startUrlButton: document.querySelector("#startUrlButton"),
  fileInput: document.querySelector("#fileInput"),
  dropzone: document.querySelector("#dropzone"),
  uploadButton: document.querySelector("#uploadButton"),
  frameInterval: document.querySelector("#frameInterval"),
  gridSize: document.querySelector("#gridSize"),
  whisperModel: document.querySelector("#whisperModel"),
  noteStyle: document.querySelector("#noteStyle"),
  taskCount: document.querySelector("#taskCount"),
  successCount: document.querySelector("#successCount"),
  runningCount: document.querySelector("#runningCount"),
  failedCount: document.querySelector("#failedCount"),
  tasks: document.querySelector("#tasks"),
  selectedSource: document.querySelector("#selectedSource"),
  selectedTitle: document.querySelector("#selectedTitle"),
  resultTabs: document.querySelectorAll(".result-tab"),
  detail: document.querySelector("#detail"),
  copyButton: document.querySelector("#copyButton")
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

async function checkHealth() {
  try {
    const data = await fetch(`${API}/health`).then(r => r.json());
    els.health.className = data.ffmpeg ? "health ok" : "health bad";
    els.health.textContent = data.ffmpeg ? "本地后端可用" : "ffmpeg 缺失";
  } catch {
    els.health.className = "health bad";
    els.health.textContent = "后端未连接";
  }
}

function setSource(source) {
  selectedSource = source;
  els.sourceTabs.forEach(tab => tab.classList.toggle("active", tab.dataset.source === source));
  els.panes.forEach(pane => pane.classList.toggle("active", pane.id === `${source}Source`));
}

async function loadTasks() {
  const data = await fetch(`${API}/api/tasks`).then(r => r.json());
  tasks = data.tasks || [];
  if (!selectedTaskId && tasks[0]) selectedTaskId = tasks[0].id;
  renderTasks();
  await renderDetail();
}

function renderTasks() {
  els.taskCount.textContent = String(tasks.length);
  els.successCount.textContent = String(tasks.filter(task => task.status === "success").length);
  els.runningCount.textContent = String(tasks.filter(task => task.status === "running" || task.status === "queued").length);
  els.failedCount.textContent = String(tasks.filter(task => task.status === "failed").length);

  if (!tasks.length) {
    els.tasks.innerHTML = `<div class="detail empty">暂无任务。</div>`;
    return;
  }

  els.tasks.innerHTML = tasks.map(task => `
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
    button.onclick = () => {
      selectedTaskId = button.dataset.id;
      renderTasks();
      renderDetail();
    };
  });
}

async function taskRecord() {
  if (!selectedTaskId) return null;
  return fetch(`${API}/api/tasks/${selectedTaskId}`).then(r => r.json()).then(d => d.task);
}

async function renderDetail() {
  const task = await taskRecord();
  if (!task) {
    els.selectedTitle.textContent = "选择一个任务";
    els.selectedSource.textContent = "结果工作区";
    els.detail.className = "detail empty";
    els.detail.textContent = "任务完成后显示结构化结果。";
    return;
  }

  els.selectedTitle.textContent = task.title || task.id;
  els.selectedSource.textContent = `${sourceText(task)} · ${statusText(task)}`;
  els.detail.className = "detail";

  if (selectedTab === "note") {
    lastNote = await fetch(`${API}/api/tasks/${task.id}/note`).then(r => r.text());
    els.detail.innerHTML = `<pre class="note">${escapeHtml(lastNote || "笔记尚未生成。")}</pre>`;
    return;
  }

  if (selectedTab === "frames") {
    if (!task.frame_grids?.length) {
      els.detail.className = "detail empty";
      els.detail.textContent = "画面切片尚未生成。";
      return;
    }
    els.detail.innerHTML = `<div class="frames">${task.frame_grids.map(grid => `
      <figure>
        <img src="${escapeHtml(grid.url)}" alt="frame grid">
        <figcaption>${fmt(grid.start)} - ${fmt(grid.end)} · ${grid.frame_count} 帧</figcaption>
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
            <div>
              <strong>${escapeHtml(attempt.strategy)} · ${escapeHtml(attempt.status)}</strong>
              <small>${escapeHtml([
                attempt.code,
                attempt.status_code ? `HTTP ${attempt.status_code}` : "",
                fmtBytes(attempt.bytes_downloaded || attempt.content_length),
                attempt.kind,
                attempt.source
              ].filter(Boolean).join(" · "))}</small>
            </div>
            <p>${escapeHtml(attempt.message || attempt.url || "-")}</p>
            ${attempt.url ? `<code>${escapeHtml(attempt.url)}</code>` : ""}
          </div>
        `).join("")}
      </div>
    ` : "暂无下载尝试记录";
    els.detail.innerHTML = `
      <dl class="diagnostics">
        <dt>任务 ID</dt><dd>${escapeHtml(task.id)}</dd>
        <dt>状态</dt><dd>${escapeHtml(task.status)} / ${escapeHtml(task.phase)} / ${task.progress || 0}%</dd>
        <dt>来源</dt><dd>${escapeHtml(task.page_url || task.source_type)}</dd>
        <dt>下载策略</dt><dd>${selected.url ? "浏览器候选资源优先" : "页面解析 fallback"}</dd>
        <dt>已选资源</dt><dd>${escapeHtml(selected.url || "未选择直接资源")}</dd>
        <dt>资源类型</dt><dd>${escapeHtml([
          selected.kind || "-",
          selected.source || "-",
          selected.is_main_video ? "主视频" : "",
          selected.request_type || "",
          selected.status_code ? `HTTP ${selected.status_code}` : "",
          fmtBytes(selected.content_length),
          selected.mime || "-"
        ].filter(Boolean).join(" · "))}</dd>
        <dt>媒体文件</dt><dd>${escapeHtml(task.media_path || "-")}</dd>
        <dt>音频文件</dt><dd>${escapeHtml(task.audio_path || "-")}</dd>
        <dt>字幕文件</dt><dd>${escapeHtml(task.subtitle_path || "-")}</dd>
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
  els.detail.innerHTML = transcript.segments.map(seg => `<div class="line"><time>${fmt(seg.start)}</time><span>${escapeHtml(seg.text)}</span></div>`).join("");
}

async function startUrlTask() {
  const url = els.urlInput.value.trim();
  if (!url) {
    els.urlInput.focus();
    return;
  }
  const kind = mediaKind(url);
  const resources = kind === "unknown" ? [] : [{
    url,
    source: "manual",
    kind,
    mime: kind === "video" ? "video/mp4" : "",
    score: kind === "unknown" ? 0 : 96,
    label: "手动链接"
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
  } finally {
    els.uploadButton.disabled = false;
    els.uploadButton.textContent = "上传并生成";
  }
}

els.sourceTabs.forEach(tab => {
  tab.onclick = () => setSource(tab.dataset.source);
});

els.resultTabs.forEach(tab => {
  tab.onclick = () => {
    selectedTab = tab.dataset.tab;
    els.resultTabs.forEach(item => item.classList.toggle("active", item === tab));
    renderDetail();
  };
});

els.startUrlButton.onclick = startUrlTask;
els.uploadButton.onclick = uploadSelectedFile;
els.refreshButton.onclick = () => loadTasks();
els.copyButton.onclick = () => navigator.clipboard.writeText(lastNote || "");

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
    setSource("local");
  }
});

els.fileInput.onchange = () => setSource("local");

checkHealth();
loadTasks();
setInterval(() => {
  checkHealth();
  loadTasks();
}, 3000);
