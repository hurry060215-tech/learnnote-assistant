// The source stays in the reading column; resizing never recreates the player.
export function installLayout() {
  const $ = (id) => document.getElementById(id);
  const sidebar = $("sidebar"),
    assistant = $("assistantPanel"),
    source = $("sourcePanel");
  const preferred = { sidebar: 232, assistant: 430 };
  try {
    const saved = JSON.parse(
      localStorage.getItem("learnnote.layout.widths") || "{}",
    );
    for (const name of Object.keys(preferred))
      if (Number.isFinite(saved[name])) preferred[name] = saved[name];
  } catch {}
  const clamp = (n, min, max) => Math.round(Math.max(min, Math.min(n, max)));
  const desktop = () => innerWidth > 1100;
  const sidebarVisible = () =>
    !document.body.matches(".sidebar-collapsed,.focus-reading");
  const assistantVisible = () =>
    document.body.classList.contains("assistant-visible");
  const handles = {},
    widths = {},
    limits = {};
  function refresh() {
    const reserve = desktop() && assistantVisible();
    const sidebarMax = reserve ? Math.min(420, innerWidth - 320 - 420) : 420;
    widths.sidebar = clamp(preferred.sidebar, 200, sidebarMax);
    const left = sidebarVisible() ? widths.sidebar : 0;
    const assistantMax = Math.max(
      320,
      desktop()
        ? Math.min(720, innerWidth - left - 420)
        : Math.min(720, innerWidth - 24),
    );
    widths.assistant = clamp(preferred.assistant, 320, assistantMax);
    limits.sidebar = [200, sidebarMax];
    limits.assistant = [320, assistantMax];
    document.body.style.setProperty(
      "--sidebar-space",
      sidebarVisible() ? `${widths.sidebar}px` : "0px",
    );
    for (const name of Object.keys(widths)) {
      document.body.style.setProperty(`--${name}-width`, `${widths[name]}px`);
      const handle = handles[name];
      if (!handle) continue;
      handle.setAttribute("aria-valuenow", widths[name]);
      handle.setAttribute("aria-valuemin", limits[name][0]);
      handle.setAttribute("aria-valuemax", limits[name][1]);
      handle.setAttribute("aria-valuetext", `${widths[name]} 像素`);
    }
    const toolbar = document
      .querySelector(".toolbar")
      .getBoundingClientRect().height;
    const strip =
      document.querySelector(".reader-strip")?.getBoundingClientRect().height ||
      0;
    document.body.style.setProperty(
      "--source-sticky-top",
      `${toolbar + strip}px`,
    );
    const readingWidth =
      parseFloat(getComputedStyle($("document")).maxWidth) || 940;
    document.body.dataset.contentsFit = String(
      document.querySelector(".workspace").clientWidth >= readingWidth + 360,
    );
  }
  const save = () => {
    try {
      localStorage.setItem(
        "learnnote.layout.widths",
        JSON.stringify(preferred),
      );
    } catch {}
  };
  function setWidth(name, value) {
    preferred[name] = clamp(value, ...limits[name]);
    refresh();
  }
  for (const [name, panel, label] of [
    ["sidebar", sidebar, "调整笔记侧栏宽度"],
    ["assistant", assistant, "调整助手侧栏宽度"],
  ]) {
    const handle = document.createElement("div");
    handle.id = `${name}Resize`;
    handle.className = "panel-resize";
    handle.tabIndex = 0;
    handle.setAttribute("role", "separator");
    handle.setAttribute("aria-orientation", "vertical");
    handle.setAttribute("aria-label", label);
    handle.setAttribute("aria-controls", panel.id);
    handle.title = `${label} · 拖动或使用左右方向键，双击恢复`;
    handles[name] = handle;
    panel.append(handle);
    let drag;
    handle.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      handle.focus();
      handle.setPointerCapture(event.pointerId);
      drag = { x: event.clientX, width: widths[name] };
      document.body.classList.add("resizing-panel");
    });
    handle.addEventListener("pointermove", (event) => {
      if (drag)
        setWidth(
          name,
          drag.width + (event.clientX - drag.x) * (name === "sidebar" ? 1 : -1),
        );
    });
    const end = () => {
      if (!drag) return;
      drag = null;
      document.body.classList.remove("resizing-panel");
      save();
    };
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
    handle.addEventListener("lostpointercapture", end);
    handle.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
        return;
      event.preventDefault();
      const delta =
        (event.key === "ArrowRight" ? 16 : -16) * (name === "sidebar" ? 1 : -1);
      setWidth(
        name,
        event.key === "Home"
          ? limits[name][0]
          : event.key === "End"
            ? limits[name][1]
            : widths[name] + delta,
      );
      save();
    });
    handle.addEventListener("dblclick", () => {
      setWidth(name, name === "sidebar" ? 232 : 430);
      save();
    });
  }
  $("document").before(source);
  const header = source.querySelector("header"),
    player = $("player");
  const pin = document.createElement("button");
  pin.id = "pinSource";
  pin.type = "button";
  pin.setAttribute("aria-pressed", "false");
  $("closeSource").before(pin);
  const transcript = document.createElement("details");
  transcript.id = "sourceTranscript";
  transcript.innerHTML = "<summary>查看原始字幕</summary>";
  transcript.append($("sourceContent"));
  source.append(transcript);
  header.after(player);
  let pinned = false;
  try {
    pinned = localStorage.getItem("learnnote.source.pinned") === "true";
  } catch {}
  function updateSource() {
    const hasVideo = !player.hidden && Boolean(player.getAttribute("src"));
    pin.hidden = !hasVideo;
    pin.textContent = pinned ? "取消固定" : "固定视频";
    pin.title = pinned ? "让视频随笔记滚动" : "阅读笔记时将视频固定在上方";
    pin.setAttribute("aria-pressed", String(pinned));
    source.classList.toggle("source-pinned", pinned && hasVideo);
    source.querySelector(".playback-controls").hidden = !hasVideo;
    header.querySelector("strong").textContent = hasVideo
      ? "原始视频"
      : "原始来源";
    refresh();
  }
  pin.onclick = () => {
    pinned = !pinned;
    try {
      localStorage.setItem("learnnote.source.pinned", String(pinned));
    } catch {}
    updateSource();
  };
  new MutationObserver(updateSource).observe(player, {
    attributes: true,
    attributeFilter: ["hidden", "src"],
  });
  new MutationObserver(refresh).observe(document.body, {
    attributes: true,
    attributeFilter: ["class"],
  });
  const resizeObserver = new ResizeObserver(refresh);
  resizeObserver.observe(document.querySelector(".toolbar"));
  const strip = document.querySelector(".reader-strip");
  if (strip) resizeObserver.observe(strip);
  window.addEventListener("resize", refresh);
  window.addEventListener("learnnote:settings", refresh);
  window.LearnNoteLayout = { refresh, updateSource };
  updateSource();
}
