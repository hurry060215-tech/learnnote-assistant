// Shared navigation and dialog behavior, including unsaved-edit protection.
export function installInteractions({
  state,
  drawList,
  showHome,
  navigateBack,
}) {
  const $ = (id) => document.getElementById(id);
  const protectedForm = (element) =>
    element?.closest?.("#settingsForm,#courseForm,.annotation-edit");
  function markSaved(dialog) {
    if (dialog) delete dialog.dataset.unsaved;
  }
  function canLeave(dialog) {
    return (
      !dialog?.dataset.unsaved ||
      confirm("还有未保存的编辑。放弃这些修改并返回？")
    );
  }
  function dismiss(dialog) {
    if (!canLeave(dialog)) return;
    markSaved(dialog);
    const event = new Event("cancel", { cancelable: true });
    if (dialog.dispatchEvent(event)) dialog.close();
  }
  window.LearnNoteDialogs = { canLeave, markSaved, dismiss };
  let pressedOutside = null;
  document.addEventListener("pointerdown", (event) => {
    const d = event.target.closest?.("dialog");
    if (!d || event.target !== d) {
      pressedOutside = null;
      return;
    }
    const r = d.getBoundingClientRect();
    pressedOutside =
      event.clientX < r.left ||
      event.clientX > r.right ||
      event.clientY < r.top ||
      event.clientY > r.bottom
        ? d
        : null;
  });
  document.addEventListener(
    "click",
    (event) => {
      const d = event.target.closest?.("dialog");
      if (d && event.target === d && pressedOutside === d) {
        pressedOutside = null;
        dismiss(d);
        return;
      }
      const close = event.target.closest?.(
        "[data-close],[data-close-tool],#outlineDialog header button,.skill-catalog-dialog header button",
      );
      if (close && d && !canLeave(d)) {
        event.preventDefault();
        event.stopImmediatePropagation();
      } else if (close && d) markSaved(d);
    },
    true,
  );
  document.addEventListener("input", (event) => {
    if (protectedForm(event.target)) {
      const dialog = event.target.closest("dialog");
      if (dialog) dialog.dataset.unsaved = "true";
    }
  });
  document.addEventListener("change", (event) => {
    if (protectedForm(event.target)) {
      const dialog = event.target.closest("dialog");
      if (dialog) dialog.dataset.unsaved = "true";
    }
  });
  document.addEventListener(
    "cancel",
    (event) => {
      if (!canLeave(event.target)) event.preventDefault();
      else markSaved(event.target);
    },
    true,
  );
  document.addEventListener(
    "close",
    (event) => {
      if (event.target.tagName === "DIALOG") {
        markSaved(event.target);
        event.target.dispatchEvent(new Event("learnnote:dialog-closed"));
      }
    },
    true,
  );
  const back = document.createElement("button");
  back.id = "navigateBack";
  back.type = "button";
  back.setAttribute("aria-label", "返回上一个位置");
  back.title = "返回上一个位置";
  back.innerHTML =
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14 6-6 6 6 6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  document.querySelector(".toolbar").prepend(back);
  back.onclick = navigateBack;
  document.querySelector(".brand").onclick = (event) => {
    event.preventDefault();
    showHome();
  };
  const controls = document.createElement("div");
  controls.className = "library-controls";
  controls.innerHTML =
    '<label class="sr-only" for="librarySort">笔记排序</label><select id="librarySort"><option value="updated">最近更新</option><option value="title">按名称</option><option value="active">处理中优先</option></select><span id="libraryVisibleCount" aria-live="polite"></span>';
  document.querySelector(".list-heading").before(controls);
  try {
    state.pinned = new Set(
      JSON.parse(localStorage.getItem("learnnote.pinned") || "[]"),
    );
    state.listSort =
      localStorage.getItem("learnnote.library.sort") || "updated";
  } catch {
    state.pinned = new Set();
    state.listSort = "updated";
  }
  $("librarySort").value = state.listSort;
  $("librarySort").onchange = () => {
    state.listSort = $("librarySort").value;
    localStorage.setItem("learnnote.library.sort", state.listSort);
    drawList();
  };
  $("notes").addEventListener("click", (event) => {
    const button = event.target.closest("[data-pin]");
    if (!button) return;
    const key = button.dataset.pin;
    if (state.pinned.has(key)) state.pinned.delete(key);
    else state.pinned.add(key);
    localStorage.setItem("learnnote.pinned", JSON.stringify([...state.pinned]));
    drawList();
    [...$("notes").querySelectorAll("[data-pin]")]
      .find((el) => el.dataset.pin === key)
      ?.focus();
  });
  window.addEventListener("learnnote:navigation", () => {
    back.disabled = !(state.navigation || []).length;
  });
  back.disabled = true;
}
