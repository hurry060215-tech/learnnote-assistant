// Literal DOM rendering shared by local catalog recovery panels.
export function make(tag, text = "", id = "") {
  const element = document.createElement(tag);
  if (text) element.textContent = text;
  if (id) element.id = id;
  return element;
}

export function addRecoveryRows(results, items, unresolved = false) {
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
export function errorText(error) {
  return `${error?.message || "目录恢复请求失败，请重试。"}${error?.code ? `（${error.code}）` : ""}`;
}

export function createMaterialRecoveryView(container) {
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
  return { root, status, retry, input, selected, previewButton, applyButton, progress, results, taskButton };
}
