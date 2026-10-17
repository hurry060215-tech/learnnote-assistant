/* One explicit viewport snapshot. No listeners, timers, network, or page-world access. */
(function (root) {
  "use strict";
  const LIMITS = Object.freeze({ items: 20, itemCharacters: 2000, characters: 20000, nodes: 1500, depth: 60 });
  const parent = node => node?.parentElement || node?.getRootNode?.()?.host || null;
  function ancestor(node, selector) {
    for (let depth = 0; node && depth < LIMITS.depth; depth++, node = parent(node)) if (node.matches?.(selector)) return node;
    return null;
  }
  function visible(node, view, timestampOnly = false) {
    try {
      let rect = node.getBoundingClientRect();
      const own = rect;
      if (!(rect.width > 0 && rect.height > 0)) return false;
      let left = Math.max(0, rect.left), top = Math.max(0, rect.top);
      let right = Math.min(view.innerWidth, rect.right), bottom = Math.min(view.innerHeight, rect.bottom);
      let current = node, depth = 0;
      for (; current && depth < LIMITS.depth; depth++, current = parent(current)) {
        const style = view.getComputedStyle(current);
        if (current.hidden || current.getAttribute("aria-hidden") === "true" || current.hasAttribute("inert") || style.display === "none" || ["hidden", "collapse"].includes(style.visibility) || Number(style.opacity) === 0) return false;
        if (current.matches("details:not([open])") && !node.closest("summary")) return false;
        rect = current.getBoundingClientRect();
        if (/(hidden|clip|scroll|auto)/.test(style.overflowX)) { left = Math.max(left, rect.left); right = Math.min(right, rect.right); }
        if (/(hidden|clip|scroll|auto)/.test(style.overflowY)) { top = Math.max(top, rect.top); bottom = Math.min(bottom, rect.bottom); }
      }
      if (current || right <= left || bottom <= top || left > own.left + 0.5 || top > own.top + 0.5 || right < own.right - 0.5 || bottom < own.bottom - 0.5) return false;
      const points = [[(left + right) / 2, (top + bottom) / 2], [left + .5, top + .5], [right - .5, top + .5], [left + .5, bottom - .5], [right - .5, bottom - .5]];
      return points.every(([x, y]) => {
        if (timestampOnly) {
          const hit = view.document.elementsFromPoint(x, y)[0];
          return node === hit || node.contains(hit);
        }
        let hit = view.document.elementFromPoint(x, y);
        for (let depth = 0; hit?.shadowRoot?.elementFromPoint && depth < LIMITS.depth; depth++) {
          const inner = hit.shadowRoot.elementFromPoint(x, y); if (!inner || inner === hit) break; hit = inner;
        }
        if (node === hit || node.contains(hit)) return true;
        // Hit-testing may retarget open shadow content to its host.
        for (let ancestor = parent(node), depth = 0; ancestor && depth < LIMITS.depth; depth++, ancestor = parent(ancestor)) if (ancestor === hit && ancestor.shadowRoot) return true;
        return false;
      });
    } catch { return false; }
  }
  function contentKind(node) {
    if (node.matches(".reply-item .reply-content,.reply-item .sub-reply-content,.reply-wrap .reply-content")) return "comment";
    if (node.id === "contents" && node.getRootNode()?.host?.matches("bili-rich-text") && ancestor(parent(node), "bili-comment-renderer,bili-comment-reply-renderer")) return "comment";
    if (node.matches(".bili-dm") && ancestor(parent(node), ".bpx-player-dm-wrap")) return "danmaku";
    if (node.matches(".b-danmaku") && ancestor(parent(node), ".bilibili-player-video-danmaku")) return "danmaku";
    if (node.matches(".bpx-player-dm-list-dm") && ancestor(parent(node), ".bpx-player-dm-list-item")) return "danmaku";
    return "";
  }
  function textOnly(node, view, budget) {
    const parts = [], stack = [{ node, depth: 0 }];
    let size = 0;
    while (stack.length && budget.remaining > 0) {
      const { node: current, depth } = stack.pop(); budget.remaining--;
      if (depth > LIMITS.depth) return "";
      if (current.nodeType === 3) {
        const value = String(current.nodeValue || ""); size += value.length;
        if (size > LIMITS.itemCharacters) return "";
        parts.push(value); continue;
      }
      if (current.nodeType !== 1 || current.matches("script,style,button,input,textarea,select,[role=button],[hidden],.user-name,.user-info,.reply-info") || !visible(current, view)) continue;
      const children = current.childNodes;
      if (children.length > budget.remaining) return "";
      for (let i = children.length - 1; i >= 0; i--) stack.push({ node: children[i], depth: depth + 1 });
    }
    return stack.length ? "" : parts.join(" ").replace(/\s+/g, " ").trim();
  }
  function timestamp(node, view) {
    const row = node.closest(".bpx-player-dm-list-item");
    const time = row?.querySelector(".bpx-player-dm-list-time");
    if (!time || !visible(time, view, true)) return null;
    const match = /^(?:(\d{1,2}):)?([0-5]?\d):([0-5]\d)$/.exec(time.innerText.trim());
    return match ? Number(match[1] || 0) * 3600 + Number(match[2]) * 60 + Number(match[3]) : null;
  }
  function collect({ document, view, pageUrl, expectedPageUrl }) {
    const canonical = root.LearnNoteCommunitySource?.canonicalPage(pageUrl);
    if (!canonical || canonical !== root.LearnNoteCommunitySource.canonicalPage(expectedPageUrl)) throw Error("community_source_changed");
    const items = [], stack = [{ node: document.documentElement, depth: 0 }], budget = { remaining: LIMITS.nodes };
    let characters = 0, limited = false;
    while (stack.length && budget.remaining > 0 && items.length < LIMITS.items) {
      const { node, depth } = stack.pop(); budget.remaining--;
      if (!node || depth > LIMITS.depth || node.nodeType !== 1 || node.matches("script,style,iframe,template,input,textarea,select,button")) continue;
      const kind = contentKind(node);
      if (kind) {
        if (visible(node, view)) {
          const text = textOnly(node, view, budget);
          if (text && characters + text.length <= LIMITS.characters) {
            items.push({ kind, text, timestamp_seconds: kind === "danmaku" ? timestamp(node, view) : null }); characters += text.length;
          }
        }
        continue;
      }
      // Traverse ordinary and open shadow DOM only; reject rather than truncate a huge sibling set.
      const children = node.shadowRoot ? node.shadowRoot.children : node.children;
      if (children.length > budget.remaining) { limited = true; continue; }
      for (let i = children.length - 1; i >= 0; i--) stack.push({ node: children[i], depth: depth + 1 });
    }
    return { page_url: canonical, items, truncated: limited || Boolean(stack.length), scope: "visible_viewport_snapshot", limits: LIMITS };
  }
  root.LearnNoteCommunityDOM = Object.freeze({ collect, visible, limits: LIMITS });
})(globalThis);
