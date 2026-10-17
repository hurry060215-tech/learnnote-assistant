// Receipts describe the previous attempt. Scheduling is never copy completion;
// only the native receipt/config reconciliation may report a committed result.
export function migrationOutcome(value) {
  if (value?.ok !== true || !["none", "complete", "failed", "incomplete", "scheduled"].includes(value.status))
    throw new Error(value?.message || "无法核实上次数据迁移的结果。");
  if (value.status === "none") return null;
  if (value.status === "complete" && ![value.source, value.path, value.receipt].every(item => typeof item === "string" && item.length))
    throw new Error("迁移完成记录不完整，暂时无法核实目录切换结果。");
  const messages = {
    complete: "上次迁移已完成：目标数据已校验，数据目录配置已提交。旧目录仍保留。",
    failed: "上次迁移未激活，仍保留原配置。请保留旧目录并检查下方记录；重试时，请选择新的空目录重新预览。",
    incomplete: "上次迁移未完成，尚不能确认复制及目录切换结果。请保留旧目录并检查下方记录；重试时，请选择新的空目录重新预览。",
    scheduled: "上次迁移仅记录为已安排，尚不能确认复制或目录切换完成。请保留旧目录并检查下方记录。",
  };
  return { status: value.status, message: typeof value.message === "string" && value.message ? value.message : messages[value.status], record: JSON.stringify({
    status: value.status, source: value.source, path: value.path, receipt: value.receipt, message: value.message,
  }, null, 2) };
}

export function createMigrationStatus({ bridge, render }) {
  let generation = 0;
  return { async refresh() {
    const request = ++generation;
    try {
      const api = bridge();
      if (!api?.data_migration_status) { render(null); return; }
      render({ status: "loading", message: "正在读取上次数据迁移记录…", record: "" });
      const value = await api.data_migration_status();
      if (request === generation) render(migrationOutcome(value));
    } catch (error) {
      if (request === generation) render({ status: "unknown", message: `${error.message || "迁移记录暂时无法读取。"} 请保留原目录，重新打开设置后再检查。`, record: "" });
    }
  } };
}

export function installMigrationStatus({ element, bridge = () => window.pywebview?.api }) {
  element.innerHTML = '<h4>上次数据迁移</h4><p class="settings-status" role="status" aria-live="polite" data-migration-outcome></p><details><summary>查看迁移记录与路径</summary><pre class="settings-status source-excerpt" tabindex="0" aria-label="上次数据迁移记录"></pre></details>';
  const message = element.querySelector("[data-migration-outcome]"), details = element.querySelector("details"), record = element.querySelector("pre");
  return createMigrationStatus({ bridge, render(outcome) {
    element.hidden = !outcome;
    element.dataset.status = outcome?.status || "none";
    message.textContent = outcome?.message || "";
    message.setAttribute("aria-busy", String(outcome?.status === "loading"));
    record.textContent = outcome?.record || "";
    details.hidden = !record.textContent;
    if (!record.textContent) details.open = false;
  } });
}
