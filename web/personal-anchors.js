/* The server supplies current exact targets; this picker never infers one. */
const names = { claim: "生成结论", transcript: "字幕时间段", visual: "画面窗口" };

export function annotationAnchorLabel(anchor = {}) {
  const name = names[anchor.kind];
  if (!name) return "";
  return `${name} · ${anchor.locator || anchor.selected_text?.slice(0, 80) || anchor.claim_id || anchor.window_id || ""}`;
}

export function annotationStatusMessage(item) {
  const status = item.anchor_status || {};
  if (status.resolution === "migrated") return "已按唯一且完全一致的来源定位；保留原始锚点记录。";
  if (status.resolution === "orphaned") return status.reason === "ambiguous_target"
    ? "有多个相同来源，无法确定原出处。请重新选择结论、字幕或画面以修复。"
    : "原出处已变化或不可用。请重新选择结论、字幕或画面以修复。";
  if (status.stale) return status.repairable
    ? "原文版本已变化；重新选择当前正文以修复出处。"
    : "原文版本已变化；没有可恢复的引用片段。";
  return "";
}

export function installAnnotationAnchors({ state, api, notice, document: doc = document }) {
  const picker = doc.createElement("details");
  picker.id = "annotationAnchorPicker";
  picker.innerHTML = '<summary>关联结论、字幕或画面</summary><label for="annotationAnchorKind">出处类型</label><select id="annotationAnchorKind"><option value="claim">生成结论</option><option value="transcript">字幕时间段</option><option value="visual">画面窗口</option></select><label for="annotationAnchorTarget">选择明确出处</label><select id="annotationAnchorTarget"></select><button id="applyAnnotationAnchor" type="button" disabled>关联所选出处</button><p id="annotationAnchorStatus" class="muted" aria-live="polite"></p>';
  doc.getElementById("annotationForm").append(picker);
  const kind = picker.querySelector("#annotationAnchorKind"), select = picker.querySelector("#annotationAnchorTarget");
  const apply = picker.querySelector("#applyAnnotationAnchor"), status = picker.querySelector("#annotationAnchorStatus");
  let sequence = 0, targets = [], owner = "";
  const sourceKey = () => state.selected ? `${state.selected.kind}:${state.selected.id}` : "";
  function draw() {
    select.replaceChildren();
    for (const [index, target] of targets.entries()) {
      if (target.anchor.kind !== kind.value) continue;
      const option = doc.createElement("option");
      option.setAttribute("data-user-content", ""); option.value = String(index); option.textContent = target.label;
      select.append(option);
    }
    apply.disabled = !select.options.length;
    status.textContent = select.options.length ? "选定并关联后保存。用户文字保持原样。" : "暂无当前可用出处；已有批注会保留，可引用当前正文或稍后修复。";
  }
  async function load() {
    const current = ++sequence, selected = state.selected, key = sourceKey();
    targets = []; owner = ""; draw(); apply.disabled = true;
    if (selected?.kind !== "task") return;
    status.textContent = "正在读取当前出处…";
    try {
      const response = await api(`/api/personal/task/${encodeURIComponent(selected.id)}/targets`);
      if (current !== sequence || sourceKey() !== key || !picker.open) return;
      targets = response.targets || []; owner = key; draw();
    } catch {
      if (current === sequence && sourceKey() === key) status.textContent = "出处暂不可用，批注仍可保存。稍后重新打开以重试。";
    }
  }
  picker.addEventListener("toggle", () => { if (picker.open) load(); else { sequence++; owner = ""; } });
  kind.onchange = draw;
  apply.onclick = () => {
    const target = targets[Number(select.value)];
    if (apply.disabled || owner !== sourceKey() || !target || target.anchor.kind !== kind.value) return;
    state.annotationEditingAnchor = { ...target.anchor };
    state.annotationQuoteReanchored = false;
    doc.getElementById("annotationQuote").textContent = annotationAnchorLabel(target.anchor);
    status.textContent = "已关联，保存批注后生效。";
    notice("已选择出处，保存后生效。");
  };
  return {
    reset() { sequence++; targets = []; owner = ""; picker.open = false; draw(); },
  };
}
