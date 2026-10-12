import { literalText, relationPresentation } from "/web/course-concepts.js";

export function relationshipGraph(result) {
  const nodes = (result.nodes || []).slice(0, 24);
  const edges = (result.edges || []).filter((edge) => nodes.some((node) => node.id === edge.from) && nodes.some((node) => node.id === edge.to));
  if (!nodes.length || !edges.length) return null;
  const width = 760, cellWidth = 180, cellHeight = 86, columns = 4;
  const height = Math.max(180, Math.ceil(nodes.length / columns) * cellHeight + 32);
  const position = new Map(nodes.map((node, index) => [node.id, { x: 16 + (index % columns) * cellWidth, y: 16 + Math.floor(index / columns) * cellHeight }]));
  const details = document.createElement("details");
  details.className = "relationship-graph";
  const summary = document.createElement("summary");
  summary.textContent = "关系图（关键词线索，不代表因果或观点一致）";
  details.append(summary);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "课程来源关系图");
  const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
  title.textContent = "课程来源关系图";
  svg.append(title);
  for (const edge of edges) {
    const from = position.get(edge.from), to = position.get(edge.to);
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", String(from.x + 72)); line.setAttribute("y1", String(from.y + 25));
    line.setAttribute("x2", String(to.x + 72)); line.setAttribute("y2", String(to.y + 25));
    line.setAttribute("class", "relationship-edge");
    const presentation = relationPresentation(edge);
    line.setAttribute("stroke-dasharray", presentation.dash);
    line.setAttribute("aria-label", `${presentation.label}：${(edge.terms || []).join("、")}`);
    const edgeTitle = document.createElementNS("http://www.w3.org/2000/svg", "title");
    edgeTitle.setAttribute("data-user-content", "true");
    edgeTitle.textContent = `${presentation.label}：${(edge.terms || []).join("、")}`;
    line.append(edgeTitle);
    svg.append(line);
  }
  for (const node of nodes) {
    const point = position.get(node.id);
    const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
    const nodeTitle = document.createElementNS("http://www.w3.org/2000/svg", "title");
    nodeTitle.setAttribute("data-user-content", "true");
    nodeTitle.textContent = String(node.title || node.id);
    group.append(nodeTitle);
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("x", String(point.x)); rect.setAttribute("y", String(point.y));
    rect.setAttribute("width", "144"); rect.setAttribute("height", "50"); rect.setAttribute("rx", "8");
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("data-user-content", "true");
    label.setAttribute("x", String(point.x + 8)); label.setAttribute("y", String(point.y + 22));
    label.textContent = String(node.title || node.id).slice(0, 22);
    const count = document.createElementNS("http://www.w3.org/2000/svg", "text");
    count.setAttribute("x", String(point.x + 8)); count.setAttribute("y", String(point.y + 40));
    count.setAttribute("class", "relationship-node-meta");
    count.textContent = `${(node.evidence_ids || []).length} 条来源证据`;
    group.append(rect, label, count); svg.append(group);
  }
  details.append(svg);
  const hint = document.createElement("p");
  hint.className = "muted";
  hint.textContent = `图形显示 ${nodes.length}/${(result.nodes || []).length} 个已返回来源、${edges.length}/${(result.edges || []).length} 条已返回关系。` + "图下方的关系列表保留每条关系对应的证据 ID；无法理解图形时可直接使用列表。";
  details.append(hint);
  return details;
}

const SNAPSHOT_BYTES = 20_000_000;
const LIMIT_MESSAGE = "当前筛选范围过大。快照最多 20 MB、10,000 条出处、200 个来源、20,000 条关系和 100 MB 分组文本扫描量；请缩小课程或关键词范围后重试。";
const paragraph = text => {
  const element = document.createElement("p");
  element.textContent = text;
  return element;
};
const snapshotError = error => error?.code === "graph_snapshot_too_large" ? LIMIT_MESSAGE : error?.message || "快照无效或读取失败，请检查文件后重试。";
function snapshotBlob(snapshot) {
  const blob = new Blob([JSON.stringify(snapshot)], { type: "application/json" });
  if (blob.size > SNAPSHOT_BYTES) throw new Error(LIMIT_MESSAGE);
  return blob;
}
function downloadSnapshot(blob) {
  const object = URL.createObjectURL(blob);
  try {
    const link = document.createElement("a");
    link.href = object;
    link.download = "learnnote-filtered-comparison.json";
    link.click();
  } finally {
    setTimeout(() => URL.revokeObjectURL(object), 1000);
  }
}

export function mountGraphCompleteness(root, graph) {
  const counts = graph.counts || {}, truncated = graph.truncated || {};
  const returned = { matches: (graph.matches || []).length, nodes: (graph.nodes || []).length, edges: (graph.edges || []).length };
  const total = key => Number.isSafeInteger(counts[key]) && counts[key] >= returned[key] ? counts[key] : key === "matches" ? graph.total_matches ?? returned[key] : returned[key];
  const incomplete = Object.keys(returned).some(key => truncated[key] || total(key) > returned[key]);
  const hint = paragraph(`已返回出处 ${returned.matches}/${total("matches")}、来源 ${returned.nodes}/${total("nodes")}、关系 ${returned.edges}/${total("edges")}。${incomplete ? "当前预览已截断；导出会重新获取筛选范围内的完整图，范围过大时请缩小筛选。" : "当前筛选结果完整。"}`);
  if (graph.query_terms_truncated) hint.textContent += " 本次查询只使用前 8 个不同关键词；请减少关键词后重新查找。";
  hint.dataset.graphCompleteness = incomplete ? "truncated" : "complete";
  root.append(hint);
}

export function mountGraphSnapshotExport(root, { api, course, scope, isCurrent }) {
  const section = document.createElement("section"), button = document.createElement("button"), message = paragraph("");
  section.dataset.graphSnapshotControls = "true";
  button.type = "button";
  button.dataset.graphSnapshotExport = "true";
  button.textContent = "导出当前筛选关系图";
  message.setAttribute("role", "status");
  section.append(button, paragraph("保存本次已查找的关键词、来源与时间范围及其完整关系图。文件同时保留本课程全部可用原始出处和历史，以重建分组。更改筛选后请先重新查找。"), message);
  root.append(section);
  // Freeze submitted values, including whitespace and zero-valued time filters.
  const params = new URLSearchParams(scope);
  params.set("revision", String(course.revision));
  const path = `/api/courses/${encodeURIComponent(course.id)}/graph-snapshot?${params}`;
  const active = () => isCurrent() && section.isConnected;
  let busy = false;
  button.addEventListener("click", async () => {
    if (busy || !active()) return;
    busy = true;
    button.disabled = true;
    message.textContent = "正在导出完整筛选关系图…";
    try {
      const snapshot = await api(path);
      if (!active()) return;
      if (snapshot?.format !== "learnnote.filtered-comparison" || snapshot.schema_version !== 1) throw new Error("服务返回的快照格式无效，未导出。");
      downloadSnapshot(snapshotBlob(snapshot));
      message.textContent = "完整筛选关系图已导出，可导入为独立只读预览。";
    } catch (error) {
      if (active()) message.textContent = snapshotError(error);
    } finally {
      busy = false;
      if (active()) button.disabled = false;
    }
  });
}

function renderSnapshotPreview(root, snapshot, graph, { isCurrent }) {
  root.dataset.graphSnapshotPreview = "true";
  root.style.minWidth = "0";
  root.style.overflowWrap = "anywhere";
  const heading = document.createElement("h3");
  heading.textContent = "只读快照 · 关键词共现 · 未验证来源真实性";
  const provenance = paragraph("这里的原文、分组和关系来自文件。校验只能确认文件内部一致；不会验证来源真实性，也不会恢复课程、写入分组或连接本机原始资料。");
  const course = paragraph("课程：");
  course.append(literalText(snapshot.course?.title || snapshot.course?.id), document.createTextNode(` · 修订 ${snapshot.course?.revision ?? ""}`));
  const query = paragraph("已查找关键词：");
  const queryText = literalText(snapshot.scope?.query);
  queryText.style.whiteSpace = "pre-wrap";
  query.append(queryText);
  const terms = paragraph("实际采用的关键词：");
  terms.append(literalText((snapshot.scope?.terms || []).join("、")));
  const filters = snapshot.scope?.filters || {};
  const scope = paragraph("来源与时间筛选：");
  scope.append(literalText(`类型 ${filters.source_kind || "全部"} · 来源 ${filters.source_id || "全部"} · 起点 ${filters.start ?? "未设置"} 秒 · 终点 ${filters.end ?? "未设置"} 秒`));
  const digest = paragraph("文件一致性摘要：");
  digest.append(literalText(snapshot.digest));
  const reexport = document.createElement("button"), message = paragraph("");
  reexport.type = "button";
  reexport.dataset.graphSnapshotReexport = "true";
  reexport.textContent = "重新导出此快照";
  message.setAttribute("role", "status");
  // Store the validated original, not reconstructed preview fields or live data.
  const blob = snapshotBlob(snapshot);
  reexport.addEventListener("click", () => {
    if (!isCurrent() || !root.isConnected) return;
    try { downloadSnapshot(blob); message.textContent = "已重新导出此只读快照。"; }
    catch (error) { message.textContent = snapshotError(error); }
  });
  root.append(heading, provenance, paragraph("共同关键词不代表同义、因果或观点一致。含义分组仅是整理选择。"), course, query, terms, scope, digest, reexport, message);
  mountGraphCompleteness(root, graph);
  const graphView = relationshipGraph(graph);
  if (graphView) root.append(graphView);
  const evidenceSection = document.createElement("section"), evidenceHeading = document.createElement("h3"), embedded = new Map();
  evidenceHeading.textContent = `文件内完整出处（${(snapshot.evidence || []).length} 条，含分组历史所需出处）`;
  evidenceSection.append(evidenceHeading);
  for (const item of snapshot.evidence || []) {
    const detail = document.createElement("details"), summary = document.createElement("summary");
    detail.dataset.snapshotEvidence = item.evidence_id;
    summary.append(literalText(`${item.title || item.course_source?.title || "出处"} · ${item.locator || ""}`));
    const id = paragraph("出处 ID：");
    id.append(literalText(item.evidence_id));
    const content = document.createElement("pre");
    content.dataset.userContent = "true";
    content.textContent = String(item.text || "");
    const origin = paragraph("记录的来源（仅文件文字）：");
    origin.append(literalText(item.source_uri || "未记录"));
    const anchors = document.createElement("details"), anchorTitle = document.createElement("summary"), anchorText = document.createElement("pre");
    anchorTitle.textContent = "定位锚点与字段省略（文件记录）";
    anchorText.dataset.userContent = "true";
    anchorText.textContent = JSON.stringify({ anchors: item.metadata || {}, redacted_fields: item.redacted_fields || [] }, null, 2);
    anchors.append(anchorTitle, anchorText);
    detail.append(summary, id, content, origin, anchors);
    evidenceSection.append(detail);
    embedded.set(item.evidence_id, detail);
  }
  function citationButton(id, label) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.snapshotCitation = id;
    button.style.maxWidth = "100%";
    button.style.whiteSpace = "normal";
    button.style.overflowWrap = "anywhere";
    button.append(document.createTextNode("查看文件内出处："), literalText(label || id));
    button.disabled = !embedded.has(id);
    button.addEventListener("click", () => {
      if (!isCurrent() || !root.isConnected) return;
      const target = embedded.get(id);
      if (!target) return;
      target.open = true;
      target.scrollIntoView?.({ block: "nearest" });
      target.querySelector("summary")?.focus();
    });
    return button;
  }
  const sources = document.createElement("details"), sourceSummary = document.createElement("summary");
  sourceSummary.textContent = `筛选结果中的全部来源（${(graph.nodes || []).length} 个）`;
  sources.append(sourceSummary);
  for (const node of graph.nodes || []) {
    const item = document.createElement("p");
    item.append(literalText(node.title || node.id));
    for (const id of node.evidence_ids || []) item.append(citationButton(id));
    sources.append(item);
  }
  root.append(sources);
  const relationships = document.createElement("details"), summary = document.createElement("summary"), list = document.createElement("ol");
  summary.textContent = "关系列表（虚线为关键词共现；不表示事实关系）";
  const count = paragraph(""), more = document.createElement("button"), titles = new Map((graph.nodes || []).map(node => [node.id, node.title]));
  more.type = "button";
  more.textContent = "显示接下来的 100 条关系";
  const edges = graph.edges || [];
  let shown = 0;
  function showMore() {
    if (!isCurrent() || !root.isConnected) return;
    const end = Math.min(shown + 100, edges.length);
    for (const edge of edges.slice(shown, end)) {
      const row = document.createElement("li");
      row.append(literalText(titles.get(edge.from) || edge.from), document.createTextNode(" ↔ "), literalText(titles.get(edge.to) || edge.to),
        document.createTextNode(` · ${relationPresentation(edge).label}：`), literalText((edge.terms || []).join("、")));
      for (const citation of edge.citations || []) row.append(citationButton(citation.evidence_id, `${citation.title} · ${citation.locator}`));
      list.append(row);
    }
    shown = end;
    count.textContent = `关系列表显示 ${shown}/${edges.length} 条。导出文件保留全部关系。`;
    more.hidden = shown >= edges.length;
  }
  more.addEventListener("click", showMore);
  relationships.append(summary, count, list, more);
  root.append(relationships, evidenceSection);
  showMore();
  const groupState = snapshot.group_state || graph.concepts || [];
  if (groupState.length) {
    const groups = document.createElement("details"), groupsTitle = document.createElement("summary");
    groupsTitle.textContent = "文件内的含义分组（只读整理选择）";
    groups.append(groupsTitle);
    for (const concept of groupState) {
      const term = document.createElement("h4");
      term.append(literalText(concept.term)); groups.append(term);
      for (const group of concept.groups || []) {
        const label = paragraph("");
        label.append(literalText(group.label), document.createTextNode(` · ${(group.evidence_ids || []).length} 条出处 · ${(group.unresolved_ids || []).length} 条缺失或变化的出处`));
        groups.append(label);
      }
    }
    root.append(groups);
  }
  if (snapshot.unresolved?.length) {
    const unresolved = document.createElement("details"), title = document.createElement("summary");
    title.textContent = `文件内未解决的出处（${snapshot.unresolved.length} 条）`;
    unresolved.append(title);
    for (const record of snapshot.unresolved) {
      const row = paragraph("");
      row.append(literalText(`${record.term} · ${record.evidence_id}`), document.createTextNode(record.status === "stale" ? " · 原文已变化" : " · 原文缺失"));
      unresolved.append(row);
    }
    root.append(unresolved);
  }
  if (snapshot.sources?.length) {
    const sources = document.createElement("details"), title = document.createElement("summary");
    title.textContent = "导出时来源状态（文件记录）";
    sources.append(title);
    const labels = { ready: "可用", alias: "已关联原始视频", missing: "缺失", excluded: "未纳入证据", unindexed: "没有可用索引", unresolved_url: "链接尚未处理" };
    for (const source of snapshot.sources) {
      const row = document.createElement("details"), summary = document.createElement("summary"), details = document.createElement("pre");
      summary.append(literalText(source.reference?.title || source.reference?.id || "未命名来源"), document.createTextNode(` · ${labels[source.status] || "未知状态"} · ${(source.missing_evidence_ids || []).length} 条出处缺失 · ${(source.excluded_evidence_ids || []).length} 条未纳入`));
      details.dataset.userContent = "true";
      details.textContent = JSON.stringify(source, null, 2);
      row.append(summary, details);
      sources.append(row);
    }
    root.append(sources);
  }
  const history = document.createElement("details"), historyTitle = document.createElement("summary"), historyText = document.createElement("pre");
  historyTitle.textContent = "文件内分组与完整历史（只读）";
  historyText.dataset.userContent = "true";
  historyText.textContent = JSON.stringify(snapshot.history, null, 2);
  history.append(historyTitle, historyText);
  root.append(history);
}

export function mountGraphSnapshotImport(root, { api, isCurrent }) {
  const section = document.createElement("section"), label = document.createElement("label"), file = document.createElement("input"), message = paragraph(""), preview = document.createElement("div");
  section.dataset.graphSnapshotImporter = "true";
  label.textContent = "选择关系图快照 JSON（只读，最多 20 MB）";
  file.type = "file";
  file.accept = ".json,application/json";
  file.dataset.graphSnapshotFile = "true";
  file.style.maxWidth = "100%";
  file.style.minWidth = "0";
  message.setAttribute("role", "status");
  label.append(file);
  section.append(label, paragraph("独立检查文件中的课程、筛选范围、完整出处和分组历史；不需要本机课程或资料。"), message, preview);
  root.append(section);
  let sequence = 0;
  file.addEventListener("change", async () => {
    const selected = file.files?.[0];
    if (!selected || !isCurrent() || !section.isConnected) return;
    const token = ++sequence;
    const active = () => token === sequence && isCurrent() && section.isConnected;
    file.value = "";
    preview.replaceChildren();
    message.textContent = "正在验证只读快照…";
    try {
      if (selected.size > SNAPSHOT_BYTES) throw new Error(LIMIT_MESSAGE);
      const text = await selected.text();
      if (!active()) return;
      if (new Blob([text]).size > SNAPSHOT_BYTES) throw new Error(LIMIT_MESSAGE);
      try { JSON.parse(text); }
      catch { throw new Error("文件不是有效的 JSON 快照，请检查文件后重试。"); }
      // Preserve raw object keys for the server's strict duplicate-key parser.
      // Parsing and reserializing here would erase conflicting file contents.
      const result = await api("/api/courses/graph-snapshot/preview", { method: "POST", body: '{"snapshot":' + text + '}' });
      if (!active()) return;
      if (result?.read_only !== true || result.snapshot?.format !== "learnnote.filtered-comparison" || result.snapshot.schema_version !== 1 || !result.graph) throw new Error("服务未返回有效的只读快照预览。");
      const content = document.createElement("section");
      preview.append(content);
      renderSnapshotPreview(content, result.snapshot, result.graph, { isCurrent: active });
      message.textContent = "快照校验通过。仅打开文件预览，本机资料和分组未改变。";
    } catch (error) {
      if (active()) { preview.replaceChildren(); message.textContent = snapshotError(error); }
    }
  });
}
