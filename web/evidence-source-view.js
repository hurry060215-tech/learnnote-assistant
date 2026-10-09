/* Source identity comes from persisted task/window/evidence IDs, never a title. */
export function sourceWindow(source, seconds = 0, windowId = "") {
  if (source?.kind !== "task") return null;
  const windows = (source.visual_windows?.length ? source.visual_windows : (source.frame_grids || []).map((grid, index) => ({ ...grid, id: `grid:${index}`, grid_url: grid.url })));
  const valid = windows.filter(window => window.start != null && window.end != null && Number.isFinite(Number(window.start)) && Number.isFinite(Number(window.end)) && Number(window.start) >= 0 && Number(window.end) >= Number(window.start));
  if (windowId) { const matches = valid.filter(window => window.id === windowId); return matches.length === 1 ? matches[0] : null; }
  const time = Number(seconds);
  if (!Number.isFinite(time) || time < 0) return null;
  return valid.filter(window => Number(window.start) <= time && time <= Number(window.end)).sort((a, b) => Number(b.start) - Number(a.start))[0] || null;
}

export function createSourceWindowView({ container, source, asset, timestamp, onSeek }) {
  let rendered = "";
  return (seconds = 0, windowId = "") => {
    const window = sourceWindow(source, seconds, windowId);
    const url = window ? asset(window.grid_url, source.id) : "";
    if (!window || !url) {
      rendered = "";
      container.replaceChildren();
      container.hidden = !windowId;
      if (windowId) container.textContent = "引用的画面窗口暂不可用，请核对原视频。";
      return;
    }
    const key = `${window.id}:${url}`;
    container.hidden = false;
    if (rendered === key) return;
    rendered = key;
    const figure = document.createElement("figure"), image = document.createElement("img"), caption = document.createElement("figcaption"), seek = document.createElement("button");
    figure.dataset.windowId = window.id;
    image.src = url; image.loading = "lazy";
    image.alt = `原视频画面 ${timestamp(window.start)} – ${timestamp(window.end)}`;
    image.style.width = "100%"; image.style.maxHeight = "240px"; image.style.objectFit = "contain";
    seek.type = "button"; seek.textContent = `${timestamp(window.start)} – ${timestamp(window.end)} · 回看该画面`;
    seek.onclick = () => onSeek(Number(window.start));
    caption.append(seek, document.createTextNode(" · 原始画面，请与字幕核对"));
    figure.append(image, caption); container.replaceChildren(figure);
  };
}

const materialViews = new WeakMap();
export function renderMaterialSource(container, text, anchors) {
  container.replaceChildren();
  const excerpt = document.createElement("section"), label = document.createElement("strong"), original = document.createElement("pre");
  excerpt.hidden = true; label.textContent = "完整原文"; original.textContent = text;
  original.style.whiteSpace = "pre-wrap"; original.style.overflowWrap = "anywhere";
  container.append(excerpt, label, original);
  materialViews.set(container, { excerpt, anchors });
}

export function highlightMaterialSource(container, evidenceId) {
  const view = materialViews.get(container);
  if (!view) return false;
  const { excerpt, anchors } = view;
  const matches = anchors.filter(anchor => anchor.evidence_id === evidenceId);
  excerpt.replaceChildren(); excerpt.hidden = matches.length !== 1;
  if (matches.length !== 1) return false;
  const anchor = matches[0], label = document.createElement("strong"), body = document.createElement("pre");
  excerpt.dataset.evidenceId = anchor.evidence_id;
  excerpt.classList.add("source-evidence-target");
  label.textContent = `定位出处 · ${anchor.locator || "原文"}`; body.textContent = String(anchor.text || "");
  body.style.whiteSpace = "pre-wrap"; body.style.overflowWrap = "anywhere";
  excerpt.append(label, body); excerpt.scrollIntoView({ block: "center", behavior: "instant" });
  return true;
}
