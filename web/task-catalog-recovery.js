import { make, errorText } from "/web/catalog-recovery-view.js";

const endpoint = "/api/library/catalog/tasks";

// The parent owns the shared operation sequence, selected file and busy state.
// Each request receives a current() ticket; only that request may release it.
export function mountTaskCatalogRecovery(root, { api, active, lifecycle, checkStatus, onRecovered }) {
  const hint = make("p", "目录完全损坏且没有可用文档快照时，可先预览仅恢复本机任务。未知文档、视频资料登记和其他目录记录不会恢复，缺失数量无法确定。执行前会永久保留原数据库及全部侧文件的独立备份，不自动清理。仍可读取的目录或未处理的事务日志会阻止替换。");
  hint.className = "muted";
  const previewButton = make("button", "预览损坏目录的任务恢复", "materialCatalogTaskPreview");
  previewButton.type = "button";
  const applyButton = make("button", "确认仅恢复任务并保留原库", "materialCatalogTaskApply");
  applyButton.type = "button";
  applyButton.className = "primary";
  const cancelButton = make("button", "取消任务恢复预览", "materialCatalogTaskCancel");
  cancelButton.type = "button";
  const actions = make("div");
  actions.className = "tool-actions";
  actions.append(previewButton, applyButton, cancelButton);
  const status = make("p", "此入口不会自动修复；先预览，再明确确认。", "materialCatalogTaskStatus");
  status.setAttribute("role", "status");
  root.append(make("h3", "损坏目录：仅恢复任务"), hint, actions, status);
  let preview = null, previewing = false, applying = false;

  function syncControls() {
    const busy = lifecycle.busy();
    previewButton.disabled = busy;
    applyButton.disabled = busy || !preview?.can_apply || preview.recovery_scope !== "task_catalog_only"
      || !/^[a-f0-9]{64}$/.test(preview.preview_token || "");
    cancelButton.disabled = applying || (!preview && !previewing);
  }
  function invalidate() {
    preview = null;
    previewing = false;
  }
  function showCatalogStatus(value) {
    if (!value.task_only_recovery) return;
    const record = value.task_only_recovery;
    status.textContent = `${value.message || "仅恢复任务，文档目录仍不完整。"} 原始字节备份：数据文件夹/exports/${record.backup_directory || "请检查本地备份"}。${record.restore_instructions || "请查看备份中的 RESTORE.txt；撤回仅恢复原先状态，不保证损坏目录可用。"}`;
  }
  previewButton.addEventListener("click", async () => {
    if (!active() || previewButton.disabled) return;
    preview = null;
    previewing = true;
    const current = lifecycle.begin("preview");
    status.textContent = "正在核对本机任务和原数据库字节；预览不会替换目录…";
    try {
      const value = await api(`${endpoint}/preview`, { method: "POST" });
      if (!current()) return;
      preview = value;
      status.textContent = `${value.message || "文档目录不会恢复。"} ${value.can_apply ? `可恢复 ${Number(value.task_count || 0)} 个任务、${Number(value.evidence_count || 0)} 条出处。请核对范围后确认；先保存原库完整字节备份。` : `恢复未启用：${value.diagnostic || "来源无法安全验证。"}`} ${value.restore_instructions || ""}`;
    } catch (error) {
      if (current()) status.textContent = `任务恢复预览失败：${errorText(error)}`;
    } finally {
      if (current()) previewing = false;
      lifecycle.finish(current);
    }
  });
  cancelButton.addEventListener("click", () => {
    if (!active() || cancelButton.disabled) return;
    invalidate();
    status.textContent = "已取消任务恢复预览，未执行恢复。再次操作需重新预览。";
    lifecycle.cancel();
  });
  applyButton.addEventListener("click", async () => {
    if (!active() || applyButton.disabled) return;
    const token = preview.preview_token;
    preview = null;
    applying = true;
    const current = lifecycle.begin("apply");
    status.textContent = "正在保存原库并重建任务目录…关闭窗口不会取消已开始的恢复；重新打开可检查结果。";
    try {
      const value = await api(`${endpoint}/apply`, {
        method: "POST", body: JSON.stringify({ preview_token: token, confirm_scope: "task_catalog_only" }),
      });
      if (!current()) return;
      status.textContent = `${value.message || "仅恢复任务，未知文档目录未恢复。"} 已恢复 ${Number(value.restored_task_count || 0)} 个任务、${Number(value.restored_evidence_count || 0)} 条出处。原始字节备份：数据文件夹/exports/${value.rollback_directory || "请检查备份"}。${value.restore_instructions || "请查看备份中的 RESTORE.txt。"}`;
      await checkStatus();
      if (!current()) return;
      try {
        await onRecovered(value);
      } catch (error) {
        if (current()) status.textContent += ` 列表刷新失败：${errorText(error)} 请刷新页面核对已完成的任务恢复。`;
      }
    } catch (error) {
      if (current()) status.textContent = `任务恢复未确认完成：${errorText(error)} 请重新检查状态并预览；原库备份不会自动清理。`;
    } finally {
      applying = false;
      lifecycle.finish(current);
    }
  });
  syncControls();
  return { syncControls, invalidate, showCatalogStatus };
}
