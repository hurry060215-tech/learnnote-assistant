import { api, escapeHtml as esc, timestamp } from "/web/desk-api.js";
import { createMaterialBatch, batchVideoRoute, importSize } from "/web/material-batch.js";

export function installMaterialBatch({ state, options, updatePresentation, openResult, refresh }) {
  const $ = id => document.getElementById(id), dialog = $("createDialog");
  let visit = 0, handling = false, route = "", routeOptions = {}, routeError = "";
  const queue = createMaterialBatch({ api, changed: render,
    videoLimit: () => state.health.upload_policy?.max_video_bytes });
  const labels = { pending: "待预检", preflighting: "预检中", ready: "待提交", invalid: "未通过", failed: "失败", submitting: "提交中", success: "已完成" };
  function render() {
    const busy = queue.running || queue.preparing || handling || state.busy;
    const locked = state.input === "file" && (Boolean(queue.snapshot) || queue.running || handling);
    $("file").disabled = queue.running || handling;
    $("materialEncoding").disabled = queue.running || handling || Boolean(queue.snapshot);
    $("materialBatchCancel").hidden = !busy;
    $("materialBatchCancel").disabled = queue.stopped;
    $("materialBatchRetryPreview").hidden = !queue.items.some(item => !item.preview && ["pending", "failed"].includes(item.status));
    $("materialBatchRetryPreview").disabled = busy;
    $("selectedFilePreview").hidden = !queue.items.length && !queue.message;
    const active = queue.items.find(item => ["preflighting", "submitting"].includes(item.status));
    $("materialBatchSummary").textContent = queue.message + (active ? ` ${labels[active.status]}：${active.file.name}（${queue.items.indexOf(active) + 1} / ${queue.items.length}）。` : "");
    $("materialBatchItems").innerHTML = queue.items.map((item, index) => {
      const preview = item.preview;
      const detail = preview ? item.kind === "material"
        ? `${preview.page_count ? `${preview.page_count} 页 · ` : ""}预计本地空间 ${importSize(preview.estimated_storage_bytes)}（可选 OCR 另计）。${preview.ocr_required ? "扫描 PDF，导入后可选择本地 OCR，识别结果需核验。" : "本地提取文字，不发送给模型。"}`
        : `${Number.isFinite(preview.duration) && preview.duration > 0 ? `时长 ${timestamp(preview.duration)}。` : "浏览器未能读取时长；时长未知，提交后由本机校验媒体，可能失败。"}至少需要 ${importSize(item.file.size)} 上传空间，解码缓存另计。`
        : "";
      return `<li class="model-route-item ${["failed", "invalid"].includes(item.status) ? "waiting" : "ready"}" data-status="${item.status}"><div><strong>${esc(item.file.name)}</strong><span>${labels[item.status]}</span></div><small>${importSize(item.file.size)}${item.encoding ? ` · ${esc(item.encoding)}` : ""}</small><p>${esc(detail)}</p><p>${esc(item.detail)}</p>${item.result ? `<button type="button" data-batch-open="${index}" ${busy ? "disabled" : ""}>${item.kind === "material" ? "阅读资料" : "查看视频任务"}</button>` : ""}</li>`;
    }).join("");
    for (const button of document.querySelectorAll("[data-input]")) button.disabled = queue.running || handling;
    $("contentModeChoices").disabled = locked;
    for (const control of $("generationOptions").querySelectorAll("input,select")) {
      // Preserve controls intentionally disabled by the content-mode UI.
      if (locked) {
        if (!control.dataset.batchLocked) control.dataset.batchLocked = control.disabled ? "disabled" : "enabled";
        control.disabled = true;
      } else if (control.dataset.batchLocked) {
        control.disabled = control.dataset.batchLocked === "disabled";
        delete control.dataset.batchLocked;
      }
    }
    routeError = "";
    if (queue.items.some(item => item.kind === "task" && item.status !== "invalid")) {
      try {
        routeOptions = queue.snapshot?.options || options();
        route = queue.snapshot?.route || batchVideoRoute(routeOptions, state.health);
      } catch (error) { routeError = error.message; route = error.message; }
    } else { routeOptions = {}; route = ""; }
    $("materialBatchRoute").textContent = "资料：只在本机提取文字，原始字节保留；按内容哈希复用已有资料。" + route
      + (queue.snapshot ? " 本批重试沿用首次提交的编码与视频设置；更改设置请重新选择文件。" : "");
    if (state.input !== "file") return;
    $("createSubmit").disabled = busy || !queue.canSubmit || Boolean(routeError);
    $("createSubmit").textContent = queue.running ? "正在逐个提交…" : queue.preparing ? "正在预检…"
      : queue.snapshot ? "继续未完成项" : queue.items.length > 1 ? "导入通过预检的文件"
        : queue.items[0]?.kind === "material" ? "导入并阅读资料" : queue.items[0]?.kind === "task" ? "按所选路线整理视频" : "先选择文件";
  }
  async function choose(files) {
    if (queue.running || handling) return;
    visit++;
    if (!queue.select(files, $("materialEncoding").value || "")) { updatePresentation(); return; }
    $("createStatus").textContent = "";
    updatePresentation();
    await queue.prepare();
  }
  function leave() { visit++; queue.cancel(); }
  $("file").addEventListener("change", () => choose($("file").files));
  $("materialEncoding").addEventListener("change", () => choose(queue.items.map(item => item.file)));
  const drop = $("fileDrop");
  for (const type of ["dragenter", "dragover"]) drop.addEventListener(type, event => {
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = queue.running || handling ? "none" : "copy";
    drop.classList.toggle("dragging", !queue.running && !handling);
  });
  for (const type of ["dragleave", "drop"]) drop.addEventListener(type, () => drop.classList.remove("dragging"));
  drop.addEventListener("drop", event => {
    event.preventDefault(); event.stopPropagation();
    if (queue.running || handling) return;
    const transfer = event.dataTransfer;
    if (Array.from(transfer?.items || []).some(item => item.webkitGetAsEntry?.()?.isDirectory)) {
      $("createStatus").textContent = "请直接选择文件，暂不接受文件夹。"; return;
    }
    if (!transfer?.files?.length) { $("createStatus").textContent = "请拖入本机文件；网页链接和文字不会导入。"; return; }
    $("file").value = "";
    choose(transfer.files);
  });
  $("materialBatchCancel").onclick = () => queue.cancel();
  $("materialBatchRetryPreview").onclick = () => queue.prepare();
  $("materialBatchItems").onclick = async event => {
    const button = event.target.closest("[data-batch-open]");
    if (!button || queue.running || handling) return;
    const item = queue.items[Number(button.dataset.batchOpen)];
    if (item?.result) {
      handling = true; render(); dialog.close();
      try { await openResult(item); } finally { handling = false; render(); }
    }
  };
  dialog.addEventListener("beforetoggle", event => { if (event.newState === "closed") leave(); });
  dialog.addEventListener("cancel", leave);
  dialog.addEventListener("close", () => { if (!dialog.open) leave(); });
  window.addEventListener("learnnote:navigation", () => { leave(); if (dialog.open) dialog.close(); });
  $("createForm").addEventListener("change", event => {
    if (event.target !== $("file") && event.target !== $("materialEncoding")) render();
  });
  return {
    get items() { return queue.items; },
    render,
    open() { visit++; render(); },
    pause: leave,
    async submit() {
      if (handling || state.busy || !dialog.open || state.input !== "file" || !queue.canSubmit) return;
      const shownOptions = JSON.stringify(routeOptions), shownRoute = route;
      render();
      if (routeError) { $("createStatus").textContent = routeError; return; }
      if (shownOptions !== JSON.stringify(routeOptions) || shownRoute !== route) {
        $("createStatus").textContent = "视频处理设置已变化，请核对上方更新后的路线，再次点击提交。";
        return;
      }
      const token = visit, epoch = state.epoch;
      const current = () => token === visit && epoch === state.epoch && dialog.open && state.input === "file";
      handling = true;
      try {
        const completed = await queue.submit(routeOptions, route, current);
        if (!current()) return;
        // An already running periodic refresh may contain the previous library.
        if (state.refreshPromise) await state.refreshPromise;
        if (!current()) return;
        await refresh();
        if (!current()) return;
        if (queue.items.length === 1 && completed.length === 1 && !queue.stopped) {
          dialog.close();
          $("file").value = "";
          $("materialEncoding").value = "";
          queue.select([]);
          updatePresentation();
          await openResult(completed[0]);
        }
      } catch (error) {
        if (current()) $("createStatus").textContent = `已提交的结果保留；刷新失败，请从资料库查看。${error.message}`;
      } finally { handling = false; render(); }
    },
  };
}
