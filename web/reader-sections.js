// Read-only view of the backend's attempt-owned partial-note projection.
// Saved Markdown and user editions remain the editing/export source of truth.
const hash = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const range = item => Number.isFinite(item?.start) && Number.isFinite(item?.end)
  && item.start >= 0 && item.end >= item.start;
const overlaps = (a, b) => Math.max(a.start, b.start) < Math.min(a.end, b.end)
  || (a.start === a.end && a.start >= b.start && a.start <= b.end);

export function sectionPlan(payload, task, edition) {
  if (task?.kind !== "task" || edition?.edited
      || !["running", "cancelling", "failed", "cancelled"].includes(task.status)
      || payload?.schema_version !== 1 || payload.task_id !== task.id
      || payload.task_updated_at !== task.updated_at || payload.status !== "draft"
      || payload.reason !== "ready" || payload.verified !== false
      || !/^[a-f0-9]{12}$/.test(payload.attempt_id || "")
      || !hash(payload.source_revision) || !hash(payload.revision)
      || !Array.isArray(payload.sections)) return null;
  const seen = new Set(), outlines = [], batches = [];
  for (const item of payload.sections) {
    if (!item || typeof item.id !== "string" || !/^[a-z0-9-]+$/.test(item.id)
        || seen.has(item.id) || !hash(item.revision) || !range(item) || item.verified !== false) return null;
    seen.add(item.id);
    if (item.kind === "temporal_outline") {
      if (item.status !== "draft" || item.summary_generated !== false
          || !Array.isArray(item.excerpts) || !item.excerpts.length
          || item.excerpts.some(excerpt => !range(excerpt) || typeof excerpt.text !== "string"
            || excerpt.start < item.start || excerpt.end > item.end)) return null;
      outlines.push({ ...item, batches: [] });
    } else if (item.kind === "vision_batch") {
      if (item.status !== "evidence_pending" || typeof item.markdown !== "string"
          || !hash(payload.generation_revision) || !Array.isArray(item.source_windows)
          || !item.source_windows.length || item.source_windows.some(window => !range(window)
            || !Number.isInteger(window.index) || window.index < 0)
          || item.start !== Math.min(...item.source_windows.map(window => window.start))
          || item.end !== Math.max(...item.source_windows.map(window => window.end))) return null;
      batches.push(item);
    } else return null; // Text-only chunks retain their existing reader path.
  }
  if (!outlines.length) return null;
  outlines.sort((a, b) => a.start - b.start || a.id.localeCompare(b.id));
  batches.sort((a, b) => a.start - b.start || a.id.localeCompare(b.id));
  const unmatched = [];
  for (const batch of batches) {
    // Match actual source windows, not the gaps in a sparse batch's envelope.
    const matches = outlines.filter(outline => batch.source_windows.some(window => overlaps(window, outline)));
    const entry = { ...batch, spans: matches.length };
    (matches[0]?.batches || unmatched).push(entry);
  }
  return { identity: JSON.stringify([task.id, payload.attempt_id, payload.source_revision]),
    generation: payload.generation_revision, outlines, unmatched };
}

export function createSectionReader({ element, scroller, timestamp, renderMarkdown, decorate, openSource, asset }) {
  let identity = "", generation = "", shell = null, overflow = null;
  let outlines = new Map(), batches = new Map();
  const doc = element.ownerDocument;
  const make = (tag, text, className) => {
    const node = doc.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const time = (start, end) => `${timestamp(start)}–${timestamp(end)}`;
  function sourceButton(start, end) {
    const button = make("button", time(start, end), "time-link");
    button.type = "button";
    button.setAttribute("aria-label", `查看原文 ${time(start, end)}`);
    button.addEventListener("click", () => openSource(start));
    return button;
  }
  function clear() { identity = ""; generation = ""; shell = null; outlines = new Map(); batches = new Map(); }
  function sync(parent, desired) {
    desired.forEach((node, index) => {
      if (parent.children[index] !== node) parent.insertBefore(node, parent.children[index] || null);
    });
    for (const node of [...parent.children]) if (!desired.includes(node)) node.remove();
  }
  function render(payload, task, edition) {
    const plan = sectionPlan(payload, task, edition);
    if (!plan) { clear(); return false; }
    const same = identity === plan.identity && shell?.parentElement === element;
    const top = scroller?.scrollTop || 0;
    const viewport = scroller?.ownerDocument?.scrollingElement === scroller ? 0 : scroller?.getBoundingClientRect?.().top || 0;
    const candidates = same ? [...element.querySelectorAll("[data-reader-section], [data-reader-batch]")] : [];
    const selected = doc.getSelection?.()?.anchorNode;
    const anchor = candidates.findLast(node => selected && node.contains(selected))
      || candidates.findLast(node => node.getBoundingClientRect().top <= viewport)
      || candidates[0];
    const offset = anchor?.getBoundingClientRect().top;
    let changed = false;
    if (!same) {
      clear(); identity = plan.identity;
      shell = make("div", undefined, "progressive-reader");
      shell.dataset.progressiveReader = "true";
      shell.append(make("h1", task.title), make("p", "字幕阅读提纲 · 按原始时间分段，摘自字幕；不是 AI 主题总结。图文草稿按来源时间补入，仍需核对。", "muted"));
      const groups = make("div"); groups.dataset.readerGroups = "true";
      overflow = make("section"); overflow.dataset.readerUnmatched = "true";
      shell.append(groups, overflow); element.replaceChildren(shell); changed = true;
    }
    if (generation && generation !== plan.generation) {
      for (const entry of batches.values()) entry.node.remove();
      batches.clear(); changed = true;
    }
    generation = plan.generation;
    const liveOutlines = new Set(), liveBatches = new Set();
    function batchNode(item) {
      liveBatches.add(item.id);
      let entry = batches.get(item.id);
      if (!entry || entry.revision !== item.revision) {
        entry?.node.remove();
        const node = make("article", undefined, "progressive-visual");
        node.dataset.readerBatch = item.id;
        node.append(make("p", "图文草稿 · 证据补充中 · 未完成最终校验", "muted"));
        const provenance = make("p");
        provenance.append(make("span", item.spans > 1 ? "跨段批次，放在首个重叠段。来源：" : item.spans === 0 ? "未匹配字幕段。来源：" : "来源："));
        for (const window of item.source_windows) provenance.append(sourceButton(window.start, window.end), doc.createTextNode(" "));
        const body = make("div"); renderMarkdown(body, item.markdown); decorate(body, item.id);
        node.append(provenance, body);
        entry = { node, revision: item.revision, media: "", figures: null }; batches.set(item.id, entry); changed = true;
      }
      // Only exact time-matched, task-owned grids can supplement the batch.
      const grids = (task.frame_grids || []).concat((task.visual_windows || []).map(window => ({ ...window, url: window.grid_url })));
      const images = [...new Set(item.source_windows.flatMap(window => grids
        .filter(grid => grid.start === window.start && grid.end === window.end)
        .map(grid => asset(grid.url, task.id)).filter(Boolean)))];
      const media = JSON.stringify(images);
      if (entry.media !== media) {
        entry.figures?.remove(); entry.media = media;
        if (images.length) {
          const details = make("details"); details.append(make("summary", `查看来源画面（${images.length} 张网格）`));
          for (const url of images) {
            const image = make("img"); image.src = url; image.loading = "lazy";
            image.alt = `来源画面网格 ${time(item.start, item.end)}，用于人工核对`;
            details.append(image);
          }
          entry.node.append(details); entry.figures = details;
        } else entry.figures = null;
        changed = true;
      }
      return entry.node;
    }
    const groups = shell.querySelector("[data-reader-groups]");
    const desired = plan.outlines.map(item => {
      liveOutlines.add(item.id);
      let entry = outlines.get(item.id);
      if (!entry || entry.revision !== item.revision) {
        entry?.node.remove();
        const node = make("section", undefined, "progressive-source-section"); node.dataset.readerSection = item.id;
        const heading = make("h2", time(item.start, item.end)); heading.id = `reader-${item.id}`;
        const list = make("ul");
        for (const excerpt of item.excerpts) {
          const li = make("li"); li.append(sourceButton(excerpt.start, excerpt.end), doc.createTextNode(` ${excerpt.text}`)); list.append(li);
        }
        const target = make("div"); node.append(heading, list, target);
        entry = { node, target, revision: item.revision }; outlines.set(item.id, entry); changed = true;
      }
      sync(entry.target, item.batches.map(batchNode));
      return entry.node;
    });
    sync(groups, desired); sync(overflow, plan.unmatched.map(batchNode));
    for (const [id, entry] of outlines) if (!liveOutlines.has(id)) { entry.node.remove(); outlines.delete(id); changed = true; }
    for (const [id, entry] of batches) if (!liveBatches.has(id)) { entry.node.remove(); batches.delete(id); changed = true; }
    if (same && scroller) scroller.scrollTop = top + (anchor?.isConnected ? anchor.getBoundingClientRect().top - offset : 0);
    if (changed) doc.defaultView.dispatchEvent(new Event("learnnote:document"));
    return true;
  }
  return { render, clear };
}
