import { api, escapeHtml as esc, taskAsset } from "/web/desk-api.js";

// Viewing an earlier generated note never replaces a personal revision.
export function installSummaryVersions({ state, openItem, notice }) {
  const dialog = document.createElement("dialog");
  dialog.id = "summaryVersionsDialog";
  dialog.className = "tools-dialog";
  document.body.append(dialog);
  let epoch = 0;
  dialog.addEventListener("close", () => epoch++);
  const stamp = (date) => {
    const value = new Date(date);
    return Number.isFinite(value.getTime())
      ? value.toLocaleString("zh-CN", { hour12: false })
      : "时间未知";
  };
  function header(title, back) {
    dialog.innerHTML = `<header>${back ? '<button data-version-back type="button">← 返回</button>' : ""}<h2>${esc(title)}</h2><button data-version-close type="button" aria-label="关闭">×</button></header><div id="summaryVersionsBody"></div><p id="summaryVersionStatus" role="status"></p>`;
    dialog.querySelector("[data-version-close]").onclick = () => dialog.close();
    if (back) dialog.querySelector("[data-version-back]").onclick = back;
    if (!dialog.open) dialog.showModal();
  }
  const body = () => dialog.querySelector("#summaryVersionsBody");
  const status = (value) => {
    const element = dialog.querySelector("#summaryVersionStatus");
    if (element) element.textContent = value;
  };
  function related(source) {
    const family = new Set([source.id, source.source_task_id].filter(Boolean));
    for (let pass = 0; pass < state.items.length; pass++) {
      const previous = family.size;
      for (const item of state.items)
        if (
          item.kind === "task" &&
          (family.has(item.id) || family.has(item.source_task_id))
        ) {
          family.add(item.id);
          if (item.source_task_id) family.add(item.source_task_id);
        }
      if (family.size === previous) break;
    }
    return state.items.filter(
      (item) =>
        item.kind === "task" && item.id !== source.id && family.has(item.id),
    );
  }
  async function preview(source, version, data) {
    const token = ++epoch;
    header("历史生成稿", () => list(source, data));
    body().innerHTML = '<p class="muted">正在读取历史内容…</p>';
    try {
      const result = await api(
        `/api/tasks/${encodeURIComponent(source.id)}/summary-versions/${encodeURIComponent(version.id)}`,
      );
      if (token !== epoch || !dialog.open) return;
      LearnNoteMarkdown.configure({
        safeNoteMediaUrl: (value) => taskAsset(value, source.id),
      });
      body().innerHTML = `<p class="muted">${esc(stamp(result.created_at))} · 历史生成内容，当前笔记未改变。</p><div class="tool-actions"><button data-copy-version type="button">复制 Markdown</button><button data-download-version type="button">下载 Markdown</button></div><article class="assistant-answer summary-version-preview">${LearnNoteMarkdown.markdownToHtml(result.markdown)}</article><details><summary>查看 Markdown 原文</summary><textarea rows="10" readonly aria-label="历史 Markdown 原文"></textarea></details>`;
      body().querySelector("textarea").value = result.markdown;
      body().querySelector("[data-copy-version]").onclick = async () => {
        try {
          await navigator.clipboard.writeText(result.markdown);
          if (token === epoch) status("已复制历史生成稿。");
        } catch {
          if (token === epoch) {
            body().querySelector("details").open = true;
            body().querySelector("textarea").select();
            status("浏览器未允许自动复制，已选中原文，可手动复制。");
          }
        }
      };
      body().querySelector("[data-download-version]").onclick = () => {
        const url = URL.createObjectURL(
          new Blob([result.markdown], { type: "text/markdown;charset=utf-8" }),
        );
        const link = document.createElement("a");
        link.href = url;
        link.download = `${(result.title || source.title || "笔记").replace(/[<>:"/\\|?*\x00-\x1f]/g, "_").slice(0, 100)}-历史生成稿.md`;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      };
    } catch (error) {
      if (token !== epoch || !dialog.open) return;
      body().innerHTML =
        '<p>这份历史内容暂时无法读取。</p><button data-retry-version type="button">重试</button>';
      status(error.message);
      body().querySelector("button").onclick = () =>
        preview(source, version, data);
    }
  }
  function list(source, data) {
    epoch++;
    header("历史版本与关联笔记");
    const versions = data.versions || [],
      rows = related(source);
    body().innerHTML = `<p class="muted">重新生成前保留上一份生成稿。查看和下载历史内容不会覆盖当前正文或个人修改。</p><button class="version-row" data-current-version><strong>${esc(source.title)}</strong><small>返回当前笔记</small></button><h3>历史生成稿</h3>${versions.length ? versions.map((item, index) => `<button class="version-row" data-summary-version="${index}"><strong>${esc(item.title || "历史笔记")}</strong><small>${esc(stamp(item.created_at))} · ${Math.max(1, Math.ceil(item.size_bytes / 1024))} KB${item.current ? " · 与当前生成稿相同" : ""}</small></button>`).join("") : '<p class="muted">还没有保留的历史生成稿。下次重新生成时，会先保存当前内容；旧版本未保存的生成稿无法补回。</p>'}${rows.length ? "<details><summary>关联笔记与视频片段</summary>" + rows.map((item, index) => `<button class="version-row" data-related-version="${index}"><strong>${esc(item.title)}</strong><small>${item.learning_range?.start !== undefined ? "视频片段" : "重新整理"}</small></button>`).join("") + "</details>" : ""}`;
    body().querySelector("[data-current-version]").onclick = () =>
      dialog.close();
    body()
      .querySelectorAll("[data-summary-version]")
      .forEach((button) => {
        button.onclick = () =>
          preview(
            source,
            versions[Number(button.dataset.summaryVersion)],
            data,
          );
      });
    body()
      .querySelectorAll("[data-related-version]")
      .forEach((button) => {
        button.onclick = () => {
          dialog.close();
          openItem(rows[Number(button.dataset.relatedVersion)]).catch((error) =>
            notice(error.message),
          );
        };
      });
  }
  document.getElementById("openVersions").onclick = async () => {
    const source = state.selected ? { ...state.selected } : null;
    if (source?.kind !== "task") return;
    const token = ++epoch;
    header("历史版本与关联笔记");
    body().innerHTML = '<p class="muted">正在读取历史版本…</p>';
    try {
      const data = await api(
        `/api/tasks/${encodeURIComponent(source.id)}/summary-versions`,
      );
      if (token === epoch && dialog.open) list(source, data);
    } catch (error) {
      if (token !== epoch || !dialog.open) return;
      body().innerHTML =
        '<p>暂时无法读取历史版本，当前笔记未改变。</p><button data-retry-versions type="button">重试</button>';
      status(error.message);
      body().querySelector("button").onclick = () =>
        document.getElementById("openVersions").click();
    }
  };
}
