const API = "";
let selectedTaskId = null;
let selectedTab = "transcript";

const healthEl = document.querySelector("#health");
const tasksEl = document.querySelector("#tasks");
const detailEl = document.querySelector("#detail");
const fileInput = document.querySelector("#fileInput");
const dropzone = document.querySelector("#dropzone");
const uploadButton = document.querySelector("#uploadButton");
const refreshButton = document.querySelector("#refreshButton");
const titleInput = document.querySelector("#titleInput");

function formatStatus(task) {
  if (task.status === "success") return "已完成";
  if (task.status === "failed") return task.error_code || "失败";
  if (task.status === "queued") return "排队中";
  return task.message || task.phase;
}

function fmt(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  return `${String(Math.floor(sec / 3600)).padStart(2, "0")}:${String(Math.floor((sec % 3600) / 60)).padStart(2, "0")}:${String(sec % 60).padStart(2, "0")}`;
}

async function checkHealth() {
  try {
    const res = await fetch(`${API}/health`);
    const data = await res.json();
    healthEl.className = data.ffmpeg ? "health ok" : "health bad";
    healthEl.textContent = data.ffmpeg ? "本地可用" : "后端可用，ffmpeg 缺失";
  } catch {
    healthEl.className = "health bad";
    healthEl.textContent = "后端未连接";
  }
}

async function loadTasks() {
  const res = await fetch(`${API}/api/tasks`);
  const data = await res.json();
  tasksEl.innerHTML = "";
  if (!data.tasks.length) {
    tasksEl.innerHTML = `<div class="detail empty">暂无任务。</div>`;
    return;
  }
  for (const task of data.tasks) {
    const item = document.createElement("button");
    item.className = `task status-${task.status}`;
    item.innerHTML = `
      <div>
        <strong>${escapeHtml(task.title)}</strong>
        <small>${formatStatus(task)} · ${task.phase}</small>
        <div class="progress"><span style="width:${task.progress || 0}%"></span></div>
      </div>
      <small>${task.progress || 0}%</small>
    `;
    item.onclick = () => {
      selectedTaskId = task.id;
      renderDetail();
    };
    tasksEl.appendChild(item);
  }
}

async function renderDetail() {
  if (!selectedTaskId) {
    detailEl.className = "detail empty";
    detailEl.textContent = "选择一个任务查看结果。";
    return;
  }
  detailEl.className = "detail";
  if (selectedTab === "note") {
    const text = await fetch(`${API}/api/tasks/${selectedTaskId}/note`).then(r => r.text());
    detailEl.innerHTML = `<pre class="note">${escapeHtml(text || "笔记尚未生成。")}</pre>`;
    return;
  }
  if (selectedTab === "frames") {
    const task = await fetch(`${API}/api/tasks/${selectedTaskId}`).then(r => r.json()).then(d => d.task);
    if (!task.frame_grids?.length) {
      detailEl.className = "detail empty";
      detailEl.textContent = "帧预览尚未生成。";
      return;
    }
    detailEl.innerHTML = `<div class="frames">${task.frame_grids.map(g => `<figure><img src="${g.url}" alt="frame grid"><figcaption>${fmt(g.start)} - ${fmt(g.end)}</figcaption></figure>`).join("")}</div>`;
    return;
  }
  const transcript = await fetch(`${API}/api/tasks/${selectedTaskId}/transcript`).then(r => r.json());
  if (!transcript.segments?.length) {
    detailEl.className = "detail empty";
    detailEl.textContent = transcript.warning || "转写尚未生成。";
    return;
  }
  detailEl.innerHTML = transcript.segments.map(seg => `<div class="line"><time>${fmt(seg.start)}</time><span>${escapeHtml(seg.text)}</span></div>`).join("");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[ch]));
}

async function uploadSelectedFile() {
  const file = fileInput.files?.[0];
  if (!file) {
    alert("请选择视频文件。");
    return;
  }
  const form = new FormData();
  form.append("file", file);
  form.append("title", titleInput.value || file.name);
  form.append("options", JSON.stringify({ visual_understanding: true, frame_interval: 20, grid_columns: 3, grid_rows: 3 }));
  uploadButton.disabled = true;
  uploadButton.textContent = "上传中...";
  try {
    const res = await fetch(`${API}/api/tasks/from-local`, { method: "POST", body: form });
    const data = await res.json();
    selectedTaskId = data.task_id;
    await loadTasks();
    await renderDetail();
  } finally {
    uploadButton.disabled = false;
    uploadButton.textContent = "上传并总结";
  }
}

dropzone.addEventListener("dragover", event => {
  event.preventDefault();
  dropzone.classList.add("drag");
});
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("drag"));
dropzone.addEventListener("drop", event => {
  event.preventDefault();
  dropzone.classList.remove("drag");
  if (event.dataTransfer.files?.[0]) fileInput.files = event.dataTransfer.files;
});
uploadButton.onclick = uploadSelectedFile;
refreshButton.onclick = () => loadTasks().then(renderDetail);
document.querySelectorAll(".tab").forEach(tab => {
  tab.onclick = () => {
    document.querySelectorAll(".tab").forEach(item => item.classList.remove("active"));
    tab.classList.add("active");
    selectedTab = tab.dataset.tab;
    renderDetail();
  };
});

checkHealth();
loadTasks();
setInterval(() => {
  checkHealth();
  loadTasks().then(renderDetail);
}, 3000);
