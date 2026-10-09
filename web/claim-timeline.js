/* Claims are anchored by persisted Unicode spans, never by rendered text/title. */
export const claimStatus = verification => ({
  direct: "直接支持", located_only: "仅定位 · 待核对", inference: "推断 · 待核对", pending_review: "待核对",
})[verification] || "待核对";

export function claimTimelineModel(mapped, { taskId, text, revision }) {
  if (typeof text !== "string" || !mapped || mapped.schema_version !== 6 || mapped.requires_rebuild || mapped.task_id !== taskId ||
      mapped.source_revision_kind !== "normalized_note_utf8_sha256" || !/^[a-f0-9]{64}$/.test(revision || "") ||
      mapped.source_revision !== revision || !Array.isArray(mapped.claims) || !Array.isArray(mapped.evidence)) return null;
  const points = Array.from(text), evidence = new Map(), ids = new Set(), entries = [];
  for (const item of mapped.evidence) {
    if (!item || typeof item.evidence_id !== "string" || !item.evidence_id || evidence.has(item.evidence_id)) return null;
    if (!["transcript", "visual", "document"].includes(item.kind)) return null;
    if (item.kind !== "document" && (![item.start, item.end].every(value => typeof value === "number" && Number.isFinite(value)) || item.start < 0 || item.end < item.start)) return null;
    evidence.set(item.evidence_id, item);
  }
  let previousEnd = 0;
  for (const claim of mapped.claims) {
    const span = claim?.source_span;
    if (!claim || typeof claim.claim_id !== "string" || !claim.claim_id || ids.has(claim.claim_id) ||
        !span || span.unit !== "unicode_codepoints" || !Number.isSafeInteger(span.start) || !Number.isSafeInteger(span.end) ||
        span.start < previousEnd || span.end <= span.start || span.end > points.length || points.slice(span.start, span.end).join("") !== claim.text ||
        !Array.isArray(claim.evidence_ids) || !Array.isArray(claim.candidate_evidence_ids) ||
        !["direct", "located_only", "inference", "pending_review"].includes(claim.verification) ||
        (claim.verification === "direct") !== Boolean(claim.evidence_ids.length)) return null;
    const refs = [...new Set([...claim.evidence_ids, ...claim.candidate_evidence_ids])];
    if (refs.some(id => !evidence.has(id))) return null;
    ids.add(claim.claim_id); previousEnd = span.end;
    entries.push({ claim, targets: refs.map(id => ({ ...evidence.get(id), candidate: !claim.evidence_ids.includes(id) })) });
  }
  return { taskId, revision, entries };
}

export function activeClaims(model, seconds) {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return [];
  return (model?.entries || []).filter(entry => entry.targets.some(target =>
    (!entry.claim.evidence_ids.length || !target.candidate) && target.kind !== "document" &&
    target.start <= seconds && (target.end === target.start ? seconds === target.end : seconds < target.end)));
}

export function claimNoteTarget(note, claim) {
  const matches = [...note.querySelectorAll("[data-note-start][data-note-end]")].filter(node =>
    Number(node.dataset.noteStart) <= claim.source_span.start && Number(node.dataset.noteEnd) >= claim.source_span.end);
  return matches.length === 1 ? matches[0] : null;
}

export function createClaimTimeline({ note, container, readMap, current, onOpen, timestamp, document: doc = document }) {
  let generation = 0, model = null, source = null, entries = [], lastTime, activeKey = "", follow = false;
  let status, list, followInput;
  function clearActive() {
    for (const entry of entries) {
      entry.block?.classList.remove("note-claim-active");
      entry.marker?.removeAttribute("aria-current");
    }
    activeKey = "";
    list?.replaceChildren();
  }
  function reset() {
    generation++; clearActive();
    for (const entry of entries) entry.marker?.remove();
    entries = []; model = null; source = null; lastTime = undefined;
    container.replaceChildren(); container.hidden = true;
  }
  function createButton(label, callback) {
    const button = doc.createElement("button"); button.type = "button"; button.textContent = label;
    button.onclick = callback; return button;
  }
  function open(entry, target) {
    if (!model || !current(source) || !entries.includes(entry)) return;
    return onOpen(target, source.taskId);
  }
  function sync(seconds, { scroll = true } = {}) {
    lastTime = seconds;
    if (!model || !current(source)) { clearActive(); return; }
    const active = activeClaims(model, seconds), selected = new Set(active.map(entry => entry.claim.claim_id));
    const key = active.map(entry => entry.claim.claim_id).join("|");
    for (const entry of entries) {
      const isActive = selected.has(entry.claim.claim_id);
      if (isActive) entry.marker?.setAttribute("aria-current", "true");
      else entry.marker?.removeAttribute("aria-current");
    }
    const blocks = new Set(entries.map(entry => entry.block).filter(Boolean));
    const activeBlocks = new Set(entries.filter(entry => selected.has(entry.claim.claim_id)).map(entry => entry.block));
    for (const block of blocks) block.classList.toggle("note-claim-active", activeBlocks.has(block));
    if (key === activeKey) return;
    if (list.contains(doc.activeElement)) {
      status.textContent = "来源列表暂时保留当前键盘操作；笔记标记仍随播放更新。";
      activeKey = "\0";
      return;
    }
    activeKey = key;
    list.replaceChildren();
    status.textContent = active.length ? `当前位置关联 ${active.length} 条结论；来源定位不等于事实验证。` : "当前位置没有精确匹配的结论来源。";
    for (const entry of entries.filter(entry => selected.has(entry.claim.claim_id))) {
      const row = doc.createElement("li"), label = doc.createElement("p");
      row.dataset.claimId = entry.claim.claim_id;
      label.textContent = `${claimStatus(entry.claim.verification)} · ${entry.claim.text}`;
      row.append(label);
      for (const target of entry.targets) {
        const label = target.kind === "document" ? `文档 ${target.locator || "出处"}` : `${timestamp(target.start)} – ${timestamp(target.end)}`;
        const button = createButton(`${target.candidate ? "候选来源 · " : "来源 · "}${label}`, () => open(entry, target));
        button.dataset.evidenceId = target.evidence_id;
        row.append(button);
      }
      if (!entry.block) { const missing = doc.createElement("small"); missing.textContent = "笔记定位标记缺失，未猜测正文位置。"; row.append(missing); }
      list.append(row);
    }
    const target = entries.find(entry => selected.has(entry.claim.claim_id) && entry.block)?.block;
    const selection = doc.getSelection?.();
    if (scroll && follow && target && !note.hidden && !note.contains(doc.activeElement) &&
        !(selection && !selection.isCollapsed && (note.contains(selection.anchorNode) || note.contains(selection.focusNode)))) {
      const bounds = target.getBoundingClientRect(), height = doc.documentElement.clientHeight;
      if (target.getClientRects().length && (bounds.top < 0 || bounds.bottom > height)) target.scrollIntoView({ block: "center", behavior: "instant" });
    }
  }
  async function load(snapshot) {
    reset();
    if (snapshot.kind !== "task") return;
    source = snapshot;
    const request = generation;
    container.hidden = false;
    const heading = doc.createElement("strong"); heading.textContent = "结论与笔记联动";
    status = doc.createElement("p"); status.className = "muted";
    status.textContent = "正在读取已保存的逐条来源映射…";
    container.append(heading, status);
    try {
      const mapped = snapshot.hasMap ? await readMap(snapshot.taskId) : null;
      if (request !== generation || !current(snapshot)) return;
      model = claimTimelineModel(mapped, snapshot);
      if (!model) { status.textContent = "没有与当前笔记版本精确对应的来源映射，已停用结论联动。编辑后的笔记不会沿用旧定位。"; return; }
      const label = doc.createElement("label"); label.className = "check";
      followInput = doc.createElement("input"); followInput.type = "checkbox"; followInput.checked = follow;
      followInput.id = "followNote";
      label.append(followInput, doc.createTextNode("跟随笔记滚动"));
      followInput.onchange = () => { follow = followInput.checked; activeKey = "\0"; sync(lastTime); };
      list = doc.createElement("ol"); list.className = "claim-timeline-list";
      list.setAttribute("aria-label", "当前位置关联的结论来源");
      list.onfocusout = () => queueMicrotask(() => sync(lastTime, { scroll: false }));
      container.append(label, list);
      entries = model.entries.map((entry, index) => {
        const block = claimNoteTarget(note, entry.claim), result = { ...entry, block };
        if (block) {
          const marker = createButton(`结论 ${index + 1} · ${claimStatus(entry.claim.verification)}`, () => open(result, result.targets[0]));
          marker.className = "time-link note-claim-marker"; marker.dataset.claimId = entry.claim.claim_id;
          marker.disabled = !entry.targets.length;
          marker.setAttribute("aria-label", `${marker.textContent} · ${entry.targets.length ? "查看来源" : "暂无可定位来源"}`);
          block.append(marker); result.marker = marker;
        }
        return result;
      });
      activeKey = "\0";
      status.textContent = "播放或选择来源后显示关联结论；仅定位、候选来源和推断仍需核对。";
      if (lastTime !== undefined) sync(lastTime, { scroll: false });
    } catch {
      if (request === generation && current(snapshot)) status.textContent = "逐条来源暂不可读取，结论联动已停用。可继续核对字幕与原视频。";
    }
  }
  return { load, sync, reset, clearActive };
}
