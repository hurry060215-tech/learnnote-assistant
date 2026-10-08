/* Bounded transcript rendering with one scroll listener per open source. */
export function createTranscriptWindow({ content, viewport, cues, timestamp, onRender, document: doc = document }) {
  const rowHeight = 72;
  let disposed = false, first = -1, last = -1;
  function render(seconds, focusedIndex) {
    if (disposed) return [];
    const index = Number.isInteger(focusedIndex) ? focusedIndex
      : typeof seconds === "number" ? cues.findLastIndex(cue => Number(cue.start) <= seconds) : -1;
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
      onRender([...viewport.querySelectorAll(".cue")]);
    }
    if (Number.isInteger(focusedIndex)) viewport.querySelector(`[data-cue-index="${focusedIndex}"]`)?.focus();
  }
  const onScroll = () => render();
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
  render();
  return {
    render,
    destroy() {
      disposed = true;
      content.removeEventListener("scroll", onScroll);
      viewport.removeEventListener("keydown", onKeyDown);
    },
  };
}
