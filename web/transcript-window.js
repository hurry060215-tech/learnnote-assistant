/* Bounded transcript rendering with listeners scoped to one open source. */
export function createTranscriptWindow({ content, viewport, cues, timestamp, onRender, followEnabled = () => true, document: doc = document }) {
  const rowHeight = 72;
  let disposed = false, replacing = false, first = -1, last = -1, activeIndex = -1;
  let latestSeconds, renderedScrollTop, scrollVersion = 0;
  const focusedCue = () => {
    const cue = doc.activeElement?.closest?.("[data-cue-index]");
    return cue && viewport.contains(cue) ? cue : null;
  };
  function markCurrentCue() {
    for (const button of viewport.querySelectorAll(".cue")) {
      const active = Number(button.dataset.cueIndex) === activeIndex;
      button.classList.toggle("active", active);
      if (active) button.setAttribute("aria-current", "time");
      else button.removeAttribute("aria-current");
    }
  }
  function render(seconds, focusedIndex, { automatic = false } = {}) {
    if (disposed) return;
    if (Number.isFinite(seconds)) {
      latestSeconds = seconds;
      activeIndex = cues.findLastIndex(cue => Number(cue.start) <= seconds);
    }
    // Playback must not unmount a keyboard reader's cue or change their scroll.
    // Keep the latest time even with follow off so a later focusout can catch up.
    if (automatic && (!followEnabled() || focusedCue())) {
      markCurrentCue();
      return;
    }
    const index = Number.isInteger(focusedIndex) ? focusedIndex
      : Number.isFinite(seconds) ? activeIndex : -1;
    const height = Math.max(content.clientHeight, 280);
    if (index >= 0 && (index * rowHeight < content.scrollTop || (index + 1) * rowHeight > content.scrollTop + height)) {
      content.scrollTop = Math.max(0, index * rowHeight - 80);
    }
    const start = Math.min(Math.max(0, cues.length - 1), Math.max(0, Math.floor(content.scrollTop / rowHeight) - 8));
    const end = Math.min(cues.length, start + Math.ceil(height / rowHeight) + 16);
    if (start !== first || end !== last) {
      first = start; last = end;
      viewport.style.paddingTop = start * rowHeight + "px";
      viewport.style.paddingBottom = Math.max(0, cues.length - end) * rowHeight + "px";
      replacing = true;
      viewport.replaceChildren(...cues.slice(start, end).map((cue, offset) => {
        const button = doc.createElement("button");
        button.type = "button";
        button.className = "cue";
        button.dataset.time = String(Number(cue.start) || 0);
        button.dataset.cueIndex = String(start + offset);
        button.setAttribute("aria-label", `${start + offset + 1}/${cues.length} · ${timestamp(cue.start)} · ${String(cue.text || "")}`);
        const time = doc.createElement("small"); time.textContent = timestamp(cue.start);
        button.append(time, doc.createTextNode(String(cue.text || "")));
        return button;
      }));
      replacing = false;
      onRender([...viewport.querySelectorAll(".cue")]);
    }
    markCurrentCue();
    const current = index >= 0 ? viewport.querySelector(`[data-cue-index="${index}"]`) : null;
    if (current?.getClientRects().length) {
      const bounds = current.getBoundingClientRect(), panel = content.getBoundingClientRect();
      if (bounds.bottom > panel.bottom - 8 || bounds.top < panel.top + 8) {
        content.scrollTop += bounds.top - panel.top - 8;
      }
    }
    // Only an explicit navigation key requests focus, never playback or scrolling.
    if (Number.isInteger(focusedIndex)) viewport.querySelector(`[data-cue-index="${focusedIndex}"]`)?.focus();
    renderedScrollTop = content.scrollTop;
  }
  const onScroll = () => {
    // The deferred event for our own scroll/alignment has already been rendered.
    // Re-windowing it from estimated heights would remove a newly focused cue.
    if (content.scrollTop === renderedScrollTop) return;
    scrollVersion++;
    render();
  };
  const onFocusOut = () => {
    if (replacing || disposed) return;
    const version = scrollVersion;
    queueMicrotask(() => {
      if (!disposed && version === scrollVersion && !focusedCue() && followEnabled() && Number.isFinite(latestSeconds)) {
        render(latestSeconds, undefined, { automatic: true });
      }
    });
  };
  const onKeyDown = (event) => {
    const target = event.target.closest?.("[data-cue-index]");
    if (!target) return;
    const current = Number(target.dataset.cueIndex);
    const next = { ArrowDown: Math.min(cues.length - 1, current + 1), ArrowUp: Math.max(0, current - 1), Home: 0, End: cues.length - 1 }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    render(undefined, next);
  };
  content.addEventListener("scroll", onScroll, { passive: true });
  viewport.addEventListener("keydown", onKeyDown);
  viewport.addEventListener("focusout", onFocusOut);
  render();
  return {
    render,
    destroy() {
      disposed = true;
      content.removeEventListener("scroll", onScroll);
      viewport.removeEventListener("keydown", onKeyDown);
      viewport.removeEventListener("focusout", onFocusOut);
    },
  };
}
