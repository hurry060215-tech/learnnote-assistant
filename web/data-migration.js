// Native bridge previews are read-only. Only the explicit confirmation consumes
// their one-use token; completion belongs to the exit-waiting desktop helper.
export function migrationPreview(value) {
  if (value?.ok !== true || value.preview !== true ||
      ![value.token, value.source, value.path].every(item => typeof item === "string" && item.length) ||
      ![value.file_count, value.byte_count].every(item => Number.isSafeInteger(item) && item >= 0) ||
      ![value.changes, value.excluded, value.external_references].every(Array.isArray) ||
      !value.changes.every(item => item && typeof item.file === "string" && typeof item.field === "string" && "before" in item && "after" in item) ||
      !value.excluded.every(item => item && typeof item.path === "string" && typeof item.reason === "string"))
    throw new Error("未收到完整的只读迁移预览，请重新选择目录。");
  return JSON.parse(JSON.stringify(value));
}

export function createDataMigration({ bridge, render, beforeConfirm = () => "" }) {
  let epoch = 0, state = { phase: "closed", plan: null, message: "" }, selectedBridge;
  const emit = (phase, plan = null, message = "") => {
    state = { phase, plan, message }; render(state);
  };
  const busy = () => ["applying", "restarting"].includes(state.phase);
  return {
    get phase() { return state.phase; },
    cancel() {
      if (busy()) return false;
      epoch++; selectedBridge = null; emit("closed"); return true;
    },
    async start() {
      if (busy()) return;
      const request = ++epoch;
      emit("selecting", null, "请选择目标目录，正在准备只读预览…");
      try {
        const api = bridge();
        if (!api?.choose_data_directory || !api?.apply_data_directory)
          throw new Error("请使用支持迁移预览的桌面客户端更改数据位置。");
        const result = await api.choose_data_directory(true);
        if (request !== epoch) return;
        if (result?.cancelled) { emit("closed"); return; }
        if (result?.unchanged && result.ok) { emit("unchanged", null, result.message || "仍使用当前数据目录，无需迁移。"); return; }
        if (!result?.ok) throw new Error(result?.message || "无法预览此目录，请选择其他空目录。");
        const plan = migrationPreview(result);
        selectedBridge = api;
        emit("preview", plan, "此预览尚未复制文件或切换数据目录。");
      } catch (error) {
        if (request === epoch) emit("error", null, error.message || "迁移预览失败。");
      }
    },
    async confirm() {
      if (state.phase !== "preview") return;
      const blocked = beforeConfirm();
      if (blocked) { emit("preview", state.plan, blocked); return; }
      const request = epoch, plan = state.plan, api = selectedBridge;
      emit("applying", plan, "正在请求关闭客户端并安排迁移，请勿重复操作…");
      try {
        const result = await api.apply_data_directory(plan.token);
        if (request !== epoch) return;
        if (result?.ok !== true || result.restarting !== true)
          throw new Error(result?.message || "未能确认迁移已安排，请检查客户端状态后重新预览。");
        emit("restarting", plan, "已安排退出后迁移。客户端完全退出后才会复制；校验通过后切换目录并重新启动。当前窗口尚不能确认复制完成。");
      } catch (error) {
        if (request === epoch) {
          selectedBridge = null;
          emit("error", null, `${error.message || "未收到迁移确认。"} 请重新预览后再确认。`);
        }
      }
    },
  };
}

export function installDataMigration({ button, settingsDialog, beforeConfirm, document: doc = document, bridge = () => window.pywebview?.api }) {
  const dialog = doc.createElement("dialog");
  dialog.id = "dataMigrationDialog";
  dialog.className = "tools-dialog data-migration-dialog";
  dialog.setAttribute("aria-labelledby", "dataMigrationHeading");
  dialog.innerHTML = '<header><h2 id="dataMigrationHeading">迁移数据位置</h2><button type="button" data-migration-close aria-label="关闭迁移预览">×</button></header>' +
    '<div data-migration-preview hidden><p>这是复制迁移：旧目录会保留，不会删除源文件。凭据不会复制；未包含的项目会列在下方。</p>' +
    '<p class="muted">确认后将关闭客户端。辅助程序等待客户端完全退出，再复制文件；目标校验通过后才切换目录并重启。</p>' +
    '<dl><dt>源目录（保留）</dt><dd class="settings-status" data-migration-source></dd><dt>目标目录</dt><dd class="settings-status" data-migration-target></dd></dl>' +
    '<p data-migration-count></p><p data-migration-warning></p><details data-migration-excluded><summary></summary><pre tabindex="0" aria-label="不复制项目的完整记录"></pre></details>' +
    '<p data-migration-external-warning></p><details data-migration-external><summary>查看外部引用完整记录</summary><pre tabindex="0" aria-label="外部引用完整记录"></pre></details>' +
    '<details data-migration-changes><summary></summary><pre tabindex="0" aria-label="逐项路径变更完整记录"></pre></details></div>' +
    '<p id="dataMigrationStatus" class="settings-status" role="status" aria-live="polite" tabindex="-1"></p>' +
    '<footer class="tool-actions"><button type="button" data-migration-cancel>取消</button><button type="button" data-migration-retry hidden>重新选择并预览</button><button type="button" class="primary" data-migration-confirm hidden>确认复制并重启</button></footer>';
  doc.body.append(dialog);
  const find = selector => dialog.querySelector(selector);
  const preview = find("[data-migration-preview]"), status = find("#dataMigrationStatus");
  const close = find("[data-migration-close]"), cancel = find("[data-migration-cancel]");
  const confirm = find("[data-migration-confirm]"), retry = find("[data-migration-retry]");
  let previousPhase = "closed", displayedPlan = null;
  const records = (selector, title, values) => {
    const details = find(selector);
    if (title) details.querySelector("summary").textContent = title;
    details.querySelector("pre").textContent = JSON.stringify(values, null, 2);
    details.open = false;
  };
  const controller = createDataMigration({ bridge, beforeConfirm, render(state) {
    const { phase, plan, message } = state, busy = ["applying", "restarting"].includes(phase);
    if (phase === "closed") {
      previousPhase = phase; displayedPlan = null; button.disabled = false; dialog.dataset.phase = phase;
      if (dialog.open) dialog.close();
      if (settingsDialog.open) button.focus();
      return;
    }
    preview.hidden = !plan;
    if (plan && plan !== displayedPlan) {
      find("[data-migration-source]").textContent = plan.source;
      find("[data-migration-target]").textContent = plan.path;
      find("[data-migration-count]").textContent = `计划复制 ${plan.file_count.toLocaleString("zh-CN")} 个文件，共 ${plan.byte_count.toLocaleString("zh-CN")} 字节。`;
      find("[data-migration-warning]").textContent = `不复制 ${plan.excluded.length} 项。凭据与排除项目仍留在原位置；下方可查看具体原因。`;
      records("[data-migration-excluded]", `查看不复制的项目（${plan.excluded.length} 项）`, plan.excluded);
      find("[data-migration-external-warning]").textContent = plan.external_references.length
        ? `${plan.external_references.length} 项引用位于源目录之外，不会复制这些外部文件，请保留原位置。` : "未发现需要保留原位置的外部引用。";
      find("[data-migration-external]").hidden = !plan.external_references.length;
      records("[data-migration-external]", null, plan.external_references);
      records("[data-migration-changes]", `查看逐项路径变更（${plan.changes.length} 项）`, plan.changes);
      displayedPlan = plan; dialog.scrollTop = 0;
    }
    status.textContent = message;
    status.setAttribute("aria-busy", String(phase === "selecting" || phase === "applying"));
    close.disabled = cancel.disabled = busy;
    cancel.textContent = phase === "unchanged" ? "关闭" : "取消";
    confirm.hidden = !["preview", "applying", "restarting"].includes(phase);
    confirm.disabled = phase !== "preview";
    retry.hidden = !["error", "unchanged"].includes(phase);
    button.disabled = phase !== "closed";
    dialog.dataset.phase = phase;
    if (!dialog.open) dialog.showModal();
    if (phase === "preview" && previousPhase !== "preview") close.focus();
    else if (["error", "restarting"].includes(phase)) status.focus();
    previousPhase = phase;
  } });
  const dismiss = () => { if (controller.cancel()) button.disabled = false; };
  button.onclick = () => controller.start();
  retry.onclick = () => controller.start();
  confirm.onclick = () => controller.confirm();
  close.onclick = cancel.onclick = dismiss;
  dialog.addEventListener("cancel", event => { event.preventDefault(); dismiss(); });
  dialog.addEventListener("close", () => { if (!dialog.open) dismiss(); });
  settingsDialog.addEventListener("close", () => { if (!settingsDialog.open) dismiss(); });
  return controller;
}
