// One local-only preview controller shared by the classic script and desk import.
// Load before classic app.js; no task content is interpolated into markup.
(() => {
  let active = null;
  function invalidate() { active?.close(); }
  function open({ taskId, apiUrl = path => path, isCurrent = () => true, parent = null }) {
    invalidate();
    const opener = document.activeElement;
    const dialog = document.createElement("dialog");
    dialog.className = "tools-dialog source-dialog task-diagnostic-export";
    dialog.setAttribute("aria-label", "安全诊断报告预览");
    const element = (tag, text) => {
      const node = document.createElement(tag);
      if (text) node.textContent = text;
      return node;
    };
    const header = element("header"), heading = element("h2", "安全诊断报告预览");
    const back = element("button", "← 返回"), close = element("button", "关闭");
    header.append(back, heading, close);
    const hint = element("p", "仅预览本地安全诊断报告。这是读取时的诊断快照。版本区分当前运行环境与历史任务；未记录的历史构建、模型用量显示为未知。报告不包含原始标题、任务标识、路径、网址、错误原文或学习正文。不会上传或自动分享。");
    const label = element("label", "报告格式 "), format = element("select");
    for (const [value, text] of [["md", "Markdown"], ["json", "JSON"]]) {
      const option = element("option", text); option.value = value; format.append(option);
    }
    label.append(format);
    const preview = element("pre"); preview.setAttribute("aria-label", "将保存的完整诊断报告");
    const consentLabel = element("label"), consent = element("input");
    consentLabel.className = "check"; consent.type = "checkbox";
    consentLabel.append(consent, document.createTextNode("我已检查报告，仅保存当前预览文件"));
    const actions = element("div"), save = element("button", "保存已预览报告"), cancel = element("button", "取消导出");
    actions.className = "tool-actions"; save.className = "primary"; actions.append(save, cancel);
    const message = element("p"); message.setAttribute("role", "status");
    dialog.append(header, hint, label, preview, consentLabel, actions, message);
    let revision = 0, controller, bytes = null, saved = false, disposed = false;
    const current = token => !disposed && dialog.open && dialog.isConnected && isCurrent() && token === revision;
    function reset() {
      revision++; controller?.abort(); bytes = null; saved = false;
      consent.checked = false; consent.disabled = true; save.disabled = true;
    }
    function dispose() {
      if (disposed) return;
      disposed = true; reset(); preview.textContent = "";
      parent?.removeEventListener("close", dispose);
      parent?.removeEventListener("cancel", dispose);
      parent?.removeEventListener("learnnote:dialog-closed", dispose);
      window.removeEventListener("pagehide", dispose);
      if (dialog.open) dialog.close();
      dialog.remove();
      if (active?.dialog === dialog) active = null;
      const target = opener?.closest?.("details:not([open])")?.querySelector("summary") || opener;
      if (target?.isConnected && isCurrent()) target.focus?.();
    }
    async function load() {
      reset(); const token = revision, chosen = format.value;
      controller = new AbortController(); preview.textContent = "正在读取安全报告…"; message.textContent = "";
      try {
        const response = await fetch(apiUrl(`/api/tasks/${encodeURIComponent(taskId)}/exports/diagnostics${chosen === "json" ? "?format=json" : ""}`), { signal: controller.signal });
        if (!response.ok) throw new Error("unavailable");
        const data = await response.arrayBuffer();
        if (!current(token)) return;
        const text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(data);
        bytes = data; preview.textContent = text; consent.disabled = false;
      } catch (_) {
        if (current(token)) { preview.textContent = ""; message.textContent = "无法读取安全诊断报告。请关闭后重试；未保存或发送任何内容。"; }
      }
    }
    consent.addEventListener("change", () => { save.disabled = !consent.checked || !bytes || saved || !current(revision); });
    save.addEventListener("click", () => {
      if (!current(revision)) { dispose(); return; }
      if (!bytes || saved || !consent.checked || save.disabled) return;
      saved = true; save.disabled = true; consent.disabled = true;
      const json = format.value === "json";
      let url, link;
      try {
        url = URL.createObjectURL(new Blob([bytes], { type: json ? "application/json;charset=utf-8" : "text/markdown;charset=utf-8" }));
        link = element("a"); link.href = url; link.download = `learnnote-diagnostics.${json ? "json" : "md"}`;
        document.body.append(link); link.click();
        message.textContent = "已请求保存当前预览文件。是否分享、发给谁以及何时分享，由你决定。";
      } catch (_) {
        message.textContent = "无法保存预览文件。请关闭后重试；未上传或分享任何内容。";
      } finally {
        link?.remove();
        if (url) setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    });
    format.addEventListener("change", load);
    for (const button of [back, close, cancel]) { button.type = "button"; button.addEventListener("click", dispose); }
    dialog.addEventListener("close", dispose); dialog.addEventListener("cancel", dispose);
    for (const name of ["close", "cancel", "learnnote:dialog-closed"]) parent?.addEventListener(name, dispose);
    window.addEventListener("pagehide", dispose);
    document.body.append(dialog); active = { dialog, close: dispose }; dialog.showModal(); load();
    return active;
  }
  function bindClassic({ desktopApi, exportTaskArtifact }) {
    document.addEventListener("click", event => {
      const button = event.target?.closest?.("[data-diagnostic-export]");
      if (button) { event.preventDefault(); exportTaskArtifact(button.dataset.diagnosticExport, "diagnostics"); return; }
      if (!desktopApi()?.export_task) return;
      const link = event.target?.closest?.('a[href*="/exports/"]');
      const match = String(link?.getAttribute("href") || "").match(/\/api\/tasks\/([^/]+)\/exports\/(.+)$/);
      if (match) { event.preventDefault(); exportTaskArtifact(decodeURIComponent(match[1]), decodeURIComponent(match[2]), link); }
    });
  }
  globalThis.LearnNoteDiagnosticExport = { open, invalidate, bindClassic };
})();
