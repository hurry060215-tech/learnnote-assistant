/* Course-local organizational choices. Evidence text is never edited here. */
export function literalText(value) {
  const span = document.createElement("span");
  span.dataset.userContent = "true";
  span.style.minWidth = "0";
  span.style.overflowWrap = "anywhere";
  span.textContent = String(value ?? "");
  return span;
}

export function relationPresentation(edge) {
  if (edge.kind === "keyword_cooccurrence") return { label: "关键词共现 · 不代表同义、因果或共识", dash: "6 4" };
  if (edge.kind === "inferred") return { label: "推断关系 · 尚未核实", dash: "2 4" };
  // An unknown backend kind must never inherit the keyword/factual label.
  return { label: "未识别的关系类型 · 请核对出处", dash: "1 5" };
}

export function mountConceptControls(root, result, { api, course, isCurrent, reload, openEvidence }) {
  const section = document.createElement("section");
  section.dataset.conceptControls = "true";
  const title = document.createElement("h3");
  title.textContent = "同名词的含义分组";
  const hint = document.createElement("p");
  hint.textContent = "分组只用于本课程的整理，不表示已证实同义。拆分所选出处；合并会包含所选组在本课程内的全部出处（含筛选范围外）。原文不会改变。";
  const message = document.createElement("p");
  message.setAttribute("role", "status");
  section.append(title, hint, message);
  let busy = false, pending = null;
  const active = () => isCurrent() && section.isConnected;
  async function save(action, { refresh = true, progress = "正在保存本机分组…" } = {}) {
    if (busy || !active()) return;
    busy = true;
    const buttons = [...section.querySelectorAll("button")];
    buttons.forEach(button => { button.disabled = true; });
    message.textContent = progress;
    try {
      await action();
      if (active() && refresh) await reload();
    } catch (error) {
      if (active()) message.textContent = error.message || "保存失败，请重新查找并核对。";
    } finally {
      busy = false;
      if (active()) buttons.forEach(button => { button.disabled = false; });
    }
  }
  const matches = new Map((result.matches || []).map(item => [item.evidence_id, item]));
  for (const [index, concept] of (result.concepts || []).entries()) {
    const field = document.createElement("fieldset"), legend = document.createElement("legend");
    field.style.minWidth = "0";
    legend.style.maxWidth = "100%";
    legend.append(literalText(concept.term));
    field.dataset.conceptTerm = concept.term;
    field.append(legend);
    const selectedEvidence = [], selectedGroups = [];
    for (const group of concept.groups) {
      const groupLabel = document.createElement("label"), groupBox = document.createElement("input");
      groupBox.type = "checkbox";
      groupLabel.className = "check";
      groupBox.dataset.conceptGroup = group.id;
      selectedGroups.push(groupBox);
      groupLabel.append(groupBox, document.createTextNode(" 合并此组："), literalText(group.label), document.createTextNode(` · ${group.evidence_ids.length} 条出处`));
      field.append(groupLabel);
      for (const id of [...group.evidence_ids, ...group.unresolved_ids]) {
        const item = matches.get(id);
        if (!item) continue;
        const row = document.createElement("div"), label = document.createElement("label"), checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        label.className = "check";
        checkbox.dataset.conceptEvidence = id;
        selectedEvidence.push(checkbox);
        label.append(checkbox, literalText(`${item.title} · ${item.locator}`), document.createTextNode(group.unresolved_ids.includes(id) ? " · 原文已变化，需重新核对" : ""));
        const source = document.createElement("button");
        source.type = "button";
        source.textContent = "核对出处";
        source.addEventListener("click", async () => {
          if (!active()) return;
          try { await openEvidence(id); } catch (error) { if (active()) message.textContent = error.message; }
        });
        row.append(label, source);
        field.append(row);
      }
      if (group.unresolved_ids.length) {
        const unresolved = document.createElement("p");
        unresolved.dataset.conceptUnresolved = "true";
        unresolved.style.overflowWrap = "anywhere";
        unresolved.append(document.createTextNode(`${group.unresolved_ids.length} 条出处已缺失或变化，保留旧分组，暂不用于关系或合并。`), literalText(group.unresolved_ids.slice(0, 8).join("、")));
        field.append(unresolved);
      }
    }
    const nameLabel = document.createElement("label"), name = document.createElement("input");
    name.id = `conceptGroupLabel${index}`;
    name.maxLength = 120;
    nameLabel.htmlFor = name.id;
    nameLabel.textContent = "新组的含义备注";
    const split = document.createElement("button"), merge = document.createElement("button");
    split.type = merge.type = "button";
    split.dataset.conceptAction = "split";
    merge.dataset.conceptAction = "merge";
    split.textContent = "将所选出处拆为新组";
    merge.textContent = "合并所选组";
    const edit = action => {
      const evidence_ids = action === "split" ? selectedEvidence.filter(el => el.checked).map(el => el.dataset.conceptEvidence) : [];
      const group_ids = action === "merge" ? selectedGroups.filter(el => el.checked).map(el => el.dataset.conceptGroup) : [];
      if (!name.value.trim() || (action === "split" ? !evidence_ids.length : group_ids.length < 2)) {
        message.textContent = "请填写含义备注，并选择出处或至少两个待合并的组。";
        return;
      }
      const payload = { action, term: concept.term, label: name.value, evidence_ids, group_ids, revision: result.identity_revision,
        course_revision: course.revision, scope_revision: concept.scope_revision };
      const key = JSON.stringify(payload);
      if (pending?.key !== key) pending = { key, payload: { ...payload, request_id: crypto.randomUUID().replaceAll("-", "") } };
      const submission = pending.payload;
      return save(() => api(`/api/courses/${encodeURIComponent(course.id)}/concepts`, { method: "POST", body: JSON.stringify(submission) }));
    };
    split.addEventListener("click", () => edit("split"));
    merge.addEventListener("click", () => edit("merge"));
    field.append(nameLabel, name, split, merge);
    section.append(field);
  }
  const backup = document.createElement("button");
  backup.type = "button";
  backup.dataset.conceptBackup = "true";
  backup.textContent = "导出分组与完整历史";
  backup.addEventListener("click", () => save(async () => {
    const value = await api(`/api/courses/${encodeURIComponent(course.id)}/concepts/backup`);
    if (!active()) return;
    const object = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = object;
    link.download = `concept-groups-${course.id}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(object), 1000);
    message.textContent = "分组与完整历史已导出。";
  }, { refresh: false, progress: "正在导出本课程的分组历史…" }));
  const importLabel = document.createElement("label"), file = document.createElement("input");
  importLabel.textContent = "恢复本课程的分组备份（保留已有的后续编辑）";
  file.type = "file";
  file.accept = ".json,application/json";
  file.dataset.conceptRestore = "true";
  importLabel.append(file);
  file.addEventListener("change", () => {
    const selected = file.files?.[0];
    if (!selected) return;
    return save(async () => {
      if (selected.size > 20_000_000) throw new Error("分组备份超过 20 MB，未导入。");
      const value = JSON.parse(await selected.text());
      if (!active()) return;
      await api(`/api/courses/${encodeURIComponent(course.id)}/concepts/restore`, { method: "POST", body: JSON.stringify({ revision: result.identity_revision, backup: value }) });
    });
  });
  section.append(backup, importLabel);
  root.append(section);
}
