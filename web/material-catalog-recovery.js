const endpoint = "/api/library/catalog";
const maxSnapshotBytes = 128 * 1024 * 1024;

export function mountMaterialCatalogRecovery(container, { api, isCurrent = () => true, onRecovered = async () => {} }) {
  const make = (tag, text = "", id = "") => {
    const element = document.createElement(tag);
    if (text) element.textContent = text;
    if (id) element.id = id;
    return element;
  };
  const root = make("section", "", "materialCatalogRecovery");
  root.className = "material-catalog-recovery";
  root.style.overflowWrap = "anywhere";
  root.setAttribute("aria-label", "学习资料目录恢复");
  const heading = make("h3", "恢复学习资料目录");
  const status = make("p", "正在检查学习资料目录…", "materialCatalogStatus");
  status.setAttribute("role", "status");
  const retry = make("button", "重新检查目录", "materialCatalogCheck"); retry.type = "button";
  const scope = make("p", "请选择你确认要恢复的 SQLite 备份；以所选快照中的资料编号、编码选择和关联信息为准。目录元数据丢失后，无法证明所选快照就是最新的历史版本。仅有原文件无法找回丢失的编号、编码选择或历史关联。这里只恢复文档资料目录与出处索引；视频资料登记需要原任务，任务索引请使用上方的独立恢复入口。");
  scope.className = "muted";
  const label = make("label", "选择资料目录快照（.sqlite3，最多 128 MB）"); label.htmlFor = "materialCatalogSnapshot";
  const input = make("input", "", "materialCatalogSnapshot"); input.type = "file"; input.accept = ".sqlite3";
  input.style.maxWidth = "100%";
  const selected = make("p", "尚未选择快照。", "materialCatalogSelected");
  const previewButton = make("button", "预览目录恢复", "materialCatalogPreview"); previewButton.type = "button";
  const applyButton = make("button", "确认恢复学习资料目录", "materialCatalogApply"); applyButton.type = "button"; applyButton.className = "primary";
  const actions = make("div"); actions.className = "tool-actions"; actions.append(previewButton, applyButton);
  const progress = make("p", "先选择快照并预览，核对每份资料后再确认恢复。", "materialCatalogProgress"); progress.setAttribute("role", "status");
  const results = make("div", "", "materialCatalogResults");
  const taskButton = make("button", "从本机任务文件重建任务索引", "materialCatalogRebuildTasks"); taskButton.type = "button";
  const taskHint = make("p", "仅根据本机 task.json 重建任务索引与任务出处，不恢复文档目录。操作后必须重新预览已选的文档快照。"); taskHint.className = "muted";
  root.append(heading, status, retry, scope, label, input, selected, actions, progress, results, make("h3", "单独重建任务索引"), taskHint, taskButton);
  container.append(root);
  let sequence = 0, statusSequence = 0, selectedFile = null, preview = null, previewing = false, applying = false;
  const active = () => root.isConnected && isCurrent();
  const valid = (ticket, file) => active() && ticket === sequence && file === selectedFile;
  const canApply = () => preview?.can_apply === true && preview.recovery_scope === "material_catalog_only"
    && typeof preview.preview_token === "string" && Boolean(preview.preview_token)
    && Number(preview.recoverable_count) > 0 && !preview.unresolved?.length
    && Array.isArray(preview.materials) && preview.materials.some(item => item.status === "recoverable")
    && preview.materials.every(item => ["recoverable", "unchanged", "excluded"].includes(item.status));
  function controls() {
    input.disabled = applying;
    previewButton.disabled = !selectedFile || previewing || applying;
    applyButton.disabled = previewing || applying || !canApply();
    taskButton.disabled = previewing || applying;
  }
  function addRows(items, unresolved = false) {
    const list = make("ul"); list.className = "tool-list";
    for (const item of items || []) {
      const row = make("li"); row.dataset.status = unresolved ? "unresolved" : item.status;
      const labels = { recoverable: "可恢复", unchanged: "无需更改", excluded: "不在恢复范围", unresolved: "无法恢复" };
      row.append(make("strong", `${item.title || item.material_id || "未知资料"} · ${labels[row.dataset.status] || "无法确认"}`));
      if (item.title && item.material_id) row.append(make("p", `资料编号：${item.material_id}`));
      row.append(make("p", item.reason || (row.dataset.status === "recoverable" ? "将按所选快照恢复目录与出处。" : row.dataset.status === "unchanged" ? "现有资料与快照一致。" : "缺少可用的恢复信息，请核对快照与原文件。")));
      list.append(row);
    }
    results.append(list);
  }
  function errorText(error) {
    return `${error?.message || "目录恢复请求失败，请重试。"}${error?.code ? `（${error.code}）` : ""}`;
  }
  async function checkStatus() {
    const ticket = ++statusSequence;
    retry.disabled = true;
    try {
      const value = await api(`${endpoint}/status`);
      if (!active() || ticket !== statusSequence) return;
      const labels = { healthy: "正常", missing: "缺失", corrupt: "损坏", incomplete: "不完整" };
      status.textContent = `学习资料目录：${labels[value.state] || "状态未知"}。${value.message || ""}${value.orphaned_material_ids?.length ? ` 检测到 ${value.orphaned_material_ids.length} 份原文件缺少目录记录。` : ""}`;
      root.dataset.state = value.state;
    } catch (error) {
      if (active() && ticket === statusSequence) status.textContent = `目录状态检查失败：${errorText(error)}`;
    } finally {
      if (active() && ticket === statusSequence) retry.disabled = false;
    }
  }
  input.addEventListener("change", () => {
    if (!active()) return;
    sequence++; preview = null; previewing = false; results.replaceChildren();
    selectedFile = input.files?.[0] || null;
    selected.textContent = selectedFile ? `已选择：${selectedFile.name}` : "尚未选择快照。";
    if (selectedFile && (!/\.sqlite3$/i.test(selectedFile.name) || !selectedFile.size || selectedFile.size > maxSnapshotBytes)) {
      progress.textContent = "请选择非空的 .sqlite3 快照，大小不能超过 128 MB。";
      selectedFile = null;
    } else progress.textContent = selectedFile ? "请先预览这份快照；重新选择文件后必须重新预览。" : "先选择快照并预览，核对每份资料后再确认恢复。";
    controls();
  });
  previewButton.addEventListener("click", async () => {
    if (!active() || previewButton.disabled || previewing || applying || !selectedFile) return;
    const ticket = ++sequence, file = selectedFile;
    preview = null; previewing = true; results.replaceChildren(); controls();
    progress.textContent = "正在核对所选快照与本机原文件；此预览不会恢复数据…";
    const body = new FormData(); body.append("file", file);
    try {
      const value = await api(`${endpoint}/recovery/preview`, { method: "POST", body });
      if (!valid(ticket, file)) return;
      preview = value;
      results.append(make("p", `快照：${file.name} · SHA-256：${value.snapshot_sha256 || "未知"}`));
      addRows(value.materials);
      const listed = new Set((value.materials || []).filter(item => item.status === "unresolved").map(item => item.material_id));
      addRows((value.unresolved || []).filter(item => !listed.has(item.material_id)), true);
      progress.textContent = `${value.message || "预览完成。"} ${canApply() ? `可恢复 ${value.recoverable_count} 份资料。请核对后确认；执行前会创建回滚快照。` : "当前预览不能执行恢复。请查看逐项原因；没有可恢复资料或存在未解决项时不会写入。"}`;
    } catch (error) {
      if (valid(ticket, file)) progress.textContent = `预览失败：${errorText(error)}`;
    } finally {
      if (valid(ticket, file)) { previewing = false; controls(); }
    }
  });
  applyButton.addEventListener("click", async () => {
    if (!active() || applyButton.disabled || applying || previewing || !selectedFile || !canApply()) return;
    const ticket = ++sequence, file = selectedFile, token = preview.preview_token;
    applying = true; controls();
    progress.textContent = "正在按已核对的快照恢复目录与出处索引…关闭此窗口不会取消已开始的恢复；重新打开后可检查结果。";
    const body = new FormData(); body.append("file", file); body.append("preview_token", token);
    try {
      const value = await api(`${endpoint}/recovery/apply`, { method: "POST", body });
      if (!valid(ticket, file)) return;
      preview = null; results.replaceChildren();
      results.append(make("p", value.message || "恢复请求已完成。"));
      if (value.rollback_snapshot_created && value.rollback_directory) results.append(make("p", `回滚备份位置：数据文件夹/exports/${value.rollback_directory}`));
      addRows(value.unresolved, true);
      progress.textContent = `${value.status === "partial" || value.unresolved?.length ? "部分恢复完成" : "恢复完成"}：${Number(value.restored_material_count || 0)} 份资料，${Number(value.restored_evidence_count || 0)} 条出处。${value.rollback_snapshot_created ? "已创建回滚快照。" : "未收到回滚快照确认，请检查本地备份。"}`;
      await checkStatus();
      if (!valid(ticket, file)) return;
      try { await onRecovered(value); }
      catch (error) { if (valid(ticket, file)) progress.textContent += ` 列表刷新失败：${errorText(error)} 请刷新页面核对恢复结果。`; }
    } catch (error) {
      if (valid(ticket, file)) {
        results.replaceChildren();
        progress.textContent = `恢复失败：${errorText(error)} 请重新预览并核对当前状态后再恢复。`;
      }
    } finally {
      applying = false;
      if (active()) { preview = null; controls(); }
    }
  });
  taskButton.addEventListener("click", async () => {
    if (!active() || taskButton.disabled || previewing || applying) return;
    const ticket = ++sequence, file = selectedFile;
    applying = true; preview = null; results.replaceChildren(); controls();
    progress.textContent = "正在从本机任务文件重建任务索引；文档目录需单独恢复…";
    try {
      const value = await api("/api/library/rebuild", { method: "POST" });
      if (!valid(ticket, file)) return;
      const labels = { pass: "任务索引重建完成", partial: "任务索引重建仅部分完成，文档目录仍未恢复", blocked: "任务索引重建受阻，文档目录未恢复" };
      progress.textContent = `${labels[value.status] || "无法确认任务索引重建结果"}。已登记 ${Number(value.indexed || 0)} 个任务，跳过 ${Number(value.skipped || 0)} 个任务。${value.status !== "pass" ? "请先选择已有 SQLite 快照预览并恢复文档目录。" : "如需恢复文档目录，请单独选择快照。"} 已选快照需重新预览。`;
      await checkStatus();
      if (!valid(ticket, file) || !["pass", "partial"].includes(value.status)) return;
      try { await onRecovered(value); }
      catch (error) { if (valid(ticket, file)) progress.textContent += ` 列表刷新失败：${errorText(error)} 请刷新页面核对结果。`; }
    } catch (error) {
      if (valid(ticket, file)) { progress.textContent = `任务索引重建失败：${errorText(error)} 请重新检查目录并预览快照。`; await checkStatus(); }
    } finally { applying = false; if (active()) controls(); }
  });
  retry.addEventListener("click", () => { if (active() && !retry.disabled) return checkStatus(); });
  controls();
  const ready = checkStatus();
  return { root, ready };
}
