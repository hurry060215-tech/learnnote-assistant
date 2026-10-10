const OUTLINE_DEFAULTS = { width: 540, size: 14, gap: 4 };
const clamp = (value, min, max) => Math.max(min, Math.min(Number(value), max));

export function normalizeOutline(value = {}) {
  return Object.fromEntries(Object.entries(OUTLINE_DEFAULTS).map(([key, fallback]) => [
    key, Number.isFinite(Number(value?.[key]))
      ? Math.round(clamp(value[key], ...({ width: [280, 980], size: [12, 20], gap: [0, 16] }[key])))
      : fallback,
  ]));
}

// The native dialog keeps its focus trap, backdrop and arrival transition.
export function createOutlineControls(dialog) {
  let preferences;
  try { preferences = normalizeOutline(JSON.parse(localStorage.getItem("learnnote.outline.preferences") || "{}")); }
  catch { preferences = { ...OUTLINE_DEFAULTS }; }
  let handle, dragging;
  const bounds = () => [Math.min(280, innerWidth - 28), Math.min(980, innerWidth - 28)];
  const save = () => {
    try { localStorage.setItem("learnnote.outline.preferences", JSON.stringify(preferences)); } catch {}
  };
  const refresh = () => {
    const [min, max] = bounds(), width = Math.round(clamp(preferences.width, min, max));
    dialog.style.width = `${width}px`;
    dialog.style.setProperty("--outline-size", `${preferences.size}px`);
    dialog.style.setProperty("--outline-gap", `${preferences.gap}px`);
    dialog.style.setProperty("--outline-padding", `${4 + preferences.gap / 2}px`);
    if (handle) {
      for (const [key, value] of Object.entries({ now: width, min, max }))
        handle.setAttribute(`aria-value${key}`, value);
      handle.setAttribute("aria-valuetext", `${width} 像素`);
    }
  };
  const stop = () => {
    if (!dragging) return;
    dragging = null;
    document.body.classList.remove("resizing-outline");
    save();
  };
  window.addEventListener("resize", refresh);
  dialog.addEventListener("close", stop);
  return {
    mount() {
      stop();
      const controls = document.createElement("details");
      controls.className = "outline-settings";
      controls.innerHTML = '<summary>目录设置</summary><div><label for="outlineSize">字号 <output id="outlineSizeValue"></output></label><input id="outlineSize" type="range" min="12" max="20" step="1"><label for="outlineGap">条目间距 <output id="outlineGapValue"></output></label><input id="outlineGap" type="range" min="0" max="16" step="1"><button type="button" id="resetOutline">恢复默认</button></div>';
      dialog.querySelector(".outline-tree").before(controls);
      for (const [id, key] of [["outlineSize", "size"], ["outlineGap", "gap"]]) {
        const input = controls.querySelector(`#${id}`), output = controls.querySelector(`#${id}Value`);
        input.value = preferences[key];
        output.textContent = `${preferences[key]} px`;
        input.oninput = () => {
          preferences = normalizeOutline({ ...preferences, [key]: input.value });
          output.textContent = `${preferences[key]} px`;
          refresh(); save();
        };
      }
      controls.querySelector("#resetOutline").onclick = () => {
        preferences = { ...OUTLINE_DEFAULTS };
        for (const [id, key] of [["outlineSize", "size"], ["outlineGap", "gap"]]) {
          controls.querySelector(`#${id}`).value = preferences[key];
          controls.querySelector(`#${id}Value`).textContent = `${preferences[key]} px`;
        }
        refresh(); save();
      };
      handle = document.createElement("div");
      handle.id = "outlineResize";
      handle.tabIndex = 0;
      handle.setAttribute("role", "separator");
      handle.setAttribute("aria-label", "调整目录宽度");
      handle.setAttribute("aria-orientation", "vertical");
      handle.setAttribute("aria-controls", dialog.id);
      handle.title = "拖动调整目录宽度；也可使用左右方向键，双击恢复宽度";
      dialog.append(handle);
      handle.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        handle.focus();
        handle.setPointerCapture(event.pointerId);
        dragging = { x: event.clientX, width: dialog.getBoundingClientRect().width };
        document.body.classList.add("resizing-outline");
      });
      handle.addEventListener("pointermove", (event) => {
        if (!dragging) return;
        // A centered dialog grows on both sides; keep its right edge under the pointer.
        preferences.width = clamp(dragging.width + 2 * (event.clientX - dragging.x), ...bounds());
        refresh();
      });
      for (const event of ["pointerup", "pointercancel", "lostpointercapture"])
        handle.addEventListener(event, stop);
      handle.addEventListener("keydown", (event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const [min, max] = bounds();
        preferences.width = event.key === "Home" ? min : event.key === "End" ? max
          : clamp(Number(handle.getAttribute("aria-valuenow")) + (event.key === "ArrowRight" ? 24 : -24), min, max);
        refresh(); save();
      });
      handle.addEventListener("dblclick", () => { preferences.width = OUTLINE_DEFAULTS.width; refresh(); save(); });
      refresh();
    },
  };
}

export function formatNoteText(text, start, end, kind) {
  if (kind === "bold") {
    const selection = text.slice(start, end) || "重点文字";
    const replacement = selection.startsWith("**") && selection.endsWith("**") && selection.length > 4
      ? selection.slice(2, -2) : `**${selection}**`;
    return { text: text.slice(0, start) + replacement + text.slice(end), start, end: start + replacement.length };
  }
  const first = start === 0 ? 0 : text.lastIndexOf("\n", start - 1) + 1;
  const last = text.indexOf("\n", Math.max(start, end - 1));
  const tail = last < 0 ? text.length : last;
  const lines = text.slice(first, tail).split("\n");
  const prefix = kind === "heading" ? "## " : "- ";
  const remove = lines.every(line => !line.trim() || line.startsWith(prefix));
  const replacement = lines.map(line => !line.trim() && lines.length > 1 ? line
    : remove ? line.slice(prefix.length) : prefix + line.replace(kind === "heading" ? /^#{1,6}\s+/ : /^[-*+]\s+/, "")).join("\n");
  return { text: text.slice(0, first) + replacement + text.slice(tail), start: first, end: first + replacement.length };
}

export function installNoteEditor({ state, $, saveNote, renderNote, renderMarkdown, guard, notice }) {
  const textarea = $("noteText"), preview = $("notePreview");
  let saving = false;
  const previewMode = (on) => {
    textarea.hidden = on;
    preview.hidden = !on;
    $("toggleNotePreview").setAttribute("aria-pressed", String(on));
    $("toggleNotePreview").textContent = on ? "返回编辑" : "预览排版";
    if (on) preview.innerHTML = renderMarkdown(textarea.value);
  };
  $("edit").onclick = () => {
    if (!state.selected) return;
    if (!state.editing) {
      state.editing = true;
      textarea.value = state.text;
      $("saveStatus").textContent = "修改独立保存，原始生成稿会保留。";
      $("document").hidden = true;
      $("editor").hidden = false;
    }
    previewMode(false);
    textarea.focus();
  };
  $("discard").onclick = () => {
    if (saving || !guard()) return;
    state.editing = false;
    renderNote();
    previewMode(false);
    $("editor").hidden = true;
    $("document").hidden = false;
  };
  $("save").onclick = async () => {
    if (saving || !state.editing || !state.selected) return;
    const selected = state.selected, epoch = state.epoch, submitted = textarea.value;
    saving = true;
    $("save").disabled = $("discard").disabled = true;
    $("saveStatus").textContent = "正在保存修改…";
    const current = () => epoch === state.epoch && selected.id === state.selected?.id && selected.kind === state.selected?.kind;
    try {
      const result = await saveNote(selected, { text: submitted, revision: state.revision });
      if (!current()) return;
      state.text = result.text;
      state.revision = result.revision;
      state.edition = result;
      if (textarea.value !== submitted) {
        $("saveStatus").textContent = "上一份修改已保存；新输入的内容仍待保存。";
        return;
      }
      state.editing = false;
      renderNote();
      previewMode(false);
      $("editor").hidden = true;
      $("document").hidden = false;
      notice("修改已保存，原始生成稿仍保留。");
    } catch (error) {
      if (current()) $("saveStatus").textContent = error.message;
    } finally {
      saving = false;
      $("save").disabled = $("discard").disabled = false;
    }
  };
  for (const [id, kind] of [["noteHeading", "heading"], ["noteBold", "bold"], ["noteList", "list"]])
    $(id).onclick = () => {
      const result = formatNoteText(textarea.value, textarea.selectionStart, textarea.selectionEnd, kind);
      textarea.value = result.text;
      previewMode(false);
      textarea.focus();
      textarea.setSelectionRange(result.start, result.end);
    };
  $("toggleNotePreview").onclick = () => { previewMode(preview.hidden); if (preview.hidden) textarea.focus(); };
}
