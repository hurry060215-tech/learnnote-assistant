import { api } from "/web/desk-api.js";
import { createAssistantRunController } from "/web/assistant-run-controller.js";

export function installAssistantRuns({ state, options, openItem, notice }) {
  const host = document.querySelector("#assistantOperationsDialog [data-agent-local]");
  const launch = document.createElement("button");
  launch.type = "button"; launch.id = "assistantRuns"; launch.textContent = "连续读取、修改并导出…";
  host.before(launch);
  const dialog = document.createElement("dialog");
  dialog.id = "assistantRunsDialog"; dialog.className = "tools-dialog";
  dialog.setAttribute("aria-labelledby", "assistantRunsTitle");
  dialog.innerHTML = `<header><h2 id="assistantRunsTitle">连续读取、修改并导出</h2><button type="button" data-run-close aria-label="关闭并停止后续步骤">×</button></header>
    <p>围绕当前保存笔记，助手会逐步读取、提出一次修改并生成文件。写入前会停下来展示实际差异；应用后重新读取核对，才继续导出。</p>
    <p data-run-source class="muted"></p>
    <label>本次要求<textarea data-run-question maxlength="1000" rows="3" placeholder="例如：先读当前笔记，把正文标题改得更清楚，再导出 Word。"></textarea></label>
    <label class="check"><input type="checkbox" data-run-share>允许本次流程把要求、当前选中正文与工具读取结果发给当前文字模型</label>
    <p class="muted">可能产生模型用量费用；最多 8 次决策、120 秒实际执行时间，等待你确认时暂停计时，正文每个保存版本限 24,000 字；决策时可能重复发送本轮读取结果。没有额外会话日志上传。原始资料保留；流程要求、读取记录、修改前后副本和导出缓存保存在本机。</p>
    <p class="muted">授权仅用于当前流程；点击“停止后续步骤”可撤销后续发送。新流程需要重新勾选。</p>
    <button type="button" data-run-start class="primary">开始流程</button><button type="button" data-run-cancel>停止后续步骤</button>
    <p data-run-status role="status"></p><section data-run-card aria-live="polite"></section>
    <details><summary>本机流程记录</summary><button type="button" data-run-history>刷新列表</button><div data-run-records></div></details>`;
  document.body.append(dialog);
  const $ = selector => dialog.querySelector(selector);
  const dirty = () => state.editing && document.getElementById("noteText").value !== state.text;
  const source = () => {
    if (!state.selected || !state.revision) throw Error("请先打开一份已保存的笔记或资料。");
    if (dirty()) throw Error("当前正文有未保存草稿，请先保存或保留草稿。");
    return { kind: state.selected.kind, id: state.selected.id, revision: state.revision };
  };
  const report = text => { $("[data-run-status]").textContent = text; };
  const titles = { read_note: "读取正文", edit_note: "修改个人修订", export_note: "导出文件", verify_note: "读回核对" };
  const statuses = { ready: "可以继续", planning: "模型决策中", executing: "执行中", awaiting_approval: "等待你确认差异", completed: "已生成并核对文件", stopped: "已停止", cancelled: "已取消后续步骤", failed: "未完成", unavailable: "记录暂不可读" };
  const reasons = {
    cancel_requested: "已请求停止；已提交的修改会保留。", active_timeout: "已达到实际执行时间上限。",
    active_timeout_pending_receipt: "已达到时间上限，正在核对当前本地操作的实际结果。",
    decision_limit: "已达到本次模型决策次数上限。", no_action: "模型没有提出受支持的下一步，流程已停止。",
    read_required: "必须先读取正文才能修改或导出。", edit_limit: "每个流程最多修改一次，请核对当前结果。",
    source_changed: "来源或保存版本已变化，未覆盖后续修改。", connection_changed: "所选模型连接已变化，请开始新的流程。",
    readback_mismatch: "保存后读回结果不一致，已停止导出。", verified_readback_required: "尚未完成保存后的读回核对。",
    export_revision_mismatch: "导出文件的版本与已核对正文不一致。", artifact_unavailable: "已生成文件暂不可用，请保留记录并核对。",
    model_timeout: "模型响应超时，后续步骤已停止。", invalid_model_result: "模型没有返回完整、受支持的单步操作。",
    interrupted_model_attempt: "上次模型请求已中断，未自动重新发送。", request_interrupted: "请求已中断，请核对实际步骤。",
    interrupted_operation: "上次本地操作缺少完整回执，未自动重做。", interrupted_readback: "读回核对中断，未继续导出。",
    recovery_conflict: "恢复时发现版本或回执冲突，已有正文保留。", source_or_operation_conflict: "来源或操作参数存在冲突，流程已停止。",
    source_output_limit_or_missing_receipt: "读取结果超出范围或缺少实际回执，未继续发送模型请求。",
    edited_source_limit: "拟修改正文超过本次字数范围，未应用。", operation_record_missing: "所需操作记录已被移除，无法继续。",
    operation_unconfirmed: "本地操作结果尚未确认，请刷新实际状态。", operation_failed: "本地操作未完成，后续步骤已停止。",
    record_or_source_unavailable: "记录或来源暂不可读，已有文件保留。",
  };
  let controller;
  const updateControls = busy => {
    for (const item of dialog.querySelectorAll("button")) if (!item.hasAttribute("data-run-close") && !item.hasAttribute("data-run-cancel")) item.disabled = busy;
    const inFlight = controller?.active && !["completed", "stopped", "cancelled", "failed"].includes(controller.active.status);
    $("[data-run-start]").disabled = busy || Boolean(inFlight);
    $("[data-run-question]").disabled = busy || Boolean(inFlight);
    $("[data-run-share]").disabled = busy || Boolean(inFlight);
  };
  const button = (parent, label, action, key) => {
    const element = document.createElement("button"); element.type = "button"; element.textContent = label;
    if (key) element.dataset[key] = "";
    element.onclick = action; element.disabled = controller.busy; parent.append(element); return element;
  };
  function render(value) {
    const card = $("[data-run-card]"); card.replaceChildren();
    $("[data-run-share]").checked = Boolean(value && !["completed", "stopped", "cancelled", "failed", "unavailable"].includes(value.status));
    updateControls(controller.busy);
    if (!value) return;
    const heading = document.createElement("h3"); heading.textContent = statuses[value.status] || value.status; card.append(heading);
    const details = document.createElement("p"); details.textContent = value.source ? `来源 ${value.source.id} · 保存版本 ${value.source.revision.slice(0, 12)}` : "来源或记录暂不可读；已有文件会保留。"; card.append(details);
    const steps = document.createElement("ol");
    for (const step of value.steps || []) {
      const row = document.createElement("li"); row.textContent = `${step.readback ? "读回核对" : titles[step.tool] || "操作"} · ${{completed:"已完成",prepared:"待应用",running:"执行中",planned:"待执行",failed:"未完成",conflict:"冲突",cancelled:"已取消"}[step.status] || "待核对"}`;
      if (step.result?.text !== undefined) { const output = document.createElement("pre"); output.textContent = step.result.text; row.append(output); }
      if (step.result?.total_lines !== undefined) { const scope = document.createElement("p"); scope.textContent = `显示第 ${step.result.start_line} 行起 ${step.result.line_count} 行，全文共 ${step.result.total_lines} 行。`; row.append(scope); }
      if (step.verification) { const verified = document.createElement("p"); verified.textContent = "已核对完整保存正文、版本和本次写入标识。"; row.append(verified); }
      if (step.result?.warnings?.length) { const warnings = document.createElement("p"); warnings.textContent = step.result.warnings.join("\n"); row.append(warnings); }
      if (step.result?.truncated) { const note = document.createElement("p"); note.textContent = "本次读取已截断，不能视为已读完整正文。"; row.append(note); }
      steps.append(row);
    }
    card.append(steps);
    if (value.reason) { const reason = document.createElement("p"); reason.textContent = reasons[value.reason] || "流程已停止，请核对上方实际步骤与操作记录。"; card.append(reason); }
    if (value.pending_operation) {
      const pre = document.createElement("pre"); pre.textContent = value.pending_operation.preview?.diff ?? "没有可显示的修改差异，请核对操作记录。"; card.append(pre);
      if (value.status === "awaiting_approval" && typeof value.pending_operation.preview?.diff === "string") button(card, "应用这次修改并继续", () => controller.approve(), "runApprove");
    }
    if (value.status === "ready") button(card, "继续已核对的流程", () => controller.continue(), "runContinue");
    button(card, "刷新实际状态", () => controller.refresh(), "runRefresh");
    if (value.artifact_operation_id && value.status === "completed") {
      const link = document.createElement("a"); link.className = "tool-link";
      link.href = `/api/assistant/operations/${encodeURIComponent(value.artifact_operation_id)}/artifact`;
      link.download = ""; link.textContent = "下载已生成文件"; card.append(link);
    }
    if (value.edit_operation_id) {
      const info = document.createElement("p"); info.textContent = "本次修改的撤销入口在“操作软件 → 最近执行记录”中。后续手工编辑可能使旧撤销失效；停止流程不会自动撤销已提交修改。"; card.append(info);
    }
    if (["completed", "cancelled", "failed", "stopped"].includes(value.status)) button(card, "删除流程记录…", () => {
      if (window.confirm("删除此流程的要求和步骤索引？当前正文和独立操作记录保留；其中的正文副本可在操作记录中单独清理。")) controller.forget();
    });
  }
  controller = createAssistantRunController({ api, source, options, report, render,
    reload: async expected => { await openItem(state.selected); if (state.revision !== expected.revision) throw Error("读回版本已变化，已停止继续。请核对当前正文。"); },
    busyChanged: updateControls,
  });
  $("[data-run-start]").onclick = () => { report(""); return controller.start($("[data-run-question]").value, $("[data-run-share]").checked); };
  $("[data-run-cancel]").onclick = () => controller.cancel();
  $("[data-run-history]").onclick = async () => {
    try {
      const result = await controller.list(); if (!dialog.open) return;
      const panel = $("[data-run-records]"); panel.replaceChildren();
      for (const value of result.runs || []) button(panel, `${statuses[value.status] || value.status} · ${value.source?.id || value.id}`, () => controller.select(value.id));
      if (!result.runs?.length) panel.textContent = "还没有流程记录。";
    } catch (error) { if (dialog.open) report(error.message); }
  };
  launch.onclick = () => {
    $("[data-run-source]").textContent = state.selected ? `当前来源：${state.selected.title}` : "请先选择一份笔记或资料。";
    $("[data-run-share]").checked = false;
    dialog.showModal(); controller.open();
  };
  $("[data-run-close]").onclick = () => dialog.close();
  dialog.addEventListener("close", () => { controller.close(); if (controller.busy) notice("已停止安排后续步骤；当前操作的真实结果可从本机记录核对。"); });
}
