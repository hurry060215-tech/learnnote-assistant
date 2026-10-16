/* Local cited candidates. Imported snapshots never resolve against live sources. */
import { literalText, relationPresentation } from "/web/course-concepts.js";
import { relationshipGraph } from "/web/course-graph-snapshot.js";

const MAX_BYTES = 20_000_000;
const element = (tag, text = "") => { const node = document.createElement(tag); node.textContent = text; return node; };
export function relationQuery(values, course) {
  const query = new URLSearchParams();
  for (const key of ["q", "source_id", "source_kind", "start", "end"]) if (values[key] !== "") query.set(key, values[key]);
  if (course) { query.set("course_id", course.id); query.set("revision", course.revision); }
  return query.toString();
}
export function mountCitedRelations(root, { api, course = null, isCurrent, openEvidence }) {
  let sequence = 0, snapshot = null, imported = false, visible = 50;
  const active = ticket => isCurrent() && root.isConnected && ticket === sequence;
  const description = element("p", "仅从本机已索引出处查找简单句中的原文陈述与可能的否定差异。词形相同不证明同义；未识别的表达不等于错误。不调用模型，也不把这些关系标为事实已验证。");
  description.className = "muted";
  const form = element("form"), controls = {}, results = element("section"), status = element("p");
  form.dataset.citedRelationForm = "true"; results.dataset.citedRelationResults = "true";
  status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
  const field = (key, label, type = "text") => {
    const title = element("label", label), input = element("input");
    input.id = `relation-${key}`; title.htmlFor = input.id; input.type = type;
    if (type === "number") { input.min = "0"; input.step = "0.1"; }
    else input.maxLength = key === "q" ? 200 : 128;
    controls[key] = input; form.append(title, input); return input;
  };
  field("q", "关键词（可留空，不进行同义词扩展）");
  const kindLabel = element("label", "来源类型"), kind = element("select");
  kind.id = "relation-source_kind"; kindLabel.htmlFor = kind.id; controls.source_kind = kind;
  for (const [value, label] of [["", "全部来源"], ["task", "视频"], ["material", "文档"]]) {
    const option = element("option", label); option.value = value; kind.append(option);
  }
  form.append(kindLabel, kind);
  const source = field("source_id", "具体来源 ID（可留空，可从下方出处选取）");
  field("start", "起点（秒，可留空）", "number"); field("end", "终点（秒，可留空）", "number");
  const generate = element("button", course ? "生成本课程引用关系" : "生成全库引用关系");
  generate.type = "submit"; form.append(generate);
  const importLabel = element("label", "导入引用关系文件（只读，最多 20 MB）"), file = element("input");
  file.id = "relation-file"; importLabel.htmlFor = file.id; file.type = "file"; file.accept = ".json,application/json";
  file.dataset.citedRelationFile = "true";
  root.append(description, form, importLabel, file, status, results);
  function button(label, action) {
    const node = element("button", label), ticket = sequence; node.type = "button";
    node.addEventListener("click", async () => {
      if (!active(ticket) || !node.isConnected) return;
      try { await action(); } catch (error) { if (active(ticket)) status.textContent = error.message; }
    });
    return node;
  }
  function clear() { snapshot = null; visible = 50; results.replaceChildren(); }
  function download() {
    const blob = new Blob([JSON.stringify(snapshot, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob), link = element("a");
    link.href = url; link.download = "learnnote-cited-relations.json"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
  function render() {
    results.replaceChildren();
    const graph = snapshot.graph, nodes = new Map(graph.nodes.map(node => [node.id, node]));
    const warning = element("p", imported ? "文件内部一致性已核对，身份与内容真实性未验证。只读查看文件内出处，不访问或重建本机资料。" : "这是本次生成时的出处快照。来源修改后请重新生成；导出不会自动刷新或改变原文。");
    const scope = element("p", snapshot.scope.kind === "course" ? "范围：课程 · " : "范围：本机已索引资料库");
    if (snapshot.scope.title) scope.append(literalText(snapshot.scope.title));
    const counts = element("p", `扫描 ${graph.counts.scanned_evidence} 条出处，筛选后 ${graph.counts.filtered_evidence} 条；${graph.nodes.length} 个词形节点，${graph.edges.length} 条候选关系。仅覆盖可识别的简单句。`);
    const exporting = button(imported ? "重新导出原文件快照" : "导出当前引用关系快照", download);
    exporting.dataset.citedRelationExport = "true";
    results.append(warning, scope, counts, element("p", graph.warning), element("p", "文件保留完整出处文字与标题；分享前请检查隐私。"), exporting);
    const view = relationshipGraph({ ...graph, nodes: graph.nodes.map(node => ({ ...node, title: node.spellings[0] || node.label })) });
    if (view) results.append(view);
    if (!imported) {
      const browse = element("details"), title = element("summary", "按图中词形筛选（前 24 个节点）");
      browse.append(title);
      for (const node of graph.nodes.slice(0, 24)) {
        const select = button("", () => { controls.q.value = node.label; return load(); });
        select.append(literalText(node.spellings[0] || node.label)); browse.append(select);
      }
      results.append(browse);
    }
    const heading = element("h3", `引用关系列表 · 显示 ${Math.min(visible, graph.edges.length)}/${graph.edges.length}`);
    results.append(heading);
    if (!graph.edges.length) results.append(element("p", "没有符合筛选条件的候选关系。这不表示来源没有联系或没有分歧。可缩小课程范围，或使用课程中的关键词对照与含义分组。"));
    for (const edge of graph.edges.slice(0, visible)) {
      const card = element("article"), title = element("h4"), label = relationPresentation(edge);
      card.dataset.citedRelationKind = edge.kind;
      title.append(literalText(`${nodes.get(edge.from)?.spellings[0] || edge.from} · ${edge.predicate} · ${nodes.get(edge.to)?.spellings[0] || edge.to}`));
      card.append(title, element("p", label.label));
      for (const citation of edge.citations) {
        const section = element("section"), quote = element("blockquote"), meta = element("p");
        quote.append(literalText(citation.quote));
        meta.append(literalText(`${citation.title} · ${citation.locator || "未记录位置"}`));
        section.append(meta, quote);
        const full = element("details"), summary = element("summary", "完整出处与定位字段"), text = element("pre");
        const evidence = snapshot.evidence.find(item => item.evidence_id === citation.evidence_id);
        text.append(literalText(evidence?.text || ""));
        full.append(summary, text, literalText(JSON.stringify({ evidence_id: citation.evidence_id, source: citation.source, anchors: citation.anchors, source_uri: citation.source_uri, quote_start: citation.quote_start, quote_end: citation.quote_end, offset_unit: "Unicode codepoints" }, null, 2)));
        section.append(full);
        if (!imported) {
          const open = button("打开本机出处", () => openEvidence(citation.evidence_id));
          open.dataset.citedRelationOpen = citation.evidence_id;
          section.append(open, button("仅看此来源", () => { source.value = citation.source.id; return load(); }));
        }
        card.append(section);
      }
      results.append(card);
    }
    if (visible < graph.edges.length) results.append(button("再显示 50 条关系", () => { visible += 50; render(); }));
  }
  async function load() {
    const ticket = ++sequence; clear(); imported = false;
    generate.disabled = true; status.textContent = "正在只读生成引用关系…";
    const values = Object.fromEntries(Object.entries(controls).map(([key, input]) => [key, input.value]));
    try {
      const result = await api(`/api/concept-relations?${relationQuery(values, course)}`);
      if (!active(ticket)) return;
      snapshot = result; render(); status.textContent = "已生成。没有修改原文、含义分组或个人核对记录。";
    } catch (error) { if (active(ticket)) status.textContent = error.message; }
    finally { if (active(ticket)) generate.disabled = false; }
  }
  form.addEventListener("submit", event => { event.preventDefault(); if (!generate.disabled) void load(); });
  for (const input of Object.values(controls)) input.addEventListener("input", () => {
    ++sequence; clear(); generate.disabled = false; status.textContent = "筛选已变化，请重新生成。";
  });
  file.addEventListener("change", async () => {
    const selected = file.files?.[0]; if (!selected) return;
    file.value = "";
    const ticket = ++sequence; clear(); generate.disabled = false;
    status.textContent = "正在校验文件内出处与关系…";
    try {
      if (selected.size > MAX_BYTES) throw new Error("文件超过 20 MB，未读取。请选择较小快照。");
      const raw = await selected.text(); if (!active(ticket)) return;
      const result = await api("/api/concept-relations/preview", { method: "POST", body: `{"snapshot":${raw}}` });
      if (!active(ticket)) return;
      snapshot = result.snapshot; imported = true; render(); status.textContent = result.warning;
    } catch (error) { if (active(ticket)) status.textContent = error.message; }
  });
}
