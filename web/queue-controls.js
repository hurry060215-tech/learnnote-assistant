export function mountQueueControls(panel, task, api, refresh) {
  if (!task.queue || !["queued", "running"].includes(task.queue.state)) return;
  const controls = document.createElement("div"); controls.className = "task-queue-controls tool-actions";
  const pause = document.createElement("button"); pause.type = "button";
  pause.textContent = task.queue.paused ? "继续排队任务" : "暂停新任务开始";
  const status = document.createElement("span"); status.className = "muted"; status.setAttribute("role", "status");
  status.textContent = task.queue.paused ? "队列已暂停；运行中的任务继续，待处理任务和优先级保留。" : "暂停只阻止新任务开始，不中断正在进行的处理。";
  async function change(button, work) {
    button.disabled = true;
    try { await work(); await refresh(); }
    catch (error) { if (controls.isConnected) status.textContent = String(error.message || "更新失败"); }
    finally { if (controls.isConnected) button.disabled = false; }
  }
  pause.addEventListener("click", () => change(pause, () => api("/api/queue/pause", {
    method: "PUT", body: JSON.stringify({ paused: !task.queue.paused }) } )));
  controls.append(pause);
  if (task.queue.state === "queued") {
    const label = document.createElement("label"); label.textContent = "任务优先级";
    const select = document.createElement("select"); select.setAttribute("aria-label", "任务优先级");
    for (const [value, text] of [[0, "正常"], [5, "优先"]]) {
      const option = document.createElement("option"); option.value = String(value); option.textContent = text; select.append(option);
    }
    select.value = String(task.queue.priority || 0);
    select.addEventListener("change", () => change(select, () => api(`/api/queue/tasks/${encodeURIComponent(task.id)}/priority`, {
      method: "PUT", body: JSON.stringify({ priority: Number(select.value) }) } )));
    label.append(select); controls.append(label);
  }
  controls.append(status); panel.append(controls);
}
