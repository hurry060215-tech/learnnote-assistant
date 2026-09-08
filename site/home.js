"use strict";
// These are educational examples, never a simulated live task.
function selectTab(button, panels) {
  const group = button.closest('[role="tablist"]');
  for (const tab of group.querySelectorAll('[role="tab"]')) {
    const selected = tab === button;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
  }
  for (const panel of panels)
    panel.hidden = panel.id !== button.getAttribute("aria-controls");
}
function installTabs(attribute, panels) {
  const tabs = [...document.querySelectorAll(`[${attribute}]`)];
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => selectTab(tab, panels));
    tab.addEventListener("keydown", (event) => {
      const directions = {
        ArrowRight: 1,
        ArrowLeft: -1,
        Home: -index,
        End: tabs.length - 1 - index,
      };
      if (!Object.hasOwn(directions, event.key)) return;
      event.preventDefault();
      const next =
        tabs[(index + directions[event.key] + tabs.length) % tabs.length];
      next.click();
      next.focus();
    });
  });
}
installTabs("data-demo", document.querySelectorAll(".sample-paper"));
installTabs("data-route", [
  document.getElementById("caption-route"),
  document.getElementById("transcription-route"),
]);
document.querySelectorAll("[data-open-source]").forEach((button) =>
  button.addEventListener("click", () => {
    const tab = document.getElementById("demo-source-tab");
    tab.click();
    tab.focus({ preventScroll: true });
  }),
);
document.querySelectorAll("[data-open-heading]").forEach((button) =>
  button.addEventListener("click", () => {
    const tab = document.getElementById("demo-note-tab");
    tab.click();
    tab.focus({ preventScroll: true });
  }),
);
