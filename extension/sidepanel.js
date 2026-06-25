const DEFAULT_BACKEND = "http://127.0.0.1:8765";
let backendUrl = DEFAULT_BACKEND;
let page = null;
let resources = [];
let selectedResourceUrl = "";
let currentTaskId = "";
let lastNote = "";

const els = {
  backendStatus: document.querySelector("#backendStatus"),
  pageTitle: document.querySelector("#pageTitle"),
  pageUrl: document.querySelector("#pageUrl"),
  resources: document.querySelector("#resources"),
  summarizeButton: document.querySelector("#summarizeButton"),
  uploadButton: document.querySelector("#uploadButton"),
  fileInput: document.querySelector("#fileInput"),
  textButton: document.querySelector("#textButton"),
  redetectButton: document.querySelector("#redetectButton"),
  progressBar: document.querySelector("#progressBar"),
  taskMessage: document.querySelector("#taskMessage"),
  transcript: document.querySelector("#transcript"),
  note: document.querySelector("#note"),
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
    const response = await fetch(`${backendUrl}/health`);
    const data = await response.json();
    els.backendStatus.textContent = data.ffmpeg ? "本地可用" : "后端可用，ffmpeg 缺失";
    els.backendStatus.style.color = data.ffmpeg ? "#16a34a" : "#d97706";
  } catch {
    els.backendStatus.textContent = "后端未连接";
    els.backendStatus.style.color = "#dc2626";
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
  if (!resources.length) {
    els.resources.innerHTML = `<p class="muted">没有检测到可直接下载的视频资源。可尝试“只总结当前页面文本”或上传本地视频。</p>`;
    return;
  }
  els.resources.innerHTML = resources.map(item => `
    <button class="resource ${item.url === selectedResourceUrl ? "selected" : ""}" data-url="${escapeHtml(item.url)}">
      <span class="play">▶</span>
      <span>
        <strong>${escapeHtml(item.label || item.kind || "media")}</strong>
        <small>${escapeHtml(item.kind)} · ${escapeHtml(item.source)} · ${escapeHtml(item.mime || "")}</small>
      </span>
      <span class="confidence">置信度：${item.score || 0}%</span>
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
    options: { visual_understanding: true, frame_interval: 20, grid_columns: 3, grid_rows: 3 }
  });
  if (response.error) {
    els.taskMessage.textContent = response.error;
    return;
  }
  currentTaskId = response.task_id;
  pollTask();
}

async function uploadLocal() {
  const file = els.fileInput.files?.[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  form.append("title", file.name);
  form.append("options", JSON.stringify({ visual_understanding: true, frame_interval: 20, grid_columns: 3, grid_rows: 3 }));
  els.taskMessage.textContent = "上传本地视频...";
  const response = await fetch(`${backendUrl}/api/tasks/from-local`, { method: "POST", body: form });
  const data = await response.json();
  currentTaskId = data.task_id;
  pollTask();
}

async function pollTask() {
  if (!currentTaskId) return;
  const data = await fetch(`${backendUrl}/api/tasks/${currentTaskId}`).then(r => r.json());
  const task = data.task;
  els.progressBar.style.width = `${task.progress || 0}%`;
  els.taskMessage.textContent = task.error_detail || task.message || task.phase;
  if (task.status === "success") {
    await loadResult();
    return;
  }
  if (task.status !== "failed") {
    setTimeout(pollTask, 2500);
  }
}

async function loadResult() {
  const transcript = await fetch(`${backendUrl}/api/tasks/${currentTaskId}/transcript`).then(r => r.json());
  if (transcript.segments?.length) {
    els.transcript.innerHTML = transcript.segments.slice(0, 80).map(seg => `<div class="line"><time>${fmt(seg.start)}</time><span>${escapeHtml(seg.text)}</span></div>`).join("");
  } else {
    els.transcript.textContent = transcript.warning || "没有字幕。";
  }
  lastNote = await fetch(`${backendUrl}/api/tasks/${currentTaskId}/note`).then(r => r.text());
  els.note.textContent = lastNote || "笔记尚未生成。";
}

els.redetectButton.onclick = collect;
els.summarizeButton.onclick = () => startTask("video");
els.textButton.onclick = () => startTask("page_text");
els.uploadButton.onclick = () => els.fileInput.click();
els.fileInput.onchange = uploadLocal;
els.copyButton.onclick = () => navigator.clipboard.writeText(lastNote || els.note.textContent || "");
els.settingsButton.onclick = saveSettings;

loadSettings().then(() => Promise.all([health(), collect()]));
