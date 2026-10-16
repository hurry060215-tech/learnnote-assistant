import { mountTaskCatalogRecovery } from "/web/task-catalog-recovery.js";
import { make, createMaterialRecoveryView, addRecoveryRows, errorText } from "/web/catalog-recovery-view.js";

const endpoint = "/api/library/catalog";
const maxSnapshotBytes = 128 * 1024 * 1024;

export function mountMaterialCatalogRecovery(container, { api, isCurrent = () => true, onRecovered = async () => {} }) {
  const {
    root, status, retry, input, selected, previewButton, applyButton, progress, results, taskButton,
  } = createMaterialRecoveryView(container);
  let sequence = 0, statusSequence = 0, selectedFile = null, preview = null, previewing = false, applying = false;
  const active = () => root.isConnected && isCurrent();
  const valid = (ticket, file) => active() && ticket === sequence && file === selectedFile;
  const taskRecovery = mountTaskCatalogRecovery(root, {
    api, active, onRecovered, checkStatus,
    lifecycle: {
      busy: () => previewing || applying,
      begin(mode) {
        const ticket = ++sequence, file = selectedFile;
        preview = null;
        previewing = mode === "preview";
        applying = mode === "apply";
        controls();
        return () => valid(ticket, file);
      },
      finish(current) {
        if (!current()) return;
        previewing = false;
        applying = false;
        controls();
      },
      cancel() {
        sequence++;
        previewing = false;
        controls();
      },
    },
  });
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
    taskRecovery.syncControls();
  }
  async function checkStatus() {
    const ticket = ++statusSequence;
    retry.disabled = true;
    try {
      const value = await api(`${endpoint}/status`);
      if (!active() || ticket !== statusSequence) return;
      const labels = { healthy: "正常", missing: "缺失", corrupt: "损坏", incomplete: "不完整", incompatible: "版本不兼容" };
      status.textContent = `学习资料目录：${labels[value.state] || "状态未知"}。${value.message || ""}${value.orphaned_material_ids?.length ? ` 检测到 ${value.orphaned_material_ids.length} 份原文件缺少目录记录。` : ""}`;
      root.dataset.state = value.state;
      taskRecovery.showCatalogStatus(value);
    } catch (error) {
      if (active() && ticket === statusSequence) status.textContent = `目录状态检查失败：${errorText(error)}`;
    } finally {
      if (active() && ticket === statusSequence) retry.disabled = false;
    }
  }
  input.addEventListener("change", () => {
    if (!active()) return;
    sequence++; preview = null; previewing = false; taskRecovery.invalidate(); results.replaceChildren();
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
    preview = null; taskRecovery.invalidate(); previewing = true; results.replaceChildren(); controls();
    progress.textContent = "正在核对所选快照与本机原文件；此预览不会恢复数据…";
    const body = new FormData(); body.append("file", file);
    try {
      const value = await api(`${endpoint}/recovery/preview`, { method: "POST", body });
      if (!valid(ticket, file)) return;
      preview = value;
      results.append(make("p", `快照：${file.name} · SHA-256：${value.snapshot_sha256 || "未知"}`));
      addRecoveryRows(results, value.materials);
      const listed = new Set((value.materials || []).filter(item => item.status === "unresolved").map(item => item.material_id));
      addRecoveryRows(results, (value.unresolved || []).filter(item => !listed.has(item.material_id)), true);
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
    applying = true; taskRecovery.invalidate(); controls();
    progress.textContent = "正在按已核对的快照恢复目录与出处索引…关闭此窗口不会取消已开始的恢复；重新打开后可检查结果。";
    const body = new FormData(); body.append("file", file); body.append("preview_token", token);
    try {
      const value = await api(`${endpoint}/recovery/apply`, { method: "POST", body });
      if (!valid(ticket, file)) return;
      preview = null; results.replaceChildren();
      results.append(make("p", value.message || "恢复请求已完成。"));
      if (value.rollback_snapshot_created && value.rollback_directory) results.append(make("p", `回滚备份位置：数据文件夹/exports/${value.rollback_directory}`));
      addRecoveryRows(results, value.unresolved, true);
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
    applying = true; preview = null; taskRecovery.invalidate(); results.replaceChildren(); controls();
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
