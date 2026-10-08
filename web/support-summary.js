// Local preview and file export. There is intentionally no remote sender.
export async function mountSupportSummary(host, api) {
  const panel = document.createElement("section");
  panel.className = "support-summary";
  const heading = document.createElement("h3"); heading.textContent = "本地连接与首次使用检查";
  const hint = document.createElement("p");
  hint.textContent = "仅保留 30 天的本地里程碑和错误类别，不记录课程、网址、标题、密钥或设备标识。不会自动发送。删除后同时关闭记录，需主动开启才会恢复。";
  const message = document.createElement("p"); message.setAttribute("role", "status");
  const controls = document.createElement("div"); controls.className = "tool-actions";
  const toggle = document.createElement("button"); toggle.type = "button";
  const clear = document.createElement("button"); clear.type = "button"; clear.textContent = "删除并关闭本地记录";
  const fields = document.createElement("fieldset");
  const legend = document.createElement("legend"); legend.textContent = "选择要导出的字段"; fields.append(legend);
  const preview = document.createElement("pre"); preview.setAttribute("aria-label", "支持摘要逐字段预览");
  const consentLabel = document.createElement("label");
  consentLabel.className = "check";
  const consent = document.createElement("input"); consent.type = "checkbox";
  consentLabel.append(consent, document.createTextNode("我已检查以下字段，仅保存这个摘要文件"));
  const save = document.createElement("button"); save.type = "button"; save.textContent = "保存已预览摘要"; save.disabled = true;
  const cancel = document.createElement("button"); cancel.type = "button"; cancel.textContent = "取消导出";
  const help = document.createElement("a"); help.textContent = "手动打开项目支持页面";
  help.href = "https://github.com/hurry060215-tech/learnnote-assistant/issues";
  help.target = "_blank"; help.rel = "noopener noreferrer"; help.referrerPolicy = "no-referrer";
  controls.append(toggle, clear); panel.append(heading, hint, controls, fields, preview, consentLabel, save, cancel, help, message);
  host.append(panel);
  const labels = { installed: "已启动本地服务", desktop_connected: "扩展已连接本地服务",
    first_task_started: "首个任务已开始", first_task_succeeded: "首个任务已完成",
    error_categories: "错误类别", version: "应用版本" };
  let state, checked = new Set(), visible = "", revision = 0;
  async function renderPreview() {
    const current = ++revision;
    visible = ""; preview.textContent = "正在更新预览…";
    consent.checked = false; consent.disabled = true; save.disabled = true;
    const value = await api("/api/support/preview", { method: "POST", body: JSON.stringify({ fields: [...checked] }) });
    if (current !== revision || !panel.isConnected) return;
    visible = JSON.stringify(value, null, 2); preview.textContent = visible; consent.disabled = false;
  }
  async function refresh() {
    state = await api("/api/support/activation");
    if (!panel.isConnected) return;
    toggle.textContent = state.enabled ? "关闭本地记录" : "开启本地记录";
    fields.replaceChildren(legend);
    checked = new Set(Object.keys(labels));
    for (const [key, label] of Object.entries(labels)) {
      const row = document.createElement("label"), input = document.createElement("input");
      row.className = "check";
      input.type = "checkbox"; input.checked = true;
      input.addEventListener("change", () => { if (input.checked) checked.add(key); else checked.delete(key); safely(renderPreview); });
      row.append(input, document.createTextNode(label)); fields.append(row);
    }
    await renderPreview();
  }
  async function safely(fn) {
    try { await fn(); message.textContent = ""; }
    catch (error) { if (panel.isConnected) message.textContent = String(error.message || "读取失败"); }
  }
  toggle.addEventListener("click", () => safely(async () => {
    await api("/api/support/activation", { method: "PUT", body: JSON.stringify({ enabled: !state.enabled }) }); await refresh();
  }));
  clear.addEventListener("click", () => safely(async () => {
    revision++; visible = ""; preview.textContent = "正在删除本地记录…"; consent.checked = false; consent.disabled = true; save.disabled = true;
    await api("/api/support/activation", { method: "DELETE" }); await refresh();
  }));
  consent.addEventListener("change", () => { save.disabled = !consent.checked || !visible; });
  cancel.addEventListener("click", () => { revision++; visible = ""; preview.textContent = "导出已取消，未发送任何内容。"; consent.checked = false; save.disabled = true; });
  save.addEventListener("click", () => {
    if (!consent.checked || !visible || save.disabled) return;
    const url = URL.createObjectURL(new Blob([visible], { type: "application/json;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = "learnnote-support-summary.json";
    link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    message.textContent = "已保存本地文件。是否分享、发给谁以及何时分享，由你决定。";
  });
  await safely(refresh);
  return panel;
}
